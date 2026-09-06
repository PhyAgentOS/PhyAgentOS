"""Provider-neutral manipulation intent projections for PAOS adapters.

This module deliberately does not implement a DAG, task lifecycle, resource
lease, retry transaction, planner, or execution path. ``AgentTaskRecord`` and
``PlanRevision`` remain the PAOS lifecycle facts; Gateway owns concurrency and
invocations. The types here are immutable inputs/outputs for adapter queries.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ManipulationPlanningError(ValueError):
    """An adapter planning projection is invalid."""


class CoordinationMode(StrEnum):
    SINGLE_ARM = "single_arm"
    ALTERNATIVE_ARM = "alternative_arm"
    BIMANUAL = "bimanual"


class ResourceMode(StrEnum):
    """Provider-neutral resource semantics for a Skill subtask."""

    SINGLE_RESOURCE = "single_resource"
    ALTERNATIVE_RESOURCE = "alternative_resource"
    PARALLEL_INDEPENDENT = "parallel_independent"
    ATOMIC_GROUP = "atomic_group"


def _identity(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    normalized = value.strip()
    if not normalized or normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
        raise ValueError(f"{label} must be non-empty and path-safe")
    return normalized


def _ref(value: str, prefix: str, label: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not value.startswith(prefix) or not value.removeprefix(prefix) or any(char.isspace() for char in value):
        raise ValueError(f"{label} must start with {prefix}")
    return value


def _digest(value: str, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"{label} must be a SHA-256 hex digest")
    return value


class ResourceRequirement(BaseModel):
    """A symbolic resource request owned by a Skill DAG node.

    It names no robot, URDF, or lock.  Runtime/Gateway resolves the concrete
    resource after planning and remains the concurrency authority.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_class: Literal["manipulator"] = "manipulator"
    mode: ResourceMode
    min_count: int = Field(default=1, ge=1, le=16)
    max_count: int = Field(default=1, ge=1, le=16)
    substitution_allowed: bool = False

    @model_validator(mode="after")
    def validate_counts(self) -> "ResourceRequirement":
        if self.max_count < self.min_count:
            raise ValueError("resource requirement max_count must be >= min_count")
        if self.mode is ResourceMode.SINGLE_RESOURCE and self.max_count != 1:
            raise ValueError("single_resource requirement must have max_count=1")
        if self.mode is ResourceMode.ALTERNATIVE_RESOURCE and not self.substitution_allowed:
            raise ValueError("alternative_resource requires substitution_allowed")
        if self.mode is ResourceMode.ATOMIC_GROUP and self.min_count < 2:
            raise ValueError("atomic_group requires at least two resources")
        return self


