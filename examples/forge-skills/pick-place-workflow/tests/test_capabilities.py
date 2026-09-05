from pathlib import Path

import pytest
import yaml
from PhyAgentOS.forge.capability_runtime.manipulation_capabilities import CapabilitySnapshotEndpoint
from PhyAgentOS.forge.tool_client import ForgeToolClient

from pick_place_workflow.fake_gateway import FakeGatewayTransport

REQUEST = {
    "scene_revision": "scene-7",
    "observation_ref": "observation://scene-7/camera_front",
    "calibration_ref": "artifact://scene-7/capture/calibration",
}


class Provider:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def describe(self, request):
        self.calls += 1
        return self.value


def test_capability_endpoint_fails_closed_on_binding_drift_and_provider_failure():
    class Raising:
        def describe(self, request):
            raise RuntimeError("backend down")

    assert CapabilitySnapshotEndpoint(Raising()).invoke(REQUEST)["error"]["code"] == "provider_unavailable"


def test_capability_contract_matches_published_spec():
    from PhyAgentOS.forge.capability_runtime.manipulation_capabilities import CAPABILITY_TOOL_SPEC

    path = Path(__file__).resolve().parents[1] / "contracts" / "manipulation.capabilities.tool.yaml"
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == CAPABILITY_TOOL_SPEC


@pytest.mark.asyncio
async def test_fake_gateway_discovers_and_queries_no_motion_capability_snapshot():
    transport = FakeGatewayTransport(type("Observation", (), {"observe": lambda self, sensor_ref: None})())
    async with ForgeToolClient("http://fake", transport=transport) as client:
        spec = await client.get_tool("manipulation.capabilities")
        result = await client.invoke_query_tool("manipulation.capabilities", REQUEST)
    assert spec["data"]["semantics"] == "query"
    assert result["data"]["status"] == "available"
    assert result["data"]["motion_authorized"] is False
    assert len(result["data"]["arms"]) == 2
