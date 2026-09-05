from __future__ import annotations

import sys

import pytest

from robotwin20_adapter import (
    PROFILE_SCHEMA_VERSION,
    PerceptionProfileError,
    SingleViewPerceptionInference,
    build_single_view_perception,
    load_perception_profile,
)


def _profile(tmp_path):
    script = tmp_path / "worker.py"
    script.write_text("pass\n", encoding="utf-8")
    worker = {
        "python": "${WORKER_PYTHON}",
        "script": "${WORKER_SCRIPT}",
        "arguments": [],
        "cwd": "${WORKER_ROOT}",
        "environment": {"PYTHONUNBUFFERED": "1"},
        "startup_timeout_s": 2,
        "request_timeout_s": 3,
        "shutdown_timeout_s": 1,
    }
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "artifact_root": "${ARTIFACT_ROOT}",
        "worker_artifact_root": "${ARTIFACT_ROOT}/workers",
        "depth_scale_to_m": 0.001,
        "max_points": 100,
        "proposal_worker": dict(worker),
        "segmentation_worker": dict(worker),
    }, {
        "WORKER_PYTHON": sys.executable,
        "WORKER_SCRIPT": str(script),
        "WORKER_ROOT": str(tmp_path),
        "ARTIFACT_ROOT": str(tmp_path / "artifacts"),
    }


def test_profile_builds_composition_without_starting_model_workers(tmp_path):
    profile, environment = _profile(tmp_path)
    composition = build_single_view_perception(lambda request: {}, profile, environ=environment)
    assert isinstance(composition, SingleViewPerceptionInference)


def test_profile_requires_all_environment_bindings(tmp_path):
    profile, environment = _profile(tmp_path)
    environment.pop("WORKER_SCRIPT")
    with pytest.raises(PerceptionProfileError, match="WORKER_SCRIPT"):
        build_single_view_perception(lambda request: {}, profile, environ=environment)


def test_yaml_profile_loader_is_explicit_and_bounded(tmp_path):
    profile, _ = _profile(tmp_path)
    path = tmp_path / "profile.yaml"
    import yaml

    path.write_text(yaml.safe_dump(profile), encoding="utf-8")
    assert load_perception_profile(path.resolve()) == profile
    with pytest.raises(PerceptionProfileError, match="absolute"):
        load_perception_profile("profile.yaml")


def test_yaml_profile_loader_rejects_duplicate_keys(tmp_path):
    path = tmp_path / "duplicate.yaml"
    path.write_text("schema_version: first\nschema_version: second\n", encoding="utf-8")

    with pytest.raises(PerceptionProfileError, match="duplicate YAML keys"):
        load_perception_profile(path.resolve())
