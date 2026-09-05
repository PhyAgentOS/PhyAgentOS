from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from PhyAgentOS.planning import (
    AdmissionContext,
    PlanGraph,
    PlanNode,
    ResourceClaim,
    ToolCallEnvelope,
    ToolResultEnvelope,
    ToolSpecPolicy,
    WorkflowPolicy,
    WorkflowPolicyCandidate,
    admit_tool_call,
    build_replan_delta,
    derive_ready_nodes,
    evaluate_conditions,
    invalidate_stale_nodes,
    make_decision_trace,
    plan_graph_digest,
    settle_node,
    validate_graph,
    validate_policy_edges,
    workflow_policy_digest,
)


def _graph() -> PlanGraph:
    nodes = (
        PlanNode(
            node_id="pick-red",
            obligation_id="relocate-red",
            capability="object.acquire",
            required_evidence=("observation:red",),
            produced_evidence=("acquired:red",),
            resources=(ResourceClaim(resource_class="arm:right"),),
        ),
        PlanNode(
            node_id="place-red",
            obligation_id="relocate-red",
            capability="object.place",
            dependencies=("pick-red",),
            required_evidence=("acquired:red",),
            resources=(ResourceClaim(resource_class="arm:right"),),
        ),
        PlanNode(
            node_id="verify",
            obligation_id="verify-task",
            capability="scene.verify",
            dependencies=("place-red",),
        ),
    )
    payload = {
        "schema_version": "paos-plan-graph/v1",
        "task_id": "task-1",
        "revision_id": "revision-1",
        "graph_digest": "0" * 64,
        "planner_decision_digest": "1" * 64,
        "policy_snapshot_digest": "2" * 64,
        "nodes": [node.model_dump(mode="json") for node in nodes],
    }
    payload["graph_digest"] = plan_graph_digest(payload)
    return PlanGraph.model_validate(payload)


def _call(*, node_id: str = "pick-red", semantics: str = "query") -> ToolCallEnvelope:
    return ToolCallEnvelope(
        task_id="task-1",
        revision_id="revision-1",
        node_id=node_id,
        tool_id="scene.observe",
        tool_spec_digest="3" * 64,
        input_binding_digest="4" * 64,
        arguments={"sensor_ref": "camera/front"},
        caller_id="agent:planner",
        scene_revision="scene-1",
        idempotency_key="idem-1",
        semantics=semantics,
    )


def _tool() -> ToolSpecPolicy:
    return ToolSpecPolicy(
        tool_id="scene.observe",
        semantics="query",
        spec_digest="3" * 64,
        capabilities=("object.acquire",),
        required_evidence=("observation:red",),
        produced_evidence=("observation:red",),
        resource_claims=(),
    )


def test_graph_digest_topology_and_ready_set_are_deterministic():
    graph = _graph()
    assert validate_graph(graph) == ("pick-red", "place-red", "verify")
    assert derive_ready_nodes(graph, {}, {"observation:red"}) == ("pick-red",)
    assert derive_ready_nodes(graph, {"pick-red": "completed"}, {"acquired:red"}) == ("place-red",)
    assert invalidate_stale_nodes(
        graph,
        "scene-2",
        {"pick-red": "scene-1", "place-red": "scene-2", "verify": "scene-2"},
    ) == ("pick-red",)
    with pytest.raises(ValueError, match="unknown nodes"):
        invalidate_stale_nodes(graph, "scene-2", {"unknown": "scene-1"})


