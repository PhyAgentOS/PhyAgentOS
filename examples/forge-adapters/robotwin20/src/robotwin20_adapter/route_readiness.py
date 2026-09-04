"""Provider-neutral contract for complete simulation route readiness.

The contract is intentionally stricter than the existing terminal-pose
readiness result.  It can be consumed by an external RoboTwin/planner worker,
but validation alone never authorizes motion or claims contact success.
"""

from __future__ import annotations

import hashlib
import math
import os
from pathlib import Path
from typing import Any, Mapping

from .perception_profile import PerceptionProfileError, _absolute_path, _worker_config
from .process_worker import JsonlProcessWorkerClient

SIMULATION_ROUTE_READINESS_SCHEMA_VERSION = "paos-robotwin20-simulation-route-readiness/v1"
ROUTE_READINESS_PROFILE_SCHEMA_VERSION = "paos-robotwin20-route-readiness/v1"
ROUTE_PHASES = (
    "approach",
    "contact",
    "close",
    "lift",
    "transport",
    "descent",
    "release",
    "retreat",
)
ROUTE_CHECKS = (
    "attached_object_collision",
    "complete_transport_descent_retreat",
    "contact_dynamics",
    "workspace_and_joint_limits",
    "stop_control",
    "semantic_verification",
)
_REF_PREFIXES = {
    "observation_ref": "observation://",
    "candidate_set_ref": "candidate-set://",
    "candidate_ref": "candidate://",
    "entity_ref": "entity://",
    "artifact_ref": "artifact://",
}


class RouteReadinessError(ValueError):
    """A route request or evidence record is malformed or unsafe."""


class RouteReadinessProfileError(RouteReadinessError):
    """A route-readiness worker profile is incomplete or unsafe."""


