import json
from dataclasses import replace

import pytest

from pick_place_workflow.long_horizon import (
    WORKFLOW_DAG,
    WORKFLOW_ID,
    WORKFLOW_VERSION,
    LongHorizonWorkflow,
    WorkflowBindingError,
    WorkflowDag,
    WorkflowNodeSpec,
    WorkflowState,
    WorkflowTransitionError,
)

OBS = "observation://scene-7/camera_front"
CSET = "candidate-set://scene-7/camera_front"
PREP = "preparation://scene-7/camera_front"
CAP = "artifact://capabilities/scene-7/snapshot"
ASSIGN = "artifact://assignments/task-1/revision-1/acquire"


def test_start_exposes_only_declared_next_tool_and_immutable_steps():
    workflow = LongHorizonWorkflow.start("task-1", "revision-1")
    snapshot = workflow.snapshot()
    assert snapshot["workflow_id"] == WORKFLOW_ID
    assert snapshot["version"] == WORKFLOW_VERSION
    assert snapshot["status"] == "ready"
    assert snapshot["active_step"] == "observe"
    assert workflow.next_tool() == "scene.observe"
    assert [node.node_id for node in workflow.ready_nodes()] == ["observe"]
    assert [step["tool_id"] for step in snapshot["steps"]] == [
        "scene.observe",
        "scene.understand",
        "grasp.propose",
        "manipulation.prepare",
        "object.acquire",
        "object.place",
    ]
    assert "coordinates" not in json.dumps(snapshot).lower()
    assert "robotwin" not in json.dumps(snapshot).lower()
    assert snapshot["dag_digest"] == WORKFLOW_DAG.dag_digest


def test_skill_dag_projects_dependencies_without_execution():
    assert [node.node_id for node in WORKFLOW_DAG.ready_nodes(set())] == ["observe"]
    assert [node.node_id for node in WORKFLOW_DAG.ready_nodes({"observe"})] == ["understand"]
    assert WORKFLOW_DAG.nodes[-1].depends_on == ("acquire",)
    assert not hasattr(WORKFLOW_DAG, "execute")
    assert not hasattr(WORKFLOW_DAG, "begin_revision")
    assert WORKFLOW_DAG.nodes[4].resource_requirement.mode.value == "alternative_resource"
    assert WORKFLOW_DAG.nodes[4].resource_requirement.substitution_allowed is True


def test_dag_schema_projects_parallel_ready_nodes_and_waits_for_join():
    dag = WorkflowDag(
        WORKFLOW_DAG.version,
        WORKFLOW_DAG.workflow_id,
        (
            WorkflowNodeSpec("root", "scene.observe", "query"),
            WorkflowNodeSpec("left", "scene.understand", "query", ("root",)),
            WorkflowNodeSpec("right", "grasp.propose", "query", ("root",)),
            WorkflowNodeSpec("join", "manipulation.prepare", "query", ("left", "right")),
        ),
    )

    assert [node.node_id for node in dag.ready_nodes(set())] == ["root"]
    assert [node.node_id for node in dag.ready_nodes({"root"})] == ["left", "right"]
    assert [node.node_id for node in dag.ready_nodes({"root", "right"})] == ["left"]
    assert [node.node_id for node in dag.ready_nodes({"root", "left", "right"})] == ["join"]


