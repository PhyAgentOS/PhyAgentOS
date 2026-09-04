from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "runtime" / "robotwin_backend.py"
spec = importlib.util.spec_from_file_location("robotwin_backend", MODULE_PATH)
assert spec and spec.loader
backend_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = backend_module
spec.loader.exec_module(backend_module)


def test_runtime_profile_rejects_unsafe_provider_identifiers(tmp_path):
    profile = backend_module.RoboTwinRuntimeProfile(
        runtime_root=tmp_path,
        artifact_root=tmp_path / "artifacts",
        task_name="../escape",
    )
    with pytest.raises(backend_module.RoboTwinRuntimeError, match="task_name"):
        profile.validate()


def test_runtime_profile_requires_external_absolute_artifacts(tmp_path):
    profile = backend_module.RoboTwinRuntimeProfile(
        runtime_root=tmp_path,
        artifact_root=Path("relative-artifacts"),
    )
    with pytest.raises(backend_module.RoboTwinRuntimeError, match="artifact_root"):
        profile.validate()


def test_runtime_profile_rejects_artifacts_inside_runtime_checkout(tmp_path):
    profile = backend_module.RoboTwinRuntimeProfile(
        runtime_root=tmp_path,
        artifact_root=tmp_path / "artifacts",
    )
    with pytest.raises(backend_module.RoboTwinRuntimeError, match="outside runtime_root"):
        profile.validate()


def test_runtime_profile_rejects_artifacts_inside_forbidden_paos_root(tmp_path):
    paos_root = tmp_path / "paos"
    profile = backend_module.RoboTwinRuntimeProfile(
        runtime_root=tmp_path / "runtime",
        artifact_root=paos_root / "artifacts",
        forbidden_roots=(paos_root,),
    )
    profile.runtime_root.mkdir()
    with pytest.raises(backend_module.RoboTwinRuntimeError, match="forbidden root"):
        profile.validate()


def test_public_camera_refs_do_not_include_truth_channels():
    assert set(backend_module._CAMERA_REFS) == {
        "camera/head",
        "camera/front",
        "camera/left_wrist",
        "camera/right_wrist",
    }
    assert all("segmentation" not in name for name in backend_module._CAMERA_REFS)


def test_runtime_calls_use_external_root_without_leaking_process_cwd(tmp_path):
    backend = object.__new__(backend_module.RoboTwinSensorBackend)
    backend.profile = backend_module.RoboTwinRuntimeProfile(
        runtime_root=tmp_path / "RoboTwin",
        artifact_root=tmp_path / "artifacts",
    )
    backend.profile.runtime_root.mkdir()
    original = Path.cwd()
    with backend._runtime_cwd():
        assert Path.cwd() == backend.profile.runtime_root
    assert Path.cwd() == original


def test_cli_emits_one_json_document_and_redirects_runtime_stdout(tmp_path, monkeypatch, capsys):
    class Backend:
        def __init__(self, profile):
            self.profile = profile

        def reset(self, *, seed):
            print("third-party runtime warning")

        def capture_sensors(self, sensor_ref):
            return backend_module.SensorCapture(
                captured_at=backend_module.datetime.now(backend_module.timezone.utc),
                scene_revision="scene-1",
                frame_id="head_camera",
                calibration_ref="artifact://scene-1/capture/calibration",
                artifacts=(),
            )

        def close(self):
            return None

    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    artifact_root = tmp_path / "artifacts"
    monkeypatch.setattr(backend_module, "RoboTwinSensorBackend", Backend)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "robotwin_backend.py",
            "--runtime-root", str(runtime_root),
            "--artifact-root", str(artifact_root),
        ],
    )
    assert backend_module.main() == 0
    captured = capsys.readouterr()
    import json

    assert json.loads(captured.out)["scene_revision"] == "scene-1"
    assert "third-party runtime warning" in captured.err