class RouteReadinessClient:
    """Profile-owned bounded JSONL client for the external route worker."""

    def __init__(self, client: JsonlProcessWorkerClient, *, worker_id: str) -> None:
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise RouteReadinessProfileError("route readiness worker_id must be non-empty")
        self.client = client
        self.worker_id = worker_id

    def evaluate(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        validate_route_request(request)
        response = self.client.request(dict(request))
        if response.get("request_id") != request["request_id"]:
            raise RouteReadinessProfileError("route readiness response identity mismatch")
        if response.get("schema_version") != SIMULATION_ROUTE_READINESS_SCHEMA_VERSION:
            raise RouteReadinessProfileError("route readiness response schema mismatch")
        if response.get("worker_id") != self.worker_id:
            raise RouteReadinessProfileError("route readiness worker identity mismatch")
        if response.get("motion_authorized") is not False:
            raise RouteReadinessProfileError("route readiness worker is not no-motion")
        if response.get("status") != "unavailable" or response.get("provider_available") is not False:
            raise RouteReadinessProfileError("route readiness worker must remain unavailable until capabilities exist")
        evidence = response.get("route_evidence")
        if not isinstance(evidence, list) or len(evidence) != len(request["candidates"]):
            raise RouteReadinessProfileError("route readiness evidence cardinality is invalid")
        expected = {candidate["candidate_ref"]: candidate["entity_ref"] for candidate in request["candidates"]}
        seen: set[str] = set()
        for item in evidence:
            if not isinstance(item, Mapping) or item.get("candidate_ref") not in expected:
                raise RouteReadinessProfileError("route readiness evidence candidate is unbound")
            if item["candidate_ref"] in seen or item.get("entity_ref") != expected[item["candidate_ref"]]:
                raise RouteReadinessProfileError("route readiness evidence identity is invalid")
            if item.get("motion_authorized") is not False or item.get("world_change_started") is not False:
                raise RouteReadinessProfileError("route readiness evidence must be no-motion")
            seen.add(item["candidate_ref"])
        return dict(response)

    def release(self) -> None:
        self.client.release()


def _finite_vector(value: Any, length: int, label: str) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != length:
        raise RouteReadinessError(f"{label} must be an array of length {length}")
    result = tuple(float(item) for item in value) if all(
        isinstance(item, (int, float)) and not isinstance(item, bool) for item in value
    ) else ()
    if len(result) != length or any(not math.isfinite(item) for item in result):
        raise RouteReadinessError(f"{label} must contain finite numbers")
    return result


def _ref(value: Any, label: str, prefix: str | None = None) -> str:
    if not isinstance(value, str) or not value.strip() or (prefix and not value.startswith(prefix)):
        raise RouteReadinessError(f"{label} is invalid")
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise RouteReadinessError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _validate_pose(value: Any, frame_id: str, label: str) -> tuple[float, ...]:
    if not isinstance(value, Mapping) or set(value) != {
        "frame_id", "position_m", "orientation_xyzw", "max_linear_speed_mps", "max_joint_speed_radps",
    }:
        raise RouteReadinessError(f"{label} fields are invalid")
    if value["frame_id"] != frame_id:
        raise RouteReadinessError(f"{label} frame binding is invalid")
    position = _finite_vector(value["position_m"], 3, f"{label}.position_m")
    orientation = _finite_vector(value["orientation_xyzw"], 4, f"{label}.orientation_xyzw")
    norm = math.sqrt(sum(item * item for item in orientation))
    if norm < 1e-9:
        raise RouteReadinessError(f"{label}.orientation_xyzw is degenerate")
    for key in ("max_linear_speed_mps", "max_joint_speed_radps"):
        speed = value[key]
        if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not math.isfinite(float(speed)) or speed <= 0:
            raise RouteReadinessError(f"{label}.{key} must be positive")
    return position


def _validate_transform(value: Any, label: str) -> None:
    matrix = _finite_vector(value, 16, label)
    if any(abs(matrix[index] - expected) > 1e-6 for index, expected in zip((12, 13, 14, 15), (0.0, 0.0, 0.0, 1.0))):
        raise RouteReadinessError(f"{label} homogeneous row is invalid")
    rows = [matrix[0:3], matrix[4:7], matrix[8:11]]
    for row in rows:
        if abs(sum(item * item for item in row) - 1.0) > 1e-3:
            raise RouteReadinessError(f"{label} rotation is invalid")
    for left, right in ((rows[0], rows[1]), (rows[0], rows[2]), (rows[1], rows[2])):
        if abs(sum(a * b for a, b in zip(left, right))) > 1e-3:
            raise RouteReadinessError(f"{label} rotation is invalid")
    determinant = (
        rows[0][0] * (rows[1][1] * rows[2][2] - rows[1][2] * rows[2][1])
        - rows[0][1] * (rows[1][0] * rows[2][2] - rows[1][2] * rows[2][0])
        + rows[0][2] * (rows[1][0] * rows[2][1] - rows[1][1] * rows[2][0])
    )
    if determinant <= 0:
        raise RouteReadinessError(f"{label} rotation is invalid")


def validate_route_request(request: Mapping[str, Any]) -> None:
    """Validate a complete route request before any planner call."""
    required = {
        "request_id", "observation_ref", "scene_revision", "frame_id", "calibration_ref",
        "candidate_set_ref", "candidates", "workspace_bounds_m", "joint_limits_ref", "stop_policy_ref",
    }
    if not isinstance(request, Mapping) or set(request) != required:
        raise RouteReadinessError("route readiness request fields are invalid")
    _ref(request["request_id"], "request_id")
    revision = _ref(request["scene_revision"], "scene_revision")
    frame = _ref(request["frame_id"], "frame_id")
    observation = _ref(request["observation_ref"], "observation_ref", "observation://")
    if observation != f"observation://{revision}/{frame}":
        raise RouteReadinessError("observation identity is invalid")
    candidate_set = _ref(request["candidate_set_ref"], "candidate_set_ref", "candidate-set://")
    if candidate_set != f"candidate-set://{revision}/{frame}":
        raise RouteReadinessError("candidate-set identity is invalid")
    _ref(request["calibration_ref"], "calibration_ref", "artifact://")
    _ref(request["joint_limits_ref"], "joint_limits_ref", "artifact://")
    _ref(request["stop_policy_ref"], "stop_policy_ref", "artifact://")
    bounds = request["workspace_bounds_m"]
    if not isinstance(bounds, Mapping) or set(bounds) != {
        "x_min_m", "x_max_m", "y_min_m", "y_max_m", "z_min_m", "z_max_m",
    }:
        raise RouteReadinessError("workspace_bounds_m fields are invalid")
    for axis in "xyz":
        low = bounds[f"{axis}_min_m"]
        high = bounds[f"{axis}_max_m"]
        if any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)) for item in (low, high)) or low >= high:
            raise RouteReadinessError("workspace bounds are invalid")
    candidates = request["candidates"]
    if not isinstance(candidates, list) or not candidates:
        raise RouteReadinessError("route readiness candidates are empty")
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, Mapping) or set(candidate) != {
            "candidate_ref", "entity_ref", "provenance", "grasp_frame", "attached_object", "route",
        }:
            raise RouteReadinessError("route candidate fields are invalid")
        candidate_ref = _ref(candidate["candidate_ref"], "candidate_ref", "candidate://")
        if candidate_ref in seen:
            raise RouteReadinessError("route candidate identity is duplicated")
        seen.add(candidate_ref)
        _ref(candidate["entity_ref"], "entity_ref", "entity://")
        provenance = candidate["provenance"]
        if not isinstance(provenance, list) or not provenance or any(
            not isinstance(item, str) or not item.startswith("artifact://") for item in provenance
        ):
            raise RouteReadinessError("route candidate provenance is invalid")
        _validate_pose(candidate["grasp_frame"], frame, "grasp_frame")
        attached = candidate["attached_object"]
        if not isinstance(attached, Mapping) or set(attached) != {
            "geometry_ref", "geometry_sha256", "frame_id", "half_extents_m", "grasp_transform",
        }:
            raise RouteReadinessError("attached object fields are invalid")
        _ref(attached["geometry_ref"], "attached_object.geometry_ref", "artifact://")
        _sha(attached["geometry_sha256"], "attached_object.geometry_sha256")
        if attached["frame_id"] != frame:
            raise RouteReadinessError("attached object frame binding is invalid")
        half_extents = _finite_vector(attached["half_extents_m"], 3, "attached_object.half_extents_m")
        if any(value <= 0 for value in half_extents):
            raise RouteReadinessError("attached object half extents must be positive")
        _validate_transform(attached["grasp_transform"], "attached_object.grasp_transform")
        route = candidate["route"]
        if not isinstance(route, list) or [item.get("phase") for item in route if isinstance(item, Mapping)] != list(ROUTE_PHASES):
            raise RouteReadinessError("route phases must be complete and ordered")
        for item in route:
            if not isinstance(item, Mapping) or set(item) != {"phase", "waypoints", "gripper_state"}:
                raise RouteReadinessError("route phase fields are invalid")
            if item["phase"] not in ROUTE_PHASES:
                raise RouteReadinessError("route phase is invalid")
            if item["gripper_state"] not in {"open", "contact", "closed", "released"}:
                raise RouteReadinessError("route gripper state is invalid")
            waypoints = item["waypoints"]
            if not isinstance(waypoints, list) or not waypoints:
                raise RouteReadinessError("route phase must contain waypoints")
            for index, waypoint in enumerate(waypoints):
                position = _validate_pose(waypoint, frame, f"route.{item['phase']}.waypoints[{index}]")
                half_extents = _finite_vector(attached["half_extents_m"], 3, "attached_object.half_extents_m")
                conservative_extent = max(half_extents)
                for axis, coordinate in zip("xyz", position):
                    if coordinate - conservative_extent < bounds[f"{axis}_min_m"] or coordinate + conservative_extent > bounds[f"{axis}_max_m"]:
                        raise RouteReadinessError("route waypoint or attached object exceeds workspace bounds")