def test_dag_and_state_binding_validation_fail_closed():
    with pytest.raises(WorkflowBindingError, match="required bindings"):
        WorkflowNodeSpec("unsafe", "scene.observe", "query", required_bindings=("pose",))
    with pytest.raises(WorkflowBindingError, match="dependencies"):
        WorkflowNodeSpec("unsafe", "scene.observe", "query", depends_on=("observe", "observe"))
    with pytest.raises(WorkflowBindingError, match="immutable node tuple"):
        WorkflowDag(WORKFLOW_DAG.version, WORKFLOW_DAG.workflow_id, list(WORKFLOW_DAG.nodes))
    with pytest.raises(WorkflowBindingError, match="string set"):
        WORKFLOW_DAG.ready_nodes(["observe"])
    with pytest.raises(WorkflowBindingError, match="dependency is invalid"):
        WorkflowDag(
            WORKFLOW_DAG.version,
            WORKFLOW_DAG.workflow_id,
            (WorkflowNodeSpec("orphan", "scene.observe", "query", ("missing",)),),
        )
    with pytest.raises(WorkflowBindingError, match="acyclic"):
        WorkflowDag(
            WORKFLOW_DAG.version,
            WORKFLOW_DAG.workflow_id,
            (
                WorkflowNodeSpec("left", "scene.observe", "query", ("right",)),
                WorkflowNodeSpec("right", "scene.understand", "query", ("left",)),
            ),
        )

    workflow = LongHorizonWorkflow.start("task-1", "revision-1")
    stale = replace(workflow.state, dag_digest="0" * 64)
    with pytest.raises(WorkflowBindingError, match="DAG binding"):
        LongHorizonWorkflow(stale)
    impossible = WorkflowState(
        **{
            **workflow.state.__dict__,
            "status": "running",
            "active_step": "understand",
        }
    )
    with pytest.raises(WorkflowBindingError, match="DAG readiness"):
        LongHorizonWorkflow(impossible)

    with pytest.raises(WorkflowBindingError, match="task_id"):
        LongHorizonWorkflow(replace(workflow.state, task_id="../unsafe"))
    with pytest.raises(WorkflowBindingError, match="immutable WorkflowSteps"):
        LongHorizonWorkflow(replace(workflow.state, steps=list(workflow.state.steps)))


def test_restored_blocked_state_requires_ready_failure_and_matching_reason():
    workflow = LongHorizonWorkflow.start("task-1", "revision-1")
    blocked = workflow.record("observe", "unavailable")

    with pytest.raises(WorkflowBindingError, match="blocked workflow state"):
        LongHorizonWorkflow(replace(blocked, block_reason="failed"))

    impossible_steps = list(workflow.start("task-1", "revision-1").state.steps)
    impossible_steps[-1] = replace(impossible_steps[-1], status="failed")
    impossible = replace(
        workflow.start("task-1", "revision-1").state,
        status="blocked",
        active_step="place",
        steps=tuple(impossible_steps),
        block_reason="failed",
    )
    with pytest.raises(WorkflowBindingError, match="blocked workflow state"):
        LongHorizonWorkflow(impossible)

    with pytest.raises(WorkflowBindingError, match="block reason"):
        LongHorizonWorkflow(
            replace(
                workflow.start("task-1", "revision-1").state,
                block_reason="stale",
            )
        )


def test_recorded_references_and_dag_nodes_are_immutable():
    source = {"observation_ref": OBS}
    workflow = LongHorizonWorkflow.start("task-1", "revision-1")
    state = workflow.record("observe", "available", source)
    source["observation_ref"] = "observation://scene-8/camera_front"

    assert state.steps[0].references["observation_ref"] == OBS
    with pytest.raises(TypeError):
        state.steps[0].references["observation_ref"] = source["observation_ref"]
    with pytest.raises(TypeError):
        WORKFLOW_DAG.nodes[0] = WORKFLOW_DAG.nodes[1]


def test_complete_chain_requires_terminal_success_and_preserves_references():
    workflow = LongHorizonWorkflow.start("task-1", "revision-1")
    workflow.record("observe", "available", {"observation_ref": OBS})
    workflow.record("understand", "available", {"observation_ref": OBS})
    workflow.record("propose", "available", {"observation_ref": OBS, "candidate_set_ref": CSET})
    workflow.record(
        "prepare",
        "available",
        {"observation_ref": OBS, "candidate_set_ref": CSET, "preparation_ref": PREP},
    )
    workflow.record(
        "acquire",
        "succeeded",
        {
            "observation_ref": OBS,
            "candidate_set_ref": CSET,
            "preparation_ref": PREP,
            "capability_snapshot_ref": CAP,
            "assignment_ref": ASSIGN,
            "invocation_ref": "invocation://object-acquire/a1",
        },
    )
    state = workflow.record(
        "place",
        "succeeded",
        {
            "observation_ref": OBS,
            "candidate_set_ref": CSET,
            "preparation_ref": PREP,
            "capability_snapshot_ref": CAP,
            "assignment_ref": ASSIGN,
            "acquire_invocation_ref": "invocation://object-acquire/a1",
            "invocation_ref": "invocation://object-place/p1",
            "destination_ref": "destination://bin/primary",
            "post_release_evidence_ref": "artifact://place-7/post-release",
        },
    )
    assert state.status == "succeeded"
    assert state.active_step is None
    assert workflow.next_tool() is None
    assert state.steps[4].references["invocation_ref"] == "invocation://object-acquire/a1"


