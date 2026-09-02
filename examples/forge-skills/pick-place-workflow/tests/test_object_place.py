from pathlib import Path

import pytest
import yaml
from PhyAgentOS.forge.tool_client import ForgeToolAPIError, ForgeToolClient

from pick_place_workflow.fake_gateway import FakeGatewayTransport
from pick_place_workflow.object_acquire import AcquireSnapshot
from pick_place_workflow.object_place import (
    PLACE_TOOL_ID,
    PLACE_TOOL_SPEC,
    ObjectPlaceEndpoint,
    PlaceSnapshot,
)

_FORBIDDEN_TOKENS = (
    "robotwin",
    "sapien",
    "task_name",
    "task_config",
    "embodiment",
    "xpolicylab",
    "eval_policy",
    "check_success",
    "ik_valid",
    "ready_to_execute",
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
        "acquire_invocation_ref": "invocation://object-acquire/placeholder",
        "destination_ref": "destination://bin/primary",
    }
    value.update(overrides)
    return value


def acquire_snapshot(**overrides):
    value = {
        "capability_phase": "hold",
        "status": "succeeded",
        "world_change_started": True,
        "outcome_known": True,
        "evidence_availability": "partial",
        "artifact_refs": ("artifact://acquire-7/settlement",),
        "bounded_metric_names": ("lift_height",),
    }
    value.update(overrides)
    return AcquireSnapshot(**value)


def place_snapshot(**overrides):
    value = {
        "capability_phase": "retreat",
        "status": "succeeded",
        "world_change_started": True,
        "outcome_known": True,
        "evidence_availability": "partial",
        "artifact_refs": ("artifact://place-7/trajectory",),
        "post_release_evidence_availability": "complete",
        "post_release_evidence_refs": ("artifact://place-7/post-release",),
        "bounded_metric_names": ("release_height",),
    }
    value.update(overrides)
    return PlaceSnapshot(**value)


class AcquireProvider:
    def __init__(self, result):
        self.result = result

    def acquire(self, request):
        return self.result


class PlaceProvider:
    def __init__(self, result):
        self.result = result
        self.calls = 0
        self.requests = []

    def place(self, request):
        self.calls += 1
        self.requests.append(request)
        return self.result


class NoCall:
    def place(self, request):
        raise AssertionError("place provider must not be called")


def _observation_stub():
    return type("Observation", (), {"observe": lambda self, sensor_ref: None})()


async def _completed_acquire(client, payload=None):
    source = payload or request_payload()
    acquire_payload = {
        key: value
        for key, value in source.items()
        if key not in {"acquire_invocation_ref", "destination_ref"}
    }
    admitted = await client.invoke_action("object.acquire", acquire_payload)
    invocation_id = admitted["data"]["invocation_id"]
    terminal = await client.invocation_result(invocation_id)
    if terminal["data"]["phase"] == "running":
        terminal = await client.invocation_result(invocation_id)
    assert terminal["data"]["phase"] == "completed"
    return invocation_id


def test_place_spec_is_strict_provider_neutral_and_keeps_phases_internal():
    assert PLACE_TOOL_SPEC["semantics"] == "action"
    assert PLACE_TOOL_SPEC["endpoint_id"] == "object_placement"
    assert PLACE_TOOL_SPEC["operation"] == "place"
    assert PLACE_TOOL_SPEC["max_concurrency"] == 1
    input_schema = PLACE_TOOL_SPEC["input_schema"]
    assert input_schema["additionalProperties"] is False
    assert "destination_ref" in input_schema["required"]
    assert not {"transport", "descent", "release", "retreat"} & set(input_schema["properties"])
    blob = repr(PLACE_TOOL_SPEC).lower()
    assert not any(token in blob for token in _FORBIDDEN_TOKENS)


def test_contract_yaml_matches_the_published_tool_spec():
    path = Path(__file__).resolve().parents[1] / "contracts" / "object.place.tool.yaml"
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == PLACE_TOOL_SPEC


