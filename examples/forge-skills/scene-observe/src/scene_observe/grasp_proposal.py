"""Provider-neutral grasp candidate proposal Query endpoint."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

GRASP_TOOL_ID = "grasp.propose"
GRASP_ENDPOINT_ID = "grasp_proposal"
GRASP_OPERATION = "propose"

_OBSERVATION_REF = re.compile(r"^observation://[^/]+/[^/]+$")
_CANDIDATE_SET_REF = re.compile(r"^candidate-set://[^/]+/.+$")
_CANDIDATE_REF = re.compile(r"^candidate://[^/]+/.+$")
_ARTIFACT_REF = re.compile(r"^artifact://[^/]+/.+$")
_ENTITY_REF = re.compile(r"^entity://[^/]+$")

_CANDIDATE_KEYS = {
    "candidate_ref",
    "entity_ref",
    "grasp_frame",
    "approach_direction",
    "score",
    "confidence",
    "provenance",
    "qualification",
}
_QUALIFICATIONS = ("proposed", "low_confidence", "ambiguous")
_FUNNEL_STAGES = ("decoded", "canonicalized", "deduplicated", "retained")


class GraspProposalProvider(Protocol):
    def propose(self, request: dict[str, Any]) -> "GraspProposalSnapshot | None": ...


@dataclass(frozen=True)
class GraspProposalSnapshot:
    candidates: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    ambiguities: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    funnel: dict[str, int] | None = None
    provider_available: bool = True


GRASP_TOOL_SPEC: dict[str, Any] = {
    "tool_id": GRASP_TOOL_ID,
    "implementation_id": "grasp.proposal",
    "endpoint_id": GRASP_ENDPOINT_ID,
    "operation": GRASP_OPERATION,
    "semantics": "query",
    "description": (
        "Propose provider-neutral grasp candidates from one verified scene understanding "
        "result without planning, IK, collision checking, or motion."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "observation_ref", "scene_revision", "frame_id", "calibration_ref",
            "freshness_ms", "max_age_ms", "targets",
        ],
        "properties": {
            "observation_ref": {"type": "string", "pattern": r"^observation://[^/]+/[^/]+$"},
            "scene_revision": {"type": "string", "minLength": 1},
            "frame_id": {"type": "string", "minLength": 1},
            "calibration_ref": {"type": "string", "minLength": 1},
            "freshness_ms": {"type": "integer", "minimum": 0},
            "max_age_ms": {"type": "integer", "minimum": 1},
            "targets": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["entity_ref", "category", "confidence", "spatial_envelope"],
                    "properties": {
                        "entity_ref": {"type": "string", "pattern": r"^entity://[^/]+$"},
                        "category": {"type": "string", "minLength": 1},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "spatial_envelope": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "frame_id", "unit", "min_xyz_m", "max_xyz_m",
                                "confidence", "provenance",
                            ],
                            "properties": {
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
                                "provenance": {
                                    "type": "array",
                                    "items": {"type": "string", "pattern": r"^artifact://[^/]+/.+$"},
                                },
                            },
                        },
                    },
                },
            },
        },
    },
    "output_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "status", "candidate_set_ref", "observation_ref", "scene_revision", "frame",
            "calibration_ref", "candidates", "funnel", "ambiguities",
        ],
        "properties": {
            "status": {"enum": ["available", "empty", "unavailable", "stale", "invalid"]},
            "candidate_set_ref": {"type": "string", "pattern": r"^candidate-set://[^/]+/.+$"},
            "observation_ref": {"type": "string", "pattern": r"^observation://[^/]+/[^/]+$"},
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
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "candidate_ref", "entity_ref", "grasp_frame", "approach_direction",
                        "score", "confidence", "provenance", "qualification",
                    ],
                    "properties": {
                        "candidate_ref": {"type": "string", "pattern": r"^candidate://[^/]+/.+$"},
                        "entity_ref": {"type": "string", "pattern": r"^entity://[^/]+$"},
                        "grasp_frame": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["frame_id", "unit", "position_m", "orientation_xyzw"],
                            "properties": {
                                "frame_id": {"type": "string", "minLength": 1},
                                "unit": {"const": "m"},
                                "position_m": {
                                    "type": "array", "minItems": 3, "maxItems": 3,
                                    "items": {"type": "number"},
                                },
                                "orientation_xyzw": {
                                    "type": "array", "minItems": 4, "maxItems": 4,
                                    "items": {"type": "number"},
                                },
                            },
                        },
                        "approach_direction": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["frame_id", "unit", "vector"],
                            "properties": {
                                "frame_id": {"type": "string", "minLength": 1},
                                "unit": {"const": "unitless"},
                                "vector": {
                                    "type": "array", "minItems": 3, "maxItems": 3,
                                    "items": {"type": "number"},
                                },
                            },
                        },
                        "score": {"type": "number", "minimum": 0, "maximum": 1},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "provenance": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string", "pattern": r"^artifact://[^/]+/.+$"},
                        },
                        "qualification": {"enum": ["proposed", "low_confidence", "ambiguous"]},
                    },
                },
            },
            "funnel": {
                "type": "object",
                "additionalProperties": False,
                "required": ["decoded", "canonicalized", "deduplicated", "retained"],
                "properties": {
                    "decoded": {"type": "integer", "minimum": 0},
                    "canonicalized": {"type": "integer", "minimum": 0},
                    "deduplicated": {"type": "integer", "minimum": 0},
                    "retained": {"type": "integer", "minimum": 0},
                },
            },
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
                            "items": {"type": "string", "pattern": r"^entity://[^/]+$"},
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


def _error(
    code: str,
    message: str,
    *,
    observation_ref: str = "observation://unknown/unknown",
) -> dict[str, Any]:
    return {
        "status": "invalid" if code.startswith("invalid") else "unavailable",
        "candidate_set_ref": "candidate-set://unknown/unknown",
        "observation_ref": observation_ref,
        "scene_revision": "unknown",
        "frame": {"frame_id": "unknown", "unit": "m"},
        "calibration_ref": None,
        "candidates": [],
        "funnel": {"decoded": 0, "canonicalized": 0, "deduplicated": 0, "retained": 0},
        "ambiguities": [],
        "error": {"code": code, "message": message},
    }


def _candidate_set_ref(arguments: dict[str, Any]) -> str:
    return f"candidate-set://{arguments['scene_revision']}/{arguments['frame_id']}"


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _finite_unit_interval(value: Any) -> bool:
    return _finite_number(value) and 0 <= value <= 1


def _artifact_refs(values: Any) -> bool:
    return isinstance(values, list) and all(
        isinstance(ref, str) and _ARTIFACT_REF.fullmatch(ref) is not None for ref in values
    )


def _validate_target(target: Any, frame_id: str) -> str | None:
    if (
        not isinstance(target, dict)
        or set(target) != {"entity_ref", "category", "confidence", "spatial_envelope"}
        or not isinstance(target.get("entity_ref"), str)
        or _ENTITY_REF.fullmatch(target["entity_ref"]) is None
        or not isinstance(target.get("category"), str)
        or not target["category"].strip()
        or not _finite_unit_interval(target.get("confidence"))
    ):
        return "invalid_target"
    envelope = target["spatial_envelope"]
    if (
        not isinstance(envelope, dict)
        or set(envelope) != {
            "frame_id", "unit", "min_xyz_m", "max_xyz_m", "confidence", "provenance",
        }
        or not isinstance(envelope.get("frame_id"), str)
        or not envelope["frame_id"].strip()
        or envelope.get("unit") != "m"
        or not isinstance(envelope.get("min_xyz_m"), list)
        or not isinstance(envelope.get("max_xyz_m"), list)
        or len(envelope["min_xyz_m"]) != 3
        or len(envelope["max_xyz_m"]) != 3
        or any(not _finite_number(value) for value in envelope["min_xyz_m"] + envelope["max_xyz_m"])
        or any(low > high for low, high in zip(envelope["min_xyz_m"], envelope["max_xyz_m"], strict=True))
        or not _finite_unit_interval(envelope.get("confidence"))
        or not _artifact_refs(envelope.get("provenance"))
    ):
        return "invalid_target"
    # One Query invocation is bound to one observation frame; envelopes must agree.
    if envelope["frame_id"] != frame_id:
        return "invalid_target_frame"
    return None


def validate_arguments(arguments: Any) -> dict[str, Any] | None:
    if not isinstance(arguments, dict):
        return _error("invalid_arguments", "arguments must be an object")
    allowed = {
        "observation_ref", "scene_revision", "frame_id", "calibration_ref",
        "freshness_ms", "max_age_ms", "targets",
    }
    if set(arguments) - allowed:
        return _error("invalid_arguments", "unknown grasp.propose argument")
    observation_ref = arguments.get("observation_ref")
    if not isinstance(observation_ref, str) or _OBSERVATION_REF.fullmatch(observation_ref) is None:
        return _error("invalid_observation_ref", "observation_ref must use observation:// scheme")
    if not isinstance(arguments.get("scene_revision"), str) or not arguments["scene_revision"].strip():
        return _error(
            "invalid_scene_revision",
            "scene_revision must be a non-empty string",
            observation_ref=observation_ref,
        )
    if not isinstance(arguments.get("frame_id"), str) or not arguments["frame_id"].strip():
        return _error("invalid_frame", "frame_id must be a non-empty string", observation_ref=observation_ref)
    if not isinstance(arguments.get("calibration_ref"), str) or not arguments["calibration_ref"].strip():
        return _error(
            "missing_calibration",
            "calibration_ref is required",
            observation_ref=observation_ref,
        )
    if any(
        isinstance(arguments.get(name), bool)
        or not isinstance(arguments.get(name), int)
        or arguments[name] < (0 if name == "freshness_ms" else 1)
        for name in ("freshness_ms", "max_age_ms")
    ):
        return _error(
            "invalid_freshness",
            "freshness_ms must be non-negative and max_age_ms positive",
            observation_ref=observation_ref,
        )
    targets = arguments.get("targets")
    if not isinstance(targets, list):
        return _error("invalid_target", "targets must be an array", observation_ref=observation_ref)
    for target in targets:
        target_error = _validate_target(target, arguments["frame_id"])
        if target_error is not None:
            return _error(target_error, "grasp target failed contract validation", observation_ref=observation_ref)
    return None


def _validate_candidate(
    candidate: Any,
    *,
    frame_id: str,
    requested_entity_refs: set[str],
    seen_candidate_refs: set[str],
) -> str | None:
    if not isinstance(candidate, dict) or set(candidate) != _CANDIDATE_KEYS:
        return "invalid_candidate"
    candidate_ref = candidate.get("candidate_ref")
    if not isinstance(candidate_ref, str) or _CANDIDATE_REF.fullmatch(candidate_ref) is None:
        return "invalid_candidate_ref"
    if candidate_ref in seen_candidate_refs:
        return "invalid_candidate_ref"
    seen_candidate_refs.add(candidate_ref)
    entity_ref = candidate.get("entity_ref")
    if not isinstance(entity_ref, str) or _ENTITY_REF.fullmatch(entity_ref) is None:
        return "invalid_entity_ref"
    if entity_ref not in requested_entity_refs:
        return "invalid_candidate_entity"
    grasp_frame = candidate.get("grasp_frame")
    if (
        not isinstance(grasp_frame, dict)
        or set(grasp_frame) != {"frame_id", "unit", "position_m", "orientation_xyzw"}
        or not isinstance(grasp_frame.get("frame_id"), str)
        or not grasp_frame["frame_id"].strip()
    ):
        return "invalid_candidate_frame"
    if grasp_frame["frame_id"] != frame_id:
        return "invalid_candidate_frame"
    if grasp_frame.get("unit") != "m":
        return "invalid_candidate_unit"
    if (
        not isinstance(grasp_frame.get("position_m"), list)
        or len(grasp_frame["position_m"]) != 3
        or any(not _finite_number(value) for value in grasp_frame["position_m"])
        or not isinstance(grasp_frame.get("orientation_xyzw"), list)
        or len(grasp_frame["orientation_xyzw"]) != 4
        or any(not _finite_number(value) for value in grasp_frame["orientation_xyzw"])
    ):
        return "invalid_candidate_geometry"
    approach = candidate.get("approach_direction")
    if (
        not isinstance(approach, dict)
        or set(approach) != {"frame_id", "unit", "vector"}
        or not isinstance(approach.get("frame_id"), str)
        or not approach["frame_id"].strip()
        or approach["frame_id"] != frame_id
    ):
        return "invalid_candidate_frame"
    if approach.get("unit") != "unitless":
        return "invalid_candidate_unit"
    if (
        not isinstance(approach.get("vector"), list)
        or len(approach["vector"]) != 3
        or any(not _finite_number(value) for value in approach["vector"])
    ):
        return "invalid_candidate_geometry"
    if not _finite_unit_interval(candidate.get("score")) or not _finite_unit_interval(candidate.get("confidence")):
        return "invalid_candidate_score"
    if (
        not isinstance(candidate.get("provenance"), list)
        or not candidate["provenance"]
        or not _artifact_refs(candidate["provenance"])
    ):
        return "invalid_provenance"
    if candidate.get("qualification") not in _QUALIFICATIONS:
        return "invalid_candidate"
    return None


def validate_snapshot(
    snapshot: GraspProposalSnapshot,
    *,
    frame_id: str,
    requested_entity_refs: set[str],
) -> str | None:
    if not isinstance(snapshot, GraspProposalSnapshot):
        return "invalid_snapshot"
    if not isinstance(snapshot.candidates, (tuple, list)):
        return "invalid_snapshot"
    if not isinstance(snapshot.ambiguities, (tuple, list)):
        return "invalid_snapshot"
    seen_candidate_refs: set[str] = set()
    for candidate in snapshot.candidates:
        candidate_error = _validate_candidate(
            candidate,
            frame_id=frame_id,
            requested_entity_refs=requested_entity_refs,
            seen_candidate_refs=seen_candidate_refs,
        )
        if candidate_error is not None:
            return candidate_error
    funnel = snapshot.funnel
    if (
        not isinstance(funnel, dict)
        or set(funnel) != set(_FUNNEL_STAGES)
        or any(
            isinstance(funnel.get(stage), bool) or not isinstance(funnel.get(stage), int) or funnel[stage] < 0
            for stage in _FUNNEL_STAGES
        )
        or funnel["decoded"] < funnel["canonicalized"]
        or funnel["canonicalized"] < funnel["deduplicated"]
        or funnel["deduplicated"] < funnel["retained"]
        or funnel["retained"] != len(snapshot.candidates)
    ):
        return "invalid_funnel"
    for ambiguity in snapshot.ambiguities:
        if (
            not isinstance(ambiguity, dict)
            or set(ambiguity) != {"code", "message", "entity_refs"}
            or not isinstance(ambiguity.get("code"), str)
            or not ambiguity["code"].strip()
            or not isinstance(ambiguity.get("message"), str)
            or not ambiguity["message"].strip()
            or not isinstance(ambiguity.get("entity_refs"), list)
            or any(not isinstance(ref, str) or _ENTITY_REF.fullmatch(ref) is None for ref in ambiguity["entity_refs"])
        ):
            return "invalid_ambiguity"
    return None


class GraspProposalEndpoint:
    """Read-only provider adapter; never plans, checks collisions, or moves a robot."""

    def __init__(self, provider: GraspProposalProvider) -> None:
        self.provider = provider

    def invoke(self, arguments: Any) -> dict[str, Any]:
        error = validate_arguments(arguments)
        if error is not None:
            return error
        assert isinstance(arguments, dict)
        observation_ref = arguments["observation_ref"]
        candidate_set_ref = _candidate_set_ref(arguments)
        if _CANDIDATE_SET_REF.fullmatch(candidate_set_ref) is None:
            return _error(
                "invalid_candidate_set_ref",
                "scene_revision and frame_id must form a candidate-set:// reference",
                observation_ref=observation_ref,
            )
        if arguments["freshness_ms"] > arguments["max_age_ms"]:
            return {
                **_error(
                    "stale_observation",
                    "observation exceeds max_age_ms",
                    observation_ref=observation_ref,
                ),
                "status": "stale",
                "candidate_set_ref": candidate_set_ref,
                "scene_revision": arguments["scene_revision"],
                "frame": {"frame_id": arguments["frame_id"], "unit": "m"},
                "calibration_ref": arguments["calibration_ref"],
            }
        if not arguments["targets"]:
            # An empty target list is a complete request: no candidates may be fabricated.
            return {
                "status": "empty",
                "candidate_set_ref": candidate_set_ref,
                "observation_ref": observation_ref,
                "scene_revision": arguments["scene_revision"],
                "frame": {"frame_id": arguments["frame_id"], "unit": "m"},
                "calibration_ref": arguments["calibration_ref"],
                "candidates": [],
                "funnel": {"decoded": 0, "canonicalized": 0, "deduplicated": 0, "retained": 0},
                "ambiguities": [],
            }
        try:
            snapshot = self.provider.propose(dict(arguments))
        except Exception:
            # Provider failures are unavailable, never an implicit Gateway 500 or success.
            return _error(
                "grasp_proposal_provider_error",
                "grasp proposal provider failed",
                observation_ref=observation_ref,
            )
        if snapshot is None:
            return _error(
                "grasp_proposal_unavailable",
                "grasp proposal provider is unavailable",
                observation_ref=observation_ref,
            )
        if not isinstance(snapshot, GraspProposalSnapshot):
            return _error(
                "invalid_snapshot",
                "grasp proposal provider returned an invalid snapshot",
                observation_ref=observation_ref,
            )
        if not isinstance(snapshot.provider_available, bool):
            return _error(
                "invalid_snapshot",
                "grasp proposal provider returned an invalid availability flag",
                observation_ref=observation_ref,
            )
        if not snapshot.provider_available:
            return _error(
                "grasp_proposal_unavailable",
                "grasp proposal provider is unavailable",
                observation_ref=observation_ref,
            )
        requested_entity_refs = {target["entity_ref"] for target in arguments["targets"]}
        snapshot_error = validate_snapshot(
            snapshot,
            frame_id=arguments["frame_id"],
            requested_entity_refs=requested_entity_refs,
        )
        if snapshot_error:
            return _error(
                snapshot_error,
                "grasp proposal provider result failed contract validation",
                observation_ref=observation_ref,
            )
        return {
            "status": "available" if snapshot.candidates else "empty",
            "candidate_set_ref": candidate_set_ref,
            "observation_ref": observation_ref,
            "scene_revision": arguments["scene_revision"],
            "frame": {"frame_id": arguments["frame_id"], "unit": "m"},
            "calibration_ref": arguments["calibration_ref"],
            "candidates": [dict(candidate) for candidate in snapshot.candidates],
            "funnel": dict(snapshot.funnel or {}),
            "ambiguities": [dict(ambiguity) for ambiguity in snapshot.ambiguities],
        }


__all__ = [
    "GRASP_TOOL_ID",
    "GRASP_ENDPOINT_ID",
    "GRASP_OPERATION",
    "GRASP_TOOL_SPEC",
    "GraspProposalProvider",
    "GraspProposalSnapshot",
    "GraspProposalEndpoint",
]
