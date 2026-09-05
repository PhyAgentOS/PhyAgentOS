from pathlib import Path

import pytest
import yaml
from PhyAgentOS.forge.tool_client import ForgeToolClient

from pick_place_workflow.fake_gateway import FakeGatewayTransport
from pick_place_workflow.understanding import (
    UNDERSTANDING_TOOL_SPEC,
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


def test_observation_ref_must_bind_to_scene_revision_and_frame():
    provider = Provider(understanding_snapshot())
    result = SceneUnderstandingEndpoint(provider).invoke(
        request_payload(observation_ref="observation://other/camera_front")
    )
    assert result["status"] == "invalid"
    assert result["error"]["code"] == "invalid_observation_binding"
    assert provider.calls == 0


@pytest.mark.parametrize("provenance", [[], ["artifact://obs-7/rgb", "artifact://obs-7/rgb"]])
def test_claim_provenance_must_be_non_empty_and_unique(provenance):
    result = SceneUnderstandingEndpoint(
        Provider(understanding_snapshot(entities=({
            "entity_ref": "entity://bottle-1",
            "category": "container",
            "confidence": 0.92,
            "provenance": provenance,
        },)))
    ).invoke(request_payload())
    assert result["status"] == "invalid"
    assert result["error"]["code"] == "invalid_entity_claim"


def test_spatial_envelope_cannot_cross_observation_frame():
    envelope = dict(understanding_snapshot().spatial_envelopes[0])
    envelope["frame_id"] = "other_camera"
    result = SceneUnderstandingEndpoint(
        Provider(understanding_snapshot(spatial_envelopes=(envelope,)))
    ).invoke(request_payload())
    assert result["status"] == "invalid"
    assert result["error"]["code"] == "invalid_spatial_envelope"


def test_provider_cannot_mutate_request_used_for_binding_validation():
    class MutatingProvider(Provider):
        def understand(self, request):
            request["scene_revision"] = "scene-attacker"
            return super().understand(request)

    provider = MutatingProvider(understanding_snapshot())
    result = SceneUnderstandingEndpoint(provider).invoke(request_payload())
    assert result["status"] == "available"
    assert result["scene_revision"] == "scene-7"


def _derived(kind="instance_mask", **overrides):
    value = {
        "artifact_ref": "artifact://obs-7/derived/mask-bottle-1",
        "kind": kind,
        "media_type": "image/png" if kind == "instance_mask" else "application/json",
        "observation_ref": "observation://scene-7/camera_front",
        "scene_revision": "scene-7",
        "entity_ref": "entity://bottle-1",
        "frame_id": "camera_front",
        "calibration_ref": "calibration://front/v3",
        "source_refs": ["artifact://obs-7/rgb"],
        "provenance": ["artifact://obs-7/rgb"],
        "descriptor": {
            "width_px": 640,
            "height_px": 480,
            "bbox_xyxy_px": [10, 20, 120, 180],
            "foreground_pixels": 9000,
            "point_count": None,
            "unit": None,
            "min_xyz_m": None,
            "max_xyz_m": None,
            "confidence": None,
        },
    }
    if kind == "object_point_cloud":
        value["artifact_ref"] = "artifact://obs-7/derived/points-bottle-1"
        value["source_refs"] = ["artifact://obs-7/rgb", "artifact://obs-7/derived/mask-bottle-1"]
        value["provenance"] = ["artifact://obs-7/rgb"]
        value["descriptor"] = {
            "width_px": None,
            "height_px": None,
            "bbox_xyxy_px": None,
            "foreground_pixels": None,
            "point_count": 1200,
            "unit": "m",
            "min_xyz_m": None,
            "max_xyz_m": None,
            "confidence": None,
        }
    elif kind == "metric_localization":
        value["artifact_ref"] = "artifact://obs-7/derived/localization-bottle-1"
        value["source_refs"] = ["artifact://obs-7/derived/points-bottle-1"]
        value["provenance"] = ["artifact://obs-7/rgb"]
        value["descriptor"] = {
            "width_px": None,
            "height_px": None,
            "bbox_xyxy_px": None,
            "foreground_pixels": None,
            "point_count": None,
            "unit": "m",
            "min_xyz_m": [0.1, -0.2, 0.0],
            "max_xyz_m": [0.2, -0.1, 0.3],
            "confidence": 0.8,
        }
    value.update(overrides)
    return value


def test_derived_artifacts_are_projected_and_contract_matches_yaml():
    snapshot = understanding_snapshot(
        derived_artifacts=(_derived(),),
    )
    output = SceneUnderstandingEndpoint(Provider(snapshot)).invoke(request_payload())
    assert output["status"] == "available"
    assert output["derived_artifacts"][0]["kind"] == "instance_mask"
    contract = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "contracts" / "scene.understand.tool.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert contract == UNDERSTANDING_TOOL_SPEC


@pytest.mark.parametrize(
    ("artifact", "code"),
    [
        (
            _derived(
                descriptor={
                    **_derived()["descriptor"],
                    "bbox_xyxy_px": [10, 20, 10, 180],
                }
            ),
            "invalid_derived_artifact_descriptor",
        ),
        (_derived(source_refs=["artifact://obs-7/unknown/depth"]), "invalid_derived_artifact_lineage"),
        (_derived(entity_ref="entity://other"), "invalid_derived_artifact_binding"),
        (_derived(kind="not-a-provider"), "invalid_derived_artifact_kind"),
    ],
)
def test_derived_artifact_validation_fails_closed(artifact, code):
    output = SceneUnderstandingEndpoint(
        Provider(understanding_snapshot(derived_artifacts=(artifact,)))
    ).invoke(request_payload())
    assert output["status"] == "invalid"
    assert output["error"]["code"] == code


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("observation_ref", "observation://other/camera_front"),
        ("scene_revision", "scene-other"),
        ("frame_id", "other_camera"),
        ("calibration_ref", "calibration://other/v1"),
    ],
)
def test_derived_artifacts_must_bind_to_the_current_request(field, value):
    output = SceneUnderstandingEndpoint(
        Provider(understanding_snapshot(derived_artifacts=(_derived(**{field: value}),)))
    ).invoke(request_payload())
    assert output["status"] == "invalid"
    assert output["error"]["code"] == "invalid_derived_artifact_binding"


def test_derived_artifact_chain_requires_declared_prior_artifact():
    mask = _derived()
    points = _derived("object_point_cloud")
    points["source_refs"] = ["artifact://obs-7/derived/localization-bottle-1"]
    output = SceneUnderstandingEndpoint(
        Provider(understanding_snapshot(derived_artifacts=(mask, points)))
    ).invoke(request_payload())
    assert output["error"]["code"] == "invalid_derived_artifact_lineage"
