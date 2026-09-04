from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from PhyAgentOS.forge.capability_runtime import ManipulationPreparationEndpoint

from robotwin20_adapter import (
    READINESS_PROFILE_SCHEMA_VERSION,
    ProcessWorkerError,
    ReadinessProfileError,
    build_readiness_evaluator,
    load_readiness_profile,
)

WORKER = Path(__file__).parents[1] / "runtime" / "readiness_replay_worker.py"


def _request():
    return {
        "observation_ref": "observation://scene-7/camera_front",
        "scene_revision": "scene-7",
        "frame_id": "camera_front",
        "calibration_ref": "calibration://front/v3",
        "freshness_ms": 20,
        "max_age_ms": 100,
        "candidate_set_ref": "candidate-set://scene-7/camera_front",
        "candidates": [
            {
                "candidate_ref": "candidate://bottle-1/1",
                "entity_ref": "entity://bottle-1",
            }
        ],
    }


def _prepared():
    return {
        "candidate_ref": "candidate://bottle-1/1",
        "entity_ref": "entity://bottle-1",
        "checks": {"kinematic": "pass", "collision": "pass", "workspace": "pass"},
        "evidence": ["artifact://scene-7/camera_front/derived/readiness-1"],
        "qualification": "prepared",
    }


def _fixture(tmp_path: Path, *, worker_id="robotwin20-readiness-replay/v1", prepared=None):
    path = tmp_path / "readiness.json"
    value = {
        "schema_version": "paos-robotwin20-readiness-replay/v1",
        "worker_id": worker_id,
        "motion_authorized": False,
        "cases": [
            {
                "observation_ref": "observation://scene-7/camera_front",
                "scene_revision": "scene-7",
                "frame_id": "camera_front",
                "candidate_set_ref": "candidate-set://scene-7/camera_front",
                "candidate_refs": [["candidate://bottle-1/1", "entity://bottle-1"]],
                "prepared_candidates": [] if prepared is None else [prepared],
            }
        ],
    }
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    path.chmod(0o600)
    return path


def _profile(tmp_path: Path, fixture: Path, *, worker_id="robotwin20-readiness-replay/v1"):
    artifact = fixture.read_bytes()
    return {
        "schema_version": READINESS_PROFILE_SCHEMA_VERSION,
        "worker_id": worker_id,
        "fixture": str(fixture),
        "fixture_sha256": hashlib.sha256(artifact).hexdigest(),
        "worker": {
            "python": sys.executable,
            "script": str(WORKER),
            "cwd": str(WORKER.parent),
            "startup_timeout_s": 2,
            "request_timeout_s": 2,
            "shutdown_timeout_s": 2,
            "environment": {"PYTHONUNBUFFERED": "1"},
            "arguments": [],
        },
    }


def test_profile_builds_process_replay_and_paos_projects_no_motion(tmp_path):
    fixture = _fixture(tmp_path, prepared=_prepared())
    evaluator = build_readiness_evaluator(_profile(tmp_path, fixture))
    result = ManipulationPreparationEndpoint(evaluator).invoke(
        {**_request(), "candidates": [{**_request()["candidates"][0], "grasp_frame": {"frame_id": "camera_front", "unit": "m", "position_m": [0.1, 0.0, 0.2], "orientation_xyzw": [0.0, 0.0, 0.0, 1.0]}, "approach_direction": {"frame_id": "camera_front", "unit": "unitless", "vector": [0.0, 0.0, -1.0]}, "score": 0.8, "confidence": 0.8, "provenance": ["artifact://scene-7/camera_front/derived/points"], "qualification": "proposed"}]}
    )
    assert result["status"] == "available"
    assert result["motion_authorized"] is False
    evaluator.release()


def test_profile_digest_mismatch_fails_before_worker_start(tmp_path):
    fixture = _fixture(tmp_path)
    profile = _profile(tmp_path, fixture)
    profile["fixture_sha256"] = "0" * 64
    with pytest.raises(ReadinessProfileError, match="sha256"):
        build_readiness_evaluator(profile)


def test_profile_rejects_symlink_fixture(tmp_path):
    fixture = _fixture(tmp_path)
    link = tmp_path / "link.json"
    link.symlink_to(fixture)
    profile = _profile(tmp_path, link)
    with pytest.raises(ReadinessProfileError, match="regular file"):
        build_readiness_evaluator(profile)


def test_profile_rejects_duplicate_fixture_argument(tmp_path):
    fixture = _fixture(tmp_path)
    profile = _profile(tmp_path, fixture)
    profile["worker"]["arguments"] = ["--fixture", str(fixture)]
    with pytest.raises(ReadinessProfileError, match="--fixture"):
        build_readiness_evaluator(profile)


def test_duplicate_fixture_case_identity_fails_before_worker_start(tmp_path):
    fixture = _fixture(tmp_path)
    value = json.loads(fixture.read_text(encoding="utf-8"))
    value["cases"].append(dict(value["cases"][0]))
    fixture.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    fixture.chmod(0o600)
    profile = _profile(tmp_path, fixture)
    profile["fixture_sha256"] = hashlib.sha256(fixture.read_bytes()).hexdigest()
    evaluator = build_readiness_evaluator(profile)
    with pytest.raises(ProcessWorkerError, match="duplicate case identity"):
        evaluator.evaluate(_request())
    evaluator.release()


def test_worker_identity_mismatch_fails_closed(tmp_path):
    fixture = _fixture(tmp_path, worker_id="fixture-worker/v1", prepared=_prepared())
    evaluator = build_readiness_evaluator(_profile(tmp_path, fixture))
    with pytest.raises(ReadinessProfileError, match="worker identity"):
        evaluator.evaluate(_request())
    evaluator.release()


def test_unknown_replay_case_returns_unavailable(tmp_path):
    fixture = _fixture(tmp_path)
    evaluator = build_readiness_evaluator(_profile(tmp_path, fixture))
    request = _request()
    request["scene_revision"] = "scene-other"
    request["observation_ref"] = "observation://scene-other/camera_front"
    request["candidate_set_ref"] = "candidate-set://scene-other/camera_front"
    result = evaluator.evaluate(request)
    assert result == {"prepared_candidates": (), "provider_available": False}
    evaluator.release()


def test_profile_loader_requires_absolute_regular_file(tmp_path):
    fixture = _fixture(tmp_path)
    profile_path = tmp_path / "profile.yaml"
    import yaml

    profile_path.write_text(yaml.safe_dump(_profile(tmp_path, fixture)), encoding="utf-8")
    assert load_readiness_profile(profile_path) == _profile(tmp_path, fixture)
    with pytest.raises(ReadinessProfileError, match="absolute"):
        load_readiness_profile("profile.yaml")
