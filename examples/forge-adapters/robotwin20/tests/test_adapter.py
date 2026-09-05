from __future__ import annotations

from datetime import datetime, timezone

import pytest

from robotwin20_adapter import (
    AdapterConfigurationError,
    AdapterSensorError,
    RoboTwin20Adapter,
    RoboTwinObservationSource,
    SensorArtifact,
    SensorCapture,
)


class Backend:
    def __init__(self, capture):
        self.capture_value = capture
        self.reset_seeds = []

    def reset(self, *, seed=None):
        self.reset_seeds.append(seed)

    def capture_sensors(self, sensor_ref):
        return self.capture_value

    def snapshot(self):
        return {"scene_revision": "scene-1", "actors": ["must-not-leak"]}


def capture(**overrides):
    value = {
        "captured_at": datetime(2026, 9, 2, tzinfo=timezone.utc),
        "scene_revision": "scene-1",
        "frame_id": "camera_front",
        "calibration_ref": "calibration://front/v1",
        "artifacts": [
            {"ref": "artifact://scene-1/rgb", "kind": "rgb", "media_type": "image/jpeg"},
            {"ref": "artifact://scene-1/depth", "kind": "depth", "media_type": "image/png"},
            {"ref": "artifact://scene-1/state", "kind": "state", "media_type": "application/json"},
        ],
    }
    value.update(overrides)
    return value


def test_adapter_requires_reset_and_returns_only_sanitized_snapshot():
    backend = Backend(capture())
    adapter = RoboTwin20Adapter(backend, profile={"name": "robotwin20-test", "asset_root": "/external/assets"})
    with pytest.raises(AdapterSensorError, match="not been reset"):
        adapter.snapshot()
    adapter.reset(seed=7)
    assert backend.reset_seeds == [7]
    assert adapter.snapshot() == {
        "profile": "robotwin20-test",
        "scene_revision": "scene-1",
        "status": "ready",
    }


def test_observation_source_exposes_camera_depth_state_only():
    adapter = RoboTwin20Adapter(Backend(capture()), profile={"name": "robotwin20-test"})
    adapter.reset()
    source = RoboTwinObservationSource(adapter)
    result = source.capture({"sensor_ref": "camera/front"})
    assert result["frame_id"] == "camera_front"
    assert {item["kind"] for item in result["artifacts"]} == {"rgb", "depth", "state"}
    assert "actors" not in result
    assert "segmentation" not in result


@pytest.mark.parametrize(
    "overrides",
    [
        {"calibration_ref": None},
        {"artifacts": [{"ref": "artifact://scene-1/rgb", "kind": "rgb", "media_type": "image/jpeg"}]},
        {"artifacts": [{"ref": "actor://scene-1/pose", "kind": "state", "media_type": "application/json"}]},
    ],
)
def test_missing_or_ground_truth_like_sensor_artifacts_fail_closed(overrides):
    adapter = RoboTwin20Adapter(Backend(capture(**overrides)), profile={"name": "robotwin20-test"})
    adapter.reset()
    with pytest.raises(AdapterSensorError):
        adapter.capture("camera/front")
    assert RoboTwinObservationSource(adapter).capture({"sensor_ref": "camera/front"}) is None


def test_sensor_capture_dataclass_is_supported():
    value = capture()
    typed = SensorCapture(
        captured_at=value["captured_at"],
        scene_revision=value["scene_revision"],
        frame_id=value["frame_id"],
        calibration_ref=value["calibration_ref"],
        artifacts=tuple(SensorArtifact(**item) for item in value["artifacts"]),
    )
    adapter = RoboTwin20Adapter(Backend(typed), profile={"name": "robotwin20-test"})
    adapter.reset()
    assert adapter.capture("camera/front").scene_revision == "scene-1"


def test_invalid_profile_is_rejected():
    with pytest.raises(AdapterConfigurationError):
        RoboTwin20Adapter(Backend(capture()), profile={})
