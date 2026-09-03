from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from PhyAgentOS.agent.context import ContextBuilder
from PhyAgentOS.agent.session_verifier import ForgeTaskVerifier, VerificationVerdictError
from PhyAgentOS.forge.evidence import ForgeEvidenceWriter
from PhyAgentOS.forge.observation import CapturedImage, CapturedState, ObservationSnapshot
from PhyAgentOS.forge.task import (
    AgentTaskError,
    AgentTaskOriginConflictError,
    AgentTaskRecord,
    AgentTaskStatus,
    AgentTaskStore,
    PlanRevision,
    ToolExecutionRecord,
)
from PhyAgentOS.state_io import render_environment_projection
from PhyAgentOS.verification.contracts import (
    VerificationEvidencePolicy,
    derive_evidence_bundle_id,
)
from PhyAgentOS.verification.request_builder import (
    VerificationEvidenceError,
    VerificationRequestBuilder,
)

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def _task(
    task_id: str,
    *,
    origin_session_key: str | None = None,
    origin_dedup_key: str | None = None,
) -> AgentTaskRecord:
    revision_id = f"revision_{task_id}"
    return AgentTaskRecord(
        task_id=task_id,
        task_description="authority-boundary test",
        status=AgentTaskStatus.SUCCEEDED,
        revisions=[PlanRevision(revision_id=revision_id, number=1, reason="test")],
        active_revision_id=revision_id,
        origin_session_key=origin_session_key,
        origin_dedup_key=origin_dedup_key,
    )


def _snapshot(*, sequence: int, payload: bytes) -> ObservationSnapshot:
    image = CapturedImage(
        source_id="camera/front",
        sequence=sequence,
        captured_at=NOW.timestamp(),
        received_at=NOW,
        media_type="image/png",
        data=payload,
    )
    return ObservationSnapshot(
        captured_at=NOW,
        images={"camera/front": image},
        state=CapturedState(received_at=NOW, payload={"sequence": sequence}),
    )


def _complete_bundle(writer: ForgeEvidenceWriter):
    before_ref = writer.write_snapshot(
        "before", _snapshot(sequence=1, payload=b"\x89PNG\r\n\x1a\nbefore")
    )
    after_ref = writer.write_snapshot(
        "after", _snapshot(sequence=2, payload=b"\x89PNG\r\n\x1a\nafter")
    )
    return writer.write_bundle(
        before_ref=before_ref,
        after_ref=after_ref,
        terminal_observed_at=NOW,
        required_sources=["camera/front"],
        required_kinds=["rgb_image", "robot_state"],
        errors=[],
    )


def test_agent_task_store_migrates_legacy_schema_and_is_reentrant(tmp_path):
    database_dir = tmp_path / ".paos" / "agent_tasks"
    database_dir.mkdir(parents=True)
    database = database_dir / "tasks.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE agent_tasks ("
            "task_id TEXT PRIMARY KEY, status TEXT NOT NULL, record_json TEXT NOT NULL, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        legacy = _task(
            "task_legacy",
            origin_session_key="chat://legacy-session",
        )
        connection.execute(
            "INSERT INTO agent_tasks(task_id, status, record_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                legacy.task_id,
                legacy.status.value,
                legacy.model_dump_json(),
                legacy.created_at.isoformat(),
                legacy.updated_at.isoformat(),
            ),
        )

    store = AgentTaskStore(tmp_path)
    AgentTaskStore(tmp_path)

    with sqlite3.connect(database) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(agent_tasks)")
        }
        indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(agent_tasks)")
        }
    assert {"origin_session_key", "origin_dedup_key"} <= columns
    assert "agent_tasks_origin_dedup_key_uq" in indexes
    assert [
        task.task_id
        for task in store.find_by_origin_session_key("chat://legacy-session")
    ] == ["task_legacy"]
    assert store.find_by_origin_dedup_key("chat://legacy-session") == []


