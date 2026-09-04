import json

import pytest

from pick_place_workflow.long_horizon import (
    WORKFLOW_ID,
    WORKFLOW_VERSION,
    LongHorizonWorkflow,
    WorkflowBindingError,
    WorkflowTransitionError,
)

OBS = "observation://scene-7/camera_front"
CSET = "candidate-set://scene-7/camera_front"
PREP = "preparation://scene-7/camera_front"


def test_start_exposes_only_declared_next_tool_and_immutable_steps():
    workflow = LongHorizonWorkflow.start("task-1", "revision-1")
    snapshot = workflow.snapshot()
    assert snapshot["workflow_id"] == WORKFLOW_ID
    assert snapshot["version"] == WORKFLOW_VERSION
    assert snapshot["status"] == "ready"
    assert snapshot["active_step"] == "observe"
    assert workflow.next_tool() == "scene.observe"
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


def test_place_requires_the_same_acquire_and_post_release_evidence():
    workflow = LongHorizonWorkflow.start("task-1", "revision-1")
    workflow.record("observe", "available", {"observation_ref": OBS})
    workflow.record("understand", "available", {"observation_ref": OBS})
    workflow.record("propose", "available", {"observation_ref": OBS, "candidate_set_ref": CSET})
    workflow.record("prepare", "available", {"observation_ref": OBS, "candidate_set_ref": CSET, "preparation_ref": PREP})
    workflow.record("acquire", "succeeded", {"observation_ref": OBS, "candidate_set_ref": CSET, "preparation_ref": PREP, "invocation_ref": "invocation://object-acquire/a1"})
    with pytest.raises(WorkflowBindingError, match="differs from acquire"):
        workflow.record("place", "succeeded", {"observation_ref": OBS, "candidate_set_ref": CSET, "preparation_ref": PREP, "acquire_invocation_ref": "invocation://object-acquire/a2", "invocation_ref": "invocation://object-place/p1", "destination_ref": "destination://bin/primary", "post_release_evidence_ref": "artifact://place-7/post-release"})
    with pytest.raises(WorkflowBindingError, match="post_release_evidence_ref"):
        workflow.record("place", "succeeded", {"observation_ref": OBS, "candidate_set_ref": CSET, "preparation_ref": PREP, "acquire_invocation_ref": "invocation://object-acquire/a1", "invocation_ref": "invocation://object-place/p1", "destination_ref": "destination://bin/primary"})


def test_terminal_response_adapter_preserves_place_evidence_and_identity():
    workflow = LongHorizonWorkflow.start("task-1", "revision-1")
    workflow.record_terminal_response("observe", {"status": "available", "result": {"observation_ref": OBS}})
    workflow.record_terminal_response("understand", {"status": "available", "result": {"observation_ref": OBS}})
    workflow.record_terminal_response("propose", {"status": "available", "result": {"observation_ref": OBS, "candidate_set_ref": CSET}})
    workflow.record_terminal_response("prepare", {"status": "available", "result": {"observation_ref": OBS, "candidate_set_ref": CSET, "preparation_ref": PREP}})
    workflow.record_terminal_response("acquire", {"status": "succeeded", "invocation_id": "invocation://object-acquire/a1", "result": {"observation_ref": OBS, "candidate_set_ref": CSET, "preparation_ref": PREP}})
    state = workflow.record_terminal_response("place", {"status": "succeeded", "invocation_id": "invocation://object-place/p1", "result": {"observation_ref": OBS, "candidate_set_ref": CSET, "preparation_ref": PREP, "acquire_invocation_ref": "invocation://object-acquire/a1", "destination_ref": "destination://bin/primary", "capability_outcome_summary": {"post_release_evidence": {"availability": "complete", "artifact_refs": ["artifact://place-7/post-release"]}}}})
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
