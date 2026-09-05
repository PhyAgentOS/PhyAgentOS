"""Independent, explicitly authorized RoboTwin simulation evidence producer.

This worker is the *external probe* paired with ``route_evidence``.  Unlike
the verifier, it is allowed to step one RoboTwin scene, but only after an
approval record and a producer/profile binding have been checked.  It never
creates a PAOS Gateway invocation, calls Dora, or talks to hardware.

The worker executes one candidate route at a time.  Every planner segment is
checked against the robot joint limits, every simulator step is monitored for
timeouts/stop requests and contacts, and immutable before/after/scope
artifacts are written below the configured artifact root.  Any missing or
ambiguous input returns ``unavailable`` rather than a partial pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from worker_protocol import serve

from robotwin20_adapter.route_readiness import (
    ROUTE_PHASES,
    route_geometry_digest,
    validate_route_request,
)

SCHEMA_VERSION = "paos-robotwin20-simulation-probe/v1"
APPROVAL_SCHEMA_VERSION = "paos-robotwin20-simulation-probe-approval/v1"
_STATE_FIELDS = ("scene_revision", "observation_ref", "frame_id", "candidate_set_ref")
_GRIPPER_VALUES = {"open": 1.0, "contact": 1.0, "closed": 0.0, "released": 1.0}
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class SimulationProbeError(ValueError):
    """The probe request or runtime result is unsafe or incomplete."""


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _artifact_path(root: Path, ref: str, *, create_parent: bool = False) -> Path:
    if not isinstance(ref, str) or not ref.startswith("artifact://"):
        raise SimulationProbeError("probe artifact_ref is invalid")
    parts = ref.removeprefix("artifact://").split("/")
    if len(parts) < 2 or any(not part or part in {".", ".."} for part in parts):
        raise SimulationProbeError("probe artifact_ref is invalid")
    path = root.joinpath(*parts)
    if not path.suffix:
        path = path.with_suffix(".json")
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise SimulationProbeError("probe artifact path is unsafe")
    resolved_root = root.resolve()
    resolved = path.resolve()
    if resolved_root not in resolved.parents and resolved != resolved_root:
        raise SimulationProbeError("probe artifact path escapes artifact root")
    return resolved


def _artifact_record(root: Path, ref: str, payload: bytes) -> dict[str, str]:
    path = _artifact_path(root, ref, create_parent=True)
    if path.exists():
        if path.is_symlink() or path.read_bytes() != payload:
            raise SimulationProbeError("probe artifact is immutable and divergent")
    else:
        with path.open("xb") as stream:
            stream.write(payload)
        path.chmod(0o600)
    return {"artifact_ref": ref, "sha256": _sha_bytes(payload)}


def _json_artifact(root: Path, ref: str, value: Mapping[str, Any]) -> dict[str, str]:
    return _artifact_record(
        root,
        ref,
        (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"),
    )


def _candidate_token(candidate_ref: str) -> str:
    token = candidate_ref.removeprefix("candidate://").replace("/", "-")
    if _SAFE_TOKEN.fullmatch(token) is None:
        raise SimulationProbeError("probe candidate_ref cannot form a safe artifact identity")
    return token


def _load_json_artifact(root: Path, ref: str) -> Mapping[str, Any]:
    path = _artifact_path(root, ref)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SimulationProbeError("probe JSON artifact is invalid") from exc
    if not isinstance(value, Mapping):
        raise SimulationProbeError("probe JSON artifact must be an object")
    return value


def _validate_approval(
    root: Path,
    ref: str,
    *,
    producer_id: str,
    producer_profile_sha256: str,
    request: Mapping[str, Any],
    candidate_ref: str,
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    approval = _load_json_artifact(root, ref)
    required = {
        "schema_version", "decision", "motion_authorized", "producer_id",
        "producer_profile_sha256", "task_name", "scene_revision", "embodiment_binding",
        "request_id", "candidate_ref", "route_geometry_digest", "reviewer_id", "reviewed_at",
        "calibration_sha256", "joint_limits_sha256", "stop_policy_sha256",
    }
    if set(approval) != required or approval["schema_version"] != APPROVAL_SCHEMA_VERSION:
        raise SimulationProbeError("probe approval record fields are invalid")
    if approval["decision"] != "approved_independent_simulation_probe" or approval["motion_authorized"] is not True:
        raise SimulationProbeError("probe approval does not authorize simulation probe")
    if approval["producer_id"] != producer_id or approval["producer_profile_sha256"] != producer_profile_sha256:
        raise SimulationProbeError("probe approval producer binding is invalid")
    if approval["task_name"] != profile["task_name"] or approval["scene_revision"] != request["scene_revision"]:
        raise SimulationProbeError("probe approval scene binding is invalid")
    if (
        approval["request_id"] != request["request_id"]
        or approval["candidate_ref"] != candidate_ref
        or approval["route_geometry_digest"] != route_geometry_digest(request)
    ):
        raise SimulationProbeError("probe approval route binding is invalid")
    if approval["embodiment_binding"] != profile["embodiment_binding"]:
        raise SimulationProbeError("probe approval embodiment binding is invalid")
    for digest_field, ref_field in (
        ("calibration_sha256", "calibration_ref"),
        ("joint_limits_sha256", "joint_limits_ref"),
        ("stop_policy_sha256", "stop_policy_ref"),
    ):
        expected_digest = approval[digest_field]
        if (
            not isinstance(expected_digest, str)
            or len(expected_digest) != 64
            or any(char not in "0123456789abcdef" for char in expected_digest)
            or expected_digest
            != _sha_bytes(_artifact_path(root, request[ref_field]).read_bytes())
        ):
            raise SimulationProbeError(f"probe approval {ref_field} digest binding is invalid")
    if not isinstance(approval["reviewer_id"], str) or not approval["reviewer_id"].strip():
        raise SimulationProbeError("probe approval reviewer is missing")
    if not isinstance(approval["reviewed_at"], str) or not approval["reviewed_at"].strip():
        raise SimulationProbeError("probe approval timestamp is missing")
    try:
        parsed = datetime.fromisoformat(approval["reviewed_at"])
    except ValueError as exc:
        raise SimulationProbeError("probe approval timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise SimulationProbeError("probe approval timestamp must include timezone")
    return dict(approval)


def _route_pose(pose_value: Mapping[str, Any], route_frame_id: str) -> list[float]:
    import numpy as np
    import transforms3d as t3d

    if pose_value.get("frame_id") != route_frame_id:
        raise SimulationProbeError("route pose frame binding is invalid")
    q = np.asarray(pose_value["orientation_xyzw"], dtype=np.float64)
    norm = float(np.linalg.norm(q))
    if norm <= 1e-9 or not math.isfinite(norm):
        raise SimulationProbeError("candidate orientation is degenerate")
    q = q / norm
    position = np.asarray(pose_value["position_m"], dtype=np.float64)
    if position.shape != (3,) or not bool(np.isfinite(position).all()):
        raise SimulationProbeError("route pose position is invalid")
    q_wxyz = t3d.quaternions.mat2quat(
        t3d.quaternions.quat2mat([q[3], q[0], q[1], q[2]])
    )
    return position.tolist() + q_wxyz.tolist()


def _contact_state(
    task: Any,
    *,
    phase: str,
    step: int,
    attached: bool = False,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for contact in task.scene.get_contacts():
        left = str(contact.bodies[0].entity.name)
        right = str(contact.bodies[1].entity.name)
        impulses: list[float] = []
        for point in contact.points:
            try:
                vector = [float(item) for item in point.impulse]
            except (AttributeError, TypeError, ValueError) as exc:
                raise SimulationProbeError("simulator contact impulse is unavailable") from exc
            if len(vector) != 3 or any(not math.isfinite(item) for item in vector):
                raise SimulationProbeError("simulator contact impulse is invalid")
            impulses.append(math.sqrt(sum(item * item for item in vector)))
        max_impulse = max(impulses, default=0.0)
        records.append(
            {
                "phase": phase,
                "step": step,
                "pair": sorted((left, right)),
                "point_count": len(impulses),
                "max_impulse_ns": max_impulse,
                "active_contact": max_impulse > 1e-6,
                "attached_object_active": attached,
            }
        )
    return records


def _snapshot(task: Any, request: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    actors: dict[str, Any] = {}
    for actor in task.scene.get_all_actors():
        pose = actor.get_pose()
        actors[str(actor.get_name())] = {"position_m": pose.p.tolist(), "orientation_wxyz": pose.q.tolist()}
    robot = task.robot
    state = {
        "actors": actors,
        "left_qpos": robot.left_entity.get_qpos().tolist(),
        "right_qpos": robot.right_entity.get_qpos().tolist(),
        "left_gripper": float(robot.get_left_gripper_val()),
        "right_gripper": float(robot.get_right_gripper_val()),
        "contacts": _contact_state(task, phase="snapshot", step=0),
    }
    encoded = json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")
    target = _actor_for_entity(task, candidate["entity_ref"])
    target_pose = target.get_pose()
    return {
        **{key: request[key] for key in _STATE_FIELDS},
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "state_digest": _sha_bytes(encoded),
        "target_entity_ref": candidate["entity_ref"],
        "target_actor": str(target.get_name()),
        "target_pose": {
            "position_m": target_pose.p.tolist(),
            "orientation_wxyz": target_pose.q.tolist(),
        },
        "robot_grippers": {
            "left": float(robot.get_left_gripper_val()),
            "right": float(robot.get_right_gripper_val()),
        },
    }


def _actor_for_entity(task: Any, entity_ref: str) -> Any:
    mapping = {
        "entity://block-red-1": "block1",
        "entity://block-green-1": "block2",
        "entity://block-blue-1": "block3",
    }
    name = mapping.get(entity_ref)
    if name is None or not hasattr(task, name):
        raise SimulationProbeError("probe entity is not supported by task profile")
    return getattr(task, name)


def _label_probe_actors(task: Any) -> None:
    """Give task entities stable identities before collecting contact evidence.

    RoboTwin's block task names every block ``box``.  Contact traces using that
    name cannot prove that the requested entity, rather than another block,
    touched the gripper or support surface.  Renaming the probe-local actors is
    metadata-only and does not alter geometry or dynamics.
    """
    for entity_ref, attribute in (
        ("entity://block-red-1", "block1"),
        ("entity://block-green-1", "block2"),
        ("entity://block-blue-1", "block3"),
    ):
        actor = getattr(task, attribute, None)
        set_name = getattr(actor, "set_name", None)
        if actor is None or not callable(set_name):
            raise SimulationProbeError("probe actor identity cannot be made unique")
        set_name(entity_ref.removeprefix("entity://"))


def _joint_limits(planner: Any) -> list[list[float]]:
    try:
        kinematics = planner.motion_gen.robot_cfg.kinematics
        limits = getattr(kinematics, "joint_limits", None)
        if limits is None:
            limits = kinematics.kinematics_config.joint_limits
        tensor = limits.position
        values = tensor.detach().cpu().tolist()
    except Exception as exc:
        raise SimulationProbeError("planner joint limits are unavailable") from exc
    if not isinstance(values, list) or len(values) != 2 or any(len(row) != 7 for row in values):
        raise SimulationProbeError("planner joint limits have unexpected shape")
    converted = [[float(item) for item in row] for row in values]
    if any(not math.isfinite(item) for row in converted for item in row) or any(
        low >= high for low, high in zip(converted[0], converted[1])
    ):
        raise SimulationProbeError("planner joint limits are invalid")
    return converted


def _validate_trajectory(
    result: Mapping[str, Any],
    limits: list[list[float]],
    *,
    max_joint_speed_radps: float,
) -> None:
    import numpy as np

    if result.get("status") != "Success":
        raise SimulationProbeError("planner route segment failed")
    positions = np.asarray(result.get("position"), dtype=np.float64)
    velocities = np.asarray(result.get("velocity"), dtype=np.float64)
    if positions.ndim != 2 or positions.shape[1] != 7 or velocities.shape != positions.shape:
        raise SimulationProbeError("planner trajectory shape is invalid")
    if not np.isfinite(positions).all() or not np.isfinite(velocities).all():
        raise SimulationProbeError("planner trajectory contains non-finite values")
    low, high = np.asarray(limits[0]), np.asarray(limits[1])
    if bool((positions < low - 1e-5).any()) or bool((positions > high + 1e-5).any()):
        raise SimulationProbeError("planner trajectory exceeds joint limits")
    if bool((np.abs(velocities) > float(max_joint_speed_radps) + 1e-5).any()):
        raise SimulationProbeError("planner trajectory exceeds waypoint joint-speed limit")


def _validate_request_policies(
    root: Path,
    request: Mapping[str, Any],
    *,
    max_duration_s: float,
) -> dict[str, Any]:
    joint = _load_json_artifact(root, request["joint_limits_ref"])
    stop = _load_json_artifact(root, request["stop_policy_ref"])
    if set(joint) != {
        "schema_version", "planner_profile", "joint_count",
        "require_runtime_position_limits", "max_joint_speed_radps",
    } or joint["schema_version"] != "paos-robotwin20-joint-limit-policy/v1":
        raise SimulationProbeError("joint-limit policy fields are invalid")
    max_joint_speed = joint["max_joint_speed_radps"]
    if (
        joint["planner_profile"] != "curobo"
        or joint["joint_count"] != 7
        or joint["require_runtime_position_limits"] is not True
        or isinstance(max_joint_speed, bool)
        or not isinstance(max_joint_speed, (int, float))
        or not math.isfinite(float(max_joint_speed))
        or max_joint_speed <= 0
    ):
        raise SimulationProbeError("joint-limit policy is invalid")
    if set(stop) != {
        "schema_version", "max_duration_s", "stop_file_required",
        "poll_each_step", "failure_recovery",
    } or stop["schema_version"] != "paos-robotwin20-stop-policy/v1":
        raise SimulationProbeError("stop policy fields are invalid")
    if (
        isinstance(stop["max_duration_s"], bool)
        or not isinstance(stop["max_duration_s"], (int, float))
        or not math.isclose(float(stop["max_duration_s"]), max_duration_s, abs_tol=1e-9)
        or stop["stop_file_required"] is not True
        or stop["poll_each_step"] is not True
        or stop["failure_recovery"] != "reset_simulation"
    ):
        raise SimulationProbeError("stop policy is invalid")
    for candidate in request["candidates"]:
        speed_limited_poses = [candidate["execution_grasp"]["contact_tcp_pose"]]
        speed_limited_poses.extend(
            waypoint
            for phase in candidate["route"]
            for waypoint in phase["waypoints"]
        )
        if any(
            float(pose["max_joint_speed_radps"]) > float(max_joint_speed)
            for pose in speed_limited_poses
        ):
            raise SimulationProbeError("candidate pose exceeds joint-limit policy")
    return {
        "joint_limit_policy": {
            "artifact_ref": request["joint_limits_ref"],
            "sha256": _sha_bytes(_artifact_path(root, request["joint_limits_ref"]).read_bytes()),
        },
        "stop_policy": {
            "artifact_ref": request["stop_policy_ref"],
            "sha256": _sha_bytes(_artifact_path(root, request["stop_policy_ref"]).read_bytes()),
        },
        "max_joint_speed_radps": float(max_joint_speed),
    }


def _validate_world_pose(
    pose: list[float], bounds: Mapping[str, Any], half_extents: list[float]
) -> None:
    conservative_extent = max(half_extents)
    for axis, coordinate in zip("xyz", pose[:3]):
        if (
            coordinate - conservative_extent < float(bounds[f"{axis}_min_m"])
            or coordinate + conservative_extent > float(bounds[f"{axis}_max_m"])
        ):
            raise SimulationProbeError("world-frame route waypoint or attached object exceeds workspace bounds")


def _robot_link_names(task: Any) -> set[str]:
    names: set[str] = set()
    try:
        for entity in (task.robot.left_entity, task.robot.right_entity):
            names.update(str(link.get_name()) for link in entity.get_links())
    except Exception as exc:
        raise SimulationProbeError("robot link identities are unavailable") from exc
    if not names:
        raise SimulationProbeError("robot link identities are empty")
    return names


def _evaluate_contacts(task: Any, actor: Any, trace: list[dict[str, Any]]) -> dict[str, Any]:
    target = str(actor.get_name())
    grippers = {str(name) for name in task.robot.gripper_name}
    robot_links = _robot_link_names(task)
    unexpected: list[dict[str, Any]] = []
    target_gripper_phases: set[str] = set()
    target_support_phases: set[str] = set()
    for record in trace:
        pair = set(record["pair"])
        robot_members = pair & robot_links
        if record["active_contact"] and target in pair and pair & grippers:
            target_gripper_phases.add(record["phase"])
        if record["active_contact"] and target in pair and "table" in pair:
            target_support_phases.add(record["phase"])
        other = pair - robot_links
        if (
            record["active_contact"]
            and record["attached_object_active"]
            and robot_members
            and other
            and target not in other
        ):
            unexpected.append(record)
    grasp_contact = bool(target_gripper_phases & {"contact", "close", "lift"})
    placed_support = bool(target_support_phases & {"release", "retreat"})
    status = "pass" if grasp_contact and placed_support and not unexpected else "fail"
    return {
        "schema_version": "paos-robotwin20-contact-dynamics/v1",
        "status": status,
        "target_actor": target,
        "sample_count": len(trace),
        "target_gripper_contact_phases": sorted(target_gripper_phases),
        "target_support_contact_phases": sorted(target_support_phases),
        "required_events": {
            "grasp_contact_observed": grasp_contact,
            "placed_support_contact_observed": placed_support,
        },
        "unexpected_robot_environment_contacts": unexpected,
        "trace": trace,
    }


def _attach_object_to_planner(
    task: Any, planner: Any, actor: Any, half_extents: list[float], arm: str
) -> dict[str, Any]:
    """Attach the observed object geometry to Curobo's dedicated attached link."""
    try:
        import numpy as np
        import torch
        from curobo.geom.types import Cuboid
        from curobo.types.robot import JointState

        base_pose = np.asarray(list(planner.robot_origion_pose.p) + list(planner.robot_origion_pose.q), dtype=np.float64)
        object_pose = np.asarray(list(actor.get_pose().p) + list(actor.get_pose().q), dtype=np.float64)
        base_position, base_quaternion = planner._trans_from_world_to_base(base_pose, object_pose)
        obstacle = Cuboid(
            name="probe_attached_object",
            pose=list(base_position) + list(base_quaternion),
            dims=[2.0 * float(item) for item in half_extents],
        )
        entity = task.robot.left_entity if arm == "left" else task.robot.right_entity
        qpos = entity.get_qpos()
        joint_state = JointState.from_position(
            torch.tensor(qpos[:7], dtype=torch.float32, device="cuda").reshape(1, -1),
            joint_names=planner.active_joints_name,
        )
        surface_sphere_radius_m = 0.001
        link_name = "attached_object"
        if not planner.motion_gen.attach_external_objects_to_robot(
            joint_state,
            [obstacle],
            surface_sphere_radius=surface_sphere_radius_m,
            link_name=link_name,
        ):
            raise SimulationProbeError("planner rejected attached object geometry")
        return {
            "status": "attached",
            "planner_link_name": link_name,
            "object_name": obstacle.name,
            "object_dimensions_m": [2.0 * float(item) for item in half_extents],
            "surface_sphere_radius_m": surface_sphere_radius_m,
            "active_route_phases": ["lift", "transport", "descent", "release"],
        }
    except SimulationProbeError:
        raise
    except Exception as exc:
        raise SimulationProbeError("attached object geometry could not be added to planner") from exc


