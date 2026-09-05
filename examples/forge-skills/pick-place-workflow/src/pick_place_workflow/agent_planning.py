"""Agent-composed semantic planning projection for the pick-place Skill.

The legacy ``LongHorizonWorkflow`` remains the deterministic baseline/replay
projection.  This module adds the task-level seam: the Agent supplies semantic
subtasks, the planning library builds a concrete DAG, and the Agent may choose
among Tool candidates.  Nothing here invokes a Tool, persists a task, leases a
robot, or authorizes motion.
"""

from __future__ import annotations

import re
from typing import Literal

from PhyAgentOS.planning import (
    AdmissionContext,
    AdmissionDecision,
    PlanGraph,
    PlanNode,
    ResourceClaim,
    ToolCallEnvelope,
    ToolSpecPolicy,
    admit_tool_call,
    plan_graph_digest,
    validate_graph,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AGENT_PLAN_VERSION = "pick_and_place_agent_plan_v1"
PlanningMode = Literal["baseline", "agent_composed"]
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]+$")
_ENTITY_REF = re.compile(r"^entity://\S+$")


class AgentPlanningError(ValueError):
    """Raised when an Agent-composed semantic plan is invalid."""


class ToolSelectionError(AgentPlanningError):
    """Raised when no frozen ToolSpec candidate matches a semantic capability."""


class AgentSubtaskSpec(BaseModel):
    """One semantic obligation supplied by the Agent/task decomposer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    subtask_id: str
    entity_ref: str
    capability: str = "object.relocate"
    depends_on: tuple[str, ...] = ()
    required_evidence: tuple[str, ...] = ()
    produced_evidence: tuple[str, ...] = ()
    resources: tuple[ResourceClaim, ...] = ()

    @field_validator("subtask_id", "capability")
    @classmethod
    def safe_identity(cls, value: str) -> str:
        if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
            raise ValueError("subtask_id and capability must be path-safe identifiers")
        return value

    @field_validator("entity_ref")
    @classmethod
    def entity_identity(cls, value: str) -> str:
        if not isinstance(value, str) or _ENTITY_REF.fullmatch(value) is None:
            raise ValueError("entity_ref must be an entity:// reference")
        return value

    @field_validator("depends_on", "required_evidence", "produced_evidence")
    @classmethod
    def unique_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("subtask values must be unique")
        return value


class AgentComposedPlan(BaseModel):
    """Concrete semantic DAG plus opaque entity bindings for one revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["pick_and_place_agent_plan_v1"] = AGENT_PLAN_VERSION
    mode: Literal["agent_composed"] = "agent_composed"
    graph: PlanGraph
    entity_bindings: tuple[tuple[str, str], ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bindings(self) -> "AgentComposedPlan":
        node_ids = {node.node_id for node in self.graph.nodes if node.node_id != "verify"}
        bound_ids = {subtask_id for subtask_id, _ in self.entity_bindings}
        if node_ids != bound_ids:
            raise AgentPlanningError("entity bindings must cover every composed subtask exactly")
        if len(self.entity_bindings) != len(bound_ids):
            raise AgentPlanningError("entity binding identities must be unique")
        return self

    def candidate_tools(self, node_id: str, policies: tuple[ToolSpecPolicy, ...]) -> tuple[str, ...]:
        node = next((item for item in self.graph.nodes if item.node_id == node_id), None)
        if node is None:
            raise ToolSelectionError(f"unknown semantic node: {node_id}")
        return tuple(
            policy.tool_id
            for policy in policies
            if node.capability in policy.capabilities
        )


def compose_agent_plan(
    task_id: str,
    revision_id: str,
    subtasks: tuple[AgentSubtaskSpec, ...],
    *,
    planner_decision_digest: str,
    policy_snapshot_digest: str,
) -> AgentComposedPlan:
    """Compile Agent semantic subtasks into a no-motion PlanGraph."""

    if not subtasks:
        raise AgentPlanningError("agent-composed plan requires at least one subtask")
    ids = [item.subtask_id for item in subtasks]
    if len(ids) != len(set(ids)) or "verify" in set(ids):
        raise AgentPlanningError("subtask identities must be unique and cannot use verify")
    known = set(ids)
    if any(set(item.depends_on) - known for item in subtasks):
        raise AgentPlanningError("subtask dependency references an unknown subtask")
    nodes = tuple(
        PlanNode(
            node_id=item.subtask_id,
            obligation_id=item.subtask_id,
            capability=item.capability,
            dependencies=item.depends_on,
            required_evidence=item.required_evidence,
            produced_evidence=item.produced_evidence,
            resources=item.resources,
        )
        for item in subtasks
    ) + (PlanNode(
        node_id="verify",
        obligation_id="verify-task",
        capability="task.verify",
        dependencies=tuple(ids),
    ),)
    payload = {
        "schema_version": "paos-plan-graph/v1",
        "task_id": task_id,
        "revision_id": revision_id,
        "graph_digest": "0" * 64,
        "planner_decision_digest": planner_decision_digest,
        "policy_snapshot_digest": policy_snapshot_digest,
        "nodes": [node.model_dump(mode="json") for node in nodes],
    }
    payload["graph_digest"] = plan_graph_digest(payload)
    graph = PlanGraph.model_validate(payload)
    try:
        validate_graph(graph)
    except ValueError as exc:
        raise AgentPlanningError(str(exc)) from exc
    return AgentComposedPlan(
        graph=graph,
        entity_bindings=tuple((item.subtask_id, item.entity_ref) for item in subtasks),
    )


def select_planning_mode(mode: PlanningMode) -> PlanningMode:
    """Validate the migration switch without changing the baseline reducer."""

    if mode not in {"baseline", "agent_composed"}:
        raise AgentPlanningError(f"unsupported pick-place planning mode: {mode!r}")
    return mode


class DynamicToolPlanner:
    """Pure candidate selection/admission over a frozen Agent-composed plan."""

    def __init__(self, plan: AgentComposedPlan, policies: tuple[ToolSpecPolicy, ...]) -> None:
        if len({policy.tool_id for policy in policies}) != len(policies):
            raise AgentPlanningError("ToolSpec policy identities must be unique")
        self.plan = plan
        self.policies = policies
        self._by_id = {policy.tool_id: policy for policy in policies}

    def candidate_tools(self, node_id: str) -> tuple[str, ...]:
        candidates = self.plan.candidate_tools(node_id, self.policies)
        if not candidates:
            raise ToolSelectionError(f"no Tool candidate matches semantic node {node_id!r}")
        return candidates

    def admit(
        self,
        call: ToolCallEnvelope,
        context: AdmissionContext,
    ) -> AdmissionDecision:
        candidates = self.candidate_tools(call.node_id)
        if call.tool_id not in candidates:
            return AdmissionDecision(
                allowed=False,
                code="tool_not_declared",
                detail="Tool is not a candidate for this semantic node",
                node_id=call.node_id,
                tool_id=call.tool_id,
            )
        return admit_tool_call(self.plan.graph, call, self._by_id[call.tool_id], context)


__all__ = [
    "AGENT_PLAN_VERSION",
    "AgentComposedPlan",
    "AgentPlanningError",
    "AgentSubtaskSpec",
    "DynamicToolPlanner",
    "PlanningMode",
    "ToolSelectionError",
    "compose_agent_plan",
    "select_planning_mode",
]
