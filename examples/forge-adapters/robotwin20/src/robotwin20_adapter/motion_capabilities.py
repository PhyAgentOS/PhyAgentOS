"""Provider-owned motion-capability projection for RoboTwin embodiments.

The projection is derived from the selected RoboTwin checkout and runtime.  It
does not authorize motion and deliberately distinguishes planner constraints
from controller-enforced limits.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from .perception_profile import _read_unique_yaml

MOTION_CAPABILITY_SCHEMA_VERSION = "paos-robotwin20-motion-capability/v2"
MOTION_CAPABILITY_VALIDATION_SCHEMA_VERSION = (
    "paos-robotwin20-motion-capability-validation/v1"
)
LimitEnforcement = Literal[
    "controller_enforced", "planner_constrained", "measured_diagnostic", "unknown"
]


class MotionCapabilityError(ValueError):
    """RoboTwin motion-capability inputs or bindings are invalid."""


class SourceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal[
        "robot_description",
        "embodiment_profile",
        "planner_profile",
        "planner_source",
        "simulator_source",
        "controller_source",
    ]
    relative_path: str
    sha256: str

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        path = Path(value)
        if not value or path.is_absolute() or ".." in path.parts:
            raise ValueError("motion capability source path is invalid")
        return value

    @field_validator("sha256")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("motion capability source digest is invalid")
        return value


class ProviderIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    robotwin_git_revision: str
    simulator_id: Literal["sapien"] = "sapien"
    simulator_version: str
    planner_id: Literal["curobo"] = "curobo"
    planner_version: str
    controller_id: Literal["robotwin-sapien-drive-target"] = (
        "robotwin-sapien-drive-target"
    )
    controller_version: str
    runtime_python_version: str

    @field_validator(
        "robotwin_git_revision", "simulator_version", "planner_version",
        "controller_version", "runtime_python_version",
    )
    @classmethod
    def validate_identity(cls, value: str) -> str:
        if not value or not value.strip() or any(char.isspace() for char in value):
            raise ValueError("motion capability provider identity is invalid")
        return value


class JointLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    position_lower_rad: tuple[float, ...]
    position_upper_rad: tuple[float, ...]
    velocity_lower_radps: tuple[float, ...]
    velocity_upper_radps: tuple[float, ...]
    acceleration_radps2: tuple[float, ...]
    jerk_radps3: tuple[float, ...]
    effort_nm: tuple[float, ...]

    @model_validator(mode="after")
    def validate_limits(self) -> "JointLimits":
        fields = (
            self.position_lower_rad, self.position_upper_rad,
            self.velocity_lower_radps, self.velocity_upper_radps,
            self.acceleration_radps2, self.jerk_radps3, self.effort_nm,
        )
        lengths = {len(values) for values in fields}
        if len(lengths) != 1 or not next(iter(lengths)):
            raise ValueError("motion capability per-joint limit lengths are inconsistent")
        if any(not math.isfinite(value) for values in fields for value in values):
            raise ValueError("motion capability limits must be finite")
        if any(low >= high for low, high in zip(self.position_lower_rad, self.position_upper_rad)):
            raise ValueError("motion capability position limits are invalid")
        if any(low >= 0 or high <= 0 for low, high in zip(
            self.velocity_lower_radps, self.velocity_upper_radps
        )):
            raise ValueError("motion capability velocity limits are invalid")
        if any(value <= 0 for values in (
            self.acceleration_radps2, self.jerk_radps3, self.effort_nm
        ) for value in values):
            raise ValueError("motion capability derivative/effort limits must be positive")
        return self


class TimingSemantics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    planner_dt_s: float
    simulator_default_dt_s: float
    controller_dt_s: float | None

    @model_validator(mode="after")
    def validate_timing(self) -> "TimingSemantics":
        values = (self.planner_dt_s, self.simulator_default_dt_s)
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError("motion capability timing must be finite and positive")
        if self.controller_dt_s is not None and (
            not math.isfinite(self.controller_dt_s) or self.controller_dt_s <= 0
        ):
            raise ValueError("motion capability controller timing must be finite and positive")
        return self


class EnforcementSemantics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    joint_position: LimitEnforcement
    joint_velocity: LimitEnforcement
    joint_acceleration: LimitEnforcement
    joint_jerk: LimitEnforcement
    cartesian_velocity: LimitEnforcement
    joint_effort: LimitEnforcement
    drive_position_target: bool
    drive_velocity_target: bool
    drive_force_limit_bound: bool

    @model_validator(mode="after")
    def reject_unproven_controller_claims(self) -> "EnforcementSemantics":
        if "controller_enforced" in {
            self.joint_position, self.joint_velocity, self.joint_acceleration,
            self.joint_jerk, self.cartesian_velocity, self.joint_effort,
        }:
            raise ValueError("RoboTwin drive-target capability is not controller-qualified")
        if not self.drive_position_target or not self.drive_velocity_target:
            raise ValueError("RoboTwin drive-target command semantics are incomplete")
        if self.drive_force_limit_bound:
            raise ValueError("RoboTwin force-limit binding is not proven")
        return self


class MotionCapabilityDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["paos-robotwin20-motion-capability/v2"] = (
        MOTION_CAPABILITY_SCHEMA_VERSION
    )
    robot_identity: str
    arm_id: Literal["left", "right"]
    runtime_kind: Literal["simulation"] = "simulation"
    provider: ProviderIdentity
    joint_order: tuple[str, ...]
    limits: JointLimits
    enforcement: EnforcementSemantics
    timing: TimingSemantics
    sources: tuple[SourceRecord, ...]
    controller_qualification_ref: None = None
    motion_authorized: Literal[False] = False

    @field_validator("robot_identity")
    @classmethod
    def validate_robot_identity(cls, value: str) -> str:
        if (
            not value
            or value in {".", ".."}
            or any(char.isspace() for char in value)
            or "/" in value
            or "\\" in value
        ):
            raise ValueError("motion capability robot identity is invalid")
        return value

    @model_validator(mode="after")
    def validate_document(self) -> "MotionCapabilityDocument":
        if not self.joint_order:
            raise ValueError("motion capability robot/joint identity is invalid")
        if len(set(self.joint_order)) != len(self.joint_order) or any(
            not item for item in self.joint_order
        ):
            raise ValueError("motion capability joint order is invalid")
        if len(self.limits.position_lower_rad) != len(self.joint_order):
            raise ValueError("motion capability limits do not match joint order")
        roles = [source.role for source in self.sources]
        expected = {
            "robot_description", "embodiment_profile", "planner_profile",
            "planner_source", "simulator_source", "controller_source",
        }
        if set(roles) != expected or len(roles) != len(expected):
            raise ValueError("motion capability source roles are incomplete or duplicated")
        return self


class MotionCapabilityValidation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[
        "paos-robotwin20-motion-capability-validation/v1"
    ] = MOTION_CAPABILITY_VALIDATION_SCHEMA_VERSION
    capability_sha256: str
    verifier_id: str
    verified_at: str
    status: Literal["validated_planner_constraints"]
    checks: tuple[str, ...]
    independent_execution_qualification: Literal[False] = False
    controller_enforced: Literal[False] = False
    motion_authorized: Literal[False] = False

    @field_validator("capability_sha256")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("motion capability validation digest is invalid")
        return value

    @field_validator("verifier_id")
    @classmethod
    def validate_verifier_id(cls, value: str) -> str:
        if not value or any(char.isspace() for char in value):
            raise ValueError("motion capability verifier identity is invalid")
        return value

    @field_validator("verified_at")
    @classmethod
    def validate_verified_at(cls, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("motion capability validation timestamp is invalid") from exc
        if parsed.tzinfo is None:
            raise ValueError("motion capability validation timestamp requires timezone")
        return value

    @field_validator("checks")
    @classmethod
    def validate_checks(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        expected = {
            "source_digests",
            "runtime_identity",
            "joint_order",
            "per_joint_limits",
            "planner_timing",
            "simulator_timing",
            "drive_semantics",
            "no_controller_enforcement_claim",
        }
        if len(value) != len(expected) or set(value) != expected:
            raise ValueError("motion capability validation checks are incomplete")
        return value


def canonical_motion_capability(value: MotionCapabilityDocument | Mapping[str, Any]) -> bytes:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else dict(value)
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def motion_capability_digest(value: MotionCapabilityDocument | Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_motion_capability(value)).hexdigest()


def _source(root: Path, path: Path, role: str) -> dict[str, str]:
    resolved_root = root.resolve()
    resolved = path.resolve()
    if (
        path.is_symlink()
        or resolved_root not in resolved.parents
        or not resolved.is_file()
    ):
        raise MotionCapabilityError(f"{role} source is unavailable")
    return {
        "role": role,
        "relative_path": resolved.relative_to(resolved_root).as_posix(),
        "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
    }


def _number(node: ast.AST) -> float | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left, right = _number(node.left), _number(node.right)
        if left is not None and right not in {None, 0.0}:
            return left / right
    return None


def _planner_dt(path: Path) -> float:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    values: set[float] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg in {"interpolation_dt", "time_step"}:
                    value = _number(keyword.value)
                    if value is not None:
                        values.add(value)
    if len(values) != 1:
        raise MotionCapabilityError("RoboTwin planner timing is absent or ambiguous")
    return values.pop()


def _simulator_dt(path: Path) -> float:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    values: set[float] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "set_timestep" or not node.args:
            continue
        argument = node.args[0]
        if isinstance(argument, ast.Call) and isinstance(argument.func, ast.Attribute):
            if argument.func.attr == "get" and len(argument.args) >= 2:
                value = _number(argument.args[1])
                if value is not None:
                    values.add(value)
    if len(values) != 1:
        raise MotionCapabilityError("RoboTwin simulator timing is absent or ambiguous")
    return values.pop()


def _drive_semantics(path: Path) -> tuple[bool, bool, bool]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(
        (node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
         and node.name == "set_arm_joints"),
        None,
    )
    if function is None:
        raise MotionCapabilityError("RoboTwin set_arm_joints is unavailable")
    calls = {
        node.func.attr
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    force_bound = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"set_drive_property", "set_drive_properties"}
        and any(keyword.arg == "force_limit" for keyword in node.keywords)
        for node in ast.walk(tree)
    )
    return "set_drive_target" in calls, "set_drive_velocity_target" in calls, force_bound


def _runtime_identity(runtime_python: Path) -> dict[str, str]:
    if (
        not runtime_python.is_absolute()
        or not runtime_python.is_file()
        or not os.access(runtime_python, os.X_OK)
    ):
        raise MotionCapabilityError("RoboTwin runtime Python must be an absolute regular file")
    code = """