def _execute_segment(
    task: Any,
    arm: str,
    result: Mapping[str, Any],
    *,
    phase: str,
    deadline: float,
    stop_file: Path | None,
    contacts: list[dict[str, Any]],
    execution_state: dict[str, Any],
    max_linear_speed_mps: float,
) -> None:
    import numpy as np

    positions = result["position"]
    velocities = result["velocity"]
    ee = task.robot.get_left_ee_pose if arm == "left" else task.robot.get_right_ee_pose
    timestep = float(task.scene.get_timestep())
    if not math.isfinite(timestep) or timestep <= 0:
        raise SimulationProbeError("simulator timestep is invalid")
    previous_position = np.asarray(ee()[:3], dtype=np.float64)
    for index in range(len(positions)):
        if time.monotonic() >= deadline:
            raise TimeoutError("simulation probe exceeded max duration")
        if stop_file is not None and stop_file.exists():
            raise InterruptedError("simulation probe stop requested")
        task.robot.set_arm_joints(positions[index], velocities[index], arm)
        execution_state["world_change_started"] = True
        execution_state["phase"] = phase
        task.scene.step()
        current_position = np.asarray(ee()[:3], dtype=np.float64)
        linear_speed = float(np.linalg.norm(current_position - previous_position) / timestep)
        if not math.isfinite(linear_speed) or linear_speed > max_linear_speed_mps + 1e-3:
            raise SimulationProbeError("simulator motion exceeds waypoint linear-speed limit")
        execution_state["max_observed_linear_speed_mps"] = max(
            execution_state.get("max_observed_linear_speed_mps", 0.0), linear_speed
        )
        previous_position = current_position
        execution_state["simulator_steps"] += 1
        contacts.extend(
            _contact_state(
                task,
                phase=phase,
                step=execution_state["simulator_steps"],
                attached=bool(execution_state["planner_object_attached"]),
            )
        )


