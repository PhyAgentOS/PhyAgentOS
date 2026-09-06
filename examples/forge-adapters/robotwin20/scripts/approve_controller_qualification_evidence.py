#!/usr/bin/env python3
"""Create the final human-reviewed controller qualification record."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from robotwin20_adapter.controller_qualification import (
    ControllerQualification,
    ControllerQualificationApproval,
    ControllerQualificationEvidence,
    ControllerQualificationPlan,
    ControllerQualificationValidation,
    canonical_controller_qualification,
)

APPROVAL_PHRASE = "I_REVIEWED_AND_APPROVE_CONTROLLER_QUALIFICATION_EVIDENCE"


class EvidenceApprovalError(RuntimeError):
    """The evidence cannot be promoted to a final qualification record."""


def _read(path: Path, model: type, label: str):
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise EvidenceApprovalError(f"{label} must be an absolute regular file")
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise EvidenceApprovalError(f"{label} is invalid") from exc


def _sha(path: Path, label: str) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise EvidenceApprovalError(f"{label} cannot be read") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--reviewer-id", required=True)
    parser.add_argument("--confirm-plan-digest", required=True)
    parser.add_argument("--confirm-approval-digest", required=True)
    parser.add_argument("--confirm-evidence-digest", required=True)
    parser.add_argument("--confirm-validation-digest", required=True)
    parser.add_argument("--approve-qualification-evidence", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.approve_qualification_evidence != APPROVAL_PHRASE:
            raise EvidenceApprovalError("explicit qualification-evidence approval phrase is required")
        if not args.reviewer_id.strip() or any(char.isspace() for char in args.reviewer_id):
            raise EvidenceApprovalError("reviewer identity is invalid")
        plan = _read(args.plan, ControllerQualificationPlan, "qualification plan")
        approval = _read(args.approval, ControllerQualificationApproval, "qualification approval")
        evidence = _read(args.evidence, ControllerQualificationEvidence, "qualification evidence")
        validation = _read(args.validation, ControllerQualificationValidation, "qualification validation")
        digests = {
            "plan": _sha(args.plan, "qualification plan"),
            "approval": _sha(args.approval, "qualification approval"),
            "evidence": _sha(args.evidence, "qualification evidence"),
            "validation": _sha(args.validation, "qualification validation"),
        }
        confirmed = {
            "plan": args.confirm_plan_digest,
            "approval": args.confirm_approval_digest,
            "evidence": args.confirm_evidence_digest,
            "validation": args.confirm_validation_digest,
        }
        if digests != confirmed:
            raise EvidenceApprovalError("confirmed qualification-evidence digest does not match")
        if (
            evidence.status != "passed"
            or validation.status != "validated_pass"
            or validation.controller_enforced is not True
            or validation.independent is not True
            or evidence.qualification_id != plan.qualification_id
            or approval.qualification_id != plan.qualification_id
            or validation.qualification_id != plan.qualification_id
            or evidence.plan_sha256 != digests["plan"]
            or evidence.approval_sha256 != digests["approval"]
            or validation.evidence_sha256 != digests["evidence"]
            or approval.motion_authorized is not False
            or evidence.motion_authorized is not False
            or validation.motion_authorized is not False
            or evidence.identity != plan.identity
        ):
            raise EvidenceApprovalError("qualification evidence result binding is invalid")
        evidence_ref = f"artifact://controller-qualification/{plan.qualification_id}/evidence"
        validation_ref = f"artifact://controller-qualification/{plan.qualification_id}/validation"
        plan_ref = approval.plan_ref
        final = ControllerQualification(
            qualification_id=plan.qualification_id,
            plan_ref=plan_ref,
            plan_sha256=digests["plan"],
            evidence_ref=evidence_ref,
            evidence_sha256=digests["evidence"],
            validation_ref=validation_ref,
            validation_sha256=digests["validation"],
            identity=evidence.identity,
            status="approved_pass",
            reviewer_id=args.reviewer_id.strip(),
            reviewed_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            independent_execution_qualification=True,
            controller_enforced=True,
        )
        if not args.output.is_absolute() or args.output.exists() or args.output.is_symlink():
            raise EvidenceApprovalError("final qualification output must be a new absolute file")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        payload = canonical_controller_qualification(final)
        with args.output.open("xb") as stream:
            stream.write(payload)
        args.output.chmod(0o600)
        print(json.dumps({"status": final.status, "output": str(args.output), "sha256": hashlib.sha256(payload).hexdigest(), "motion_authorized": False, "benchmark_motion_authorized": False, "hardware_motion_authorized": False}, sort_keys=True))
        return 0
    except EvidenceApprovalError as exc:
        print(json.dumps({"status": "rejected", "error": str(exc), "motion_authorized": False}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
