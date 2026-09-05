from __future__ import annotations

import sys

import pytest

from robotwin20_adapter import (
    GRASP_PROFILE_SCHEMA_VERSION,
    GraspGenProposalProvider,
    GraspProfileError,
    build_grasp_provider,
    load_grasp_profile,
)


def _profile(tmp_path):
    script = tmp_path / "worker.py"
    script.write_text("pass\n", encoding="utf-8")
    return {
        "schema_version": GRASP_PROFILE_SCHEMA_VERSION,
        "artifact_root": "${ARTIFACT_ROOT}",
        "max_candidates": 12,
        "score_threshold": 0.02,
        "apply_nms": True,
        "nms_position_threshold_m": 0.005,
        "nms_approach_angle_deg": 10.0,
        "nms_closing_angle_deg": 10.0,
        "apply_model_collision": False,
        "worker": {
            "python": "${WORKER_PYTHON}",
            "script": "${WORKER_SCRIPT}",
            "arguments": ["--stdio-worker"],
            "cwd": "${WORKER_ROOT}",
            "environment": {"PYTHONUNBUFFERED": "1"},
            "startup_timeout_s": 2,
            "request_timeout_s": 3,
            "shutdown_timeout_s": 1,
        },
    }, {
        "WORKER_PYTHON": sys.executable,
        "WORKER_SCRIPT": str(script),
        "WORKER_ROOT": str(tmp_path),
        "ARTIFACT_ROOT": str(tmp_path / "artifacts"),
    }


def test_grasp_profile_builds_without_starting_worker(tmp_path):
    profile, environment = _profile(tmp_path)
    (tmp_path / "artifacts").mkdir()
    provider = build_grasp_provider(profile, environ=environment)
    assert isinstance(provider, GraspGenProposalProvider)


def test_grasp_profile_requires_external_bindings(tmp_path):
    profile, environment = _profile(tmp_path)
    (tmp_path / "artifacts").mkdir()
    environment.pop("WORKER_PYTHON")
    with pytest.raises(GraspProfileError, match="WORKER_PYTHON"):
        build_grasp_provider(profile, environ=environment)


def test_grasp_profile_loader_requires_absolute_file(tmp_path):
    profile, _ = _profile(tmp_path)
    import yaml

    path = tmp_path / "grasp.yaml"
    path.write_text(yaml.safe_dump(profile), encoding="utf-8")
    assert load_grasp_profile(path.resolve()) == profile
    with pytest.raises(GraspProfileError, match="absolute"):
        load_grasp_profile("grasp.yaml")
