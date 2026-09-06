"""Strict, provider-owned RoboTwin controller-qualification contracts.

The contracts separate a pre-motion plan, human review request, execution
evidence, independent validation, and the final reviewed qualification. This
module performs deterministic validation only: it never imports SAPIEN, issues
drive targets, steps a scene, or grants PAOS motion authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from .motion_capabilities import (
    MotionCapabilityDocument,
    MotionCapabilityValidation,
    motion_capability_digest,
)

CONTROLLER_QUALIFICATION_PLAN_SCHEMA_VERSION = "paos-robotwin20-controller-qualification-plan/v1"
CONTROLLER_QUALIFICATION_SOURCE_MANIFEST_SCHEMA_VERSION = (
    "paos-robotwin20-controller-qualification-source-manifest/v1"
)
CONTROLLER_QUALIFICATION_PLAN_VALIDATION_SCHEMA_VERSION = (
    "paos-robotwin20-controller-qualification-plan-validation/v1"
)
CONTROLLER_QUALIFICATION_APPROVAL_SCHEMA_VERSION = (
    "paos-robotwin20-controller-qualification-approval/v1"
)
CONTROLLER_QUALIFICATION_REVIEW_REQUEST_SCHEMA_VERSION = (
    "paos-robotwin20-controller-qualification-review-request/v1"
)
CONTROLLER_QUALIFICATION_EVIDENCE_SCHEMA_VERSION = (
    "paos-robotwin20-controller-qualification-evidence/v1"
)
CONTROLLER_QUALIFICATION_VALIDATION_SCHEMA_VERSION = (
    "paos-robotwin20-controller-qualification-validation/v1"
)
CONTROLLER_QUALIFICATION_SCHEMA_VERSION = "paos-robotwin20-controller-qualification/v1"

QualificationTestId = Literal[
    "nominal_position_command",
    "nominal_velocity_command",
    "over_limit_velocity_command",
    "contact_load",
    "dropped_step",
    "stop_path",
    "error_path",
    "reset_path",
]
CommandFamily = Literal["position_drive_target", "velocity_drive_target"]
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_REF = re.compile(r"^artifact://[^/]+(?:/[^/]+)+$")
_REQUIRED_TESTS = frozenset(QualificationTestId.__args__)
_REQUIRED_SIGNALS = frozenset(
    {
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
    }
)
_PLAN_VALIDATION_CHECKS = (
    "plan_schema",
    "source_manifest_binding",
    "review_request_binding",
    "left_capability_binding",
    "right_capability_binding",
    "provider_identity",
    "unqualified_source_state",
    "no_motion_authority",
)


class ControllerQualificationError(ValueError):
    """A qualification input or artifact binding is invalid."""


def _digest(value: str, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _artifact(value: str, label: str) -> str:
    if not isinstance(value, str) or _ARTIFACT_REF.fullmatch(value) is None:
        raise ValueError(f"{label} must be an artifact reference")
    return value


def _identity_text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(c.isspace() for c in value):
        raise ValueError(f"{label} is invalid")
    return value.strip()


def _timestamp(value: str, label: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return value


class QualificationIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    robot_identity: str
    arm_ids: tuple[Literal["left", "right"], ...]
    simulator_id: Literal["sapien"] = "sapien"
    simulator_version: str
    controller_id: Literal[
        "robotwin-sapien-drive-target",
        "paos-robotwin-capability-bounded-drive-target",
    ] = "robotwin-sapien-drive-target"
    controller_version: str
    runtime_python_version: str
    robotwin_git_revision: str

    @field_validator(
        "robot_identity",
        "simulator_version",
        "controller_version",
        "runtime_python_version",
        "robotwin_git_revision",
    )
    @classmethod
    def validate_identity(cls, value: str) -> str:
        return _identity_text(value, "controller qualification identity")

    @field_validator("arm_ids")
    @classmethod
    def validate_arms(cls, value: tuple[Literal["left", "right"], ...]):
        if set(value) != {"left", "right"} or len(value) != 2:
            raise ValueError("controller qualification must cover both route arms")
        return value


class QualificationCapabilityBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    arm_id: Literal["left", "right"]
    artifact_ref: str
    sha256: str
    validation_ref: str
    validation_sha256: str

    @field_validator("artifact_ref", "validation_ref")
    @classmethod
    def validate_ref(cls, value: str) -> str:
        return _artifact(value, "qualification capability reference")

    @field_validator("sha256", "validation_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        return _digest(value, "qualification capability digest")


class QualificationTestSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    test_id: QualificationTestId
    command_family: CommandFamily
    arm_ids: tuple[Literal["left", "right"], ...]
    limit_source: Literal["motion_capability"] = "motion_capability"

    @field_validator("arm_ids")
    @classmethod
    def validate_arms(cls, value: tuple[Literal["left", "right"], ...]):
        if set(value) != {"left", "right"} or len(value) != 2:
            raise ValueError("qualification test must cover both arms")
        return value


class ControllerQualificationSourceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["paos-robotwin20-controller-qualification-source-manifest/v1"] = (
        CONTROLLER_QUALIFICATION_SOURCE_MANIFEST_SCHEMA_VERSION
    )
    qualification_id: str
    producer_id: str
    created_at: str
    identity: QualificationIdentity
    capability_bindings: tuple[QualificationCapabilityBinding, ...]
    test_protocol_schema_version: Literal["paos-robotwin20-controller-qualification-tests/v1"] = (
        "paos-robotwin20-controller-qualification-tests/v1"
    )
    motion_authorized: Literal[False] = False

    @field_validator("qualification_id", "producer_id")
    @classmethod
    def validate_identity_text(cls, value: str) -> str:
        return _identity_text(value, "qualification source manifest identity")

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: str) -> str:
        return _timestamp(value, "qualification source manifest created_at")

    @model_validator(mode="after")
    def validate_bindings(self) -> "ControllerQualificationSourceManifest":
        if {item.arm_id for item in self.capability_bindings} != {"left", "right"} or len(
            self.capability_bindings
        ) != 2:
            raise ValueError(
                "qualification source manifest arm coverage is incomplete or duplicated"
            )
        return self


class ControllerQualificationPlan(BaseModel):
    """Digest-bound plan for a future isolated simulation qualification run."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["paos-robotwin20-controller-qualification-plan/v1"] = (
        CONTROLLER_QUALIFICATION_PLAN_SCHEMA_VERSION
    )
    qualification_id: str
    producer_id: str
    created_at: str
    identity: QualificationIdentity
    capability_bindings: tuple[QualificationCapabilityBinding, ...]
    source_manifest_ref: str
    source_manifest_sha256: str
    scene_mode: Literal["isolated_no_task_objects"] = "isolated_no_task_objects"
    command_families: tuple[CommandFamily, ...]
    tests: tuple[QualificationTestSpec, ...]
    required_signals: tuple[str, ...]
    stop_file_required: Literal[True] = True
    poll_stop_each_step: Literal[True] = True
    reset_required: Literal[True] = True
    world_change_requested: Literal[True] = True
    qualification_motion_authorized: Literal[False] = False
    benchmark_motion_authorized: Literal[False] = False
    hardware_motion_authorized: Literal[False] = False

    @field_validator("qualification_id", "producer_id")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _identity_text(value, "controller qualification plan identity")

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: str) -> str:
        return _timestamp(value, "controller qualification created_at")

    @field_validator("source_manifest_ref")
    @classmethod
    def validate_manifest_ref(cls, value: str) -> str:
        return _artifact(value, "qualification source manifest reference")

    @field_validator("source_manifest_sha256")
    @classmethod
    def validate_manifest_sha256(cls, value: str) -> str:
        return _digest(value, "qualification source manifest digest")

    @model_validator(mode="after")
    def validate_plan(self) -> "ControllerQualificationPlan":
        if {item.arm_id for item in self.capability_bindings} != {"left", "right"} or len(
            self.capability_bindings
        ) != 2:
            raise ValueError("qualification capability arm coverage is incomplete or duplicated")
        if (
            set(self.command_families) != {"position_drive_target", "velocity_drive_target"}
            or len(self.command_families) != 2
        ):
            raise ValueError("qualification command-family coverage is incomplete")
        if {item.test_id for item in self.tests} != _REQUIRED_TESTS or len(self.tests) != len(
            _REQUIRED_TESTS
        ):
            raise ValueError("qualification test matrix is incomplete or duplicated")
        if any(item.command_family not in self.command_families for item in self.tests):
            raise ValueError("qualification test command family is outside plan scope")
        if set(self.required_signals) != _REQUIRED_SIGNALS or len(self.required_signals) != len(
            _REQUIRED_SIGNALS
        ):
            raise ValueError("qualification required signals are incomplete or duplicated")
        return self


class ControllerQualificationReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["paos-robotwin20-controller-qualification-review-request/v1"] = (
        CONTROLLER_QUALIFICATION_REVIEW_REQUEST_SCHEMA_VERSION
    )
    decision: Literal["pending_human_review"] = "pending_human_review"
    qualification_id: str
    plan_ref: str
    plan_sha256: str
    source_manifest_ref: str
    source_manifest_sha256: str
    required_approval_phrase: Literal[
        "I_REVIEWED_AND_APPROVE_CONTROLLER_QUALIFICATION_SIMULATION_ONLY"
    ] = "I_REVIEWED_AND_APPROVE_CONTROLLER_QUALIFICATION_SIMULATION_ONLY"
    required_reviewer: Literal["human"] = "human"
    qualification_motion_authorized: Literal[False] = False
    benchmark_motion_authorized: Literal[False] = False
    hardware_motion_authorized: Literal[False] = False

    @field_validator("qualification_id")
    @classmethod
    def validate_qualification_id(cls, value: str) -> str:
        return _identity_text(value, "controller qualification review identity")

    @field_validator("plan_ref", "source_manifest_ref")
    @classmethod
    def validate_refs(cls, value: str) -> str:
        return _artifact(value, "controller qualification review reference")

    @field_validator("plan_sha256", "source_manifest_sha256")
    @classmethod
    def validate_digests(cls, value: str) -> str:
        return _digest(value, "controller qualification review digest")