def _set_gripper(
    task: Any,
    arm: str,
    value: float,
    *,
    phase: str,
    deadline: float,
    stop_file: Path | None,
    contacts: list[dict[str, Any]],
    execution_state: dict[str, Any],
) -> None:
    for _ in range(20):
        if time.monotonic() >= deadline:
            raise TimeoutError("simulation probe exceeded max duration")
        if stop_file is not None and stop_file.exists():
            raise InterruptedError("simulation probe stop requested")
        task.robot.set_gripper(value, arm)
        execution_state["world_change_started"] = True
        execution_state["phase"] = phase
        task.scene.step()
        execution_state["simulator_steps"] += 1
        contacts.extend(
            _contact_state(
                task,
                phase=phase,
                step=execution_state["simulator_steps"],
                attached=bool(execution_state["planner_object_attached"]),
            )
        )


def _run_candidate(
    task: Any,
    request: Mapping[str, Any],
    candidate: Mapping[str, Any],
    policies: Mapping[str, Any],
    *,
    deadline: float,
    stop_file: Path | None,
    execution_state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], str]:
    import numpy as np

    actor = _actor_for_entity(task, candidate["entity_ref"])
    before_actor = np.asarray(actor.get_pose().p, dtype=np.float64).copy()
    route_records: list[dict[str, Any]] = []
    contact_trace: list[dict[str, Any]] = []
    execution_state["contact_trace"] = contact_trace
    arm_results: dict[str, tuple[list[list[float]], Any]] = {}
    arm_attempts: list[dict[str, Any]] = []
    execution_state["arm_selection_attempts"] = arm_attempts
    for arm in ("left", "right"):
        planner = task.robot.left_planner if arm == "left" else task.robot.right_planner
        limits = _joint_limits(planner)
        try:
            pose = _route_pose(
                candidate["execution_grasp"]["contact_tcp_pose"], request["frame_id"]
            )
            fn = task.robot.left_plan_path if arm == "left" else task.robot.right_plan_path
            result = fn(pose)
            _validate_trajectory(
                result,
                limits,
                max_joint_speed_radps=float(
                    candidate["execution_grasp"]["contact_tcp_pose"][
                        "max_joint_speed_radps"
                    ]
                ),
            )
            arm_results[arm] = (limits, result)
            arm_attempts.append({"arm": arm, "status": "pass"})
        except Exception as exc:
            arm_attempts.append(
                {"arm": arm, "status": "fail", "error": type(exc).__name__, "detail": str(exc)}
            )
            continue
    if not arm_results:
        raise SimulationProbeError("no arm can plan candidate route")
    arm = next(iter(arm_results))
    planner = task.robot.left_planner if arm == "left" else task.robot.right_planner
    execution_state["_planner"] = planner
    limits = _joint_limits(planner)
    fn = task.robot.left_plan_path if arm == "left" else task.robot.right_plan_path
    task.need_plan = True
    half_extents = [float(item) for item in candidate["attached_object"]["half_extents_m"]]
    attached_model: dict[str, Any] | None = None
    detached = False
    for phase in candidate["route"]:
        phase_name = phase["phase"]
        execution_state["phase"] = phase_name
        world_waypoints = []
        for waypoint in phase["waypoints"]:
            world_pose = _route_pose(waypoint, request["frame_id"])
            _validate_world_pose(world_pose, request["workspace_bounds_m"], half_extents)
            world_waypoints.append(world_pose)
        planned_segments = []
        for route_waypoint, waypoint in zip(phase["waypoints"], world_waypoints):
            result = fn(waypoint)
            _validate_trajectory(
                result,
                limits,
                max_joint_speed_radps=float(route_waypoint["max_joint_speed_radps"]),
            )
            planned_segments.append(
                {
                    "route_waypoint": route_waypoint,
                    "world_pose_pq_wxyz": waypoint,
                    "position": np.asarray(result["position"], dtype=np.float64).tolist(),
                    "velocity": np.asarray(result["velocity"], dtype=np.float64).tolist(),
                }
            )
            _execute_segment(
                task,
                arm,
                result,
                phase=phase_name,
                deadline=deadline,
                stop_file=stop_file,
                contacts=contact_trace,
                execution_state=execution_state,
                max_linear_speed_mps=float(route_waypoint["max_linear_speed_mps"]),
            )
        _set_gripper(
            task,
            arm,
            _GRIPPER_VALUES[phase["gripper_state"]],
            phase=phase_name,
            deadline=deadline,
            stop_file=stop_file,
            contacts=contact_trace,
            execution_state=execution_state,
        )
        if phase_name == "lift":
            lift_z = float(actor.get_pose().p[2])
            if not math.isfinite(lift_z) or lift_z - float(before_actor[2]) < 0.01:
                raise SimulationProbeError("attached object did not lift with the gripper")
            execution_state["object_lifted"] = True
        elif phase_name in {"transport", "descent"} and not execution_state.get("object_lifted"):
            raise SimulationProbeError("attached route advanced without verified object lift")
        if phase_name == "close":
            attached_model = _attach_object_to_planner(
                task,
                planner,
                actor,
                half_extents,
                arm,
            )
            execution_state["planner_object_attached"] = True
        elif phase_name == "release":
            try:
                planner.motion_gen.detach_object_from_robot()
                detached = True
                execution_state["planner_object_attached"] = False
            except Exception as exc:
                raise SimulationProbeError("planner could not detach object after release") from exc
        route_records.append(
            {
                "phase": phase_name,
                "arm": arm,
                "waypoint_count": len(world_waypoints),
                "trajectory_steps": sum(len(item["position"]) for item in planned_segments),
                "segments": planned_segments,
            }
        )
    after_actor = np.asarray(actor.get_pose().p, dtype=np.float64).copy()
    if not np.isfinite(after_actor).all() or float(np.linalg.norm(after_actor - before_actor)) < 1e-4:
        raise SimulationProbeError("simulation route did not change target actor state")
    gripper_open = task.robot.get_left_gripper_val() if arm == "left" else task.robot.get_right_gripper_val()
    if float(gripper_open) < 0.8:
        raise SimulationProbeError("simulation route did not release target actor")
    trajectory = {
        "schema_version": "paos-robotwin20-simulation-trajectory/v1",
        "request_id": request["request_id"],
        "candidate_ref": candidate["candidate_ref"],
        "scene_revision": request["scene_revision"],
        "arm": arm,
        "arm_selection_attempts": arm_attempts,
        "phases": route_records,
        "contact_samples": len(contact_trace),
    }
    joint_limits = {
        "schema_version": "paos-robotwin20-joint-limits/v1",
        "planner_profile": "curobo",
        "arm": arm,
        "joint_limits": limits,
        "source_policy": policies["joint_limit_policy"],
        "max_joint_speed_radps": policies["max_joint_speed_radps"],
        "max_observed_linear_speed_mps": execution_state.get(
            "max_observed_linear_speed_mps", 0.0
        ),
    }
    contact_dynamics = _evaluate_contacts(task, actor, contact_trace)
    collision = {
        "schema_version": "paos-robotwin20-attached-collision/v1",
        "collision_scope": "curobo_attached_object_and_sapien_robot_environment_contacts",
        "target_actor": str(actor.get_name()),
        "sample_count": len(contact_trace),
        "planner_attached_model": attached_model,
        "planner_detached_after_release": detached,
        "unexpected_robot_environment_contacts": contact_dynamics[
            "unexpected_robot_environment_contacts"
        ],
        "status": (
            "pass"
            if attached_model is not None
            and detached
            and not contact_dynamics["unexpected_robot_environment_contacts"]
            else "fail"
        ),
    }
    if collision["status"] != "pass":
        raise SimulationProbeError("unexpected simulator contact during attached route")
    if contact_dynamics["status"] != "pass":
        raise SimulationProbeError("required grasp/place contact dynamics were not observed")
    return trajectory, joint_limits, collision, contact_dynamics, arm


