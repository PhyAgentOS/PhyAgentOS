"""Provider-neutral semantic manipulation planning contracts.

The core module describes task intent and bounded replanning signals.  It does
not know about RoboTwin, a robot model, a motion planner, or a Gateway.  The
adapter-owned route selector is responsible for turning an intent into
candidate/arm combinations and for evaluating complete routes without motion.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ManipulationPlanningError(ValueError):
    """A semantic manipulation plan or replanning signal is invalid."""


class CoordinationMode(StrEnum):
    """How an intent may allocate manipulator resources."""

    SINGLE_ARM = "single_arm"
    ALTERNATIVE_ARM = "alternative_arm"
    BIMANUAL = "bimanual"


class ManipulationOperation(StrEnum):
    """Semantic DAG operations; none of these operations executes motion."""

    OBSERVE = "observe"
    MANIPULATE = "manipulate"
    VERIFY = "verify"


class PlanConditionKind(StrEnum):
    ALWAYS = "always"
    NODE_STATE_EQUALS = "node_state_equals"
    EVIDENCE_REVISION_EQUALS = "evidence_revision_equals"


class PlanConditionOutcome(StrEnum):
    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"
    UNKNOWN = "unknown"


class NodeSettlementStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class ExpectedEffect(StrEnum):
    NONE = "none"
    ENTITY_POSE_CHANGE = "entity_pose_change"
    GRIPPER_ATTACHMENT = "gripper_attachment"


def _stable_digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _identity(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    normalized = value.strip()
    if not normalized or normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
        raise ValueError(f"{label} must be non-empty and path-safe")
    return normalized


def _ref(value: str, prefix: str, label: str) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value.startswith(prefix)
        or not value.removeprefix(prefix)
        or any(char.isspace() for char in value)
    ):
        raise ValueError(f"{label} must start with {prefix}")
    return value


class PlanCondition(BaseModel):
    """A bounded precondition evaluated by PAOS without provider calls."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["manipulation_plan_condition_v1"] = "manipulation_plan_condition_v1"
    kind: PlanConditionKind = PlanConditionKind.ALWAYS
    node_id: str | None = None
    expected_state: NodeSettlementStatus | None = None
    evidence_ref: str | None = None
    evidence_revision: str | None = None

    @field_validator("evidence_ref")
    @classmethod
    def validate_evidence_ref(cls, value: str | None) -> str | None:
        return None if value is None else _ref(value, "artifact://", "evidence_ref")

    @field_validator("evidence_revision")
    @classmethod
    def validate_evidence_revision(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized or any(char.isspace() for char in normalized):
            raise ValueError("evidence_revision must be a non-empty token")
        return normalized

    @model_validator(mode="after")
    def validate_operands(self) -> "PlanCondition":
        if self.kind is PlanConditionKind.ALWAYS:
            if any(
                value is not None
                for value in (
                    self.node_id,
                    self.expected_state,
                    self.evidence_ref,
                    self.evidence_revision,
                )
            ):
                raise ValueError("always condition cannot carry operands")
        elif self.kind is PlanConditionKind.NODE_STATE_EQUALS:
            if self.node_id is None or self.expected_state is None or self.evidence_ref is not None or self.evidence_revision is not None:
                raise ValueError("node_state_equals requires only node_id and expected_state")
            _identity(self.node_id, "condition node_id")
        elif self.evidence_ref is None or self.evidence_revision is None or self.node_id is not None or self.expected_state is not None:
            raise ValueError("evidence_revision_equals requires only evidence_ref and evidence_revision")
        return self

    def evaluate(
        self,
        *,
        node_states: Mapping[str, NodeSettlementStatus | str],
        evidence_revisions: Mapping[str, str],
    ) -> PlanConditionOutcome:
        if self.kind is PlanConditionKind.ALWAYS:
            return PlanConditionOutcome.SATISFIED
        if self.kind is PlanConditionKind.NODE_STATE_EQUALS:
            actual = node_states.get(self.node_id)
            if actual is None:
                return PlanConditionOutcome.UNKNOWN
            try:
                actual_state = NodeSettlementStatus(actual)
            except (TypeError, ValueError):
                return PlanConditionOutcome.UNKNOWN
            return (
                PlanConditionOutcome.SATISFIED
                if actual_state is self.expected_state
                else PlanConditionOutcome.UNSATISFIED
            )
        actual_revision = evidence_revisions.get(self.evidence_ref)
        if actual_revision is None:
            return PlanConditionOutcome.UNKNOWN
        return (
            PlanConditionOutcome.SATISFIED
            if actual_revision == self.evidence_revision
            else PlanConditionOutcome.UNSATISFIED
        )


class RetryLineage(BaseModel):
    """Immutable lineage for retries of one semantic obligation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["manipulation_retry_lineage_v1"] = "manipulation_retry_lineage_v1"
    root_node_id: str
    retry_index: int = Field(default=0, ge=0)
    parent_node_id: str | None = None

    @field_validator("root_node_id")
    @classmethod
    def validate_root(cls, value: str) -> str:
        return _identity(value, "root_node_id")

    @field_validator("parent_node_id")
    @classmethod
    def validate_parent(cls, value: str | None) -> str | None:
        return None if value is None else _identity(value, "parent_node_id")

    @model_validator(mode="after")
    def validate_retry(self) -> "RetryLineage":
        if self.retry_index == 0 and self.parent_node_id is not None:
            raise ValueError("initial node cannot have a retry parent")
        if self.retry_index > 0 and self.parent_node_id is None:
            raise ValueError("retried node requires a parent_node_id")
        return self


class ManipulationDagNode(BaseModel):
    """One semantic task node and its resource/verification intent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["manipulation_dag_node_v1"] = "manipulation_dag_node_v1"
    node_id: str
    operation: ManipulationOperation
    depends_on: tuple[str, ...] = ()
    resource_locks: tuple[str, ...] = ()
    entity_ref: str | None = None
    goal: str = ""
    success_criteria: tuple[str, ...] = ()
    allowed_arms: tuple[str, ...] = ()
    coordination_mode: CoordinationMode = CoordinationMode.ALTERNATIVE_ARM
    retry_lineage: RetryLineage
    condition: PlanCondition = Field(default_factory=PlanCondition)
    required_evidence_roles: tuple[
        Literal["observation", "candidate_set", "calibration", "geometry", "route_readiness"]
    , ...] = ()
    expected_effects: tuple[ExpectedEffect, ...] = ()
    node_digest: str = ""

    @field_validator("node_id")
    @classmethod
    def validate_node_id(cls, value: str) -> str:
        return _identity(value, "node_id")

    @field_validator("depends_on", "resource_locks", "allowed_arms")
    @classmethod
    def validate_id_lists(cls, values: Sequence[str]) -> tuple[str, ...]:
        normalized = tuple(_identity(item, "DAG identity") for item in values)
        if len(normalized) != len(set(normalized)):
            raise ValueError("DAG identity lists must be unique")
        return normalized

    @field_validator("entity_ref")
    @classmethod
    def validate_entity_ref(cls, value: str | None) -> str | None:
        return None if value is None else _ref(value, "entity://", "entity_ref")

    @field_validator("goal")
    @classmethod
    def normalize_goal(cls, value: str) -> str:
        return value.strip()

    @field_validator("success_criteria")
    @classmethod
    def normalize_criteria(cls, values: Sequence[str]) -> tuple[str, ...]:
        normalized = tuple(str(item).strip() for item in values)
        if any(not item for item in normalized):
            raise ValueError("success criteria must be non-empty")
        return normalized

    @field_validator("required_evidence_roles", "expected_effects")
    @classmethod
    def validate_unique_enums(cls, values: Sequence[object]) -> tuple[object, ...]:
        normalized = tuple(values)
        if len(normalized) != len(set(normalized)):
            raise ValueError("node evidence/effect declarations must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_operation_contract(self) -> "ManipulationDagNode":
        if self.operation is ManipulationOperation.MANIPULATE:
            if self.entity_ref is None or not self.goal or not self.success_criteria:
                raise ValueError("manipulation nodes require entity_ref, goal, and success_criteria")
            if not self.allowed_arms:
                raise ValueError("manipulation nodes require at least one allowed arm")
            if self.coordination_mode is CoordinationMode.SINGLE_ARM and len(self.allowed_arms) != 1:
                raise ValueError("single_arm nodes must name exactly one arm")
            if self.coordination_mode is CoordinationMode.BIMANUAL and len(self.allowed_arms) != 2:
                raise ValueError("bimanual nodes must name exactly two distinct arms")
            required = {"observation", "candidate_set", "calibration", "geometry", "route_readiness"}
            if set(self.required_evidence_roles) != required:
                raise ValueError("manipulation nodes require all planning evidence roles")
            if not self.resource_locks:
                raise ValueError("manipulation nodes require resource locks")
            if not self.expected_effects or ExpectedEffect.NONE in self.expected_effects:
                raise ValueError("manipulation nodes require explicit non-none expected effects")
        elif self.coordination_mode is CoordinationMode.BIMANUAL:
            raise ValueError("only manipulation nodes may request bimanual coordination")
        if self.retry_lineage.parent_node_id == self.node_id:
            raise ValueError("retry parent_node_id cannot equal node_id")
        expected = _stable_digest(self._digest_payload())
        if self.node_digest and self.node_digest != expected:
            raise ValueError("node_digest does not match node content")
        object.__setattr__(self, "node_digest", expected)
        return self

    def _digest_payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "node_id": self.node_id,
            "operation": self.operation.value,
            "depends_on": sorted(self.depends_on),
            "resource_locks": sorted(self.resource_locks),
            "entity_ref": self.entity_ref,
            "goal": self.goal,
            "success_criteria": list(self.success_criteria),
            "allowed_arms": list(self.allowed_arms),
            "coordination_mode": self.coordination_mode.value,
            "retry_lineage": self.retry_lineage.model_dump(mode="json"),
            "condition": self.condition.model_dump(mode="json"),
            "required_evidence_roles": list(self.required_evidence_roles),
            "expected_effects": [item.value for item in self.expected_effects],
        }


class ManipulationDag(BaseModel):
    """A validated semantic DAG for one append-only plan revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["manipulation_dag_v1"] = "manipulation_dag_v1"
    task_id: str
    revision_id: str
    nodes: tuple[ManipulationDagNode, ...] = Field(min_length=1)
    dag_digest: str = ""

    @field_validator("task_id", "revision_id")
    @classmethod
    def validate_plan_identity(cls, value: str) -> str:
        return _identity(value, "plan identity")

    @model_validator(mode="after")
    def validate_graph(self) -> "ManipulationDag":
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("DAG node identities must be unique")
        known = set(node_ids)
        for node in self.nodes:
            missing = set(node.depends_on) - known
            if missing:
                raise ValueError("DAG dependency references an unknown node")
            if node.node_id in node.depends_on:
                raise ValueError("DAG nodes cannot depend on themselves")
            if node.retry_lineage.root_node_id not in known:
                raise ValueError("retry lineage references an unknown root node")
            if node.retry_lineage.parent_node_id is not None and node.retry_lineage.parent_node_id not in known:
                raise ValueError("retry lineage references an unknown parent node")
            if node.retry_lineage.retry_index == 0 and node.retry_lineage.root_node_id != node.node_id:
                raise ValueError("initial retry lineage root must equal node_id")
            if node.retry_lineage.parent_node_id is not None:
                parent = next(item for item in self.nodes if item.node_id == node.retry_lineage.parent_node_id)
                if parent.node_id not in node.depends_on:
                    raise ValueError("retry lineage parent must be a DAG dependency")
                if parent.retry_lineage.root_node_id != node.retry_lineage.root_node_id:
                    raise ValueError("retry lineage parent belongs to another root")
                if parent.retry_lineage.retry_index >= node.retry_lineage.retry_index:
                    raise ValueError("retry lineage index must increase from parent")
            if node.condition.kind is PlanConditionKind.NODE_STATE_EQUALS and node.condition.node_id not in known:
                raise ValueError("node condition references an unknown node")
        self._topological_order()
        expected = _stable_digest(
            {
                "version": self.version,
                "task_id": self.task_id,
                "revision_id": self.revision_id,
                "nodes": [
                    {"node_id": node.node_id, "node_digest": node.node_digest}
                    for node in sorted(self.nodes, key=lambda item: item.node_id)
                ],
            }
        )
        if self.dag_digest and self.dag_digest != expected:
            raise ValueError("dag_digest does not match DAG content")
        object.__setattr__(self, "dag_digest", expected)
        return self

    def _topological_order(self) -> tuple[str, ...]:
        nodes = {node.node_id: node for node in self.nodes}
        state: dict[str, int] = {}
        order: list[str] = []

        def visit(node_id: str) -> None:
            marker = state.get(node_id, 0)
            if marker == 1:
                raise ValueError("manipulation DAG contains a cycle")
            if marker == 2:
                return
            state[node_id] = 1
            for dependency in sorted(nodes[node_id].depends_on):
                visit(dependency)
            state[node_id] = 2
            order.append(node_id)

        for node in sorted(nodes):
            visit(node)
        return tuple(order)

    def topological_order(self) -> tuple[str, ...]:
        """Return a stable dependency-first order."""

        return self._topological_order()

    def ready_nodes(
        self,
        completed: Iterable[str],
        *,
        node_states: Mapping[str, NodeSettlementStatus | str] | None = None,
        evidence_revisions: Mapping[str, str] | None = None,
    ) -> tuple[ManipulationDagNode, ...]:
        """Return dependency-ready nodes whose bounded condition is satisfied."""

        completed_ids = set(completed)
        known = {node.node_id for node in self.nodes}
        if not completed_ids <= known:
            raise ManipulationPlanningError("completed set contains an unknown DAG node")
        return tuple(
            node
            for node_id in self.topological_order()
            if (node := next(item for item in self.nodes if item.node_id == node_id)).node_id not in completed_ids
            and set(node.depends_on) <= completed_ids
            and node.condition.evaluate(
                node_states=node_states or {},
                evidence_revisions=evidence_revisions or {},
            )
            is PlanConditionOutcome.SATISFIED
        )

    def node(self, node_id: str) -> ManipulationDagNode:
        """Return a node by identity or fail closed."""

        normalized = _identity(node_id, "node_id")
        for node in self.nodes:
            if node.node_id == normalized:
                return node
        raise ManipulationPlanningError("DAG node is unknown")


class ManipulationIntent(BaseModel):
    """Bounded semantic intent compiled from one DAG manipulation node."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["manipulation_intent_v1"] = "manipulation_intent_v1"
    task_id: str
    revision_id: str
    node_id: str
    entity_ref: str
    goal: str
    success_criteria: tuple[str, ...]
    allowed_arms: tuple[str, ...]
    coordination_mode: CoordinationMode
    observation_ref: str
    scene_revision: str
    frame_id: str
    calibration_ref: str
    candidate_set_ref: str
    constraints: tuple[str, ...] = ()
    motion_authorized: Literal[False] = False
    node_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("task_id", "revision_id", "node_id", "scene_revision", "frame_id")
    @classmethod
    def validate_intent_identities(cls, value: str) -> str:
        return _identity(value, "intent identity")

    @field_validator("entity_ref")
    @classmethod
    def validate_intent_entity(cls, value: str) -> str:
        return _ref(value, "entity://", "entity_ref")

    @field_validator("observation_ref")
    @classmethod
    def validate_observation(cls, value: str) -> str:
        return _ref(value, "observation://", "observation_ref")

    @field_validator("calibration_ref", "candidate_set_ref")
    @classmethod
    def validate_artifact_refs(cls, value: str, info) -> str:
        prefix = "candidate-set://" if info.field_name == "candidate_set_ref" else "artifact://"
        return _ref(value, prefix, info.field_name)

    @field_validator("goal")
    @classmethod
    def validate_intent_goal(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("intent goal must be non-empty")
        return normalized

    @field_validator("success_criteria", "constraints")
    @classmethod
    def validate_intent_text(cls, values: Sequence[str]) -> tuple[str, ...]:
        normalized = tuple(str(item).strip() for item in values)
        if any(not item for item in normalized):
            raise ValueError("intent text items must be non-empty")
        return normalized

    @field_validator("allowed_arms")
    @classmethod
    def validate_intent_arms(cls, values: Sequence[str]) -> tuple[str, ...]:
        normalized = tuple(_identity(item, "arm_id") for item in values)
        if not normalized or len(normalized) != len(set(normalized)):
            raise ValueError("intent allowed_arms must be unique and non-empty")
        return normalized

    @model_validator(mode="after")
    def validate_coordination(self) -> "ManipulationIntent":
        if not self.success_criteria:
            raise ValueError("intent requires at least one success criterion")
        if self.coordination_mode is CoordinationMode.SINGLE_ARM and len(self.allowed_arms) != 1:
            raise ValueError("single_arm intent must name exactly one arm")
        if self.coordination_mode is CoordinationMode.BIMANUAL and len(self.allowed_arms) != 2:
            raise ValueError("bimanual intent must name exactly two arms")
        if self.observation_ref != f"observation://{self.scene_revision}/{self.frame_id}":
            raise ValueError("intent observation identity is invalid")
        if self.candidate_set_ref != f"candidate-set://{self.scene_revision}/{self.frame_id}":
            raise ValueError("intent candidate-set identity is invalid")
        return self


def compile_manipulation_intent(
    task_id: str,
    revision_id: str,
    node: ManipulationDagNode,
    *,
    observation_ref: str,
    scene_revision: str,
    frame_id: str,
    calibration_ref: str,
    candidate_set_ref: str,
    constraints: Sequence[str] = (),
) -> ManipulationIntent:
    """Compile one semantic node into a no-motion, identity-bound intent."""

    if node.operation is not ManipulationOperation.MANIPULATE:
        raise ManipulationPlanningError("only manipulation nodes compile to a manipulation intent")
    return ManipulationIntent(
        task_id=task_id,
        revision_id=revision_id,
        node_id=node.node_id,
        entity_ref=node.entity_ref,
        goal=node.goal,
        success_criteria=tuple(node.success_criteria),
        allowed_arms=tuple(node.allowed_arms),
        coordination_mode=node.coordination_mode,
        observation_ref=observation_ref,
        scene_revision=scene_revision,
        frame_id=frame_id,
        calibration_ref=calibration_ref,
        candidate_set_ref=candidate_set_ref,
        constraints=tuple(constraints),
        node_digest=node.node_digest,
    )


class RouteFailure(BaseModel):
    """Bounded rejection evidence for one candidate/arm route option."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["route_failure_v1"] = "route_failure_v1"
    candidate_ref: str
    arm_ids: tuple[str, ...]
    phase: str
    code: str
    owner: Literal["input", "binding", "planner", "policy", "collision", "readiness", "infrastructure"]
    detail: str
    route_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("candidate_ref")
    @classmethod
    def validate_candidate_ref(cls, value: str) -> str:
        return _ref(value, "candidate://", "candidate_ref")

    @field_validator("arm_ids")
    @classmethod
    def validate_arm_ids(cls, values: Sequence[str]) -> tuple[str, ...]:
        normalized = tuple(_identity(item, "arm_id") for item in values)
        if not normalized or len(normalized) != len(set(normalized)):
            raise ValueError("route failure arm_ids must be unique and non-empty")
        return normalized

    @field_validator("phase", "code", "detail")
    @classmethod
    def validate_failure_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("route failure text must be non-empty")
        return normalized


class ReplanSignal(BaseModel):
    """A fail-closed request to create a new PlanRevision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["manipulation_replan_signal_v1"] = "manipulation_replan_signal_v1"
    task_id: str
    revision_id: str
    node_id: str
    status: Literal["replan_required"] = "replan_required"
    reason: Literal[
        "all_routes_rejected",
        "scene_revision_stale",
        "candidate_set_invalid",
        "semantic_verification_failed",
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
    def validate_replan_ids(cls, value: str) -> str:
        return _identity(value, "replan identity")

    @field_validator("candidate_set_ref")
    @classmethod
    def validate_replan_candidate_set(cls, value: str) -> str:
        return _ref(value, "candidate-set://", "candidate_set_ref")

    @field_validator("preserved_constraints", "next_actions")
    @classmethod
    def validate_replan_lists(cls, values: Sequence[str]) -> tuple[str, ...]:
        normalized = tuple(str(item).strip() for item in values)
        if any(not item for item in normalized):
            raise ValueError("replan items must be non-empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("replan items must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_candidate_digest(self) -> "ReplanSignal":
        if self.reason == "candidate_set_invalid":
            if self.failed_routes:
                raise ValueError("candidate_set_invalid cannot carry route failures")
        elif not self.failed_routes:
            raise ValueError("route-related replanning requires failed routes")
        if not self.next_actions:
            raise ValueError("replan signal requires at least one next action")
        expected = _stable_digest(self._candidate_payload())
        if self.candidate_digest != expected:
            raise ValueError("candidate_digest does not match replan signal")
        return self

    def _candidate_payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "revision_id": self.revision_id,
            "node_id": self.node_id,
            "reason": self.reason,
            "failed_routes": [item.model_dump(mode="json") for item in self.failed_routes],
            "preserved_constraints": list(self.preserved_constraints),
            "next_actions": list(self.next_actions),
            "scene_revision": self.scene_revision,
            "candidate_set_ref": self.candidate_set_ref,
        }


class ReplanCoordinator:
    """Build replan signals without mutating task state or starting execution."""

    def __init__(self, *, max_failures: int = 256) -> None:
        if not isinstance(max_failures, int) or max_failures < 1:
            raise ValueError("max_failures must be positive")
        self.max_failures = max_failures

    def build_signal(
        self,
        intent: ManipulationIntent,
        failures: Sequence[RouteFailure],
        *,
        reason: Literal[
            "all_routes_rejected",
            "scene_revision_stale",
            "candidate_set_invalid",
            "semantic_verification_failed",
            "execution_unknown",
        ] = "all_routes_rejected",
        next_actions: Sequence[str] = ("regenerate_candidates", "refresh_observation"),
    ) -> ReplanSignal:
        if not isinstance(intent, ManipulationIntent):
            raise TypeError("replan intent must be a ManipulationIntent")
        if not isinstance(failures, Sequence) or (not failures and reason != "candidate_set_invalid"):
            raise ValueError("replan requires at least one failed route")
        if len(failures) > self.max_failures:
            raise ValueError("replan failure list exceeds configured bound")
        validated = tuple(
            item if isinstance(item, RouteFailure) else RouteFailure.model_validate(item)
            for item in failures
        )
        if reason != "candidate_set_invalid":
            allowed = set(intent.allowed_arms)
            identities: set[tuple[str, tuple[str, ...]]] = set()
            for failure in validated:
                if not set(failure.arm_ids) <= allowed:
                    raise ManipulationPlanningError("route failure arm is not allowed by intent")
                identity = (failure.candidate_ref, failure.arm_ids)
                if identity in identities:
                    raise ManipulationPlanningError("route failure identity is duplicated")
                identities.add(identity)
        next_action_items = tuple(next_actions)
        candidate_payload = {
            "task_id": intent.task_id,
            "revision_id": intent.revision_id,
            "node_id": intent.node_id,
            "reason": reason,
            "failed_routes": [item.model_dump(mode="json") for item in validated],
            "preserved_constraints": list(intent.constraints),
            "next_actions": list(next_action_items),
            "scene_revision": intent.scene_revision,
            "candidate_set_ref": intent.candidate_set_ref,
        }
        payload = {
            "task_id": intent.task_id,
            "revision_id": intent.revision_id,
            "node_id": intent.node_id,
            "status": "replan_required",
            "reason": reason,
            "failed_routes": [item.model_dump(mode="json") for item in validated],
            "preserved_constraints": intent.constraints,
            "next_actions": next_action_items,
            "scene_revision": intent.scene_revision,
            "candidate_set_ref": intent.candidate_set_ref,
            "motion_authorized": False,
            "candidate_digest": _stable_digest(candidate_payload),
        }
        try:
            json.dumps(payload, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ManipulationPlanningError("replan signal must contain finite JSON") from exc
        return ReplanSignal(**payload)

__all__ = [
    "CoordinationMode",
    "ExpectedEffect",
    "ManipulationDag",
    "ManipulationDagNode",
    "ManipulationIntent",
    "ManipulationOperation",
    "ManipulationPlanningError",
    "NodeSettlementStatus",
    "PlanConditionKind",
    "PlanConditionOutcome",
    "PlanCondition",
    "ReplanCoordinator",
    "ReplanSignal",
    "RouteFailure",
    "RetryLineage",
    "compile_manipulation_intent",
]
