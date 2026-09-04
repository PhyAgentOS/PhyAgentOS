from pathlib import Path

import pytest
import yaml
from PhyAgentOS.forge.tool_client import ForgeToolAPIError, ForgeToolClient

from pick_place_workflow.fake_gateway import FakeGatewayTransport
from pick_place_workflow.object_acquire import (
    ACQUIRE_TOOL_ID,
    ACQUIRE_TOOL_SPEC,
    AcquireSnapshot,
    ObjectAcquireEndpoint,
)

_FORBIDDEN_TOKENS = (
    "robotwin",
    "sapien",
    "task_name",
    "task_config",
    "embodiment",
    "seed",
    "xpolicylab",
    "eval_policy",
    "check_success",
)


def request_payload(**overrides):
    value = {
        "observation_ref": "observation://scene-7/camera_front",
        "scene_revision": "scene-7",
        "frame_id": "camera_front",
        "calibration_ref": "calibration://front/v3",
        "freshness_ms": 25,
        "max_age_ms": 100,
        "candidate_set_ref": "candidate-set://scene-7/camera_front",
        "preparation_ref": "preparation://scene-7/camera_front",
        "candidate_ref": "candidate://bottle-1/1",
        "entity_ref": "entity://bottle-1",
    }
    value.update(overrides)
    return value


def successful_snapshot(**overrides):
    value = {
        "capability_phase": "hold",
        "status": "succeeded",
        "failure_owner": None,
        "failure_code": None,
        "world_change_started": True,
        "outcome_known": True,
        "evidence_availability": "partial",
        "artifact_refs": ("artifact://acquire-7/settlement",),
        "bounded_metric_names": ("lift_height", "gripper_closure"),
    }
    value.update(overrides)
    return AcquireSnapshot(**value)


class Provider:
    def __init__(self, result):
        self.result = result
        self.calls = 0
        self.requests = []

    def acquire(self, request):
        self.calls += 1
        self.requests.append(request)
        return self.result


class NoCall:
    def acquire(self, request):
        raise AssertionError("provider must not be called")


class RaisingProvider:
    def acquire(self, request):
        raise RuntimeError("provider backend failure")


def _observation_stub():
    return type("Observation", (), {"observe": lambda self, sensor_ref: None})()


def test_action_spec_is_strict_provider_neutral_and_keeps_phases_internal():
    assert ACQUIRE_TOOL_SPEC["semantics"] == "action"
    assert ACQUIRE_TOOL_SPEC["endpoint_id"] == "object_acquisition"
    assert ACQUIRE_TOOL_SPEC["operation"] == "acquire"
    assert ACQUIRE_TOOL_SPEC["max_concurrency"] == 1
    input_schema = ACQUIRE_TOOL_SPEC["input_schema"]
    assert input_schema["additionalProperties"] is False
    assert "preparation_ref" in input_schema["required"]
    assert "candidate_ref" in input_schema["required"]
    assert not {"approach", "contact", "close", "lift", "hold"} & set(input_schema["properties"])
    assert ACQUIRE_TOOL_SPEC["unknown_semantics"] == "terminal_for_accounting_not_physical_stop"
    assert ACQUIRE_TOOL_SPEC["cancellation"] == "supported_via_common_cancel_route"
    blob = repr(ACQUIRE_TOOL_SPEC).lower()
    assert not any(token in blob for token in _FORBIDDEN_TOKENS)


def test_contract_yaml_matches_the_published_tool_spec():
    contract_path = Path(__file__).resolve().parents[1] / "contracts" / "object.acquire.tool.yaml"
    assert yaml.safe_load(contract_path.read_text(encoding="utf-8")) == ACQUIRE_TOOL_SPEC


