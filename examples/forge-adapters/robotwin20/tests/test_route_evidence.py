from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from test_route_readiness import _request

from robotwin20_adapter import (
    ROUTE_CHECKS,
    ROUTE_EVIDENCE_PROFILE_SCHEMA_VERSION,
    ROUTE_EVIDENCE_SCHEMA_VERSION,
    RouteEvidenceError,
    build_route_evidence_client,
    verify_route_evidence,
)
from robotwin20_adapter.process_worker import JsonlProcessWorkerClient, ProcessWorkerConfig
from robotwin20_adapter.route_readiness import route_geometry_digest

WORKER = Path(__file__).parents[1] / "runtime" / "robotwin_route_evidence_worker.py"
TRUSTED = {
    "producer_id": "independent-simulation-probe/v1",
    "profile_sha256": "b" * 64,
    "evidence_mode": "independent_simulation_probe",
}


def _write_artifact(root: Path, name: str, content: bytes = b"independently-produced\n") -> dict[str, str]:
    path = root / "inputs" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return {
        "artifact_ref": f"artifact://inputs/{name}",
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _external(request: dict, root: Path) -> dict:
    candidate = request["candidates"][0]
    geometry = root / "blocks" / "geometry" / "red.json"
    geometry.parent.mkdir(parents=True, exist_ok=True)
    geometry.write_bytes(b"attached geometry\n")
    request["candidates"][0]["attached_object"]["geometry_sha256"] = hashlib.sha256(
        geometry.read_bytes()
    ).hexdigest()
    records = [_write_artifact(root, f"scope-{index}.json", f"scope-{index}".encode()) for index in range(6)]
    snapshots = []
    for index in range(2):
        payload = {
            "scene_revision": request["scene_revision"],
            "observation_ref": request["observation_ref"],
            "frame_id": request["frame_id"],
            "candidate_set_ref": request["candidate_set_ref"],
            "captured_at": f"2026-09-04T00:00:0{index}Z",
            "state_digest": hashlib.sha256(f"state-{index}".encode()).hexdigest(),
        }
        snapshots.append(_write_artifact(root, f"snapshot-{index}.json", json.dumps(payload).encode()))
    return {
        "schema_version": ROUTE_EVIDENCE_SCHEMA_VERSION,
        "request_id": request["request_id"],
        "candidate_ref": candidate["candidate_ref"],
        "entity_ref": candidate["entity_ref"],
        "observation_ref": request["observation_ref"],
        "scene_revision": request["scene_revision"],
        "frame_id": request["frame_id"],
        "calibration_ref": request["calibration_ref"],
        "candidate_set_ref": request["candidate_set_ref"],
        "route_geometry_digest": route_geometry_digest(request),
        "planner": {
            "status": "pass",
            "planner_id": "independent-collision-planner/v1",
            "trajectory": _write_artifact(root, "trajectory.bin", b"trajectory"),
            "joint_limits": _write_artifact(root, "joint-limits.bin", b"joint limits"),
            "route_phase_order": [item["phase"] for item in candidate["route"]],
        },
        "scopes": {
            scope: {
                "status": "pass",
                "evidence": records[index],
                "method": f"independent-{scope}-probe/v1",
            }
            for index, scope in enumerate(ROUTE_CHECKS)
        },
        "before_snapshot": snapshots[0],
        "after_snapshot": snapshots[1],
        "semantic_verdict": {
            "status": "pass",
            "verifier_id": "independent-semantic-verifier/v1",
            "criteria": ["ordered_blocks", "target_relation"],
            "after_snapshot_ref": snapshots[1]["artifact_ref"],
        },
        "producer_binding": TRUSTED.copy(),
        "probe_execution": {
            "simulation_only": True,
            "motion_authorized": True,
            "world_change_started": True,
            "world_change_completed": True,
            "authorization": _write_artifact(root, "probe-authorization.json", b"authorized probe"),
        },
    }


def test_independent_evidence_verifier_requires_all_bound_artifacts(tmp_path: Path):
    request = _request(tmp_path)
    result = verify_route_evidence(request, _external(request, tmp_path), tmp_path, trusted_producer=TRUSTED)
    assert result["schema_version"] == "paos-robotwin20-simulation-route-readiness/v1"
    assert result["checks"] == {scope: "pass" for scope in ROUTE_CHECKS}
    assert result["motion_authorized"] is False
    assert result["world_change_started"] is False
    assert len(result["evidence"]) == 4 + len(ROUTE_CHECKS) + 2


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda value: value["scopes"].pop("contact_dynamics"), "scopes are incomplete"),
        (lambda value: value.update(route_geometry_digest="0" * 64), "geometry digest"),
        (lambda value: value["planner"].update(status="unavailable"), "planner status"),
        (lambda value: value["semantic_verdict"].update(after_snapshot_ref="artifact://inputs/other.json"), "snapshot binding"),
        (lambda value: value["probe_execution"].update(world_change_completed=False), "incomplete"),
        (lambda value: value.update(producer_binding={**TRUSTED, "producer_id": "untrusted"}), "untrusted"),
    ],
)
def test_external_evidence_fails_closed(tmp_path: Path, mutate, message: str):
    request = _request(tmp_path)
    evidence = _external(request, tmp_path)
    mutate(evidence)
    with pytest.raises(RouteEvidenceError, match=message):
        verify_route_evidence(request, evidence, tmp_path, trusted_producer=TRUSTED)


