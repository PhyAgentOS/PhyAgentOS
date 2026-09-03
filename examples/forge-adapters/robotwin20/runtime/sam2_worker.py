"""Box-prompted SAM2 worker for the dedicated segmentation environment."""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Mapping

from worker_protocol import serve

_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class Sam2BoxWorker:
    def __init__(
        self,
        *,
        repo_root: Path,
        model_config: str,
        checkpoint: Path,
        device: str,
        source_artifact_root: Path,
        worker_artifact_root: Path,
    ) -> None:
        if not repo_root.is_dir():
            raise ValueError("SAM2 repo_root is unavailable")
        if not checkpoint.is_file():
            raise ValueError("SAM2 checkpoint is unavailable")
        if not source_artifact_root.is_absolute() or not worker_artifact_root.is_absolute():
            raise ValueError("artifact roots must be absolute")
        self.repo_root = repo_root.resolve()
        self.model_config = model_config
        self.checkpoint = checkpoint.resolve()
        self.device = device
        self.source_artifact_root = source_artifact_root.resolve()
        self.worker_artifact_root = worker_artifact_root.resolve()
        self._predictor: Any = None

    def load(self) -> None:
        if self._predictor is not None:
            return
        self.worker_artifact_root.mkdir(parents=True, exist_ok=True)
        if str(self.repo_root) not in sys.path:
            sys.path.insert(0, str(self.repo_root))
        with contextlib.redirect_stdout(sys.stderr):
            import torch
            from sam2.build_sam import build_sam2
            from sam2.sam2_image_predictor import SAM2ImagePredictor

            if self.device.startswith("cuda") and not torch.cuda.is_available():
                raise RuntimeError("configured CUDA device is unavailable")
            model = build_sam2(
                self.model_config,
                str(self.checkpoint),
                device=self.device,
                mode="eval",
            )
            self._predictor = SAM2ImagePredictor(model)

    def handle(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        request_id = request["request_id"]
        bbox_value = request.get("bbox_xyxy_px")
        unavailable = {
            "request_id": request_id,
            "status": "unavailable",
            "bbox_xyxy_px": bbox_value,
            "mask_path": None,
        }
        if set(request) != {
            "request_id", "operation", "observation_ref", "scene_revision",
            "entity_ref", "rgb_path", "image_size_px", "bbox_xyxy_px",
        } or request.get("operation") != "segment_box":
            return unavailable
        try:
            import numpy as np
            from PIL import Image

            if not isinstance(request_id, str) or _REQUEST_ID.fullmatch(request_id) is None:
                raise ValueError("request_id is invalid")
            rgb_path = _bounded_source(request.get("rgb_path"), self.source_artifact_root)
            width, height = _image_size(request.get("image_size_px"))
            bbox = _bbox(bbox_value, width, height)
            with Image.open(rgb_path) as source:
                image = np.asarray(source.convert("RGB"))
            if tuple(image.shape[:2]) != (height, width):
                raise ValueError("RGB dimensions do not match request")
            with contextlib.redirect_stdout(sys.stderr):
                self._predictor.set_image(image)
                masks, _scores, _logits = self._predictor.predict(
                    point_coords=None,
                    point_labels=None,
                    box=np.asarray([bbox], dtype=np.float32),
                    multimask_output=False,
                )
            mask = np.asarray(masks)
            while mask.ndim > 2 and mask.shape[0] == 1:
                mask = mask[0]
            if mask.ndim != 2 or tuple(mask.shape) != (height, width):
                raise ValueError("SAM2 returned an invalid mask shape")
            mask = mask.astype(bool, copy=False)
            if not bool(mask.any()):
                raise ValueError("SAM2 returned an empty mask")
            output = self.worker_artifact_root / f"mask-{request_id}.npy"
            _atomic_numpy(output, mask)
            return {
                "request_id": request_id,
                "status": "available",
                "bbox_xyxy_px": list(bbox),
                "mask_path": str(output),
            }
        except Exception as exc:
            print(f"SAM2 inference failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return unavailable


def _bounded_source(value: Any, root: Path) -> Path:
    path = Path(value).resolve() if isinstance(value, str) and Path(value).is_absolute() else None
    if path is None or root not in path.parents or not path.is_file():
        raise ValueError("rgb_path is outside source_artifact_root or unavailable")
    return path


def _image_size(value: Any) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2 or any(
        isinstance(item, bool) or not isinstance(item, int) or item < 1 for item in value
    ):
        raise ValueError("image_size_px must contain positive integer width and height")
    return value[0], value[1]


def _bbox(value: Any, width: int, height: int) -> tuple[int, int, int, int]:
    if not isinstance(value, list) or len(value) != 4 or any(
        isinstance(item, bool) or not isinstance(item, int) for item in value
    ):
        raise ValueError("bbox_xyxy_px must contain four integers")
    box = tuple(value)
    if not (0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height):
        raise ValueError("bbox_xyxy_px is outside the image")
    return box


def _atomic_numpy(path: Path, value: Any) -> None:
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix=".tmp-", delete=False) as handle:
            temporary = Path(handle.name)
            np.save(handle, value, allow_pickle=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--model-config", required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--source-artifact-root", type=Path, required=True)
    parser.add_argument("--worker-artifact-root", type=Path, required=True)
    args = parser.parse_args()
    worker = Sam2BoxWorker(
        repo_root=args.repo_root.expanduser().resolve(),
        model_config=args.model_config,
        checkpoint=args.checkpoint.expanduser().resolve(),
        device=args.device,
        source_artifact_root=args.source_artifact_root.expanduser().resolve(),
        worker_artifact_root=args.worker_artifact_root.expanduser().resolve(),
    )
    return serve("sam2", worker.load, worker.handle)


if __name__ == "__main__":
    raise SystemExit(main())
