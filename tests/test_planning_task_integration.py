from __future__ import annotations

import asyncio
import json

import pytest

from PhyAgentOS.agent.experience.source import AgentTaskOutcomeSource
from PhyAgentOS.agent.tools.forge_tool_api import ForgeToolQueryTool
from PhyAgentOS.config.schema import ForgeConfig
from PhyAgentOS.forge.binding import BoundToolSpec
from PhyAgentOS.forge.task import AgentTaskCoordinator, AgentTaskStatus
from PhyAgentOS.planning import (
    PlanGraph,
    PlanningExecutionBinding,
    PlanNode,
    ToolResultEnvelope,
    build_replan_delta,
    plan_graph_digest,
    plan_node_digest,
    settle_node,
)
from PhyAgentOS.verification.contracts import TaskVerificationContract


class _Client:
    pass


def _graph(task_id: str, revision_id: str) -> PlanGraph:
    node = PlanNode(
        node_id="relocate-red",
        obligation_id="relocate-red",
        capability="object.relocate",
        required_evidence=("observation:red",),
    )
    payload = {
        "schema_version": "paos-plan-graph/v1",
        "task_id": task_id,
        "revision_id": revision_id,
        "graph_digest": "0" * 64,
        "planner_decision_digest": "1" * 64,
        "policy_snapshot_digest": "2" * 64,
        "nodes": [node.model_dump(mode="json")],
    }
    payload["graph_digest"] = plan_graph_digest(payload)
    return PlanGraph.model_validate(payload)


def test_coordinator_persists_concrete_graph_and_complete_execution_attribution(tmp_path):
    graph = _graph("task-1", "revision-1")
    coordinator = AgentTaskCoordinator(
        workspace=tmp_path, config=ForgeConfig(), client=_Client()
    )
    task = coordinator.create_task(
        task_description="relocate red",
        verification=TaskVerificationContract(mode="off"),
        plan_graph=graph,
        plan_graph_ref="artifact://plans/task-1/revision-1",
    )
    assert task.task_id == graph.task_id
    assert task.active_revision.plan_graph_digest == graph.graph_digest

    binding = PlanningExecutionBinding(
        node_id="relocate-red",
        node_digest=plan_node_digest(graph.nodes[0]),
        obligation_id="relocate-red",
        input_binding_digest="3" * 64,
        decision_trace_ref="artifact://traces/task-1/record-1",
    )
    record_id, _caller = coordinator._append_execution(
        task.task_id,
        "scene.observe",
        "query",
        {"sensor_ref": "camera/front"},
        tool=BoundToolSpec(
            tool_id="scene.observe",
            semantics="query",
            spec_sha256="4" * 64,
            ready_at_binding=True,
        ),
        planning_binding=binding,
    )
    record = coordinator.get_task(task.task_id).execution_records[0]
    assert record.record_id == record_id
    assert record.node_id == binding.node_id
    assert record.node_digest == binding.node_digest
    assert record.obligation_id == binding.obligation_id
    assert record.input_binding_digest == binding.input_binding_digest
    assert record.decision_trace_ref == binding.decision_trace_ref

    coordinator._finish_execution(
        task.task_id, record_id, status="succeeded", response={"status": "succeeded"}
    )
    coordinator.store.update(
        task.task_id,
        lambda current: setattr(current, "status", AgentTaskStatus.SUCCEEDED),
        event_type="test_completed",
    )
    outcome = AgentTaskOutcomeSource(coordinator).build(task.task_id)
    assert len(outcome.decision_trace_refs) == 1
    assert outcome.decision_trace_refs[0].startswith("evidence:")