class ControllerQualificationPlanValidation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["paos-robotwin20-controller-qualification-plan-validation/v1"] = (
        CONTROLLER_QUALIFICATION_PLAN_VALIDATION_SCHEMA_VERSION
    )
    status: Literal["validated_no_motion_plan"] = "validated_no_motion_plan"
    qualification_id: str
    plan_sha256: str
    source_manifest_sha256: str
    review_request_sha256: str
    verifier_id: str
    verified_at: str
    checks: tuple[str, ...]
    world_change_started: Literal[False] = False
    qualification_motion_authorized: Literal[False] = False
    benchmark_motion_authorized: Literal[False] = False
    hardware_motion_authorized: Literal[False] = False

    @field_validator("qualification_id", "verifier_id")
    @classmethod
    def validate_identity_text(cls, value: str) -> str:
        return _identity_text(value, "qualification plan validation identity")

    @field_validator("plan_sha256", "source_manifest_sha256", "review_request_sha256")
    @classmethod
    def validate_digests(cls, value: str) -> str:
        return _digest(value, "qualification plan validation digest")

    @field_validator("verified_at")
    @classmethod
    def validate_verified_at(cls, value: str) -> str:
        return _timestamp(value, "qualification plan validated_at")

    @field_validator("checks")
    @classmethod
    def validate_checks(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != _PLAN_VALIDATION_CHECKS:
            raise ValueError("qualification plan validation checks are incomplete")
        return value


class ControllerQualificationApproval(BaseModel):
    """Human approval for the isolated qualification test only."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["paos-robotwin20-controller-qualification-approval/v1"] = (
        CONTROLLER_QUALIFICATION_APPROVAL_SCHEMA_VERSION
    )
    decision: Literal["approved_controller_qualification_simulation_only"]
    qualification_id: str
    plan_ref: str
    plan_sha256: str
    source_manifest_ref: str
    source_manifest_sha256: str
    plan_validation_ref: str
    plan_validation_sha256: str
    reviewer_id: str
    reviewed_at: str
    qualification_motion_authorized: Literal[True] = True
    benchmark_motion_authorized: Literal[False] = False
    hardware_motion_authorized: Literal[False] = False
    motion_authorized: Literal[False] = False

    @field_validator("qualification_id", "reviewer_id")
    @classmethod
    def validate_identity_text(cls, value: str) -> str:
        return _identity_text(value, "qualification approval identity")

    @field_validator("plan_ref", "source_manifest_ref", "plan_validation_ref")
    @classmethod
    def validate_refs(cls, value: str) -> str:
        return _artifact(value, "qualification approval reference")

    @field_validator("plan_sha256", "source_manifest_sha256", "plan_validation_sha256")
    @classmethod
    def validate_digests(cls, value: str) -> str:
        return _digest(value, "qualification approval digest")

    @field_validator("reviewed_at")
    @classmethod
    def validate_reviewed_at(cls, value: str) -> str:
        return _timestamp(value, "qualification approval reviewed_at")


class QualificationTestEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    test_id: QualificationTestId
    command_family: CommandFamily
    outcome: Literal["pass", "fail", "unavailable"]
    evidence_ref: str
    evidence_sha256: str
    observed_max_joint_velocity_radps: float | None = None
    observed_max_cartesian_velocity_mps: float | None = None
    controller_status: str

    @field_validator("evidence_ref")
    @classmethod
    def validate_evidence_ref(cls, value: str) -> str:
        return _artifact(value, "qualification test evidence reference")

    @field_validator("evidence_sha256")
    @classmethod
    def validate_evidence_sha256(cls, value: str) -> str:
        return _digest(value, "qualification test evidence digest")

    @field_validator("controller_status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        return _identity_text(value, "qualification controller status")

    @field_validator("observed_max_joint_velocity_radps", "observed_max_cartesian_velocity_mps")
    @classmethod
    def validate_measurement(cls, value: float | None) -> float | None:
        if value is not None and (not math.isfinite(value) or value < 0):
            raise ValueError("qualification observed velocity must be finite and non-negative")
        return value


class ControllerQualificationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["paos-robotwin20-controller-qualification-evidence/v1"] = (
        CONTROLLER_QUALIFICATION_EVIDENCE_SCHEMA_VERSION
    )
    qualification_id: str
    producer_id: str
    plan_ref: str
    plan_sha256: str
    approval_ref: str
    approval_sha256: str
    identity: QualificationIdentity
    status: Literal["passed", "failed", "unavailable"]
    tests: tuple[QualificationTestEvidence, ...]
    world_change_started: bool
    world_change_completed: bool
    reset_completed: bool
    outcome_known: bool
    started_at: str
    finished_at: str
    motion_authorized: Literal[False] = False

    @field_validator("qualification_id", "producer_id")
    @classmethod
    def validate_identity_text(cls, value: str) -> str:
        return _identity_text(value, "qualification evidence identity")

    @field_validator("plan_ref", "approval_ref")
    @classmethod
    def validate_refs(cls, value: str) -> str:
        return _artifact(value, "qualification evidence reference")

    @field_validator("plan_sha256", "approval_sha256")
    @classmethod
    def validate_digests(cls, value: str) -> str:
        return _digest(value, "qualification evidence digest")

    @field_validator("started_at", "finished_at")
    @classmethod
    def validate_timestamps(cls, value: str) -> str:
        return _timestamp(value, "qualification evidence timestamp")

    @model_validator(mode="after")
    def validate_evidence(self) -> "ControllerQualificationEvidence":
        if {item.test_id for item in self.tests} != _REQUIRED_TESTS or len(self.tests) != len(
            _REQUIRED_TESTS
        ):
            raise ValueError("qualification evidence test matrix is incomplete or duplicated")
        if self.status == "passed" and (
            any(item.outcome != "pass" for item in self.tests)
            or not self.world_change_started
            or not self.world_change_completed
            or not self.reset_completed
            or not self.outcome_known
        ):
            raise ValueError("passed qualification evidence is incomplete")
        if not self.world_change_started and self.world_change_completed:
            raise ValueError("qualification world-change state is inconsistent")
        if self.world_change_started and not self.reset_completed and self.outcome_known:
            raise ValueError("known qualification outcome requires reset completion")
        return self


class ControllerQualificationValidation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["paos-robotwin20-controller-qualification-validation/v1"] = (
        CONTROLLER_QUALIFICATION_VALIDATION_SCHEMA_VERSION
    )
    qualification_id: str
    evidence_ref: str
    evidence_sha256: str
    validator_id: str
    producer_id: str
    validated_at: str
    status: Literal["validated_pass", "validated_failure"]
    checks: tuple[str, ...]
    independent: Literal[True] = True
    controller_enforced: bool
    motion_authorized: Literal[False] = False

    @field_validator("qualification_id", "validator_id", "producer_id")
    @classmethod
    def validate_identity_text(cls, value: str) -> str:
        return _identity_text(value, "qualification validation identity")

    @field_validator("evidence_ref")
    @classmethod
    def validate_evidence_ref(cls, value: str) -> str:
        return _artifact(value, "qualification validation evidence reference")

    @field_validator("evidence_sha256")
    @classmethod
    def validate_evidence_sha256(cls, value: str) -> str:
        return _digest(value, "qualification validation evidence digest")

    @field_validator("validated_at")
    @classmethod
    def validate_validated_at(cls, value: str) -> str:
        return _timestamp(value, "qualification validated_at")

    @model_validator(mode="after")
    def validate_validation(self) -> "ControllerQualificationValidation":
        if self.validator_id == self.producer_id:
            raise ValueError("qualification validator must be independent from producer")
        if not self.checks or len(self.checks) != len(set(self.checks)):
            raise ValueError("qualification validation checks are invalid")
        if self.status == "validated_pass" and not self.controller_enforced:
            raise ValueError("validated qualification pass must prove controller enforcement")
        if self.status == "validated_failure" and self.controller_enforced:
            raise ValueError("failed qualification cannot claim controller enforcement")
        return self


class ControllerQualification(BaseModel):
    """Final post-evidence human-reviewed qualification record."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["paos-robotwin20-controller-qualification/v1"] = (
        CONTROLLER_QUALIFICATION_SCHEMA_VERSION
    )
    qualification_id: str
    plan_ref: str
    plan_sha256: str
    evidence_ref: str
    evidence_sha256: str
    validation_ref: str
    validation_sha256: str
    identity: QualificationIdentity
    status: Literal["approved_pass", "reviewed_failure"]
    reviewer_id: str
    reviewed_at: str
    independent_execution_qualification: bool
    controller_enforced: bool
    benchmark_motion_authorized: Literal[False] = False
    hardware_motion_authorized: Literal[False] = False
    motion_authorized: Literal[False] = False

    @field_validator("qualification_id", "reviewer_id")
    @classmethod
    def validate_identity_text(cls, value: str) -> str:
        return _identity_text(value, "qualification review identity")

    @field_validator("plan_ref", "evidence_ref", "validation_ref")
    @classmethod
    def validate_refs(cls, value: str) -> str:
        return _artifact(value, "final qualification reference")

    @field_validator("plan_sha256", "evidence_sha256", "validation_sha256")
    @classmethod
    def validate_digests(cls, value: str) -> str:
        return _digest(value, "final qualification digest")

    @field_validator("reviewed_at")
    @classmethod
    def validate_reviewed_at(cls, value: str) -> str:
        return _timestamp(value, "qualification reviewed_at")

    @model_validator(mode="after")
    def validate_final_record(self) -> "ControllerQualification":
        passed = self.status == "approved_pass"
        if (
            self.independent_execution_qualification is not passed
            or self.controller_enforced is not passed
        ):
            raise ValueError("qualification status and enforcement result disagree")
        return self