def route_geometry_digest(request: Mapping[str, Any]) -> str:
    """Return a stable digest for the validated route/geometry input."""
    validate_route_request(request)
    import json

    payload = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_route_readiness_profile(path: str | os.PathLike[str]) -> dict[str, Any]:
    profile_path = Path(path).expanduser()
    if not profile_path.is_absolute() or not profile_path.is_file() or profile_path.is_symlink():
        raise RouteReadinessProfileError("route readiness profile must be an existing absolute regular file")
    try:
        import yaml
    except ImportError as exc:
        raise RouteReadinessProfileError("PyYAML is required to load route readiness profiles") from exc
    try:
        value = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise RouteReadinessProfileError("route readiness profile could not be loaded") from exc
    if not isinstance(value, dict):
        raise RouteReadinessProfileError("route readiness profile must contain an object")
    return value


def build_route_readiness_client(
    profile: Mapping[str, Any], *, environ: Mapping[str, str] | None = None
) -> RouteReadinessClient:
    required = {"schema_version", "worker_id", "artifact_root", "worker"}
    if not isinstance(profile, Mapping) or set(profile) != required:
        raise RouteReadinessProfileError("route readiness profile fields are invalid")
    if profile.get("schema_version") != ROUTE_READINESS_PROFILE_SCHEMA_VERSION:
        raise RouteReadinessProfileError("route readiness profile schema_version is unsupported")
    variables = dict(os.environ if environ is None else environ)
    worker_id = profile.get("worker_id")
    if not isinstance(worker_id, str) or not worker_id.strip():
        raise RouteReadinessProfileError("route readiness worker_id is invalid")
    try:
        artifact_root = _absolute_path(profile.get("artifact_root"), variables, "route artifact_root", must_be_directory=True)
        worker_config = _worker_config(profile.get("worker"), variables, "route worker")
    except PerceptionProfileError as exc:
        raise RouteReadinessProfileError(str(exc)) from exc
    arguments = worker_config.command
    if "--artifact-root" not in arguments or str(artifact_root) not in arguments:
        raise RouteReadinessProfileError("route worker must bind the configured artifact_root")
    if "--worker-id" not in arguments or worker_id not in arguments:
        raise RouteReadinessProfileError("route worker must bind the configured worker_id")
    return RouteReadinessClient(JsonlProcessWorkerClient(worker_config), worker_id=worker_id)


