import math
from pathlib import Path

import pytest
import yaml
from PhyAgentOS.forge.tool_client import ForgeToolAPIError, ForgeToolClient

from pick_place_workflow.fake_gateway import FakeGatewayTransport
from pick_place_workflow.manipulation_prepare import (
    MANIPULATION_TOOL_SPEC,
    PREPARATION_TOOL_ID,
    ManipulationPreparationEndpoint,
    PreparationSnapshot,
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

# motion_authorized is allowed but must stay const false; these keys never are.
_ADMISSION_KEYS = {
    "ik_valid",
    "collision_free",
    "reachable",
    "ready_to_execute",
    "execution_approved",
}

_PASS_CHECKS = {"kinematic": "pass", "collision": "pass", "workspace": "pass"}


def request_payload(**overrides):
    value = {
        "observation_ref": "observation://scene-7/camera_front",
        "scene_revision": "scene-7",
        "frame_id": "camera_front",
        "calibration_ref": "calibration://front/v3",
        "freshness_ms": 25,
        "max_age_ms": 100,
        "candidate_set_ref": "candidate-set://scene-7/camera_front",
        "candidates": [candidate(1), candidate(2)],
    }
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


def prepared(index=1, **overrides):
    value = {
        "candidate_ref": f"candidate://bottle-1/{index}",
        "entity_ref": "entity://bottle-1",
        "checks": dict(_PASS_CHECKS),
        "evidence": [f"artifact://prep-7/kinematic-{index}", f"artifact://prep-7/collision-{index}"],
        "qualification": "prepared",
    }
    value.update(overrides)
    return value


def preparation_snapshot(**overrides):
    value = {
        "prepared_candidates": (prepared(1), prepared(2)),
    }
    value.update(overrides)
    return PreparationSnapshot(**value)


class Provider:
    def __init__(self, result):
        self.result = result
        self.calls = 0
        self.requests = []

    def prepare(self, request):
        self.calls += 1
        self.requests.append(request)
        return self.result


class NoCall:
    def prepare(self, request):
        raise AssertionError("provider must not be called")


class RaisingProvider:
    def prepare(self, request):
        raise RuntimeError("provider backend failure")


def _observation_stub():
    return type("Observation", (), {"observe": lambda self, sensor_ref: None})()


async def query(provider, arguments):
    transport = FakeGatewayTransport(_observation_stub(), preparation_provider=provider)
    async with ForgeToolClient("http://fake", transport=transport) as client:
        spec = await client.get_tool(PREPARATION_TOOL_ID)
        context = await client.get_tool_context(PREPARATION_TOOL_ID)
        result = await client.invoke_query_tool(PREPARATION_TOOL_ID, arguments)
    return spec, context, result, transport


@pytest.mark.asyncio
async def test_prepare_is_discovered_after_the_proposal_query():
    provider = Provider(preparation_snapshot())
    transport = FakeGatewayTransport(_observation_stub(), preparation_provider=provider)
    async with ForgeToolClient("http://fake", transport=transport) as client:
        tools = await client.list_tools()
        spec = await client.get_tool(PREPARATION_TOOL_ID)
        context = await client.get_tool_context(PREPARATION_TOOL_ID)
    assert [item["tool_id"] for item in tools["data"]["tools"]] == [
        "scene.observe",
        "scene.understand",
        "grasp.propose",
        "manipulation.prepare",
        "object.acquire",
        "object.place",
    ]
    assert spec["data"]["endpoint_id"] == "manipulation_preparation"
    assert spec["data"]["operation"] == "prepare"
    assert spec["data"]["semantics"] == "query"
    assert context["data"] == {
        "ready": True,
        "binding_error": None,
        "motion_authorized": False,
        "observation_frame": "observation",
        "unit": "m",
    }


def test_tool_spec_is_strict_and_never_authorizes_motion():
    assert MANIPULATION_TOOL_SPEC["semantics"] == "query"
    assert MANIPULATION_TOOL_SPEC["endpoint_id"] == "manipulation_preparation"
    assert MANIPULATION_TOOL_SPEC["operation"] == "prepare"
    assert MANIPULATION_TOOL_SPEC["input_schema"]["additionalProperties"] is False
    assert MANIPULATION_TOOL_SPEC["output_schema"]["additionalProperties"] is False
    assert "candidates" in MANIPULATION_TOOL_SPEC["input_schema"]["required"]
    assert MANIPULATION_TOOL_SPEC["output_schema"]["properties"]["status"]["enum"] == [
        "available",
        "empty",
        "unavailable",
        "stale",
        "invalid",
    ]
    prepared_schema = MANIPULATION_TOOL_SPEC["output_schema"]["properties"]["prepared_candidates"]
    assert prepared_schema["items"]["properties"]["qualification"]["enum"] == ["prepared"]
    assert (
        prepared_schema["items"]["properties"]["checks"]["properties"]["kinematic"]["enum"]
        == ["pass", "fail", "unknown"]
    )
    assert (
        MANIPULATION_TOOL_SPEC["output_schema"]["properties"]["motion_authorized"] == {"const": False}
    )
    blob = repr(MANIPULATION_TOOL_SPEC).lower()
    assert not any(token in blob for token in _FORBIDDEN_TOKENS)
    assert not any(token in blob for token in _ADMISSION_KEYS)


def test_skill_imports_resolve_to_paos_generic_runtime():
    assert (
        ManipulationPreparationEndpoint.__module__
        == "PhyAgentOS.forge.capability_runtime.manipulation_prepare"
    )
    assert PreparationSnapshot.__module__ == "PhyAgentOS.forge.capability_runtime.manipulation_prepare"


def test_contract_yaml_matches_the_published_tool_spec():
    contract_path = (
        Path(__file__).resolve().parents[1] / "contracts" / "manipulation.prepare.tool.yaml"
    )
    assert yaml.safe_load(contract_path.read_text(encoding="utf-8")) == MANIPULATION_TOOL_SPEC


@pytest.mark.asyncio
async def test_successful_preparation_returns_evidence_without_motion_authority():
    provider = Provider(preparation_snapshot())
    _, context, result, transport = await query(provider, request_payload())
    data = result["data"]
    assert context["data"]["motion_authorized"] is False
    assert data["status"] == "available"
    assert data["preparation_ref"] == "preparation://scene-7/camera_front"
    assert data["candidate_set_ref"] == "candidate-set://scene-7/camera_front"
    assert data["observation_ref"] == "observation://scene-7/camera_front"
    assert data["scene_revision"] == "scene-7"
    assert data["frame"] == {"frame_id": "camera_front", "unit": "m"}
    assert data["calibration_ref"] == "calibration://front/v3"
    assert [item["candidate_ref"] for item in data["prepared_candidates"]] == [
        "candidate://bottle-1/1",
        "candidate://bottle-1/2",
    ]
    assert all(item["checks"] == _PASS_CHECKS for item in data["prepared_candidates"])
    assert all(item["qualification"] == "prepared" for item in data["prepared_candidates"])
    assert data["checks"] == _PASS_CHECKS
    assert data["evidence"] == [
        "artifact://prep-7/kinematic-1",
        "artifact://prep-7/collision-1",
        "artifact://prep-7/kinematic-2",
        "artifact://prep-7/collision-2",
    ]
    assert data["motion_authorized"] is False
    assert provider.calls == 1
    assert provider.requests[0]["candidate_set_ref"] == "candidate-set://scene-7/camera_front"
    assert [item["candidate_ref"] for item in provider.requests[0]["candidates"]] == [
        "candidate://bottle-1/1",
        "candidate://bottle-1/2",
    ]
    assert [request.url.path for request in transport.requests] == [
        "/tools/manipulation.prepare",
        "/tools/manipulation.prepare/context",
        "/tools/manipulation.prepare",
        "/tools/manipulation_preparation/prepare:invoke",
    ]


@pytest.mark.asyncio
async def test_partial_preparation_returns_only_ready_candidates():
    provider = Provider(preparation_snapshot(prepared_candidates=(prepared(2),)))
    _, _, result, _ = await query(provider, request_payload())
    data = result["data"]
    assert data["status"] == "available"
    assert [item["candidate_ref"] for item in data["prepared_candidates"]] == [
        "candidate://bottle-1/2"
    ]
    assert data["evidence"] == ["artifact://prep-7/kinematic-2", "artifact://prep-7/collision-2"]


@pytest.mark.asyncio
async def test_all_candidates_rejected_returns_explicit_empty():
    provider = Provider(preparation_snapshot(prepared_candidates=()))
    _, _, result, _ = await query(provider, request_payload())
    data = result["data"]
    assert data["status"] == "empty"
    assert data["prepared_candidates"] == []
    assert data["checks"] == {"kinematic": "unknown", "collision": "unknown", "workspace": "unknown"}
    assert data["evidence"] == []
    assert data["motion_authorized"] is False
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_empty_candidate_input_skips_the_provider():
    _, _, result, _ = await query(NoCall(), request_payload(candidates=[]))
    data = result["data"]
    assert data["status"] == "empty"
    assert data["prepared_candidates"] == []
    assert data["preparation_ref"] == "preparation://scene-7/camera_front"
    assert data["motion_authorized"] is False


@pytest.mark.asyncio
async def test_stale_input_is_rejected_before_the_provider_call():
    _, _, result, _ = await query(NoCall(), request_payload(freshness_ms=101))
    data = result["data"]
    assert data["status"] == "stale"
    assert data["error"]["code"] == "stale_observation"
    assert data["prepared_candidates"] == []
    assert data["preparation_ref"] == "preparation://scene-7/camera_front"


@pytest.mark.asyncio
async def test_missing_calibration_is_rejected_before_the_provider_call():
    _, _, result, _ = await query(NoCall(), request_payload(calibration_ref=""))
    data = result["data"]
    assert data["status"] == "unavailable"
    assert data["error"]["code"] == "missing_calibration"
    assert data["prepared_candidates"] == []


@pytest.mark.parametrize(
    ("candidate_set_ref", "code"),
    [
        ("candidate-set://scene-8/camera_front", "invalid_candidate_set_binding"),
        ("candidate-set://scene-7/base_link", "invalid_candidate_set_binding"),
        ("candidate-set://oops", "invalid_candidate_set_ref"),
        ("grasp://scene-7/camera_front", "invalid_candidate_set_ref"),
    ],
)
@pytest.mark.asyncio
async def test_candidate_set_mismatch_fails_closed_before_the_provider_call(candidate_set_ref, code):
    _, _, result, _ = await query(NoCall(), request_payload(candidate_set_ref=candidate_set_ref))
    data = result["data"]
    assert data["status"] == "invalid"
    assert data["error"]["code"] == code
    assert data["prepared_candidates"] == []


@pytest.mark.asyncio
async def test_unavailable_provider_fails_closed_without_fabricated_candidates():
    _, _, result, _ = await query(Provider(None), request_payload())
    data = result["data"]
    assert data["status"] == "unavailable"
    assert data["error"]["code"] == "preparation_unavailable"
    assert data["prepared_candidates"] == []


@pytest.mark.asyncio
async def test_provider_exception_fails_closed_without_gateway_error():
    _, _, result, _ = await query(RaisingProvider(), request_payload())
    data = result["data"]
    assert data["status"] == "unavailable"
    assert data["error"]["code"] == "preparation_provider_error"
    assert data["prepared_candidates"] == []


@pytest.mark.parametrize(
    "snapshot",
    [
        {"prepared_candidates": ()},
        PreparationSnapshot(prepared_candidates=None),
        PreparationSnapshot(provider_available="yes"),
    ],
)
@pytest.mark.asyncio
async def test_malformed_snapshot_fails_closed_with_invalid_snapshot(snapshot):
    _, _, result, _ = await query(Provider(snapshot), request_payload())
    data = result["data"]
    assert data["status"] == "invalid"
    assert data["error"]["code"] == "invalid_snapshot"
    assert data["prepared_candidates"] == []


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        ({**request_payload(), "seed": 7}, "invalid_arguments"),
        ({**request_payload(), "task_name": "pick"}, "invalid_arguments"),
        (request_payload(observation_ref="obs://scene-7/camera_front"), "invalid_observation_ref"),
        (request_payload(scene_revision=" "), "invalid_scene_revision"),
        (request_payload(frame_id=""), "invalid_frame"),
        (request_payload(freshness_ms=-1), "invalid_freshness"),
        (request_payload(freshness_ms=True), "invalid_freshness"),
        (request_payload(max_age_ms=0), "invalid_freshness"),
        (request_payload(candidates={"0": candidate(1)}), "invalid_candidate"),
        (request_payload(candidates=[candidate(1), candidate(1)]), "invalid_candidate_ref"),
        (
            request_payload(candidates=[candidate(1, entity_ref="entity://bottle-1/extra")]),
            "invalid_entity_ref",
        ),
        (
            request_payload(candidates=[candidate(1, grasp_frame={"frame_id": "base_link"})]),
            "invalid_candidate_frame",
        ),
        (
            request_payload(
                candidates=[candidate(1, approach_direction={"frame_id": "base_link"})]
            ),
            "invalid_candidate_frame",
        ),
        (request_payload(candidates=[candidate(1, grasp_frame={"unit": "mm"})]), "invalid_candidate_unit"),
        (
            request_payload(candidates=[candidate(1, approach_direction={"unit": "m"})]),
            "invalid_candidate_unit",
        ),
        (
            request_payload(candidates=[candidate(1, grasp_frame={"position_m": [0.1, 0.2]})]),
            "invalid_candidate_geometry",
        ),
        (
            request_payload(
                candidates=[candidate(1, grasp_frame={"orientation_xyzw": [0.0, 0.0, 1.0]})]
            ),
            "invalid_candidate_geometry",
        ),
        (request_payload(candidates=[candidate(1, score=1.5)]), "invalid_candidate_score"),
        (request_payload(candidates=[candidate(1, confidence=-0.1)]), "invalid_candidate_score"),
        (
            request_payload(candidates=[candidate(1, provenance=["../escape"])]),
            "invalid_provenance",
        ),
        (
            request_payload(candidates=[candidate(1, qualification="ready_to_execute")]),
            "invalid_candidate",
        ),
        (request_payload(candidates=[candidate(1, ik_valid=True)]), "invalid_candidate"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_arguments_fail_closed_before_the_provider_call(arguments, code):
    _, _, result, _ = await query(NoCall(), arguments)
    data = result["data"]
    assert data["status"] == "invalid"
    assert data["error"]["code"] == code
    assert data["prepared_candidates"] == []


@pytest.mark.parametrize(
    "coordinate",
    [math.nan, math.inf, -math.inf],
)
def test_non_finite_candidate_coordinates_fail_closed_at_the_endpoint(coordinate):
    payload = request_payload(
        candidates=[candidate(1, grasp_frame={"position_m": [coordinate, 0.0, 0.0]})]
    )
    result = ManipulationPreparationEndpoint(NoCall()).invoke(payload)
    assert result["status"] == "invalid"
    assert result["error"]["code"] == "invalid_candidate_geometry"


@pytest.mark.parametrize(
    ("snapshot", "code"),
    [
        (preparation_snapshot(prepared_candidates=(prepared(1, candidate_ref="bottle-1/1"),)), "invalid_candidate_ref"),
        (
            preparation_snapshot(prepared_candidates=(prepared(1, candidate_ref="candidate://cup-9/1"),)),
            "invalid_candidate_binding",
        ),
        (preparation_snapshot(prepared_candidates=(prepared(1, entity_ref="entity://cup-9"),)), "invalid_candidate_entity_binding"),
        (preparation_snapshot(prepared_candidates=(prepared(1, entity_ref="cup-9"),)), "invalid_entity_ref"),
        (
            preparation_snapshot(
                prepared_candidates=(
                    prepared(1, checks={"kinematic": "pass", "collision": "pass"}),
                )
            ),
            "invalid_check_result",
        ),
        (
            preparation_snapshot(
                prepared_candidates=(
                    prepared(
                        1,
                        checks={"kinematic": "maybe", "collision": "pass", "workspace": "pass"},
                    ),
                )
            ),
            "invalid_check_result",
        ),
        (
            preparation_snapshot(
                prepared_candidates=(
                    prepared(
                        1,
                        checks={"kinematic": "pass", "collision": "fail", "workspace": "pass"},
                    ),
                )
            ),
            "invalid_check_result",
        ),
        (preparation_snapshot(prepared_candidates=(prepared(1, evidence=[]),)), "invalid_evidence"),
        (
            preparation_snapshot(prepared_candidates=(prepared(1, evidence=["../escape"]),)),
            "invalid_evidence",
        ),
        (
            preparation_snapshot(prepared_candidates=(prepared(1, qualification="ready_to_execute"),)),
            "invalid_prepared_candidate",
        ),
        (
            preparation_snapshot(prepared_candidates=(prepared(1, motion_authorized=True),)),
            "invalid_prepared_candidate",
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
    assert data["prepared_candidates"] == []
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_request_and_result_remain_provider_neutral():
    provider = Provider(preparation_snapshot())
    _, _, result, _ = await query(provider, request_payload())
    blob = (repr(request_payload()) + repr(result["data"])).lower()
    assert not any(token in blob for token in _FORBIDDEN_TOKENS)
    assert not any(token in blob for token in _ADMISSION_KEYS)
    assert result["data"]["motion_authorized"] is False


@pytest.mark.asyncio
async def test_prepare_never_creates_action_session_or_motion_routes():
    provider = Provider(preparation_snapshot())
    transport = FakeGatewayTransport(_observation_stub(), preparation_provider=provider)
    async with ForgeToolClient("http://fake", transport=transport) as client:
        context = await client.get_tool_context(PREPARATION_TOOL_ID)
        result = await client.invoke_query_tool(PREPARATION_TOOL_ID, request_payload())
        with pytest.raises(ForgeToolAPIError) as excinfo:
            await client.invoke_action(PREPARATION_TOOL_ID, {})
    assert context["data"]["motion_authorized"] is False
    assert result["data"]["motion_authorized"] is False
    assert excinfo.value.status_code == 404
    paths = [request.url.path for request in transport.requests]
    assert paths == [
        "/tools/manipulation.prepare/context",
        "/tools/manipulation.prepare",
        "/tools/manipulation_preparation/prepare:invoke",
        "/tools/manipulation.prepare:invoke",
    ]
    assert all(not path.startswith("/invocations/") for path in paths)
