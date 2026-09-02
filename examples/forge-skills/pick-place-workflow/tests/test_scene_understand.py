import pytest
from PhyAgentOS.forge.tool_client import ForgeToolClient

from pick_place_workflow.fake_gateway import FakeGatewayTransport
from pick_place_workflow.understanding import (
    SceneUnderstandingEndpoint,
    UnderstandingSnapshot,
)


def request_payload(**overrides):
    value = {
        "observation_ref": "observation://scene-7/camera_front",
        "scene_revision": "scene-7",
        "frame_id": "camera_front",
        "calibration_ref": "calibration://front/v3",
        "freshness_ms": 25,
        "max_age_ms": 100,
        "artifacts": ["artifact://obs-7/rgb"],
    }
    value.update(overrides)
    return value


def understanding_snapshot(**overrides):
    value = {
        "entities": (
            {
                "entity_ref": "entity://bottle-1",
                "category": "container",
                "confidence": 0.92,
                "provenance": ["artifact://obs-7/rgb"],
            },
        ),
        "relations": (),
        "spatial_envelopes": (
            {
                "entity_ref": "entity://bottle-1",
                "frame_id": "camera_front",
                "unit": "m",
                "min_xyz_m": [0.1, -0.2, 0.0],
                "max_xyz_m": [0.2, -0.1, 0.3],
                "confidence": 0.8,
                "provenance": ["artifact://obs-7/rgb"],
            },
        ),
        "ambiguities": (),
    }
    value.update(overrides)
    return UnderstandingSnapshot(**value)


class Provider:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def understand(self, request):
        self.calls += 1
        return self.result


@pytest.mark.asyncio
async def test_understanding_query_is_bound_to_observation_and_provider_neutral():
    provider = Provider(understanding_snapshot())
    transport = FakeGatewayTransport(
        provider=type("Observation", (), {"observe": lambda self, sensor_ref: None})(),
        understanding_provider=provider,
    )
    async with ForgeToolClient("http://fake", transport=transport) as client:
        spec = await client.get_tool("scene.understand")
        context = await client.get_tool_context("scene.understand")
        result = await client.invoke_query_tool("scene.understand", request_payload())
    assert spec["data"]["semantics"] == "query"
    assert spec["data"]["input_schema"]["additionalProperties"] is False
    assert "observation_ref" in spec["data"]["input_schema"]["required"]
    assert context["data"]["motion_authorized"] is False
    assert result["data"]["status"] == "available"
    assert result["data"]["observation_ref"] == "observation://scene-7/camera_front"
    assert result["data"]["entities"][0]["provenance"] == ["artifact://obs-7/rgb"]
    assert [request.url.path for request in transport.requests] == [
        "/tools/scene.understand",
        "/tools/scene.understand/context",
        "/tools/scene.understand",
        "/tools/scene_understanding/understand:invoke",
    ]


def test_stale_observation_is_rejected_before_provider_call():
    provider = Provider(understanding_snapshot())
    endpoint = SceneUnderstandingEndpoint(provider)
    result = endpoint.invoke(request_payload(freshness_ms=101))
    assert result["status"] == "stale"
    assert result["error"]["code"] == "stale_observation"
    assert provider.calls == 0


@pytest.mark.parametrize(
    ("result", "code"),
    [
        (None, "understanding_unavailable"),
        (understanding_snapshot(entities=({"entity_ref": "bad"},)), "invalid_entity_claim"),
        (
            understanding_snapshot(
                spatial_envelopes=(
                    {
                        "entity_ref": "entity://bottle-1",
                        "frame_id": "camera_front",
                        "unit": "m",
                        "min_xyz_m": [0.2, 0.0, 0.0],
                        "max_xyz_m": [0.1, 0.0, 0.0],
                        "confidence": 0.8,
                        "provenance": ["artifact://obs-7/rgb"],
                    },
                )
            ),
            "invalid_spatial_envelope",
        ),
    ],
)
def test_provider_failures_are_explicit(result, code):
    output = SceneUnderstandingEndpoint(Provider(result)).invoke(request_payload())
    assert output["error"]["code"] == code


def test_missing_calibration_and_unknown_provider_fields_fail_closed():
    provider = Provider(understanding_snapshot())
    endpoint = SceneUnderstandingEndpoint(provider)
    missing = endpoint.invoke(request_payload(calibration_ref=""))
    unknown = endpoint.invoke({**request_payload(), "provider": "robotwin"})
    assert missing["error"]["code"] == "missing_calibration"
    assert unknown["error"]["code"] == "invalid_arguments"
    assert provider.calls == 0