def _recover_candidate_failure(
    *,
    backend: Any,
    task: Any,
    runtime_seed: int,
    artifact_root: Path,
    prefix: str,
    profile: Mapping[str, Any],
    producer_binding: Mapping[str, str],
    request: Mapping[str, Any],
    candidate: Mapping[str, Any],
    before_ref: Mapping[str, str] | None,
    execution_state: dict[str, Any],
    error: Exception,
) -> dict[str, Any]:
    """Detach, snapshot, and reset after any post-step probe failure."""
    planner = execution_state.pop("_planner", None)
    detach_status = "not_attached"
    if execution_state["planner_object_attached"] and planner is not None:
        try:
            planner.motion_gen.detach_object_from_robot()
            detach_status = "detached_after_failure"
            execution_state["planner_object_attached"] = False
        except Exception:
            detach_status = "detach_failed"

    reconciliation_required = bool(execution_state["world_change_started"])
    after_failure_ref = None
    snapshot_error = None
    reset_status = "not_required"
    if execution_state["world_change_started"]:
        try:
            after_failure = _snapshot(task, request, candidate)
            after_failure_ref = _json_artifact(
                artifact_root, prefix + "/after-failure-snapshot", after_failure
            )
        except Exception as snapshot_exc:
            snapshot_error = {
                "error": type(snapshot_exc).__name__,
                "detail": str(snapshot_exc),
            }
        reset_status = "failed"
        try:
            backend.reset(seed=runtime_seed)
            reset_status = "completed"
            reconciliation_required = False
        except Exception:
            reset_status = "failed"
    failure_ref = _json_artifact(
        artifact_root,
        prefix + "/failure",
        {
            "schema_version": "paos-robotwin20-simulation-probe-failure/v1",
            "request_id": request["request_id"],
            "candidate_ref": candidate["candidate_ref"],
            "scene_revision": request["scene_revision"],
            "error": type(error).__name__,
            "error_detail": str(error),
            "failed_phase": execution_state["phase"],
            "simulator_steps": execution_state["simulator_steps"],
            "arm_selection_attempts": execution_state.get("arm_selection_attempts", []),
            "contact_trace": execution_state.get("contact_trace", []),
            "planner_detach_status": detach_status,
            "simulation_reset_status": reset_status,
            "before_snapshot": dict(before_ref) if before_ref is not None else None,
            "after_failure_snapshot": after_failure_ref,
            "after_failure_snapshot_error": snapshot_error,
        },
    )
    return {
        "request_id": request["request_id"],
        "schema_version": SCHEMA_VERSION,
        "status": "unavailable",
        "provider_available": True,
        "worker_id": profile["worker_id"],
        "producer_binding": dict(producer_binding),
        "motion_authorized": True,
        "world_change_started": execution_state["world_change_started"],
        "world_change_completed": False,
        "reconciliation_required": reconciliation_required,
        "failure_evidence": failure_ref,
        "error": type(error).__name__,
        "error_detail": str(error),
    }


