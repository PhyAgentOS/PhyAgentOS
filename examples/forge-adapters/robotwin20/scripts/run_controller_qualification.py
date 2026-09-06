#!/usr/bin/env python3
"""Run an approved, isolated RoboTwin/SAPIEN controller qualification."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from robotwin_controller_qualification_worker import (
    ControllerQualificationWorker,
    QualificationWorkerError,
    SapienQualificationRuntime,
    load_qualification_package,
)

from robotwin20_adapter.controller_qualification import (
    ControllerQualificationEvidence,
    QualificationTestEvidence,
)


def _persist_unavailable(package, artifact_root: Path, reason: str) -> Path:
    root = artifact_root.resolve() / "controller-qualification" / package.plan.qualification_id
    evidence_dir = root / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    tests = []
    for spec in package.plan.tests:
        ref = f"artifact://controller-qualification/{package.plan.qualification_id}/evidence/{spec.test_id}"
        trace = {"schema_version": "paos-robotwin20-controller-qualification-test-trace/v1", "qualification_id": package.plan.qualification_id, "test_id": spec.test_id, "command_family": spec.command_family, "started_at": now, "finished_at": now, "arms": {}, "events": [], "outcome": "unavailable", "failure_reason": reason}
        raw = (json.dumps(trace, sort_keys=True, separators=(",", ":")) + "\n").encode()
        path = evidence_dir / f"{spec.test_id}.json"
        if path.exists() and path.read_bytes() != raw:
            raise QualificationWorkerError("unavailable trace artifact is immutable and divergent")
        if not path.exists():
            with path.open("xb") as stream:
                stream.write(raw)
            path.chmod(0o600)
        tests.append(QualificationTestEvidence(test_id=spec.test_id, command_family=spec.command_family, outcome="unavailable", evidence_ref=ref, evidence_sha256=hashlib.sha256(raw).hexdigest(), controller_status="unavailable"))
    evidence = ControllerQualificationEvidence(qualification_id=package.plan.qualification_id, producer_id="robotwin20-controller-qualification-worker/v1", plan_ref=package.approval.plan_ref, plan_sha256=package.approval.plan_sha256, approval_ref=f"artifact://controller-qualification/{package.plan.qualification_id}/approval", approval_sha256=package.file_digests["approval"], identity=package.plan.identity, status="unavailable", tests=tuple(tests), world_change_started=False, world_change_completed=False, reset_completed=True, outcome_known=True, started_at=now, finished_at=now)
    path = root / "evidence.json"
    raw = (json.dumps(evidence.model_dump(mode="json"), sort_keys=True, separators=(",", ":")) + "\n").encode()
    if path.exists() and path.read_bytes() != raw:
        raise QualificationWorkerError("unavailable evidence artifact is immutable and divergent")
    if not path.exists():
        with path.open("xb") as stream:
            stream.write(raw)
        path.chmod(0o600)
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--approval", type=Path, required=True)
    parser.add_argument("--plan-validation", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--left-capability", type=Path, required=True)
    parser.add_argument("--left-validation", type=Path, required=True)
    parser.add_argument("--right-capability", type=Path, required=True)
    parser.add_argument("--right-validation", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--robotwin-root", type=Path, required=True)
    parser.add_argument("--stop-file", type=Path, required=True)
    parser.add_argument("--max-duration-s", type=float, default=300.0)
    parser.add_argument("--dry-run", action="store_true", help="validate package without creating a provider scene")
    args = parser.parse_args()
    try:
        package = load_qualification_package(
            plan_path=args.plan.resolve(),
            approval_path=args.approval.resolve(),
            plan_validation_path=args.plan_validation.resolve(),
            source_manifest_path=args.source_manifest.resolve(),
            capability_paths={"left": args.left_capability.resolve(), "right": args.right_capability.resolve()},
            validation_paths={"left": args.left_validation.resolve(), "right": args.right_validation.resolve()},
        )
        if args.dry_run:
            print(json.dumps({"status": "validated_qualification_inputs", "qualification_id": package.plan.qualification_id}, sort_keys=True))
            return 0
        try:
            runtime = SapienQualificationRuntime(args.robotwin_root.resolve())
        except QualificationWorkerError as exc:
            path = _persist_unavailable(package, args.artifact_root, str(exc))
            print(json.dumps({"status": "unavailable", "qualification_id": package.plan.qualification_id, "evidence": str(path), "evidence_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "motion_authorized": False}, sort_keys=True))
            return 2
        worker = ControllerQualificationWorker(
            package,
            runtime,
            args.artifact_root.resolve(),
            stop_file=args.stop_file.resolve(),
            max_duration_s=args.max_duration_s,
        )
        evidence, refs = worker.run()
        output_path = args.artifact_root.resolve() / "controller-qualification" / package.plan.qualification_id / "evidence.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = evidence.model_dump(mode="json")
        encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
        if output_path.exists() and output_path.read_bytes() != encoded:
            raise QualificationWorkerError("qualification evidence output is immutable and divergent")
        if not output_path.exists():
            with output_path.open("xb") as stream:
                stream.write(encoded)
            output_path.chmod(0o600)
        print(json.dumps({"status": evidence.status, "qualification_id": evidence.qualification_id, "evidence": str(output_path), "evidence_sha256": hashlib.sha256(encoded).hexdigest(), "test_evidence": refs, "world_change_started": evidence.world_change_started, "motion_authorized": evidence.motion_authorized}, sort_keys=True))
        return 0 if evidence.status == "passed" else 2
    except QualificationWorkerError as exc:
        print(json.dumps({"status": "unavailable", "error": str(exc), "motion_authorized": False}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
