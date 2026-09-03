"""Isolated GraspGen-compatible JSONL worker.

This process is deliberately outside PAOS and the RoboTwin simulator.  It
accepts an adapter-resolved point-cloud path and returns only raw normalized
grasp matrices and scores.  Model imports are lazy and failures are reported
as worker-unavailable rather than fabricated candidates.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Mapping

from worker_protocol import serve


class WorkerUnavailableError(RuntimeError):
    pass


_MODEL: Any | None = None
_OPTIONS: argparse.Namespace | None = None


def _load() -> None:
    global _MODEL
    assert _OPTIONS is not None
    checkpoint = Path(_OPTIONS.checkpoint).expanduser().resolve()
    config = Path(_OPTIONS.config).expanduser().resolve()
    if not checkpoint.is_file() or not config.is_file():
        raise WorkerUnavailableError("grasp model checkpoint or config is unavailable")
    if _OPTIONS.source_root:
        source = str(Path(_OPTIONS.source_root).expanduser().resolve())
        if source not in sys.path:
            sys.path.insert(0, source)
    try:
        from grasp_gen.grasp_server import GraspGenSampler, load_grasp_cfg

        cfg = load_grasp_cfg(str(config))
        cfg.eval.checkpoint = str(checkpoint)
        _MODEL = GraspGenSampler(cfg)
    except Exception as exc:  # noqa: BLE001
        raise WorkerUnavailableError("grasp model initialization failed") from exc


def _handle(request: Mapping[str, Any]) -> Mapping[str, Any]:
    if request.get("schema_version") != "paos-grasp-worker/v1":
        raise WorkerUnavailableError("grasp request schema_version is unsupported")
    if request.get("provider") != "graspgen" or request.get("model_variant") != "ptv3":
        raise WorkerUnavailableError("grasp request provider/variant is unsupported")
    point_path = request.get("point_cloud_path")
    if not isinstance(point_path, str) or not Path(point_path).is_absolute():
        raise WorkerUnavailableError("grasp point_cloud_path must be absolute")
    try:
        import numpy as np

        points = np.asarray(np.load(Path(point_path), allow_pickle=False), dtype=np.float32)
    except (ImportError, OSError, ValueError) as exc:
        raise WorkerUnavailableError("grasp point cloud could not be loaded") from exc
    if points.ndim != 2 or points.shape[1] != 3 or points.shape[0] < 1 or not bool(np.isfinite(points).all()):
        raise WorkerUnavailableError("grasp point cloud must be a finite non-empty Nx3 array")
    max_candidates = request.get("max_candidates")
    threshold = request.get("score_threshold")
    if isinstance(max_candidates, bool) or not isinstance(max_candidates, int) or not 1 <= max_candidates <= 512:
        raise WorkerUnavailableError("max_candidates is invalid")
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 <= float(threshold) <= 1:
        raise WorkerUnavailableError("score_threshold is invalid")
    if request.get("apply_model_collision") is True:
        raise WorkerUnavailableError("model collision filtering requires an explicit worker profile implementation")
    if _MODEL is None:
        raise WorkerUnavailableError("grasp model is unavailable")
    try:
        grasps, scores = _MODEL.run_inference(
            points,
            _MODEL,
            grasp_threshold=float(threshold),
            num_grasps=max_candidates,
            topk_num_grasps=max_candidates,
            min_grasps=1,
            max_tries=1,
        )
        matrices = np.asarray(grasps.detach().cpu() if hasattr(grasps, "detach") else grasps, dtype=np.float64)
        values = np.asarray(scores.detach().cpu() if hasattr(scores, "detach") else scores, dtype=np.float64).reshape(-1)
    except Exception as exc:  # noqa: BLE001
        raise WorkerUnavailableError("grasp model inference failed") from exc
    if matrices.ndim != 3 or matrices.shape[1:] != (4, 4) or values.shape[0] != matrices.shape[0]:
        raise WorkerUnavailableError("grasp model returned malformed candidates")
    candidates = []
    for matrix, score in zip(matrices, values, strict=True):
        if not bool(np.isfinite(matrix).all()) or not np.isfinite(score):
            raise WorkerUnavailableError("grasp model returned non-finite candidates")
        if float(score) < float(threshold):
            continue
        candidates.append({"matrix": matrix.tolist(), "score": float(score)})
    candidates = candidates[:max_candidates]
    return {
        "request_id": request["request_id"],
        "status": "available" if candidates else "empty",
        "candidates": candidates,
        "funnel": {
            "decoded": int(matrices.shape[0]),
            "canonicalized": len(candidates),
            "deduplicated": len(candidates),
            "retained": len(candidates),
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stdio-worker", action="store_true")
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--source-root")
    return parser


def main(argv: list[str] | None = None) -> int:
    global _OPTIONS
    _OPTIONS = _parser().parse_args(argv)
    if not _OPTIONS.stdio_worker:
        raise SystemExit("--stdio-worker is required")
    return serve("graspgen", _load, _handle, schema_version="paos-grasp-worker/v1")


if __name__ == "__main__":
    raise SystemExit(main())