def canonical_controller_qualification(value: BaseModel | Mapping[str, object]) -> bytes:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else dict(value)
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def controller_qualification_digest(value: BaseModel | Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_controller_qualification(value)).hexdigest()


def validate_controller_qualification_result_package(
    *,
    qualification: ControllerQualification,
    plan: ControllerQualificationPlan,
    evidence: ControllerQualificationEvidence,
    validation: ControllerQualificationValidation,
    qualification_file_sha256: str,
    plan_file_sha256: str,
    evidence_file_sha256: str,
    validation_file_sha256: str,
) -> None:
    """Validate the complete, post-review controller qualification chain."""

    digests = {
        "qualification": qualification_file_sha256,
        "plan": plan_file_sha256,
        "evidence": evidence_file_sha256,
        "validation": validation_file_sha256,
    }
    for label, digest in digests.items():
        _digest(digest, f"{label} file digest")
    if qualification_file_sha256 != controller_qualification_digest(qualification):
        raise ControllerQualificationError("final qualification file digest is invalid")
    if plan_file_sha256 != controller_qualification_digest(plan):
        raise ControllerQualificationError("qualification plan file digest is invalid")
    if evidence_file_sha256 != controller_qualification_digest(evidence):
        raise ControllerQualificationError("qualification evidence file digest is invalid")
    if validation_file_sha256 != controller_qualification_digest(validation):
        raise ControllerQualificationError("qualification validation file digest is invalid")
    if not (
        qualification.qualification_id
        == plan.qualification_id
        == evidence.qualification_id
        == validation.qualification_id
    ):
        raise ControllerQualificationError("qualification result identities do not match")
    if qualification.identity != plan.identity or qualification.identity != evidence.identity:
        raise ControllerQualificationError("qualification result provider identity drifted")
    plan_tests = {item.test_id: item.command_family for item in plan.tests}
    evidence_tests = {item.test_id: item.command_family for item in evidence.tests}
    if plan_tests != evidence_tests or evidence.producer_id != plan.producer_id:
        raise ControllerQualificationError("qualification test evidence drifted from plan")
    if (
        qualification.plan_sha256 != plan_file_sha256
        or evidence.plan_ref != qualification.plan_ref
        or evidence.plan_sha256 != plan_file_sha256
        or qualification.evidence_ref != validation.evidence_ref
        or qualification.evidence_sha256 != evidence_file_sha256
        or validation.evidence_sha256 != evidence_file_sha256
        or validation.producer_id != evidence.producer_id
        or qualification.validation_sha256 != validation_file_sha256
    ):
        raise ControllerQualificationError("qualification result artifact bindings are invalid")
    if (
        qualification.status != "approved_pass"
        or not qualification.independent_execution_qualification
        or not qualification.controller_enforced
        or evidence.status != "passed"
        or not evidence.outcome_known
        or not evidence.world_change_completed
        or not evidence.reset_completed
        or validation.status != "validated_pass"
        or not validation.independent
        or not validation.controller_enforced
    ):
        raise ControllerQualificationError("controller qualification is not an approved pass")
    if (
        qualification.motion_authorized
        or qualification.benchmark_motion_authorized
        or qualification.hardware_motion_authorized
        or evidence.motion_authorized
        or validation.motion_authorized
    ):
        raise ControllerQualificationError("qualification result exceeds its authority")


