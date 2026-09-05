"""AgentLoop bridge for PAOS agent-composed planning.

The bridge is deliberately a read-only adapter.  It exposes the current
PlanGraph ready set and performs pure admission before a Forge Tool wrapper is
invoked.  Task lifecycle, Gateway transport, evidence persistence, and motion
authority remain owned by their existing components.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Callable

from PhyAgentOS.planning import (
    AdmissionContext,
    AdmissionDecision,
    PlanGraph,
    PlanningExecutionBinding,
    ToolCallEnvelope,
    ToolSpecPolicy,
    admit_tool_call,
    derive_ready_nodes,
    plan_node_digest,
)


class PlanningDispatchError(ValueError):
    """A Forge Tool call cannot be admitted by the active semantic graph."""


class AgentComposedDispatch:
    """Pure admission facade used by AgentLoop for one frozen PlanGraph."""

    _FORGE_CREATE_TOOLS = {
        "forge_tool_query": "query",
        "forge_tool_start_action": "action",
        "forge_tool_start_session": "session",
    }

    def __init__(
        self,
        graph: PlanGraph,
        policies: tuple[ToolSpecPolicy, ...],
        context: AdmissionContext,
        context_provider: Callable[[str], AdmissionContext] | None = None,
    ) -> None:
        if len({policy.tool_id for policy in policies}) != len(policies):
            raise PlanningDispatchError("planning ToolSpec identities must be unique")
        self.graph = graph
        self.policies = policies
        self.context = context
        self.context_provider = context_provider
        self._policies = {policy.tool_id: policy for policy in policies}

    @classmethod
    def from_task(
        cls,
        task: Any,
        *,
        context_provider: Callable[[str], AdmissionContext],
    ) -> "AgentComposedDispatch":
        """Build a dispatch from an existing task aggregate and frozen binding."""
        graph = getattr(getattr(task, "active_revision", None), "plan_graph", None)
        if graph is None:
            raise PlanningDispatchError("AgentTask active revision has no concrete PlanGraph")
        binding = getattr(task, "primary_skill_binding", None)
        if binding is None:
            raise PlanningDispatchError("AgentTask has no frozen Skill binding")
        policies = tuple(
            item.planning_policy
            for item in getattr(binding, "required_tools", ())
            if item.planning_policy is not None
        )
        if not policies:
            raise PlanningDispatchError("frozen Skill binding has no planning ToolSpec projections")
        context = context_provider(graph.task_id)
        if not isinstance(context, AdmissionContext):
            raise PlanningDispatchError("planning context provider returned an invalid context")
        return cls(
            graph,
            policies,
            context,
            context_provider=context_provider,
        )

    def describe(self) -> dict[str, Any]:
        """Return bounded data for the Agent; no provider payloads are exposed."""
        context = self._current_context()
        settlements = dict(context.settlements)
        conditions = dict(context.condition_facts)
        ready = derive_ready_nodes(
            self.graph,
            settlements,
            set(context.evidence_refs),
            conditions,
        )
        nodes = {node.node_id: node for node in self.graph.nodes}
        return {
            "ok": True,
            "mode": "agent_composed",
            "task_id": self.graph.task_id,
            "revision_id": self.graph.revision_id,
            "graph_digest": self.graph.graph_digest,
            "scene_revision": context.scene_revision,
            "ready_nodes": [
                {
                    "node_id": node_id,
                    "obligation_id": nodes[node_id].obligation_id,
                    "capability": nodes[node_id].capability,
                    "candidate_tool_ids": [
                        policy.tool_id
                        for policy in self.policies
                        if nodes[node_id].capability in policy.capabilities
                    ],
                }
                for node_id in ready
            ],
            "motion_authorized": False,
        }

    def admit_forge_tool(
        self, wrapper_name: str, arguments: Mapping[str, Any]
    ) -> AdmissionDecision | None:
        """Admit a task-bound Forge create call, or return ``None`` for diagnostics.

        Status/result/cancel wrappers are control-plane reconciliation calls and
        remain governed by Coordinator ownership checks; only calls that create
        a Query/Action/Session are subject to semantic-node admission here.
        """
        semantics = self._FORGE_CREATE_TOOLS.get(wrapper_name)
        if semantics is None:
            return None
        task_id = arguments.get("task_id")
        if task_id is None:
            return None
        if not isinstance(task_id, str) or task_id != self.graph.task_id:
            return AdmissionDecision(
                allowed=False,
                code="identity_mismatch",
                detail="task-bound Forge call is not bound to the active PlanGraph",
                node_id="unknown",
                tool_id=str(arguments.get("tool_id", "unknown")),
            )
        tool_id = arguments.get("tool_id")
        binding = arguments.get("planning_binding")
        if not isinstance(tool_id, str) or not isinstance(binding, Mapping):
            return AdmissionDecision(
                allowed=False,
                code="missing_planning_binding",
                detail="agent-composed Forge calls require a complete planning_binding",
                node_id="unknown",
                tool_id=str(tool_id or "unknown"),
            )
        policy = self._policies.get(tool_id)
        if policy is None or policy.semantics != semantics:
            return AdmissionDecision(
                allowed=False,
                code="tool_not_declared",
                detail="Tool has no matching frozen planning projection",
                node_id=str(binding.get("node_id", "unknown")),
                tool_id=tool_id,
            )
        try:
            planning_binding = PlanningExecutionBinding.model_validate(dict(binding))
            node_id = planning_binding.node_id
            input_digest = planning_binding.input_binding_digest
            node = next(node for node in self.graph.nodes if node.node_id == node_id)
            if planning_binding.node_digest != plan_node_digest(node):
                raise PlanningDispatchError("planning binding node digest does not match the active graph")
            if planning_binding.obligation_id != node.obligation_id:
                raise PlanningDispatchError("planning binding obligation does not match the active graph")
            if node.node_id == "verify":
                raise PlanningDispatchError("verification node cannot create a Forge Tool")
            idempotency = hashlib.sha256(
                json.dumps(
                    {
                        "task_id": task_id,
                        "revision_id": self.graph.revision_id,
                        "node_id": node_id,
                        "tool_id": tool_id,
                        "arguments": arguments.get("arguments", {}),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest()
            context = self._current_context()
            call = ToolCallEnvelope(
                task_id=task_id,
                revision_id=self.graph.revision_id,
                node_id=node_id,
                tool_id=tool_id,
                tool_spec_digest=policy.spec_digest,
                input_binding_digest=input_digest,
                arguments=dict(arguments.get("arguments", {})),
                caller_id="paos:agent-loop",
                scene_revision=context.scene_revision,
                idempotency_key=idempotency,
                semantics=semantics,
            )
        except (KeyError, StopIteration, TypeError, ValueError) as exc:
            return AdmissionDecision(
                allowed=False,
                code="invalid_planning_binding",
                detail=f"planning binding is invalid: {exc}",
                node_id=str(binding.get("node_id", "unknown")),
                tool_id=tool_id,
            )
        return admit_tool_call(self.graph, call, policy, context)

    def _current_context(self) -> AdmissionContext:
        if self.context_provider is None:
            return self.context
        context = self.context_provider(self.graph.task_id)
        if not isinstance(context, AdmissionContext):
            raise PlanningDispatchError("planning context provider returned an invalid context")
        self.context = context
        return context


__all__ = ["AgentComposedDispatch", "PlanningDispatchError"]
