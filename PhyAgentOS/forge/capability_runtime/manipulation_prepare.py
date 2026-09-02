"""Provider-neutral manipulation preparation Query endpoint."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from PhyAgentOS.forge.capability_runtime.grasp_proposal import _validate_candidate

PREPARATION_TOOL_ID = "manipulation.prepare"
PREPARATION_ENDPOINT_ID = "manipulation_preparation"
PREPARATION_OPERATION = "prepare"

_OBSERVATION_REF = re.compile(r"^observation://[^/]+/[^/]+$")
_CANDIDATE_SET_REF = re.compile(r"^candidate-set://[^/]+/.+$")
_CANDIDATE_REF = re.compile(r"^candidate://[^/]+/.+$")
_PREPARATION_REF = re.compile(r"^preparation://[^/]+/.+$")
_ARTIFACT_REF = re.compile(r"^artifact://[^/]+/.+$")
_ENTITY_REF = re.compile(r"^entity://[^/]+$")

_CHECK_KEYS = ("kinematic", "collision", "workspace")
_CHECK_STATUSES = ("pass", "fail", "unknown")
_PREPARED_KEYS = {"candidate_ref", "entity_ref", "checks", "evidence", "qualification"}


class PreparationProvider(Protocol):
    def prepare(self, request: dict[str, Any]) -> "PreparationSnapshot | None": ...


@dataclass(frozen=True)
class PreparationSnapshot:
    prepared_candidates: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    provider_available: bool = True


MANIPULATION_TOOL_SPEC: dict[str, Any] = {
    "tool_id": PREPARATION_TOOL_ID,
    "implementation_id": "manipulation.preparation",
    "endpoint_id": PREPARATION_ENDPOINT_ID,
    "operation": PREPARATION_OPERATION,
    "semantics": "query",
    "description": (
        "Evaluate non-mutating workspace, kinematic, and collision readiness for one grasp "
        "candidate set without authorizing or producing motion."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "observation_ref", "scene_revision", "frame_id", "calibration_ref",
            "freshness_ms", "max_age_ms", "candidate_set_ref", "candidates",
        ],
        "properties": {
            "observation_ref": {"type": "string", "pattern": r"^observation://[^/]+/[^/]+$"},
            "scene_revision": {"type": "string", "minLength": 1},
            "frame_id": {"type": "string", "minLength": 1},
            "calibration_ref": {"type": "string", "minLength": 1},
            "freshness_ms": {"type": "integer", "minimum": 0},
            "max_age_ms": {"type": "integer", "minimum": 1},
            "candidate_set_ref": {"type": "string", "pattern": r"^candidate-set://[^/]+/.+$"},
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
        },
    },
    "output_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "status", "preparation_ref", "candidate_set_ref", "observation_ref",
            "scene_revision", "frame", "calibration_ref", "prepared_candidates",
            "checks", "evidence", "motion_authorized",
        ],
        "properties": {
            "status": {"enum": ["available", "empty", "unavailable", "stale", "invalid"]},
            "preparation_ref": {"type": "string", "pattern": r"^preparation://[^/]+/.+$"},
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
            "prepared_candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["candidate_ref", "entity_ref", "checks", "evidence", "qualification"],
                    "properties": {
                        "candidate_ref": {"type": "string", "pattern": r"^candidate://[^/]+/.+$"},
                        "entity_ref": {"type": "string", "pattern": r"^entity://[^/]+$"},
                        "checks": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["kinematic", "collision", "workspace"],
                            "properties": {
                                "kinematic": {"enum": ["pass", "fail", "unknown"]},
                                "collision": {"enum": ["pass", "fail", "unknown"]},
                                "workspace": {"enum": ["pass", "fail", "unknown"]},
                            },
                        },
                        "evidence": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string", "pattern": r"^artifact://[^/]+/.+$"},
                        },
                        "qualification": {"enum": ["prepared"]},
                    },
                },
            },
            "checks": {
                "type": "object",
                "additionalProperties": False,
                "required": ["kinematic", "collision", "workspace"],
                "properties": {
                    "kinematic": {"enum": ["pass", "fail", "unknown"]},
                    "collision": {"enum": ["pass", "fail", "unknown"]},
                    "workspace": {"enum": ["pass", "fail", "unknown"]},
                },
            },
            "evidence": {
                "type": "array",
                "items": {"type": "string", "pattern": r"^artifact://[^/]+/.+$"},
            },
            "motion_authorized": {"const": False},
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


def _unknown_checks() -> dict[str, str]:
    return {key: "unknown" for key in _CHECK_KEYS}


def _error(
    code: str,
    message: str,
    *,
    observation_ref: str = "observation://unknown/unknown",
) -> dict[str, Any]:
    return {
        "status": "invalid" if code.startswith("invalid") else "unavailable",
        "preparation_ref": "preparation://unknown/unknown",
        "candidate_set_ref": "candidate-set://unknown/unknown",
        "observation_ref": observation_ref,
        "scene_revision": "unknown",
        "frame": {"frame_id": "unknown", "unit": "m"},
        "calibration_ref": None,
        "prepared_candidates": [],
        "checks": _unknown_checks(),
        "evidence": [],
        "motion_authorized": False,
        "error": {"code": code, "message": message},
    }


def validate_arguments(arguments: Any) -> dict[str, Any] | None:
    if not isinstance(arguments, dict):
        return _error("invalid_arguments", "arguments must be an object")
    allowed = {
        "observation_ref", "scene_revision", "frame_id", "calibration_ref",
        "freshness_ms", "max_age_ms", "candidate_set_ref", "candidates",
    }
    if set(arguments) - allowed:
        return _error("invalid_arguments", "unknown manipulation.prepare argument")
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
    candidate_set_ref = arguments.get("candidate_set_ref")
    if not isinstance(candidate_set_ref, str) or _CANDIDATE_SET_REF.fullmatch(candidate_set_ref) is None:
        return _error(
            "invalid_candidate_set_ref",
            "candidate_set_ref must use candidate-set:// scheme",
            observation_ref=observation_ref,
        )
    if candidate_set_ref != f"candidate-set://{arguments['scene_revision']}/{arguments['frame_id']}":
        return _error(
            "invalid_candidate_set_binding",
            "candidate_set_ref must match scene_revision and frame_id",
            observation_ref=observation_ref,
        )
    candidates = arguments.get("candidates")
    if not isinstance(candidates, list):
        return _error("invalid_candidate", "candidates must be an array", observation_ref=observation_ref)
    entity_refs: set[str] = set()
    for candidate in candidates:
        entity_ref = candidate.get("entity_ref") if isinstance(candidate, dict) else None
        if not isinstance(entity_ref, str) or _ENTITY_REF.fullmatch(entity_ref) is None:
            return _error("invalid_entity_ref", "candidate entity_ref is invalid", observation_ref=observation_ref)
        entity_refs.add(entity_ref)
    seen_candidate_refs: set[str] = set()
    for candidate in candidates:
        candidate_error = _validate_candidate(
            candidate,
            frame_id=arguments["frame_id"],
            requested_entity_refs=entity_refs,
            seen_candidate_refs=seen_candidate_refs,
        )
        if candidate_error is not None:
            return _error(
                candidate_error,
                "grasp candidate failed contract validation",
                observation_ref=observation_ref,
            )
    return None


def validate_snapshot(
    snapshot: PreparationSnapshot,
    *,
    candidate_entities: dict[str, str],
) -> str | None:
    if not isinstance(snapshot, PreparationSnapshot):
        return "invalid_snapshot"
    if not isinstance(snapshot.prepared_candidates, (tuple, list)):
        return "invalid_snapshot"
    for item in snapshot.prepared_candidates:
        if not isinstance(item, dict) or set(item) != _PREPARED_KEYS:
            return "invalid_prepared_candidate"
        candidate_ref = item.get("candidate_ref")
        if not isinstance(candidate_ref, str) or _CANDIDATE_REF.fullmatch(candidate_ref) is None:
            return "invalid_candidate_ref"
        if candidate_ref not in candidate_entities:
            return "invalid_candidate_binding"
        entity_ref = item.get("entity_ref")
        if not isinstance(entity_ref, str) or _ENTITY_REF.fullmatch(entity_ref) is None:
            return "invalid_entity_ref"
        if entity_ref != candidate_entities[candidate_ref]:
            return "invalid_candidate_entity_binding"
        checks = item.get("checks")
        if (
            not isinstance(checks, dict)
            or set(checks) != set(_CHECK_KEYS)
            or any(checks.get(key) not in _CHECK_STATUSES for key in _CHECK_KEYS)
        ):
            return "invalid_check_result"
        # A prepared candidate is preparation evidence only when every check passed.
        if any(checks[key] != "pass" for key in _CHECK_KEYS):
            return "invalid_check_result"
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not evidence or any(
            not isinstance(ref, str) or _ARTIFACT_REF.fullmatch(ref) is None for ref in evidence
        ):
            return "invalid_evidence"
        if item.get("qualification") != "prepared":
            return "invalid_prepared_candidate"
    return None


class ManipulationPreparationEndpoint:
    """Read-only readiness evaluation; never authorizes or produces motion."""

    def __init__(self, provider: PreparationProvider) -> None:
        self.provider = provider

    def invoke(self, arguments: Any) -> dict[str, Any]:
        error = validate_arguments(arguments)
        if error is not None:
            return error
        assert isinstance(arguments, dict)
        observation_ref = arguments["observation_ref"]
        preparation_ref = f"preparation://{arguments['scene_revision']}/{arguments['frame_id']}"
        if _PREPARATION_REF.fullmatch(preparation_ref) is None:
            return _error(
                "invalid_preparation_ref",
                "scene_revision and frame_id must form a preparation:// reference",
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
                "preparation_ref": preparation_ref,
                "candidate_set_ref": arguments["candidate_set_ref"],
                "scene_revision": arguments["scene_revision"],
                "frame": {"frame_id": arguments["frame_id"], "unit": "m"},
                "calibration_ref": arguments["calibration_ref"],
            }
        if not arguments["candidates"]:
            # An empty candidate list is a complete request; no preparation may be fabricated.
            return {
                "status": "empty",
                "preparation_ref": preparation_ref,
                "candidate_set_ref": arguments["candidate_set_ref"],
                "observation_ref": observation_ref,
                "scene_revision": arguments["scene_revision"],
                "frame": {"frame_id": arguments["frame_id"], "unit": "m"},
                "calibration_ref": arguments["calibration_ref"],
                "prepared_candidates": [],
                "checks": _unknown_checks(),
                "evidence": [],
                "motion_authorized": False,
            }
        try:
            snapshot = self.provider.prepare(dict(arguments))
        except Exception:
            # Provider failures are unavailable, never an implicit Gateway 500 or success.
            return _error(
                "preparation_provider_error",
                "manipulation preparation provider failed",
                observation_ref=observation_ref,
            )
        if snapshot is None:
            return _error(
                "preparation_unavailable",
                "manipulation preparation provider is unavailable",
                observation_ref=observation_ref,
            )
        if not isinstance(snapshot, PreparationSnapshot):
            return _error(
                "invalid_snapshot",
                "manipulation preparation provider returned an invalid snapshot",
                observation_ref=observation_ref,
            )
        if not isinstance(snapshot.provider_available, bool):
            return _error(
                "invalid_snapshot",
                "manipulation preparation provider returned an invalid availability flag",
                observation_ref=observation_ref,
            )
        if not snapshot.provider_available:
            return _error(
                "preparation_unavailable",
                "manipulation preparation provider is unavailable",
                observation_ref=observation_ref,
            )
        candidate_entities = {
            candidate["candidate_ref"]: candidate["entity_ref"] for candidate in arguments["candidates"]
        }
        snapshot_error = validate_snapshot(snapshot, candidate_entities=candidate_entities)
        if snapshot_error:
            return _error(
                snapshot_error,
                "manipulation preparation result failed contract validation",
                observation_ref=observation_ref,
            )
        prepared = [dict(item) for item in snapshot.prepared_candidates]
        evidence: list[str] = []
        for item in prepared:
            for ref in item["evidence"]:
                if ref not in evidence:
                    evidence.append(ref)
        return {
            "status": "available" if prepared else "empty",
            "preparation_ref": preparation_ref,
            "candidate_set_ref": arguments["candidate_set_ref"],
            "observation_ref": observation_ref,
            "scene_revision": arguments["scene_revision"],
            "frame": {"frame_id": arguments["frame_id"], "unit": "m"},
            "calibration_ref": arguments["calibration_ref"],
            "prepared_candidates": prepared,
            "checks": {key: "pass" for key in _CHECK_KEYS} if prepared else _unknown_checks(),
            "evidence": evidence,
            "motion_authorized": False,
        }


__all__ = [
    "PREPARATION_TOOL_ID",
    "PREPARATION_ENDPOINT_ID",
    "PREPARATION_OPERATION",
    "MANIPULATION_TOOL_SPEC",
    "PreparationProvider",
    "PreparationSnapshot",
    "ManipulationPreparationEndpoint",
]

