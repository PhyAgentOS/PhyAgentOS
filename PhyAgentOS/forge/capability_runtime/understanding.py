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
    ambiguities: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    provider_available: bool = True


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
            "calibration_ref", "entities", "relations", "spatial_envelopes", "ambiguities",
        ],
        "properties": {
            "status": {"enum": ["available", "unavailable", "stale", "invalid"]},
            "observation_ref": {"type": "string", "pattern": _OBSERVATION_REF.pattern},
            "scene_revision": {"type": "string", "minLength": 1},
            "frame": {"type": "object"},
            "calibration_ref": {"type": ["string", "null"]},
            "entities": {"type": "array"}, "relations": {"type": "array"},
            "spatial_envelopes": {"type": "array"}, "ambiguities": {"type": "array"},
            "error": {"type": "object"},
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
        "entities": [], "relations": [], "spatial_envelopes": [], "ambiguities": [],
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
    allowed = {"entities", "relations", "spatial_envelopes", "ambiguities", "provider_available"}
    if set(snapshot) - allowed:
        return None
    values = {
        key: snapshot.get(key, ())
        for key in ("entities", "relations", "spatial_envelopes", "ambiguities")
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
            or not _provenance_is_bound(entity.get("provenance"), allowed_artifacts)
        ):
            return "invalid_entity_claim"
    entity_refs = {item.get("entity_ref") for item in snapshot.entities if isinstance(item, dict)}
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
            or not _provenance_is_bound(relation.get("provenance"), allowed_artifacts)
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
            or not _provenance_is_bound(envelope.get("provenance"), allowed_artifacts)
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
            "ambiguities": [dict(item) for item in normalized.ambiguities],
        }


__all__ = [
    "ENDPOINT_ID", "OPERATION", "SceneUnderstandingEndpoint", "SceneUnderstandingProvider",
    "TOOL_ID", "TOOL_SPEC", "UnderstandingSnapshot", "normalize_snapshot", "validate_arguments",
    "validate_snapshot",
]