def test_skip_and_invalid_status_fail_closed():
    workflow = LongHorizonWorkflow.start("task-1", "revision-1")
    with pytest.raises(WorkflowTransitionError):
        workflow.record("understand", "available", {"observation_ref": OBS})
    with pytest.raises(WorkflowTransitionError):
        workflow.record("observe", "running", {"observation_ref": OBS})


@pytest.mark.parametrize("status", ["failed", "cancelled", "unknown", "empty", "stale"])
def test_non_success_stops_progression_and_requires_recovery(status):
    workflow = LongHorizonWorkflow.start("task-1", "revision-1")
    state = workflow.record("observe", status, {})
    assert state.status == "blocked"
    assert state.active_step == "observe"
    with pytest.raises(WorkflowTransitionError):
        workflow.record("observe", "available", {"observation_ref": OBS})
    recovered = workflow.begin_recovery("revision-2")
    assert recovered.state.revision_id == "revision-2"
    assert recovered.state.active_step == "observe"
    assert recovered.state.steps[0].status == "pending"


def test_cross_scene_or_cross_stage_reference_drift_is_rejected():
    workflow = LongHorizonWorkflow.start("task-1", "revision-1")
    workflow.record("observe", "available", {"observation_ref": OBS})
    with pytest.raises(WorkflowBindingError):
        workflow.record("understand", "available", {"observation_ref": "observation://scene-8/camera_front"})
    workflow.record("understand", "available", {"observation_ref": OBS})
    with pytest.raises(WorkflowBindingError):
        workflow.record("propose", "available", {"observation_ref": OBS, "candidate_set_ref": "candidate-set://scene-8/camera_front"})


def test_prepare_acquire_and_place_require_their_bound_references():
    workflow = LongHorizonWorkflow.start("task-1", "revision-1")
    workflow.record("observe", "available", {"observation_ref": OBS})
    workflow.record("understand", "available", {"observation_ref": OBS})
    with pytest.raises(WorkflowBindingError):
        workflow.record("propose", "available", {"observation_ref": OBS})
    workflow.record("propose", "available", {"observation_ref": OBS, "candidate_set_ref": CSET})
    with pytest.raises(WorkflowBindingError):
        workflow.record("prepare", "available", {"observation_ref": OBS, "candidate_set_ref": CSET})
    workflow.record("prepare", "available", {"observation_ref": OBS, "candidate_set_ref": CSET, "preparation_ref": PREP})
    with pytest.raises(WorkflowBindingError):
        workflow.record("acquire", "succeeded", {"observation_ref": OBS, "candidate_set_ref": CSET, "preparation_ref": PREP})


def test_action_steps_require_capability_snapshot_and_assignment_bindings():
    workflow = LongHorizonWorkflow.start("task-1", "revision-1")
    workflow.record("observe", "available", {"observation_ref": OBS})
    workflow.record("understand", "available", {"observation_ref": OBS})
    workflow.record("propose", "available", {"observation_ref": OBS, "candidate_set_ref": CSET})
    workflow.record("prepare", "available", {"observation_ref": OBS, "candidate_set_ref": CSET, "preparation_ref": PREP})
    with pytest.raises(WorkflowBindingError, match="capability_snapshot_ref"):
        workflow.record("acquire", "succeeded", {
            "observation_ref": OBS, "candidate_set_ref": CSET, "preparation_ref": PREP,
            "assignment_ref": ASSIGN, "invocation_ref": "invocation://object-acquire/a1",
        })
    with pytest.raises(WorkflowBindingError, match="assignment_ref"):
        workflow.record("acquire", "succeeded", {
            "observation_ref": OBS, "candidate_set_ref": CSET, "preparation_ref": PREP,
            "capability_snapshot_ref": CAP, "invocation_ref": "invocation://object-acquire/a1",
        })


