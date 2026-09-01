import math
from pathlib import Path

import pytest
import yaml
from PhyAgentOS.forge.tool_client import ForgeToolAPIError, ForgeToolClient

from scene_observe.fake_gateway import FakeGatewayTransport
from scene_observe.grasp_proposal import (
    GRASP_TOOL_ID,
    GRASP_TOOL_SPEC,
    GraspProposalEndpoint,
    GraspProposalSnapshot,
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

_MOTION_KEYS = {
    "motion_authorized",
    "ik_valid",
    "collision_free",
    "reachable",
    "ready_to_execute",
    "execution_approved",
}


def _motion_keys(value):
    found = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in _MOTION_KEYS:
                found.add(key)
            found |= _motion_keys(item)
    elif isinstance(value, list):
        for item in value:
            found |= _motion_keys(item)
    return found


def request_payload(**overrides):
    value = {
        "observation_ref": "observation://scene-7/camera_front",
        "scene_revision": "scene-7",
        "frame_id": "camera_front",
        "calibration_ref": "calibration://front/v3",
        "freshness_ms": 25,
        "max_age_ms": 100,
        "targets": [target()],
    }
    value.update(overrides)
    return value


def target(**overrides):
    value = {
        "entity_ref": "entity://bottle-1",
        "category": "container",
        "confidence": 0.92,
        "spatial_envelope": {
            "frame_id": "camera_front",
            "unit": "m",
            "min_xyz_m": [0.1, -0.2, 0.0],
            "max_xyz_m": [0.2, -0.1, 0.3],
            "confidence": 0.8,
            "provenance": ["artifact://obs-7/rgb"],
        },
    }
    envelope = overrides.pop("envelope", None)
    if envelope is not None:
        value["spatial_envelope"].update(envelope)
    value.update(overrides)
    return value


def candidate(index=1, **overrides):
    value = {
        "candidate_ref": f"candidate://bottle-1/{index}",
        "entity_ref": "entity://bottle-1",
        "grasp_frame": {
            "frame_id": "camera_front",
            "unit": "m",
            "position_m": [0.15, -0.15, 0.12],
            "orientation_xyzw": [0.0, 0.0, 0.0, 1.0],
        },
        "approach_direction": {
            "frame_id": "camera_front",
            "unit": "unitless",
            "vector": [0.0, 0.0, -1.0],
        },
        "score": 0.81,
        "confidence": 0.77,
        "provenance": ["artifact://obs-7/rgb"],
        "qualification": "proposed",
    }
    grasp_frame = overrides.pop("grasp_frame", None)
    approach_direction = overrides.pop("approach_direction", None)
    if grasp_frame is not None:
        value["grasp_frame"].update(grasp_frame)
    if approach_direction is not None:
        value["approach_direction"].update(approach_direction)
    value.update(overrides)
    return value


def proposal_snapshot(**overrides):
    value = {
        "candidates": (candidate(1), candidate(2)),
        "ambiguities": (),
        "funnel": {"decoded": 10, "canonicalized": 8, "deduplicated": 3, "retained": 2},
    }
    value.update(overrides)
    return GraspProposalSnapshot(**value)


class Provider:
    def __init__(self, result):
        self.result = result
        self.calls = 0
        self.requests = []

    def propose(self, request):
        self.calls += 1
        self.requests.append(request)
        return self.result


class NoCall:
    def propose(self, request):
        raise AssertionError("provider must not be called")


class RaisingProvider:
    def propose(self, request):
        raise RuntimeError("provider backend failure")


def _observation_stub():
    return type("Observation", (), {"observe": lambda self, sensor_ref: None})()


async def query(provider, arguments):
    transport = FakeGatewayTransport(_observation_stub(), grasp_provider=provider)
    async with ForgeToolClient("http://fake", transport=transport) as client:
        spec = await client.get_tool(GRASP_TOOL_ID)
        context = await client.get_tool_context(GRASP_TOOL_ID)
        result = await client.invoke_query_tool(GRASP_TOOL_ID, arguments)
    return spec, context, result, transport


@pytest.mark.asyncio
async def test_grasp_propose_is_discovered_with_the_perception_queries():
    provider = Provider(proposal_snapshot())
    transport = FakeGatewayTransport(_observation_stub(), grasp_provider=provider)
    async with ForgeToolClient("http://fake", transport=transport) as client:
        tools = await client.list_tools()
        spec = await client.get_tool(GRASP_TOOL_ID)
        context = await client.get_tool_context(GRASP_TOOL_ID)
    assert [item["tool_id"] for item in tools["data"]["tools"]] == [
        "scene.observe",
        "scene.understand",
        "grasp.propose",
        "manipulation.prepare",
    ]
    assert spec["data"]["endpoint_id"] == "grasp_proposal"
    assert spec["data"]["operation"] == "propose"
    assert spec["data"]["semantics"] == "query"
    assert context["data"] == {
        "ready": True,
        "binding_error": None,
        "motion_authorized": False,
        "observation_frame": "observation",
        "unit": "m",
    }


def test_tool_spec_is_strict_and_provider_neutral():
    assert GRASP_TOOL_SPEC["semantics"] == "query"
    assert GRASP_TOOL_SPEC["endpoint_id"] == "grasp_proposal"
    assert GRASP_TOOL_SPEC["operation"] == "propose"
    assert GRASP_TOOL_SPEC["input_schema"]["additionalProperties"] is False
    assert GRASP_TOOL_SPEC["output_schema"]["additionalProperties"] is False
    assert "targets" in GRASP_TOOL_SPEC["input_schema"]["required"]
    assert GRASP_TOOL_SPEC["output_schema"]["properties"]["status"]["enum"] == [
        "available",
        "empty",
        "unavailable",
        "stale",
        "invalid",
    ]
    assert GRASP_TOOL_SPEC["output_schema"]["properties"]["candidates"]["items"]["properties"][
        "qualification"
    ]["enum"] == ["proposed", "low_confidence", "ambiguous"]
    blob = repr(GRASP_TOOL_SPEC).lower()
    assert not any(token in blob for token in _FORBIDDEN_TOKENS)
    assert not any(token in blob for token in _MOTION_KEYS)


def test_contract_yaml_matches_the_published_tool_spec():
    contract_path = Path(__file__).resolve().parents[1] / "contracts" / "grasp.propose.tool.yaml"
    assert yaml.safe_load(contract_path.read_text(encoding="utf-8")) == GRASP_TOOL_SPEC


def test_bundle_and_package_versions_match_the_feature_revision():
    bundle_manifest = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "skill.yaml").read_text(encoding="utf-8")
    )
    package_text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert bundle_manifest["version"] == "0.4.0"
    assert 'version = "0.4.0"' in package_text


