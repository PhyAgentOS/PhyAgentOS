"""No-motion RoboTwin/Curobo readiness worker.

This process is launched in the external RoboTwin20 environment.  It rebuilds
the profiled scene, evaluates each camera-frame grasp with the configured
Curobo planner, and writes an opaque evidence record outside the runtime
checkout.  It never calls ``play_once``, steps an action, or mutates the task.
The worker is intentionally strict: malformed or unbound requests return an
unavailable response instead of manufacturing prepared candidates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from worker_protocol import serve

SCHEMA_VERSION = "paos-robotwin20-readiness-live/v1"


class ReadinessProbeError(ValueError):
    """The request or planner result is not safe to project."""


def _binding(profile: Mapping[str, Any]) -> dict[str, str]:
    digest = str(profile.get("profile_digest", ""))
    if len(digest) != 64:
        import hashlib

        digest = hashlib.sha256(Path(str(profile["_profile_path"])).read_bytes()).hexdigest()
    return {
        "robot_identity": str(profile["robot_identity"]),
        "gripper_identity": str(profile["gripper_identity"]),
        "embodiment_topology": str(profile["embodiment_topology"]),
        "planner_profile": str(profile["planner_profile"]),
        "profile_digest": digest,
    }


def _artifact_path(root: Path, ref: str, suffix: str, *, must_exist: bool = True) -> Path:
    if not isinstance(ref, str) or not ref.startswith("artifact://"):
        raise ReadinessProbeError("calibration_ref is invalid")
    parts = ref.removeprefix("artifact://").split("/")
    if len(parts) < 3 or any(not p or p in {".", ".."} for p in parts):
        raise ReadinessProbeError("calibration_ref is invalid")
    path = (root.joinpath(*parts).with_suffix(suffix)).resolve()
    if root.resolve() not in path.parents or (must_exist and not path.is_file()):
        raise ReadinessProbeError("calibration artifact is unavailable")
    return path


def _validate_request(request: Mapping[str, Any], profile: Mapping[str, Any]) -> None:
    required = {
        "request_id", "observation_ref", "scene_revision", "frame_id", "calibration_ref",
        "freshness_ms", "max_age_ms", "candidate_set_ref", "candidates",
    }
    if set(request) != required:
        raise ReadinessProbeError("readiness request fields are invalid")
    request_id = request["request_id"]
    if not isinstance(request_id, str) or not request_id.strip():
        raise ReadinessProbeError("readiness request identity is invalid")
    revision = request["scene_revision"]
    frame = request["frame_id"]
    if request["calibration_ref"] != profile.get("calibration_ref"):
        raise ReadinessProbeError("readiness calibration binding is invalid")
    if request["observation_ref"] != f"observation://{revision}/{frame}":
        raise ReadinessProbeError("readiness observation binding is invalid")
    if request["candidate_set_ref"] != f"candidate-set://{revision}/{frame}":
        raise ReadinessProbeError("readiness candidate-set binding is invalid")
    expected_revision = f"{profile['task_name']}-{profile['seed']}-1"
    if revision != expected_revision:
        raise ReadinessProbeError("readiness scene revision does not match profiled scene")
    freshness_ms = request["freshness_ms"]
    max_age_ms = request["max_age_ms"]
    if (
        isinstance(freshness_ms, bool)
        or not isinstance(freshness_ms, (int, float))
        or not math.isfinite(float(freshness_ms))
        or freshness_ms < 0
        or isinstance(max_age_ms, bool)
        or not isinstance(max_age_ms, (int, float))
        or not math.isfinite(float(max_age_ms))
        or max_age_ms < 0
        or freshness_ms > max_age_ms
    ):
        raise ReadinessProbeError("readiness observation freshness is invalid or stale")
    candidates = request["candidates"]
    if not isinstance(candidates, list) or not candidates:
        raise ReadinessProbeError("readiness candidates are empty")
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ReadinessProbeError("readiness candidate is invalid")
        ref = candidate.get("candidate_ref")
        entity = candidate.get("entity_ref")
        frame_value = candidate.get("grasp_frame")
        if not isinstance(ref, str) or not ref.startswith("candidate://") or ref in seen:
            raise ReadinessProbeError("readiness candidate identity is invalid")
        if not isinstance(entity, str) or not entity.startswith("entity://"):
            raise ReadinessProbeError("readiness candidate entity is invalid")
        provenance = candidate.get("provenance")
        if (
            not isinstance(provenance, list)
            or not provenance
            or any(
                not isinstance(source, str)
                or not source.startswith(f"artifact://{revision}/")
                for source in provenance
            )
        ):
            raise ReadinessProbeError("readiness candidate provenance is unbound")
        if not isinstance(frame_value, Mapping) or frame_value.get("frame_id") != frame:
            raise ReadinessProbeError("readiness candidate frame is unbound")
        position = frame_value.get("position_m")
        orientation = frame_value.get("orientation_xyzw")
        if (
            not isinstance(position, list) or len(position) != 3
            or not isinstance(orientation, list) or len(orientation) != 4
            or any(not isinstance(v, (int, float)) or not math.isfinite(float(v)) for v in (*position, *orientation))
        ):
            raise ReadinessProbeError("readiness candidate pose is invalid")
        seen.add(ref)


def _camera_pose(candidate: Mapping[str, Any], calibration: Mapping[str, Any]) -> Any:
    import sapien.core as sapien
    import transforms3d as t3d
    frame = candidate["grasp_frame"]
    q_xyzw = np.asarray(frame["orientation_xyzw"], dtype=np.float64)
    q_norm = float(np.linalg.norm(q_xyzw))
    if q_norm <= 1e-9 or not math.isfinite(q_norm):
        raise ReadinessProbeError("candidate orientation is degenerate")
    q_xyzw = q_xyzw / q_norm
    rotation = t3d.quaternions.quat2mat([q_xyzw[3], q_xyzw[0], q_xyzw[1], q_xyzw[2]])
    local = np.eye(4, dtype=np.float64)
    local[:3, :3] = rotation
    local[:3, 3] = np.asarray(frame["position_m"], dtype=np.float64)
    # GraspGen consumes the RGB-D/OpenCV camera frame.  RoboTwin also exposes
    # an OpenGL camera transform, but its handedness/depth convention is not
    # the one used by the metric point cloud.  Use the calibrated OpenCV
    # extrinsic and lift it to a homogeneous transform explicitly.
    extrinsic = np.asarray(calibration.get("extrinsic_cv"), dtype=np.float64)
    if extrinsic.shape != (3, 4) or not bool(np.isfinite(extrinsic).all()):
        raise ReadinessProbeError("calibration extrinsic_cv is invalid")
    camera_to_world = np.eye(4, dtype=np.float64)
    camera_to_world[:3, :] = extrinsic
    world = camera_to_world @ local
    if not np.allclose(world[3], [0, 0, 0, 1], atol=1e-5):
        raise ReadinessProbeError("candidate world pose is invalid")
    quat_wxyz = t3d.quaternions.mat2quat(world[:3, :3])
    return sapien.Pose(world[:3, 3], quat_wxyz)


def _workspace_ok(pose: Any, bounds: Mapping[str, float]) -> bool:
    p = np.asarray(pose.p, dtype=np.float64)
    return bool(
        np.isfinite(p).all()
        and bounds["x_min_m"] <= p[0] <= bounds["x_max_m"]
        and bounds["y_min_m"] <= p[1] <= bounds["y_max_m"]
        and bounds["z_min_m"] <= p[2] <= bounds["z_max_m"]
    )


def _handle_factory(
    profile: Mapping[str, Any], artifact_root: Path, workspace_bounds: Mapping[str, float]
):
    from robotwin_backend import RoboTwinRuntimeProfile, RoboTwinSensorBackend

    backend = RoboTwinSensorBackend(
        RoboTwinRuntimeProfile(
            runtime_root=Path(profile["_runtime_root"]),
            artifact_root=artifact_root,
            task_name=profile["task_name"],
            task_config=profile["task_config"],
            embodiment=profile["embodiment"],
        )
    )
    backend.reset(seed=profile["seed"])
    task = backend._task
    if task is None or not hasattr(task, "robot"):
        raise ReadinessProbeError("RoboTwin task planner is unavailable")
    robot = task.robot
    calibration_path = _artifact_path(artifact_root, str(profile["calibration_ref"]), ".json")
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    binding = _binding(profile)

    def handle(request: Mapping[str, Any]) -> Mapping[str, Any]:
        _validate_request(request, profile)
        prepared: list[dict[str, Any]] = []
        for candidate in request["candidates"]:
            try:
                pose = _camera_pose(candidate, calibration)
                if not _workspace_ok(pose, workspace_bounds):
                    print(
                        f"readiness candidate {candidate['candidate_ref']} is outside workspace bounds",
                        file=sys.stderr,
                    )
                    continue
                attempts = []
                for arm_name, planner_method in (("left", robot.left_plan_path), ("right", robot.right_plan_path)):
                    try:
                        result = planner_method(pose.p.tolist() + pose.q.tolist())
                    except Exception as exc:  # planner failure remains candidate-local
                        attempts.append({"arm": arm_name, "status": "error", "error": type(exc).__name__})
                        continue
                    status = result.get("status") if isinstance(result, Mapping) else None
                    attempts.append({"arm": arm_name, "status": status})
                    if status != "Success":
                        continue
                    calibration_parts = str(request["calibration_ref"]).removeprefix("artifact://").split("/")
                    evidence_token = hashlib.sha256(
                        str(candidate["candidate_ref"]).encode("utf-8")
                    ).hexdigest()[:16]
                    evidence_ref = (
                        "artifact://" + "/".join(calibration_parts[:-1]) + "/derived/"
                        f"readiness-{evidence_token}"
                    )
                    evidence_path = _artifact_path(
                        artifact_root, evidence_ref, ".json", must_exist=False
                    )
                    evidence_path.parent.mkdir(parents=True, exist_ok=True)
                    checks = {"kinematic": "pass", "collision": "pass", "workspace": "pass"}
                    evidence = {
                        "schema_version": "paos-robotwin20-readiness-evidence/v1",
                        "captured_at": datetime.now(timezone.utc).isoformat(),
                        "request_id": request["request_id"],
                        "observation_ref": request["observation_ref"],
                        "scene_revision": request["scene_revision"],
                        "frame_id": request["frame_id"],
                        "calibration_ref": request["calibration_ref"],
                        "candidate_set_ref": request["candidate_set_ref"],
                        "candidate_ref": candidate["candidate_ref"],
                        "entity_ref": candidate["entity_ref"],
                        "worker_id": profile["worker_id"],
                        "selected_arm": arm_name,
                        "checks": checks,
                        "workspace_bounds_m": dict(workspace_bounds),
                        "collision_scope": "robot_self_and_table",
                        "planner_profile": binding["planner_profile"],
                        "embodiment_binding": binding,
                        "motion_authorized": False,
                        "planner_attempts": attempts,
                    }
                    evidence_path.write_text(json.dumps(evidence, sort_keys=True) + "\n", encoding="utf-8")
                    prepared.append({
                        "candidate_ref": candidate["candidate_ref"],
                        "entity_ref": candidate["entity_ref"],
                        "checks": checks,
                        "evidence": [evidence_ref],
                        "qualification": "prepared",
                    })
                    break
                if not any(item.get("status") == "Success" for item in attempts):
                    print(
                        f"readiness candidate {candidate['candidate_ref']} planner attempts: {attempts}",
                        file=sys.stderr,
                    )
            except ReadinessProbeError:
                raise
        return {
            "request_id": request["request_id"],
            "schema_version": SCHEMA_VERSION,
            "status": "available" if prepared else "empty",
            "worker_id": profile["worker_id"],
            "embodiment_binding": binding,
            "motion_authorized": False,
            "prepared_candidates": prepared,
            "provider_available": True,
        }

    return backend, handle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--runtime-profile", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--calibration-ref", required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument(
        "--workspace-bounds",
        nargs=6,
        type=float,
        metavar=("X_MIN", "X_MAX", "Y_MIN", "Y_MAX", "Z_MIN", "Z_MAX"),
        required=True,
    )
    args = parser.parse_args()
    with redirect_stdout(sys.stderr):
        from robotwin_backend import load_runtime_profile

        profile = load_runtime_profile(args.runtime_profile.resolve())
    profile["_profile_path"] = str(args.runtime_profile.resolve())
    profile["_runtime_root"] = str(args.runtime_root.resolve())
    profile["artifact_root"] = str(args.artifact_root.resolve())
    profile["calibration_ref"] = args.calibration_ref
    profile["worker_id"] = args.worker_id
    backend = None
    try:
        with redirect_stdout(sys.stderr):
            names = ("x_min_m", "x_max_m", "y_min_m", "y_max_m", "z_min_m", "z_max_m")
            bounds = dict(zip(names, args.workspace_bounds))
            if any(not math.isfinite(value) for value in bounds.values()) or any(
                bounds[f"{axis}_min_m"] >= bounds[f"{axis}_max_m"] for axis in ("x", "y", "z")
            ):
                raise ReadinessProbeError("workspace bounds are invalid")
            backend, handle = _handle_factory(profile, args.artifact_root.resolve(), bounds)
        return serve("robotwin20-readiness", lambda: None, handle, schema_version=SCHEMA_VERSION)
    finally:
        if backend is not None:
            backend.close()


if __name__ == "__main__":
    raise SystemExit(main())
