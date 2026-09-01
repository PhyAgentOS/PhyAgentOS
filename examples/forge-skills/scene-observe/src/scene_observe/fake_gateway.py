"""No-motion Fake Gateway implementing the PAOS Query Tool API contract."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import unquote
from uuid import uuid4

import httpx

from .grasp_proposal import (
    GRASP_ENDPOINT_ID,
    GRASP_OPERATION,
    GRASP_TOOL_ID,
    GRASP_TOOL_SPEC,
    GraspProposalEndpoint,
    GraspProposalProvider,
)
from .manipulation_prepare import (
    MANIPULATION_TOOL_SPEC,
    PREPARATION_ENDPOINT_ID,
    PREPARATION_OPERATION,
    PREPARATION_TOOL_ID,
    ManipulationPreparationEndpoint,
    PreparationProvider,
)
from .object_acquire import (
    ACQUIRE_TOOL_ID,
    ACQUIRE_TOOL_SPEC,
    AcquireAdmission,
    AcquireProvider,
    AcquireRejection,
    ObjectAcquireEndpoint,
)
from .object_place import (
    PLACE_TOOL_ID,
    PLACE_TOOL_SPEC,
    ObjectPlaceEndpoint,
    PlaceAdmission,
    PlaceProvider,
    PlaceRejection,
)
from .object_place import (
    validate_arguments as validate_place_arguments,
)
from .understanding import (
    UNDERSTANDING_ENDPOINT_ID,
    UNDERSTANDING_OPERATION,
    UNDERSTANDING_TOOL_ID,
    UNDERSTANDING_TOOL_SPEC,
    SceneUnderstandingEndpoint,
    UnderstandingProvider,
)

TOOL_ID = "scene.observe"
ENDPOINT_ID = "scene_observation"
OPERATION = "observe"
_ARTIFACT_REF = re.compile(r"^artifact://[^/]+/[^/]+$")
_OBSERVATION_REF = re.compile(r"^observation://[^/]+/[^/]+$")


class ObservationProvider(Protocol):
    def observe(self, sensor_ref: str) -> "ObservationSnapshot | None": ...


@dataclass(frozen=True)
class ObservationSnapshot:
    captured_at: datetime
    scene_revision: str
    frame_id: str
    calibration_ref: str | None
    artifacts: tuple[dict[str, str], ...] = field(default_factory=tuple)
    sensor_available: bool = True
    observation_ref: str | None = None


class SceneObservationEndpoint:
    """Provider-backed ToolEndpoint operation for the synchronous Query."""

    def __init__(self, provider: ObservationProvider, *, now: datetime | None = None) -> None:
        self.provider = provider
        self.now = now or datetime.now(timezone.utc)

    def invoke(self, arguments: Any) -> dict[str, Any]:
        checked = validate_arguments(arguments)
        if isinstance(checked, dict):
            return checked
        sensor_ref, requested_frame, max_age_ms = checked
        snapshot = self.provider.observe(sensor_ref)
        if snapshot is None or not snapshot.sensor_available:
            return _error("sensor_unavailable", "requested sensor is unavailable")
        snapshot_error = validate_snapshot(snapshot)
        if snapshot_error:
            return _error(snapshot_error, "observation failed contract validation")
        if requested_frame is not None and requested_frame != snapshot.frame_id:
            return _error("invalid_frame", "requested frame is not available")
        age_ms = max(0, int((self.now - snapshot.captured_at).total_seconds() * 1000))
        result = {
            "status": "stale" if age_ms > max_age_ms else "available",
            "observation_ref": snapshot.observation_ref
            or f"observation://{snapshot.scene_revision}/{snapshot.frame_id}",
            "captured_at": snapshot.captured_at.astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "scene_revision": snapshot.scene_revision,
            "frame": {"frame_id": snapshot.frame_id, "unit": "m"},
            "calibration_ref": snapshot.calibration_ref,
            "freshness_ms": age_ms,
            "artifacts": [dict(item) for item in snapshot.artifacts],
        }
        if result["status"] == "stale":
            result["error"] = {
                "code": "stale_observation",
                "message": "observation exceeds max_age_ms",
            }
        return result


TOOL_SPEC: dict[str, Any] = {
    "tool_id": TOOL_ID,
    "implementation_id": "scene.observation",
    "endpoint_id": ENDPOINT_ID,
    "operation": OPERATION,
    "semantics": "query",
    "description": (
        "Return a measured, calibrated scene observation without causing a physical effect."
    ),
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["sensor_ref", "max_age_ms"],
        "properties": {
            "sensor_ref": {"type": "string", "minLength": 1},
            "requested_frame": {"type": "string", "minLength": 1},
            "max_age_ms": {"type": "integer", "minimum": 1},
        },
    },
    "output_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "status", "captured_at", "scene_revision", "frame",
            "observation_ref", "calibration_ref", "freshness_ms", "artifacts",
        ],
        "properties": {
            "status": {"enum": ["available", "unavailable", "stale", "invalid"]},
            "observation_ref": {
                "type": "string",
                "pattern": r"^observation://[^/]+/[^/]+$",
            },
            "captured_at": {"type": "string", "format": "date-time"},
            "scene_revision": {"type": "string", "minLength": 1},
            "frame": {
                "type": "object",
                "additionalProperties": False,
                "required": ["frame_id"],
                "properties": {
                    "frame_id": {"type": "string", "minLength": 1},
                    "unit": {"const": "m"},
                },
            },
            "calibration_ref": {"type": ["string", "null"]},
            "freshness_ms": {"type": "integer", "minimum": 0},
            "artifacts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["ref", "kind", "media_type"],
                    "properties": {
                        "ref": {"type": "string", "pattern": r"^artifact://[^/]+/.+$"},
                        "kind": {"enum": ["rgb", "depth", "point_cloud", "state"]},
                        "media_type": {"type": "string", "minLength": 1},
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
    "robot_frame_profile": {"observation_frame": "sensor", "unit": "m"},
}


def _error(code: str, message: str) -> dict[str, Any]:
    return {
        "status": "invalid" if code.startswith("invalid") else "unavailable",
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "observation_ref": "observation://unknown/unknown",
        "scene_revision": "unknown",
        "frame": {"frame_id": "unknown", "unit": "m"},
        "calibration_ref": None,
        "freshness_ms": 0,
        "artifacts": [],
        "error": {"code": code, "message": message},
    }


def validate_arguments(arguments: Any) -> tuple[str, str | None, int] | dict[str, Any]:
    if not isinstance(arguments, dict):
        return _error("invalid_arguments", "arguments must be an object")
    if set(arguments) - {"sensor_ref", "requested_frame", "max_age_ms"}:
        return _error("invalid_arguments", "unknown scene.observe argument")
    sensor_ref = arguments.get("sensor_ref")
    requested_frame = arguments.get("requested_frame")
    max_age_ms = arguments.get("max_age_ms")
    if not isinstance(sensor_ref, str) or not sensor_ref.strip():
        return _error("invalid_sensor_ref", "sensor_ref must be a non-empty string")
    if requested_frame is not None and (
        not isinstance(requested_frame, str) or not requested_frame.strip()
    ):
        return _error("invalid_frame", "requested_frame must be a non-empty string")
    if isinstance(max_age_ms, bool) or not isinstance(max_age_ms, int) or max_age_ms < 1:
        return _error("invalid_max_age", "max_age_ms must be a positive integer")
    return sensor_ref, requested_frame, max_age_ms


def validate_snapshot(snapshot: ObservationSnapshot) -> str | None:
    if not snapshot.frame_id.strip():
        return "missing_frame"
    if snapshot.calibration_ref is None or not snapshot.calibration_ref.strip():
        return "missing_calibration"
    if snapshot.captured_at.tzinfo is None:
        return "invalid_timestamp"
    if not snapshot.scene_revision.strip():
        return "missing_scene_revision"
    observation_ref = snapshot.observation_ref or (
        f"observation://{snapshot.scene_revision}/{snapshot.frame_id}"
    )
    if _OBSERVATION_REF.fullmatch(observation_ref) is None:
        return "invalid_observation_ref"
    for artifact in snapshot.artifacts:
        if not isinstance(artifact, dict):
            return "invalid_artifact_ref"
        if (
            set(artifact) != {"ref", "kind", "media_type"}
            or not isinstance(artifact.get("ref"), str)
            or _ARTIFACT_REF.fullmatch(artifact["ref"]) is None
            or not isinstance(artifact.get("kind"), str)
            or not isinstance(artifact.get("media_type"), str)
        ):
            return "invalid_artifact_ref"
    return None


class FakeGatewayTransport(httpx.AsyncBaseTransport):
    """In-memory Gateway with Query and bounded Action conformance routes."""

    def __init__(
        self,
        provider: ObservationProvider,
        *,
        understanding_provider: UnderstandingProvider | None = None,
        grasp_provider: GraspProposalProvider | None = None,
        preparation_provider: PreparationProvider | None = None,
        acquire_provider: AcquireProvider | None = None,
        place_provider: PlaceProvider | None = None,
        now: datetime | None = None,
    ) -> None:
        self.endpoint = SceneObservationEndpoint(provider, now=now)
        self.understanding_endpoint = (
            SceneUnderstandingEndpoint(understanding_provider)
            if understanding_provider is not None
            else None
        )
        self.grasp_endpoint = (
            GraspProposalEndpoint(grasp_provider) if grasp_provider is not None else None
        )
        self.preparation_endpoint = (
            ManipulationPreparationEndpoint(preparation_provider)
            if preparation_provider is not None
            else None
        )
        self.acquire_endpoint = (
            ObjectAcquireEndpoint(acquire_provider) if acquire_provider is not None else None
        )
        self.place_endpoint = (
            ObjectPlaceEndpoint(place_provider) if place_provider is not None else None
        )
        self.invocations: dict[str, dict[str, Any]] = {}
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "GET" and path == "/tools":
            return self._ok(
                {
                    "tools": [
                        TOOL_SPEC,
                        UNDERSTANDING_TOOL_SPEC,
                        GRASP_TOOL_SPEC,
                        MANIPULATION_TOOL_SPEC,
                        ACQUIRE_TOOL_SPEC,
                        PLACE_TOOL_SPEC,
                    ]
                }
            )
        if request.method == "GET" and path == f"/tools/{TOOL_ID}":
            return self._ok(TOOL_SPEC)
        if request.method == "GET" and path == f"/tools/{TOOL_ID}/context":
            return self._ok(
                {
                    "ready": True,
                    "binding_error": None,
                    "motion_authorized": False,
                    **TOOL_SPEC["robot_frame_profile"],
                }
            )
        if request.method == "GET" and path == f"/tools/{UNDERSTANDING_TOOL_ID}":
            return self._ok(UNDERSTANDING_TOOL_SPEC)
        if request.method == "GET" and path == f"/tools/{UNDERSTANDING_TOOL_ID}/context":
            return self._ok(
                {
                    "ready": self.understanding_endpoint is not None,
                    "binding_error": (
                        None
                        if self.understanding_endpoint is not None
                        else "understanding provider is unavailable"
                    ),
                    "motion_authorized": False,
                    **UNDERSTANDING_TOOL_SPEC["robot_frame_profile"],
                }
            )
        if request.method == "GET" and path == f"/tools/{GRASP_TOOL_ID}":
            return self._ok(GRASP_TOOL_SPEC)
        if request.method == "GET" and path == f"/tools/{GRASP_TOOL_ID}/context":
            return self._ok(
                {
                    "ready": self.grasp_endpoint is not None,
                    "binding_error": (
                        None
                        if self.grasp_endpoint is not None
                        else "grasp proposal provider is unavailable"
                    ),
                    "motion_authorized": False,
                    **GRASP_TOOL_SPEC["robot_frame_profile"],
                }
            )
        if request.method == "GET" and path == f"/tools/{PREPARATION_TOOL_ID}":
            return self._ok(MANIPULATION_TOOL_SPEC)
        if request.method == "GET" and path == f"/tools/{PREPARATION_TOOL_ID}/context":
            return self._ok(
                {
                    "ready": self.preparation_endpoint is not None,
                    "binding_error": (
                        None
                        if self.preparation_endpoint is not None
                        else "manipulation preparation provider is unavailable"
                    ),
                    "motion_authorized": False,
                    **MANIPULATION_TOOL_SPEC["robot_frame_profile"],
                }
            )
        if request.method == "GET" and path == f"/tools/{ACQUIRE_TOOL_ID}":
            return self._ok(ACQUIRE_TOOL_SPEC)
        if request.method == "GET" and path == f"/tools/{ACQUIRE_TOOL_ID}/context":
            return self._ok(
                {
                    "ready": self.acquire_endpoint is not None,
                    "binding_error": (
                        None
                        if self.acquire_endpoint is not None
                        else "object acquisition provider is unavailable"
                    ),
                    "max_concurrency": 1,
                    "observation_frame": "observation",
                    "unit": "m",
                    "orientation_convention": "candidate-bound",
                    "cancellation": "supported_via_common_cancel_route",
                    "unknown_semantics": "terminal_for_accounting_not_physical_stop",
                }
            )
        if request.method == "GET" and path == f"/tools/{PLACE_TOOL_ID}":
            return self._ok(PLACE_TOOL_SPEC)
        if request.method == "GET" and path == f"/tools/{PLACE_TOOL_ID}/context":
            return self._ok(
                {
                    "ready": self.place_endpoint is not None,
                    "binding_error": (
                        None
                        if self.place_endpoint is not None
                        else "object placement provider is unavailable"
                    ),
                    "max_concurrency": 1,
                    "observation_frame": "observation",
                    "unit": "m",
                    "orientation_convention": "candidate-bound",
                    "cancellation": "supported_via_common_cancel_route",
                    "unknown_semantics": "terminal_for_accounting_not_physical_stop",
                }
            )
        if request.method == "POST" and path == f"/tools/{ENDPOINT_ID}/{OPERATION}:invoke":
            return self._invoke(request)
        if (
            request.method == "POST"
            and path == f"/tools/{UNDERSTANDING_ENDPOINT_ID}/{UNDERSTANDING_OPERATION}:invoke"
        ):
            return self._invoke_understanding(request)
        if (
            request.method == "POST"
            and path == f"/tools/{GRASP_ENDPOINT_ID}/{GRASP_OPERATION}:invoke"
        ):
            return self._invoke_grasp(request)
        if (
            request.method == "POST"
            and path == f"/tools/{PREPARATION_ENDPOINT_ID}/{PREPARATION_OPERATION}:invoke"
        ):
            return self._invoke_preparation(request)
        if request.method == "POST" and path == f"/tools/{ACQUIRE_TOOL_ID}:invoke":
            return self._admit_acquire(request)
        if request.method == "POST" and path == f"/tools/{PLACE_TOOL_ID}:invoke":
            return self._admit_place(request)
        if request.method == "GET" and path.startswith("/invocations/"):
            return self._read_invocation(request)
        if request.method == "POST" and path.startswith("/invocations/") and path.endswith("/cancel"):
            return self._cancel_invocation(request)
        return self._fail(404, "not_found", "Gateway route not found")

    def _invoke(self, request: httpx.Request) -> httpx.Response:
        try:
            payload = json.loads(request.content or b"{}")
        except json.JSONDecodeError:
            return self._fail(400, "invalid_json", "request body must be JSON")
        arguments = payload.get("arguments") if isinstance(payload, dict) else None
        return self._ok(self.endpoint.invoke(arguments))

    def _invoke_understanding(self, request: httpx.Request) -> httpx.Response:
        try:
            payload = json.loads(request.content or b"{}")
        except json.JSONDecodeError:
            return self._fail(400, "invalid_json", "request body must be JSON")
        arguments = payload.get("arguments") if isinstance(payload, dict) else None
        if self.understanding_endpoint is None:
            return self._fail(503, "unavailable", "understanding provider is unavailable")
        return self._ok(self.understanding_endpoint.invoke(arguments))

    def _invoke_grasp(self, request: httpx.Request) -> httpx.Response:
        try:
            payload = json.loads(request.content or b"{}")
        except json.JSONDecodeError:
            return self._fail(400, "invalid_json", "request body must be JSON")
        arguments = payload.get("arguments") if isinstance(payload, dict) else None
        if self.grasp_endpoint is None:
            return self._fail(503, "unavailable", "grasp proposal provider is unavailable")
        return self._ok(self.grasp_endpoint.invoke(arguments))

    def _invoke_preparation(self, request: httpx.Request) -> httpx.Response:
        try:
            payload = json.loads(request.content or b"{}")
        except json.JSONDecodeError:
            return self._fail(400, "invalid_json", "request body must be JSON")
        arguments = payload.get("arguments") if isinstance(payload, dict) else None
        if self.preparation_endpoint is None:
            return self._fail(503, "unavailable", "manipulation preparation provider is unavailable")
        return self._ok(self.preparation_endpoint.invoke(arguments))

    def _admit_acquire(self, request: httpx.Request) -> httpx.Response:
        if self.acquire_endpoint is None:
            return self._fail(503, "unavailable", "object acquisition provider is unavailable")
        if self._has_active_invocation(ACQUIRE_TOOL_ID):
            return self._fail(409, "concurrency_exhausted", "object acquisition is already active")
        try:
            payload = json.loads(request.content or b"{}")
        except json.JSONDecodeError:
            return self._fail(400, "invalid_json", "request body must be JSON")
        arguments = payload.get("arguments") if isinstance(payload, dict) else None
        admitted = self.acquire_endpoint.admit(arguments)
        if isinstance(admitted, AcquireRejection):
            return self._fail(admitted.status_code, admitted.code, admitted.message)
        assert isinstance(admitted, AcquireAdmission)
        invocation_id = f"invocation://object-acquire/{uuid4().hex[:16]}"
        attempt_id = f"attempt://object-acquire/{uuid4().hex[:16]}"
        self.invocations[invocation_id] = {
            "tool_id": ACQUIRE_TOOL_ID,
            "attempt_id": attempt_id,
            "arguments": dict(arguments),
            "pending_polls": admitted.snapshot.pending_polls,
            "terminal": False,
            "cancel_requested": False,
            "result": admitted.terminal_result,
        }
        return httpx.Response(
            202,
            json={
                "ok": True,
                "data": {"invocation_id": invocation_id, "attempt_id": attempt_id, "phase": "accepted"},
            },
        )

    def _admit_place(self, request: httpx.Request) -> httpx.Response:
        if self.place_endpoint is None:
            return self._fail(503, "unavailable", "object placement provider is unavailable")
        if self._has_active_invocation(PLACE_TOOL_ID):
            return self._fail(409, "concurrency_exhausted", "object placement is already active")
        try:
            payload = json.loads(request.content or b"{}")
        except json.JSONDecodeError:
            return self._fail(400, "invalid_json", "request body must be JSON")
        arguments = payload.get("arguments") if isinstance(payload, dict) else None
        validation_error = validate_place_arguments(arguments)
        if validation_error is not None:
            status_code = {"missing_calibration": 422, "stale_observation": 409}.get(
                validation_error, 400
            )
            return self._fail(
                status_code,
                validation_error,
                "object.place request failed contract validation",
            )
        binding_error = self._validate_acquire_binding(arguments)
        if binding_error is not None:
            status_code, code, message = binding_error
            return self._fail(status_code, code, message)
        admitted = self.place_endpoint.admit(arguments)
        if isinstance(admitted, PlaceRejection):
            return self._fail(admitted.status_code, admitted.code, admitted.message)
        assert isinstance(admitted, PlaceAdmission)
        invocation_id = f"invocation://object-place/{uuid4().hex[:16]}"
        attempt_id = f"attempt://object-place/{uuid4().hex[:16]}"
        self.invocations[invocation_id] = {
            "tool_id": PLACE_TOOL_ID,
            "attempt_id": attempt_id,
            "arguments": dict(arguments),
            "pending_polls": admitted.snapshot.pending_polls,
            "terminal": False,
            "cancel_requested": False,
            "result": admitted.terminal_result,
        }
        return httpx.Response(
            202,
            json={
                "ok": True,
                "data": {
                    "invocation_id": invocation_id,
                    "attempt_id": attempt_id,
                    "phase": "accepted",
                },
            },
        )

    def _has_active_invocation(self, tool_id: str) -> bool:
        return any(
            not record["terminal"] and record.get("tool_id") == tool_id
            for record in self.invocations.values()
        )

    def _validate_acquire_binding(
        self, arguments: dict[str, Any]
    ) -> tuple[int, str, str] | None:
        acquire_ref = arguments["acquire_invocation_ref"]
        record = self.invocations.get(acquire_ref)
        if record is None or record.get("tool_id") != ACQUIRE_TOOL_ID:
            return (404, "acquire_invocation_not_found", "acquire invocation was not found")
        if not record["terminal"]:
            return (409, "acquire_not_terminal", "acquire invocation is not terminal")
        result = record["result"]
        if not isinstance(result, dict) or result.get("status") != "succeeded":
            return (409, "acquire_not_succeeded", "acquire invocation did not succeed")
        for key in (
            "observation_ref",
            "scene_revision",
            "frame_id",
            "calibration_ref",
            "candidate_set_ref",
            "preparation_ref",
            "candidate_ref",
            "entity_ref",
        ):
            if record["arguments"].get(key) != arguments.get(key):
                return (409, "invalid_acquire_binding", "place references a different acquire binding")
        return None

    def _read_invocation(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        prefix = "/invocations/"
        suffix = "/result"
        is_result = path.endswith(suffix)
        invocation_id = unquote(path[len(prefix): -len(suffix) if is_result else None])
        if not invocation_id:
            return self._fail(404, "not_found", "Gateway route not found")
        record = self.invocations.get(invocation_id)
        if record is None:
            return self._fail(404, "not_found", "invocation was not found")
        if record["cancel_requested"]:
            record["terminal"] = True
            result = dict(record["result"])
            result["status"] = "cancelled"
            result["capability_outcome_summary"] = {
                **result["capability_outcome_summary"],
                "capability_phase": "none",
                "status": "cancelled",
                "failure_owner": "operator",
                "failure_code": "cancelled_by_operator",
                "outcome_known": True,
            }
            record["result"] = result
        elif record["pending_polls"] > 0:
            record["pending_polls"] -= 1
            return httpx.Response(
                202 if is_result else 200,
                json={
                    "ok": True,
                    "data": {
                        "invocation_id": invocation_id,
                        "attempt_id": record["attempt_id"],
                        "phase": "running",
                    },
                },
            )
        else:
            record["terminal"] = True
        result = record["result"]
        return self._ok(
            {
                "invocation_id": invocation_id,
                "attempt_id": record["attempt_id"],
                "phase": "completed" if result["status"] == "succeeded" else result["status"],
                "result": result,
            }
        )

    def _cancel_invocation(self, request: httpx.Request) -> httpx.Response:
        prefix = "/invocations/"
        suffix = "/cancel"
        invocation_id = unquote(request.url.path[len(prefix): -len(suffix)])
        record = self.invocations.get(invocation_id)
        if record is None:
            return self._fail(404, "not_found", "invocation was not found")
        if not record["terminal"]:
            record["cancel_requested"] = True
        return httpx.Response(202, json={"ok": True, "data": {"invocation_id": invocation_id, "cancel_requested": True}})

    @staticmethod
    def _ok(data: dict[str, Any]) -> httpx.Response:
        json.dumps(data, allow_nan=False)
        return httpx.Response(200, json={"ok": True, "data": data})

    @staticmethod
    def _fail(status: int, code: str, message: str) -> httpx.Response:
        return httpx.Response(
            status, json={"ok": False, "error": {"code": code, "message": message}}
        )


__all__ = [
    "FakeGatewayTransport",
    "ObservationProvider",
    "ObservationSnapshot",
    "SceneObservationEndpoint",
    "TOOL_SPEC",
]