def test_cycle_and_condition_fail_closed():
    nodes = (
        PlanNode(node_id="a", obligation_id="a", capability="x", dependencies=("b",)),
        PlanNode(node_id="b", obligation_id="b", capability="x", dependencies=("a",)),
    )
    payload = {
        "schema_version": "paos-plan-graph/v1",
        "task_id": "task-1", "revision_id": "revision-1", "graph_digest": "0" * 64,
        "planner_decision_digest": "1" * 64, "policy_snapshot_digest": "2" * 64,
        "nodes": [node.model_dump(mode="json") for node in nodes],
    }
    payload["graph_digest"] = plan_graph_digest(payload)
    graph = PlanGraph.model_validate(payload)
    with pytest.raises(ValueError, match="cycle"):
        validate_graph(graph)
    assert evaluate_conditions(("ready",), {}) is False
    assert evaluate_conditions(("ready",), {"ready": True}) is True


def test_admission_checks_dynamic_choice_and_failure_paths():
    graph = _graph()
    context = AdmissionContext(scene_revision="scene-1", evidence_refs=frozenset({"observation:red"}))
    immutable_context = AdmissionContext(
        scene_revision="scene-1", settlements={"pick-red": "completed"}, condition_facts={"arm_ready": True}
    )
    assert immutable_context.settlements == (("pick-red", "completed"),)
    assert immutable_context.condition_facts == (("arm_ready", True),)
    decision = admit_tool_call(graph, _call(), _tool(), context)
    assert decision.allowed is True
    assert decision.motion_authorized is False
    with pytest.raises(ValidationError):
        type(decision).model_validate(decision.model_copy(update={"motion_authorized": True}).model_dump())
    assert admit_tool_call(graph, _call(), _tool(), context.model_copy(update={"scene_revision": "scene-2"})).code == "stale_scene"
    assert admit_tool_call(graph, _call(), _tool(), AdmissionContext(scene_revision="scene-1")).code == "node_not_ready"
    assert admit_tool_call(graph, _call(), _tool().model_copy(update={"spec_digest": "5" * 64}), context).code == "tool_binding_mismatch"
    assert admit_tool_call(graph, _call(), _tool(), context.model_copy(update={"resources_in_use": frozenset({"arm:right"})})).code == "resource_conflict"
    assert admit_tool_call(
        graph,
        _call(),
        _tool().model_copy(update={"capabilities": ("scene.verify",)}),
        context,
    ).code == "capability_mismatch"
    assert admit_tool_call(
        graph,
        _call(),
        _tool().model_copy(update={"preconditions": ("arm_ready",)}),
        context,
    ).code == "precondition_failed"
    assert admit_tool_call(
        graph,
        _call(),
        _tool().model_copy(update={"preconditions": ("arm_ready",)}),
        context.model_copy(update={"condition_facts": {"arm_ready": True}}),
    ).allowed is True


def test_settlement_distinguishes_success_unknown_failure_cancel_and_stale():
    node = _graph().nodes[0]
    base = {"task_id": "task-1", "revision_id": "revision-1", "node_id": node.node_id, "tool_id": "scene.observe"}
    assert settle_node(node, ToolResultEnvelope(**base, status="unknown"), current_scene_revision="scene-1").status == "outcome_unknown"
    assert settle_node(node, ToolResultEnvelope(**base, status="failed", failure_code="timeout"), current_scene_revision="scene-1").status == "failed"
    assert settle_node(node, ToolResultEnvelope(**base, status="cancelled"), current_scene_revision="scene-1").status == "cancelled_before_start"
    assert settle_node(node, ToolResultEnvelope(**base, status="succeeded", world_changed=True, new_scene_revision="scene-2"), current_scene_revision="scene-1").status == "completed"
    assert settle_node(node, ToolResultEnvelope(**base, status="succeeded", world_changed=True, new_scene_revision="scene-1"), current_scene_revision="scene-1").status == "stale"
    with pytest.raises(ValidationError):
        ToolResultEnvelope(**base, status="failed", world_changed=True)


