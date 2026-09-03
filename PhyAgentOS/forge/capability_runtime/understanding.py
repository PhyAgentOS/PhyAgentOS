"""PAOS-owned, provider-neutral scene-understanding Query runtime.

This module contains only the public contract and deterministic projection
logic.  A model, camera runtime, simulator, or vendor SDK is supplied through
``SceneUnderstandingProvider`` and is never imported here.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

TOOL_ID = "scene.understand"
ENDPOINT_ID = "scene_understanding"
OPERATION = "understand"
_OBSERVATION_REF = re.compile(r"^observation://[^/]+/[^/]+$")
_ARTIFACT_REF = re.compile(r"^artifact://[^/]+/.+$")
_ENTITY_REF = re.compile(r"^entity://[^/]+$")
_RELATION_REF = re.compile(r"^relation://[^/]+$")


class SceneUnderstandingProvider(Protocol):
    def understand(self, request: dict[str, Any]) -> "UnderstandingSnapshot | Mapping[str, Any] | None": ...


@dataclass(frozen=True)
class UnderstandingSnapshot:
    entities: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    relations: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    spatial_envelopes: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    derived_artifacts: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    ambiguities: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    provider_available: bool = True


_PROVENANCE_SCHEMA = {
    "type": "array",
    "minItems": 1,
    "items": {"type": "string", "pattern": _ARTIFACT_REF.pattern},
}
_VECTOR3_SCHEMA = {
    "type": ["array", "null"],
    "minItems": 3,
    "maxItems": 3,
    "items": {"type": "number"},
}
_DERIVED_DESCRIPTOR_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "width_px",
        "height_px",
        "bbox_xyxy_px",
        "foreground_pixels",
        "point_count",
        "unit",
        "min_xyz_m",
        "max_xyz_m",
        "confidence",
    ],
    "properties": {
        "width_px": {"type": ["integer", "null"], "minimum": 1},
        "height_px": {"type": ["integer", "null"], "minimum": 1},
        "bbox_xyxy_px": {
            "type": ["array", "null"],
            "minItems": 4,
            "maxItems": 4,
            "items": {"type": "integer", "minimum": 0},
        },
        "foreground_pixels": {"type": ["integer", "null"], "minimum": 1},
        "point_count": {"type": ["integer", "null"], "minimum": 1},
        "unit": {"type": ["string", "null"], "enum": ["m", None]},
        "min_xyz_m": _VECTOR3_SCHEMA,
        "max_xyz_m": _VECTOR3_SCHEMA,
        "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
    },
}
_DERIVED_ARTIFACT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "artifact_ref",
        "kind",
        "media_type",
        "observation_ref",
        "scene_revision",
        "entity_ref",
        "frame_id",
        "calibration_ref",
        "source_refs",
        "provenance",
        "descriptor",
    ],
    "properties": {
        "artifact_ref": {"type": "string", "pattern": _ARTIFACT_REF.pattern},
        "kind": {"enum": ["instance_mask", "object_point_cloud", "metric_localization"]},
        "media_type": {"type": "string", "minLength": 1},
        "observation_ref": {"type": "string", "pattern": _OBSERVATION_REF.pattern},
        "scene_revision": {"type": "string", "minLength": 1},
        "entity_ref": {"type": "string", "pattern": _ENTITY_REF.pattern},
        "frame_id": {"type": "string", "minLength": 1},
        "calibration_ref": {"type": "string", "minLength": 1},
        "source_refs": _PROVENANCE_SCHEMA,
        "provenance": _PROVENANCE_SCHEMA,
        "descriptor": _DERIVED_DESCRIPTOR_SCHEMA,
    },
}


TOOL_SPEC: dict[str, Any] = {
    "tool_id": TOOL_ID,
    "implementation_id": "scene.understanding",
    "endpoint_id": ENDPOINT_ID,
    "operation": OPERATION,
    "semantics": "query",
    "description": "Derive provider-neutral entity and relation claims from one named observation.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "observation_ref", "scene_revision", "frame_id", "calibration_ref",
            "freshness_ms", "max_age_ms", "artifacts",
        ],
        "properties": {
            "observation_ref": {"type": "string", "pattern": _OBSERVATION_REF.pattern},
            "scene_revision": {"type": "string", "minLength": 1},
            "frame_id": {"type": "string", "minLength": 1},
            "calibration_ref": {"type": "string", "minLength": 1},
            "freshness_ms": {"type": "integer", "minimum": 0},
            "max_age_ms": {"type": "integer", "minimum": 1},
            "artifacts": {
                "type": "array", "minItems": 1,
                "items": {"type": "string", "pattern": _ARTIFACT_REF.pattern},
            },
        },
    },
    "output_schema": {
        "type": "object", "additionalProperties": False,
        "required": [
            "status", "observation_ref", "scene_revision", "frame",
            "calibration_ref", "entities", "relations", "spatial_envelopes",
            "derived_artifacts", "ambiguities",
        ],
        "properties": {
            "status": {"enum": ["available", "unavailable", "stale", "invalid"]},
            "observation_ref": {"type": "string", "pattern": _OBSERVATION_REF.pattern},
            "scene_revision": {"type": "string", "minLength": 1},
            "frame": {
                "type": "object",
                "additionalProperties": False,
                "required": ["frame_id", "unit"],
                "properties": {
                    "frame_id": {"type": "string", "minLength": 1},
                    "unit": {"const": "m"},
                },
            },
            "calibration_ref": {"type": ["string", "null"]},
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["entity_ref", "category", "confidence", "provenance"],
                    "properties": {
                        "entity_ref": {"type": "string", "pattern": _ENTITY_REF.pattern},
                        "category": {"type": "string", "minLength": 1},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "provenance": _PROVENANCE_SCHEMA,
                    },
                },
            },
            "relations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "relation_ref", "subject_ref", "predicate", "object_ref",
                        "confidence", "provenance",
                    ],
                    "properties": {
                        "relation_ref": {"type": "string", "pattern": _RELATION_REF.pattern},
                        "subject_ref": {"type": "string", "pattern": _ENTITY_REF.pattern},
                        "predicate": {"type": "string", "minLength": 1},
                        "object_ref": {"type": "string", "pattern": _ENTITY_REF.pattern},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "provenance": _PROVENANCE_SCHEMA,
                    },
                },
            },
            "spatial_envelopes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "entity_ref", "frame_id", "unit", "min_xyz_m", "max_xyz_m",
                        "confidence", "provenance",
                    ],
                    "properties": {
                        "entity_ref": {"type": "string", "pattern": _ENTITY_REF.pattern},
                        "frame_id": {"type": "string", "minLength": 1},
                        "unit": {"const": "m"},
                        "min_xyz_m": {
                            "type": "array", "minItems": 3, "maxItems": 3,
                            "items": {"type": "number"},
                        },
                        "max_xyz_m": {
                            "type": "array", "minItems": 3, "maxItems": 3,
                            "items": {"type": "number"},
                        },
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "provenance": _PROVENANCE_SCHEMA,
                    },
                },
            },
            "derived_artifacts": {"type": "array", "items": _DERIVED_ARTIFACT_SCHEMA},
            "ambiguities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["code", "message", "entity_refs"],
                    "properties": {
                        "code": {"type": "string", "minLength": 1},
                        "message": {"type": "string", "minLength": 1},
                        "entity_refs": {
                            "type": "array",
                            "items": {"type": "string", "pattern": _ENTITY_REF.pattern},
                        },
                    },
                },
            },
            "error": {
                "type": "object",
                "additionalProperties": False,
                "required": ["code", "message"],
                "properties": {
                    "code": {"type": "string", "minLength": 1},
                    "message": {"type": "string", "minLength": 1},
                },
            },
        },
    },
    "robot_frame_profile": {"observation_frame": "observation", "unit": "m"},
}


def _error(code: str, message: str, *, observation_ref: str = "observation://unknown/unknown") -> dict[str, Any]:
    return {
        "status": "invalid" if code.startswith("invalid") else "unavailable",
        "observation_ref": observation_ref,
        "scene_revision": "unknown",
        "frame": {"frame_id": "unknown", "unit": "m"},
        "calibration_ref": None,
        "entities": [], "relations": [], "spatial_envelopes": [],
        "derived_artifacts": [], "ambiguities": [],
        "error": {"code": code, "message": message},
    }


def validate_arguments(arguments: Any) -> dict[str, Any] | None:
    if not isinstance(arguments, dict):
        return _error("invalid_arguments", "arguments must be an object")
    allowed = {
        "observation_ref", "scene_revision", "frame_id", "calibration_ref",
        "freshness_ms", "max_age_ms", "artifacts",
    }
    if set(arguments) - allowed:
        return _error("invalid_arguments", "unknown scene.understand argument")
    observation_ref = arguments.get("observation_ref")
    if not isinstance(observation_ref, str) or _OBSERVATION_REF.fullmatch(observation_ref) is None:
        return _error("invalid_observation_ref", "observation_ref must use observation:// scheme")
    if not isinstance(arguments.get("scene_revision"), str) or not arguments["scene_revision"].strip():
        return _error("invalid_scene_revision", "scene_revision must be a non-empty string", observation_ref=observation_ref)
    if not isinstance(arguments.get("frame_id"), str) or not arguments["frame_id"].strip():
        return _error("invalid_frame", "frame_id must be a non-empty string", observation_ref=observation_ref)
    if not isinstance(arguments.get("calibration_ref"), str) or not arguments["calibration_ref"].strip():
        return _error("missing_calibration", "calibration_ref is required", observation_ref=observation_ref)
    if any(
        isinstance(arguments.get(name), bool)
        or not isinstance(arguments.get(name), int)
        or arguments[name] < (0 if name == "freshness_ms" else 1)
        for name in ("freshness_ms", "max_age_ms")
    ):
        return _error("invalid_freshness", "freshness_ms must be non-negative and max_age_ms positive", observation_ref=observation_ref)
    artifacts = arguments.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts or any(
        not isinstance(ref, str) or _ARTIFACT_REF.fullmatch(ref) is None for ref in artifacts
    ):
        return _error("invalid_artifact_ref", "artifacts must contain valid artifact references", observation_ref=observation_ref)
    return None


def _finite_confidence(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1


def normalize_snapshot(snapshot: Any) -> UnderstandingSnapshot | None:
    if isinstance(snapshot, UnderstandingSnapshot):
        return snapshot
    if not isinstance(snapshot, Mapping):
        return None
    allowed = {
        "entities", "relations", "spatial_envelopes", "derived_artifacts", "ambiguities",
        "provider_available",
    }
    if set(snapshot) - allowed:
        return None
    values = {
        key: snapshot.get(key, ())
        for key in ("entities", "relations", "spatial_envelopes", "derived_artifacts", "ambiguities")
    }
    if any(
        not isinstance(value, (list, tuple))
        or any(not isinstance(item, Mapping) for item in value)
        for value in values.values()
    ):
        return None
    provider_available = snapshot.get("provider_available", True)
    if not isinstance(provider_available, bool):
        return None
    return UnderstandingSnapshot(
        entities=tuple(dict(item) for item in values["entities"]),
        relations=tuple(dict(item) for item in values["relations"]),
        spatial_envelopes=tuple(dict(item) for item in values["spatial_envelopes"]),
        derived_artifacts=tuple(dict(item) for item in values["derived_artifacts"]),
        ambiguities=tuple(dict(item) for item in values["ambiguities"]),
        provider_available=provider_available,
    )


def _provenance_is_bound(value: Any, allowed_artifacts: set[str] | None) -> bool:
    if not isinstance(value, list):
        return False
    return all(
        isinstance(ref, str)
        and _ARTIFACT_REF.fullmatch(ref) is not None
        and (allowed_artifacts is None or ref in allowed_artifacts)
        for ref in value
    )


def _finite_vector(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 3
        and all(
            isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(item)
            for item in value
        )
    )


def _validate_derived_artifacts(
    artifacts: tuple[dict[str, Any], ...],
    *,
    observation_ref: str,
    scene_revision: str,
    frame_id: str,
    calibration_ref: str,
    entity_refs: set[str],
    source_artifacts: set[str],
) -> str | None:
    seen: set[str] = set()
    root_cache: dict[str, set[str]] = {ref: {ref} for ref in source_artifacts}
    for artifact in artifacts:
        if not isinstance(artifact, dict) or set(artifact) != {
            "artifact_ref", "kind", "media_type", "observation_ref", "scene_revision",
            "entity_ref", "frame_id", "calibration_ref", "source_refs", "provenance", "descriptor",
        }:
            return "invalid_derived_artifact"
        ref = artifact.get("artifact_ref")
        if (
            not isinstance(ref, str) or _ARTIFACT_REF.fullmatch(ref) is None
            or ref in source_artifacts or ref in seen
        ):
            return "invalid_derived_artifact_ref"
        if (
            artifact.get("observation_ref") != observation_ref
            or artifact.get("scene_revision") != scene_revision
            or artifact.get("frame_id") != frame_id
            or artifact.get("calibration_ref") != calibration_ref
            or artifact.get("entity_ref") not in entity_refs
            or not isinstance(artifact.get("media_type"), str)
            or not artifact["media_type"].strip()
        ):
            return "invalid_derived_artifact_binding"
        kind = artifact.get("kind")
        if kind not in {"instance_mask", "object_point_cloud", "metric_localization"}:
            return "invalid_derived_artifact_kind"
        source_refs = artifact.get("source_refs")
        provenance = artifact.get("provenance")
        if (
            not isinstance(source_refs, list) or not source_refs
            or len(set(source_refs)) != len(source_refs)
            or any(
                not isinstance(item, str)
                or _ARTIFACT_REF.fullmatch(item) is None
                or item not in source_artifacts | seen
                for item in source_refs
            )
            or not isinstance(provenance, list)
            or not provenance
            or len(set(provenance)) != len(provenance)
            or any(item not in source_artifacts for item in provenance)
        ):
            return "invalid_derived_artifact_lineage"
        roots: set[str] = set()
        for source in source_refs:
            roots.update(root_cache[source])
        if set(provenance) != roots:
            return "invalid_derived_artifact_lineage"
        descriptor = artifact.get("descriptor")
        if not isinstance(descriptor, dict) or set(descriptor) != {
            "width_px", "height_px", "bbox_xyxy_px", "foreground_pixels", "point_count",
            "unit", "min_xyz_m", "max_xyz_m", "confidence",
        }:
            return "invalid_derived_artifact_descriptor"
        if kind == "instance_mask":
            width, height, bbox, pixels = (
                descriptor.get("width_px"), descriptor.get("height_px"),
                descriptor.get("bbox_xyxy_px"), descriptor.get("foreground_pixels"),
            )
            if (
                not isinstance(width, int) or isinstance(width, bool) or width < 1
                or not isinstance(height, int) or isinstance(height, bool) or height < 1
                or not isinstance(bbox, list) or len(bbox) != 4
                or any(not isinstance(v, int) or isinstance(v, bool) or v < 0 for v in bbox)
                or not (bbox[0] < bbox[2] <= width and bbox[1] < bbox[3] <= height)
                or not isinstance(pixels, int) or isinstance(pixels, bool) or not 0 < pixels <= width * height
                or any(descriptor.get(name) is not None for name in ("point_count", "unit", "min_xyz_m", "max_xyz_m", "confidence"))
            ):
                return "invalid_derived_artifact_descriptor"
        elif kind == "object_point_cloud":
            if (
                not isinstance(descriptor.get("point_count"), int)
                or isinstance(descriptor["point_count"], bool) or descriptor["point_count"] < 1
                or descriptor.get("unit") != "m"
                or any(descriptor.get(name) is not None for name in ("width_px", "height_px", "bbox_xyxy_px", "foreground_pixels", "min_xyz_m", "max_xyz_m", "confidence"))
            ):
                return "invalid_derived_artifact_descriptor"
        else:
            if (
                descriptor.get("unit") != "m"
                or not _finite_vector(descriptor.get("min_xyz_m"))
                or not _finite_vector(descriptor.get("max_xyz_m"))
                or any(low > high for low, high in zip(descriptor["min_xyz_m"], descriptor["max_xyz_m"], strict=True))
                or not _finite_confidence(descriptor.get("confidence"))
                or any(descriptor.get(name) is not None for name in ("width_px", "height_px", "bbox_xyxy_px", "foreground_pixels", "point_count"))
            ):
                return "invalid_derived_artifact_descriptor"
        seen.add(ref)
        root_cache[ref] = roots
    return None


def validate_snapshot(
    snapshot: UnderstandingSnapshot | Mapping[str, Any],
    *,
    artifact_refs: list[str] | tuple[str, ...] | set[str] | None = None,
) -> str | None:
    snapshot = normalize_snapshot(snapshot)
    if snapshot is None:
        return "invalid_snapshot"
    allowed_artifacts = set(artifact_refs) if artifact_refs is not None else None
    for entity in snapshot.entities:
        if (
            not isinstance(entity, dict)
            or set(entity) != {"entity_ref", "category", "confidence", "provenance"}
            or not isinstance(entity.get("entity_ref"), str)
            or _ENTITY_REF.fullmatch(entity["entity_ref"]) is None
            or not isinstance(entity.get("category"), str)
            or not entity["category"].strip()
            or not _finite_confidence(entity.get("confidence"))
        ):
            return "invalid_entity_claim"
    entity_refs = {item.get("entity_ref") for item in snapshot.entities if isinstance(item, dict)}
    if artifact_refs is not None and not isinstance(artifact_refs, (list, tuple, set)):
        return "invalid_artifact_ref"
    if snapshot.derived_artifacts:
        if artifact_refs is None:
            return "invalid_artifact_ref"
        first = snapshot.derived_artifacts[0]
        observation_ref = first.get("observation_ref") if isinstance(first, dict) else ""
        scene_revision = first.get("scene_revision") if isinstance(first, dict) else ""
        frame_id = first.get("frame_id") if isinstance(first, dict) else ""
        calibration_ref = first.get("calibration_ref") if isinstance(first, dict) else ""
        if not all(isinstance(value, str) and value for value in (observation_ref, scene_revision, frame_id, calibration_ref)):
            return "invalid_derived_artifact_binding"
        derived_error = _validate_derived_artifacts(
            snapshot.derived_artifacts,
            observation_ref=observation_ref,
            scene_revision=scene_revision,
            frame_id=frame_id,
            calibration_ref=calibration_ref,
            entity_refs=entity_refs,
            source_artifacts=allowed_artifacts,
        )
        if derived_error:
            return derived_error
    all_artifacts = (
        None
        if allowed_artifacts is None
        else allowed_artifacts | {item["artifact_ref"] for item in snapshot.derived_artifacts}
    )
    for entity in snapshot.entities:
        if not _provenance_is_bound(entity.get("provenance"), all_artifacts):
            return "invalid_entity_claim"
    for relation in snapshot.relations:
        if (
            not isinstance(relation, dict)
            or set(relation) != {"relation_ref", "subject_ref", "predicate", "object_ref", "confidence", "provenance"}
            or not isinstance(relation.get("relation_ref"), str)
            or _RELATION_REF.fullmatch(relation["relation_ref"]) is None
            or relation.get("subject_ref") not in entity_refs
            or relation.get("object_ref") not in entity_refs
            or not isinstance(relation.get("predicate"), str)
            or not relation["predicate"].strip()
            or not _finite_confidence(relation.get("confidence"))
            or not _provenance_is_bound(relation.get("provenance"), all_artifacts)
        ):
            return "invalid_relation"
    for envelope in snapshot.spatial_envelopes:
        if (
            not isinstance(envelope, dict)
            or set(envelope) != {"entity_ref", "frame_id", "unit", "min_xyz_m", "max_xyz_m", "confidence", "provenance"}
            or envelope.get("entity_ref") not in entity_refs
            or not isinstance(envelope.get("frame_id"), str)
            or not envelope["frame_id"].strip()
            or envelope.get("unit") != "m"
            or not isinstance(envelope.get("min_xyz_m"), list)
            or not isinstance(envelope.get("max_xyz_m"), list)
            or len(envelope["min_xyz_m"]) != 3 or len(envelope["max_xyz_m"]) != 3
            or any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) for value in envelope["min_xyz_m"] + envelope["max_xyz_m"])
            or any(low > high for low, high in zip(envelope["min_xyz_m"], envelope["max_xyz_m"], strict=True))
            or not _finite_confidence(envelope.get("confidence"))
            or not _provenance_is_bound(envelope.get("provenance"), all_artifacts)
        ):
            return "invalid_spatial_envelope"
    for ambiguity in snapshot.ambiguities:
        if (
            not isinstance(ambiguity, dict)
            or set(ambiguity) != {"code", "message", "entity_refs"}
            or not isinstance(ambiguity.get("code"), str) or not ambiguity["code"].strip()
            or not isinstance(ambiguity.get("message"), str) or not ambiguity["message"].strip()
            or not isinstance(ambiguity.get("entity_refs"), list)
            or any(ref not in entity_refs for ref in ambiguity["entity_refs"])
        ):
            return "invalid_ambiguity"
    return None


class SceneUnderstandingEndpoint:
    """PAOS-owned Query projection; it never emits an actuator command."""

    def __init__(self, provider: SceneUnderstandingProvider) -> None:
        self.provider = provider

    def invoke(self, arguments: Any) -> dict[str, Any]:
        error = validate_arguments(arguments)
        if error is not None:
            return error
        assert isinstance(arguments, dict)
        observation_ref = arguments["observation_ref"]
        if arguments["freshness_ms"] > arguments["max_age_ms"]:
            return {
                **_error("stale_observation", "observation exceeds max_age_ms", observation_ref=observation_ref),
                "status": "stale", "scene_revision": arguments["scene_revision"],
                "frame": {"frame_id": arguments["frame_id"], "unit": "m"},
                "calibration_ref": arguments["calibration_ref"],
            }
        try:
            snapshot = self.provider.understand(arguments)
        except Exception:
            return _error("understanding_provider_error", "scene understanding provider failed", observation_ref=observation_ref)
        normalized = normalize_snapshot(snapshot)
        if normalized is None or not normalized.provider_available:
            return _error("understanding_unavailable", "scene understanding provider is unavailable", observation_ref=observation_ref)
        snapshot_error = validate_snapshot(normalized, artifact_refs=arguments["artifacts"])
        if snapshot_error:
            return _error(snapshot_error, "understanding provider result failed contract validation", observation_ref=observation_ref)
        return {
            "status": "available", "observation_ref": observation_ref,
            "scene_revision": arguments["scene_revision"],
            "frame": {"frame_id": arguments["frame_id"], "unit": "m"},
            "calibration_ref": arguments["calibration_ref"],
            "entities": [dict(item) for item in normalized.entities],
            "relations": [dict(item) for item in normalized.relations],
            "spatial_envelopes": [dict(item) for item in normalized.spatial_envelopes],
            "derived_artifacts": [dict(item) for item in normalized.derived_artifacts],
            "ambiguities": [dict(item) for item in normalized.ambiguities],
        }


__all__ = [
    "ENDPOINT_ID", "OPERATION", "SceneUnderstandingEndpoint", "SceneUnderstandingProvider",
    "TOOL_ID", "TOOL_SPEC", "UnderstandingSnapshot", "normalize_snapshot", "validate_arguments",
    "validate_snapshot",
]