def test_origin_dedup_is_transactional_without_making_chat_session_unique(tmp_path):
    store = AgentTaskStore(tmp_path)
    store.create(
        _task(
            "task_one",
            origin_session_key="chat://same-session",
            origin_dedup_key="declaration://one",
        )
    )
    store.create(
        _task(
            "task_two",
            origin_session_key="chat://same-session",
            origin_dedup_key="declaration://two",
        )
    )
    assert len(store.find_by_origin_session_key("chat://same-session")) == 2

    second_store = AgentTaskStore(tmp_path)
    with pytest.raises(AgentTaskOriginConflictError, match="declaration://one"):
        second_store.create(
            _task(
                "task_duplicate",
                origin_session_key="chat://other-session",
                origin_dedup_key="declaration://one",
            )
        )


def test_origin_dedup_conflict_is_serialized_across_store_instances(tmp_path):
    stores = [AgentTaskStore(tmp_path), AgentTaskStore(tmp_path)]
    barrier = threading.Barrier(2)

    def create(index: int):
        barrier.wait(timeout=2.0)
        try:
            stores[index].create(
                _task(
                    f"task_concurrent_{index}",
                    origin_session_key=f"chat://session-{index}",
                    origin_dedup_key="declaration://same",
                )
            )
            return "created"
        except AgentTaskOriginConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(create, range(2)))

    assert outcomes == ["conflict", "created"]
    assert len(stores[0].find_by_origin_dedup_key("declaration://same")) == 1


def test_agent_task_origin_cannot_change_during_store_update(tmp_path):
    store = AgentTaskStore(tmp_path)
    store.create(
        _task(
            "task_one",
            origin_session_key="chat://session",
            origin_dedup_key="declaration://one",
        )
    )
    with pytest.raises(AgentTaskError, match="origin is immutable"):
        store.update(
            "task_one",
            lambda task: setattr(task, "origin_dedup_key", "declaration://changed"),
            event_type="invalid_origin_change",
        )
    assert store.get("task_one").origin_dedup_key == "declaration://one"


def test_agent_task_store_revalidates_mutated_aggregate_before_commit(tmp_path):
    store = AgentTaskStore(tmp_path)
    store.create(_task("task_invalid_mutation"))

    with pytest.raises(AgentTaskError, match="authoritative record schema"):
        store.update(
            "task_invalid_mutation",
            lambda task: setattr(task, "task_description", ""),
            event_type="invalid_task_mutation",
        )

    assert store.get("task_invalid_mutation").task_description == "authority-boundary test"
    assert store.events("task_invalid_mutation")[-1]["event_type"] == "task_created"


def test_agent_task_store_revalidates_aggregate_before_create(tmp_path):
    store = AgentTaskStore(tmp_path)
    task = _task("task_invalid_create")
    task.task_description = ""

    with pytest.raises(AgentTaskError, match="creation violates"):
        store.create(task)

    with pytest.raises(AgentTaskError, match="not found"):
        store.get("task_invalid_create")


def test_agent_task_store_rejects_task_identity_mutation(tmp_path):
    store = AgentTaskStore(tmp_path)
    store.create(_task("task_identity"))

    with pytest.raises(AgentTaskError, match="identity is immutable"):
        store.update(
            "task_identity",
            lambda task: setattr(task, "task_id", "task_rewritten"),
            event_type="invalid_identity_change",
        )

    assert store.get("task_identity").task_id == "task_identity"
    with pytest.raises(AgentTaskError, match="not found"):
        store.get("task_rewritten")
    assert store.events("task_identity")[-1]["event_type"] == "task_created"


