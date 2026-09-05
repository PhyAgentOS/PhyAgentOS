from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PhyAgentOS.forge.tool_client import ForgeToolClient
from pick_place_workflow.fake_gateway import (
    FakeGatewayTransport,
    ObservationSnapshot,
)

from robotwin20_adapter import RoboTwin20Adapter, SensorArtifact, SensorCapture

MODULE_PATH = Path(__file__).parents[1] / "runtime" / "robotwin_backend.py"
spec = importlib.util.spec_from_file_location("robotwin_backend_integration", MODULE_PATH)
assert spec and spec.loader
backend_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = backend_module
spec.loader.exec_module(backend_module)

NOW = datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc)


class SensorBackend:
    def reset(self, *, seed=None):
        self.seed = seed

    def snapshot(self):
        return {"scene_revision": "scene-7"}

    def capture_sensors(self, sensor_ref):
        if sensor_ref != "sensor/front":
            return None
        return SensorCapture(
            captured_at=NOW,
            scene_revision="scene-7",
            frame_id="camera_front",
            calibration_ref="calibration://front/v3",
            artifacts=(
                SensorArtifact("artifact://obs-7/capture-1/rgb", "rgb", "image/jpeg"),
                SensorArtifact("artifact://obs-7/capture-1/depth", "depth", "application/numpy"),
                SensorArtifact("artifact://obs-7/capture-1/state", "state", "application/json"),
            ),
        )


class FakeProvider:
    def observe(self, sensor_ref):
        if sensor_ref != "sensor/front":
            return None
        return ObservationSnapshot(
            captured_at=NOW,
            scene_revision="scene-7",
            frame_id="camera_front",
            calibration_ref="calibration://front/v3",
            artifacts=(
                {"ref": "artifact://obs-7/capture-1/rgb", "kind": "rgb", "media_type": "image/jpeg"},
                {"ref": "artifact://obs-7/capture-1/depth", "kind": "depth", "media_type": "application/numpy"},
                {"ref": "artifact://obs-7/capture-1/state", "kind": "state", "media_type": "application/json"},
            ),
        )


async def invoke_scene_observe(provider):
    transport = FakeGatewayTransport(provider, now=NOW)
    async with ForgeToolClient("http://fake", transport=transport) as client:
        response = await client.invoke_query_tool(
            "scene.observe",
            {"sensor_ref": "sensor/front", "max_age_ms": 1000},
        )
    return response["data"]


@pytest.mark.asyncio
async def test_fake_gateway_and_robotwin_provider_return_identical_scene_observe_result():
    adapter = RoboTwin20Adapter(
        SensorBackend(),
        profile={"name": "robotwin20-test"},
    )
    adapter.reset(seed=0)
    robotwin_provider = backend_module.RoboTwinObservationProvider(adapter)

    fake_result = await invoke_scene_observe(FakeProvider())
    robotwin_result = await invoke_scene_observe(robotwin_provider)

    assert robotwin_result == fake_result
    assert robotwin_result == {
        "status": "available",
        "observation_ref": "observation://scene-7/camera_front",
        "captured_at": "2026-09-02T00:00:00Z",
        "scene_revision": "scene-7",
        "frame": {"frame_id": "camera_front", "unit": "m"},
        "calibration_ref": "calibration://front/v3",
        "freshness_ms": 0,
        "artifacts": [
            {"ref": "artifact://obs-7/capture-1/rgb", "kind": "rgb", "media_type": "image/jpeg"},
            {"ref": "artifact://obs-7/capture-1/depth", "kind": "depth", "media_type": "application/numpy"},
            {"ref": "artifact://obs-7/capture-1/state", "kind": "state", "media_type": "application/json"},
        ],
    }


def test_runtime_artifact_refs_can_include_capture_subpaths():
    adapter = RoboTwin20Adapter(SensorBackend(), profile={"name": "robotwin20-test"})
    adapter.reset(seed=0)
    snapshot = backend_module.RoboTwinObservationProvider(adapter).observe("sensor/front")
    assert snapshot is not None
    assert all(item["ref"].count("/") >= 4 for item in snapshot.artifacts)


def test_runtime_provider_snapshot_is_json_serializable():
    adapter = RoboTwin20Adapter(SensorBackend(), profile={"name": "robotwin20-test"})
    adapter.reset(seed=0)
    snapshot = backend_module.RoboTwinObservationProvider(adapter).observe("sensor/front")
    assert snapshot is not None
    assert snapshot.observation_ref == "observation://scene-7/camera_front"
    assert snapshot.artifacts[0]["kind"] == "rgb"
    serialized = backend_module._jsonable(asdict(snapshot))
    assert json.loads(json.dumps(serialized)) == serialized
    assert serialized["captured_at"] == "2026-09-02T00:00:00Z"