def test_replan_invalidates_transitive_descendants_without_creating_revision():
    graph = _graph()
    settlement = settle_node(
        graph.nodes[0],
        ToolResultEnvelope(task_id="task-1", revision_id="revision-1", node_id="pick-red", tool_id="scene.observe", status="failed", failure_code="no_candidate"),
        current_scene_revision="scene-1",
    )
    delta = build_replan_delta(graph, settlement, fresh_evidence_requirements=("observation:red", "observation:red"))
    assert delta.invalidate_node_ids == ("place-red", "verify")
    assert delta.preserve_node_ids == ()
    assert delta.retry_parent_node_id == "pick-red"
    assert not hasattr(delta, "new_revision_id")


def test_trace_policy_and_candidate_are_review_gated():
    trace = make_decision_trace(_call(), candidate_tool_ids=("scene.observe", "scene.query"), context={"arm": "right"}, reason="fresh observation required")
    assert len(trace.context_digest) == 64
    with pytest.raises(ValidationError, match="selected Tool"):
        type(trace).model_validate(trace.model_copy(update={"selected_tool_id": "other"}).model_dump())
    policy = WorkflowPolicy(
        policy_id="pick-place-baseline", version="1", partial_order_edges=(("observe", "acquire"),),
        tunable_parameters=("candidate_ranking",), provider_owned_parameters=("arm_profile",),
        safety_immutable_parameters=("joint_limits",),
    )
    assert validate_policy_edges(policy) == ("observe", "acquire")
    assert len(workflow_policy_digest(policy)) == 64
    with pytest.raises(ValueError, match="cycle"):
        validate_policy_edges(
            policy.model_copy(update={"partial_order_edges": (("observe", "acquire"), ("acquire", "observe"))})
        )
    candidate = WorkflowPolicyCandidate(
        candidate_id="candidate-1", base_policy_digest="1" * 64, proposed_policy_digest="2" * 64,
        source_episode_ids=("episode-1",), verification_receipts=("artifact://receipt/1",),
        change_summary="prefer re-observation after stale scene",
    )
    assert candidate.status == "pending_review"
    with pytest.raises(ValidationError):
        WorkflowPolicy(policy_id="bad", version="1", tunable_parameters=("joint_limits",), safety_immutable_parameters=("joint_limits",))


def test_module_is_pure_and_does_not_define_motion_authority():
    root = Path(__file__).parents[1] / "PhyAgentOS" / "planning"
    source = "\n".join(path.read_text() for path in root.glob("*.py"))
    assert "sqlite3" not in source
    assert "httpx" not in source
    assert "motion_authorized=True" not in source


def test_task_lifecycle_models_can_bind_graph_and_node_trace():
    from PhyAgentOS.forge.task import PlanRevision, ToolExecutionRecord

    revision = PlanRevision(
        revision_id="revision-1",
        number=1,
        reason="agent composed semantic DAG",
        plan_graph_ref="artifact://plans/task-1/revision-1",
        plan_graph_digest="a" * 64,
        planner_decision_digest="b" * 64,
        policy_snapshot_digest="c" * 64,
        execution_records=[
            ToolExecutionRecord(
                record_id="record-1",
                revision_id="revision-1",
                tool_id="scene.observe",
                semantics="query",
                caller_id="paos:task-1",
                node_id="pick-red",
                node_digest="d" * 64,
                obligation_id="relocate-red",
                input_binding_digest="e" * 64,
                decision_trace_ref="artifact://trace/record-1",
            )
        ],
    )
    assert revision.plan_graph_digest == "a" * 64
    assert revision.execution_records[0].node_id == "pick-red"
    with pytest.raises(ValidationError, match="requires graph"):
        PlanRevision(
            revision_id="revision-1",
            number=1,
            reason="incomplete binding",
            plan_graph_digest="a" * 64,
        )
    with pytest.raises(ValidationError, match="require node_id"):
        ToolExecutionRecord(
            record_id="record-2",
            revision_id="revision-1",
            tool_id="scene.observe",
            semantics="query",
            caller_id="paos:task-1",
            node_digest="d" * 64,
            obligation_id="relocate-red",
        )
