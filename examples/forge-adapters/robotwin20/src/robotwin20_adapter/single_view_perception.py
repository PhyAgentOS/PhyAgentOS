"""Adapter-owned single-view proposal, segmentation, and RGB-D localization.

The module is a clean-room provider composition. It does not import PAOS,
RoboTwin, SAPIEN, Torch, LocateAnything, or SAM2. Deployment profiles inject
model workers and an external artifact root; only provider-neutral mappings
cross back into the generic ``scene.understand`` endpoint.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import urlparse
from uuid import uuid4


class SingleViewPerceptionError(RuntimeError):
    """The adapter cannot produce a contract-valid perception result."""


@dataclass(frozen=True)
class Proposal:
    bbox_xyxy_px: tuple[int, int, int, int]
    confidence: float | None


@dataclass(frozen=True)
class ProposalRequest:
    observation_ref: str
    scene_revision: str
    entity_ref: str
    query: str
    frame_id: str
    rgb_artifact_ref: str
    rgb_path: Path
    width_px: int
    height_px: int


@dataclass(frozen=True)
class SegmentationRequest:
    observation_ref: str
    scene_revision: str
    entity_ref: str
    frame_id: str
    rgb_artifact_ref: str
    rgb_path: Path
    width_px: int
    height_px: int
    proposal: Proposal


@dataclass(frozen=True)
class SegmentationResult:
    mask: Any
    proposal_bbox_xyxy_px: tuple[int, int, int, int]


@dataclass(frozen=True)
class LocalizationRequest:
    mask: Any
    depth: Any
    calibration: Mapping[str, Any]
    frame_id: str


@dataclass(frozen=True)
class LocalizationResult:
    points_xyz_m: Any
    min_xyz_m: tuple[float, float, float]
    max_xyz_m: tuple[float, float, float]
    valid_depth_ratio: float


class ProposalProvider(Protocol):
    def propose(self, request: ProposalRequest) -> Sequence[Proposal]: ...


class SegmentationProvider(Protocol):
    def segment(self, request: SegmentationRequest) -> SegmentationResult: ...


class MetricLocalizationProvider(Protocol):
    def localize(self, request: LocalizationRequest) -> LocalizationResult: ...


class WorkerClient(Protocol):
    def request(self, payload: Mapping[str, Any]) -> Mapping[str, Any]: ...


class WorkerProposalProvider:
    """Translate one configured proposal worker into the adapter port."""

    def __init__(self, client: WorkerClient) -> None:
        if not callable(getattr(client, "request", None)):
            raise TypeError("proposal worker client must expose request(payload)")
        self.client = client

    def propose(self, request: ProposalRequest) -> tuple[Proposal, ...]:
        request_id = uuid4().hex
        reply = self.client.request(
            {
                "request_id": request_id,
                "operation": "propose_2d_boxes",
                "observation_ref": request.observation_ref,
                "scene_revision": request.scene_revision,
                "entity_ref": request.entity_ref,
                "query": request.query,
                "rgb_path": str(request.rgb_path),
                "image_size_px": [request.width_px, request.height_px],
            }
        )
        if not isinstance(reply, Mapping) or set(reply) != {"request_id", "status", "proposals"}:
            raise SingleViewPerceptionError("proposal worker returned an invalid response")
        if reply.get("request_id") != request_id:
            raise SingleViewPerceptionError("proposal worker request identity mismatch")
        if reply.get("status") not in {"available", "empty"}:
            raise SingleViewPerceptionError("proposal worker reported unavailable")
        raw = reply.get("proposals")
        if not isinstance(raw, list) or (reply["status"] == "empty" and raw):
            raise SingleViewPerceptionError("proposal worker proposals are invalid")
        proposals = tuple(_normalize_proposal(item, request.width_px, request.height_px) for item in raw)
        if reply["status"] == "available" and not proposals:
            raise SingleViewPerceptionError("proposal worker available response is empty")
        return proposals

    def release(self) -> None:
        release = getattr(self.client, "release", None)
        if callable(release):
            release()


class WorkerSegmentationProvider:
    """Materialize a configured segmentation worker's bounded NumPy mask."""

    def __init__(self, client: WorkerClient, *, worker_artifact_root: str | os.PathLike[str]) -> None:
        if not callable(getattr(client, "request", None)):
            raise TypeError("segmentation worker client must expose request(payload)")
        root = Path(worker_artifact_root)
        if not root.is_absolute():
            raise ValueError("worker_artifact_root must be absolute")
        self.client = client
        self.worker_artifact_root = root.resolve()

    def segment(self, request: SegmentationRequest) -> SegmentationResult:
        request_id = uuid4().hex
        bbox = list(request.proposal.bbox_xyxy_px)
        reply = self.client.request(
            {
                "request_id": request_id,
                "operation": "segment_box",
                "observation_ref": request.observation_ref,
                "scene_revision": request.scene_revision,
                "entity_ref": request.entity_ref,
                "rgb_path": str(request.rgb_path),
                "image_size_px": [request.width_px, request.height_px],
                "bbox_xyxy_px": bbox,
            }
        )
        if not isinstance(reply, Mapping) or set(reply) != {
            "request_id", "status", "bbox_xyxy_px", "mask_path"
        }:
            raise SingleViewPerceptionError("segmentation worker returned an invalid response")
        if reply.get("request_id") != request_id or reply.get("status") != "available":
            raise SingleViewPerceptionError("segmentation worker did not return an available mask")
        if reply.get("bbox_xyxy_px") != bbox:
            raise SingleViewPerceptionError("segmentation worker changed the proposal bbox")
        path = Path(reply.get("mask_path")) if isinstance(reply.get("mask_path"), str) else None
        if path is None or not path.is_absolute():
            raise SingleViewPerceptionError("segmentation worker mask path is invalid")
        resolved = path.resolve()
        if self.worker_artifact_root not in resolved.parents or not resolved.is_file():
            raise SingleViewPerceptionError("segmentation worker mask escapes its artifact root")
        np = _numpy()
        try:
            mask = np.load(resolved, allow_pickle=False)
        except (OSError, ValueError) as exc:
            raise SingleViewPerceptionError("segmentation worker mask could not be loaded") from exc
        finally:
            resolved.unlink(missing_ok=True)
        return SegmentationResult(mask=mask, proposal_bbox_xyxy_px=request.proposal.bbox_xyxy_px)

    def release(self) -> None:
        release = getattr(self.client, "release", None)
        if callable(release):
            release()