@pytest.mark.asyncio
async def test_discovery_success_pending_and_post_release_evidence():
    acquire = AcquireProvider(acquire_snapshot())
    place = PlaceProvider(place_snapshot(pending_polls=1))
    transport = FakeGatewayTransport(_observation_stub(), acquire_provider=acquire, place_provider=place)
    async with ForgeToolClient("http://fake", transport=transport) as client:
        acquire_ref = await _completed_acquire(client)
        payload = request_payload(acquire_invocation_ref=acquire_ref)
        tools = await client.list_tools()
        spec = await client.get_tool(PLACE_TOOL_ID)
        context = await client.get_tool_context(PLACE_TOOL_ID)
        admitted = await client.invoke_action(PLACE_TOOL_ID, payload, caller_id="paos:test")
        invocation_id = admitted["data"]["invocation_id"]
        pending = await client.invocation_result(invocation_id)
        terminal = await client.invocation_result(invocation_id)
    assert [item["tool_id"] for item in tools["data"]["tools"]][-1] == PLACE_TOOL_ID
    assert spec["data"]["semantics"] == "action"
    assert context["data"]["ready"] is True
    assert admitted["data"]["phase"] == "accepted"
    assert pending["data"]["phase"] == "running"
    result = terminal["data"]["result"]
    assert terminal["data"]["phase"] == "completed"
    assert result["destination_ref"] == "destination://bin/primary"
    assert result["capability_outcome_summary"]["post_release_evidence"] == {
        "availability": "complete",
        "artifact_refs": ["artifact://place-7/post-release"],
    }
    assert place.calls == 1
    assert place.requests == [payload]
    paths = [request.url.path for request in transport.requests]
    assert "/tools/object.place:invoke" in paths
    assert all(not path.startswith("/sessions/") for path in paths)


@pytest.mark.asyncio
async def test_place_requires_terminal_successful_acquire_binding():
    place = PlaceProvider(place_snapshot())
    transport = FakeGatewayTransport(_observation_stub(), place_provider=place)
    async with ForgeToolClient("http://fake", transport=transport) as client:
        with pytest.raises(ForgeToolAPIError) as missing:
            await client.invoke_action(PLACE_TOOL_ID, request_payload())
    assert missing.value.status_code == 404
    assert missing.value.error_code == "acquire_invocation_not_found"
    assert place.calls == 0
    assert transport.invocations == {}


@pytest.mark.asyncio
async def test_unconfigured_or_malformed_place_provider_fails_closed():
    transport = FakeGatewayTransport(_observation_stub())
    async with ForgeToolClient("http://fake", transport=transport) as client:
        acquire = await client.get_tool_context("object.acquire")
        place = await client.get_tool_context(PLACE_TOOL_ID)
        with pytest.raises(ForgeToolAPIError) as excinfo:
            await client.invoke_action(PLACE_TOOL_ID, request_payload())
    assert acquire["data"]["ready"] is False
    assert place["data"]["binding_error"] == "object placement provider is unavailable"
    assert excinfo.value.status_code == 503

    malformed = PlaceSnapshot(
        post_release_evidence_availability="complete",
        post_release_evidence_refs=(),
    )
    transport = FakeGatewayTransport(
        _observation_stub(),
        acquire_provider=AcquireProvider(acquire_snapshot()),
        place_provider=PlaceProvider(malformed),
    )
    async with ForgeToolClient("http://fake", transport=transport) as client:
        acquire_ref = await _completed_acquire(client)
        with pytest.raises(ForgeToolAPIError) as excinfo:
            await client.invoke_action(PLACE_TOOL_ID, request_payload(acquire_invocation_ref=acquire_ref))
    assert excinfo.value.status_code == 502
    assert excinfo.value.error_code == "invalid_post_release_evidence"
    assert transport.invocations[acquire_ref]["terminal"] is True
    assert all(record["tool_id"] == "object.acquire" for record in transport.invocations.values())


