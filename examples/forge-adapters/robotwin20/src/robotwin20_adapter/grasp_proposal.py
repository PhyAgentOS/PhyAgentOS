"""Adapter-side grasp proposal port backed by an isolated model worker.

The public PAOS contract carries only observation-bound geometry artifact
references.  This module resolves those references inside the adapter-owned
artifact root, invokes a replaceable worker, and translates normalized 4x4
grasp matrices into provider-neutral Query evidence.  It never imports PAOS,
RoboTwin, SAPIEN, Torch, or a model package and never performs IK, collision
admission, or motion.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping, Protocol
from uuid import uuid4


class GraspProposalAdapterError(RuntimeError):
    """The adapter cannot produce provider-neutral grasp evidence."""


class GraspWorkerClient(Protocol):
    def request(self, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def release(self) -> None: ...


class PointCloudArtifactResolver(Protocol):
    """Provider-neutral resolver for observation-derived point-cloud artifacts."""

    def resolve_point_cloud(self, artifact_ref: str) -> Path: ...


class FilesystemPointCloudArtifactResolver:
    """Resolve only derived Nx3 point clouds under an explicitly external root."""

    def __init__(self, artifact_root: str | Path) -> None:
        root = Path(artifact_root)
        if not root.is_absolute() or not root.is_dir():
            raise ValueError("artifact_root must be an existing absolute directory")
        self.root = root.resolve()

    def resolve_point_cloud(self, artifact_ref: str) -> Path:
        if not isinstance(artifact_ref, str) or not artifact_ref.startswith("artifact://"):
            raise GraspProposalAdapterError("point-cloud artifact reference is invalid")
        parts = artifact_ref.split("//", 1)[1].split("/")
        if len(parts) < 4 or "derived" not in parts or any(not part or part in {".", ".."} for part in parts):
            raise GraspProposalAdapterError("point-cloud artifact reference is invalid")
        path = (self.root.joinpath(*parts)).with_suffix(".npy").resolve()
        if self.root not in path.parents or not path.is_file():
            raise GraspProposalAdapterError("point-cloud artifact is unavailable")
        try:
            import numpy as np

            points = np.asarray(np.load(path, allow_pickle=False), dtype=np.float32)
        except (ImportError, OSError, ValueError) as exc:
            raise GraspProposalAdapterError("point-cloud artifact could not be loaded") from exc
        if points.ndim != 2 or points.shape[1] != 3 or points.shape[0] < 1 or not bool(np.isfinite(points).all()):
            raise GraspProposalAdapterError("point-cloud artifact must be a finite non-empty Nx3 array")
        return path


class GraspGenProposalProvider:
    """Translate a configured GraspGen-compatible worker into the PAOS port."""

    def __init__(
        self,
        client: GraspWorkerClient,
        *,
        artifact_store: PointCloudArtifactResolver,
        max_candidates: int = 24,
        score_threshold: float = 0.0,
        apply_nms: bool = True,
        nms_position_threshold_m: float = 0.005,
        nms_approach_angle_deg: float = 10.0,
        nms_closing_angle_deg: float = 10.0,
        apply_model_collision: bool = False,
    ) -> None:
        if not callable(getattr(client, "request", None)):
            raise TypeError("grasp worker client must expose request(payload)")
        if not callable(getattr(artifact_store, "resolve_point_cloud", None)):
            raise TypeError("artifact_store must expose resolve_point_cloud(artifact_ref)")
        if isinstance(max_candidates, bool) or not isinstance(max_candidates, int) or not 1 <= max_candidates <= 512:
            raise ValueError("max_candidates must be between 1 and 512")
        if not _unit_interval(score_threshold):
            raise ValueError("score_threshold must be between 0 and 1")
        for name, value in (
            ("nms_position_threshold_m", nms_position_threshold_m),
            ("nms_approach_angle_deg", nms_approach_angle_deg),
            ("nms_closing_angle_deg", nms_closing_angle_deg),
        ):
            if not _finite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if not isinstance(apply_nms, bool) or not isinstance(apply_model_collision, bool):
            raise TypeError("grasp filtering flags must be booleans")
        self.client = client
        self.artifact_store = artifact_store
        self.max_candidates = max_candidates
        self.score_threshold = float(score_threshold)
        self.apply_nms = apply_nms
        self.nms_position_threshold_m = float(nms_position_threshold_m)
        self.nms_approach_angle_deg = float(nms_approach_angle_deg)
        self.nms_closing_angle_deg = float(nms_closing_angle_deg)
        self.apply_model_collision = apply_model_collision

    def propose(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(request, Mapping):
            raise GraspProposalAdapterError("grasp request must be an object")
        targets = request.get("targets")
        if not isinstance(targets, list):
            raise GraspProposalAdapterError("grasp request targets must be an array")
        all_candidates: list[dict[str, Any]] = []
        ambiguities: list[dict[str, Any]] = []
        funnel = {"decoded": 0, "canonicalized": 0, "deduplicated": 0, "retained": 0}
        try:
            for target in targets:
                if not isinstance(target, Mapping):
                    raise GraspProposalAdapterError("grasp target must be an object")
                entity_ref = target.get("entity_ref")
                if not isinstance(entity_ref, str) or not entity_ref:
                    raise GraspProposalAdapterError("grasp target entity_ref is invalid")
                geometry = _select_geometry_artifact(target, request)
                points_path = self._resolve_point_cloud(geometry)
                reply = self._invoke_worker(request, target, geometry, points_path)
                raw_candidates, raw_funnel = _validate_worker_reply(reply)
                funnel["decoded"] += raw_funnel["decoded"]
                canonical: list[tuple[Any, float, int]] = []
                for index, item in enumerate(raw_candidates):
                    matrix = _matrix(item.get("matrix"))
                    score = item.get("score")
                    if not _unit_interval(score):
                        raise GraspProposalAdapterError("grasp worker score is invalid")
                    if score < self.score_threshold:
                        continue
                    canonical.append((matrix, float(score), index))
                funnel["canonicalized"] += len(canonical)
                if self.apply_nms:
                    canonical = _nms(
                        canonical,
                        position_threshold_m=self.nms_position_threshold_m,
                        approach_angle_deg=self.nms_approach_angle_deg,
                        closing_angle_deg=self.nms_closing_angle_deg,
                    )
                funnel["deduplicated"] += len(canonical)
                for matrix, score, index in canonical[: self.max_candidates]:
                    all_candidates.append(
                        _candidate(
                            entity_ref=entity_ref,
                            candidate_index=len(all_candidates),
                            matrix=matrix,
                            score=score,
                            frame_id=str(request["frame_id"]),
                            geometry_ref=str(geometry["artifact_ref"]),
                            source_index=index,
                        )
                    )
                funnel["retained"] = len(all_candidates)
                if not canonical:
                    ambiguities.append(
                        {
                            "code": "no_grasp_candidate",
                            "message": "grasp worker produced no candidate above the configured threshold",
                            "entity_refs": [entity_ref],
                        }
                    )
        finally:
            try:
                self.release()
            except Exception as exc:
                raise GraspProposalAdapterError("grasp worker cleanup failed") from exc
        return {
            "candidates": tuple(all_candidates),
            "ambiguities": tuple(ambiguities),
            "funnel": funnel,
            "provider_available": True,
        }

    def release(self) -> None:
        release = getattr(self.client, "release", None)
        if callable(release):
            release()

    def _resolve_point_cloud(self, geometry: Mapping[str, Any]) -> Path:
        if geometry.get("kind") not in {"object_point_cloud", "fused_entity_perception"}:
            raise GraspProposalAdapterError("geometry artifact kind is not graspable")
        try:
            return self.artifact_store.resolve_point_cloud(str(geometry["artifact_ref"]))
        except (KeyError, OSError, ValueError, GraspProposalAdapterError) as exc:
            raise GraspProposalAdapterError("geometry point cloud is unavailable") from exc

    def _invoke_worker(
        self,
        request: Mapping[str, Any],
        target: Mapping[str, Any],
        geometry: Mapping[str, Any],
        points_path: Path,
    ) -> Mapping[str, Any]:
        request_id = uuid4().hex
        reply = self.client.request(
            {
                "schema_version": "paos-grasp-worker/v1",
                "request_id": request_id,
                "provider": "graspgen",
                "model_variant": "ptv3",
                "observation_ref": request["observation_ref"],
                "scene_revision": request["scene_revision"],
                "entity_ref": target["entity_ref"],
                "point_cloud_frame": request["frame_id"],
                "point_units": "m",
                "point_cloud_path": str(points_path),
                "max_candidates": self.max_candidates,
                "score_threshold": self.score_threshold,
                "apply_nms": False,
                "apply_model_collision": self.apply_model_collision,
                "geometry_artifact_ref": geometry["artifact_ref"],
            }
        )
        if not isinstance(reply, Mapping) or reply.get("request_id") != request_id:
            raise GraspProposalAdapterError("grasp worker response identity mismatch")
        return reply


def _select_geometry_artifact(target: Mapping[str, Any], request: Mapping[str, Any]) -> Mapping[str, Any]:
    values = target.get("geometry_artifacts")
    if not isinstance(values, list) or not values:
        raise GraspProposalAdapterError("grasp target has no bound geometry artifact")
    matches = [
        item for item in values
        if isinstance(item, Mapping)
        and item.get("observation_ref") == request.get("observation_ref")
        and item.get("scene_revision") == request.get("scene_revision")
        and item.get("frame_id") == request.get("frame_id")
        and item.get("calibration_ref") == request.get("calibration_ref")
        and item.get("entity_ref") == target.get("entity_ref")
        and item.get("kind") in {"object_point_cloud", "fused_entity_perception"}
    ]
    if len(matches) != 1:
        raise GraspProposalAdapterError("grasp target geometry binding is ambiguous or mismatched")
    return matches[0]


def _validate_worker_reply(reply: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], dict[str, int]]:
    if set(reply) != {"request_id", "status", "candidates", "funnel"}:
        raise GraspProposalAdapterError("grasp worker response fields are invalid")
    if reply.get("status") not in {"available", "empty"}:
        raise GraspProposalAdapterError("grasp worker is unavailable")
    candidates = reply.get("candidates")
    funnel = reply.get("funnel")
    if not isinstance(candidates, list) or not isinstance(funnel, Mapping):
        raise GraspProposalAdapterError("grasp worker response shape is invalid")
    normalized = {}
    for key in ("decoded", "canonicalized", "deduplicated", "retained"):
        value = funnel.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise GraspProposalAdapterError("grasp worker funnel is invalid")
        normalized[key] = value
    if normalized["retained"] != len(candidates) or not (
        normalized["decoded"] >= normalized["canonicalized"] >= normalized["deduplicated"] >= normalized["retained"]
    ):
        raise GraspProposalAdapterError("grasp worker funnel is inconsistent")
    if reply.get("status") == "available" and not candidates:
        raise GraspProposalAdapterError("grasp worker marked an empty result available")
    if reply.get("status") == "empty" and candidates:
        raise GraspProposalAdapterError("grasp worker returned candidates with empty status")
    if any(not isinstance(item, Mapping) or set(item) != {"matrix", "score"} for item in candidates):
        raise GraspProposalAdapterError("grasp worker candidate shape is invalid")
    return candidates, normalized


def _matrix(value: Any) -> Any:
    np = _numpy()
    try:
        matrix = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise GraspProposalAdapterError("grasp matrix is invalid") from exc
    if matrix.shape != (4, 4) or not bool(np.isfinite(matrix).all()):
        raise GraspProposalAdapterError("grasp matrix must be finite 4x4")
    if not bool(np.allclose(matrix[3], [0.0, 0.0, 0.0, 1.0], atol=1e-6)):
        raise GraspProposalAdapterError("grasp matrix homogeneous row is invalid")
    rotation = matrix[:3, :3]
    if not bool(np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-3)) or np.linalg.det(rotation) <= 0:
        raise GraspProposalAdapterError("grasp matrix rotation is invalid")
    return matrix


def _candidate(*, entity_ref: str, candidate_index: int, matrix: Any, score: float, frame_id: str, geometry_ref: str, source_index: int) -> dict[str, Any]:
    rotation = matrix[:3, :3]
    approach = rotation[:, 2]
    return {
        "candidate_ref": f"candidate://{entity_ref.removeprefix('entity://')}/{candidate_index}",
        "entity_ref": entity_ref,
        "grasp_frame": {
            "frame_id": frame_id,
            "unit": "m",
            "position_m": [float(value) for value in matrix[:3, 3]],
            "orientation_xyzw": _quaternion_xyzw(rotation),
        },
        "approach_direction": {
            "frame_id": frame_id,
            "unit": "unitless",
            "vector": [float(value) for value in approach],
        },
        "score": score,
        "confidence": score,
        "provenance": [geometry_ref],
        "qualification": "proposed" if score >= 0.5 else "low_confidence",
    }


def _nms(candidates: list[tuple[Any, float, int]], *, position_threshold_m: float, approach_angle_deg: float, closing_angle_deg: float) -> list[tuple[Any, float, int]]:
    np = _numpy()
    position_sq = position_threshold_m ** 2
    approach_cos = math.cos(math.radians(approach_angle_deg))
    closing_cos = math.cos(math.radians(closing_angle_deg))
    ordered = sorted(candidates, key=lambda item: (-item[1], item[2]))
    kept: list[tuple[Any, float, int]] = []
    for candidate in ordered:
        matrix, _, _ = candidate
        suppressed = False
        for retained, _, _ in kept:
            if float(np.sum((matrix[:3, 3] - retained[:3, 3]) ** 2)) > position_sq:
                continue
            if float(np.dot(matrix[:3, :3][:, 2], retained[:3, :3][:, 2])) < approach_cos:
                continue
            if abs(float(np.dot(matrix[:3, :3][:, 0], retained[:3, :3][:, 0]))) < closing_cos:
                continue
            suppressed = True
            break
        if not suppressed:
            kept.append(candidate)
    return sorted(kept, key=lambda item: (-item[1], item[2]))


def _quaternion_xyzw(rotation: Any) -> list[float]:
    # Stable matrix-to-quaternion conversion; output is normalized and finite.
    trace = float(rotation[0, 0] + rotation[1, 1] + rotation[2, 2])
    if trace > 0:
        scale = math.sqrt(trace + 1.0) * 2
        w = 0.25 * scale
        x = (rotation[2, 1] - rotation[1, 2]) / scale
        y = (rotation[0, 2] - rotation[2, 0]) / scale
        z = (rotation[1, 0] - rotation[0, 1]) / scale
    else:
        index = max(range(3), key=lambda i: float(rotation[i, i]))
        if index == 0:
            scale = math.sqrt(1.0 + rotation[0, 0] - rotation[1, 1] - rotation[2, 2]) * 2
            x, y, z, w = 0.25 * scale, (rotation[0, 1] + rotation[1, 0]) / scale, (rotation[0, 2] + rotation[2, 0]) / scale, (rotation[2, 1] - rotation[1, 2]) / scale
        elif index == 1:
            scale = math.sqrt(1.0 + rotation[1, 1] - rotation[0, 0] - rotation[2, 2]) * 2
            x, y, z, w = (rotation[0, 1] + rotation[1, 0]) / scale, 0.25 * scale, (rotation[1, 2] + rotation[2, 1]) / scale, (rotation[0, 2] - rotation[2, 0]) / scale
        else:
            scale = math.sqrt(1.0 + rotation[2, 2] - rotation[0, 0] - rotation[1, 1]) * 2
            x, y, z, w = (rotation[0, 2] + rotation[2, 0]) / scale, (rotation[1, 2] + rotation[2, 1]) / scale, 0.25 * scale, (rotation[1, 0] - rotation[0, 1]) / scale
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if not _finite(norm) or norm <= 1e-9:
        raise GraspProposalAdapterError("grasp orientation could not be normalized")
    return [float(value / norm) for value in (x, y, z, w)]


def _unit_interval(value: Any) -> bool:
    return _finite(value) and 0 <= float(value) <= 1


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _numpy() -> Any:
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - adapter preflight owns this branch
        raise GraspProposalAdapterError("NumPy is required only in the isolated grasp adapter") from exc
    return np


__all__ = [
    "FilesystemPointCloudArtifactResolver",
    "GraspGenProposalProvider",
    "GraspProposalAdapterError",
    "GraspWorkerClient",
    "PointCloudArtifactResolver",
]
