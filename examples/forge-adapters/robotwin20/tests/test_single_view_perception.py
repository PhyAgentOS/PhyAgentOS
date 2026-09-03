from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from PhyAgentOS.forge.tool_client import ForgeToolClient
from pick_place_workflow.fake_gateway import FakeGatewayTransport

from robotwin20_adapter import (
    FilesystemPerceptionArtifactStore,
    NumpyMetricLocalizationProvider,
    Proposal,
    RoboTwinSceneUnderstandingProvider,
    SegmentationResult,
    SingleViewPerceptionError,
    SingleViewPerceptionInference,
    WorkerProposalProvider,
    WorkerSegmentationProvider,
)

np = pytest.importorskip("numpy", reason="single-view perception runs in the adapter environment")

SCENE_REVISION = "scene-7"
CAPTURE_ID = "capture-1"
OBSERVATION_REF = "observation://scene-7/head_camera"
RGB_REF = "artifact://scene-7/capture-1/rgb"
DEPTH_REF = "artifact://scene-7/capture-1/depth"
STATE_REF = "artifact://scene-7/capture-1/state"
CALIBRATION_REF = "artifact://scene-7/capture-1/calibration"
REQUEST = {
    "observation_ref": OBSERVATION_REF,
    "scene_revision": SCENE_REVISION,
    "frame_id": "head_camera",
    "calibration_ref": CALIBRATION_REF,
    "freshness_ms": 5,
    "max_age_ms": 1000,
    "artifacts": [RGB_REF, DEPTH_REF, STATE_REF],
}


class SemanticInference:
    def infer(self, request):
        return {
            "entities": [
                {
                    "entity_ref": "entity://red-block",
                    "category": "red block",
                    "confidence": 0.9,
                    "provenance": [RGB_REF],
                }
            ],
            "relations": [],
            "spatial_envelopes": [],
            "ambiguities": [],
        }


class ProposalProvider:
    def __init__(self, proposals=(Proposal((1, 1, 3, 3), 0.8),), *, release_error=False):
        self.proposals = proposals
        self.release_error = release_error
        self.requests = []
        self.released = 0

    def propose(self, request):
        self.requests.append(request)
        return self.proposals

    def release(self):
        self.released += 1
        if self.release_error:
            raise RuntimeError("release failed")


class SegmentationProvider:
    def __init__(self, mask, *, changed_bbox=False, release_error=False):
        self.mask = mask
        self.changed_bbox = changed_bbox
        self.release_error = release_error
        self.requests = []
        self.released = 0

    def segment(self, request):
        self.requests.append(request)
        bbox = (0, 0, 1, 1) if self.changed_bbox else request.proposal.bbox_xyxy_px
        return SegmentationResult(mask=self.mask, proposal_bbox_xyxy_px=bbox)

    def release(self):
        self.released += 1
        if self.release_error:
            raise RuntimeError("release failed")


def _png_header(width, height):
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + width.to_bytes(4, "big") + height.to_bytes(4, "big")


def _artifacts(tmp_path: Path, *, depth=None, camera_name="head_camera"):
    capture = tmp_path / SCENE_REVISION / CAPTURE_ID
    capture.mkdir(parents=True)
    (capture / "rgb.png").write_bytes(_png_header(4, 3))
    np.save(
        capture / "depth.npy",
        np.full((3, 4), 1000.0, dtype=np.float32) if depth is None else depth,
        allow_pickle=False,
    )
    (capture / "state.json").write_text("{}", encoding="utf-8")
    (capture / "calibration.json").write_text(
        json.dumps(
            {
                "camera_name": camera_name,
                "intrinsic_cv": [[100.0, 0.0, 2.0], [0.0, 100.0, 1.5], [0.0, 0.0, 1.0]],
                "extrinsic_cv": [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]],
            }
        ),
        encoding="utf-8",
    )
    return FilesystemPerceptionArtifactStore(tmp_path)