def validate_controller_qualification_plan_package(
    *,
    plan: ControllerQualificationPlan,
    source_manifest: ControllerQualificationSourceManifest,
    review_request: ControllerQualificationReviewRequest,
    capabilities: Mapping[str, MotionCapabilityDocument],
    capability_file_sha256: Mapping[str, str],
    validations: Mapping[str, MotionCapabilityValidation],
    validation_file_sha256: Mapping[str, str],
) -> tuple[str, ...]:
    """Cross-check a no-motion review package and all capability bindings."""

    if (
        source_manifest.qualification_id != plan.qualification_id
        or source_manifest.producer_id != plan.producer_id
        or source_manifest.created_at != plan.created_at
        or source_manifest.identity != plan.identity
        or source_manifest.capability_bindings != plan.capability_bindings
    ):
        raise ControllerQualificationError("qualification source manifest does not match plan")
    source_manifest_sha256 = controller_qualification_digest(source_manifest)
    plan_sha256 = controller_qualification_digest(plan)
    prefix = plan.source_manifest_ref.removesuffix("/source-manifest")
    if (
        not plan.source_manifest_ref.endswith("/source-manifest")
        or plan.source_manifest_sha256 != source_manifest_sha256
        or review_request.qualification_id != plan.qualification_id
        or review_request.plan_ref != f"{prefix}/plan"
        or review_request.plan_sha256 != plan_sha256
        or review_request.source_manifest_ref != plan.source_manifest_ref
        or review_request.source_manifest_sha256 != source_manifest_sha256
    ):
        raise ControllerQualificationError("qualification review binding does not match plan")
    if set(capabilities) != {"left", "right"} or set(validations) != {"left", "right"}:
        raise ControllerQualificationError("qualification capability inputs are incomplete")
    if set(capability_file_sha256) != {"left", "right"} or set(validation_file_sha256) != {
        "left",
        "right",
    }:
        raise ControllerQualificationError("qualification capability digests are incomplete")
    bindings = {item.arm_id: item for item in plan.capability_bindings}
    for arm_id in ("left", "right"):
        binding = bindings[arm_id]
        capability = capabilities[arm_id]
        validation = validations[arm_id]
        provider = capability.provider
        identity = plan.identity
        if (
            capability.arm_id != arm_id
            or capability.robot_identity != identity.robot_identity
            or provider.simulator_id != identity.simulator_id
            or provider.simulator_version != identity.simulator_version
            or provider.controller_id != identity.controller_id
            or provider.controller_version != identity.controller_version
            or provider.runtime_python_version != identity.runtime_python_version
            or provider.robotwin_git_revision != identity.robotwin_git_revision
        ):
            raise ControllerQualificationError("qualification provider identity drifted")
        capability_sha256 = motion_capability_digest(capability)
        if (
            binding.sha256 != capability_sha256
            or capability_file_sha256[arm_id] != capability_sha256
            or capability.controller_qualification_ref is not None
            or capability.motion_authorized is not False
        ):
            raise ControllerQualificationError("qualification capability binding is invalid")
        if (
            binding.validation_sha256 != validation_file_sha256[arm_id]
            or validation.capability_sha256 != capability_sha256
            or validation.status != "validated_planner_constraints"
            or validation.independent_execution_qualification is not False
            or validation.controller_enforced is not False
            or validation.motion_authorized is not False
        ):
            raise ControllerQualificationError("qualification source validation binding is invalid")
    return _PLAN_VALIDATION_CHECKS


