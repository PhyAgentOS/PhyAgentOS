from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from PhyAgentOS.forge.manipulation import CoordinationMode, ManipulationIntent
from test_route_readiness import _request

from robotwin20_adapter import (
    CompleteRouteSelector,
    RouteGenerationError,
    enumerate_arm_candidates,
    generate_route_request,
    load_arm_planning_profile,
    validate_route_request,
)
from robotwin20_adapter.arm_candidates import ROUTE_EVALUATION_SCHEMA_VERSION
from robotwin20_adapter.route_readiness import ROUTE_CHECKS, ROUTE_PHASES, route_geometry_digest


def _inputs():
    complete = _request(Path("/tmp"))
    candidate = complete["candidates"][0]
    base = deepcopy(complete)
    base["candidates"] = []
    proposal = {
        "candidate_ref": candidate["candidate_ref"],
        "entity_ref": candidate["entity_ref"],
        "provenance": deepcopy(candidate["provenance"]),
        "observation_ref": base["observation_ref"],
        "observation_frame_id": base["observation_frame_id"],
        "scene_revision": base["scene_revision"],
        "calibration_ref": base["calibration_ref"],
        "candidate_set_ref": base["candidate_set_ref"],
    }
    execution_grasp = deepcopy(candidate["execution_grasp"])
    attached_object = deepcopy(candidate["attached_object"])
    placement_target = {
        key: deepcopy(candidate["placement_target"][key])
        for key in ("target_ref", "target_object_pose", "provenance_ref")
    }
    policy = {
        "approach_clearance_m": 0.08,
        "lift_clearance_m": 0.10,
        "transport_clearance_m": 0.12,
        "descent_clearance_m": 0.04,
        "retreat_distance_m": 0.10,
        "retreat_direction": {
            "frame_id": "world",
            "vector": [0.0, 0.0, 1.0],
            "provenance_ref": "artifact://robotwin/franka/route-policy",
        },
    }
    return base, proposal, execution_grasp, attached_object, placement_target, policy


def _generate():
    return generate_route_request(*_inputs())


def test_route_generation_produces_complete_deterministic_no_motion_request():
    inputs = _inputs()
    before = deepcopy(inputs)
    first = generate_route_request(*inputs)
    second = generate_route_request(*inputs)
    candidate = first["candidates"][0]
    assert [item["phase"] for item in candidate["route"]] == list(ROUTE_PHASES)
    assert candidate["route"][0]["gripper_state"] == "open"
    assert candidate["route"][3]["gripper_state"] == "closed"
    assert candidate["route"][6]["gripper_state"] == "released"
    assert first == second
    assert inputs == before
    validate_route_request(first)


def test_route_generation_uses_object_to_robot_target_transform_for_release_pose():
    inputs = list(_inputs())
    inputs[3]["object_T_robot_target"] = [
        1, 0, 0, 0.01,
        0, 1, 0, -0.02,
        0, 0, 1, 0.03,
        0, 0, 0, 1,
    ]
    generated = generate_route_request(*inputs)["candidates"][0]
    target = generated["placement_target"]["target_object_pose"]["position_m"]
    release = generated["placement_target"]["release_robot_target_pose"]["position_m"]
    assert release == pytest.approx(
        [target[0] + 0.01, target[1] - 0.02, target[2] + 0.03]
    )


@pytest.mark.parametrize(
    ("index", "mutate", "message"),
    [
        (1, lambda value: value.update(scene_revision="stale"), "not bound"),
        (2, lambda value: value["ingress_direction"].update(vector=[0, 0, 0]), "normalized"),
        (3, lambda value: value.update(half_extents_m=[float("nan"), 0.02, 0.02]), "finite"),
        (3, lambda value: value.update(object_T_robot_target=[0.0] * 16), "homogeneous row"),
        (4, lambda value: value["target_object_pose"].update(frame_id="camera"), "frame"),
        (5, lambda value: value.update(lift_clearance_m=0), "positive"),
    ],
)
def test_route_generation_rejects_unbound_or_unsafe_inputs(index, mutate, message):
    inputs = list(_inputs())
    mutate(inputs[index])
    with pytest.raises(RouteGenerationError, match=message):
        generate_route_request(*inputs)


def test_franka_profile_feeds_candidate_arm_route_selection_chain():
    generated = _generate()
    profile = load_arm_planning_profile(
        (
            Path(__file__).parents[1]
            / "profiles"
            / "robotwin20"
            / "manipulation-planning.yaml"
        ).resolve()
    )
    intent = ManipulationIntent(
        task_id="task-1",
        revision_id="revision-1",
        node_id="prepare-red",
        node_digest="a" * 64,
        entity_ref="entity://red-block",
        goal="prepare red block route",
        success_criteria=("one route passes readiness",),
        allowed_arms=("left", "right"),
        coordination_mode=CoordinationMode.ALTERNATIVE_ARM,
        observation_ref=generated["observation_ref"],
        scene_revision=generated["scene_revision"],
        observation_frame_id=generated["observation_frame_id"],
        calibration_ref=generated["calibration_ref"],
        candidate_set_ref=generated["candidate_set_ref"],
    )
    options = enumerate_arm_candidates(intent, generated["candidates"], profile)

    def evaluate(request, option):
        route = request["candidates"][0]["route"]
        positions = [point["position_m"] for phase in route for point in phase["waypoints"]]
        length = sum(
            sum((a - b) ** 2 for a, b in zip(left, right)) ** 0.5
            for left, right in zip(positions, positions[1:])
        )
        return {
            "schema_version": ROUTE_EVALUATION_SCHEMA_VERSION,
            "request_id": request["request_id"],
            "task_id": intent.task_id,
            "revision_id": intent.revision_id,
            "node_id": intent.node_id,
            "node_digest": intent.node_digest,
            "candidate_ref": option["candidate_ref"],
            "entity_ref": option["entity_ref"],
            "observation_ref": option["observation_ref"],
            "scene_revision": option["scene_revision"],
            "observation_frame_id": option["observation_frame_id"],
            "frame_id": option["frame_id"],
            "calibration_ref": option["calibration_ref"],
            "candidate_set_ref": option["candidate_set_ref"],
            "arm_ids": option["arm_ids"],
            "option_id": option["option_id"],
            "status": "pass",
            "checks": {check: "pass" for check in ROUTE_CHECKS},
            "phase": "none",
            "code": "ok",
            "owner": "readiness",
            "detail": "complete route passes",
            "route_geometry_digest": route_geometry_digest(request),
            "evidence_refs": ["artifact://route/readiness"],
            "motion_authorized": False,
            "world_change_started": False,
            "metrics": {"route_length_m": length, "min_joint_speed_margin_radps": 0.2},
        }

    selected = CompleteRouteSelector(evaluate, profile).select(intent, generated, options)
    assert selected["status"] == "selected"
    assert selected["frame_id"] == "world"
    assert selected["motion_authorized"] is False