def test_external_artifact_digest_and_symlink_fail_closed(tmp_path: Path):
    request = _request(tmp_path)
    evidence = _external(request, tmp_path)
    evidence["planner"]["trajectory"]["sha256"] = "f" * 64
    with pytest.raises(RouteEvidenceError, match="digest mismatch"):
        verify_route_evidence(request, evidence, tmp_path, trusted_producer=TRUSTED)
    evidence = _external(request, tmp_path)
    target = tmp_path / "inputs" / "scope-0.json"
    link = tmp_path / "inputs" / "scope-0-link.json"
    link.symlink_to(target)
    evidence["planner"]["trajectory"] = {
        "artifact_ref": "artifact://inputs/scope-0-link.json",
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    }
    with pytest.raises(RouteEvidenceError, match="unsafe"):
        verify_route_evidence(request, evidence, tmp_path, trusted_producer=TRUSTED)


def test_route_evidence_worker_roundtrip_and_immutable_projection(tmp_path: Path):
    config = ProcessWorkerConfig(
        command=(sys.executable, str(WORKER), "--artifact-root", str(tmp_path), "--worker-id", "route-evidence-test/v1", "--trusted-producer-id", TRUSTED["producer_id"], "--trusted-profile-sha256", TRUSTED["profile_sha256"]),
        cwd=WORKER.parent,
        environment={"PYTHONPATH": str(Path(__file__).parents[1] / "src") + ":" + str(WORKER.parent)},
        startup_timeout_s=2,
        request_timeout_s=2,
        shutdown_timeout_s=2,
    )
    client = JsonlProcessWorkerClient(config)
    try:
        request = _request(tmp_path)
        external = _external(request, tmp_path)
        response = client.request({"request_id": request["request_id"], "route_request": request, "external_evidence": external})
        assert response["status"] == "available"
        assert response["provider_available"] is True
        assert response["motion_authorized"] is False
        canonical = tmp_path / "route-evidence" / "red-block-1.json"
        assert canonical.is_file()
        original = canonical.read_bytes()
        response = client.request({"request_id": request["request_id"], "route_request": request, "external_evidence": external})
        assert canonical.read_bytes() == original
        assert response["route_evidence"]["world_change_started"] is False
    finally:
        client.release()


def test_profile_owned_route_evidence_client(tmp_path: Path):
    import yaml

    profile_path = tmp_path / "route-evidence.yaml"
    profile = {
        "schema_version": ROUTE_EVIDENCE_PROFILE_SCHEMA_VERSION,
        "worker_id": "route-evidence-test/v1",
        "artifact_root": str(tmp_path),
        "trusted_producer": TRUSTED,
        "worker": {
            "python": sys.executable,
            "script": str(WORKER),
            "cwd": str(WORKER.parent),
            "startup_timeout_s": 2,
            "request_timeout_s": 2,
            "shutdown_timeout_s": 2,
            "environment": {"PYTHONPATH": f"{Path(__file__).parents[1] / 'src'}:{WORKER.parent}"},
            "arguments": ["--artifact-root", str(tmp_path), "--worker-id", "route-evidence-test/v1", "--trusted-producer-id", TRUSTED["producer_id"], "--trusted-profile-sha256", TRUSTED["profile_sha256"]],
        },
    }
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    client = build_route_evidence_client(profile)
    try:
        request = _request(tmp_path)
        response = client.verify(request, _external(request, tmp_path))
        assert response["status"] == "available"
        assert response["route_evidence"]["motion_authorized"] is False
    finally:
        client.release()