def test_agent_task_store_rejects_created_at_mutation(tmp_path):
    store = AgentTaskStore(tmp_path)
    store.create(_task("task_created_at"))

    with pytest.raises(AgentTaskError, match="identity is immutable"):
        store.update(
            "task_created_at",
            lambda task: setattr(task, "created_at", NOW.replace(year=2025)),
            event_type="invalid_created_at_change",
        )

    assert store.get("task_created_at").created_at != NOW.replace(year=2025)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda task: setattr(task, "active_revision_id", "missing_revision"),
        lambda task: task.revisions.append(task.revisions[0].model_copy(deep=True)),
        lambda task: task.active_revision.execution_records.append(
            ToolExecutionRecord(
                record_id="record_wrong_revision",
                revision_id="another_revision",
                tool_id="scene.observe",
                semantics="query",
                caller_id="test",
            )
        ),
    ],
)
def test_agent_task_store_rejects_broken_aggregate_relationships(tmp_path, mutate):
    store = AgentTaskStore(tmp_path)
    store.create(_task("task_relationships"))

    with pytest.raises(AgentTaskError, match="authoritative record schema"):
        store.update(
            "task_relationships",
            mutate,
            event_type="invalid_relationship_change",
        )

    assert store.events("task_relationships")[-1]["event_type"] == "task_created"


def test_agent_task_store_rejects_nonfinite_execution_payload(tmp_path):
    store = AgentTaskStore(tmp_path)
    store.create(_task("task_nonfinite"))

    def mutate(task):
        execution = ToolExecutionRecord(
            record_id="record_nonfinite",
            revision_id=task.active_revision_id,
            tool_id="scene.observe",
            semantics="query",
            caller_id="test",
        )
        execution.arguments["value"] = float("nan")
        task.active_revision.execution_records.append(execution)

    with pytest.raises(AgentTaskError, match="authoritative record schema"):
        store.update(
            "task_nonfinite",
            mutate,
            event_type="invalid_nonfinite_payload",
        )

    assert store.events("task_nonfinite")[-1]["event_type"] == "task_created"


def test_agent_task_store_rejects_nonfinite_event_payload(tmp_path):
    store = AgentTaskStore(tmp_path)
    store.create(_task("task_event_nonfinite"))

    with pytest.raises(AgentTaskError, match="event payload"):
        store.update(
            "task_event_nonfinite",
            lambda _task: None,
            event_type="invalid_event_payload",
            payload={"value": float("inf")},
        )

    assert store.events("task_event_nonfinite")[-1]["event_type"] == "task_created"


@pytest.mark.parametrize("field", ["version", "uri", "sha256", "byte_size"])
def test_snapshot_manifest_tampering_fails_closed(tmp_path, field):
    writer = ForgeEvidenceWriter(tmp_path, "task_manifest", "agent_task")
    reference = writer.write_snapshot(
        "before", _snapshot(sequence=1, payload=b"\x89PNG\r\n\x1a\nbefore")
    )
    manifest_path = tmp_path / reference
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if field == "version":
        manifest[field] = "forge_observation_snapshot_v1"
    elif field == "uri":
        manifest["entries"][0][field] = "ENVIRONMENT.md"
    elif field == "sha256":
        manifest["entries"][0][field] = "0" * 64
    else:
        manifest["entries"][0][field] += 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError):
        writer.load_snapshot(reference)


def test_snapshot_validation_happens_before_artifact_writes(tmp_path):
    writer = ForgeEvidenceWriter(tmp_path, "task_invalid", "agent_task")
    image = CapturedImage(
        source_id="camera/front",
        sequence=1,
        captured_at=NOW.timestamp(),
        received_at=NOW,
        media_type="application/octet-stream",
        data=b"invalid",
    )
    snapshot = ObservationSnapshot(
        captured_at=NOW,
        images={"camera/front": image},
    )

    with pytest.raises(ValueError):
        writer.write_snapshot("before", snapshot)

    assert not writer.artifact_dir.exists()