def _inference(tmp_path, *, proposals=None, mask=None, depth=None, camera_name="head_camera"):
    proposal = ProposalProvider() if proposals is None else ProposalProvider(proposals)
    default_mask = np.array(
        [[False, False, False, False], [False, True, True, False], [False, True, True, False]]
    )
    segmentation = SegmentationProvider(default_mask if mask is None else mask)
    inference = SingleViewPerceptionInference(
        SemanticInference(),
        proposal_provider=proposal,
        segmentation_provider=segmentation,
        localization_provider=NumpyMetricLocalizationProvider(),
        artifact_store=_artifacts(tmp_path, depth=depth, camera_name=camera_name),
    )
    return inference, proposal, segmentation


def test_single_view_composition_crosses_the_generic_gateway_without_motion(tmp_path):
    inference, proposal, segmentation = _inference(tmp_path)
    provider = RoboTwinSceneUnderstandingProvider(inference)
    observation = type("Observation", (), {"observe": lambda self, sensor_ref: None})()
    transport = FakeGatewayTransport(observation, understanding_provider=provider)

    async def invoke():
        async with ForgeToolClient("http://fake", transport=transport) as client:
            return (
                await client.get_tool_context("scene.understand"),
                await client.invoke_query_tool("scene.understand", REQUEST),
            )

    context, response = asyncio.run(invoke())

    result = response["data"]
    assert context["data"]["motion_authorized"] is False
    assert result["status"] == "available"
    assert [item["kind"] for item in result["derived_artifacts"]] == [
        "instance_mask",
        "object_point_cloud",
        "metric_localization",
    ]
    assert result["spatial_envelopes"][0]["frame_id"] == "head_camera"
    assert result["spatial_envelopes"][0]["min_xyz_m"] == pytest.approx([-0.01, -0.005, 1.0])
    assert proposal.released == 1
    assert segmentation.released == 1
    assert proposal.requests[0].query == "red block"
    assert (tmp_path / SCENE_REVISION / CAPTURE_ID / "derived").is_dir()
    assert [request.url.path for request in transport.requests] == [
        "/tools/scene.understand/context",
        "/tools/scene.understand",
        "/tools/scene_understanding/understand:invoke",
    ]


def test_multiple_proposals_return_ambiguity_without_segmenting(tmp_path):
    inference, proposal, segmentation = _inference(
        tmp_path,
        proposals=(Proposal((0, 0, 2, 2), 0.8), Proposal((2, 1, 4, 3), 0.7)),
    )
    result = inference.infer(REQUEST)
    assert result["derived_artifacts"] == []
    assert result["spatial_envelopes"] == []
    assert result["ambiguities"][0]["code"] == "proposal_ambiguous"
    assert proposal.released == 1
    assert segmentation.requests == []
    assert segmentation.released == 1


def test_missing_proposal_score_is_not_fabricated(tmp_path):
    inference, _, _ = _inference(tmp_path, proposals=(Proposal((1, 1, 3, 3), None),))
    result = inference.infer(REQUEST)
    assert result["spatial_envelopes"][0]["confidence"] == pytest.approx(0.9)


def test_no_proposal_does_not_require_depth_or_calibration_materialization(tmp_path):
    inference, _, segmentation = _inference(tmp_path, proposals=())
    (tmp_path / SCENE_REVISION / CAPTURE_ID / "depth.npy").unlink()
    (tmp_path / SCENE_REVISION / CAPTURE_ID / "calibration.json").unlink()
    result = inference.infer(REQUEST)
    assert result["ambiguities"][0]["code"] == "proposal_unavailable"
    assert segmentation.requests == []


@pytest.mark.parametrize(
    ("mask", "depth", "camera_name", "message"),
    [
        (np.zeros((3, 4), dtype=bool), None, "head_camera", "mask is empty"),
        (np.ones((2, 4), dtype=bool), None, "head_camera", "does not match the RGB"),
        (None, np.zeros((3, 4), dtype=np.float32), "head_camera", "no finite positive depth"),
        (None, None, "other_camera", "does not match the observation frame"),
    ],
)
def test_invalid_mask_depth_or_calibration_fails_closed_and_releases_workers(
    tmp_path, mask, depth, camera_name, message
):
    inference, proposal, segmentation = _inference(
        tmp_path, mask=mask, depth=depth, camera_name=camera_name
    )
    with pytest.raises(SingleViewPerceptionError, match=message):
        inference.infer(REQUEST)
    assert proposal.released == 1
    assert segmentation.released == 1


