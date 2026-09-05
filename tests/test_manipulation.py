from __future__ import annotations

import pytest
from pydantic import ValidationError

from PhyAgentOS.forge.manipulation import (
    CoordinationMode,
    ManipulationIntent,
    ReplanCoordinator,
    RouteFailure,
)


def _intent() -> ManipulationIntent:
    return ManipulationIntent(
        task_id="task-1",
        revision_id="revision-2",
        node_id="prepare-red",
        node_digest="a" * 64,
        entity_ref="entity://red-block",
        goal="prepare red block for placement",
        success_criteria=("red block has one fully qualified route",),
        allowed_arms=("left", "right"),
        coordination_mode=CoordinationMode.ALTERNATIVE_ARM,
        observation_ref="observation://scene-7/head-camera",
        scene_revision="scene-7",
        observation_frame_id="head-camera",
        calibration_ref="artifact://scene-7/calibration",
        candidate_set_ref="candidate-set://scene-7/head-camera",
        constraints=("preserve placement order",),
    )


def test_intent_is_immutable_and_strictly_binds_observation_identity():
    intent = _intent()
    assert intent.motion_authorized is False
    with pytest.raises(ValidationError, match="observation identity"):
        ManipulationIntent.model_validate(
            intent.model_copy(update={"observation_ref": "observation://scene-8/head-camera"})
            .model_dump()
        )
    with pytest.raises(ValidationError):
        intent.task_id = "changed"


def test_replan_is_a_bounded_hint_and_preserves_task_identity():
    intent = _intent()
    failure = RouteFailure(
        candidate_ref="candidate://red-block/1",
        arm_ids=("left",),
        phase="transport",
        code="attached_collision",
        owner="collision",
        detail="attached object intersects the table",
        route_digest="b" * 64,
    )
    signal = ReplanCoordinator(max_failures=1).build_signal(intent, [failure])
    assert signal.status == "replan_required"
    assert signal.task_id == intent.task_id
    assert signal.revision_id == intent.revision_id
    assert signal.node_digest == intent.node_digest
    assert signal.preserved_constraints == intent.constraints
    assert signal.motion_authorized is False
    assert not hasattr(signal, "new_revision_id")
    assert not hasattr(signal, "resource_locks")


def test_replan_rejects_unbounded_or_evidence_free_route_failure():
    intent = _intent()
    failure = RouteFailure(
        candidate_ref="candidate://red-block/1",
        arm_ids=("left",),
        phase="contact",
        code="planner_failed",
        owner="planner",
        detail="no complete route",
    )
    with pytest.raises(ValueError, match="configured bound"):
        ReplanCoordinator(max_failures=1).build_signal(intent, [failure, failure])
    with pytest.raises(ValueError, match="at least one"):
        ReplanCoordinator().build_signal(intent, [])


def test_replan_signal_rejects_digest_drift_duplicates_and_empty_actions():
    intent = _intent()
    failure = RouteFailure(
        candidate_ref="candidate://red-block/1",
        arm_ids=("left",),
        phase="transport",
        code="attached_collision",
        owner="collision",
        detail="attached object intersects the table",
        route_digest="b" * 64,
    )
    signal = ReplanCoordinator().build_signal(intent, [failure])

    with pytest.raises(ValidationError, match="digest does not match"):
        type(signal).model_validate(
            signal.model_copy(update={"scene_revision": "scene-8"}).model_dump()
        )
    with pytest.raises(ValidationError, match="digest does not match"):
        type(signal).model_validate(
            signal.model_copy(update={"node_digest": "c" * 64}).model_dump()
        )
    with pytest.raises(ValidationError, match="failed routes must be unique"):
        type(signal).model_validate(
            signal.model_copy(update={"failed_routes": (failure, failure)}).model_dump()
        )
    with pytest.raises(ValidationError, match="at least one next action"):
        type(signal).model_validate(
            signal.model_copy(update={"next_actions": ()}).model_dump()
        )
