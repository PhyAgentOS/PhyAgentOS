#!/usr/bin/env python3
"""Create a no-motion controller-qualification plan and human review request."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from robotwin20_adapter import (
    ControllerQualificationPlan,
    ControllerQualificationReviewRequest,
    ControllerQualificationSourceManifest,
    MotionCapabilityDocument,
    MotionCapabilityValidation,
    QualificationCapabilityBinding,
    QualificationIdentity,
    QualificationTestSpec,
    canonical_controller_qualification,
    motion_capability_digest,
)

TESTS = (
    ("nominal_position_command", "position_drive_target"),
    ("nominal_velocity_command", "velocity_drive_target"),
    ("over_limit_velocity_command", "velocity_drive_target"),
    ("contact_load", "velocity_drive_target"),
    ("dropped_step", "velocity_drive_target"),
    ("stop_path", "velocity_drive_target"),
    ("error_path", "velocity_drive_target"),
    ("reset_path", "position_drive_target"),
)
REQUIRED_SIGNALS = (
    "commanded_joint_position",
    "commanded_joint_velocity",
    "observed_joint_position",
    "observed_joint_velocity",
    "observed_tcp_pose",
    "derived_tcp_velocity",
    "contacts",
    "controller_status",
    "simulator_step_and_time",
    "stop_error_reset_status",
)


class MaterializationError(RuntimeError):
    pass


def _load(path: Path, model: type, label: str):
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise MaterializationError(f"{label} must be an absolute regular file")
    try:
        value = model.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise MaterializationError(f"{label} is invalid") from exc
    return value


def _file_sha(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise MaterializationError("qualification source cannot be read") from exc


def _write_new(path: Path, value: Any) -> str:
    payload = canonical_controller_qualification(value)
    if not path.is_absolute() or path.exists() or path.is_symlink():
        raise MaterializationError("qualification output must be a new absolute file")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)
    path.chmod(0o600)
    return hashlib.sha256(payload).hexdigest()


def _binding(args: argparse.Namespace, arm: str):
    capability_path = getattr(args, f"{arm}_capability")
    validation_path = getattr(args, f"{arm}_validation")
    capability = _load(capability_path, MotionCapabilityDocument, f"{arm} capability")
    validation = _load(validation_path, MotionCapabilityValidation, f"{arm} validation")
    canonical_sha = motion_capability_digest(capability)
    if (
        capability.arm_id != arm
        or capability.motion_authorized is not False
        or capability.controller_qualification_ref is not None
        or validation.capability_sha256 != canonical_sha
        or validation.independent_execution_qualification is not False
        or validation.controller_enforced is not False
        or validation.motion_authorized is not False
        or _file_sha(capability_path) != canonical_sha
    ):
        raise MaterializationError(
            f"{arm} capability source is not an unqualified canonical binding"
        )
    binding = QualificationCapabilityBinding(
        arm_id=arm,
        artifact_ref=getattr(args, f"{arm}_capability_ref"),
        sha256=canonical_sha,
        validation_ref=getattr(args, f"{arm}_validation_ref"),
        validation_sha256=_file_sha(validation_path),
    )
    return capability, binding


def materialize(args: argparse.Namespace) -> dict[str, Any]:
    if (
        not args.output_dir.is_absolute()
        or args.output_dir.exists()
        or args.output_dir.is_symlink()
    ):
        raise MaterializationError("output directory must be a new absolute path")
    left, left_binding = _binding(args, "left")
    right, right_binding = _binding(args, "right")
    if left.robot_identity != right.robot_identity or left.provider != right.provider:
        raise MaterializationError("left/right controller qualification identity differs")
    created_at = args.created_at or datetime.now(timezone.utc).isoformat()
    identity = QualificationIdentity(
        robot_identity=left.robot_identity,
        arm_ids=("left", "right"),
        simulator_id=left.provider.simulator_id,
        simulator_version=left.provider.simulator_version,
        controller_id=left.provider.controller_id,
        controller_version=left.provider.controller_version,
        runtime_python_version=left.provider.runtime_python_version,
        robotwin_git_revision=left.provider.robotwin_git_revision,
    )
    bindings = (left_binding, right_binding)
    prefix = f"artifact://controller-qualification/{args.qualification_id}"
    manifest = ControllerQualificationSourceManifest(
        qualification_id=args.qualification_id,
        producer_id=args.producer_id,
        created_at=created_at,
        identity=identity,
        capability_bindings=bindings,
    )
    staging = args.output_dir.with_name(f".{args.output_dir.name}.staging-{os.getpid()}")
    if staging.exists() or staging.is_symlink():
        raise MaterializationError("qualification staging path already exists")
    manifest_path = staging / "source_manifest.json"
    try:
        manifest_sha = _write_new(manifest_path, manifest)
        plan = ControllerQualificationPlan(
            qualification_id=args.qualification_id,
            producer_id=args.producer_id,
            created_at=created_at,
            identity=identity,
            capability_bindings=bindings,
            source_manifest_ref=f"{prefix}/source-manifest",
            source_manifest_sha256=manifest_sha,
            command_families=("position_drive_target", "velocity_drive_target"),
            tests=tuple(
                QualificationTestSpec(
                    test_id=test_id,
                    command_family=family,
                    arm_ids=("left", "right"),
                )
                for test_id, family in TESTS
            ),
            required_signals=REQUIRED_SIGNALS,
        )
        plan_path = staging / "qualification_plan.json"
        plan_sha = _write_new(plan_path, plan)
        review = ControllerQualificationReviewRequest(
            qualification_id=args.qualification_id,
            plan_ref=f"{prefix}/plan",
            plan_sha256=plan_sha,
            source_manifest_ref=plan.source_manifest_ref,
            source_manifest_sha256=manifest_sha,
        )
        review_path = staging / "human_review_request.json"
        review_sha = _write_new(review_path, review)
        staging.rename(args.output_dir)
    except Exception:
        if staging.is_dir() and not staging.is_symlink():
            shutil.rmtree(staging)
        raise
    manifest_path = args.output_dir / manifest_path.name
    plan_path = args.output_dir / plan_path.name
    review_path = args.output_dir / review_path.name
    return {
        "status": "pending_human_review",
        "qualification_plan": str(plan_path),
        "qualification_plan_sha256": plan_sha,
        "source_manifest": str(manifest_path),
        "source_manifest_sha256": manifest_sha,
        "human_review_request": str(review_path),
        "human_review_request_sha256": review_sha,
        "world_change_started": False,
        "qualification_motion_authorized": False,
        "benchmark_motion_authorized": False,
        "hardware_motion_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qualification-id", required=True)
    parser.add_argument("--producer-id", default="robotwin20-controller-qualification-worker/v1")
    parser.add_argument("--created-at")
    for arm in ("left", "right"):
        parser.add_argument(f"--{arm}-capability", type=Path, required=True)
        parser.add_argument(f"--{arm}-validation", type=Path, required=True)
        parser.add_argument(f"--{arm}-capability-ref", required=True)
        parser.add_argument(f"--{arm}-validation-ref", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    result = materialize(parser.parse_args())
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
