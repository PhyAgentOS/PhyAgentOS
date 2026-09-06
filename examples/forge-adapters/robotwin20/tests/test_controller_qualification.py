from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from robotwin20_adapter.controller_qualification import (
    ControllerQualification,
    ControllerQualificationEvidence,
    ControllerQualificationPlan,
    ControllerQualificationReviewRequest,
    ControllerQualificationValidation,
    QualificationCapabilityBinding,
    QualificationIdentity,
    QualificationTestEvidence,
    QualificationTestSpec,
    controller_qualification_digest,
    validate_controller_qualification_plan_package,
    validate_controller_qualification_result_package,
)
from robotwin20_adapter.motion_capabilities import (
    MotionCapabilityDocument,
    MotionCapabilityValidation,
    motion_capability_digest,
)

SHA = "a" * 64
IDENTITY = QualificationIdentity(
    robot_identity="franka-panda",
    arm_ids=("left", "right"),
    simulator_version="3.0.0b1",
    controller_version="source-controller",
    runtime_python_version="3.10.21",
    robotwin_git_revision="b" * 40,
)
TEST_IDS = (
    "nominal_position_command",
    "nominal_velocity_command",
    "over_limit_velocity_command",
    "contact_load",
    "dropped_step",
    "stop_path",
    "error_path",
    "reset_path",
)


def _binding(arm: str) -> QualificationCapabilityBinding:
    return QualificationCapabilityBinding(
        arm_id=arm,
        artifact_ref=f"artifact://robotwin/franka/{arm}-motion-capabilities",
        sha256=SHA,
        validation_ref=f"artifact://robotwin/franka/{arm}-motion-capabilities-source-validation",
        validation_sha256="b" * 64,
    )


def _plan() -> ControllerQualificationPlan:
    specs = tuple(
        QualificationTestSpec(
            test_id=test_id,
            command_family=(
                "position_drive_target" if "position" in test_id else "velocity_drive_target"
            ),
            arm_ids=("left", "right"),
        )
        for test_id in TEST_IDS
    )
    return ControllerQualificationPlan(
        qualification_id="blocks-ranking-rgb-controller-q1",
        producer_id="robotwin20-controller-qualification-worker/v1",
        created_at="2026-09-06T08:00:00+00:00",
        identity=IDENTITY,
        capability_bindings=(_binding("left"), _binding("right")),
        source_manifest_ref="artifact://route/source-manifest",
        source_manifest_sha256=SHA,
        command_families=("position_drive_target", "velocity_drive_target"),
        tests=specs,
        required_signals=(
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
        ),
    )


def _evidence(outcome: str = "pass") -> ControllerQualificationEvidence:
    tests = tuple(
        QualificationTestEvidence(
            test_id=test_id,
            command_family=(
                "position_drive_target" if "position" in test_id else "velocity_drive_target"
            ),
            outcome=outcome,
            evidence_ref=f"artifact://qualification/evidence/{test_id}",
            evidence_sha256=SHA,
            observed_max_joint_velocity_radps=1.0,
            controller_status="reset" if test_id == "reset_path" else "ok",
        )
        for test_id in TEST_IDS
    )
    return ControllerQualificationEvidence(
        qualification_id="blocks-ranking-rgb-controller-q1",
        producer_id="robotwin20-controller-qualification-worker/v1",
        plan_ref="artifact://qualification/plan",
        plan_sha256=SHA,
        approval_ref="artifact://qualification/review",
        approval_sha256="b" * 64,
        identity=IDENTITY,
        status=("passed" if outcome == "pass" else "failed"),
        tests=tests,
        world_change_started=True,
        world_change_completed=True,
        reset_completed=True,
        outcome_known=True,
        started_at="2026-09-06T08:01:00+00:00",
        finished_at="2026-09-06T08:02:00+00:00",
    )


def test_plan_requires_both_arms_and_complete_test_matrix():
    plan = _plan()
    assert plan.identity.arm_ids == ("left", "right")
    assert len(plan.tests) == 8
    assert plan.qualification_motion_authorized is False
    assert controller_qualification_digest(plan) == controller_qualification_digest(
        json.loads(json.dumps(plan.model_dump(mode="json")))
    )


