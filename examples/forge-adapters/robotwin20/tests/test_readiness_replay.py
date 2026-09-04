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
    ReadinessReplayArtifactError,
    build_readiness_evaluator,
    load_readiness_profile,
    load_readiness_replay_artifact,
    readiness_replay_artifact_id,
)

WORKER = Path(__file__).parents[1] / "runtime" / "readiness_replay_worker.py"
BINDING = {
    "robot_identity": "franka-panda",
    "gripper_identity": "panda-gripper",
    "embodiment_topology": "two-single-arm",
    "planner_profile": "curobo",
    "profile_digest": "a" * 64,
}


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
    prepared_items = [] if prepared is None else [prepared]
    value = {
        "schema_version": "paos-robotwin20-readiness-replay/v1",
        "worker_id": worker_id,
        "motion_authorized": False,
        "embodiment_binding": BINDING,
        "cases": [
            {
                "observation_ref": "observation://scene-7/camera_front",
                "scene_revision": "scene-7",
                "frame_id": "camera_front",
                "calibration_ref": "calibration://front/v3",
                "candidate_set_ref": "candidate-set://scene-7/camera_front",
                "candidate_refs": [["candidate://bottle-1/1", "entity://bottle-1"]],
                "prepared_candidates": prepared_items,
            }
        ],
    }
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    path.chmod(0o600)
    manifest = path.with_name("evidence.json")
    evidence = {
        "schema_version": "paos-robotwin20-readiness-evidence/v1",
        "worker_id": worker_id,
        "motion_authorized": False,
        "embodiment_binding": BINDING,
        "artifacts": [
            {
                "artifact_ref": ref,
                "observation_ref": "observation://scene-7/camera_front",
                "scene_revision": "scene-7",
                "frame_id": "camera_front",
                "candidate_set_ref": "candidate-set://scene-7/camera_front",
                "calibration_ref": "calibration://front/v3",
                "source": "provider://robotwin20/readiness-replay",
                "captured_at": "2026-09-04T12:00:00+00:00",
            }
            for ref in (prepared_items[0].get("evidence", []) if prepared_items else [])
        ],
    }
    manifest.write_text(json.dumps(evidence, sort_keys=True), encoding="utf-8")
    manifest.chmod(0o600)
    return path


