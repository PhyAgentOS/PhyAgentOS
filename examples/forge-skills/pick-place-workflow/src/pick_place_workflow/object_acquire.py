"""Provider-neutral bounded object acquisition Action contract."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

ACQUIRE_TOOL_ID = "object.acquire"
ACQUIRE_ENDPOINT_ID = "object_acquisition"
ACQUIRE_OPERATION = "acquire"
CAPABILITY_OUTCOME_SUMMARY_VERSION = "capability_outcome_summary_v1"

_OBSERVATION_REF = re.compile(r"^observation://[^/]+/[^/]+$")
_CANDIDATE_SET_REF = re.compile(r"^candidate-set://[^/]+/.+$")
_PREPARATION_REF = re.compile(r"^preparation://[^/]+/.+$")
_CANDIDATE_REF = re.compile(r"^candidate://[^/]+/.+$")
_ENTITY_REF = re.compile(r"^entity://[^/]+$")
_ARTIFACT_REF = re.compile(r"^artifact://[^/]+/.+$")
_METRIC_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

_CAPABILITY_PHASES = ("approach", "contact", "close", "lift", "hold", "none")
_TERMINAL_STATUSES = ("succeeded", "failed", "cancelled", "stopped", "unknown")
_FAILURE_OWNERS = (
    "none",
    "input",
    "binding",
    "readiness",
    "planner",
    "execution",
    "settlement",
    "operator",
    "infrastructure",
)
_EVIDENCE_AVAILABILITY = ("complete", "partial", "none", "unknown")

_SUMMARY_KEYS = {
    "version",
    "capability_phase",
    "status",
    "failure_owner",
    "failure_code",
    "world_change_started",
    "outcome_known",
    "evidence_availability",
    "artifact_refs",
    "bounded_metric_names",
}


class AcquireProvider(Protocol):
    """Gateway-side provider that starts one bounded acquire execution."""

    def acquire(self, request: dict[str, Any]) -> "AcquireSnapshot | None": ...


class ActionReadinessGate(Protocol):
    """Validate immutable readiness evidence before provider admission."""

    def check(self, request: dict[str, Any]) -> str | None: ...


@dataclass(frozen=True)
class AcquireSnapshot:
    """Provider-neutral terminal facts plus an internal fake pending budget."""

    capability_phase: str = "hold"
    status: str = "succeeded"
    failure_owner: str | None = None
    failure_code: str | None = None
    world_change_started: bool = False
    outcome_known: bool = True
    evidence_availability: str = "none"
    artifact_refs: tuple[str, ...] = field(default_factory=tuple)
    bounded_metric_names: tuple[str, ...] = field(default_factory=tuple)
    pending_polls: int = 0
    provider_available: bool = True


@dataclass(frozen=True)
class AcquireAdmission:
    """Validated provider plan held by the Gateway invocation owner."""

    snapshot: AcquireSnapshot
    terminal_result: dict[str, Any]


@dataclass(frozen=True)
class AcquireRejection:
    """HTTP rejection that occurs before an Action invocation is created."""

    status_code: int
    code: str
    message: str


_INPUT_KEYS = {
    "observation_ref",
    "scene_revision",
    "frame_id",
    "calibration_ref",
    "freshness_ms",
    "max_age_ms",
    "candidate_set_ref",
    "preparation_ref",
    "candidate_ref",
    "entity_ref",
}


def _summary_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_SUMMARY_KEYS),
        "properties": {
            "version": {"const": CAPABILITY_OUTCOME_SUMMARY_VERSION},
            "capability_phase": {"enum": list(_CAPABILITY_PHASES)},
            "status": {"enum": list(_TERMINAL_STATUSES)},
            "failure_owner": {"enum": list(_FAILURE_OWNERS) + [None]},
            "failure_code": {"type": ["string", "null"]},
            "world_change_started": {"type": "boolean"},
            "outcome_known": {"type": "boolean"},
            "evidence_availability": {"enum": list(_EVIDENCE_AVAILABILITY)},
            "artifact_refs": {
                "type": "array",
                "items": {"type": "string", "pattern": r"^artifact://[^/]+/.+$"},
            },
            "bounded_metric_names": {
                "type": "array",
                "items": {"type": "string", "pattern": r"^[a-z][a-z0-9_]{0,63}$"},
            },
        },
    }


def _terminal_result_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "status",
            "observation_ref",
            "scene_revision",
            "frame",
            "calibration_ref",
            "candidate_set_ref",
            "preparation_ref",
            "candidate_ref",
            "entity_ref",
            "capability_outcome_summary",
        ],
        "properties": {
            "status": {"enum": list(_TERMINAL_STATUSES)},
            "observation_ref": {
                "type": "string",
                "pattern": r"^observation://[^/]+/[^/]+$",
            },
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
            "calibration_ref": {"type": "string", "minLength": 1},
            "candidate_set_ref": {
                "type": "string",
                "pattern": r"^candidate-set://[^/]+/.+$",
            },
            "preparation_ref": {
                "type": "string",
                "pattern": r"^preparation://[^/]+/.+$",
            },
            "candidate_ref": {"type": "string", "pattern": r"^candidate://[^/]+/.+$"},
            "entity_ref": {"type": "string", "pattern": r"^entity://[^/]+$"},
            "capability_outcome_summary": _summary_schema(),
        },
    }


ACQUIRE_TOOL_SPEC: dict[str, Any] = {
    "tool_id": ACQUIRE_TOOL_ID,
    "implementation_id": "object.acquisition",
    "endpoint_id": ACQUIRE_ENDPOINT_ID,
    "operation": ACQUIRE_OPERATION,
    "semantics": "action",
    "description": (
        "Admit one bounded object acquisition workflow using a prepared grasp reference; "
        "approach, contact, close, lift, and hold remain internal Gateway phases."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "observation_ref",
            "scene_revision",
            "frame_id",
            "calibration_ref",
            "freshness_ms",
            "max_age_ms",
            "candidate_set_ref",
            "preparation_ref",
            "candidate_ref",
            "entity_ref",
        ],
        "properties": {
            "observation_ref": {"type": "string", "pattern": r"^observation://[^/]+/[^/]+$"},
            "scene_revision": {"type": "string", "minLength": 1},
            "frame_id": {"type": "string", "minLength": 1},
            "calibration_ref": {"type": "string", "minLength": 1},
            "freshness_ms": {"type": "integer", "minimum": 0},
            "max_age_ms": {"type": "integer", "minimum": 1},
            "candidate_set_ref": {
                "type": "string",
                "pattern": r"^candidate-set://[^/]+/.+$",
            },
            "preparation_ref": {"type": "string", "pattern": r"^preparation://[^/]+/.+$"},
            "candidate_ref": {"type": "string", "pattern": r"^candidate://[^/]+/.+$"},
            "entity_ref": {"type": "string", "pattern": r"^entity://[^/]+$"},
        },
    },
    "output_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["invocation_id", "attempt_id", "phase"],
        "properties": {
            "invocation_id": {"type": "string", "pattern": r"^invocation://[^/]+/.+$"},
            "attempt_id": {"type": "string", "pattern": r"^attempt://[^/]+/.+$"},
            "phase": {
                "enum": ["accepted", "running", "completed", "failed", "cancelled", "stopped", "unknown"]
            },
            "cancel_requested": {"type": "boolean"},
            "result": _terminal_result_schema(),
        },
    },
    "robot_frame_profile": {
        "observation_frame": "observation",
        "unit": "m",
        "orientation_convention": "candidate-bound",
    },
    "max_concurrency": 1,
    "cancellation": "supported_via_common_cancel_route",
    "unknown_semantics": "terminal_for_accounting_not_physical_stop",
}


def validate_arguments(arguments: Any) -> str | None:
    """Validate all Action inputs before provider or invocation allocation."""

    if not isinstance(arguments, dict):
        return "invalid_arguments"
    if set(arguments) != _INPUT_KEYS:
        return "invalid_arguments"
    observation_ref = arguments.get("observation_ref")
    scene_revision = arguments.get("scene_revision")
    frame_id = arguments.get("frame_id")
    if not isinstance(observation_ref, str) or _OBSERVATION_REF.fullmatch(observation_ref) is None:
        return "invalid_observation_ref"
    if not isinstance(scene_revision, str) or not scene_revision.strip():
        return "invalid_scene_revision"
    if not isinstance(frame_id, str) or not frame_id.strip():
        return "invalid_frame"
    if observation_ref != f"observation://{scene_revision}/{frame_id}":
        return "invalid_observation_binding"
    calibration_ref = arguments.get("calibration_ref")
    if not isinstance(calibration_ref, str) or not calibration_ref.strip():
        return "missing_calibration"
    for name, minimum in (("freshness_ms", 0), ("max_age_ms", 1)):
        value = arguments.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            return "invalid_freshness"
    candidate_set_ref = arguments.get("candidate_set_ref")
    if (
        not isinstance(candidate_set_ref, str)
        or _CANDIDATE_SET_REF.fullmatch(candidate_set_ref) is None
    ):
        return "invalid_candidate_set_ref"
    if candidate_set_ref != f"candidate-set://{scene_revision}/{frame_id}":
        return "invalid_candidate_set_binding"
    preparation_ref = arguments.get("preparation_ref")
    if not isinstance(preparation_ref, str) or _PREPARATION_REF.fullmatch(preparation_ref) is None:
        return "invalid_preparation_ref"
    if preparation_ref != f"preparation://{scene_revision}/{frame_id}":
        return "invalid_preparation_binding"
    candidate_ref = arguments.get("candidate_ref")
    if not isinstance(candidate_ref, str) or _CANDIDATE_REF.fullmatch(candidate_ref) is None:
        return "invalid_candidate_ref"
    entity_ref = arguments.get("entity_ref")
    if not isinstance(entity_ref, str) or _ENTITY_REF.fullmatch(entity_ref) is None:
        return "invalid_entity_ref"
    candidate_entity = candidate_ref.removeprefix("candidate://").split("/", 1)[0]
    if candidate_entity != entity_ref.removeprefix("entity://"):
        return "invalid_candidate_entity_binding"
    if arguments["freshness_ms"] > arguments["max_age_ms"]:
        return "stale_observation"
    return None


def _error_message(code: str) -> str:
    return {
        "invalid_arguments": "object.acquire arguments must match the strict Action schema",
        "invalid_observation_ref": "observation_ref must use observation:// scheme",
        "invalid_observation_binding": "observation_ref must match scene_revision and frame_id",
        "invalid_scene_revision": "scene_revision must be a non-empty string",
        "invalid_frame": "frame_id must be a non-empty string",
        "missing_calibration": "calibration_ref is required",
        "invalid_freshness": "freshness_ms must be non-negative and max_age_ms positive",
        "stale_observation": "observation exceeds max_age_ms",
        "invalid_candidate_set_ref": "candidate_set_ref must use candidate-set:// scheme",
        "invalid_candidate_set_binding": "candidate_set_ref must match scene_revision and frame_id",
        "invalid_preparation_ref": "preparation_ref must use preparation:// scheme",
        "invalid_preparation_binding": "preparation_ref must match scene_revision and frame_id",
        "invalid_candidate_ref": "candidate_ref must use candidate:// scheme",
        "invalid_entity_ref": "entity_ref must use entity:// scheme",
        "invalid_candidate_entity_binding": "candidate_ref must belong to entity_ref",
    }.get(code, "object.acquire request failed contract validation")


def _validate_snapshot(snapshot: AcquireSnapshot) -> str | None:
    if not isinstance(snapshot, AcquireSnapshot):
        return "invalid_snapshot"
    if snapshot.status not in _TERMINAL_STATUSES:
        return "invalid_summary_status"
    if snapshot.capability_phase not in _CAPABILITY_PHASES:
        return "invalid_capability_phase"
    if snapshot.failure_owner not in _FAILURE_OWNERS and snapshot.failure_owner is not None:
        return "invalid_failure_owner"
    if snapshot.failure_code is not None and (
        not isinstance(snapshot.failure_code, str) or not snapshot.failure_code.strip()
    ):
        return "invalid_failure_code"
    if not isinstance(snapshot.world_change_started, bool) or not isinstance(
        snapshot.outcome_known, bool
    ):
        return "invalid_summary_boolean"
    if snapshot.status == "unknown" and snapshot.outcome_known:
        return "invalid_unknown_outcome"
    if snapshot.status == "succeeded" and (
        snapshot.failure_owner not in {None, "none"} or snapshot.failure_code is not None
    ):
        return "invalid_success_failure_fields"
    if snapshot.status != "succeeded" and snapshot.failure_owner in {None, "none"}:
        return "invalid_failure_owner"
    if snapshot.status != "succeeded" and snapshot.failure_code is None:
        return "invalid_failure_code"
    if snapshot.evidence_availability not in _EVIDENCE_AVAILABILITY:
        return "invalid_evidence_availability"
    if not isinstance(snapshot.artifact_refs, (tuple, list)):
        return "invalid_artifact_refs"
    refs = list(snapshot.artifact_refs)
    if any(not isinstance(ref, str) or _ARTIFACT_REF.fullmatch(ref) is None for ref in refs):
        return "invalid_artifact_refs"
    if len(set(refs)) != len(refs):
        return "invalid_artifact_refs"
    if snapshot.evidence_availability == "none" and refs:
        return "invalid_evidence_availability"
    if snapshot.evidence_availability in {"complete", "partial"} and not refs:
        return "invalid_evidence_availability"
    if not isinstance(snapshot.bounded_metric_names, (tuple, list)):
        return "invalid_metric_names"
    metrics = list(snapshot.bounded_metric_names)
    if len(set(metrics)) != len(metrics) or any(
        not isinstance(name, str) or _METRIC_NAME.fullmatch(name) is None for name in metrics
    ):
        return "invalid_metric_names"
    if (
        isinstance(snapshot.pending_polls, bool)
        or not isinstance(snapshot.pending_polls, int)
        or snapshot.pending_polls < 0
    ):
        return "invalid_snapshot"
    if not isinstance(snapshot.provider_available, bool):
        return "invalid_snapshot"
    return None


def terminal_result(arguments: dict[str, Any], snapshot: AcquireSnapshot) -> dict[str, Any]:
    """Project provider facts into the bounded, redacted terminal ToolResult."""

    summary = {
        "version": CAPABILITY_OUTCOME_SUMMARY_VERSION,
        "capability_phase": snapshot.capability_phase,
        "status": snapshot.status,
        "failure_owner": snapshot.failure_owner,
        "failure_code": snapshot.failure_code,
        "world_change_started": snapshot.world_change_started,
        "outcome_known": snapshot.outcome_known,
        "evidence_availability": snapshot.evidence_availability,
        "artifact_refs": list(snapshot.artifact_refs),
        "bounded_metric_names": list(snapshot.bounded_metric_names),
    }
    return {
        "status": snapshot.status,
        "observation_ref": arguments["observation_ref"],
        "scene_revision": arguments["scene_revision"],
        "frame": {"frame_id": arguments["frame_id"], "unit": "m"},
        "calibration_ref": arguments["calibration_ref"],
        "candidate_set_ref": arguments["candidate_set_ref"],
        "preparation_ref": arguments["preparation_ref"],
        "candidate_ref": arguments["candidate_ref"],
        "entity_ref": arguments["entity_ref"],
        "capability_outcome_summary": summary,
    }


class ObjectAcquireEndpoint:
    """Validate and admit one bounded Action without owning Gateway lifecycle state."""

    def __init__(
        self,
        provider: AcquireProvider,
        *,
        readiness_gate: ActionReadinessGate | None = None,
    ) -> None:
        self.provider = provider
        self.readiness_gate = readiness_gate

    def admit(self, arguments: Any) -> AcquireAdmission | AcquireRejection:
        error = validate_arguments(arguments)
        if error is not None:
            status_code = {
                "missing_calibration": 422,
                "stale_observation": 409,
            }.get(error, 400)
            return AcquireRejection(status_code, error, _error_message(error))
        assert isinstance(arguments, dict)
        if self.readiness_gate is not None:
            try:
                readiness_error = self.readiness_gate.check(dict(arguments))
            except Exception:
                return AcquireRejection(
                    503,
                    "readiness_gate_error",
                    "readiness evidence gate failed",
                )
            if readiness_error is not None:
                if not isinstance(readiness_error, str) or not readiness_error.strip():
                    return AcquireRejection(
                        502,
                        "invalid_readiness_gate_result",
                        "readiness evidence gate returned an invalid result",
                    )
                return AcquireRejection(
                    409,
                    readiness_error,
                    "readiness evidence is not admissible for this Action",
                )
        try:
            snapshot = self.provider.acquire(dict(arguments))
        except Exception:
            return AcquireRejection(
                503,
                "acquire_provider_error",
                "object acquisition provider failed",
            )
        if snapshot is None:
            return AcquireRejection(
                503,
                "acquire_unavailable",
                "object acquisition provider is unavailable",
            )
        if not isinstance(snapshot, AcquireSnapshot):
            return AcquireRejection(
                502,
                "invalid_snapshot",
                "object acquisition provider returned an invalid snapshot",
            )
        if not snapshot.provider_available:
            return AcquireRejection(
                503,
                "acquire_unavailable",
                "object acquisition provider is unavailable",
            )
        snapshot_error = _validate_snapshot(snapshot)
        if snapshot_error is not None:
            return AcquireRejection(
                502,
                snapshot_error,
                "object acquisition result failed contract validation",
            )
        if self.readiness_gate is not None and snapshot.world_change_started is not False:
            return AcquireRejection(
                502,
                "motion_started_in_no_motion_mode",
                "no-motion Action provider reported world change",
            )
        return AcquireAdmission(snapshot, terminal_result(arguments, snapshot))

    def invoke(self, arguments: Any) -> AcquireAdmission | AcquireRejection:
        """Alias used by Gateway adapters that call every operation ``invoke``."""

        return self.admit(arguments)


__all__ = [
    "ACQUIRE_TOOL_ID",
    "ACQUIRE_ENDPOINT_ID",
    "ACQUIRE_OPERATION",
    "CAPABILITY_OUTCOME_SUMMARY_VERSION",
    "AcquireProvider",
    "AcquireSnapshot",
    "AcquireAdmission",
    "AcquireRejection",
    "ActionReadinessGate",
    "ACQUIRE_TOOL_SPEC",
    "ObjectAcquireEndpoint",
    "terminal_result",
    "validate_arguments",
]