def test_partial_planning_binding_and_unbound_graph_ref_fail_closed(tmp_path):
    coordinator = AgentTaskCoordinator(
        workspace=tmp_path, config=ForgeConfig(), client=_Client()
    )
    try:
        coordinator.create_task(
            task_description="invalid",
            verification=TaskVerificationContract(mode="off"),
            plan_graph_ref="artifact://plans/only-ref",
        )
    except Exception as exc:
        assert "requires a concrete PlanGraph" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("graph ref without graph must be rejected")

    task = coordinator.create_task(
        task_description="legacy",
        verification=TaskVerificationContract(mode="off"),
    )
    try:
        coordinator._append_execution(
            task.task_id,
            "scene.observe",
            "query",
            {},
            tool=BoundToolSpec(
                tool_id="scene.observe",
                semantics="query",
                spec_sha256="4" * 64,
                ready_at_binding=True,
            ),
            planning_binding={"node_id": "partial"},
        )
    except Exception as exc:
        assert "invalid planning execution binding" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("partial planning binding must be rejected")


@pytest.mark.parametrize("semantics", ["query", "action", "session"])
def test_complete_planning_binding_is_shared_by_all_tool_semantics(tmp_path, semantics):
    graph = _graph("task-1", "revision-1")
    coordinator = AgentTaskCoordinator(
        workspace=tmp_path, config=ForgeConfig(), client=_Client()
    )
    task = coordinator.create_task(
        task_description="attribute tool",
        verification=TaskVerificationContract(mode="off"),
        plan_graph=graph,
        plan_graph_ref="artifact://plans/task-1/revision-1",
    )
    binding = {
        "node_id": "relocate-red",
        "node_digest": plan_node_digest(graph.nodes[0]),
        "obligation_id": "relocate-red",
        "input_binding_digest": "3" * 64,
        "decision_trace_ref": "artifact://traces/task-1/record-1",
    }
    coordinator._append_execution(
        task.task_id,
        f"tool.{semantics}",
        semantics,
        {},
        tool=BoundToolSpec(
            tool_id=f"tool.{semantics}",
            semantics=semantics,
            spec_sha256="4" * 64,
            ready_at_binding=True,
        ),
        planning_binding=binding,
    )
    record = coordinator.get_task(task.task_id).execution_records[0]
    assert record.semantics == semantics
    assert record.decision_trace_ref == binding["decision_trace_ref"]


def test_replan_delta_adapter_creates_new_coordinator_revision(tmp_path):
    graph = _graph("task-1", "revision-1")
    coordinator = AgentTaskCoordinator(
        workspace=tmp_path, config=ForgeConfig(), client=_Client(), max_replans=2
    )
    task = coordinator.create_task(
        task_description="relocate red",
        verification=TaskVerificationContract(mode="off"),
        plan_graph=graph,
        plan_graph_ref="artifact://plans/task-1/revision-1",
    )
    settlement = settle_node(
        graph.nodes[0],
        ToolResultEnvelope(
            task_id=task.task_id,
            revision_id=task.active_revision_id,
            node_id="relocate-red",
            tool_id="scene.observe",
            status="failed",
            failure_code="no_candidate",
        ),
        current_scene_revision="scene-1",
    )
    delta = build_replan_delta(graph, settlement, fresh_evidence_requirements=("observation:red",))
    coordinator.store.update(
        task.task_id,
        lambda current: setattr(current, "status", AgentTaskStatus.AWAITING_REPLAN),
        event_type="test_awaiting_replan",
    )
    replacement = _graph(task.task_id, "revision-2")
    revised = coordinator.begin_revision_from_delta(
        task.task_id,
        delta,
        plan_graph=replacement,
        plan_graph_ref="artifact://plans/task-1/revision-2",
    )
    assert revised.active_revision_id == "revision-2"
    assert revised.active_revision.plan_graph_digest == replacement.graph_digest


def test_query_tool_does_not_drop_planning_binding_in_unbound_diagnostic_mode(tmp_path):
    coordinator = AgentTaskCoordinator(
        workspace=tmp_path, config=ForgeConfig(), client=_Client()
    )
    result = json.loads(
        asyncio.run(
            ForgeToolQueryTool(_Client(), coordinator).execute(
                "scene.observe", {}, planning_binding={"node_id": "n"}
            )
        )
    )
    assert result["ok"] is False
    assert result["error"]["message"] == "planning_binding requires task_id"
