#!/usr/bin/env python3
"""Create a human, digest-bound approval for isolated qualification motion."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from robotwin20_adapter import (
    ControllerQualificationApproval,
    ControllerQualificationPlan,
    ControllerQualificationPlanValidation,
    ControllerQualificationReviewRequest,
    ControllerQualificationSourceManifest,
    canonical_controller_qualification,
)

APPROVAL_PHRASE = "I_REVIEWED_AND_APPROVE_CONTROLLER_QUALIFICATION_SIMULATION_ONLY"


class ApprovalError(RuntimeError):
    pass


def _read(path: Path, model: type, label: str):
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise ApprovalError(f"{label} must be an absolute regular file")
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ApprovalError(f"{label} is invalid") from exc


def _sha(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ApprovalError("approval input cannot be read") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--review-request", type=Path, required=True)
    parser.add_argument("--plan-validation", type=Path, required=True)
    parser.add_argument("--reviewer-id", required=True)
    parser.add_argument("--confirm-plan-digest", required=True)
    parser.add_argument("--confirm-source-manifest-digest", required=True)
    parser.add_argument("--confirm-review-request-digest", required=True)
    parser.add_argument("--confirm-plan-validation-digest", required=True)
    parser.add_argument("--approve-qualification-simulation-only", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.approve_qualification_simulation_only != APPROVAL_PHRASE:
        raise ApprovalError("explicit controller-qualification approval phrase is required")
    if not args.reviewer_id.strip() or any(char.isspace() for char in args.reviewer_id):
        raise ApprovalError("reviewer identity is invalid")
    plan = _read(args.plan, ControllerQualificationPlan, "qualification plan")
    manifest = _read(args.source_manifest, ControllerQualificationSourceManifest, "source manifest")
    review = _read(args.review_request, ControllerQualificationReviewRequest, "review request")
    validation = _read(
        args.plan_validation, ControllerQualificationPlanValidation, "plan validation"
    )
    digests = {
        "plan": _sha(args.plan),
        "source_manifest": _sha(args.source_manifest),
        "review_request": _sha(args.review_request),
        "plan_validation": _sha(args.plan_validation),
    }
    confirmed = {
        "plan": args.confirm_plan_digest,
        "source_manifest": args.confirm_source_manifest_digest,
        "review_request": args.confirm_review_request_digest,
        "plan_validation": args.confirm_plan_validation_digest,
    }
    if digests != confirmed:
        raise ApprovalError("confirmed controller-qualification digest does not match")
    if (
        manifest.qualification_id != plan.qualification_id
        or review.qualification_id != plan.qualification_id
        or validation.qualification_id != plan.qualification_id
        or plan.source_manifest_sha256 != digests["source_manifest"]
        or review.plan_sha256 != digests["plan"]
        or review.source_manifest_sha256 != digests["source_manifest"]
        or validation.plan_sha256 != digests["plan"]
        or validation.source_manifest_sha256 != digests["source_manifest"]
        or validation.review_request_sha256 != digests["review_request"]
        or validation.world_change_started is not False
        or validation.qualification_motion_authorized is not False
    ):
        raise ApprovalError("controller-qualification review package binding is invalid")
    prefix = plan.source_manifest_ref.removesuffix("/source-manifest")
    approval = ControllerQualificationApproval(
        decision="approved_controller_qualification_simulation_only",
        qualification_id=plan.qualification_id,
        plan_ref=f"{prefix}/plan",
        plan_sha256=digests["plan"],
        source_manifest_ref=plan.source_manifest_ref,
        source_manifest_sha256=digests["source_manifest"],
        plan_validation_ref=f"{prefix}/no-motion-validation",
        plan_validation_sha256=digests["plan_validation"],
        reviewer_id=args.reviewer_id.strip(),
        reviewed_at=datetime.now(timezone.utc).isoformat(),
    )
    if not args.output.is_absolute() or args.output.exists() or args.output.is_symlink():
        raise ApprovalError("approval output must be a new absolute file")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_controller_qualification(approval)
    with args.output.open("xb") as stream:
        stream.write(payload)
    args.output.chmod(0o600)
    print(
        json.dumps(
            {
                "status": "approved_controller_qualification_simulation_only",
                "output": str(args.output),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "qualification_motion_authorized": True,
                "benchmark_motion_authorized": False,
                "hardware_motion_authorized": False,
                "motion_authorized": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