def test_place_requires_the_same_acquire_and_post_release_evidence():
    workflow = LongHorizonWorkflow.start("task-1", "revision-1")
    workflow.record("observe", "available", {"observation_ref": OBS})
    workflow.record("understand", "available", {"observation_ref": OBS})
    workflow.record("propose", "available", {"observation_ref": OBS, "candidate_set_ref": CSET})
    workflow.record("prepare", "available", {"observation_ref": OBS, "candidate_set_ref": CSET, "preparation_ref": PREP})
    workflow.record("acquire", "succeeded", {"observation_ref": OBS, "candidate_set_ref": CSET, "preparation_ref": PREP, "capability_snapshot_ref": CAP, "assignment_ref": ASSIGN, "invocation_ref": "invocation://object-acquire/a1"})
    with pytest.raises(WorkflowBindingError, match="differs from acquire"):
        workflow.record("place", "succeeded", {"observation_ref": OBS, "candidate_set_ref": CSET, "preparation_ref": PREP, "capability_snapshot_ref": CAP, "assignment_ref": ASSIGN, "acquire_invocation_ref": "invocation://object-acquire/a2", "invocation_ref": "invocation://object-place/p1", "destination_ref": "destination://bin/primary", "post_release_evidence_ref": "artifact://place-7/post-release"})
    with pytest.raises(WorkflowBindingError, match="post_release_evidence_ref"):
        workflow.record("place", "succeeded", {"observation_ref": OBS, "candidate_set_ref": CSET, "preparation_ref": PREP, "capability_snapshot_ref": CAP, "assignment_ref": ASSIGN, "acquire_invocation_ref": "invocation://object-acquire/a1", "invocation_ref": "invocation://object-place/p1", "destination_ref": "destination://bin/primary"})


def test_terminal_response_adapter_preserves_place_evidence_and_identity():
    workflow = LongHorizonWorkflow.start("task-1", "revision-1")
    workflow.record_terminal_response("observe", {"status": "available", "result": {"observation_ref": OBS}})
    workflow.record_terminal_response("understand", {"status": "available", "result": {"observation_ref": OBS}})
    workflow.record_terminal_response("propose", {"status": "available", "result": {"observation_ref": OBS, "candidate_set_ref": CSET}})
    workflow.record_terminal_response("prepare", {"status": "available", "result": {"observation_ref": OBS, "candidate_set_ref": CSET, "preparation_ref": PREP}})
    workflow.record_terminal_response("acquire", {"status": "succeeded", "invocation_id": "invocation://object-acquire/a1", "result": {"observation_ref": OBS, "candidate_set_ref": CSET, "preparation_ref": PREP, "capability_snapshot_ref": CAP, "assignment_ref": ASSIGN}})
    state = workflow.record_terminal_response("place", {"status": "succeeded", "invocation_id": "invocation://object-place/p1", "result": {"observation_ref": OBS, "candidate_set_ref": CSET, "preparation_ref": PREP, "capability_snapshot_ref": CAP, "assignment_ref": ASSIGN, "acquire_invocation_ref": "invocation://object-acquire/a1", "destination_ref": "destination://bin/primary", "capability_outcome_summary": {"post_release_evidence": {"availability": "complete", "artifact_refs": ["artifact://place-7/post-release"]}}}})
    assert state.status == "succeeded"
    assert state.steps[-1].references["post_release_evidence_ref"] == "artifact://place-7/post-release"


def test_recovery_is_append_only_and_terminal_workflow_cannot_be_rewritten():
    workflow = LongHorizonWorkflow.start("task-1", "revision-1")
    workflow.record("observe", "available", {"observation_ref": OBS})
    workflow.record("understand", "failed", {"observation_ref": OBS})
    recovered = workflow.begin_recovery("revision-2")
    assert workflow.state.steps[0].status == "available"
    assert workflow.state.steps[1].status == "blocked" or workflow.state.steps[1].status == "failed"
    assert recovered.state.steps[0].status == "available"
    assert recovered.state.active_step == "understand"
    with pytest.raises(WorkflowTransitionError):
        recovered.begin_recovery("revision-3")
