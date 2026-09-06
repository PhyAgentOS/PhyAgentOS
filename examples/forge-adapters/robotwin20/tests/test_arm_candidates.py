from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest
from PhyAgentOS.forge.manipulation import (
    CoordinationMode,
    ManipulationIntent,
)
from test_route_readiness import WORKER, _request

from robotwin20_adapter import (
    ARM_PLANNING_PROFILE_SCHEMA_VERSION,
    ROUTE_EVALUATION_SCHEMA_VERSION,
    ArmPlanningError,
    CompleteRouteSelector,
    JsonlProcessWorkerClient,
    ProcessWorkerConfig,
    RouteReadinessClient,
    RouteReadinessEvaluationAdapter,
    build_capability_snapshot,
    enumerate_arm_candidates,
    load_arm_planning_profile,
    project_arm_assignment,
    validate_arm_planning_profile,
)
from robotwin20_adapter.route_readiness import (
    ROUTE_CHECKS,
    project_route_evidence,
    route_geometry_digest,
)


def _profile() -> dict:
    return {
        "schema_version": ARM_PLANNING_PROFILE_SCHEMA_VERSION,
        "embodiment_id": "franka-panda",
        "topology": "dual_independent",
        "route_frame_id": "world",
        "arms": [
            {"arm_id": "left", "base_frame": "world", "tool_frame": "panda_hand", "gripper_identity": "panda-gripper", "planner_profile_ref": "artifact://planner/left", "workspace_ref": "artifact://workspace/left", "joint_limits_ref": "artifact://limits/left", "controller_capabilities_ref": "artifact://controller/left", "park_pose_ref": "artifact://park/left", "supported_modes": ["single_resource", "alternative_resource"]},
            {"arm_id": "right", "base_frame": "world", "tool_frame": "panda_hand", "gripper_identity": "panda-gripper", "planner_profile_ref": "artifact://planner/right", "workspace_ref": "artifact://workspace/right", "joint_limits_ref": "artifact://limits/right", "controller_capabilities_ref": "artifact://controller/right", "park_pose_ref": "artifact://park/right", "supported_modes": ["single_resource", "alternative_resource"]},
        ],
        "route_policy": {
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
        },
        "selection_policy": {
            "max_options": 8,
            "weights": {"route_length": 1.0, "speed_margin": 0.1},
            "tie_break": "candidate_ref_then_arm_id",
        },
    }


def _intent() -> ManipulationIntent:
    return ManipulationIntent(
        task_id="task-1",
        revision_id="revision-1",
        node_id="pick-red",
        node_digest="a" * 64,
        entity_ref="entity://red-block",
        goal="move red block",
        success_criteria=("red block is placed",),
        allowed_arms=("left", "right"),
        coordination_mode=CoordinationMode.ALTERNATIVE_ARM,
        observation_ref="observation://blocks_ranking_rgb-0-1/head_camera",
        scene_revision="blocks_ranking_rgb-0-1",
        observation_frame_id="head_camera",
        calibration_ref="artifact://blocks/calibration",
        candidate_set_ref="candidate-set://blocks_ranking_rgb-0-1/head_camera",
        constraints=("preserve_scene_revision",),
    )


def _result(request, option, *, status="pass"):
    positions = [
        waypoint["position_m"]
        for phase in request["candidates"][0]["route"]
        for waypoint in phase["waypoints"]
    ]
    route_length = sum(
        sum((a - b) ** 2 for a, b in zip(left, right)) ** 0.5
        for left, right in zip(positions, positions[1:])
    )
    return {
        "schema_version": ROUTE_EVALUATION_SCHEMA_VERSION,
        "request_id": request["request_id"],
        "task_id": "task-1",
        "revision_id": "revision-1",
        "node_id": "pick-red",
        "node_digest": "a" * 64,
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
        "status": status,
        "checks": {check: "pass" if status == "pass" else "fail" for check in ROUTE_CHECKS},
        "phase": "none" if status == "pass" else "transport",
        "code": "ok" if status == "pass" else "collision",
        "owner": "readiness" if status == "pass" else "collision",
        "detail": "all checks passed" if status == "pass" else "route collides",
        "route_geometry_digest": route_geometry_digest(request),
        "evidence_refs": ["artifact://route/evidence"],
        "motion_authorized": False,
        "world_change_started": False,
        "metrics": {
            "route_length_m": route_length,
            "min_joint_speed_margin_radps": 0.2,
        },
    }


def test_enumeration_expands_candidates_over_both_arms():
    request = _request(Path("/tmp"))
    candidates = [dict(request["candidates"][0])]
    options = enumerate_arm_candidates(_intent(), candidates, _profile())
    assert [item["arm_ids"] for item in options] == [["left"], ["right"]]
    assert all(item["motion_authorized"] is False for item in options)


