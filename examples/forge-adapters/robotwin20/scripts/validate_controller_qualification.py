#!/usr/bin/env python3
"""Validate a controller-qualification artifact without running a provider."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Type

from robotwin20_adapter.controller_qualification import (
    ControllerQualification,
    ControllerQualificationApproval,
    ControllerQualificationEvidence,
    ControllerQualificationPlan,
    ControllerQualificationPlanValidation,
    ControllerQualificationReviewRequest,
    ControllerQualificationSourceManifest,
    ControllerQualificationValidation,
    canonical_controller_qualification,
)

_KINDS: dict[str, Type] = {
    "approval": ControllerQualificationApproval,
    "plan": ControllerQualificationPlan,
    "plan-validation": ControllerQualificationPlanValidation,
    "review": ControllerQualificationReviewRequest,
    "source-manifest": ControllerQualificationSourceManifest,
    "evidence": ControllerQualificationEvidence,
    "validation": ControllerQualificationValidation,
    "qualification": ControllerQualification,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=tuple(_KINDS), required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    args = parser.parse_args()
    path = args.artifact
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise SystemExit("artifact must be an absolute regular file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        model = _KINDS[args.kind].model_validate(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"invalid controller qualification artifact: {exc}") from exc
    canonical = canonical_controller_qualification(model)
    print(
        json.dumps(
            {
                "status": "valid",
                "kind": args.kind,
                "schema_version": model.schema_version,
                "artifact": str(path),
                "sha256": hashlib.sha256(canonical).hexdigest(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
