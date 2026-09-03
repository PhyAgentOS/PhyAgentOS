from __future__ import annotations

import pytest

from PhyAgentOS.agent.session_verifier import ForgeTaskVerifier, VerificationVerdictError
from PhyAgentOS.state_io import render_environment_projection
from PhyAgentOS.verification.contracts import CriterionVerdict, VerificationVerdict
from PhyAgentOS.verification.request_builder import (
    VerificationEvidenceError,
    VerificationRequestBuilder,
)


def _environment_projection(path):
    render_environment_projection(
        path,
        {
            "schema_version": "paos.environment.v1",
            "scene_revision": "scene-1",
            "snapshot_ref": "evidence://forge/task-1/after_snapshot",
            "phase": "after",
            "captured_at": "2026-09-03T00:00:00+00:00",
            "source_id": "sensor://camera/front",
            "frame": "world",
            "calibration_ref": "calibration://camera/front/v1",
            "scene_graph": {"nodes": [], "relations": []},
        },
        revision="scene-1",
        source="producer://paos/environment/v1",
    )


def test_request_builder_never_treats_environment_projection_as_evidence(tmp_path):
    _environment_projection(tmp_path / "ENVIRONMENT.md")
    builder = VerificationRequestBuilder(tmp_path)
    with pytest.raises(VerificationEvidenceError, match="invalid Evidence Bundle"):
        builder._load_evidence(
            "ENVIRONMENT.md",
            expected_session_id="task-1",
            expected_command_id="agent_task",
            identity_name="AgentTask",
        )


def test_verifier_rejects_projection_reference_as_evidence_ref():
    verdict = VerificationVerdict(
        verdict="success",
        criteria=[CriterionVerdict(criterion="done", status="satisfied")],
        evidence_refs=["evidence://forge/task-1/after_snapshot"],
        reason="projection claims success",
        lesson="none",
    )
    with pytest.raises(VerificationVerdictError, match="unknown evidence"):
        ForgeTaskVerifier._validate_generic_verdict(
            expected_criteria=["done"],
            valid_evidence_refs={"artifact_1"},
            verdict=verdict,
        )
