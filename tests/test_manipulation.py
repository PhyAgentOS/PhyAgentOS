from __future__ import annotations

import pytest
from pydantic import ValidationError

from PhyAgentOS.forge.capability_runtime.manipulation_capabilities import CapabilitySnapshotEndpoint
from PhyAgentOS.forge.manipulation import (
    ArmCapability,
    CapabilitySnapshot,
    CoordinationGroup,
    CoordinationMode,
    ManipulationIntent,
    ReplanCoordinator,
    ResourceMode,
    ResourceRequirement,
    RouteFailure,
    capability_snapshot_digest,
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


def test_resource_requirement_is_symbolic_and_strict():
    requirement = ResourceRequirement(
        mode=ResourceMode.ALTERNATIVE_RESOURCE,
        substitution_allowed=True,
    )
    assert requirement.resource_class == "manipulator"
    with pytest.raises(ValidationError, match="substitution_allowed"):
        ResourceRequirement(mode=ResourceMode.ALTERNATIVE_RESOURCE)
    with pytest.raises(ValidationError, match="at least two"):
        ResourceRequirement(mode=ResourceMode.ATOMIC_GROUP)


def _capability_snapshot() -> CapabilitySnapshot:
    value = {
        "schema_version": "paos-manipulation-capability-snapshot/v1",
        "snapshot_ref": "artifact://capabilities/task-1/revision-2",
        "snapshot_digest": "0" * 64,
        "scene_revision": "scene-7",
        "observation_ref": "observation://scene-7/camera_front",
        "calibration_ref": "artifact://scene-7/calibration",
        "embodiment_id": "dual-panda",
        "topology": "dual_independent",
        "profile_digest": "b" * 64,
        "captured_at": "2026-09-05T12:00:00+00:00",
        "arms": (
            ArmCapability(
                arm_id="left", base_frame="world", tool_frame="panda_hand",
                planner_profile_ref="artifact://planner/left",
                workspace_ref="artifact://workspace/left",
                joint_limits_ref="artifact://limits/left",
                gripper_identity="panda-gripper",
                supported_modes=(ResourceMode.SINGLE_RESOURCE, ResourceMode.ALTERNATIVE_RESOURCE),
            ),
            ArmCapability(
                arm_id="right", base_frame="world", tool_frame="panda_hand",
                planner_profile_ref="artifact://planner/right",
                workspace_ref="artifact://workspace/right",
                joint_limits_ref="artifact://limits/right",
                gripper_identity="panda-gripper",
                supported_modes=(ResourceMode.SINGLE_RESOURCE, ResourceMode.ALTERNATIVE_RESOURCE),
            ),
        ),
        "motion_authorized": False,
    }
    value["snapshot_digest"] = capability_snapshot_digest(value)
    return CapabilitySnapshot.model_validate(value)


def test_capability_snapshot_binds_scene_and_digest():
    snapshot = _capability_snapshot()
    assert snapshot.motion_authorized is False
    with pytest.raises(ValidationError, match="observation identity"):
        CapabilitySnapshot.model_validate(
            snapshot.model_copy(update={"observation_ref": "observation://other/camera"}).model_dump()
        )


def test_coordination_group_requires_atomic_bundle():
    with pytest.raises(ValidationError, match="timeline and route bundle"):
        CoordinationGroup(
            group_ref="artifact://coordination/task-1/group-1",
            mode=ResourceMode.ATOMIC_GROUP,
            participant_ids=("left", "right"),
            scene_revision="scene-7",
        )


def test_capability_snapshot_endpoint_is_query_only_and_fails_closed():
    snapshot = _capability_snapshot()

    class Provider:
        def describe(self, request):
            return snapshot

    endpoint = CapabilitySnapshotEndpoint(Provider())
    result = endpoint.invoke({
        "scene_revision": "scene-7",
        "observation_ref": "observation://scene-7/camera_front",
        "calibration_ref": "artifact://scene-7/calibration",
    })
    assert result["status"] == "available"
    assert result["motion_authorized"] is False
    assert endpoint.invoke({"scene_revision": "scene-8"})["status"] == "invalid"

    class Broken:
        def describe(self, request):
            raise RuntimeError("unavailable")

    assert CapabilitySnapshotEndpoint(Broken()).invoke({
        "scene_revision": "scene-7",
        "observation_ref": "observation://scene-7/camera_front",
        "calibration_ref": "artifact://scene-7/calibration",
    })["status"] == "unavailable"