def _finalize_candidate_success(
    *,
    task: Any,
    artifact_root: Path,
    approval_ref: str,
    worker_id: str,
    prefix: str,
    producer_binding: Mapping[str, str],
    request: Mapping[str, Any],
    candidate: Mapping[str, Any],
    before: Mapping[str, Any],
    before_ref: Mapping[str, str],
    trajectory: Mapping[str, Any],
    limits: Mapping[str, Any],
    collision: Mapping[str, Any],
    contact_dynamics: Mapping[str, Any],
    selected_arm: str,
    policies: Mapping[str, Any],
    execution_state: dict[str, Any],
) -> dict[str, Any]:
    """Persist a complete success bundle; callers recover if any write fails."""
    import numpy as np

    execution_state["phase"] = "finalizing"
    execution_state.pop("_planner", None)
    after = _snapshot(task, request, candidate)
    if before["state_digest"] == after["state_digest"]:
        raise SimulationProbeError("simulation probe before/after state did not change")
    trajectory_ref = _json_artifact(artifact_root, prefix + "/trajectory", trajectory)
    limits_ref = _json_artifact(artifact_root, prefix + "/joint-limits", limits)
    collision_ref = _json_artifact(artifact_root, prefix + "/attached-collision", collision)
    contact_ref = _json_artifact(
        artifact_root, prefix + "/contact-dynamics", contact_dynamics
    )
    stop_ref = _json_artifact(
        artifact_root,
        prefix + "/stop-control",
        {
            "schema_version": "paos-robotwin20-stop-control/v1",
            "status": "pass",
            "deadline_enforced": True,
            "stop_file_configured": True,
            "stop_file_polled_each_step": True,
            "stop_requested": False,
            "simulator_steps": execution_state["simulator_steps"],
            "scope": "worker_local_simulation_route",
            "source_policy": policies["stop_policy"],
        },
    )
    after_ref = _json_artifact(artifact_root, prefix + "/after-snapshot", after)
    displacement = float(
        np.linalg.norm(
            np.asarray(after["target_pose"]["position_m"], dtype=np.float64)
            - np.asarray(before["target_pose"]["position_m"], dtype=np.float64)
        )
    )
    selected_gripper = float(after["robot_grippers"][selected_arm])
    observed_outcome = {
        "schema_version": "paos-robotwin20-observed-route-outcome/v1",
        "after_snapshot_ref": after_ref["artifact_ref"],
        "target_displacement_m": displacement,
        "target_pose_changed": displacement >= 1e-4,
        "selected_arm": selected_arm,
        "selected_gripper_value": selected_gripper,
        "selected_gripper_open": selected_gripper >= 0.8,
    }
    outcome_ref = _json_artifact(
        artifact_root, prefix + "/observed-outcome", observed_outcome
    )
    evidence = {
        "schema_version": "paos-robotwin20-simulation-route-evidence/v2",
        "request_id": request["request_id"],
        "candidate_ref": candidate["candidate_ref"],
        "entity_ref": candidate["entity_ref"],
        "observation_ref": request["observation_ref"],
        "scene_revision": request["scene_revision"],
        "frame_id": request["frame_id"],
        "calibration_ref": request["calibration_ref"],
        "candidate_set_ref": request["candidate_set_ref"],
        "route_geometry_digest": route_geometry_digest(request),
        "planner": {
            "status": "pass",
            "planner_id": "robotwin20-curobo/v1",
            "trajectory": trajectory_ref,
            "joint_limits": limits_ref,
            "route_phase_order": list(ROUTE_PHASES),
        },
        "scopes": {
            "attached_object_collision": {
                "status": "pass",
                "evidence": collision_ref,
                "method": "curobo-attached-object-plus-sapien-contact/v1",
            },
            "complete_transport_descent_retreat": {
                "status": "pass",
                "evidence": trajectory_ref,
                "method": "curobo-segmented-route/v1",
            },
            "contact_dynamics": {
                "status": "pass",
                "evidence": contact_ref,
                "method": "sapien-phase-contact-impulse-trace/v1",
            },
            "workspace_and_joint_limits": {
                "status": "pass",
                "evidence": limits_ref,
                "method": "world-waypoint-plus-curobo-position-joint-speed-and-sapien-linear-speed/v1",
            },
            "stop_control": {
                "status": "pass",
                "evidence": stop_ref,
                "method": "worker-local-deadline-stop-file/v1",
            },
        },
        "before_snapshot": dict(before_ref),
        "after_snapshot": after_ref,
        "observed_outcome": observed_outcome,
        "observed_outcome_artifact": outcome_ref,
        "producer_binding": dict(producer_binding),
        "probe_execution": {
            "simulation_only": True,
            "motion_authorized": True,
            "world_change_started": True,
            "world_change_completed": True,
            "authorization": {
                "artifact_ref": approval_ref,
                "sha256": _sha_bytes(_artifact_path(artifact_root, approval_ref).read_bytes()),
            },
        },
    }
    return {
        "request_id": request["request_id"],
        "schema_version": SCHEMA_VERSION,
        "status": "available",
        "provider_available": True,
        "worker_id": worker_id,
        "producer_binding": evidence["producer_binding"],
        "motion_authorized": True,
        "world_change_started": True,
        "world_change_completed": True,
        "reconciliation_required": False,
        "external_evidence": evidence,
    }