def test_plan_rejects_incomplete_matrix():
    payload = _plan().model_dump(mode="json")
    payload["tests"] = payload["tests"][:-1]
    with pytest.raises(ValueError, match="test matrix"):
        ControllerQualificationPlan.model_validate(payload)


def test_passed_evidence_requires_all_tests_and_reset():
    evidence = _evidence()
    assert evidence.status == "passed"
    payload = evidence.model_dump(mode="json")
    payload["reset_completed"] = False
    with pytest.raises(ValueError, match="passed qualification evidence"):
        ControllerQualificationEvidence.model_validate(payload)


def test_validation_must_be_independent_and_cannot_authorize_motion():
    validation = ControllerQualificationValidation(
        qualification_id="blocks-ranking-rgb-controller-q1",
        evidence_ref="artifact://qualification/evidence",
        evidence_sha256=SHA,
        validator_id="independent-validator/v1",
        producer_id="robotwin20-controller-qualification-worker/v1",
        validated_at="2026-09-06T08:03:00+00:00",
        status="validated_pass",
        checks=("identity", "command_family", "all_test_evidence", "reset", "enforcement"),
        controller_enforced=True,
    )
    assert validation.motion_authorized is False
    payload = validation.model_dump(mode="json")
    payload["validator_id"] = validation.producer_id
    with pytest.raises(ValueError, match="independent"):
        ControllerQualificationValidation.model_validate(payload)


def test_final_record_cannot_claim_enforcement_on_failure():
    evidence = _evidence("fail")
    assert evidence.status == "failed"
    with pytest.raises(ValueError, match="status and enforcement"):
        ControllerQualification(
            qualification_id=evidence.qualification_id,
            plan_ref=evidence.plan_ref,
            plan_sha256=evidence.plan_sha256,
            evidence_ref="artifact://qualification/evidence",
            evidence_sha256=controller_qualification_digest(evidence),
            validation_ref="artifact://qualification/validation",
            validation_sha256="b" * 64,
            identity=IDENTITY,
            status="reviewed_failure",
            reviewer_id="yanxu",
            reviewed_at="2026-09-06T08:04:00+00:00",
            independent_execution_qualification=True,
            controller_enforced=True,
        )


def _approved_result_chain():
    plan = _plan()
    plan_digest = controller_qualification_digest(plan)
    evidence = _evidence().model_copy(
        update={
            "plan_ref": "artifact://qualification/plan",
            "plan_sha256": plan_digest,
        }
    )
    evidence_digest = controller_qualification_digest(evidence)
    validation = ControllerQualificationValidation(
        qualification_id=plan.qualification_id,
        evidence_ref="artifact://qualification/evidence",
        evidence_sha256=evidence_digest,
        validator_id="independent-validator/v1",
        producer_id=evidence.producer_id,
        validated_at="2026-09-06T08:03:00+00:00",
        status="validated_pass",
        checks=("identity", "all_tests", "controller_enforcement", "reset"),
        controller_enforced=True,
    )
    validation_digest = controller_qualification_digest(validation)
    qualification = ControllerQualification(
        qualification_id=plan.qualification_id,
        plan_ref=evidence.plan_ref,
        plan_sha256=plan_digest,
        evidence_ref=validation.evidence_ref,
        evidence_sha256=evidence_digest,
        validation_ref="artifact://qualification/validation",
        validation_sha256=validation_digest,
        identity=plan.identity,
        status="approved_pass",
        reviewer_id="yanxu",
        reviewed_at="2026-09-06T08:04:00+00:00",
        independent_execution_qualification=True,
        controller_enforced=True,
    )
    return qualification, plan, evidence, validation


def test_approved_result_package_is_cross_bound():
    qualification, plan, evidence, validation = _approved_result_chain()
    validate_controller_qualification_result_package(
        qualification=qualification,
        plan=plan,
        evidence=evidence,
        validation=validation,
        qualification_file_sha256=controller_qualification_digest(qualification),
        plan_file_sha256=controller_qualification_digest(plan),
        evidence_file_sha256=controller_qualification_digest(evidence),
        validation_file_sha256=controller_qualification_digest(validation),
    )