class NumpyMetricLocalizationProvider:
    """Back-project one current-observation mask into the camera frame."""

    def __init__(self, *, depth_scale_to_m: float = 0.001, max_points: int = 200_000) -> None:
        if not math.isfinite(depth_scale_to_m) or depth_scale_to_m <= 0:
            raise ValueError("depth_scale_to_m must be finite and positive")
        if isinstance(max_points, bool) or not isinstance(max_points, int) or max_points < 1:
            raise ValueError("max_points must be a positive integer")
        self.depth_scale_to_m = depth_scale_to_m
        self.max_points = max_points

    def localize(self, request: LocalizationRequest) -> LocalizationResult:
        np = _numpy()
        mask = np.asarray(request.mask)
        depth = np.asarray(request.depth, dtype=np.float64)
        if mask.ndim != 2 or depth.ndim != 2 or mask.shape != depth.shape:
            raise SingleViewPerceptionError("mask and depth must be aligned 2D arrays")
        mask = mask.astype(bool, copy=False)
        if not bool(mask.any()):
            raise SingleViewPerceptionError("segmentation mask is empty")
        if request.calibration.get("camera_name") != request.frame_id:
            raise SingleViewPerceptionError("calibration camera does not match the observation frame")
        intrinsic = _finite_matrix(request.calibration.get("intrinsic_cv"), (3, 3), "intrinsic_cv")
        extrinsic = request.calibration.get("extrinsic_cv")
        if extrinsic is None:
            raise SingleViewPerceptionError("calibration lacks extrinsic_cv")
        extrinsic_array = np.asarray(extrinsic, dtype=np.float64)
        if extrinsic_array.shape not in {(3, 4), (4, 4)} or not bool(np.isfinite(extrinsic_array).all()):
            raise SingleViewPerceptionError("extrinsic_cv must be a finite 3x4 or 4x4 matrix")
        fx, fy = float(intrinsic[0, 0]), float(intrinsic[1, 1])
        cx, cy = float(intrinsic[0, 2]), float(intrinsic[1, 2])
        if fx <= 0 or fy <= 0:
            raise SingleViewPerceptionError("camera focal lengths must be positive")
        ys, xs = np.nonzero(mask)
        raw_depth = depth[ys, xs]
        valid = np.isfinite(raw_depth) & (raw_depth > 0)
        if not bool(valid.any()):
            raise SingleViewPerceptionError("mask contains no finite positive depth")
        valid_depth_ratio = float(valid.sum() / raw_depth.size)
        xs, ys = xs[valid], ys[valid]
        z = raw_depth[valid] * self.depth_scale_to_m
        points = np.stack(((xs - cx) * z / fx, (ys - cy) * z / fy, z), axis=1)
        if len(points) > self.max_points:
            indices = np.linspace(0, len(points) - 1, self.max_points, dtype=np.int64)
            points = points[indices]
        minimum = tuple(float(value) for value in points.min(axis=0))
        maximum = tuple(float(value) for value in points.max(axis=0))
        return LocalizationResult(
            points_xyz_m=points.astype(np.float32, copy=False),
            min_xyz_m=minimum,
            max_xyz_m=maximum,
            valid_depth_ratio=valid_depth_ratio,
        )