def _handle_factory(profile: Mapping[str, Any], artifact_root: Path, *, producer_id: str, producer_profile_sha256: str, approval_ref: str, max_duration_s: float, stop_file: Path | None):
    from robotwin_backend import RoboTwinRuntimeProfile, RoboTwinSensorBackend, load_runtime_profile

    runtime_profile = load_runtime_profile(Path(profile["runtime_profile"]).resolve())
    backend = RoboTwinSensorBackend(
        RoboTwinRuntimeProfile(
            runtime_root=Path(profile["runtime_root"]),
            artifact_root=artifact_root,
            task_name=runtime_profile["task_name"],
            task_config=runtime_profile["task_config"],
            embodiment=runtime_profile["embodiment"],
        )
    )
    request_consumed = False

    def handle(message: Mapping[str, Any]) -> Mapping[str, Any]:
        nonlocal request_consumed
        if set(message) != {"request_id", "route_request", "candidate_ref", "calibration_ref"}:
            raise SimulationProbeError("simulation probe request fields are invalid")
        request = message["route_request"]
        validate_route_request(request)
        if message["request_id"] != request["request_id"] or message["calibration_ref"] != request["calibration_ref"]:
            raise SimulationProbeError("simulation probe request identity is invalid")
        if request["scene_revision"] != f"{runtime_profile['task_name']}-{runtime_profile['seed']}-1":
            raise SimulationProbeError("simulation probe scene revision is invalid")
        candidate = next((item for item in request["candidates"] if item["candidate_ref"] == message["candidate_ref"]), None)
        if candidate is None:
            raise SimulationProbeError("simulation probe candidate is not in request")
        producer_binding = {
            "producer_id": producer_id,
            "profile_sha256": producer_profile_sha256,
            "evidence_mode": "independent_simulation_probe",
        }
        if request_consumed:
            return {
                "request_id": request["request_id"],
                "schema_version": SCHEMA_VERSION,
                "status": "unavailable",
                "provider_available": True,
                "worker_id": profile["worker_id"],
                "producer_binding": producer_binding,
                "motion_authorized": False,
                "world_change_started": False,
                "world_change_completed": False,
                "reconciliation_required": False,
                "failure_evidence": None,
                "error": "SimulationProbeError",
                "error_detail": "simulation probe worker is single-use",
            }
        try:
            _validate_approval(
                artifact_root,
                approval_ref,
                producer_id=producer_id,
                producer_profile_sha256=producer_profile_sha256,
                request=request,
                candidate_ref=candidate["candidate_ref"],
                profile=profile,
            )
            geometry_ref = candidate["attached_object"]["geometry_ref"]
            geometry_path = _artifact_path(artifact_root, geometry_ref)
            if _sha_bytes(geometry_path.read_bytes()) != candidate["attached_object"]["geometry_sha256"]:
                raise SimulationProbeError("attached geometry artifact digest mismatch")
            policies = _validate_request_policies(
                artifact_root,
                request,
                max_duration_s=max_duration_s,
            )
        except Exception as exc:
            return {
                "request_id": request["request_id"],
                "schema_version": SCHEMA_VERSION,
                "status": "unavailable",
                "provider_available": True,
                "worker_id": profile["worker_id"],
                "producer_binding": producer_binding,
                "motion_authorized": False,
                "world_change_started": False,
                "world_change_completed": False,
                "reconciliation_required": False,
                "failure_evidence": None,
                "error": type(exc).__name__,
                "error_detail": str(exc),
            }
        if stop_file is None:
            raise SimulationProbeError("simulation probe stop control is not configured")
        if stop_file.exists():
            return {
                "request_id": request["request_id"],
                "schema_version": SCHEMA_VERSION,
                "status": "unavailable",
                "provider_available": True,
                "worker_id": profile["worker_id"],
                "producer_binding": producer_binding,
                "motion_authorized": True,
                "world_change_started": False,
                "world_change_completed": False,
                "reconciliation_required": False,
                "error": "InterruptedError",
                "error_detail": "simulation probe stop requested before world change",
            }
        request_consumed = True
        execution_state: dict[str, Any] = {
            "world_change_started": False,
            "simulator_steps": 0,
            "phase": "scene_initialization",
            "planner_object_attached": False,
            "object_lifted": False,
        }
        prefix = (
            f"artifact://simulation-probe/{request['request_id']}/"
            f"{_candidate_token(candidate['candidate_ref'])}"
        )
        task = None
        before_ref = None
        try:
            # Scene initialization/reset itself mutates the isolated simulator,
            # even before a robot-control step.  Mark it before invoking the
            # backend so partial reset failures cannot masquerade as no-change.
            execution_state["world_change_started"] = True
            backend.reset(seed=runtime_profile["seed"])
            task = backend._task
            if task is None or not hasattr(task, "robot"):
                raise SimulationProbeError("RoboTwin simulation task is unavailable")
            if backend.snapshot().get("scene_revision") != request["scene_revision"]:
                raise SimulationProbeError("simulation backend revision binding is invalid")
            _label_probe_actors(task)
            start = time.monotonic()
            before = _snapshot(task, request, candidate)
            deadline = start + max_duration_s
            # Persist the immutable pre-route state before any simulator step so a
            # failure can always be reconciled against the exact starting scene.
            before_ref = _json_artifact(artifact_root, prefix + "/before-snapshot", before)
            execution_state["phase"] = "preflight"
        except Exception as exc:
            return _recover_candidate_failure(
                backend=backend,
                task=task,
                runtime_seed=runtime_profile["seed"],
                artifact_root=artifact_root,
                prefix=prefix,
                profile=profile,
                producer_binding=producer_binding,
                request=request,
                candidate=candidate,
                before_ref=before_ref,
                execution_state=execution_state,
                error=exc,
            )
        try:
            trajectory, limits, collision, contact_dynamics, selected_arm = _run_candidate(
                task,
                request,
                candidate,
                policies,
                deadline=deadline,
                stop_file=stop_file,
                execution_state=execution_state,
            )
        except Exception as exc:
            return _recover_candidate_failure(
                backend=backend,
                task=task,
                runtime_seed=runtime_profile["seed"],
                artifact_root=artifact_root,
                prefix=prefix,
                profile=profile,
                producer_binding=producer_binding,
                request=request,
                candidate=candidate,
                before_ref=before_ref,
                execution_state=execution_state,
                error=exc,
            )
        try:
            return _finalize_candidate_success(
                task=task,
                artifact_root=artifact_root,
                approval_ref=approval_ref,
                worker_id=profile["worker_id"],
                prefix=prefix,
                producer_binding=producer_binding,
                request=request,
                candidate=candidate,
                before=before,
                before_ref=before_ref,
                trajectory=trajectory,
                limits=limits,
                collision=collision,
                contact_dynamics=contact_dynamics,
                selected_arm=selected_arm,
                policies=policies,
                execution_state=execution_state,
            )
        except Exception as exc:
            return _recover_candidate_failure(
                backend=backend,
                task=task,
                runtime_seed=runtime_profile["seed"],
                artifact_root=artifact_root,
                prefix=prefix,
                profile=profile,
                producer_binding=producer_binding,
                request=request,
                candidate=candidate,
                before_ref=before_ref,
                execution_state=execution_state,
                error=exc,
            )

    return backend, handle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--runtime-profile", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--producer-id", required=True)
    parser.add_argument("--producer-profile-sha256", required=True)
    parser.add_argument("--approval-ref", required=True)
    parser.add_argument("--max-duration-s", type=float, default=300.0)
    parser.add_argument("--stop-file", type=Path)
    args = parser.parse_args()
    if not args.runtime_root.is_absolute() or not args.runtime_root.is_dir() or args.runtime_root.is_symlink():
        raise SystemExit("runtime root must be an absolute directory")
    if not args.artifact_root.is_absolute() or not args.artifact_root.is_dir() or args.artifact_root.is_symlink():
        raise SystemExit("artifact root must be an absolute directory")
    if len(args.producer_profile_sha256) != 64 or any(c not in "0123456789abcdef" for c in args.producer_profile_sha256):
        raise SystemExit("producer profile digest must be lowercase SHA-256")
    from robotwin_backend import load_runtime_profile

    runtime_profile = load_runtime_profile(args.runtime_profile.resolve())
    profile = {
        "worker_id": args.worker_id,
        "runtime_root": str(args.runtime_root.resolve()),
        "runtime_profile": str(args.runtime_profile.resolve()),
        "task_name": runtime_profile["task_name"],
        "scene_revision": f"{runtime_profile['task_name']}-{runtime_profile['seed']}-1",
        "embodiment_binding": {key: runtime_profile[key] for key in ("robot_identity", "gripper_identity", "embodiment_topology", "planner_profile")},
    }
    resolved_stop = args.stop_file.resolve() if args.stop_file else None
    if (
        resolved_stop is None
        or args.stop_file.is_symlink()
        or args.artifact_root.resolve() not in resolved_stop.parents
        or not resolved_stop.parent.is_dir()
    ):
        raise SystemExit("stop file must be a non-symlink path below artifact root")
    state: dict[str, Any] = {}

    def load() -> None:
        # Keep third-party runtime output off the JSONL protocol stream while
        # making the expensive import/backend construction observable as load.
        with redirect_stdout(sys.stderr):
            backend, handler = _handle_factory(
                profile,
                args.artifact_root.resolve(),
                producer_id=args.producer_id,
                producer_profile_sha256=args.producer_profile_sha256,
                approval_ref=args.approval_ref,
                max_duration_s=args.max_duration_s,
                stop_file=resolved_stop,
            )
        state["backend"] = backend
        state["handle"] = handler

    def handle(message: Mapping[str, Any]) -> Mapping[str, Any]:
        handler = state.get("handle")
        if not callable(handler):
            raise SimulationProbeError("simulation probe worker is not loaded")
        with redirect_stdout(sys.stderr):
            return handler(message)

    try:
        return serve("robotwin20-simulation-probe", load, handle, schema_version=SCHEMA_VERSION)
    finally:
        backend = state.get("backend")
        if backend is not None:
            backend.close()


if __name__ == "__main__":
    raise SystemExit(main())