import importlib.metadata as m, json, platform
def version(*names):
    for name in names:
        try: return m.version(name)
        except m.PackageNotFoundError: pass
    raise SystemExit('missing distribution: ' + ','.join(names))
print(json.dumps({'python': platform.python_version(), 'sapien': version('sapien'),
                  'curobo': version('nvidia-curobo','curobo')}))
"""
    try:
        result = subprocess.run(
            [str(runtime_python), "-c", code], check=True, capture_output=True,
            text=True, timeout=15,
        )
        value = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise MotionCapabilityError("RoboTwin runtime identity is unavailable") from exc
    if set(value) != {"python", "sapien", "curobo"} or any(
        not isinstance(item, str) or not item for item in value.values()
    ):
        raise MotionCapabilityError("RoboTwin runtime identity is invalid")
    return value


def _git_revision(root: Path) -> str:
    try:
        top_level = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"], check=True,
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        revision = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise MotionCapabilityError("RoboTwin git revision is unavailable") from exc
    if Path(top_level).resolve() != root.resolve():
        raise MotionCapabilityError("RoboTwin root is not a checkout root")
    if len(revision) != 40 or any(char not in "0123456789abcdef" for char in revision):
        raise MotionCapabilityError("RoboTwin git revision is invalid")
    return revision


def derive_robotwin_motion_capability(
    robotwin_root: str | os.PathLike[str],
    *,
    embodiment_id: str,
    arm_id: Literal["left", "right"],
    runtime_python: str | os.PathLike[str],
) -> MotionCapabilityDocument:
    """Derive one no-motion capability document from the selected provider."""

    root = Path(robotwin_root)
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise MotionCapabilityError("RoboTwin root must be an absolute checkout")
    if (
        not embodiment_id
        or embodiment_id in {".", ".."}
        or any(char.isspace() for char in embodiment_id)
        or "/" in embodiment_id
        or "\\" in embodiment_id
    ):
        raise MotionCapabilityError("RoboTwin embodiment identity is invalid")
    if arm_id not in {"left", "right"}:
        raise MotionCapabilityError("RoboTwin arm identity is invalid")
    embodiment_root = root / "assets" / "embodiments" / embodiment_id
    config_path = embodiment_root / "config.yml"
    planner_profile_path = embodiment_root / "curobo.yml"
    planner_source_path = root / "envs" / "robot" / "planner.py"
    simulator_source_path = root / "envs" / "_base_task.py"
    controller_source_path = root / "envs" / "robot" / "robot.py"
    try:
        config = _read_unique_yaml(
            config_path, error_type=MotionCapabilityError, label="embodiment profile"
        )
        planner_profile = _read_unique_yaml(
            planner_profile_path, error_type=MotionCapabilityError, label="CuRobo profile"
        )
    except OSError as exc:
        raise MotionCapabilityError("RoboTwin capability source is unavailable") from exc
    if config.get("planner") != "curobo":
        raise MotionCapabilityError("selected embodiment does not use CuRobo")
    arm_index = 0 if arm_id == "left" else 1
    arm_orders = config.get("arm_joints_name")
    if not isinstance(arm_orders, list) or len(arm_orders) != 2:
        raise MotionCapabilityError("embodiment arm joint order is invalid")
    joint_order = tuple(str(item) for item in arm_orders[arm_index])
    if not joint_order or len(set(joint_order)) != len(joint_order):
        raise MotionCapabilityError("embodiment arm joint order is invalid")
    urdf_rel = config.get("urdf_path")
    if not isinstance(urdf_rel, str) or Path(urdf_rel).is_absolute():
        raise MotionCapabilityError("embodiment URDF path is invalid")
    urdf_path = embodiment_root / urdf_rel
    resolved_urdf_path = urdf_path.resolve()
    if (
        urdf_path.is_symlink()
        or root.resolve() not in resolved_urdf_path.parents
        or not resolved_urdf_path.is_file()
    ):
        raise MotionCapabilityError("embodiment URDF path is unavailable or unsafe")
    try:
        urdf_root = ET.parse(resolved_urdf_path).getroot()
    except (OSError, ET.ParseError) as exc:
        raise MotionCapabilityError("embodiment URDF is invalid") from exc
    by_name = {joint.get("name"): joint for joint in urdf_root.findall("joint")}
    position_lower: list[float] = []
    position_upper: list[float] = []
    velocity_upper: list[float] = []
    effort: list[float] = []
    for name in joint_order:
        joint = by_name.get(name)
        limit = None if joint is None else joint.find("limit")
        if limit is None:
            raise MotionCapabilityError(f"URDF limit is unavailable for {name}")
        try:
            position_lower.append(float(limit.attrib["lower"]))
            position_upper.append(float(limit.attrib["upper"]))
            velocity_upper.append(float(limit.attrib["velocity"]))
            effort.append(float(limit.attrib["effort"]))
        except (KeyError, ValueError) as exc:
            raise MotionCapabilityError(f"URDF limit is invalid for {name}") from exc
    try:
        cspace = planner_profile["robot_cfg"]["kinematics"]["cspace"]
        planner_joint_order = tuple(str(item) for item in cspace["joint_names"])
        acceleration = float(cspace["max_acceleration"])
        jerk = float(cspace["max_jerk"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MotionCapabilityError("CuRobo cspace limits are invalid") from exc
    if (
        planner_joint_order[: len(joint_order)] != joint_order
        or acceleration <= 0
        or jerk <= 0
    ):
        raise MotionCapabilityError("CuRobo joint order or derivative limits are invalid")
    planner_dt = _planner_dt(planner_source_path)
    simulator_dt = _simulator_dt(simulator_source_path)
    drive_position, drive_velocity, force_bound = _drive_semantics(controller_source_path)
    runtime = _runtime_identity(Path(runtime_python))
    revision = _git_revision(root)
    controller_digest = hashlib.sha256(controller_source_path.read_bytes()).hexdigest()
    sources = (
        _source(root, urdf_path, "robot_description"),
        _source(root, config_path, "embodiment_profile"),
        _source(root, planner_profile_path, "planner_profile"),
        _source(root, planner_source_path, "planner_source"),
        _source(root, simulator_source_path, "simulator_source"),
        _source(root, controller_source_path, "controller_source"),
    )
    return MotionCapabilityDocument.model_validate({
        "robot_identity": embodiment_id,
        "arm_id": arm_id,
        "provider": {
            "robotwin_git_revision": revision,
            "simulator_version": runtime["sapien"],
            "planner_version": runtime["curobo"],
            "controller_version": f"source-{controller_digest[:16]}",
            "runtime_python_version": runtime["python"],
        },
        "joint_order": joint_order,
        "limits": {
            "position_lower_rad": position_lower,
            "position_upper_rad": position_upper,
            "velocity_lower_radps": [-value for value in velocity_upper],
            "velocity_upper_radps": velocity_upper,
            "acceleration_radps2": [acceleration] * len(joint_order),
            "jerk_radps3": [jerk] * len(joint_order),
            "effort_nm": effort,
        },
        "enforcement": {
            "joint_position": "planner_constrained",
            "joint_velocity": "planner_constrained",
            "joint_acceleration": "planner_constrained",
            "joint_jerk": "planner_constrained",
            "cartesian_velocity": "unknown",
            "joint_effort": "unknown",
            "drive_position_target": drive_position,
            "drive_velocity_target": drive_velocity,
            "drive_force_limit_bound": force_bound,
        },
        "timing": {
            "planner_dt_s": planner_dt,
            "simulator_default_dt_s": simulator_dt,
            "controller_dt_s": None,
        },
        "sources": sources,
    })


def validate_robotwin_motion_capability(
    document: MotionCapabilityDocument | Mapping[str, Any],
    robotwin_root: str | os.PathLike[str],
    *,
    runtime_python: str | os.PathLike[str],
    verifier_id: str,
) -> MotionCapabilityValidation:
    """Re-derive provider facts and emit no-motion source-validation evidence."""

    parsed = (
        document if isinstance(document, MotionCapabilityDocument)
        else MotionCapabilityDocument.model_validate(document)
    )
    expected = derive_robotwin_motion_capability(
        robotwin_root,
        embodiment_id=parsed.robot_identity,
        arm_id=parsed.arm_id,
        runtime_python=runtime_python,
    )
    if canonical_motion_capability(parsed) != canonical_motion_capability(expected):
        raise MotionCapabilityError("motion capability does not match provider sources")
    if not verifier_id or any(char.isspace() for char in verifier_id):
        raise MotionCapabilityError("motion capability verifier identity is invalid")
    return MotionCapabilityValidation(
        capability_sha256=motion_capability_digest(parsed),
        verifier_id=verifier_id,
        verified_at=datetime.now(timezone.utc).isoformat(),
        status="validated_planner_constraints",
        checks=(
            "source_digests", "runtime_identity", "joint_order", "per_joint_limits",
            "planner_timing", "simulator_timing", "drive_semantics",
            "no_controller_enforcement_claim",
        ),
    )


__all__ = [
    "MOTION_CAPABILITY_SCHEMA_VERSION",
    "MOTION_CAPABILITY_VALIDATION_SCHEMA_VERSION",
    "MotionCapabilityDocument",
    "MotionCapabilityError",
    "MotionCapabilityValidation",
    "canonical_motion_capability",
    "derive_robotwin_motion_capability",
    "motion_capability_digest",
    "validate_robotwin_motion_capability",
]
