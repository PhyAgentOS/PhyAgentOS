from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy", reason="worker contract tests run in the adapter environment")
PIL = pytest.importorskip("PIL.Image", reason="worker contract tests require Pillow")

RUNTIME = Path(__file__).resolve().parents[1] / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))


def _module(name):
    spec = importlib.util.spec_from_file_location(name, RUNTIME / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_locateanything_worker_accepts_native_box_syntax_without_inventing_score(tmp_path):
    module = _module("locateanything_worker")
    image_path = tmp_path / "rgb.png"
    PIL.new("RGB", (100, 50)).save(image_path)
    worker = module.LocateAnythingProposalWorker(
        model_id="model",
        revision="revision",
        device="cpu",
        cache_dir=tmp_path / "cache",
        modules_cache_dir=tmp_path / "modules",
        generation_mode="fast",
        max_new_tokens=32,
        repetition_penalty=1.1,
        temperature=0.7,
        top_p=0.9,
        decode_seed=0,
        local_files_only=True,
    )
    worker._generate = lambda image, query: "<box><100><200><900><800></box>"
    reply = worker.handle(
        {
            "request_id": "request-1",
            "operation": "propose_2d_boxes",
            "observation_ref": "observation://scene/camera",
            "scene_revision": "scene",
            "entity_ref": "entity://block",
            "query": "red block",
            "rgb_path": str(image_path),
            "image_size_px": [100, 50],
        }
    )
    assert reply == {
        "request_id": "request-1",
        "status": "available",
        "proposals": [{"bbox_xyxy_px": [10, 10, 90, 40], "confidence": None}],
    }


@pytest.mark.parametrize("answer", ["no box", "<box><900><200><100><800></box>", "<box>none</box><box><1><2><3><4></box>"])
def test_locateanything_parser_rejects_ambiguous_or_invalid_results(answer):
    module = _module("locateanything_worker")
    with pytest.raises(ValueError):
        module._parse_boxes(answer, 100, 50)


def test_sam2_worker_materializes_only_a_box_bound_mask(tmp_path):
    module = _module("sam2_worker")
    repo = tmp_path / "sam2"
    source_root = tmp_path / "captures"
    worker_root = tmp_path / "worker"
    repo.mkdir()
    source_root.mkdir()
    checkpoint = repo / "model.pt"
    checkpoint.write_bytes(b"checkpoint")
    image_path = source_root / "rgb.png"
    PIL.new("RGB", (4, 3)).save(image_path)

    class Predictor:
        def set_image(self, image):
            assert image.shape == (3, 4, 3)

        def predict(self, **kwargs):
            assert kwargs["box"].tolist() == [[1.0, 1.0, 3.0, 3.0]]
            return np.ones((1, 3, 4), dtype=bool), np.array([0.8]), None

    worker = module.Sam2BoxWorker(
        repo_root=repo,
        model_config="configs/model.yaml",
        checkpoint=checkpoint,
        device="cpu",
        source_artifact_root=source_root,
        worker_artifact_root=worker_root,
    )
    worker._predictor = Predictor()
    reply = worker.handle(
        {
            "request_id": "request-1",
            "operation": "segment_box",
            "observation_ref": "observation://scene/camera",
            "scene_revision": "scene",
            "entity_ref": "entity://block",
            "rgb_path": str(image_path),
            "image_size_px": [4, 3],
            "bbox_xyxy_px": [1, 1, 3, 3],
        }
    )
    assert reply["status"] == "available"
    assert reply["bbox_xyxy_px"] == [1, 1, 3, 3]
    assert np.load(reply["mask_path"], allow_pickle=False).shape == (3, 4)


def test_sam2_worker_rejects_rgb_outside_source_root(tmp_path):
    module = _module("sam2_worker")
    repo = tmp_path / "sam2"
    source_root = tmp_path / "captures"
    repo.mkdir()
    source_root.mkdir()
    checkpoint = repo / "model.pt"
    checkpoint.write_bytes(b"checkpoint")
    outside = tmp_path / "outside.png"
    PIL.new("RGB", (4, 3)).save(outside)
    worker = module.Sam2BoxWorker(
        repo_root=repo,
        model_config="configs/model.yaml",
        checkpoint=checkpoint,
        device="cpu",
        source_artifact_root=source_root,
        worker_artifact_root=tmp_path / "worker",
    )
    worker._predictor = object()
    reply = worker.handle(
        {
            "request_id": "request-1",
            "operation": "segment_box",
            "observation_ref": "observation://scene/camera",
            "scene_revision": "scene",
            "entity_ref": "entity://block",
            "rgb_path": str(outside),
            "image_size_px": [4, 3],
            "bbox_xyxy_px": [1, 1, 3, 3],
        }
    )
    assert reply["status"] == "unavailable"
    assert reply["mask_path"] is None
