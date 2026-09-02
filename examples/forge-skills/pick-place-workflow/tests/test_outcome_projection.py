from pathlib import Path
from types import SimpleNamespace

import pytest
from PhyAgentOS.forge.task import AgentTaskRecord, PlanRevision, ToolExecutionRecord
from PhyAgentOS.verification.contracts import (
    EvidenceBundle,
    EvidenceQuality,
    TaskVerificationContract,
)
from PhyAgentOS.verification.outcome_projection import (
    project_terminal_outcomes,
    projection_to_dict,
)
from PhyAgentOS.verification.request_builder import VerificationRequestBuilder


def summary(**overrides):
    value = {
        "version": "capability_outcome_summary_v1",
        "capability_phase": "retreat",
        "status": "succeeded",
        "failure_owner": None,
        "failure_code": None,
        "world_change_started": True,
        "outcome_known": True,
        "evidence_availability": "partial",
        "artifact_refs": ["artifact://place-1/trajectory"],
        "bounded_metric_names": ["release_height"],
    }
    value.update(overrides)
    return value


def record(*, status="succeeded", tool_id="object.place", semantics="action", response=None, record_id="r1"):
    return SimpleNamespace(
        record_id=record_id,
        tool_id=tool_id,
        semantics=semantics,
        status=status,
        invocation_id="invocation://object-place/1",
        attempt_id="attempt://object-place/1",
        response=response,
    )


def response(summary_value):
    return {"ok": True, "data": {"phase": "completed", "result": {"capability_outcome_summary": summary_value}}}


def test_success_projection_is_execution_fact_only_and_artifacts_stay_opaque():
    result = project_terminal_outcomes([record(response=response(summary()))])
    assert not result.errors
    assert len(result.projections) == 1
    value = projection_to_dict(result.projections[0])
    assert value["authority"] == "execution_fact_only"
    assert value["task_success_authorized"] is False
    assert value["opaque_artifact_refs"] == ["artifact://place-1/trajectory"]
    assert value["tool_id"] == "object.place"


def test_non_action_and_non_terminal_records_are_not_projected():
    assert not project_terminal_outcomes(
        [
            record(semantics="query", response=response(summary())),
            record(status="pending", response=response(summary())),
            record(response=None),
        ]
    ).projections


@pytest.mark.parametrize(
    ("mutations", "code"),
    [
        ({"version": "capability_outcome_summary_v2"}, "unsupported_summary_version"),
        ({"capability_phase": "ik"}, "invalid_capability_phase"),
        ({"artifact_refs": ["file:///tmp/raw"]}, "invalid_artifact_refs"),
        ({"status": "unknown", "outcome_known": True}, "invalid_unknown_outcome"),
        ({"status": "succeeded", "failure_code": "release_failed"}, "invalid_success_failure_fields"),
        ({"status": "failed", "failure_owner": None}, "invalid_failure_fields"),
        ({"post_release_evidence": {"availability": "complete", "artifact_refs": []}}, "invalid_post_release_evidence"),
        ({"extra": True}, "invalid_summary_fields"),
    ],
)
def test_malformed_summary_returns_bounded_projection_error(mutations, code):
    payload = summary(**mutations)
    record_status = payload["status"] if payload["status"] in {"succeeded", "failed", "unknown"} else "succeeded"
    result = project_terminal_outcomes([record(status=record_status, response=response(payload))])
    assert not result.projections
    assert result.errors[0].code == code
    assert result.errors[0].record_id == "r1"


def test_place_post_release_evidence_is_projected_without_entering_evidence_allowlist():
    payload = summary(
        post_release_evidence={
            "availability": "complete",
            "artifact_refs": ["artifact://place-1/post-release"],
        }
    )
    result = project_terminal_outcomes([record(response=response(payload))])
    projection = result.projections[0]
    assert projection.post_release_evidence is not None
    assert projection.post_release_evidence.opaque_artifact_refs == (
        "artifact://place-1/post-release",
    )
    assert "artifact://place-1/post-release" not in projection_to_dict(projection)["opaque_artifact_refs"]


def test_missing_summary_on_terminal_action_is_an_explicit_error():
    result = project_terminal_outcomes(
        [record(response={"ok": True, "data": {"phase": "completed", "result": {"status": "succeeded"}}})]
    )
    assert result.errors[0].code == "missing_summary"


def test_summary_and_record_status_mismatch_is_rejected():
    result = project_terminal_outcomes([record(status="succeeded", response=response(summary(status="failed", failure_owner="execution", failure_code="x")))])
    assert result.errors[0].code == "summary_status_mismatch"


def test_agent_task_verification_context_contains_projection_without_allowlisting_artifact():
    terminal_response = response(
        summary(
            post_release_evidence={
                "availability": "complete",
                "artifact_refs": ["artifact://place-1/post-release"],
            }
        )
    )
    execution = ToolExecutionRecord(
        record_id="record-1",
        revision_id="revision-1",
        tool_id="object.place",
        semantics="action",
        caller_id="paos:test",
        status="succeeded",
        invocation_id="invocation://object-place/1",
        attempt_id="attempt://object-place/1",
        response=terminal_response,
        evidence_refs=["invocation:invocation://object-place/1"],
    )
    task = AgentTaskRecord(
        task_id="task-1",
        task_description="pick and place",
        verification=TaskVerificationContract(),
        revisions=[
            PlanRevision(
                revision_id="revision-1",
                number=1,
                reason="initial",
                execution_records=[execution],
            )
        ],
        active_revision_id="revision-1",
        evidence_bundle_ref="evidence/bundle.json",
    )
    evidence = EvidenceBundle(
        bundle_id="bundle-1",
        session_id="task-1",
        command_id="agent_task",
        quality=EvidenceQuality(complete=True),
    )
    validated = SimpleNamespace(
        evidence=evidence,
        artifact_paths=tuple(),
        images=tuple(),
        structured={},
        artifact_ids=frozenset(),
    )
    builder = VerificationRequestBuilder(Path("."))
    builder._load_evidence = lambda *args, **kwargs: (Path("evidence/bundle.json"), evidence)
    builder._validate_evidence = lambda *args, **kwargs: validated
    request = builder.build_agent_task(task, events=[], lessons="[]")
    text = request.content[0]["text"]
    assert "capability_outcome_projections" in text
    assert "execution_fact_only" in text
    assert "task_success_authorized" in text
    assert "artifact://place-1/post-release" in text
    assert "artifact://place-1/post-release" not in request.valid_evidence_refs
