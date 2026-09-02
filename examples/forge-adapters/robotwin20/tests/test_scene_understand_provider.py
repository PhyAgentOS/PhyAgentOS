from __future__ import annotations

import sys

import pytest
from PhyAgentOS.forge.tool_client import ForgeToolClient
from pick_place_workflow.fake_gateway import FakeGatewayTransport

from robotwin20_adapter import (
    RoboTwinSceneUnderstandingProvider,
    RoboTwinUnderstandingSnapshot,
)

OBSERVE_INPUT = {
    "observation_ref": "observation://scene-7/camera_front",
    "scene_revision": "scene-7",
    "frame_id": "camera_front",
    "calibration_ref": "calibration://front/v3",
    "freshness_ms": 0,
    "max_age_ms": 1000,
    "artifacts": [
        "artifact://obs-7/capture-1/rgb",
        "artifact://obs-7/capture-1/depth",
        "artifact://obs-7/capture-1/state",
    ],
}


class Inference:
    def __init__(self):
        self.requests = []

    def infer(self, request):
        self.requests.append(dict(request))
        return {
            "entities": [
                {
                    "entity_ref": "entity://red_block",
                    "category": "block",
                    "confidence": 0.94,
                    "provenance": ["artifact://obs-7/capture-1/rgb"],
                }
            ],
            "relations": [],
            "spatial_envelopes": [],
            "ambiguities": [],
        }


async def invoke(provider, arguments=OBSERVE_INPUT):
    observation_provider = type("Observation", (), {"observe": lambda self, sensor_ref: None})()
    transport = FakeGatewayTransport(
        observation_provider,
        understanding_provider=provider,
    )
    async with ForgeToolClient("http://fake", transport=transport) as client:
        response = await client.invoke_query_tool("scene.understand", arguments)
    return response["data"]


@pytest.mark.asyncio
async def test_robotwin_understanding_provider_uses_only_observation_contract():
    inference = Inference()
    result = await invoke(RoboTwinSceneUnderstandingProvider(inference))

    assert result["status"] == "available"
    assert result["observation_ref"] == OBSERVE_INPUT["observation_ref"]
    assert result["entities"][0]["entity_ref"] == "entity://red_block"
    assert inference.requests == [OBSERVE_INPUT]


@pytest.mark.asyncio
async def test_stale_observation_is_rejected_before_inference():
    inference = Inference()
    result = await invoke(
        RoboTwinSceneUnderstandingProvider(inference),
        {**OBSERVE_INPUT, "freshness_ms": 1001},
    )

    assert result["status"] == "stale"
    assert result["error"]["code"] == "stale_observation"
    assert inference.requests == []


@pytest.mark.asyncio
async def test_provider_specific_fields_fail_closed_through_tool_api():
    class BadInference:
        def infer(self, request):
            return {"entities": [], "relations": [], "simulator_actor_id": "actor-1"}

    result = await invoke(RoboTwinSceneUnderstandingProvider(BadInference()))
    assert result["status"] == "unavailable"
    assert result["error"]["code"] == "understanding_provider_error"


@pytest.mark.asyncio
async def test_claim_provenance_must_bind_to_requested_observation_artifacts():
    class UnboundInference:
        def infer(self, request):
            return {
                "entities": [
                    {
                        "entity_ref": "entity://red_block",
                        "category": "block",
                        "confidence": 0.94,
                        "provenance": ["artifact://different-observation/rgb"],
                    }
                ],
                "relations": [],
                "spatial_envelopes": [],
                "ambiguities": [],
            }

    result = await invoke(RoboTwinSceneUnderstandingProvider(UnboundInference()))
    assert result["status"] == "invalid"
    assert result["error"]["code"] == "invalid_entity_claim"


def test_paos_import_boundary_remains_clean():
    forbidden = {"robotwin", "sapien", "torch", "ultralytics", "dora", "openai"}
    assert not any(name.split(".", 1)[0].lower() in forbidden for name in sys.modules)


def test_adapter_returns_runtime_independent_mapping_type():
    assert RoboTwinUnderstandingSnapshot is dict