def test_result_package_rejects_digest_and_identity_drift():
    qualification, plan, evidence, validation = _approved_result_chain()
    with pytest.raises(ValueError, match="qualification file digest"):
        validate_controller_qualification_result_package(
            qualification=qualification,
            plan=plan,
            evidence=evidence,
            validation=validation,
            qualification_file_sha256="0" * 64,
            plan_file_sha256=controller_qualification_digest(plan),
            evidence_file_sha256=controller_qualification_digest(evidence),
            validation_file_sha256=controller_qualification_digest(validation),
        )
    drifted = evidence.model_copy(
        update={"identity": evidence.identity.model_copy(update={"robot_identity": "other"})}
    )
    with pytest.raises(ValueError, match="provider identity drifted"):
        validate_controller_qualification_result_package(
            qualification=qualification,
            plan=plan,
            evidence=drifted,
            validation=validation,
            qualification_file_sha256=controller_qualification_digest(qualification),
            plan_file_sha256=controller_qualification_digest(plan),
            evidence_file_sha256=controller_qualification_digest(drifted),
            validation_file_sha256=controller_qualification_digest(validation),
        )


def test_review_request_is_simulation_only():
    request = ControllerQualificationReviewRequest(
        qualification_id="blocks-ranking-rgb-controller-q1",
        plan_ref="artifact://qualification/plan",
        plan_sha256=SHA,
        source_manifest_ref="artifact://route/source-manifest",
        source_manifest_sha256=SHA,
    )
    assert request.qualification_motion_authorized is False
    assert request.benchmark_motion_authorized is False
    assert request.hardware_motion_authorized is False