@pytest.mark.asyncio
async def test_action_discovery_context_admission_pending_and_terminal_result():
    provider = Provider(successful_snapshot(pending_polls=1))
    transport = FakeGatewayTransport(_observation_stub(), acquire_provider=provider)
    async with ForgeToolClient("http://fake", transport=transport) as client:
        tools = await client.list_tools()
        spec = await client.get_tool(ACQUIRE_TOOL_ID)
        context = await client.get_tool_context(ACQUIRE_TOOL_ID)
        admitted = await client.invoke_action(ACQUIRE_TOOL_ID, request_payload(), caller_id="paos:test")
        invocation_id = admitted["data"]["invocation_id"]
        pending = await client.invocation_result(invocation_id)
        terminal = await client.invocation_result(invocation_id)
    assert [item["tool_id"] for item in tools["data"]["tools"]] == [
        "scene.observe",
        "scene.understand",
        "grasp.propose",
        "manipulation.prepare",
        "object.acquire",
        "object.place",
    ]
    assert spec["data"]["semantics"] == "action"
    assert context["data"] == {
        "ready": True,
        "binding_error": None,
        "max_concurrency": 1,
        "observation_frame": "observation",
        "unit": "m",
        "orientation_convention": "candidate-bound",
        "motion_authorized": False,
        "cancellation": "supported_via_common_cancel_route",
        "unknown_semantics": "terminal_for_accounting_not_physical_stop",
    }
    assert admitted["data"]["phase"] == "accepted"
    assert admitted["data"]["invocation_id"].startswith("invocation://object-acquire/")
    assert admitted["data"]["attempt_id"].startswith("attempt://object-acquire/")
    assert pending["data"]["phase"] == "running"
    data = terminal["data"]
    assert data["phase"] == "completed"
    assert data["invocation_id"] == invocation_id
    assert data["result"]["status"] == "succeeded"
    assert data["result"]["candidate_ref"] == "candidate://bottle-1/1"
    assert data["result"]["capability_outcome_summary"] == {
        "version": "capability_outcome_summary_v1",
        "capability_phase": "hold",
        "status": "succeeded",
        "failure_owner": None,
        "failure_code": None,
        "world_change_started": True,
        "outcome_known": True,
        "evidence_availability": "partial",
        "artifact_refs": ["artifact://acquire-7/settlement"],
        "bounded_metric_names": ["lift_height", "gripper_closure"],
    }
    assert provider.calls == 1
    assert provider.requests == [request_payload()]
    paths = [request.url.path for request in transport.requests]
    assert paths[:5] == [
        "/tools",
        "/tools/object.acquire",
        "/tools/object.acquire/context",
        "/tools/object.acquire:invoke",
        paths[4],
    ]
    assert all("object_acquisition/acquire:invoke" not in path for path in paths)
    assert all(not path.startswith("/sessions/") for path in paths)


@pytest.mark.asyncio
async def test_query_client_rejects_the_action_without_a_query_execution_route():
    transport = FakeGatewayTransport(_observation_stub(), acquire_provider=Provider(successful_snapshot()))
    async with ForgeToolClient("http://fake", transport=transport) as client:
        with pytest.raises(ForgeToolAPIError, match="is not a Query"):
            await client.invoke_query_tool(ACQUIRE_TOOL_ID, request_payload())
    assert [request.url.path for request in transport.requests] == ["/tools/object.acquire"]