__all__ = [
    "CONTROLLER_QUALIFICATION_APPROVAL_SCHEMA_VERSION",
    "CONTROLLER_QUALIFICATION_EVIDENCE_SCHEMA_VERSION",
    "CONTROLLER_QUALIFICATION_PLAN_VALIDATION_SCHEMA_VERSION",
    "CONTROLLER_QUALIFICATION_PLAN_SCHEMA_VERSION",
    "CONTROLLER_QUALIFICATION_REVIEW_REQUEST_SCHEMA_VERSION",
    "CONTROLLER_QUALIFICATION_SCHEMA_VERSION",
    "CONTROLLER_QUALIFICATION_SOURCE_MANIFEST_SCHEMA_VERSION",
    "CONTROLLER_QUALIFICATION_VALIDATION_SCHEMA_VERSION",
    "ControllerQualification",
    "ControllerQualificationApproval",
    "ControllerQualificationError",
    "ControllerQualificationEvidence",
    "ControllerQualificationPlan",
    "ControllerQualificationPlanValidation",
    "ControllerQualificationReviewRequest",
    "ControllerQualificationSourceManifest",
    "ControllerQualificationValidation",
    "QualificationCapabilityBinding",
    "QualificationIdentity",
    "QualificationTestEvidence",
    "QualificationTestSpec",
    "canonical_controller_qualification",
    "controller_qualification_digest",
    "validate_controller_qualification_result_package",
    "validate_controller_qualification_plan_package",
]