def test_cli_validates_plan(tmp_path: Path):
    artifact = tmp_path / "plan.json"
    artifact.write_text(json.dumps(_plan().model_dump(mode="json")), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "examples/forge-adapters/robotwin20/scripts/validate_controller_qualification.py",
            "--kind",
            "plan",
            "--artifact",
            str(artifact),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    output = json.loads(result.stdout)
    assert output["status"] == "valid"
    assert output["schema_version"].endswith("plan/v1")


def _capability(arm: str) -> MotionCapabilityDocument:
    limit = [1.0] * 7
    sources = [
        {"role": role, "relative_path": path, "sha256": SHA}
        for role, path in (
            ("robot_description", "assets/embodiments/franka-panda/panda.urdf"),
            ("embodiment_profile", "assets/embodiments/franka-panda/config.yml"),
            ("planner_profile", "assets/embodiments/franka-panda/curobo.yml"),
            ("planner_source", "envs/robot/planner.py"),
            ("simulator_source", "envs/_base_task.py"),
            ("controller_source", "envs/robot/robot.py"),
        )
    ]
    return MotionCapabilityDocument.model_validate(
        {
            "robot_identity": "franka-panda",
            "arm_id": arm,
            "runtime_kind": "simulation",
            "provider": {
                "robotwin_git_revision": "b" * 40,
                "simulator_id": "sapien",
                "simulator_version": "3.0.0b1",
                "planner_id": "curobo",
                "planner_version": "0.7.8",
                "controller_id": "robotwin-sapien-drive-target",
                "controller_version": "source-controller",
                "runtime_python_version": "3.10.21",
            },
            "joint_order": [f"panda_joint{i}" for i in range(1, 8)],
            "limits": {
                "position_lower_rad": [-2.0] * 7,
                "position_upper_rad": [2.0] * 7,
                "velocity_lower_radps": [-1.0] * 7,
                "velocity_upper_radps": limit,
                "acceleration_radps2": limit,
                "jerk_radps3": limit,
                "effort_nm": limit,
            },
            "enforcement": {
                "joint_position": "planner_constrained",
                "joint_velocity": "planner_constrained",
                "joint_acceleration": "planner_constrained",
                "joint_jerk": "planner_constrained",
                "cartesian_velocity": "unknown",
                "joint_effort": "unknown",
                "drive_position_target": True,
                "drive_velocity_target": True,
                "drive_force_limit_bound": False,
            },
            "timing": {
                "planner_dt_s": 0.004,
                "simulator_default_dt_s": 0.004,
                "controller_dt_s": None,
            },
            "sources": sources,
            "controller_qualification_ref": None,
            "motion_authorized": False,
        }
    )


def test_materializer_creates_no_motion_review_package(tmp_path: Path):
    args = []
    for arm in ("left", "right"):
        capability = _capability(arm)
        capability_path = tmp_path / f"{arm}-capability.json"
        capability_path.write_bytes(
            json.dumps(
                capability.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode()
            + b"\n"
        )
        validation = MotionCapabilityValidation(
            capability_sha256=motion_capability_digest(capability),
            verifier_id="source-validator/v1",
            verified_at="2026-09-06T07:00:00+00:00",
            status="validated_planner_constraints",
            checks=(
                "source_digests",
                "runtime_identity",
                "joint_order",
                "per_joint_limits",
                "planner_timing",
                "simulator_timing",
                "drive_semantics",
                "no_controller_enforcement_claim",
            ),
        )
        validation_path = tmp_path / f"{arm}-validation.json"
        validation_path.write_text(json.dumps(validation.model_dump(mode="json")), encoding="utf-8")
        args.extend(
            [
                f"--{arm}-capability",
                str(capability_path),
                f"--{arm}-validation",
                str(validation_path),
                f"--{arm}-capability-ref",
                f"artifact://robotwin/franka/{arm}-motion-capabilities",
                f"--{arm}-validation-ref",
                f"artifact://robotwin/franka/{arm}-source-validation",
            ]
        )
    output_dir = tmp_path / "qualification-package"
    result = subprocess.run(
        [
            sys.executable,
            "examples/forge-adapters/robotwin20/scripts/materialize_controller_qualification_plan.py",
            "--qualification-id",
            "qualification-q1",
            "--created-at",
            "2026-09-06T08:00:00+00:00",
            "--output-dir",
            str(output_dir),
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    summary = json.loads(result.stdout)
    assert summary["status"] == "pending_human_review"
    assert summary["world_change_started"] is False
    assert summary["qualification_motion_authorized"] is False
    assert (
        ControllerQualificationPlan.model_validate_json(
            (output_dir / "qualification_plan.json").read_text()
        ).qualification_motion_authorized
        is False
    )
    validation_path = output_dir / "no-motion-validation.json"
    verify = subprocess.run(
        [
            sys.executable,
            "examples/forge-adapters/robotwin20/scripts/verify_controller_qualification_plan.py",
            "--plan",
            str(output_dir / "qualification_plan.json"),
            "--source-manifest",
            str(output_dir / "source_manifest.json"),
            "--review-request",
            str(output_dir / "human_review_request.json"),
            "--left-capability",
            str(tmp_path / "left-capability.json"),
            "--left-validation",
            str(tmp_path / "left-validation.json"),
            "--right-capability",
            str(tmp_path / "right-capability.json"),
            "--right-validation",
            str(tmp_path / "right-validation.json"),
            "--verifier-id",
            "independent-plan-validator/v1",
            "--output",
            str(validation_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(verify.stdout)["world_change_started"] is False


def test_approval_cli_rejects_wrong_phrase_and_never_authorizes_benchmark(tmp_path: Path):
    import hashlib

    output_dir = tmp_path / "package"
    output_dir.mkdir()
    plan = _plan()
    from robotwin20_adapter import (
        ControllerQualificationPlanValidation,
        ControllerQualificationSourceManifest,
    )

    manifest = ControllerQualificationSourceManifest(
        qualification_id=plan.qualification_id,
        producer_id=plan.producer_id,
        created_at=plan.created_at,
        identity=plan.identity,
        capability_bindings=plan.capability_bindings,
    )
    manifest_path = output_dir / "source_manifest.json"
    manifest_path.write_bytes(
        json.dumps(manifest.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )
    plan = plan.model_copy(
        update={"source_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest()}
    )
    plan_path = output_dir / "plan.json"
    plan_path.write_bytes(
        json.dumps(plan.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )
    prefix = plan.source_manifest_ref.removesuffix("/source-manifest")
    review = ControllerQualificationReviewRequest(
        qualification_id=plan.qualification_id,
        plan_ref=f"{prefix}/plan",
        plan_sha256=hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        source_manifest_ref=plan.source_manifest_ref,
        source_manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    )
    review_path = output_dir / "review.json"
    review_path.write_bytes(
        json.dumps(review.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        + b"\n"
    )
    validation = ControllerQualificationPlanValidation(
        qualification_id=plan.qualification_id,
        plan_sha256=hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        source_manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        review_request_sha256=hashlib.sha256(review_path.read_bytes()).hexdigest(),
        verifier_id="independent-validator/v1",
        verified_at="2026-09-06T08:00:00+00:00",
        checks=(
            "plan_schema",
            "source_manifest_binding",
            "review_request_binding",
            "left_capability_binding",
            "right_capability_binding",
            "provider_identity",
            "unqualified_source_state",
            "no_motion_authority",
        ),
    )
    validation_path = output_dir / "validation.json"
    validation_path.write_bytes(
        json.dumps(
            validation.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
        + b"\n"
    )
    files = {
        "plan": plan_path,
        "source-manifest": manifest_path,
        "review-request": review_path,
        "plan-validation": validation_path,
    }
    command = [
        sys.executable,
        "examples/forge-adapters/robotwin20/scripts/approve_controller_qualification_plan.py",
        "--plan",
        str(plan_path),
        "--source-manifest",
        str(manifest_path),
        "--review-request",
        str(review_path),
        "--plan-validation",
        str(validation_path),
        "--reviewer-id",
        "reviewer-1",
    ]
    for name, path in files.items():
        command.extend([f"--confirm-{name}-digest", hashlib.sha256(path.read_bytes()).hexdigest()])
    output = output_dir / "approval.json"
    rejected = subprocess.run(
        [*command, "--approve-qualification-simulation-only", "WRONG", "--output", str(output)],
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0 and not output.exists()
    approved = subprocess.run(
        [
            *command,
            "--approve-qualification-simulation-only",
            "I_REVIEWED_AND_APPROVE_CONTROLLER_QUALIFICATION_SIMULATION_ONLY",
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    summary = json.loads(approved.stdout)
    assert summary["qualification_motion_authorized"] is True
    assert summary["benchmark_motion_authorized"] is False
    assert summary["hardware_motion_authorized"] is False
    assert summary["motion_authorized"] is False


def test_package_validation_rejects_provider_identity_drift():
    from robotwin20_adapter import ControllerQualificationSourceManifest

    capabilities = {arm: _capability(arm) for arm in ("left", "right")}
    validations = {
        arm: MotionCapabilityValidation(
            capability_sha256=motion_capability_digest(capabilities[arm]),
            verifier_id="source-validator/v1",
            verified_at="2026-09-06T07:00:00+00:00",
            status="validated_planner_constraints",
            checks=(
                "source_digests",
                "runtime_identity",
                "joint_order",
                "per_joint_limits",
                "planner_timing",
                "simulator_timing",
                "drive_semantics",
                "no_controller_enforcement_claim",
            ),
        )
        for arm in capabilities
    }
    validation_digests = {
        arm: controller_qualification_digest(value) for arm, value in validations.items()
    }
    bindings = tuple(
        QualificationCapabilityBinding(
            arm_id=arm,
            artifact_ref=f"artifact://robotwin/franka/{arm}-motion-capabilities",
            sha256=motion_capability_digest(capabilities[arm]),
            validation_ref=f"artifact://robotwin/franka/{arm}-source-validation",
            validation_sha256=validation_digests[arm],
        )
        for arm in ("left", "right")
    )
    plan = _plan().model_copy(update={"capability_bindings": bindings})
    manifest = ControllerQualificationSourceManifest(
        qualification_id=plan.qualification_id,
        producer_id=plan.producer_id,
        created_at=plan.created_at,
        identity=plan.identity,
        capability_bindings=bindings,
    )
    plan = plan.model_copy(
        update={"source_manifest_sha256": controller_qualification_digest(manifest)}
    )
    prefix = plan.source_manifest_ref.removesuffix("/source-manifest")
    review = ControllerQualificationReviewRequest(
        qualification_id=plan.qualification_id,
        plan_ref=f"{prefix}/plan",
        plan_sha256=controller_qualification_digest(plan),
        source_manifest_ref=plan.source_manifest_ref,
        source_manifest_sha256=controller_qualification_digest(manifest),
    )
    drifted = capabilities["right"].model_copy(
        update={
            "provider": capabilities["right"].provider.model_copy(
                update={"controller_version": "drifted-controller"}
            )
        }
    )
    with pytest.raises(ValueError, match="provider identity drifted"):
        validate_controller_qualification_plan_package(
            plan=plan,
            source_manifest=manifest,
            review_request=review,
            capabilities={"left": capabilities["left"], "right": drifted},
            capability_file_sha256={
                arm: motion_capability_digest(value) for arm, value in capabilities.items()
            },
            validations=validations,
            validation_file_sha256=validation_digests,
        )