@pytest.mark.parametrize(
    ("arguments", "status_code", "code"),
    [
        (request_payload(freshness_ms=101), 409, "stale_observation"),
        (request_payload(calibration_ref=""), 422, "missing_calibration"),
        (request_payload(preparation_ref="preparation://scene-8/camera_front"), 400, "invalid_preparation_binding"),
        (request_payload(candidate_ref="candidate://cup-1/1"), 400, "invalid_candidate_entity_binding"),
        ({**request_payload(), "phase": "lift"}, 400, "invalid_arguments"),
        ({**request_payload(), "task_name": "pick"}, 400, "invalid_arguments"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_admission_is_rejected_before_provider_or_identity(arguments, status_code, code):
    transport = FakeGatewayTransport(_observation_stub(), acquire_provider=NoCall())
    async with ForgeToolClient("http://fake", transport=transport) as client:
        with pytest.raises(ForgeToolAPIError) as excinfo:
            await client.invoke_action(ACQUIRE_TOOL_ID, arguments)
    assert excinfo.value.status_code == status_code
    assert excinfo.value.error_code == code
    assert transport.invocations == {}


@pytest.mark.asyncio
async def test_unavailable_and_raising_provider_fail_closed_without_admission():
    for provider, code in ((Provider(None), "acquire_unavailable"), (RaisingProvider(), "acquire_provider_error")):
        transport = FakeGatewayTransport(_observation_stub(), acquire_provider=provider)
        async with ForgeToolClient("http://fake", transport=transport) as client:
            with pytest.raises(ForgeToolAPIError) as excinfo:
                await client.invoke_action(ACQUIRE_TOOL_ID, request_payload())
        assert excinfo.value.status_code == 503
        assert excinfo.value.error_code == code
        assert transport.invocations == {}


@pytest.mark.asyncio
async def test_unconfigured_provider_is_unready_and_rejects_admission():
    transport = FakeGatewayTransport(_observation_stub())
    async with ForgeToolClient("http://fake", transport=transport) as client:
        context = await client.get_tool_context(ACQUIRE_TOOL_ID)
        with pytest.raises(ForgeToolAPIError) as excinfo:
            await client.invoke_action(ACQUIRE_TOOL_ID, request_payload())
    assert context["data"]["ready"] is False
    assert context["data"]["binding_error"] == "object acquisition provider is unavailable"
    assert excinfo.value.status_code == 503


@pytest.mark.asyncio
async def test_concurrency_rejection_precedes_second_provider_call():
    provider = Provider(successful_snapshot(pending_polls=2))
    transport = FakeGatewayTransport(_observation_stub(), acquire_provider=provider)
    async with ForgeToolClient("http://fake", transport=transport) as client:
        await client.invoke_action(ACQUIRE_TOOL_ID, request_payload())
        with pytest.raises(ForgeToolAPIError) as excinfo:
            await client.invoke_action(ACQUIRE_TOOL_ID, request_payload(candidate_ref="candidate://bottle-1/2"))
    assert excinfo.value.status_code == 409
    assert excinfo.value.error_code == "concurrency_exhausted"
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_cancel_acceptance_does_not_claim_stop_until_terminal_result():
    transport = FakeGatewayTransport(_observation_stub(), acquire_provider=Provider(successful_snapshot(pending_polls=2)))
    async with ForgeToolClient("http://fake", transport=transport) as client:
        admitted = await client.invoke_action(ACQUIRE_TOOL_ID, request_payload())
        invocation_id = admitted["data"]["invocation_id"]
        cancelled = await client.cancel_invocation(invocation_id)
        terminal = await client.invocation_result(invocation_id)
    assert cancelled["data"] == {"invocation_id": invocation_id, "cancel_requested": True}
    assert terminal["data"]["phase"] == "cancelled"
    summary = terminal["data"]["result"]["capability_outcome_summary"]
    assert summary["status"] == "cancelled"
    assert summary["failure_owner"] == "operator"
    assert summary["failure_code"] == "cancelled_by_operator"


@pytest.mark.asyncio
async def test_unknown_result_remains_explicitly_physically_uncertain():
    snapshot = successful_snapshot(
        capability_phase="lift",
        status="unknown",
        failure_owner="execution",
        failure_code="remote_state_unknown",
        outcome_known=False,
        evidence_availability="partial",
    )
    transport = FakeGatewayTransport(_observation_stub(), acquire_provider=Provider(snapshot))
    async with ForgeToolClient("http://fake", transport=transport) as client:
        admitted = await client.invoke_action(ACQUIRE_TOOL_ID, request_payload())
        terminal = await client.invocation_result(admitted["data"]["invocation_id"])
    assert terminal["data"]["phase"] == "unknown"
    summary = terminal["data"]["result"]["capability_outcome_summary"]
    assert summary["world_change_started"] is True
    assert summary["outcome_known"] is False
    assert summary["status"] == "unknown"


@pytest.mark.parametrize(
    "snapshot",
    [
        successful_snapshot(status="running"),
        successful_snapshot(status="failed", failure_owner=None, failure_code="planner_rejected"),
        successful_snapshot(status="failed", failure_owner="planner", failure_code=None),
        successful_snapshot(status="unknown", outcome_known=True, failure_owner="execution", failure_code="x"),
        successful_snapshot(evidence_availability="complete", artifact_refs=()),
        successful_snapshot(bounded_metric_names=("bad-metric",)),
    ],
)
@pytest.mark.asyncio
async def test_malformed_provider_summary_fails_closed(snapshot):
    transport = FakeGatewayTransport(_observation_stub(), acquire_provider=Provider(snapshot))
    async with ForgeToolClient("http://fake", transport=transport) as client:
        with pytest.raises(ForgeToolAPIError) as excinfo:
            await client.invoke_action(ACQUIRE_TOOL_ID, request_payload())
    assert excinfo.value.status_code == 502
    assert transport.invocations == {}


def test_endpoint_validates_before_provider_and_never_executes_motion_itself():
    endpoint = ObjectAcquireEndpoint(NoCall())
    rejected = endpoint.admit(request_payload(freshness_ms=101))
    assert rejected.code == "stale_observation"
    assert rejected.status_code == 409