def test_selector_skips_failed_arm_and_selects_passing_arm():
    request = _request(Path("/tmp"))
    candidates = [dict(request["candidates"][0])]
    options = enumerate_arm_candidates(_intent(), candidates, _profile())
    def evaluate(route_request, option):
        return _result(route_request, option, status="fail" if option["arm_ids"] == ["left"] else "pass")
    result = CompleteRouteSelector(evaluate, _profile()).select(_intent(), request, options)
    assert result["status"] == "selected"
    assert result["arm_ids"] == ["right"]
    assert result["motion_authorized"] is False
    assert len(result["rejected_routes"]) == 1


def test_selector_returns_replan_when_all_options_fail():
    request = _request(Path("/tmp"))
    options = enumerate_arm_candidates(_intent(), [dict(request["candidates"][0])], _profile())
    result = CompleteRouteSelector(lambda route_request, option: _result(route_request, option, status="fail"), _profile()).select(_intent(), request, options)
    assert result.status == "replan_required"
    assert len(result.failed_routes) == 2
    assert result.motion_authorized is False


def test_selector_integrates_one_argument_readiness_client_and_replans_unavailable():
    request = _request(Path("/tmp"))
    options = enumerate_arm_candidates(_intent(), [dict(request["candidates"][0])], _profile())

    class OneArgumentClient:
        def evaluate(self, route_request):
            return {"status": "unavailable", "route_evidence": [project_route_evidence(
                route_request,
                route_request["candidates"][0],
                capability_status={check: "unavailable" for check in ROUTE_CHECKS},
                evidence_ref="artifact://route-readiness/unavailable",
            )]}

    result = CompleteRouteSelector(
        RouteReadinessEvaluationAdapter(OneArgumentClient()), _profile()
    ).select(_intent(), request, options)

    assert result.status == "replan_required"
    assert {failure.code for failure in result.failed_routes} == {"provider_unavailable"}
    assert result.motion_authorized is False


def test_selector_to_jsonl_route_worker_is_no_motion_and_replans_unavailable(tmp_path):
    request = _request(tmp_path)
    options = enumerate_arm_candidates(
        _intent(), [dict(request["candidates"][0])], _profile()
    )
    config = ProcessWorkerConfig(
        command=(
            sys.executable,
            str(WORKER),
            "--artifact-root",
            str(tmp_path),
            "--worker-id",
            "route-selector-integration/v1",
        ),
        cwd=WORKER.parent,
        environment={
            "PYTHONPATH": (
                f"{Path(__file__).parents[1] / 'src'}:{WORKER.parent}"
            )
        },
        startup_timeout_s=2,
        request_timeout_s=2,
        shutdown_timeout_s=2,
    )
    client = RouteReadinessClient(
        JsonlProcessWorkerClient(config), worker_id="route-selector-integration/v1"
    )
    try:
        result = CompleteRouteSelector(
            RouteReadinessEvaluationAdapter(client), _profile()
        ).select(_intent(), request, options)
    finally:
        client.release()

    assert result.status == "replan_required"
    assert len(result.failed_routes) == 2
    assert {failure.code for failure in result.failed_routes} == {
        "provider_unavailable"
    }
    assert result.motion_authorized is False


def test_enumerator_rejects_stale_scene_and_unimplemented_bimanual():
    request = _request(Path("/tmp"))
    stale = dict(request["candidates"][0])
    stale["scene_revision"] = "stale-scene"
    with pytest.raises(ArmPlanningError, match="stale"):
        enumerate_arm_candidates(_intent(), [stale], _profile())

    intent_payload = _intent().model_dump(mode="python")
    intent_payload["coordination_mode"] = "bimanual"
    coordinated = _profile()
    coordinated["topology"] = "dual_coordinated"
    with pytest.raises(ArmPlanningError, match="synchronized"):
        enumerate_arm_candidates(ManipulationIntent.model_validate(intent_payload), [request["candidates"][0]], coordinated)


def test_selector_converts_provider_error_and_tampered_success_to_replan():
    request = _request(Path("/tmp"))
    options = enumerate_arm_candidates(_intent(), [dict(request["candidates"][0])], _profile())

    def evaluate(route_request, option):
        if option["arm_ids"] == ["left"]:
            raise RuntimeError("planner unavailable")
        result = _result(route_request, option)
        result["motion_authorized"] = True
        return result

    outcome = CompleteRouteSelector(evaluate, _profile()).select(_intent(), request, options)
    assert outcome.status == "replan_required"
    assert {item.code for item in outcome.failed_routes} == {
        "readiness_provider_error",
        "invalid_readiness_result",
    }


