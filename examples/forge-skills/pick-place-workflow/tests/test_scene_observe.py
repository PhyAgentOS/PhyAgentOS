from datetime import datetime, timezone

import pytest
from PhyAgentOS.forge.tool_client import ForgeToolClient

from pick_place_workflow.fake_gateway import (
    TOOL_SPEC,
    FakeGatewayTransport,
    ObservationSnapshot,
    SceneObservationEndpoint,
)


class FixtureProvider:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def observe(self, sensor_ref):
        return self.snapshot if sensor_ref == "sensor/front" else None


def snapshot(**overrides):
    value = {
        "captured_at": datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc),
        "scene_revision": "scene-7",
        "frame_id": "camera_front",
        "calibration_ref": "calibration://front/v3",
        "artifacts": ({"ref": "artifact://obs-7/rgb", "kind": "rgb", "media_type": "image/jpeg"},),
    }
    value.update(overrides)
    return ObservationSnapshot(**value)


def test_public_contract_is_provider_neutral_and_endpoint_is_no_motion():
    serialized = repr(TOOL_SPEC).lower()
    assert "robotwin" not in serialized
    assert "sapien" not in serialized
    assert "task_name" not in serialized
    assert "embodiment" not in serialized
    endpoint = SceneObservationEndpoint(
        FixtureProvider(snapshot()),
        now=datetime(2026, 9, 1, 0, 0, 0, 500000, tzinfo=timezone.utc),
    )
    result = endpoint.invoke({"sensor_ref": "sensor/front", "max_age_ms": 1000})
    assert result["status"] == "available"


async def query(
    provider,
    arguments,
    *,
    now=datetime(2026, 9, 1, 0, 0, 0, 500000, tzinfo=timezone.utc),
):
    transport = FakeGatewayTransport(provider, now=now)
    async with ForgeToolClient("http://fake", transport=transport) as client:
        spec = await client.get_tool("scene.observe")
        context = await client.get_tool_context("scene.observe")
        result = await client.invoke_query_tool("scene.observe", arguments)
    return spec, context, result, transport


@pytest.mark.asyncio
async def test_query_discovery_context_and_success():
    spec, context, result, transport = await query(
        FixtureProvider(snapshot()), {"sensor_ref": "sensor/front", "max_age_ms": 1000}
    )
    assert spec["data"]["semantics"] == "query"
    assert spec["data"]["endpoint_id"] == "scene_observation"
    assert context["data"]["motion_authorized"] is False
    assert result["data"]["status"] == "available"
    assert result["data"]["observation_ref"] == "observation://scene-7/camera_front"
    assert result["data"]["freshness_ms"] == 500
    assert result["data"]["artifacts"][0]["ref"].startswith("artifact://")
    assert [request.url.path for request in transport.requests] == [
        "/tools/scene.observe",
        "/tools/scene.observe/context",
        "/tools/scene.observe",
        "/tools/scene_observation/observe:invoke",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("snapshot_overrides", "arguments", "status", "code"),
    [
        (
            {"calibration_ref": None},
            {"sensor_ref": "sensor/front", "max_age_ms": 1000},
            "unavailable",
            "missing_calibration",
        ),
        (
            {"captured_at": datetime(2026, 8, 31, 23, 59, tzinfo=timezone.utc)},
            {"sensor_ref": "sensor/front", "max_age_ms": 100},
            "stale",
            "stale_observation",
        ),
        (
            {"sensor_available": False},
            {"sensor_ref": "sensor/front", "max_age_ms": 1000},
            "unavailable",
            "sensor_unavailable",
        ),
        (
            {"artifacts": ({"ref": "../escape", "kind": "rgb", "media_type": "image/jpeg"},)},
            {"sensor_ref": "sensor/front", "max_age_ms": 1000},
            "invalid",
            "invalid_artifact_ref",
        ),
    ],
)
async def test_fail_closed_observations(snapshot_overrides, arguments, status, code):
    _, _, result, _ = await query(FixtureProvider(snapshot(**snapshot_overrides)), arguments)
    assert result["data"]["status"] == status
    assert result["data"]["error"]["code"] == code


@pytest.mark.asyncio
async def test_invalid_arguments_are_rejected_without_provider_call():
    class NoCall:
        def observe(self, sensor_ref):
            raise AssertionError("provider must not be called")

    _, _, result, _ = await query(
        NoCall(),
        {"sensor_ref": "sensor/front", "max_age_ms": 1, "provider": "robotwin"},
    )
    assert result["data"]["status"] == "invalid"
    assert result["data"]["error"]["code"] == "invalid_arguments"