def _profile(tmp_path: Path, fixture: Path, *, worker_id="robotwin20-readiness-replay/v1"):
    artifact = fixture.read_bytes()
    manifest = fixture.with_name("evidence.json")
    return {
        "schema_version": READINESS_PROFILE_SCHEMA_VERSION,
        "worker_id": worker_id,
        "fixture": str(fixture),
        "fixture_sha256": hashlib.sha256(artifact).hexdigest(),
        "evidence_manifest": str(manifest),
        "evidence_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "embodiment_binding": BINDING,
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


def test_record_replay_writes_immutable_canonical_artifact(tmp_path):
    fixture = _fixture(tmp_path, prepared=_prepared())
    evaluator = build_readiness_evaluator(_profile(tmp_path, fixture))
    path = (tmp_path / "replays" / "readiness.json").absolute()
    path.parent.mkdir()
    artifact = evaluator.record_replay(_request(), path)
    loaded = load_readiness_replay_artifact(path)
    assert loaded == artifact
    assert loaded["motion_authorized"] is False
    assert path.read_bytes().endswith(b"\n")
    evaluator.release()


def test_replay_artifact_refuses_divergent_overwrite_and_tampering(tmp_path):
    fixture = _fixture(tmp_path, prepared=_prepared())
    evaluator = build_readiness_evaluator(_profile(tmp_path, fixture))
    path = (tmp_path / "replay.json").absolute()
    artifact = evaluator.record_replay(_request(), path)
    original = path.read_bytes()
    changed = dict(artifact)
    changed["worker_id"] = "other-worker"
    changed["artifact_id"] = readiness_replay_artifact_id(changed)
    with pytest.raises(ReadinessReplayArtifactError, match="overwrite"):
        from robotwin20_adapter import write_readiness_replay_artifact
        write_readiness_replay_artifact(path, changed)
    path.write_bytes(original.replace(b'"provider_available":true', b'"provider_available":false'))
    with pytest.raises(ReadinessReplayArtifactError, match="digest|canonical"):
        load_readiness_replay_artifact(path)
    evaluator.release()


def test_replay_artifact_rejects_relative_path_and_naive_timestamp(tmp_path):
    fixture = _fixture(tmp_path, prepared=_prepared())
    evaluator = build_readiness_evaluator(_profile(tmp_path, fixture))
    artifact = evaluator.record_replay(_request(), (tmp_path / "replay.json").absolute())
    artifact["generated_at"] = "2026-09-04T12:00:00"
    artifact["artifact_id"] = readiness_replay_artifact_id(artifact)
    from robotwin20_adapter import write_readiness_replay_artifact
    with pytest.raises(ReadinessReplayArtifactError, match="timezone"):
        write_readiness_replay_artifact((tmp_path / "naive.json").absolute(), artifact)
    with pytest.raises(ReadinessReplayArtifactError, match="absolute"):
        write_readiness_replay_artifact("relative.json", evaluator.record_replay(_request(), (tmp_path / "other.json").absolute()))
    evaluator.release()


def test_record_replay_rejects_unavailable_projection(tmp_path):
    fixture = _fixture(tmp_path)
    evaluator = build_readiness_evaluator(_profile(tmp_path, fixture))
    request = _request()
    request.update(
        {
            "observation_ref": "observation://scene-8/camera_front",
            "scene_revision": "scene-8",
            "candidate_set_ref": "candidate-set://scene-8/camera_front",
        }
    )
    with pytest.raises(ReadinessProfileError, match="unavailable"):
        evaluator.record_replay(request, (tmp_path / "unavailable.json").absolute())
    evaluator.release()


def test_replay_artifact_rejects_symlink_and_permissive_existing_file(tmp_path):
    fixture = _fixture(tmp_path, prepared=_prepared())
    evaluator = build_readiness_evaluator(_profile(tmp_path, fixture))
    artifact = evaluator.record_replay(_request(), (tmp_path / "source.json").absolute())
    from robotwin20_adapter import write_readiness_replay_artifact
    link = (tmp_path / "link.json").absolute()
    link.symlink_to(tmp_path / "source.json")
    with pytest.raises(ReadinessReplayArtifactError, match="symlink"):
        write_readiness_replay_artifact(link, artifact)
    permissive = (tmp_path / "permissive.json").absolute()
    permissive.write_bytes((tmp_path / "source.json").read_bytes())
    permissive.chmod(0o666)
    with pytest.raises(ReadinessReplayArtifactError, match="writable"):
        load_readiness_replay_artifact(permissive)
    evaluator.release()


def test_profile_digest_mismatch_fails_before_worker_start(tmp_path):
    fixture = _fixture(tmp_path)
    profile = _profile(tmp_path, fixture)
    profile["fixture_sha256"] = "0" * 64
    with pytest.raises(ReadinessProfileError, match="sha256"):
        build_readiness_evaluator(profile)


def test_profile_evidence_manifest_digest_mismatch_fails_before_worker_start(tmp_path):
    fixture = _fixture(tmp_path)
    profile = _profile(tmp_path, fixture)
    profile["evidence_manifest_sha256"] = "0" * 64
    with pytest.raises(ReadinessProfileError, match="evidence_manifest sha256"):
        build_readiness_evaluator(profile)


def test_profile_rejects_symlink_fixture(tmp_path):
    fixture = _fixture(tmp_path)
    link = tmp_path / "link.json"
    link.symlink_to(fixture)
    profile = _profile(tmp_path, link)
    with pytest.raises(ReadinessProfileError, match="regular file"):
        build_readiness_evaluator(profile)


def test_profile_rejects_symlink_evidence_manifest(tmp_path):
    fixture = _fixture(tmp_path)
    manifest = fixture.with_name("evidence-link.json")
    manifest.symlink_to(fixture.with_name("evidence.json"))
    profile = _profile(tmp_path, fixture)
    profile["evidence_manifest"] = str(manifest)
    with pytest.raises(ReadinessProfileError, match="regular file"):
        build_readiness_evaluator(profile)


def test_profile_rejects_duplicate_fixture_argument(tmp_path):
    fixture = _fixture(tmp_path)
    profile = _profile(tmp_path, fixture)
    profile["worker"]["arguments"] = ["--fixture", str(fixture)]
    with pytest.raises(ReadinessProfileError, match="--fixture"):
        build_readiness_evaluator(profile)


def test_profile_rejects_duplicate_evidence_manifest_argument(tmp_path):
    fixture = _fixture(tmp_path)
    profile = _profile(tmp_path, fixture)
    profile["worker"]["arguments"] = ["--evidence-manifest", str(fixture.with_name("evidence.json"))]
    with pytest.raises(ReadinessProfileError, match="--evidence-manifest"):
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


def test_embodiment_binding_mismatch_fails_closed(tmp_path):
    fixture = _fixture(tmp_path, prepared=_prepared())
    profile = _profile(tmp_path, fixture)
    profile["embodiment_binding"] = {**BINDING, "robot_identity": "other-arm"}
    evaluator = build_readiness_evaluator(profile)
    with pytest.raises(ReadinessProfileError, match="embodiment binding"):
        evaluator.evaluate(_request())
    evaluator.release()


def test_profile_requires_complete_embodiment_binding(tmp_path):
    fixture = _fixture(tmp_path)
    profile = _profile(tmp_path, fixture)
    profile["embodiment_binding"] = {"robot_identity": "franka-panda"}
    with pytest.raises(ReadinessProfileError, match="binding fields"):
        build_readiness_evaluator(profile)


def test_missing_evidence_reference_fails_closed(tmp_path):
    prepared = _prepared()
    prepared["evidence"] = ["artifact://scene-7/camera_front/derived/missing"]
    fixture = _fixture(tmp_path, prepared=prepared)
    manifest = fixture.with_name("evidence.json")
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["artifacts"] = []
    manifest.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    manifest.chmod(0o600)
    profile = _profile(tmp_path, fixture)
    profile["evidence_manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    evaluator = build_readiness_evaluator(profile)
    with pytest.raises(ProcessWorkerError, match="evidence reference is missing"):
        evaluator.evaluate(_request())
    evaluator.release()


def test_evidence_identity_drift_fails_closed(tmp_path):
    fixture = _fixture(tmp_path, prepared=_prepared())
    manifest = fixture.with_name("evidence.json")
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["artifacts"][0]["calibration_ref"] = "calibration://front/v4"
    manifest.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    manifest.chmod(0o600)
    profile = _profile(tmp_path, fixture)
    profile["evidence_manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    evaluator = build_readiness_evaluator(profile)
    with pytest.raises(ProcessWorkerError, match="evidence identity is unbound"):
        evaluator.evaluate(_request())
    evaluator.release()


def test_naive_evidence_timestamp_fails_closed(tmp_path):
    fixture = _fixture(tmp_path, prepared=_prepared())
    manifest = fixture.with_name("evidence.json")
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["artifacts"][0]["captured_at"] = "2026-09-04T12:00:00"
    manifest.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    manifest.chmod(0o600)
    profile = _profile(tmp_path, fixture)
    profile["evidence_manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    evaluator = build_readiness_evaluator(profile)
    with pytest.raises(ProcessWorkerError, match="captured_at requires timezone"):
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