def test_selector_rejects_tampered_arm_profile_and_inconsistent_failure():
    request = _request(Path("/tmp"))
    options = enumerate_arm_candidates(_intent(), [dict(request["candidates"][0])], _profile())
    tampered = dict(options[0])
    tampered["arm_profiles"] = [dict(options[1]["arm_profiles"][0])]
    with pytest.raises(ArmPlanningError, match="arm profile"):
        CompleteRouteSelector(lambda *_: {}, _profile()).select(_intent(), request, [tampered])

    def inconsistent(route_request, option):
        result = _result(route_request, option, status="pass")
        result["status"] = "fail"
        return result

    outcome = CompleteRouteSelector(inconsistent, _profile()).select(_intent(), request, options)
    assert outcome.status == "replan_required"
    assert all(item.code == "invalid_readiness_result" for item in outcome.failed_routes)


def test_versioned_franka_profile_loads_and_topology_mismatch_fails_closed():
    profile_path = (
        Path(__file__).parents[1]
        / "profiles"
        / "robotwin20"
        / "manipulation-planning.yaml"
    ).resolve()
    loaded = load_arm_planning_profile(profile_path)
    assert loaded["embodiment_id"] == "franka-panda"
    assert [arm["arm_id"] for arm in loaded["arms"]] == ["left", "right"]

    invalid = _profile()
    invalid["topology"] = "single_arm"
    with pytest.raises(ArmPlanningError, match="topology"):
        validate_arm_planning_profile(invalid)


def test_arm_profile_loader_rejects_duplicate_keys(tmp_path):
    profile_path = tmp_path / "duplicate.yaml"
    profile_path.write_text(
        "schema_version: paos-robotwin20-arm-planning/v1\n"
        "schema_version: overwritten\n",
        encoding="utf-8",
    )

    with pytest.raises(ArmPlanningError, match="duplicate YAML keys"):
        load_arm_planning_profile(profile_path.resolve())


def test_enumeration_and_selection_are_deterministic_and_do_not_mutate_inputs():
    request = _request(Path("/tmp"))
    first = deepcopy(request["candidates"][0])
    second = deepcopy(first)
    first["candidate_ref"] = "candidate://red-block/2"
    second["candidate_ref"] = "candidate://red-block/1"
    candidates = [first, second]
    profile = _profile()
    candidates_before = deepcopy(candidates)
    profile_before = deepcopy(profile)
    request_before = deepcopy(request)

    options = enumerate_arm_candidates(_intent(), candidates, profile)
    selected = CompleteRouteSelector(
        lambda route_request, option: _result(route_request, option), profile
    ).select(_intent(), request, tuple(reversed(options)))

    assert selected["candidate_ref"] == "candidate://red-block/1"
    assert selected["arm_ids"] == ["left"]
    assert candidates == candidates_before
    assert profile == profile_before
    assert request == request_before


def test_selector_rejects_stale_base_request_without_calling_provider():
    request = _request(Path("/tmp"))
    options = enumerate_arm_candidates(
        _intent(), [dict(request["candidates"][0])], _profile()
    )
    request["scene_revision"] = "stale"

    class NoCall:
        def evaluate(self, *_args):
            raise AssertionError("provider must not be called")

    with pytest.raises(ArmPlanningError, match="does not match"):
        CompleteRouteSelector(NoCall(), _profile()).select(_intent(), request, options)


def test_capability_snapshot_and_assignment_bind_selected_route():
    profile = _profile()
    snapshot = build_capability_snapshot(
        profile,
        scene_revision=_intent().scene_revision,
        observation_ref=_intent().observation_ref,
        calibration_ref=_intent().calibration_ref,
        profile_digest="b" * 64,
        snapshot_ref="artifact://capabilities/task-1/revision-1",
        captured_at="2026-09-05T12:00:00+00:00",
    )
    request = _request(Path("/tmp"))
    options = enumerate_arm_candidates(_intent(), [dict(request["candidates"][0])], profile)
    selected = CompleteRouteSelector(
        lambda route_request, option: _result(route_request, option), profile
    ).select(_intent(), request, options)
    assignment = project_arm_assignment(_intent(), snapshot, selected)
    assert assignment.selected_arm_ids == ("left",)
    assert assignment.motion_authorized is False
    tampered = dict(selected)
    tampered["scene_revision"] = "stale"
    with pytest.raises(ArmPlanningError, match="does not match"):
        project_arm_assignment(_intent(), snapshot, tampered)