def test_proposal_cleanup_failure_fails_closed_before_segmentation(tmp_path):
    store = _artifacts(tmp_path)
    proposal = ProposalProvider(release_error=True)
    segmentation = SegmentationProvider(np.ones((3, 4), dtype=bool))
    inference = SingleViewPerceptionInference(
        SemanticInference(),
        proposal_provider=proposal,
        segmentation_provider=segmentation,
        localization_provider=NumpyMetricLocalizationProvider(),
        artifact_store=store,
    )
    with pytest.raises(SingleViewPerceptionError, match="proposal provider cleanup failed"):
        inference.infer(REQUEST)
    assert segmentation.requests == []


def test_artifact_store_rejects_paths_outside_the_external_root(tmp_path):
    store = FilesystemPerceptionArtifactStore(tmp_path)
    with pytest.raises(SingleViewPerceptionError, match="invalid"):
        store.resolve_source("artifact://scene-7/../rgb", "rgb")


def test_materialized_artifacts_are_rolled_back_when_later_write_fails(tmp_path):
    class FailingStore(FilesystemPerceptionArtifactStore):
        def materialize_json(self, artifact_ref, value):
            raise SingleViewPerceptionError("injected JSON failure")

    _artifacts(tmp_path)
    inference = SingleViewPerceptionInference(
        SemanticInference(),
        proposal_provider=ProposalProvider(),
        segmentation_provider=SegmentationProvider(np.ones((3, 4), dtype=bool)),
        localization_provider=NumpyMetricLocalizationProvider(),
        artifact_store=FailingStore(tmp_path),
    )
    with pytest.raises(SingleViewPerceptionError, match="injected JSON failure"):
        inference.infer(REQUEST)
    derived = tmp_path / SCENE_REVISION / CAPTURE_ID / "derived"
    assert not derived.exists() or list(derived.iterdir()) == []


def test_worker_ports_enforce_protocol_and_remove_transient_mask(tmp_path):
    class ProposalClient:
        def request(self, payload):
            return {
                "request_id": payload["request_id"],
                "status": "available",
                "proposals": [{"bbox_xyxy_px": [1, 1, 3, 3], "confidence": None}],
            }

    class SegmentationClient:
        def request(self, payload):
            mask_path = tmp_path / "mask.npy"
            np.save(mask_path, np.ones((3, 4), dtype=bool), allow_pickle=False)
            return {
                "request_id": payload["request_id"],
                "status": "available",
                "bbox_xyxy_px": payload["bbox_xyxy_px"],
                "mask_path": str(mask_path),
            }

    proposal = WorkerProposalProvider(ProposalClient()).propose(
        type("Request", (), {
            "observation_ref": OBSERVATION_REF,
            "scene_revision": SCENE_REVISION,
            "entity_ref": "entity://red-block",
            "query": "red block",
            "rgb_path": tmp_path / "rgb.png",
            "width_px": 4,
            "height_px": 3,
        })()
    )[0]
    segment_request = type("Request", (), {
        "observation_ref": OBSERVATION_REF,
        "scene_revision": SCENE_REVISION,
        "entity_ref": "entity://red-block",
        "rgb_path": tmp_path / "rgb.png",
        "width_px": 4,
        "height_px": 3,
        "proposal": proposal,
    })()
    result = WorkerSegmentationProvider(
        SegmentationClient(), worker_artifact_root=tmp_path
    ).segment(segment_request)
    assert proposal.confidence is None
    assert result.mask.shape == (3, 4)
    assert not (tmp_path / "mask.npy").exists()
