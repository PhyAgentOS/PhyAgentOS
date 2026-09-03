from pathlib import Path

import numpy as np
import pytest

from robotwin20_adapter.grasp_proposal import (
    FilesystemPointCloudArtifactResolver,
    GraspGenProposalProvider,
    GraspProposalAdapterError,
)

REQUEST = {
    "observation_ref": "observation://scene-7/camera_front",
    "scene_revision": "scene-7",
    "frame_id": "camera_front",
    "calibration_ref": "calibration://front/v3",
    "freshness_ms": 20,
    "max_age_ms": 100,
    "targets": [
        {
            "entity_ref": "entity://bottle-1",
            "category": "container",
            "confidence": 0.9,
            "spatial_envelope": {
                "frame_id": "camera_front",
                "unit": "m",
                "min_xyz_m": [0.1, -0.2, 0.0],
                "max_xyz_m": [0.2, -0.1, 0.3],
                "confidence": 0.8,
                "provenance": ["artifact://scene-7/camera_front/rgb"],
            },
            "geometry_artifacts": [
                {
                    "artifact_ref": "artifact://scene-7/camera_front/derived/points-bottle",
                    "kind": "object_point_cloud",
                    "observation_ref": "observation://scene-7/camera_front",
                    "scene_revision": "scene-7",
                    "entity_ref": "entity://bottle-1",
                    "frame_id": "camera_front",
                    "calibration_ref": "calibration://front/v3",
                    "provenance": ["artifact://scene-7/camera_front/depth"],
                }
            ],
        }
    ],
}


class Worker:
    def __init__(self):
        self.requests = []
        self.released = False

    def request(self, payload):
        self.requests.append(payload)
        return {
            "request_id": payload["request_id"],
            "status": "available",
            "candidates": [
                {"matrix": np.eye(4).tolist(), "score": 0.8},
                {"matrix": (np.eye(4) + np.diag([0, 0, 0, 0])).tolist(), "score": 0.7},
            ],
            "funnel": {"decoded": 2, "canonicalized": 2, "deduplicated": 2, "retained": 2},
        }

    def release(self):
        self.released = True


class CleanupFailureWorker(Worker):
    def release(self):
        raise RuntimeError("shutdown failed")


def _store(tmp_path: Path):
    path = tmp_path / "scene-7" / "camera_front" / "derived"
    path.mkdir(parents=True)
    np.save(path / "points-bottle.npy", np.asarray([[0.1, 0.0, 0.5], [0.11, 0.0, 0.5]], dtype=np.float32))
    return FilesystemPointCloudArtifactResolver(tmp_path)


def test_graspgen_provider_maps_bound_geometry_to_neutral_candidates(tmp_path):
    worker = Worker()
    provider = GraspGenProposalProvider(worker, artifact_store=_store(tmp_path), apply_nms=True)
    data = provider.propose(REQUEST)
    assert len(data["candidates"]) == 1
    assert data["candidates"][0]["grasp_frame"]["frame_id"] == "camera_front"
    assert data["candidates"][0]["provenance"] == [
        "artifact://scene-7/camera_front/derived/points-bottle"
    ]
    assert data["funnel"] == {"decoded": 2, "canonicalized": 2, "deduplicated": 1, "retained": 1}
    assert worker.requests[0]["provider"] == "graspgen"
    assert worker.requests[0]["point_units"] == "m"
    assert worker.released is True


def test_missing_geometry_fails_closed(tmp_path):
    provider = GraspGenProposalProvider(Worker(), artifact_store=_store(tmp_path))
    request = {**REQUEST, "targets": [{k: v for k, v in REQUEST["targets"][0].items() if k != "geometry_artifacts"}]}
    with pytest.raises(GraspProposalAdapterError, match="no bound geometry"):
        provider.propose(request)


def test_geometry_binding_mismatch_is_rejected(tmp_path):
    provider = GraspGenProposalProvider(Worker(), artifact_store=_store(tmp_path))
    target = dict(REQUEST["targets"][0])
    target["geometry_artifacts"] = [dict(target["geometry_artifacts"][0], scene_revision="other")]
    with pytest.raises(GraspProposalAdapterError, match="ambiguous or mismatched"):
        provider.propose({**REQUEST, "targets": [target]})


def test_worker_cleanup_failure_is_fail_closed(tmp_path):
    provider = GraspGenProposalProvider(CleanupFailureWorker(), artifact_store=_store(tmp_path))
    with pytest.raises(GraspProposalAdapterError, match="cleanup failed"):
        provider.propose(REQUEST)