class FilesystemPerceptionArtifactStore:
    """Resolve observation artifacts and atomically materialize derived results."""

    _SOURCE_LEAVES = {"rgb": "rgb.png", "depth": "depth.npy", "calibration": "calibration.json"}

    def __init__(self, artifact_root: str | os.PathLike[str]) -> None:
        root = Path(artifact_root)
        if not root.is_absolute():
            raise ValueError("artifact_root must be absolute")
        self.root = root.resolve()

    def resolve_source(self, artifact_ref: str, expected_leaf: str) -> Path:
        if expected_leaf not in self._SOURCE_LEAVES:
            raise ValueError("unsupported source artifact kind")
        parts = _artifact_parts(artifact_ref)
        if parts[-1] != expected_leaf:
            raise SingleViewPerceptionError(f"expected {expected_leaf} artifact")
        path = (self.root.joinpath(*parts[:-1]) / self._SOURCE_LEAVES[expected_leaf]).resolve()
        if self.root not in path.parents or not path.is_file():
            raise SingleViewPerceptionError(f"{expected_leaf} artifact is unavailable")
        return path

    def image_size(self, rgb_path: Path) -> tuple[int, int]:
        try:
            header = rgb_path.read_bytes()[:24]
        except OSError as exc:
            raise SingleViewPerceptionError("RGB artifact could not be read") from exc
        if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
            raise SingleViewPerceptionError("RGB artifact must be a valid PNG")
        width = int.from_bytes(header[16:20], "big")
        height = int.from_bytes(header[20:24], "big")
        if width < 1 or height < 1:
            raise SingleViewPerceptionError("RGB artifact has invalid dimensions")
        return width, height

    def load_depth(self, artifact_ref: str) -> Any:
        np = _numpy()
        path = self.resolve_source(artifact_ref, "depth")
        try:
            return np.load(path, allow_pickle=False)
        except (OSError, ValueError) as exc:
            raise SingleViewPerceptionError("depth artifact could not be loaded") from exc

    def load_point_cloud(self, artifact_ref: str) -> Any:
        """Load a provider-neutral derived object point cloud inside the artifact root."""
        np = _numpy()
        parts = _artifact_parts(artifact_ref)
        if parts[-2:-1] != ("derived",):
            raise SingleViewPerceptionError("point-cloud artifact must be a derived artifact")
        path = self._derived_path(artifact_ref, ".npy")
        if not path.is_file():
            raise SingleViewPerceptionError("point-cloud artifact is unavailable")
        try:
            points = np.asarray(np.load(path, allow_pickle=False), dtype=np.float32)
        except (OSError, ValueError) as exc:
            raise SingleViewPerceptionError("point-cloud artifact could not be loaded") from exc
        if points.ndim != 2 or points.shape[1] != 3 or points.shape[0] < 1:
            raise SingleViewPerceptionError("point-cloud artifact must be a non-empty Nx3 array")
        if not bool(np.isfinite(points).all()):
            raise SingleViewPerceptionError("point-cloud artifact contains non-finite values")
        return points

    def load_calibration(self, calibration_ref: str) -> Mapping[str, Any]:
        path = self.resolve_source(calibration_ref, "calibration")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SingleViewPerceptionError("calibration artifact could not be loaded") from exc
        if not isinstance(value, Mapping):
            raise SingleViewPerceptionError("calibration artifact must contain an object")
        return value

    def materialize_numpy(self, artifact_ref: str, value: Any) -> None:
        np = _numpy()
        path = self._derived_path(artifact_ref, ".npy")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(dir=path.parent, prefix=".tmp-", delete=False) as handle:
                temporary = Path(handle.name)
                np.save(handle, value, allow_pickle=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except (OSError, ValueError) as exc:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise SingleViewPerceptionError("derived NumPy artifact could not be materialized") from exc

    def materialize_json(self, artifact_ref: str, value: Mapping[str, Any]) -> None:
        path = self._derived_path(artifact_ref, ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, prefix=".tmp-", delete=False
            ) as handle:
                temporary = Path(handle.name)
                json.dump(value, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except (OSError, TypeError, ValueError) as exc:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise SingleViewPerceptionError("derived JSON artifact could not be materialized") from exc

    def discard(self, artifact_ref: str, suffix: str) -> None:
        if suffix not in {".npy", ".json"}:
            raise ValueError("unsupported derived artifact suffix")
        try:
            self._derived_path(artifact_ref, suffix).unlink(missing_ok=True)
        except OSError as exc:
            raise SingleViewPerceptionError("derived artifact rollback failed") from exc

    def _derived_path(self, artifact_ref: str, suffix: str) -> Path:
        parts = _artifact_parts(artifact_ref)
        if "derived" not in parts:
            raise SingleViewPerceptionError("derived artifact ref lacks derived namespace")
        path = self.root.joinpath(*parts).with_suffix(suffix).resolve()
        if self.root not in path.parents:
            raise SingleViewPerceptionError("derived artifact path escapes artifact_root")
        return path


class SingleViewPerceptionInference:
    """Compose semantic claims with replaceable single-view geometry providers."""

    def __init__(
        self,
        semantic_inference: Any,
        *,
        proposal_provider: ProposalProvider,
        segmentation_provider: SegmentationProvider,
        localization_provider: MetricLocalizationProvider,
        artifact_store: FilesystemPerceptionArtifactStore,
    ) -> None:
        infer = getattr(semantic_inference, "infer", None)
        if not callable(infer) and not callable(semantic_inference):
            raise TypeError("semantic_inference must expose infer(request) or be callable")
        for provider, method, label in (
            (proposal_provider, "propose", "proposal_provider"),
            (segmentation_provider, "segment", "segmentation_provider"),
            (localization_provider, "localize", "localization_provider"),
        ):
            if not callable(getattr(provider, method, None)):
                raise TypeError(f"{label} must expose {method}()")
        self.semantic_inference = semantic_inference
        self.proposal_provider = proposal_provider
        self.segmentation_provider = segmentation_provider
        self.localization_provider = localization_provider
        self.artifact_store = artifact_store

    def infer(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        base = self._semantic_result(request)
        artifacts = request.get("artifacts")
        if not isinstance(artifacts, list):
            raise SingleViewPerceptionError("scene understanding artifacts must be an array")
        rgb_ref = _unique_artifact(artifacts, "rgb")
        depth_ref = _unique_artifact(artifacts, "depth")
        rgb_path = self.artifact_store.resolve_source(rgb_ref, "rgb")
        width, height = self.artifact_store.image_size(rgb_path)
        pending: list[tuple[Mapping[str, Any], Proposal]] = []
        ambiguities = list(base.get("ambiguities", []))
        try:
            for entity in base["entities"]:
                entity_ref = entity.get("entity_ref")
                query = entity.get("category")
                if not isinstance(entity_ref, str) or not isinstance(query, str) or not query.strip():
                    raise SingleViewPerceptionError("semantic entity cannot bind a proposal query")
                proposals = tuple(
                    self.proposal_provider.propose(
                        ProposalRequest(
                            observation_ref=str(request["observation_ref"]),
                            scene_revision=str(request["scene_revision"]),
                            entity_ref=entity_ref,
                            query=query,
                            frame_id=str(request["frame_id"]),
                            rgb_artifact_ref=rgb_ref,
                            rgb_path=rgb_path,
                            width_px=width,
                            height_px=height,
                        )
                    )
                )
                if len(proposals) != 1:
                    ambiguities.append(
                        {
                            "code": "proposal_unavailable" if not proposals else "proposal_ambiguous",
                            "message": "single-view proposal did not bind exactly one region",
                            "entity_refs": [entity_ref],
                        }
                    )
                    continue
                pending.append((entity, _normalize_proposal(proposals[0], width, height)))
        finally:
            _release_provider(self.proposal_provider, "proposal")

        derived: list[dict[str, Any]] = []
        envelopes = list(base.get("spatial_envelopes", []))
        if not pending:
            _release_provider(self.segmentation_provider, "segmentation")
            return {
                "entities": list(base["entities"]),
                "relations": list(base.get("relations", [])),
                "spatial_envelopes": envelopes,
                "derived_artifacts": derived,
                "ambiguities": ambiguities,
                "provider_available": base.get("provider_available", True),
            }
        materialized: list[tuple[str, str]] = []
        try:
            try:
                depth = self.artifact_store.load_depth(depth_ref)
                calibration_ref = str(request["calibration_ref"])
                calibration = self.artifact_store.load_calibration(calibration_ref)
                for entity, proposal in pending:
                    entity_ref = str(entity["entity_ref"])
                    segmentation = self.segmentation_provider.segment(
                        SegmentationRequest(
                            observation_ref=str(request["observation_ref"]),
                            scene_revision=str(request["scene_revision"]),
                            entity_ref=entity_ref,
                            frame_id=str(request["frame_id"]),
                            rgb_artifact_ref=rgb_ref,
                            rgb_path=rgb_path,
                            width_px=width,
                            height_px=height,
                            proposal=proposal,
                        )
                    )
                    if segmentation.proposal_bbox_xyxy_px != proposal.bbox_xyxy_px:
                        raise SingleViewPerceptionError("segmentation result changed the proposal bbox")
                    np = _numpy()
                    mask = np.asarray(segmentation.mask)
                    if mask.ndim != 2 or tuple(mask.shape) != (height, width):
                        raise SingleViewPerceptionError("segmentation mask does not match the RGB image")
                    mask = mask.astype(bool, copy=False)
                    foreground = int(mask.sum())
                    if foreground < 1:
                        raise SingleViewPerceptionError("segmentation mask is empty")
                    localization = self.localization_provider.localize(
                        LocalizationRequest(
                            mask=mask,
                            depth=depth,
                            calibration=calibration,
                            frame_id=str(request["frame_id"]),
                        )
                    )
                    mask_ref, points_ref, localization_ref = _derived_refs(rgb_ref, entity_ref)
                    self.artifact_store.materialize_numpy(mask_ref, mask.astype(np.uint8))
                    materialized.append((mask_ref, ".npy"))
                    self.artifact_store.materialize_numpy(points_ref, localization.points_xyz_m)
                    materialized.append((points_ref, ".npy"))
                    confidence_evidence = [float(entity["confidence"]), localization.valid_depth_ratio]
                    if proposal.confidence is not None:
                        confidence_evidence.append(proposal.confidence)
                    confidence = min(confidence_evidence)
                    localization_value = {
                        "entity_ref": entity_ref,
                        "frame_id": str(request["frame_id"]),
                        "unit": "m",
                        "min_xyz_m": list(localization.min_xyz_m),
                        "max_xyz_m": list(localization.max_xyz_m),
                        "confidence": confidence,
                    }
                    self.artifact_store.materialize_json(localization_ref, localization_value)
                    materialized.append((localization_ref, ".json"))
                    derived.extend(
                        _derived_records(
                            request=request,
                            entity_ref=entity_ref,
                            rgb_ref=rgb_ref,
                            depth_ref=depth_ref,
                            mask_ref=mask_ref,
                            points_ref=points_ref,
                            localization_ref=localization_ref,
                            proposal=proposal,
                            width=width,
                            height=height,
                            foreground=foreground,
                            point_count=len(localization.points_xyz_m),
                            localization=localization,
                            confidence=confidence,
                        )
                    )
                    envelopes.append({**localization_value, "provenance": [localization_ref]})
            finally:
                _release_provider(self.segmentation_provider, "segmentation")
        except Exception:
            for artifact_ref, suffix in reversed(materialized):
                self.artifact_store.discard(artifact_ref, suffix)
            raise
        return {
            "entities": list(base["entities"]),
            "relations": list(base.get("relations", [])),
            "spatial_envelopes": envelopes,
            "derived_artifacts": derived,
            "ambiguities": ambiguities,
            "provider_available": base.get("provider_available", True),
        }

    def _semantic_result(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        infer = getattr(self.semantic_inference, "infer", None)
        raw = infer(request) if callable(infer) else self.semantic_inference(request)
        if not isinstance(raw, Mapping):
            raise SingleViewPerceptionError("semantic inference returned an invalid result")
        allowed = {"entities", "relations", "spatial_envelopes", "derived_artifacts", "ambiguities", "provider_available"}
        if set(raw) - allowed:
            raise SingleViewPerceptionError("semantic inference returned provider-specific fields")
        if raw.get("derived_artifacts") not in (None, [], ()):
            raise SingleViewPerceptionError("single-view composition must own derived artifacts")
        if not isinstance(raw.get("entities"), (list, tuple)):
            raise SingleViewPerceptionError("semantic inference entities must be an array")
        refs = [item.get("entity_ref") for item in raw["entities"] if isinstance(item, Mapping)]
        if len(refs) != len(raw["entities"]) or len(refs) != len(set(refs)):
            raise SingleViewPerceptionError("semantic inference entity identities are invalid")
        return raw


def _derived_records(
    *,
    request: Mapping[str, Any],
    entity_ref: str,
    rgb_ref: str,
    depth_ref: str,
    mask_ref: str,
    points_ref: str,
    localization_ref: str,
    proposal: Proposal,
    width: int,
    height: int,
    foreground: int,
    point_count: int,
    localization: LocalizationResult,
    confidence: float,
) -> list[dict[str, Any]]:
    binding = {
        "observation_ref": request["observation_ref"],
        "scene_revision": request["scene_revision"],
        "entity_ref": entity_ref,
        "frame_id": request["frame_id"],
        "calibration_ref": request["calibration_ref"],
    }
    empty = {
        "width_px": None, "height_px": None, "bbox_xyxy_px": None,
        "foreground_pixels": None, "point_count": None, "unit": None,
        "min_xyz_m": None, "max_xyz_m": None, "confidence": None,
    }
    return [
        {
            "artifact_ref": mask_ref, "kind": "instance_mask", "media_type": "application/numpy",
            **binding, "source_refs": [rgb_ref], "provenance": [rgb_ref],
            "descriptor": {
                **empty, "width_px": width, "height_px": height,
                "bbox_xyxy_px": list(proposal.bbox_xyxy_px), "foreground_pixels": foreground,
            },
        },
        {
            "artifact_ref": points_ref, "kind": "object_point_cloud", "media_type": "application/numpy",
            **binding, "source_refs": [depth_ref, mask_ref], "provenance": [rgb_ref, depth_ref],
            "descriptor": {**empty, "point_count": point_count, "unit": "m"},
        },
        {
            "artifact_ref": localization_ref, "kind": "metric_localization", "media_type": "application/json",
            **binding, "source_refs": [points_ref], "provenance": [rgb_ref, depth_ref],
            "descriptor": {
                **empty, "unit": "m", "min_xyz_m": list(localization.min_xyz_m),
                "max_xyz_m": list(localization.max_xyz_m), "confidence": confidence,
            },
        },
    ]


def _normalize_proposal(value: Any, width: int, height: int) -> Proposal:
    if isinstance(value, Proposal):
        proposal = value
    elif isinstance(value, Mapping) and set(value) == {"bbox_xyxy_px", "confidence"}:
        bbox = value["bbox_xyxy_px"]
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            raise SingleViewPerceptionError("proposal bbox must contain four integers")
        proposal = Proposal(tuple(bbox), value["confidence"])
    else:
        raise SingleViewPerceptionError("proposal response is invalid")
    bbox = proposal.bbox_xyxy_px
    if (
        len(bbox) != 4
        or any(not isinstance(item, int) or isinstance(item, bool) for item in bbox)
        or not (0 <= bbox[0] < bbox[2] <= width and 0 <= bbox[1] < bbox[3] <= height)
        or (
            proposal.confidence is not None
            and (
                not isinstance(proposal.confidence, (int, float))
                or isinstance(proposal.confidence, bool)
                or not math.isfinite(proposal.confidence)
                or not 0 <= proposal.confidence <= 1
            )
        )
    ):
        raise SingleViewPerceptionError("proposal bbox or confidence is invalid")
    confidence = None if proposal.confidence is None else float(proposal.confidence)
    return Proposal(tuple(int(item) for item in bbox), confidence)


def _unique_artifact(artifacts: list[Any], leaf: str) -> str:
    matches = [item for item in artifacts if isinstance(item, str) and item.rsplit("/", 1)[-1] == leaf]
    if len(matches) != 1:
        raise SingleViewPerceptionError(f"scene understanding requires exactly one {leaf} artifact")
    return matches[0]


def _artifact_parts(artifact_ref: str) -> tuple[str, ...]:
    parsed = urlparse(artifact_ref) if isinstance(artifact_ref, str) else None
    if parsed is None or parsed.scheme != "artifact" or not parsed.netloc or parsed.query or parsed.fragment:
        raise SingleViewPerceptionError("artifact reference is invalid")
    parts = (parsed.netloc, *parsed.path.strip("/").split("/"))
    if len(parts) < 3 or any(not part or part in {".", ".."} or "/" in part for part in parts):
        raise SingleViewPerceptionError("artifact reference is invalid")
    return parts


def _derived_refs(rgb_ref: str, entity_ref: str) -> tuple[str, str, str]:
    parsed = urlparse(rgb_ref)
    path = parsed.path.rsplit("/", 1)[0]
    token = sha256(entity_ref.encode("utf-8")).hexdigest()[:16]
    base = f"artifact://{parsed.netloc}{path}/derived"
    return f"{base}/mask-{token}", f"{base}/points-{token}", f"{base}/localization-{token}"


def _release_provider(provider: Any, label: str) -> None:
    release = getattr(provider, "release", None)
    if callable(release):
        try:
            release()
        except Exception as exc:
            raise SingleViewPerceptionError(f"{label} provider cleanup failed") from exc


def _finite_matrix(value: Any, shape: tuple[int, int], name: str) -> Any:
    np = _numpy()
    try:
        array = np.asarray(value, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise SingleViewPerceptionError(f"{name} must be numeric") from exc
    if array.shape != shape or not bool(np.isfinite(array).all()):
        raise SingleViewPerceptionError(f"{name} must be a finite {shape[0]}x{shape[1]} matrix")
    return array


def _numpy() -> Any:
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - deployment preflight owns this branch
        raise SingleViewPerceptionError(
            "NumPy is required only in the isolated perception adapter environment"
        ) from exc
    return np


__all__ = [
    "FilesystemPerceptionArtifactStore",
    "LocalizationRequest",
    "LocalizationResult",
    "MetricLocalizationProvider",
    "NumpyMetricLocalizationProvider",
    "Proposal",
    "ProposalProvider",
    "ProposalRequest",
    "SegmentationProvider",
    "SegmentationRequest",
    "SegmentationResult",
    "SingleViewPerceptionError",
    "SingleViewPerceptionInference",
    "WorkerClient",
    "WorkerProposalProvider",
    "WorkerSegmentationProvider",
]
