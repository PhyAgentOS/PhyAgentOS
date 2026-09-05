from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json

from PhyAgentOS.agent.experience.policy_candidates import WorkflowPolicyCandidateManager
from PhyAgentOS.agent.experience.store import ExperienceStore
from PhyAgentOS.agent.planning_dispatch import AgentComposedDispatch
from PhyAgentOS.agent.tools.planning import ForgePlanActivateTool
from PhyAgentOS.config.schema import ForgeConfig
from PhyAgentOS.forge.binding import BoundToolSpec, ForgeSkillBinding
from PhyAgentOS.forge.task import AgentTaskCoordinator, AgentTaskStatus
from PhyAgentOS.planning import (
    AdmissionContext,
    PlanGraph,
    PlanNode,
    ToolResultEnvelope,
    ToolSpecPolicy,
    WorkflowPolicyCandidate,
    WorkflowPolicyReplayReceipt,
    build_replan_delta,
    plan_graph_digest,
    plan_node_digest,
    settle_node,
)
from PhyAgentOS.verification.contracts import TaskVerificationContract


class _NoopGateway:
    """The integration test must prove planning without a transport provider."""


def _graph(revision_id: str = "revision-1") -> PlanGraph:
    nodes = (
        PlanNode(
            node_id="observe",
            obligation_id="observe",
            capability="scene.observe",
            produced_evidence=("observation:red",),
        ),
        PlanNode(
            node_id="understand",
            obligation_id="relocate-red",
            capability="scene.understand",
            dependencies=("observe",),
            required_evidence=("observation:red",),
            produced_evidence=("understood:red",),
        ),
        PlanNode(
            node_id="acquire",
            obligation_id="relocate-red",
            capability="object.acquire",
            dependencies=("understand",),
            required_evidence=("understood:red",),
            produced_evidence=("acquired:red",),
        ),
        PlanNode(
            node_id="verify",
            obligation_id="verify-task",
            capability="task.verify",
            dependencies=("acquire",),
            required_evidence=("acquired:red",),
        ),
    )
    payload = {
        "schema_version": "paos-plan-graph/v1",
        "task_id": "task-e2e",
        "revision_id": revision_id,
        "graph_digest": "0" * 64,
        "planner_decision_digest": "1" * 64,
        "policy_snapshot_digest": "2" * 64,
        "nodes": [node.model_dump(mode="json") for node in nodes],
    }
    payload["graph_digest"] = plan_graph_digest(payload)
    return PlanGraph.model_validate(payload)


def _policies() -> tuple[ToolSpecPolicy, ...]:
    return (
        ToolSpecPolicy(
            tool_id="scene.observe",
            semantics="query",
            spec_digest="3" * 64,
            capabilities=("scene.observe",),
            produced_evidence=("observation:red",),
        ),
        ToolSpecPolicy(
            tool_id="scene.understand",
            semantics="query",
            spec_digest="4" * 64,
            capabilities=("scene.understand",),
            required_evidence=("observation:red",),
            produced_evidence=("understood:red",),
        ),
        ToolSpecPolicy(
            tool_id="object.acquire",
            semantics="action",
            spec_digest="5" * 64,
            capabilities=("object.acquire",),
            required_evidence=("understood:red",),
        ),
    )


def _binding(policies: tuple[ToolSpecPolicy, ...]) -> ForgeSkillBinding:
    return ForgeSkillBinding(
        binding_id="binding-e2e",
        skill_name="pick-place-workflow",
        skill_version="0.10.0",
        manifest_sha256="a" * 64,
        skill_document_sha256="b" * 64,
        runtime_profile="test-no-motion",
        runtime_instance_id="runtime-e2e",
        gateway_url="http://gateway.invalid",
        required_tools=tuple(
            BoundToolSpec(
                tool_id=policy.tool_id,
                semantics=policy.semantics,
                spec_sha256=policy.spec_digest,
                ready_at_binding=True,
                planning_policy=policy,
            )
            for policy in policies
        ),
    )


