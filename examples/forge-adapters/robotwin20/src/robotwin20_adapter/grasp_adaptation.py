"""Calibration-bound conversion from provider grasps to executable TCP poses.

The adapter owns this deterministic frame conversion. It performs no planning,
simulation, Gateway invocation, or motion authorization.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

GRASP_ADAPTATION_PROFILE_SCHEMA_VERSION = "paos-robotwin20-grasp-adaptation/v1"


class GraspAdaptationError(ValueError):
    """A grasp, calibration, or tool-frame binding is incomplete or unsafe."""


def _vector(value: Any, length: int, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != length or any(
        isinstance(item, bool)
        or not isinstance(item, (int, float))
        or not math.isfinite(float(item))
        for item in value
    ):
        raise GraspAdaptationError(f"{label} must contain {length} finite numbers")
    return [float(item) for item in value]


def _matrix(value: Any, rows: int, columns: int, label: str) -> list[list[float]]:
    if not isinstance(value, list) or len(value) != rows:
        raise GraspAdaptationError(f"{label} must be a {rows}x{columns} matrix")
    return [_vector(row, columns, f"{label}[{index}]") for index, row in enumerate(value)]


def _homogeneous(value: Any, label: str) -> list[list[float]]:
    flat = _vector(value, 16, label)
    result = [flat[index : index + 4] for index in range(0, 16, 4)]
    _validate_rigid(result, label)
    return result


def _validate_rigid(value: list[list[float]], label: str) -> None:
    if any(abs(actual - expected) > 1e-6 for actual, expected in zip(value[3], (0, 0, 0, 1))):
        raise GraspAdaptationError(f"{label} homogeneous row is invalid")
    rotation = [row[:3] for row in value[:3]]
    for row in rotation:
        if abs(sum(item * item for item in row) - 1.0) > 1e-3:
            raise GraspAdaptationError(f"{label} rotation is invalid")
    for left, right in ((rotation[0], rotation[1]), (rotation[0], rotation[2]), (rotation[1], rotation[2])):
        if abs(sum(a * b for a, b in zip(left, right))) > 1e-3:
            raise GraspAdaptationError(f"{label} rotation is invalid")
    determinant = (
        rotation[0][0] * (rotation[1][1] * rotation[2][2] - rotation[1][2] * rotation[2][1])
        - rotation[0][1] * (rotation[1][0] * rotation[2][2] - rotation[1][2] * rotation[2][0])
        + rotation[0][2] * (rotation[1][0] * rotation[2][1] - rotation[1][1] * rotation[2][0])
    )
    if determinant <= 0 or abs(determinant - 1.0) > 1e-3:
        raise GraspAdaptationError(f"{label} rotation is invalid")


def _multiply(left: list[list[float]], right: list[list[float]]) -> list[list[float]]:
    return [
        [sum(left[row][index] * right[index][column] for index in range(4)) for column in range(4)]
        for row in range(4)
    ]


def _inverse_rigid(value: list[list[float]]) -> list[list[float]]:
    rotation = [row[:3] for row in value[:3]]
    transpose = [[rotation[column][row] for column in range(3)] for row in range(3)]
    translation = [value[row][3] for row in range(3)]
    inverse_translation = [-sum(transpose[row][index] * translation[index] for index in range(3)) for row in range(3)]
    return [
        [*transpose[0], inverse_translation[0]],
        [*transpose[1], inverse_translation[1]],
        [*transpose[2], inverse_translation[2]],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _quat_rotation(value: Any, label: str) -> list[list[float]]:
    x, y, z, w = _vector(value, 4, label)
    norm = math.sqrt(x * x + y * y + z * z + w * w)
    if norm <= 1e-9:
        raise GraspAdaptationError(f"{label} is degenerate")
    x, y, z, w = (item / norm for item in (x, y, z, w))
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]


def _rotation_quat(rotation: list[list[float]]) -> list[float]:
    trace = rotation[0][0] + rotation[1][1] + rotation[2][2]
    if trace > 0:
        scale = math.sqrt(trace + 1.0) * 2
        result = [
            (rotation[2][1] - rotation[1][2]) / scale,
            (rotation[0][2] - rotation[2][0]) / scale,
            (rotation[1][0] - rotation[0][1]) / scale,
            0.25 * scale,
        ]
    else:
        axis = max(range(3), key=lambda index: rotation[index][index])
        if axis == 0:
            scale = math.sqrt(1 + rotation[0][0] - rotation[1][1] - rotation[2][2]) * 2
            result = [0.25 * scale, (rotation[0][1] + rotation[1][0]) / scale, (rotation[0][2] + rotation[2][0]) / scale, (rotation[2][1] - rotation[1][2]) / scale]
        elif axis == 1:
            scale = math.sqrt(1 + rotation[1][1] - rotation[0][0] - rotation[2][2]) * 2
            result = [(rotation[0][1] + rotation[1][0]) / scale, 0.25 * scale, (rotation[1][2] + rotation[2][1]) / scale, (rotation[0][2] - rotation[2][0]) / scale]
        else:
            scale = math.sqrt(1 + rotation[2][2] - rotation[0][0] - rotation[1][1]) * 2
            result = [(rotation[0][2] + rotation[2][0]) / scale, (rotation[1][2] + rotation[2][1]) / scale, 0.25 * scale, (rotation[1][0] - rotation[0][1]) / scale]
    norm = math.sqrt(sum(item * item for item in result))
    return [item / norm for item in result]


def _pose_matrix(pose: Mapping[str, Any], frame_id: str) -> list[list[float]]:
    if not isinstance(pose, Mapping) or set(pose) != {
        "frame_id", "unit", "position_m", "orientation_xyzw",
    }:
        raise GraspAdaptationError("provider grasp_frame fields are invalid")
    if pose["frame_id"] != frame_id or pose["unit"] != "m":
        raise GraspAdaptationError("provider grasp_frame binding is invalid")
    rotation = _quat_rotation(pose["orientation_xyzw"], "provider grasp orientation")
    position = _vector(pose["position_m"], 3, "provider grasp position")
    return [
        [*rotation[0], position[0]],
        [*rotation[1], position[1]],
        [*rotation[2], position[2]],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _normalize(value: list[float], label: str) -> list[float]:
    norm = math.sqrt(sum(item * item for item in value))
    if norm <= 1e-9:
        raise GraspAdaptationError(f"{label} is degenerate")
    return [item / norm for item in value]


def camera_pose_to_world_matrix(
    pose: Mapping[str, Any], calibration: Mapping[str, Any], observation_frame_id: str
) -> list[list[float]]:
    """Transform one OpenCV camera-frame pose into RoboTwin world coordinates."""

    if not isinstance(calibration, Mapping) or calibration.get("camera_name") != observation_frame_id:
        raise GraspAdaptationError("calibration camera does not match observation frame")
    extrinsic = _matrix(calibration.get("extrinsic_cv"), 3, 4, "calibration extrinsic_cv")
    camera_from_world = [*extrinsic, [0.0, 0.0, 0.0, 1.0]]
    _validate_rigid(camera_from_world, "calibration extrinsic_cv")
    world_from_camera = _inverse_rigid(camera_from_world)
    camera_from_provider = _pose_matrix(pose, observation_frame_id)
    return _multiply(world_from_camera, camera_from_provider)


def adapt_grasp_candidate(
    proposal: Mapping[str, Any],
    calibration_payload: bytes,
    base_request: Mapping[str, Any],
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    """Convert one bound provider grasp into the route frame without side effects."""

    required_profile = {
        "schema_version", "extrinsic_semantics", "provider_T_tcp",
        "adaptation_provenance_ref", "support_clear_direction",
        "max_linear_speed_mps", "max_joint_speed_radps",
    }
    if not isinstance(profile, Mapping) or set(profile) != required_profile:
        raise GraspAdaptationError("grasp adaptation profile fields are invalid")
    if profile["schema_version"] != GRASP_ADAPTATION_PROFILE_SCHEMA_VERSION:
        raise GraspAdaptationError("grasp adaptation profile schema is unsupported")
    if profile["extrinsic_semantics"] != "world_to_camera_cv":
        raise GraspAdaptationError("grasp adaptation extrinsic semantics are unsupported")
    required_base = {
        "observation_ref", "observation_frame_id", "scene_revision", "frame_id",
        "calibration_ref", "calibration_sha256", "calibration_revision", "candidate_set_ref",
    }
    if not isinstance(base_request, Mapping) or not required_base.issubset(base_request):
        raise GraspAdaptationError("grasp adaptation request binding is incomplete")
    if base_request["frame_id"] != "world":
        raise GraspAdaptationError("grasp adaptation currently requires the world route frame")
    if hashlib.sha256(calibration_payload).hexdigest() != base_request["calibration_sha256"]:
        raise GraspAdaptationError("calibration payload digest does not match request")
    try:
        calibration = json.loads(calibration_payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GraspAdaptationError("calibration payload is invalid JSON") from exc
    required_proposal = {
        "candidate_ref", "entity_ref", "grasp_frame", "approach_direction",
        "score", "confidence", "provenance", "qualification",
    }
    if not isinstance(proposal, Mapping) or set(proposal) != required_proposal:
        raise GraspAdaptationError("provider proposal fields are invalid")
    grasp_frame = proposal["grasp_frame"]
    world_from_provider = camera_pose_to_world_matrix(
        grasp_frame, calibration, base_request["observation_frame_id"]
    )
    provider_to_tcp = _homogeneous(profile["provider_T_tcp"], "provider_T_tcp")
    world_from_tcp = _multiply(world_from_provider, provider_to_tcp)

    approach = proposal["approach_direction"]
    if not isinstance(approach, Mapping) or set(approach) != {"frame_id", "unit", "vector"}:
        raise GraspAdaptationError("provider approach_direction fields are invalid")
    if approach["frame_id"] != base_request["observation_frame_id"] or approach["unit"] != "unitless":
        raise GraspAdaptationError("provider approach_direction binding is invalid")
    camera_direction = _vector(approach["vector"], 3, "provider approach direction")
    extrinsic = _matrix(calibration.get("extrinsic_cv"), 3, 4, "calibration extrinsic_cv")
    world_from_camera = _inverse_rigid([*extrinsic, [0.0, 0.0, 0.0, 1.0]])
    rotation = [row[:3] for row in world_from_camera[:3]]
    ingress = _normalize(
        [sum(rotation[row][index] * camera_direction[index] for index in range(3)) for row in range(3)],
        "world ingress direction",
    )

    support = profile["support_clear_direction"]
    if not isinstance(support, Mapping) or set(support) != {"frame_id", "vector", "provenance_ref"}:
        raise GraspAdaptationError("support_clear_direction fields are invalid")
    if support["frame_id"] != "world" or not isinstance(support["provenance_ref"], str) or not support["provenance_ref"].startswith("artifact://"):
        raise GraspAdaptationError("support_clear_direction binding is invalid")
    support_vector = _normalize(_vector(support["vector"], 3, "support clear direction"), "support clear direction")
    provenance_ref = profile["adaptation_provenance_ref"]
    if not isinstance(provenance_ref, str) or not provenance_ref.startswith("artifact://"):
        raise GraspAdaptationError("adaptation provenance_ref is invalid")
    speeds = {}
    for key in ("max_linear_speed_mps", "max_joint_speed_radps"):
        value = profile[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
            raise GraspAdaptationError(f"{key} must be positive")
        speeds[key] = float(value)

    return {
        "contact_tcp_pose": {
            "frame_id": "world",
            "position_m": [world_from_tcp[index][3] for index in range(3)],
            "orientation_xyzw": _rotation_quat([row[:3] for row in world_from_tcp[:3]]),
            **speeds,
        },
        "ingress_direction": {
            "frame_id": "world",
            "vector": ingress,
            "provenance_ref": provenance_ref,
        },
        "support_clear_direction": {
            "frame_id": "world",
            "vector": support_vector,
            "provenance_ref": support["provenance_ref"],
        },
        "adaptation_provenance_ref": provenance_ref,
    }


__all__ = [
    "GRASP_ADAPTATION_PROFILE_SCHEMA_VERSION",
    "GraspAdaptationError",
    "adapt_grasp_candidate",
    "camera_pose_to_world_matrix",
]
