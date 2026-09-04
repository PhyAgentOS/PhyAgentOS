from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from robotwin20_adapter import (
    ROUTE_CHECKS,
    ROUTE_PHASES,
    ROUTE_READINESS_PROFILE_SCHEMA_VERSION,
    RouteReadinessError,
    build_route_readiness_client,
    load_route_readiness_profile,
    route_geometry_digest,
    validate_route_request,
)
from robotwin20_adapter.process_worker import JsonlProcessWorkerClient, ProcessWorkerConfig
from robotwin20_adapter.route_readiness import project_route_evidence

WORKER = Path(__file__).parents[1] / "runtime" / "robotwin_route_readiness_worker.py"


def _pose(z: float = 0.8) -> dict:
    return {
        "frame_id": "head_camera",
        "position_m": [0.0, 0.0, z],
        "orientation_xyzw": [0.0, 0.0, 0.0, 1.0],
        "max_linear_speed_mps": 0.2,
        "max_joint_speed_radps": 1.0,
    }


def _request(tmp_path: Path) -> dict:
    phases = []
    for phase in ROUTE_PHASES:
        phases.append({
            "phase": phase,
            "waypoints": [_pose()],
            "gripper_state": "open" if phase == "approach" else "closed" if phase in {"close", "lift", "transport", "descent"} else "released" if phase == "release" else "open",
        })
    return {
        "request_id": "request-route-1",
        "observation_ref": "observation://blocks_ranking_rgb-0-1/head_camera",
        "scene_revision": "blocks_ranking_rgb-0-1",
        "frame_id": "head_camera",
        "calibration_ref": "artifact://blocks/calibration",
        "candidate_set_ref": "candidate-set://blocks_ranking_rgb-0-1/head_camera",
        "workspace_bounds_m": {
            "x_min_m": -0.5, "x_max_m": 0.5, "y_min_m": -0.5, "y_max_m": 0.5, "z_min_m": 0.5, "z_max_m": 1.2,
        },
        "joint_limits_ref": "artifact://blocks/joint-limits",
        "stop_policy_ref": "artifact://blocks/stop-policy",
        "candidates": [{
            "candidate_ref": "candidate://red-block/1",
            "entity_ref": "entity://red-block",
            "provenance": ["artifact://blocks/points/red"],
            "grasp_frame": _pose(),
            "attached_object": {
                "geometry_ref": "artifact://blocks/geometry/red",
                "geometry_sha256": "a" * 64,
                "frame_id": "head_camera",
                "half_extents_m": [0.02, 0.02, 0.02],
                "grasp_transform": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
            },
            "route": phases,
        }],
    }


def test_valid_route_request_is_deterministically_bound(tmp_path: Path):
    request = _request(tmp_path)
    validate_route_request(request)
    assert route_geometry_digest(request) == route_geometry_digest(request)


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda r: r["candidates"][0]["route"].reverse(), "phases"),
        (lambda r: r["candidates"][0]["attached_object"].update(geometry_sha256="bad"), "SHA-256"),
        (lambda r: r["candidates"][0]["attached_object"].update(frame_id="wrist"), "frame"),
        (lambda r: r["candidates"][0]["route"][0]["waypoints"][0].update(position_m=[0, 0, 2]), "workspace"),
        (lambda r: r["candidates"][0]["route"][0]["waypoints"][0].update(max_linear_speed_mps=0), "positive"),
    ],
)
def test_route_request_fails_closed(tmp_path: Path, mutate, message: str):
    request = _request(tmp_path)
    mutate(request)
    with pytest.raises(RouteReadinessError, match=message):
        validate_route_request(request)


def test_route_evidence_never_authorizes_motion(tmp_path: Path):
    request = _request(tmp_path)
    candidate = request["candidates"][0]
    evidence = project_route_evidence(
        request,
        candidate,
        capability_status={check: "unavailable" for check in ROUTE_CHECKS},
        evidence_ref="artifact://route/evidence-1",
    )
    assert evidence["motion_authorized"] is False
    assert evidence["world_change_started"] is False
    assert set(evidence["checks"]) == set(ROUTE_CHECKS)


def test_external_worker_records_unavailable_evidence_without_motion(tmp_path: Path):
    config = ProcessWorkerConfig(
        command=(sys.executable, str(WORKER), "--artifact-root", str(tmp_path), "--worker-id", "route-readiness-test/v1"),
        cwd=WORKER.parent,
        environment={"PYTHONPATH": str(Path(__file__).parents[1] / "src") + ":" + str(WORKER.parent)},
        startup_timeout_s=2,
        request_timeout_s=2,
        shutdown_timeout_s=2,
    )
    client = JsonlProcessWorkerClient(config)
    try:
        request = _request(tmp_path)
        response = client.request(request)
        assert response["status"] == "unavailable"
        assert response["provider_available"] is False
        assert response["motion_authorized"] is False
        artifact = next((tmp_path / "simulation-route-readiness").glob("*.json"), None)
        assert artifact is not None
        evidence = json.loads(artifact.read_text(encoding="utf-8"))
        assert all(status == "unavailable" for status in evidence["checks"].values())
    finally:
        client.release()


def test_profile_owned_route_client_preserves_unavailable_boundary(tmp_path: Path):
    profile_path = tmp_path / "route-readiness.yaml"
    value = {
        "schema_version": ROUTE_READINESS_PROFILE_SCHEMA_VERSION,
        "worker_id": "route-readiness-test/v1",
        "artifact_root": str(tmp_path),
        "worker": {
            "python": sys.executable,
            "script": str(WORKER),
            "cwd": str(WORKER.parent),
            "startup_timeout_s": 2,
            "request_timeout_s": 2,
            "shutdown_timeout_s": 2,
            "environment": {
                "PYTHONUNBUFFERED": "1",
                "PYTHONPATH": f"{Path(__file__).parents[1] / 'src'}:{WORKER.parent}",
            },
            "arguments": [
                "--artifact-root", str(tmp_path),
                "--worker-id", "route-readiness-test/v1",
            ],
        },
    }
    import yaml

    profile_path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    loaded = load_route_readiness_profile(profile_path)
    client = build_route_readiness_client(loaded)
    try:
        response = client.evaluate(_request(tmp_path))
        assert response["status"] == "unavailable"
        assert response["motion_authorized"] is False
    finally:
        client.release()