def test_agent_composed_plan_is_effectively_wired_without_motion(tmp_path):
    graph = _graph()
    policies = _policies()
    coordinator = AgentTaskCoordinator(
        workspace=tmp_path,
        config=ForgeConfig(),
        client=_NoopGateway(),
    )
    task = coordinator.create_task(
        task_description="relocate red block",
        verification=TaskVerificationContract(mode="off"),
        plan_graph=graph,
        plan_graph_ref="artifact://plans/task-e2e/revision-1",
    )
    binding = _binding(policies)
    coordinator.store.update(
        task.task_id,
        lambda current: setattr(current, "primary_skill_binding", binding),
        event_type="test_binding_attached",
    )

    context = {"value": AdmissionContext(scene_revision="scene-1")}
    active: list[AgentComposedDispatch | None] = [None]
    activate = ForgePlanActivateTool(
        coordinator,
        lambda value: active.__setitem__(0, value),
        lambda _task_id: context["value"],
    )
    activation_result = json.loads(asyncio.run(activate.execute(task.task_id)))
    assert activation_result["ok"] is True
    dispatch = active[0]
    assert dispatch is not None
    assert [node["node_id"] for node in activation_result["ready_nodes"]] == ["observe"]
    assert activation_result["motion_authorized"] is False

    def binding_for(node_id: str, index: int) -> dict[str, str]:
        node = next(item for item in graph.nodes if item.node_id == node_id)
        return {
            "node_id": node_id,
            "node_digest": plan_node_digest(node),
            "obligation_id": node.obligation_id,
            "input_binding_digest": f"{index:x}" * 64,
            "decision_trace_ref": f"artifact://traces/task-e2e/{node_id}",
        }

    observe = dispatch.admit_forge_tool(
        "forge_tool_query",
        {
            "task_id": task.task_id,
            "tool_id": "scene.observe",
            "arguments": {"sensor_ref": "camera/front"},
            "planning_binding": binding_for("observe", 6),
        },
    )
    assert observe is not None and observe.allowed and observe.motion_authorized is False

    context["value"] = AdmissionContext(
        scene_revision="scene-1",
        evidence_refs={"observation:red"},
        settlements={"observe": "completed"},
    )
    ready_after_observe = dispatch.describe()
    assert [node["node_id"] for node in ready_after_observe["ready_nodes"]] == ["understand"]
    understand = dispatch.admit_forge_tool(
        "forge_tool_query",
        {
            "task_id": task.task_id,
            "tool_id": "scene.understand",
            "arguments": {},
            "planning_binding": binding_for("understand", 7),
        },
    )
    assert understand is not None and understand.allowed

    context["value"] = AdmissionContext(
        scene_revision="scene-1",
        evidence_refs={"observation:red", "understood:red"},
        settlements={"observe": "completed", "understand": "completed"},
    )
    acquire = dispatch.admit_forge_tool(
        "forge_tool_start_action",
        {
            "task_id": task.task_id,
            "tool_id": "object.acquire",
            "arguments": {"assignment_ref": "assignment://right/red"},
            "planning_binding": binding_for("acquire", 8),
        },
    )
    assert acquire is not None and acquire.allowed and acquire.motion_authorized is False
    assert dispatch.describe()["ready_nodes"] == [{
        "node_id": "acquire",
        "obligation_id": "relocate-red",
        "capability": "object.acquire",
        "candidate_tool_ids": ["object.acquire"],
    }]

    failed = settle_node(
        graph.nodes[2],
        ToolResultEnvelope(
            task_id=graph.task_id,
            revision_id=graph.revision_id,
            node_id="acquire",
            tool_id="object.acquire",
            status="failed",
            failure_code="readiness_unavailable",
        ),
        current_scene_revision="scene-1",
    )
    delta = build_replan_delta(graph, failed, fresh_evidence_requirements=("understood:red",))
    assert delta.retry_parent_node_id == "acquire"
    assert delta.invalidate_node_ids == ("verify",)
    coordinator.store.update(
        task.task_id,
        lambda current: setattr(current, "status", AgentTaskStatus.AWAITING_REPLAN),
        event_type="test_awaiting_replan",
    )
    revised = coordinator.begin_revision_from_delta(
        task.task_id,
        delta,
        plan_graph=_graph("revision-2"),
        plan_graph_ref="artifact://plans/task-e2e/revision-2",
    )
    assert revised.active_revision_id == "revision-2"
    assert revised.active_revision.plan_graph is not None

    manager = WorkflowPolicyCandidateManager(
        ExperienceStore(tmp_path / "experience"),
        min_support_episodes=2,
        promotion_callback=lambda _candidate: "artifact://skills/pick-place/v2",
    )
    candidate = WorkflowPolicyCandidate(
        candidate_id="candidate-e2e",
        base_policy_digest="1" * 64,
        proposed_policy_digest="2" * 64,
        source_episode_ids=("episode-1", "episode-2"),
        change_summary="retry acquisition after readiness failure",
    )
    manager.submit(candidate)
    for episode_id, replay_id in (("episode-1", "replay-1"), ("episode-2", "replay-2")):
        manager.record_replay(
            WorkflowPolicyReplayReceipt(
                replay_id=replay_id,
                candidate_id=candidate.candidate_id,
                base_policy_digest=candidate.base_policy_digest,
                proposed_policy_digest=candidate.proposed_policy_digest,
                source_episode_id=episode_id,
                receipt_ref=f"artifact://replay/{replay_id}",
                verdict="pass",
                independent=True,
                runner_id="independent-runner",
                created_at=datetime.now(timezone.utc),
            )
        )
    approved = manager.review(candidate.candidate_id, approved=True, reviewer_id="reviewer-e2e")
    promoted = manager.promote(approved.candidate_id)
    assert promoted.status == "promoted"
    assert promoted.promotion_ref == "artifact://skills/pick-place/v2"