@pytest.mark.asyncio
async def test_successful_proposal_binds_candidates_to_observation_evidence():
    provider = Provider(proposal_snapshot())
    _, context, result, transport = await query(provider, request_payload())
    data = result["data"]
    assert context["data"]["motion_authorized"] is False
    assert data["status"] == "available"
    assert data["candidate_set_ref"] == "candidate-set://scene-7/camera_front"
    assert data["observation_ref"] == "observation://scene-7/camera_front"
    assert data["scene_revision"] == "scene-7"
    assert data["frame"] == {"frame_id": "camera_front", "unit": "m"}
    assert data["calibration_ref"] == "calibration://front/v3"
    assert [item["candidate_ref"] for item in data["candidates"]] == [
        "candidate://bottle-1/1",
        "candidate://bottle-1/2",
    ]
    assert all(item["entity_ref"] == "entity://bottle-1" for item in data["candidates"])
    assert all(
        item["grasp_frame"]["frame_id"] == "camera_front"
        and item["grasp_frame"]["unit"] == "m"
        for item in data["candidates"]
    )
    assert all(item["approach_direction"]["unit"] == "unitless" for item in data["candidates"])
    assert all(item["provenance"] == ["artifact://obs-7/rgb"] for item in data["candidates"])
    assert data["funnel"] == {"decoded": 10, "canonicalized": 8, "deduplicated": 3, "retained": 2}
    assert data["ambiguities"] == []
    assert _motion_keys(data) == set()
    assert provider.calls == 1
    assert provider.requests[0]["observation_ref"] == "observation://scene-7/camera_front"
    assert provider.requests[0]["targets"][0]["entity_ref"] == "entity://bottle-1"
    assert [request.url.path for request in transport.requests] == [
        "/tools/grasp.propose",
        "/tools/grasp.propose/context",
        "/tools/grasp.propose",
        "/tools/grasp_proposal/propose:invoke",
    ]


@pytest.mark.asyncio
async def test_empty_provider_result_returns_explicit_empty_status():
    provider = Provider(
        proposal_snapshot(
            candidates=(),
            funnel={"decoded": 4, "canonicalized": 2, "deduplicated": 0, "retained": 0},
        )
    )
    _, _, result, _ = await query(provider, request_payload())
    data = result["data"]
    assert data["status"] == "empty"
    assert data["candidates"] == []
    assert data["funnel"] == {"decoded": 4, "canonicalized": 2, "deduplicated": 0, "retained": 0}
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_empty_targets_return_empty_without_fabricated_candidates():
    provider = NoCall()
    _, _, result, _ = await query(provider, request_payload(targets=[]))
    data = result["data"]
    assert data["status"] == "empty"
    assert data["candidates"] == []
    assert data["candidate_set_ref"] == "candidate-set://scene-7/camera_front"
    assert data["funnel"]["retained"] == 0