def test_snapshot_rejects_non_standard_robot_state_json_before_writes(tmp_path):
    writer = ForgeEvidenceWriter(tmp_path, "task_non_finite", "agent_task")
    snapshot = ObservationSnapshot(
        captured_at=NOW,
        state=CapturedState(
            received_at=NOW,
            payload={"joint_position": float("nan")},
        ),
    )

    with pytest.raises(ValueError, match="Out of range float values"):
        writer.write_snapshot("before", snapshot)

    assert not writer.artifact_dir.exists()


def test_evidence_bundle_is_idempotent_drift_rejecting_and_retention_stable(tmp_path):
    writer = ForgeEvidenceWriter(tmp_path, "task_bundle", "agent_task")
    first, reference = _complete_bundle(writer)
    second, second_reference = _complete_bundle(writer)
    assert second_reference == reference
    assert second.bundle_id == first.bundle_id

    retained_copy = first.model_copy(deep=True)
    retained_copy.artifacts[0].retained = False
    retained_copy.artifacts[0].deleted_at = NOW
    assert derive_evidence_bundle_id(retained_copy) == first.bundle_id

    with pytest.raises(ValueError, match="different content"):
        writer.write_bundle(
            before_ref=str(
                writer.artifact_dir.relative_to(tmp_path) / "before_snapshot.json"
            ),
            after_ref=str(writer.artifact_dir.relative_to(tmp_path) / "after_snapshot.json"),
            terminal_observed_at=NOW.replace(minute=1),
            required_sources=["camera/front"],
            required_kinds=["rgb_image", "robot_state"],
            errors=[],
        )


def test_agent_task_bundle_identity_mismatch_is_rejected_before_verification(tmp_path):
    writer = ForgeEvidenceWriter(
        tmp_path, "task_request", "agent_task", artifact_namespace="agent_tasks"
    )
    bundle, reference = _complete_bundle(writer)
    revision_id = "revision_request"
    task = AgentTaskRecord(
        task_id="task_request",
        task_description="verify bundle identity",
        revisions=[
            PlanRevision(
                revision_id=revision_id,
                number=1,
                reason="test",
                execution_records=[
                    ToolExecutionRecord(
                        record_id="record_request",
                        revision_id=revision_id,
                        tool_id="scene.observe",
                        semantics="query",
                        caller_id="test",
                        status="succeeded",
                    )
                ],
            )
        ],
        active_revision_id=revision_id,
        evidence_bundle_ref=reference,
        evidence_bundle_id="forge_evidence_wrong",
    )
    assert bundle.bundle_id != task.evidence_bundle_id

    with pytest.raises(VerificationEvidenceError, match="does not match AgentTask record"):
        VerificationRequestBuilder(tmp_path).build_agent_task(
            task,
            events=[],
            lessons="",
        )


def test_environment_prompt_contains_identity_only_and_stable_failure_code(tmp_path):
    render_environment_projection(
        tmp_path / "ENVIRONMENT.md",
        {
            "schema_version": "paos.environment.v1",
            "scene_revision": "scene-1",
            "snapshot_ref": "evidence://snapshot/1",
            "phase": "after",
            "captured_at": NOW.isoformat(),
            "source_id": "sensor://camera/front",
            "frame": "world",
            "calibration_ref": "calibration://camera/front/v1",
            "scene_graph": {
                "nodes": [{"id": "RAW_SCENE_CONTENT_MUST_NOT_ENTER_PROMPT"}],
                "relations": [],
            },
        },
        revision="scene-1",
        source="snapshot://task/after",
    )
    prompt = ContextBuilder(tmp_path).build_system_prompt()
    assert "RAW_SCENE_CONTENT_MUST_NOT_ENTER_PROMPT" not in prompt
    assert "non_authoritative_projection_identity_only" in prompt
    assert '"data_sha256":' in prompt

    content = (tmp_path / "ENVIRONMENT.md").read_text(encoding="utf-8")
    (tmp_path / "ENVIRONMENT.md").write_text(
        content.replace('"scene_revision": "scene-1"', '"scene_revision": "RAW_ERROR_MUST_NOT_ENTER_PROMPT"'),
        encoding="utf-8",
    )
    invalid_prompt = ContextBuilder(tmp_path).build_system_prompt()
    assert "RAW_ERROR_MUST_NOT_ENTER_PROMPT" not in invalid_prompt
    assert "invalid_environment_projection" in invalid_prompt