class ArmCapability(BaseModel):
    """One profile-owned arm capability description projected to the Agent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    arm_id: str
    base_frame: str
    tool_frame: str
    planner_profile_ref: str
    workspace_ref: str
    joint_limits_ref: str
    motion_capabilities_ref: str | None = None
    gripper_identity: str
    supported_modes: tuple[ResourceMode, ...]
    availability: Literal["available", "unavailable"] = "available"

    @field_validator("arm_id", "base_frame", "tool_frame", "gripper_identity")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        return _identity(value, "arm capability identity")

    @field_validator("planner_profile_ref", "workspace_ref", "joint_limits_ref")
    @classmethod
    def validate_artifact_refs(cls, value: str) -> str:
        return _ref(value, "artifact://", "arm capability reference")

    @field_validator("motion_capabilities_ref")
    @classmethod
    def validate_motion_capabilities_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _ref(value, "artifact://", "arm motion capability reference")

    @field_validator("supported_modes")
    @classmethod
    def validate_modes(cls, value: tuple[ResourceMode, ...]) -> tuple[ResourceMode, ...]:
        if not value or len(value) != len(set(value)):
            raise ValueError("arm capability supported_modes must be unique and non-empty")
        return value


class CapabilitySnapshot(BaseModel):
    """Immutable, no-motion view of embodiment capabilities for one scene."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["paos-manipulation-capability-snapshot/v1"] = (
        "paos-manipulation-capability-snapshot/v1"
    )
    snapshot_ref: str
    snapshot_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    scene_revision: str
    observation_ref: str
    calibration_ref: str
    embodiment_id: str
    topology: Literal["single_arm", "dual_independent", "dual_coordinated"]
    profile_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    captured_at: str
    arms: tuple[ArmCapability, ...]
    motion_authorized: Literal[False] = False

    @field_validator("snapshot_ref", "calibration_ref")
    @classmethod
    def validate_snapshot_refs(cls, value: str) -> str:
        return _ref(value, "artifact://", "capability snapshot reference")

    @field_validator("scene_revision", "embodiment_id")
    @classmethod
    def validate_snapshot_identity(cls, value: str) -> str:
        return _identity(value, "capability snapshot identity")

    @field_validator("observation_ref")
    @classmethod
    def validate_snapshot_observation(cls, value: str) -> str:
        return _ref(value, "observation://", "capability snapshot observation_ref")

    @model_validator(mode="after")
    def validate_snapshot(self) -> "CapabilitySnapshot":
        if not self.arms or len({arm.arm_id for arm in self.arms}) != len(self.arms):
            raise ValueError("capability snapshot arm identities must be unique and non-empty")
        if self.topology == "single_arm" and len(self.arms) != 1:
            raise ValueError("single_arm capability snapshot requires one arm")
        if self.topology != "single_arm" and len(self.arms) != 2:
            raise ValueError("dual capability snapshot requires two arms")
        payload = self.observation_ref.removeprefix("observation://").split("/", 1)
        if len(payload) != 2 or payload[0] != self.scene_revision:
            raise ValueError("capability snapshot observation identity is invalid")
        try:
            captured_at = datetime.fromisoformat(self.captured_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("capability snapshot captured_at is invalid") from exc
        if captured_at.tzinfo is None or captured_at.utcoffset() is None:
            raise ValueError("capability snapshot captured_at must be timezone-aware")
        if self.snapshot_digest != capability_snapshot_digest(self):
            raise ValueError("capability snapshot digest does not match its content")
        return self


def capability_snapshot_digest(snapshot: "CapabilitySnapshot | dict[str, object]") -> str:
    """Digest capability content without its storage reference or digest field."""

    value = _canonical_json(snapshot.model_dump(mode="json") if isinstance(snapshot, BaseModel) else snapshot)
    value.pop("snapshot_ref", None)
    value.pop("snapshot_digest", None)
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class AssignmentAlternative(BaseModel):
    """A rejected, auditable assignment option."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    arm_ids: tuple[str, ...]
    candidate_ref: str
    status: Literal["rejected"] = "rejected"
    reason: str

    @field_validator("candidate_ref")
    @classmethod
    def validate_candidate_ref(cls, value: str) -> str:
        return _ref(value, "candidate://", "assignment candidate_ref")

    @field_validator("arm_ids")
    @classmethod
    def validate_assignment_arms(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_identity(item, "assignment arm_id") for item in value)
        if not normalized or len(normalized) != len(set(normalized)):
            raise ValueError("assignment arm_ids must be unique and non-empty")
        return normalized

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("assignment alternative reason must be non-empty")
        return value.strip()


class ArmAssignment(BaseModel):
    """No-motion planning result selecting resources after readiness evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["paos-arm-assignment/v1"] = "paos-arm-assignment/v1"
    assignment_ref: str
    assignment_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_id: str
    revision_id: str
    node_id: str
    node_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    entity_ref: str
    observation_ref: str
    scene_revision: str
    calibration_ref: str
    candidate_set_ref: str
    coordination_mode: CoordinationMode
    selected_arm_ids: tuple[str, ...]
    candidate_ref: str
    route_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    capability_snapshot_ref: str
    readiness_evidence_ref: str
    decision_basis: tuple[str, ...]
    alternatives: tuple[AssignmentAlternative, ...] = ()
    motion_authorized: Literal[False] = False

    @field_validator(
        "assignment_ref", "capability_snapshot_ref", "readiness_evidence_ref", "calibration_ref"
    )
    @classmethod
    def validate_assignment_refs(cls, value: str) -> str:
        return _ref(value, "artifact://", "assignment artifact reference")

    @field_validator("task_id", "revision_id", "node_id", "scene_revision")
    @classmethod
    def validate_assignment_ids(cls, value: str) -> str:
        return _identity(value, "assignment identity")

    @field_validator("entity_ref")
    @classmethod
    def validate_assignment_entity(cls, value: str) -> str:
        return _ref(value, "entity://", "assignment entity_ref")

    @field_validator("observation_ref")
    @classmethod
    def validate_assignment_observation(cls, value: str) -> str:
        return _ref(value, "observation://", "assignment observation_ref")

    @field_validator("candidate_set_ref")
    @classmethod
    def validate_assignment_candidate_set(cls, value: str) -> str:
        return _ref(value, "candidate-set://", "assignment candidate_set_ref")

    @field_validator("candidate_ref")
    @classmethod
    def validate_assignment_candidate(cls, value: str) -> str:
        return _ref(value, "candidate://", "assignment candidate_ref")

    @field_validator("selected_arm_ids")
    @classmethod
    def validate_selected_arms(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_identity(item, "selected arm_id") for item in value)
        if not normalized or len(normalized) != len(set(normalized)):
            raise ValueError("selected_arm_ids must be unique and non-empty")
        return normalized

    @field_validator("decision_basis")
    @classmethod
    def validate_decision_basis(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(not item.strip() for item in value):
            raise ValueError("assignment decision_basis must be non-empty")
        return tuple(item.strip() for item in value)

    @model_validator(mode="after")
    def validate_assignment(self) -> "ArmAssignment":
        expected = 2 if self.coordination_mode is CoordinationMode.BIMANUAL else 1
        if len(self.selected_arm_ids) != expected:
            raise ValueError("selected_arm_ids do not match coordination_mode")
        observation = self.observation_ref.removeprefix("observation://").split("/", 1)
        candidate_set = self.candidate_set_ref.removeprefix("candidate-set://").split("/", 1)
        if (
            len(observation) != 2
            or len(candidate_set) != 2
            or observation[0] != self.scene_revision
            or candidate_set != observation
        ):
            raise ValueError("assignment observation and candidate-set bindings are invalid")
        if self.assignment_digest != arm_assignment_digest(self):
            raise ValueError("arm assignment digest does not match its content")
        return self


def arm_assignment_digest(assignment: "ArmAssignment | dict[str, object]") -> str:
    """Digest assignment content without its storage reference or digest field."""

    value = _canonical_json(assignment.model_dump(mode="json") if isinstance(assignment, BaseModel) else assignment)
    value.pop("assignment_ref", None)
    value.pop("assignment_digest", None)
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _canonical_json(value: object) -> object:
    if isinstance(value, BaseModel):
        return _canonical_json(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): _canonical_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical_json(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    return value


class CoordinationGroup(BaseModel):
    """Binding for future atomic multi-resource execution, not an executor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["paos-coordination-group/v1"] = "paos-coordination-group/v1"
    group_ref: str
    mode: ResourceMode
    participant_ids: tuple[str, ...]
    scene_revision: str
    shared_timeline_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    route_bundle_ref: str | None = None
    cancel_scope: Literal["atomic_group"] = "atomic_group"
    motion_authorized: Literal[False] = False

    @field_validator("group_ref")
    @classmethod
    def validate_group_ref(cls, value: str) -> str:
        return _ref(value, "artifact://", "coordination group reference")

    @field_validator("participant_ids", "scene_revision")
    @classmethod
    def validate_group_identity(cls, value):
        if isinstance(value, tuple):
            normalized = tuple(_identity(item, "coordination participant") for item in value)
            if len(normalized) < 2 or len(normalized) != len(set(normalized)):
                raise ValueError("coordination participant_ids must contain unique resources")
            return normalized
        return _identity(value, "coordination scene_revision")

    @field_validator("route_bundle_ref")
    @classmethod
    def validate_route_bundle_ref(cls, value: str | None) -> str | None:
        return None if value is None else _ref(value, "artifact://", "route bundle reference")

    @model_validator(mode="after")
    def validate_group(self) -> "CoordinationGroup":
        if self.mode is ResourceMode.ATOMIC_GROUP and (
            self.shared_timeline_digest is None or self.route_bundle_ref is None
        ):
            raise ValueError("atomic coordination group requires timeline and route bundle")
        return self


class ManipulationIntent(BaseModel):
    """Immutable semantic input for one adapter-owned capability query."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["manipulation_intent_v2"] = "manipulation_intent_v2"
    task_id: str
    revision_id: str
    node_id: str
    node_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    entity_ref: str
    goal: str
    success_criteria: tuple[str, ...]
    allowed_arms: tuple[str, ...]
    coordination_mode: CoordinationMode
    observation_ref: str
    scene_revision: str
    observation_frame_id: str
    calibration_ref: str
    candidate_set_ref: str
    constraints: tuple[str, ...] = ()
    motion_authorized: Literal[False] = False

    @field_validator(
        "task_id", "revision_id", "node_id", "scene_revision", "observation_frame_id"
    )
    @classmethod
    def validate_ids(cls, value: str) -> str:
        return _identity(value, "intent identity")

    @field_validator("entity_ref")
    @classmethod
    def validate_entity(cls, value: str) -> str:
        return _ref(value, "entity://", "entity_ref")

    @field_validator("observation_ref")
    @classmethod
    def validate_observation(cls, value: str) -> str:
        return _ref(value, "observation://", "observation_ref")

    @field_validator("calibration_ref")
    @classmethod
    def validate_calibration(cls, value: str) -> str:
        return _ref(value, "artifact://", "calibration_ref")

    @field_validator("candidate_set_ref")
    @classmethod
    def validate_candidate_set(cls, value: str) -> str:
        return _ref(value, "candidate-set://", "candidate_set_ref")

    @field_validator("goal")
    @classmethod
    def validate_goal(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("intent goal must be non-empty")
        return value.strip()

    @field_validator("success_criteria", "constraints")
    @classmethod
    def validate_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(str(item).strip() for item in values)
        if any(not item for item in normalized):
            raise ValueError("intent text items must be non-empty")
        return normalized

    @field_validator("allowed_arms")
    @classmethod
    def validate_arms(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_identity(item, "arm_id") for item in values)
        if not normalized or len(normalized) != len(set(normalized)):
            raise ValueError("intent allowed_arms must be unique and non-empty")
        return normalized

    @model_validator(mode="after")
    def validate_bindings(self) -> "ManipulationIntent":
        if not self.success_criteria:
            raise ValueError("intent requires at least one success criterion")
        if self.coordination_mode is CoordinationMode.SINGLE_ARM and len(self.allowed_arms) != 1:
            raise ValueError("single_arm intent must name exactly one arm")
        if self.coordination_mode is CoordinationMode.BIMANUAL and len(self.allowed_arms) != 2:
            raise ValueError("bimanual intent must name exactly two arms")
        if self.observation_ref != (
            f"observation://{self.scene_revision}/{self.observation_frame_id}"
        ):
            raise ValueError("intent observation identity is invalid")
        if self.candidate_set_ref != (
            f"candidate-set://{self.scene_revision}/{self.observation_frame_id}"
        ):
            raise ValueError("intent candidate-set identity is invalid")
        return self


class RouteFailure(BaseModel):
    """Bounded adapter rejection projection; not a task verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["route_failure_v2"] = "route_failure_v2"
    candidate_ref: str
    arm_ids: tuple[str, ...]
    phase: str
    code: str
    owner: Literal["input", "binding", "planner", "policy", "collision", "readiness", "infrastructure"]
    detail: str
    route_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("candidate_ref")
    @classmethod
    def validate_candidate(cls, value: str) -> str:
        return _ref(value, "candidate://", "candidate_ref")

    @field_validator("arm_ids")
    @classmethod
    def validate_arm_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_identity(item, "arm_id") for item in values)
        if not normalized or len(normalized) != len(set(normalized)):
            raise ValueError("route failure arm_ids must be unique and non-empty")
        return normalized

    @field_validator("phase", "code", "detail")
    @classmethod
    def validate_text_fields(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("route failure text must be non-empty")
        return value.strip()


class ReplanSignal(BaseModel):
    """A non-authoritative recovery hint consumed by existing task recovery."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["manipulation_replan_hint_v2"] = "manipulation_replan_hint_v2"
    task_id: str
    revision_id: str
    node_id: str
    node_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["replan_required"] = "replan_required"
    reason: Literal[
        "all_routes_rejected",
        "scene_revision_stale",
        "candidate_set_invalid",
        "resource_unavailable",
        "coordination_conflict",
        "partial_group_failure",
        "execution_unknown",
    ]
    failed_routes: tuple[RouteFailure, ...]
    preserved_constraints: tuple[str, ...]
    next_actions: tuple[str, ...]
    scene_revision: str
    candidate_set_ref: str
    motion_authorized: Literal[False] = False
    candidate_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("task_id", "revision_id", "node_id", "scene_revision")
    @classmethod
    def validate_ids(cls, value: str) -> str:
        return _identity(value, "replan identity")

    @field_validator("candidate_set_ref")
    @classmethod
    def validate_candidate_set(cls, value: str) -> str:
        return _ref(value, "candidate-set://", "candidate_set_ref")

    @field_validator("preserved_constraints", "next_actions")
    @classmethod
    def validate_items(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(str(item).strip() for item in values)
        if any(not item for item in normalized) or len(normalized) != len(set(normalized)):
            raise ValueError("replan text items must be unique and non-empty")
        return normalized

    @model_validator(mode="after")
    def validate_signal(self) -> "ReplanSignal":
        if not self.next_actions:
            raise ValueError("replan signal requires at least one next action")
        if self.reason != "candidate_set_invalid" and not self.failed_routes:
            raise ValueError("replan signal requires at least one failed route")
        failure_keys = tuple(
            (item.candidate_ref, item.arm_ids, item.phase, item.code, item.route_digest)
            for item in self.failed_routes
        )
        if len(failure_keys) != len(set(failure_keys)):
            raise ValueError("replan failed routes must be unique")
        if self.candidate_digest != _replan_digest(
            task_id=self.task_id,
            revision_id=self.revision_id,
            node_id=self.node_id,
            node_digest=self.node_digest,
            reason=self.reason,
            failed_routes=self.failed_routes,
            preserved_constraints=self.preserved_constraints,
            next_actions=self.next_actions,
            scene_revision=self.scene_revision,
            candidate_set_ref=self.candidate_set_ref,
        ):
            raise ValueError("replan signal digest does not match its content")
        return self


def _replan_digest(
    *,
    task_id: str,
    revision_id: str,
    node_id: str,
    node_digest: str,
    reason: str,
    failed_routes: tuple[RouteFailure, ...],
    preserved_constraints: tuple[str, ...],
    next_actions: tuple[str, ...],
    scene_revision: str,
    candidate_set_ref: str,
) -> str:
    payload = {
        "task_id": task_id,
        "revision_id": revision_id,
        "node_id": node_id,
        "node_digest": node_digest,
        "reason": reason,
        "failed_routes": [item.model_dump(mode="json") for item in failed_routes],
        "preserved_constraints": list(preserved_constraints),
        "next_actions": list(next_actions),
        "scene_revision": scene_revision,
        "candidate_set_ref": candidate_set_ref,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class ReplanCoordinator:
    """Build a bounded hint; never changes AgentTask or creates a revision."""

    def __init__(self, *, max_failures: int = 256) -> None:
        if not isinstance(max_failures, int) or max_failures < 1:
            raise ValueError("max_failures must be positive")
        self.max_failures = max_failures

    def build_signal(
        self,
        intent: ManipulationIntent,
        failures: tuple[RouteFailure, ...] | list[RouteFailure],
        *,
        reason: Literal[
            "all_routes_rejected",
            "scene_revision_stale",
            "candidate_set_invalid",
            "resource_unavailable",
            "coordination_conflict",
            "partial_group_failure",
            "execution_unknown",
        ] = "all_routes_rejected",
        next_actions: tuple[str, ...] = ("regenerate_candidates", "refresh_observation"),
    ) -> ReplanSignal:
        if not isinstance(intent, ManipulationIntent):
            raise TypeError("replan intent must be a ManipulationIntent")
        validated = tuple(item if isinstance(item, RouteFailure) else RouteFailure.model_validate(item) for item in failures)
        if reason != "candidate_set_invalid" and not validated:
            raise ValueError("replan requires at least one failed route")
        if len(validated) > self.max_failures:
            raise ValueError("replan failure list exceeds configured bound")
        return ReplanSignal(
            task_id=intent.task_id,
            revision_id=intent.revision_id,
            node_id=intent.node_id,
            node_digest=intent.node_digest,
            reason=reason,
            failed_routes=validated,
            preserved_constraints=intent.constraints,
            next_actions=next_actions,
            scene_revision=intent.scene_revision,
            candidate_set_ref=intent.candidate_set_ref,
            candidate_digest=_replan_digest(
                task_id=intent.task_id,
                revision_id=intent.revision_id,
                node_id=intent.node_id,
                node_digest=intent.node_digest,
                reason=reason,
                failed_routes=validated,
                preserved_constraints=intent.constraints,
                next_actions=next_actions,
                scene_revision=intent.scene_revision,
                candidate_set_ref=intent.candidate_set_ref,
            ),
        )


__all__ = [
    "ArmAssignment",
    "ArmCapability",
    "AssignmentAlternative",
    "CapabilitySnapshot",
    "CoordinationGroup",
    "CoordinationMode",
    "ManipulationIntent",
    "ManipulationPlanningError",
    "ReplanCoordinator",
    "ReplanSignal",
    "ResourceMode",
    "ResourceRequirement",
    "RouteFailure",
    "arm_assignment_digest",
    "capability_snapshot_digest",
]
