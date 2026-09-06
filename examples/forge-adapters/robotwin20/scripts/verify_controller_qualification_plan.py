#!/usr/bin/env python3
"""Independently cross-verify one no-motion qualification review package."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from robotwin20_adapter import (
    ControllerQualificationPlan,
    ControllerQualificationPlanValidation,
    ControllerQualificationReviewRequest,
    ControllerQualificationSourceManifest,
    MotionCapabilityDocument,
    MotionCapabilityValidation,
    validate_controller_qualification_plan_package,
)


class VerificationError(RuntimeError):
    pass


def _read(path: Path, model: type, label: str):
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise VerificationError(f"{label} must be an absolute regular file")
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise VerificationError(f"{label} is invalid") from exc


def _sha(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise VerificationError("qualification verification input cannot be read") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--review-request", type=Path, required=True)
    for arm in ("left", "right"):
        parser.add_argument(f"--{arm}-capability", type=Path, required=True)
        parser.add_argument(f"--{arm}-validation", type=Path, required=True)
    parser.add_argument("--verifier-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.verifier_id.strip() or any(char.isspace() for char in args.verifier_id):
        raise VerificationError("verifier identity is invalid")
    plan = _read(args.plan, ControllerQualificationPlan, "qualification plan")
    manifest = _read(args.source_manifest, ControllerQualificationSourceManifest, "source manifest")
    review = _read(args.review_request, ControllerQualificationReviewRequest, "review request")
    capabilities = {
        arm: _read(
            getattr(args, f"{arm}_capability"), MotionCapabilityDocument, f"{arm} capability"
        )
        for arm in ("left", "right")
    }
    validations = {
        arm: _read(
            getattr(args, f"{arm}_validation"), MotionCapabilityValidation, f"{arm} validation"
        )
        for arm in ("left", "right")
    }
    checks = validate_controller_qualification_plan_package(
        plan=plan,
        source_manifest=manifest,
        review_request=review,
        capabilities=capabilities,
        capability_file_sha256={
            arm: _sha(getattr(args, f"{arm}_capability")) for arm in capabilities
        },
        validations=validations,
        validation_file_sha256={
            arm: _sha(getattr(args, f"{arm}_validation")) for arm in validations
        },
    )
    result = ControllerQualificationPlanValidation(
        qualification_id=plan.qualification_id,
        plan_sha256=_sha(args.plan),
        source_manifest_sha256=_sha(args.source_manifest),
        review_request_sha256=_sha(args.review_request),
        verifier_id=args.verifier_id,
        verified_at=datetime.now(timezone.utc).isoformat(),
        checks=checks,
    )
    if not args.output.is_absolute() or args.output.exists() or args.output.is_symlink():
        raise VerificationError("verification output must be a new absolute file")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(result.model_dump(mode="json"), sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    with args.output.open("xb") as stream:
        stream.write(payload)
    args.output.chmod(0o600)
    print(
        json.dumps(
            {
                "status": result.status,
                "output": str(args.output),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "world_change_started": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