def project_route_evidence(
    request: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    capability_status: Mapping[str, str],
    evidence_ref: str,
) -> dict[str, Any]:
    """Project one candidate's route evidence without granting motion."""
    validate_route_request(request)
    if candidate not in request["candidates"]:
        raise RouteReadinessError("route candidate is not bound to request")
    if not isinstance(capability_status, Mapping) or set(capability_status) != set(ROUTE_CHECKS):
        raise RouteReadinessError("route capability status fields are invalid")
    if any(status not in {"pass", "fail", "unavailable"} for status in capability_status.values()):
        raise RouteReadinessError("route capability status is invalid")
    _ref(evidence_ref, "evidence_ref", "artifact://")
    return {
        "schema_version": SIMULATION_ROUTE_READINESS_SCHEMA_VERSION,
        "request_id": request["request_id"],
        "observation_ref": request["observation_ref"],
        "scene_revision": request["scene_revision"],
        "frame_id": request["frame_id"],
        "calibration_ref": request["calibration_ref"],
        "candidate_set_ref": request["candidate_set_ref"],
        "candidate_ref": candidate["candidate_ref"],
        "entity_ref": candidate["entity_ref"],
        "route_geometry_digest": route_geometry_digest(request),
        "route_phase_order": list(ROUTE_PHASES),
        "checks": dict(capability_status),
        "evidence": [evidence_ref],
        "collision_scope": "attached_object_and_static_scene" if capability_status["attached_object_collision"] == "pass" else "unavailable",
        "motion_authorized": False,
        "world_change_started": False,
    }


__all__ = [
    "ROUTE_CHECKS",
    "ROUTE_PHASES",
    "ROUTE_READINESS_PROFILE_SCHEMA_VERSION",
    "SIMULATION_ROUTE_READINESS_SCHEMA_VERSION",
    "RouteReadinessError",
    "RouteReadinessClient",
    "RouteReadinessProfileError",
    "build_route_readiness_client",
    "load_route_readiness_profile",
    "project_route_evidence",
    "route_geometry_digest",
    "validate_route_request",
]