@pytest.mark.asyncio
async def test_stale_input_is_rejected_before_the_provider_call():
    provider = NoCall()
    _, _, result, _ = await query(provider, request_payload(freshness_ms=101))
    data = result["data"]
    assert data["status"] == "stale"
    assert data["error"]["code"] == "stale_observation"
    assert data["candidates"] == []
    assert data["candidate_set_ref"] == "candidate-set://scene-7/camera_front"


@pytest.mark.asyncio
async def test_missing_calibration_is_rejected_before_the_provider_call():
    provider = NoCall()
    _, _, result, _ = await query(provider, request_payload(calibration_ref=""))
    data = result["data"]
    assert data["status"] == "unavailable"
    assert data["error"]["code"] == "missing_calibration"
    assert data["candidates"] == []


@pytest.mark.asyncio
async def test_unavailable_provider_fails_closed_without_fabricated_candidates():
    _, _, result, _ = await query(Provider(None), request_payload())
    data = result["data"]
    assert data["status"] == "unavailable"
    assert data["error"]["code"] == "grasp_proposal_unavailable"
    assert data["candidates"] == []


@pytest.mark.asyncio
async def test_provider_exception_fails_closed_without_gateway_error():
    _, _, result, _ = await query(RaisingProvider(), request_payload())
    data = result["data"]
    assert data["status"] == "unavailable"
    assert data["error"]["code"] == "grasp_proposal_provider_error"
    assert data["candidates"] == []


@pytest.mark.parametrize(
    "snapshot",
    [
        GraspProposalSnapshot(candidates=None),
        GraspProposalSnapshot(ambiguities=None),
        {"provider_available": True},
    ],
)
@pytest.mark.asyncio
async def test_malformed_snapshot_fails_closed_with_invalid_snapshot(snapshot):
    _, _, result, _ = await query(Provider(snapshot), request_payload())
    data = result["data"]
    assert data["status"] == "invalid"
    assert data["error"]["code"] == "invalid_snapshot"
    assert data["candidates"] == []


