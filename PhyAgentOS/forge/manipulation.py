"""Provider-neutral manipulation intent projections for PAOS adapters.

This module deliberately does not implement a DAG, task lifecycle, resource
lease, retry transaction, planner, or execution path. ``AgentTaskRecord`` and
``PlanRevision`` remain the PAOS lifecycle facts; Gateway owns concurrency and
invocations. The types here are immutable inputs/outputs for adapter queries.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ManipulationPlanningError(ValueError):
    """An adapter planning projection is invalid."""


class CoordinationMode(StrEnum):
    SINGLE_ARM = "single_arm"
    ALTERNATIVE_ARM = "alternative_arm"
    BIMANUAL = "bimanual"


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
    reason: Literal["all_routes_rejected", "scene_revision_stale", "candidate_set_invalid", "execution_unknown"]
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
        reason: Literal["all_routes_rejected", "scene_revision_stale", "candidate_set_invalid", "execution_unknown"] = "all_routes_rejected",
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


__all__ = ["CoordinationMode", "ManipulationIntent", "ManipulationPlanningError", "ReplanCoordinator", "ReplanSignal", "RouteFailure"]