@pytest.mark.parametrize(
    ("overrides", "status_code", "code"),
    [
        ({"freshness_ms": 101}, 409, "stale_observation"),
        ({"calibration_ref": ""}, 422, "missing_calibration"),
        ({"destination_ref": "bin"}, 400, "invalid_destination_ref"),
        ({"acquire_invocation_ref": "invocation://object-place/x"}, 400, "invalid_acquire_invocation_ref"),
        ({"phase": "release"}, 400, "invalid_arguments"),
        ({"task_name": "put"}, 400, "invalid_arguments"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_place_admission_fails_before_provider(overrides, status_code, code):
    acquire = AcquireProvider(acquire_snapshot())
    place = PlaceProvider(place_snapshot())
    transport = FakeGatewayTransport(_observation_stub(), acquire_provider=acquire, place_provider=place)
    async with ForgeToolClient("http://fake", transport=transport) as client:
        acquire_ref = await _completed_acquire(client)
        with pytest.raises(ForgeToolAPIError) as excinfo:
            place_payload = request_payload(acquire_invocation_ref=acquire_ref)
            place_payload.update(overrides)
            await client.invoke_action(PLACE_TOOL_ID, place_payload)
    assert excinfo.value.status_code == status_code
    assert excinfo.value.error_code == code
    assert place.calls == 0


@pytest.mark.asyncio
async def test_place_rejects_non_success_or_non_terminal_acquire():
    for snapshot, code in (
        (acquire_snapshot(pending_polls=1), "acquire_not_terminal"),
        (acquire_snapshot(status="failed", failure_owner="execution", failure_code="grasp_lost"), "acquire_not_succeeded"),
    ):
        transport = FakeGatewayTransport(
            _observation_stub(), acquire_provider=AcquireProvider(snapshot), place_provider=PlaceProvider(place_snapshot())
        )
        async with ForgeToolClient("http://fake", transport=transport) as client:
            admitted = await client.invoke_action(
                "object.acquire",
                {
                    key: value
                    for key, value in request_payload().items()
                    if key not in {"acquire_invocation_ref", "destination_ref"}
                },
            )
            acquire_ref = admitted["data"]["invocation_id"]
            if snapshot.pending_polls:
                with pytest.raises(ForgeToolAPIError):
                    await client.invoke_action(PLACE_TOOL_ID, request_payload(acquire_invocation_ref=acquire_ref))
            else:
                await client.invocation_result(acquire_ref)
                with pytest.raises(ForgeToolAPIError) as excinfo:
                    await client.invoke_action(PLACE_TOOL_ID, request_payload(acquire_invocation_ref=acquire_ref))
                assert excinfo.value.error_code == code


@pytest.mark.asyncio
async def test_cancel_and_unknown_preserve_physical_uncertainty():
    transport = FakeGatewayTransport(
        _observation_stub(),
        acquire_provider=AcquireProvider(acquire_snapshot()),
        place_provider=PlaceProvider(place_snapshot(pending_polls=2)),
    )
    async with ForgeToolClient("http://fake", transport=transport) as client:
        acquire_ref = await _completed_acquire(client)
        admitted = await client.invoke_action(PLACE_TOOL_ID, request_payload(acquire_invocation_ref=acquire_ref))
        invocation_id = admitted["data"]["invocation_id"]
        cancelled = await client.cancel_invocation(invocation_id)
        terminal = await client.invocation_result(invocation_id)
    assert cancelled["data"]["cancel_requested"] is True
    summary = terminal["data"]["result"]["capability_outcome_summary"]
    assert summary["status"] == "cancelled"
    assert summary["outcome_known"] is True

    unknown_transport = FakeGatewayTransport(
        _observation_stub(),
        acquire_provider=AcquireProvider(acquire_snapshot()),
        place_provider=PlaceProvider(
            place_snapshot(
                capability_phase="release",
                status="unknown",
                failure_owner="execution",
                failure_code="remote_state_unknown",
                outcome_known=False,
                post_release_evidence_availability="unknown",
                post_release_evidence_refs=(),
            )
        ),
    )
    async with ForgeToolClient("http://fake", transport=unknown_transport) as client:
        acquire_ref = await _completed_acquire(client)
        admitted = await client.invoke_action(PLACE_TOOL_ID, request_payload(acquire_invocation_ref=acquire_ref))
        terminal = await client.invocation_result(admitted["data"]["invocation_id"])
    summary = terminal["data"]["result"]["capability_outcome_summary"]
    assert summary["status"] == "unknown"
    assert summary["outcome_known"] is False
    assert summary["post_release_evidence"]["availability"] == "unknown"


@pytest.mark.asyncio
async def test_place_and_acquire_have_independent_concurrency_leases():
    acquire_provider = AcquireProvider(acquire_snapshot(pending_polls=1))
    place_provider = PlaceProvider(place_snapshot(pending_polls=1))
    transport = FakeGatewayTransport(
        _observation_stub(), acquire_provider=acquire_provider, place_provider=place_provider
    )
    async with ForgeToolClient("http://fake", transport=transport) as client:
        acquire_ref = await _completed_acquire(client)
        first = await client.invoke_action(PLACE_TOOL_ID, request_payload(acquire_invocation_ref=acquire_ref))
        with pytest.raises(ForgeToolAPIError) as excinfo:
            await client.invoke_action(PLACE_TOOL_ID, request_payload(acquire_invocation_ref=acquire_ref))
    assert first["data"]["phase"] == "accepted"
    assert excinfo.value.error_code == "concurrency_exhausted"
    assert place_provider.calls == 1


def test_endpoint_validates_before_provider_and_never_executes_motion_itself():
    endpoint = ObjectPlaceEndpoint(NoCall())
    rejected = endpoint.admit(request_payload(freshness_ms=101))
    assert rejected.code == "stale_observation"
    assert rejected.status_code == 409
