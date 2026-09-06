#!/usr/bin/env python3
"""Independently validate controller qualification evidence and trace artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from robotwin_controller_qualification_worker import (
    VALIDATOR_ID,
    QualificationWorkerError,
    validate_trace_artifact,
)

from robotwin20_adapter.controller_qualification import (
    ControllerQualificationApproval,
    ControllerQualificationEvidence,
    ControllerQualificationPlan,
    ControllerQualificationValidation,
)


def _read(path: Path, model: type, label: str):
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise QualificationWorkerError(f"{label} must be an absolute regular file")
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise QualificationWorkerError(f"{label} is invalid") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        plan = _read(args.plan.resolve(), ControllerQualificationPlan, "qualification plan")
        approval = _read(args.approval.resolve(), ControllerQualificationApproval, "qualification approval")
        evidence = _read(args.evidence.resolve(), ControllerQualificationEvidence, "qualification evidence")
        if evidence.qualification_id != plan.qualification_id or evidence.plan_sha256 != hashlib.sha256(args.plan.read_bytes()).hexdigest():
            raise QualificationWorkerError("qualification evidence plan binding is invalid")
        if evidence.approval_sha256 != hashlib.sha256(args.approval.read_bytes()).hexdigest():
            raise QualificationWorkerError("qualification evidence approval binding is invalid")
        if approval.qualification_id != evidence.qualification_id or approval.motion_authorized is not False:
            raise QualificationWorkerError("qualification approval authority boundary is invalid")
        checks = []
        for test in evidence.tests:
            path = args.artifact_root.resolve() / Path(test.evidence_ref.removeprefix("artifact://"))
            if path.suffix == "":
                path = path.with_suffix(".json")
            if not path.is_file() or path.is_symlink():
                raise QualificationWorkerError(f"missing trace artifact for {test.test_id}")
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != test.evidence_sha256:
                raise QualificationWorkerError(f"trace digest mismatch for {test.test_id}")
            trace = json.loads(raw.decode("utf-8"))
            checks.extend(validate_trace_artifact(trace, test))
        checks = tuple(dict.fromkeys(checks))
        status = "validated_pass" if evidence.status == "passed" else "validated_failure"
        if args.output.exists() or args.output.is_symlink() or not args.output.is_absolute():
            raise QualificationWorkerError("validation output must be a new absolute file")
        from datetime import datetime, timezone
        result = ControllerQualificationValidation(
            qualification_id=evidence.qualification_id,
            evidence_ref="artifact://" + str(args.evidence.resolve().relative_to(args.artifact_root.resolve())).removesuffix(".json"),
            evidence_sha256=hashlib.sha256(args.evidence.read_bytes()).hexdigest(),
            validator_id=VALIDATOR_ID,
            producer_id=evidence.producer_id,
            validated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            status=status,
            checks=tuple(list(checks) + ["evidence_model", "plan_binding", "approval_binding", "all_trace_digests"]),
            controller_enforced=evidence.status == "passed",
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        payload = (json.dumps(result.model_dump(mode="json"), sort_keys=True, separators=(",", ":")) + "\n").encode()
        with args.output.open("xb") as stream:
            stream.write(payload)
        args.output.chmod(0o600)
        print(json.dumps({"status": status, "validation": str(args.output), "sha256": hashlib.sha256(payload).hexdigest(), "motion_authorized": False}, sort_keys=True))
        return 0 if status == "validated_pass" else 2
    except (QualificationWorkerError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "invalid", "error": str(exc), "motion_authorized": False}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