@pytest.mark.asyncio
async def test_unconfigured_grasp_provider_is_unready_and_fails_closed():
    transport = FakeGatewayTransport(_observation_stub())
    async with ForgeToolClient("http://fake", transport=transport) as client:
        context = await client.get_tool_context(GRASP_TOOL_ID)
        with pytest.raises(ForgeToolAPIError) as excinfo:
            await client.invoke_query_tool(GRASP_TOOL_ID, request_payload())
    assert context["data"]["ready"] is False
    assert context["data"]["binding_error"] == "grasp proposal provider is unavailable"
    assert context["data"]["motion_authorized"] is False
    assert excinfo.value.status_code == 503


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        (
            request_payload(
                targets=[
                    target(
                        envelope={
                            "min_xyz_m": [0.2, -0.1, 0.3],
                            "max_xyz_m": [0.1, -0.2, 0.0],
                        }
                    )
                ]
            ),
            "invalid_target",
        ),
        (request_payload(targets=[target(envelope={"frame_id": "base_link"})]), "invalid_target_frame"),
        (request_payload(targets=[target(envelope={"unit": "mm"})]), "invalid_target"),
        (request_payload(targets=[target(entity_ref="entity://bottle-1/extra")]), "invalid_target"),
        (request_payload(targets=[target(confidence=1.5)]), "invalid_target"),
        (request_payload(targets=[target(category=" ")]), "invalid_target"),
        (request_payload(targets=[target(spatial_envelope={"confidence": 0.8})]), "invalid_target"),
        ({**request_payload(), "seed": 7}, "invalid_arguments"),
        ({**request_payload(), "task_name": "pick"}, "invalid_arguments"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_arguments_fail_closed_before_the_provider_call(arguments, code):
    provider = NoCall()
    _, _, result, _ = await query(provider, arguments)
    data = result["data"]
    assert data["status"] == "invalid"
    assert data["error"]["code"] == code
    assert data["candidates"] == []


@pytest.mark.parametrize(
    "coordinate",
    [math.nan, math.inf, -math.inf],
)
def test_non_finite_target_coordinates_fail_closed_at_the_endpoint(coordinate):
    payload = request_payload(targets=[target(envelope={"min_xyz_m": [coordinate, -0.2, 0.0]})])
    result = GraspProposalEndpoint(NoCall()).invoke(payload)
    assert result["status"] == "invalid"
    assert result["error"]["code"] == "invalid_target"


@pytest.mark.parametrize(
    ("snapshot", "code"),
    [
        (
            proposal_snapshot(candidates=(candidate(1, candidate_ref="bottle-1/1"),)),
            "invalid_candidate_ref",
        ),
        (proposal_snapshot(candidates=(candidate(1), candidate(1))), "invalid_candidate_ref"),
        (
            proposal_snapshot(candidates=(candidate(1, entity_ref="entity://bottle-1/extra"),)),
            "invalid_entity_ref",
        ),
        (
            proposal_snapshot(candidates=(candidate(1, entity_ref="entity://cup-9"),)),
            "invalid_candidate_entity",
        ),
        (proposal_snapshot(candidates=(candidate(1, provenance=["../escape"]),)), "invalid_provenance"),
        (proposal_snapshot(candidates=(candidate(1, provenance=[]),)), "invalid_provenance"),
        (
            proposal_snapshot(candidates=(candidate(1, grasp_frame={"frame_id": "base_link"}),)),
            "invalid_candidate_frame",
        ),
        (
            proposal_snapshot(candidates=(candidate(1, approach_direction={"frame_id": "base_link"}),)),
            "invalid_candidate_frame",
        ),
        (proposal_snapshot(candidates=(candidate(1, grasp_frame={"unit": "mm"}),)), "invalid_candidate_unit"),
        (
            proposal_snapshot(candidates=(candidate(1, approach_direction={"unit": "m"}),)),
            "invalid_candidate_unit",
        ),
        (
            proposal_snapshot(candidates=(candidate(1, grasp_frame={"position_m": [0.1, 0.2]}),)),
            "invalid_candidate_geometry",
        ),
        (
            proposal_snapshot(
                candidates=(candidate(1, grasp_frame={"position_m": [math.nan, 0.0, 0.0]}),)
            ),
            "invalid_candidate_geometry",
        ),
        (
            proposal_snapshot(
                candidates=(candidate(1, grasp_frame={"position_m": [math.inf, 0.0, 0.0]}),)
            ),
            "invalid_candidate_geometry",
        ),
        (
            proposal_snapshot(
                candidates=(candidate(1, grasp_frame={"orientation_xyzw": [0.0, 0.0, 1.0]}),)
            ),
            "invalid_candidate_geometry",
        ),
        (
            proposal_snapshot(
                candidates=(candidate(1, approach_direction={"vector": [0.0, -1.0]}),)
            ),
            "invalid_candidate_geometry",
        ),
        (proposal_snapshot(candidates=(candidate(1, score=1.5),)), "invalid_candidate_score"),
        (proposal_snapshot(candidates=(candidate(1, confidence=-0.1),)), "invalid_candidate_score"),
        (proposal_snapshot(candidates=(candidate(1, ik_valid=True),)), "invalid_candidate"),
        (
            proposal_snapshot(candidates=(candidate(1, qualification="ready_to_execute"),)),
            "invalid_candidate",
        ),
        (
            proposal_snapshot(
                funnel={"decoded": 10, "canonicalized": 8, "deduplicated": 3, "retained": 3}
            ),
            "invalid_funnel",
        ),
        (
            proposal_snapshot(
                funnel={"decoded": -1, "canonicalized": 0, "deduplicated": 0, "retained": 2}
            ),
            "invalid_funnel",
        ),
        (
            proposal_snapshot(
                funnel={"decoded": 1, "canonicalized": 8, "deduplicated": 3, "retained": 2}
            ),
            "invalid_funnel",
        ),
        (
            proposal_snapshot(
                ambiguities=({"code": "occlusion", "message": "grasp region is occluded"},)
            ),
            "invalid_ambiguity",
        ),
    ],
)
@pytest.mark.asyncio
async def test_invalid_provider_results_fail_closed(snapshot, code):
    provider = Provider(snapshot)
    _, _, result, _ = await query(provider, request_payload())
    data = result["data"]
    assert data["status"] == "invalid"
    assert data["error"]["code"] == code
    assert data["candidates"] == []
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_request_and_result_remain_provider_neutral():
    provider = Provider(proposal_snapshot())
    _, _, result, _ = await query(provider, request_payload())
    blob = (repr(request_payload()) + repr(result["data"])).lower()
    assert not any(token in blob for token in _FORBIDDEN_TOKENS)
    assert _motion_keys(result["data"]) == set()


@pytest.mark.asyncio
async def test_grasp_propose_never_creates_action_session_or_motion_routes():
    provider = Provider(proposal_snapshot())
    _, context, result, transport = await query(provider, request_payload())
    assert context["data"]["motion_authorized"] is False
    assert _motion_keys(result["data"]) == set()
    paths = [request.url.path for request in transport.requests]
    assert paths == [
        "/tools/grasp.propose",
        "/tools/grasp.propose/context",
        "/tools/grasp.propose",
        "/tools/grasp_proposal/propose:invoke",
    ]
    assert all(not path.endswith("/grasp.propose:invoke") for path in paths)
    assert all(not path.startswith("/invocations/") for path in paths)
