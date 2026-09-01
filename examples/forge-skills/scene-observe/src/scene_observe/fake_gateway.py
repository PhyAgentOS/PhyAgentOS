"""No-motion Fake Gateway implementing the PAOS Query Tool API contract."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

import httpx

TOOL_ID = "scene.observe"
ENDPOINT_ID = "scene_observation"
OPERATION = "observe"
_ARTIFACT_REF = re.compile(r"^artifact://[^/]+/[^/]+$")


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
            "calibration_ref", "freshness_ms", "artifacts",
        ],
        "properties": {
            "status": {"enum": ["available", "unavailable", "stale", "invalid"]},
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
    """In-memory Gateway transport; all calls are read-only except Query POST."""

    def __init__(self, provider: ObservationProvider, *, now: datetime | None = None) -> None:
        self.endpoint = SceneObservationEndpoint(provider, now=now)
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "GET" and path == "/tools":
            return self._ok({"tools": [TOOL_SPEC]})
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
        if request.method == "POST" and path == f"/tools/{ENDPOINT_ID}/{OPERATION}:invoke":
            return self._invoke(request)
        return self._fail(404, "not_found", "Gateway route not found")

    def _invoke(self, request: httpx.Request) -> httpx.Response:
        try:
            payload = json.loads(request.content or b"{}")
        except json.JSONDecodeError:
            return self._fail(400, "invalid_json", "request body must be JSON")
        arguments = payload.get("arguments") if isinstance(payload, dict) else None
        return self._ok(self.endpoint.invoke(arguments))

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
