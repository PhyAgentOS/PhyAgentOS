from __future__ import annotations

import json

from PhyAgentOS.agent.planning_dispatch import AgentComposedDispatch
from PhyAgentOS.agent.tools.base import Tool
from PhyAgentOS.agent.tools.planning import ForgePlanActivateTool
from PhyAgentOS.agent.tools.registry import ToolRegistry
from PhyAgentOS.planning import (
    AdmissionContext,
    PlanGraph,
    PlanNode,
    ToolSpecPolicy,
    plan_graph_digest,
    plan_node_digest,
)


def _graph() -> PlanGraph:
    payload = {
        "schema_version": "paos-plan-graph/v1",
        "task_id": "task-1",
        "revision_id": "revision-1",
        "graph_digest": "0" * 64,
        "planner_decision_digest": "1" * 64,
        "policy_snapshot_digest": "2" * 64,
        "nodes": [
            PlanNode(node_id="observe", obligation_id="observe", capability="scene.observe").model_dump(mode="json"),
            PlanNode(node_id="verify", obligation_id="verify", capability="task.verify", dependencies=("observe",)).model_dump(mode="json"),
        ],
    }
    payload["graph_digest"] = plan_graph_digest(payload)
    return PlanGraph.model_validate(payload)


def _dispatch() -> AgentComposedDispatch:
    policy = ToolSpecPolicy(
        tool_id="scene.observe",
        semantics="query",
        spec_digest="3" * 64,
        capabilities=("scene.observe",),
    )
    return AgentComposedDispatch(
        _graph(), (policy,), AdmissionContext(scene_revision="scene-1")
    )


def test_ready_tool_is_read_only_and_reports_candidates():
    data = _dispatch().describe()
    assert data["ready_nodes"][0]["candidate_tool_ids"] == ["scene.observe"]
    assert data["motion_authorized"] is False


def test_dispatch_refreshes_authoritative_context_before_each_read():
    contexts = [AdmissionContext(scene_revision="scene-1"), AdmissionContext(scene_revision="scene-2")]
    dispatch = AgentComposedDispatch(
        _graph(),
        (_dispatch().policies[0],),
        contexts[0],
        context_provider=lambda _task_id: contexts.pop(0),
    )
    assert dispatch.describe()["scene_revision"] == "scene-1"
    assert dispatch.describe()["scene_revision"] == "scene-2"


def test_guard_rejects_missing_binding_and_wrong_node():
    dispatch = _dispatch()
    missing = dispatch.admit_forge_tool(
        "forge_tool_query", {"task_id": "task-1", "tool_id": "scene.observe", "arguments": {}}
    )
    assert missing is not None and missing.code == "missing_planning_binding"
    wrong = dispatch.admit_forge_tool(
        "forge_tool_query",
        {
            "task_id": "task-1",
            "tool_id": "scene.observe",
            "arguments": {},
            "planning_binding": {
                "node_id": "verify",
                "input_binding_digest": "4" * 64,
            },
        },
    )
    assert wrong is not None and wrong.code == "invalid_planning_binding"


def test_guard_rejects_node_and_obligation_drift():
    dispatch = _dispatch()
    base = {
        "node_id": "observe",
        "node_digest": plan_node_digest(dispatch.graph.nodes[0]),
        "obligation_id": "observe",
        "input_binding_digest": "4" * 64,
        "decision_trace_ref": "artifact://trace/1",
    }
    drift = dict(base, node_digest="5" * 64)
    result = dispatch.admit_forge_tool(
        "forge_tool_query",
        {"task_id": "task-1", "tool_id": "scene.observe", "arguments": {}, "planning_binding": drift},
    )
    assert result is not None and result.code == "invalid_planning_binding"
    drift = dict(base, obligation_id="other")
    result = dispatch.admit_forge_tool(
        "forge_tool_query",
        {"task_id": "task-1", "tool_id": "scene.observe", "arguments": {}, "planning_binding": drift},
    )
    assert result is not None and result.code == "invalid_planning_binding"


def test_guard_admits_complete_binding_without_authorizing_motion():
    dispatch = _dispatch()
    binding = {
        "node_id": "observe",
        "node_digest": plan_node_digest(dispatch.graph.nodes[0]),
        "obligation_id": "observe",
        "input_binding_digest": "4" * 64,
        "decision_trace_ref": "artifact://trace/1",
    }
    result = dispatch.admit_forge_tool(
        "forge_tool_query",
        {"task_id": "task-1", "tool_id": "scene.observe", "arguments": {}, "planning_binding": binding},
    )
    assert result is not None and result.allowed is True
    assert result.motion_authorized is False


def test_activation_failure_clears_previous_dispatch():
    class _Coordinator:
        def get_task(self, task_id):
            raise RuntimeError("missing task")

    active = [_dispatch()]
    tool = ForgePlanActivateTool(
        _Coordinator(),
        lambda value: active.__setitem__(0, value),
        context_provider=None,
    )
    import asyncio

    result = json.loads(asyncio.run(tool.execute("task-1")))
    assert result["ok"] is False
    assert active[0] is None


class _Probe(Tool):
    @property
    def name(self):
        return "probe"

    @property
    def description(self):
        return "probe"

    @property
    def parameters(self):
        return {"type": "object", "properties": {}, "additionalProperties": False}

    async def execute(self):
        return "executed"


def test_registry_guard_runs_before_tool_execution():
    registry = ToolRegistry()
    registry.register(_Probe())
    registry.set_execution_guard(lambda name, params: json.dumps({"ok": False, "code": "blocked"}))
    assert json.loads(__import__("asyncio").run(registry.execute("probe", {}))) == {"ok": False, "code": "blocked"}
