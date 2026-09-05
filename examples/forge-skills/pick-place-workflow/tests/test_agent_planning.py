from __future__ import annotations

import pytest
from PhyAgentOS.planning import (
    AdmissionContext,
    ResourceClaim,
    ToolCallEnvelope,
    ToolSpecPolicy,
    derive_ready_nodes,
)
from pydantic import ValidationError

from pick_place_workflow.agent_planning import (
    AgentPlanningError,
    AgentSubtaskSpec,
    DynamicToolPlanner,
    ToolSelectionError,
    compose_agent_plan,
    select_planning_mode,
)


def _plan():
    return compose_agent_plan(
        "task-1",
        "revision-1",
        (
            AgentSubtaskSpec(
                subtask_id="relocate-red",
                entity_ref="entity://red-block",
                required_evidence=("observation:red",),
                resources=(ResourceClaim(resource_class="arm:right"),),
            ),
            AgentSubtaskSpec(
                subtask_id="relocate-blue",
                entity_ref="entity://blue-block",
                depends_on=(),
                required_evidence=("observation:blue",),
                resources=(ResourceClaim(resource_class="arm:left"),),
            ),
        ),
        planner_decision_digest="1" * 64,
        policy_snapshot_digest="2" * 64,
    )


def _policy(tool_id: str, capability: str) -> ToolSpecPolicy:
    return ToolSpecPolicy(
        tool_id=tool_id,
        semantics="query",
        spec_digest="3" * 64,
        capabilities=(capability,),
        required_evidence=("observation:red",),
    )


def test_agent_plan_compiles_multi_entity_partial_order_and_verify_join():
    plan = _plan()
    assert plan.mode == "agent_composed"
    assert derive_ready_nodes(plan.graph, {}, {"observation:red", "observation:blue"}) == (
        "relocate-blue",
        "relocate-red",
    )
    assert plan.graph.nodes[-1].node_id == "verify"
    assert set(plan.graph.nodes[-1].dependencies) == {"relocate-red", "relocate-blue"}
    assert dict(plan.entity_bindings)["relocate-red"] == "entity://red-block"


def test_agent_plan_rejects_duplicate_unknown_and_invalid_bindings():
    with pytest.raises(AgentPlanningError, match="unknown subtask"):
        compose_agent_plan(
            "task-1", "revision-1",
            (AgentSubtaskSpec(subtask_id="red", entity_ref="entity://red", depends_on=("missing",)),),
            planner_decision_digest="1" * 64, policy_snapshot_digest="2" * 64,
        )
    with pytest.raises(AgentPlanningError, match="unique"):
        compose_agent_plan(
            "task-1", "revision-1",
            (AgentSubtaskSpec(subtask_id="red", entity_ref="entity://red"), AgentSubtaskSpec(subtask_id="red", entity_ref="entity://red2")),
            planner_decision_digest="1" * 64, policy_snapshot_digest="2" * 64,
        )
    with pytest.raises(ValidationError):
        AgentSubtaskSpec(subtask_id="red", entity_ref="not-an-entity")
    with pytest.raises(AgentPlanningError, match="cycle"):
        compose_agent_plan(
            "task-1", "revision-1",
            (
                AgentSubtaskSpec(subtask_id="red", entity_ref="entity://red", depends_on=("blue",)),
                AgentSubtaskSpec(subtask_id="blue", entity_ref="entity://blue", depends_on=("red",)),
            ),
            planner_decision_digest="1" * 64, policy_snapshot_digest="2" * 64,
        )


def test_dynamic_planner_selects_alternative_tools_and_admits_without_execution():
    plan = _plan()
    planner = DynamicToolPlanner(
        plan,
        (
            _policy("understand.rgb", "object.relocate"),
            _policy("understand.depth", "object.relocate"),
        ),
    )
    assert planner.candidate_tools("relocate-red") == ("understand.rgb", "understand.depth")
    call = ToolCallEnvelope(
        task_id="task-1", revision_id="revision-1", node_id="relocate-red",
        tool_id="understand.depth", tool_spec_digest="3" * 64,
        input_binding_digest="4" * 64, scene_revision="scene-1",
        idempotency_key="idem-1", semantics="query",
    )
    decision = planner.admit(call, AdmissionContext(scene_revision="scene-1", evidence_refs=frozenset({"observation:red"})))
    assert decision.allowed is True
    assert decision.motion_authorized is False
    assert planner.admit(call, AdmissionContext(scene_revision="scene-2", evidence_refs=frozenset({"observation:red"}))).code == "stale_scene"
    assert planner.admit(call, AdmissionContext(scene_revision="scene-1")).code == "node_not_ready"
    with pytest.raises(ToolSelectionError):
        planner.candidate_tools("missing")
    rejected = planner.admit(call.model_copy(update={"tool_id": "other"}), AdmissionContext(scene_revision="scene-1", evidence_refs=frozenset({"observation:red"})))
    assert rejected.code == "tool_not_declared"


def test_mode_switch_is_explicit_and_baseline_remains_untouched():
    assert select_planning_mode("baseline") == "baseline"
    assert select_planning_mode("agent_composed") == "agent_composed"
    with pytest.raises(AgentPlanningError):
        select_planning_mode("fixed")
