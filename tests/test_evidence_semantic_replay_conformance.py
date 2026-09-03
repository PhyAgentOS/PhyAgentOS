from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone

import pytest

from PhyAgentOS.verification.contracts import (
    EvidenceArtifact,
    EvidenceBundle,
    EvidenceCaptureWindow,
    EvidenceQuality,
    VerificationEvidencePolicy,
)
from PhyAgentOS.verification.request_builder import (
    VerificationEvidenceError,
    VerificationRequestBuilder,
)

NOW = datetime(2026, 9, 3, 0, 0, tzinfo=timezone.utc)


def _artifact(tmp_path, *, artifact_id, phase, uri, data, media_type="image/jpeg", source="camera/front", retained=True):
    path = tmp_path / uri
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return EvidenceArtifact(
        artifact_id=artifact_id,
        phase=phase,
        kind="rgb_image",
        source_id=source,
        received_at=NOW,
        media_type=media_type,
        sha256=hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
        uri=uri,
        retained=retained,
    )


def _bundle(tmp_path, *, before_at=NOW, terminal_at=NOW, after_at=NOW, retained=True):
    before = _artifact(
        tmp_path,
        artifact_id="before_rgb",
        phase="before",
        uri="artifacts/task-replay-1/evidence/before.jpg",
        data=b"\xff\xd8\xffbefore",
        retained=retained,
    )
    after = _artifact(
        tmp_path,
        artifact_id="after_rgb",
        phase="after",
        uri="artifacts/task-replay-1/evidence/after.jpg",
        data=b"\xff\xd8\xffafter",
        retained=retained,
    )
    bundle = EvidenceBundle(
        bundle_id="bundle-replay-1",
        session_id="task-replay-1",
        command_id="agent_task",
        capture_window=EvidenceCaptureWindow(
            before_command_at=before_at,
            command_terminal_at=terminal_at,
            after_command_at=after_at,
        ),
        artifacts=[before, after],
        quality=EvidenceQuality(
            complete=True,
            association_quality="authoritative",
        ),
    )
    path = tmp_path / "artifacts" / "task-replay-1" / "evidence_bundle.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(bundle.model_dump_json(), encoding="utf-8")
    return path, bundle


def _policy():
    return VerificationEvidencePolicy(
        required_kinds=["rgb_image"],
        required_sources=["camera/front"],
        minimum_association="authoritative",
    )


def test_complete_bundle_replays_across_workspaces_with_same_artifact_facts(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    first_path, first_bundle = _bundle(first)
    shutil.copytree(first, second, dirs_exist_ok=True)
    second_path = second / "artifacts" / "task-replay-1" / "evidence_bundle.json"

    first_validated = VerificationRequestBuilder(first)._validate_evidence(
        first_path, first_bundle, policy=_policy()
    )
    second_bundle = EvidenceBundle.model_validate_json(second_path.read_text(encoding="utf-8"))
    second_validated = VerificationRequestBuilder(second)._validate_evidence(
        second_path, second_bundle, policy=_policy()
    )
    assert first_validated.artifact_ids == second_validated.artifact_ids == {
        "before_rgb",
        "after_rgb",
    }
    assert first_validated.images == second_validated.images
    assert first_validated.evidence.capture_window == second_validated.evidence.capture_window


def test_incomplete_bundle_is_rejected_before_artifact_consumption(tmp_path):
    path, bundle = _bundle(tmp_path)
    bundle.quality.complete = False
    bundle.quality.missing_requirements = ["after:rgb_image"]
    with pytest.raises(VerificationEvidenceError, match="incomplete"):
        VerificationRequestBuilder(tmp_path)._validate_evidence(
            path, bundle, policy=_policy()
        )


def test_capture_window_ordering_and_association_policy_fail_closed(tmp_path):
    path, bundle = _bundle(
        tmp_path,
        before_at=NOW,
        terminal_at=NOW.replace(hour=1),
        after_at=NOW.replace(hour=0, minute=30),
    )
    with pytest.raises(VerificationEvidenceError, match="ordering"):
        VerificationRequestBuilder(tmp_path)._validate_evidence(
            path, bundle, policy=_policy()
        )

    path, bundle = _bundle(tmp_path / "best_effort")
    bundle.quality.association_quality = "best_effort"
    with pytest.raises(VerificationEvidenceError, match="below task policy"):
        VerificationRequestBuilder(tmp_path / "best_effort")._validate_evidence(
            path, bundle, policy=_policy()
        )


def test_evidence_timestamps_and_numeric_capture_values_require_strict_schema():
    with pytest.raises(ValueError, match="timezone"):
        EvidenceCaptureWindow(before_command_at=datetime(2026, 9, 3, 0, 0))
    with pytest.raises(ValueError, match="finite number"):
        EvidenceArtifact(
            artifact_id="invalid_capture",
            phase="before",
            kind="rgb_image",
            source_id="camera/front",
            captured_at=float("inf"),
            received_at=NOW,
            media_type="image/jpeg",
            sha256="0" * 64,
            byte_size=0,
            uri="artifacts/task-replay-1/evidence/invalid.jpg",
        )


def test_digest_retention_and_required_source_fail_closed(tmp_path):
    path, bundle = _bundle(tmp_path)
    bundle.artifacts[0].sha256 = "0" * 64
    with pytest.raises(VerificationEvidenceError, match="digest mismatch"):
        VerificationRequestBuilder(tmp_path)._validate_evidence(
            path, bundle, policy=_policy()
        )

    retained_root = tmp_path / "retained"
    path, bundle = _bundle(retained_root, retained=False)
    with pytest.raises(VerificationEvidenceError, match="retention"):
        VerificationRequestBuilder(retained_root)._validate_evidence(
            path, bundle, policy=_policy()
        )

    source_root = tmp_path / "source"
    path, bundle = _bundle(source_root)
    bundle.artifacts[0].source_id = "camera/rear"
    with pytest.raises(VerificationEvidenceError, match="source is unavailable"):
        VerificationRequestBuilder(source_root)._validate_evidence(
            path, bundle, policy=_policy()
        )


def test_structured_artifact_json_is_replayed_as_data_not_verdict(tmp_path):
    path, bundle = _bundle(tmp_path)
    data = json.dumps({"object": "cup", "placed": True}).encode()
    structured = _artifact(
        tmp_path,
        artifact_id="after_state",
        phase="after",
        uri="artifacts/task-replay-1/evidence/after_state.json",
        data=data,
        media_type="application/json",
        source="ws/state",
    )
    bundle.artifacts.append(structured)
    path.write_text(bundle.model_dump_json(), encoding="utf-8")
    validated = VerificationRequestBuilder(tmp_path)._validate_evidence(
        path, bundle, policy=_policy()
    )
    assert validated.structured == {"after_state": {"object": "cup", "placed": True}}
    assert "after_state" in validated.artifact_ids


def test_structured_artifact_rejects_non_standard_json_constants(tmp_path):
    path, bundle = _bundle(tmp_path)
    artifact = bundle.artifacts[0]
    artifact.media_type = "application/json"
    data = b'{"joint_position":NaN}'
    artifact_path = tmp_path / artifact.uri
    artifact_path.write_bytes(data)
    artifact.byte_size = len(data)
    artifact.sha256 = hashlib.sha256(data).hexdigest()

    with pytest.raises(VerificationEvidenceError, match="verification JSON is invalid"):
        VerificationRequestBuilder(tmp_path)._validate_evidence(
            path,
            bundle,
            policy=_policy(),
        )