def test_request_builder_rejects_workspace_file_as_evidence_artifact(tmp_path):
    writer = ForgeEvidenceWriter(
        tmp_path, "task_owned", "agent_task", artifact_namespace="agent_tasks"
    )
    bundle, reference = _complete_bundle(writer)
    outside = tmp_path / "ENVIRONMENT.md"
    outside.write_text("{}", encoding="utf-8")
    artifact = bundle.artifacts[0]
    artifact.uri = "ENVIRONMENT.md"
    artifact.byte_size = len(outside.read_bytes())
    artifact.sha256 = hashlib.sha256(outside.read_bytes()).hexdigest()
    bundle.bundle_id = derive_evidence_bundle_id(bundle)
    (tmp_path / reference).write_text(bundle.model_dump_json(), encoding="utf-8")

    evidence_path, loaded = VerificationRequestBuilder(tmp_path)._load_evidence(
        reference,
        expected_session_id="task_owned",
        expected_command_id="agent_task",
        identity_name="AgentTask",
    )
    with pytest.raises(VerificationEvidenceError, match="not writer-owned"):
        VerificationRequestBuilder(tmp_path)._validate_evidence(
            evidence_path,
            loaded,
            policy=VerificationEvidencePolicy(
                required_kinds=["rgb_image"],
                required_sources=["camera/front"],
            ),
        )


def test_retention_reloads_bundle_and_rejects_post_build_path_mutation(tmp_path):
    writer = ForgeEvidenceWriter(
        tmp_path,
        "task_retention",
        "agent_task",
        artifact_namespace="agent_tasks",
    )
    bundle, reference = _complete_bundle(writer)
    revision_id = "revision_retention"
    task = AgentTaskRecord(
        task_id="task_retention",
        task_description="retain only validated evidence",
        revisions=[
            PlanRevision(
                revision_id=revision_id,
                number=1,
                reason="test",
                execution_records=[
                    ToolExecutionRecord(
                        record_id="record_retention",
                        revision_id=revision_id,
                        tool_id="scene.observe",
                        semantics="query",
                        caller_id="test",
                        status="succeeded",
                    )
                ],
            )
        ],
        active_revision_id=revision_id,
        evidence_bundle_ref=reference,
        evidence_bundle_id=bundle.bundle_id,
    )
    request = VerificationRequestBuilder(tmp_path).build_agent_task(
        task,
        events=[],
        lessons="",
    )
    victim = tmp_path / "KEEP.txt"
    victim.write_text("must survive", encoding="utf-8")
    original_uri = request.evidence.artifacts[0].uri
    request.evidence.artifacts[0].uri = "KEEP.txt"
    verifier = ForgeTaskVerifier(
        workspace=tmp_path,
        provider=object(),
        model="fixture",
        evidence_retention="none",
        service_provider_spec={
            "provider_name": "custom",
            "model": "fixture",
            "api_base": "http://127.0.0.1:9000/v1",
        },
    )

    with pytest.raises(VerificationVerdictError, match="identity changed"):
        verifier.apply_retention(request, final_status="succeeded")

    assert victim.read_text(encoding="utf-8") == "must survive"
    assert all(path.exists() for path in request.artifact_paths)

    request.evidence.artifacts[0].uri = original_uri
    result = verifier.apply_retention(request, final_status="succeeded")
    assert result["status"] == "deleted"
    assert victim.read_text(encoding="utf-8") == "must survive"
    assert request.artifact_paths[0].exists()
    assert all(not path.exists() for path in request.artifact_paths[1:])
