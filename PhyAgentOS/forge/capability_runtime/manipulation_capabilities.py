"""Provider-neutral capability snapshot Query endpoint.

The endpoint only projects a validated snapshot.  It never invokes a planner,
acquires a resource, creates an AgentTask record, or authorizes motion.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from PhyAgentOS.forge.manipulation import CapabilitySnapshot

CAPABILITY_TOOL_ID = "manipulation.capabilities"
CAPABILITY_ENDPOINT_ID = "manipulation_capabilities"
CAPABILITY_OPERATION = "describe"


class CapabilitySnapshotProvider(Protocol):
    def describe(self, request: Mapping[str, Any]) -> CapabilitySnapshot | Mapping[str, Any] | None: ...


CAPABILITY_TOOL_SPEC: dict[str, Any] = {
    "tool_id": CAPABILITY_TOOL_ID,
    "implementation_id": "manipulation.capabilities",
    "endpoint_id": CAPABILITY_ENDPOINT_ID,
    "operation": CAPABILITY_OPERATION,
    "semantics": "query",
    "description": "Describe profile-bound manipulator capabilities for one immutable scene revision.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["scene_revision", "observation_ref", "calibration_ref"],
        "properties": {
            "scene_revision": {"type": "string", "minLength": 1},
            "observation_ref": {"type": "string", "pattern": r"^observation://[^/]+/.+$"},
            "calibration_ref": {"type": "string", "pattern": r"^artifact://[^/]+/.+$"},
        },
    },
    "robot_frame_profile": {"observation_frame": "observation", "unit": "m"},
    "unknown_semantics": "terminal_for_accounting_only",
}


class CapabilitySnapshotEndpoint:
    """Validate request/snapshot identity at the generic Query boundary."""

    def __init__(self, provider: CapabilitySnapshotProvider) -> None:
        if not callable(getattr(provider, "describe", None)):
            raise TypeError("capability provider must expose describe(request)")
        self.provider = provider

    def invoke(self, arguments: Any) -> dict[str, Any]:
        if not isinstance(arguments, Mapping):
            return self._error("invalid_arguments", "capability request must be an object")
        required = {"scene_revision", "observation_ref", "calibration_ref"}
        if set(arguments) != required:
            return self._error("invalid_arguments", "capability request fields are invalid")
        scene_revision = arguments["scene_revision"]
        observation_ref = arguments["observation_ref"]
        calibration_ref = arguments["calibration_ref"]
        if not isinstance(scene_revision, str) or not scene_revision.strip():
            return self._error("invalid_scene_revision", "scene_revision is invalid")
        if (
            not isinstance(observation_ref, str)
            or not observation_ref.startswith("observation://")
            or not isinstance(calibration_ref, str)
            or not calibration_ref.startswith("artifact://")
        ):
            return self._error("invalid_binding", "capability request references are invalid")
        try:
            value = self.provider.describe(dict(arguments))
        except Exception as exc:  # provider failures remain unavailable
            return self._error("provider_unavailable", f"capability provider raised {type(exc).__name__}")
        if value is None:
            return self._error("provider_unavailable", "capability provider returned no snapshot")
        try:
            snapshot = value if isinstance(value, CapabilitySnapshot) else CapabilitySnapshot.model_validate(value)
        except Exception:
            return self._error("invalid_snapshot", "capability provider returned an invalid snapshot")
        if (
            snapshot.scene_revision != scene_revision
            or snapshot.observation_ref != observation_ref
            or snapshot.calibration_ref != calibration_ref
            or snapshot.motion_authorized is not False
        ):
            return self._error("binding_mismatch", "capability snapshot does not match request")
        return {"status": "available", **snapshot.model_dump(mode="json")}

    @staticmethod
    def _error(code: str, message: str) -> dict[str, Any]:
        return {
            "status": "invalid" if code.startswith("invalid") else "unavailable",
            "motion_authorized": False,
            "error": {"code": code, "message": message},
        }


__all__ = [
    "CAPABILITY_ENDPOINT_ID",
    "CAPABILITY_OPERATION",
    "CAPABILITY_TOOL_ID",
    "CAPABILITY_TOOL_SPEC",
    "CapabilitySnapshotEndpoint",
    "CapabilitySnapshotProvider",
]
