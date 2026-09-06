from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from test_controller_qualification import _evidence, _plan

from robotwin20_adapter import (
    ControllerQualificationApproval,
    ControllerQualificationValidation,
)

CLI = Path(__file__).parents[1] / "scripts" / "approve_controller_qualification_evidence.py"


def _write(path: Path, value) -> str:
    raw = (json.dumps(value.model_dump(mode="json"), sort_keys=True, separators=(",", ":")) + "\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _package(tmp_path: Path):
    plan = _plan()
    plan_path = tmp_path / "plan.json"
    plan_digest = _write(plan_path, plan)
    approval = ControllerQualificationApproval(
        decision="approved_controller_qualification_simulation_only",
        qualification_id=plan.qualification_id,
        plan_ref="artifact://controller-qualification/q/plan",
        plan_sha256=plan_digest,
        source_manifest_ref="artifact://controller-qualification/q/source-manifest",
        source_manifest_sha256="b" * 64,
        plan_validation_ref="artifact://controller-qualification/q/no-motion-validation",
        plan_validation_sha256="c" * 64,
        reviewer_id="reviewer",
        reviewed_at="2026-09-06T08:00:00+00:00",
    )
    approval_path = tmp_path / "approval.json"
    approval_digest = _write(approval_path, approval)
    evidence = _evidence().model_copy(
        update={"plan_sha256": plan_digest, "approval_sha256": approval_digest}
    )
    evidence_path = tmp_path / "evidence.json"
    evidence_digest = _write(evidence_path, evidence)
    validation = ControllerQualificationValidation(
        qualification_id=plan.qualification_id,
        evidence_ref="artifact://controller-qualification/q/evidence",
        evidence_sha256=evidence_digest,
        validator_id="independent-validator/v1",
        producer_id=evidence.producer_id,
        validated_at="2026-09-06T08:03:00+00:00",
        status="validated_pass",
        checks=("trace_schema", "test_binding", "both_arm_signals", "finite_values", "outcome_binding"),
        controller_enforced=True,
    )
    validation_path = tmp_path / "validation.json"
    validation_digest = _write(validation_path, validation)
    return plan_path, approval_path, evidence_path, validation_path, (plan_digest, approval_digest, evidence_digest, validation_digest)


def _command(paths, digests, output):
    plan, approval, evidence, validation = paths
    plan_digest, approval_digest, evidence_digest, validation_digest = digests
    return [
        sys.executable,
        str(CLI),
        "--plan", str(plan), "--approval", str(approval), "--evidence", str(evidence),
        "--validation", str(validation), "--reviewer-id", "reviewer-2",
        "--confirm-plan-digest", plan_digest, "--confirm-approval-digest", approval_digest,
        "--confirm-evidence-digest", evidence_digest, "--confirm-validation-digest", validation_digest,
        "--approve-qualification-evidence", "I_REVIEWED_AND_APPROVE_CONTROLLER_QUALIFICATION_EVIDENCE",
        "--output", str(output),
    ]


def test_final_approval_creates_non_authoritative_pass(tmp_path: Path):
    paths = _package(tmp_path)
    output = tmp_path / "qualification.json"
    result = subprocess.run(_command(paths[:4], paths[4], output), capture_output=True, text=True, check=True)
    summary = json.loads(result.stdout)
    assert summary["status"] == "approved_pass"
    assert summary["motion_authorized"] is False
    assert output.is_file()


def test_final_approval_rejects_wrong_phrase_without_output(tmp_path: Path):
    paths = _package(tmp_path)
    output = tmp_path / "qualification.json"
    command = _command(paths[:4], paths[4], output)
    index = command.index("I_REVIEWED_AND_APPROVE_CONTROLLER_QUALIFICATION_EVIDENCE")
    command[index] = "WRONG"
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode != 0
    assert not output.exists()
