from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from robotwin20_adapter import (
    MotionCapabilityDocument,
    MotionCapabilityError,
    MotionCapabilityValidation,
    canonical_motion_capability,
    derive_robotwin_motion_capability,
    motion_capability_digest,
    validate_robotwin_motion_capability,
)

JOINTS = tuple(f"panda_joint{index}" for index in range(1, 8))


def _write_provider_tree(root: Path, *, force_limit: bool = False) -> Path:
    embodiment = root / "assets" / "embodiments" / "franka-panda"
    robot = root / "envs" / "robot"
    embodiment.mkdir(parents=True)
    robot.mkdir(parents=True)
    (root / "envs" / "_base_task.py").write_text(
        "def setup(scene, kwargs):\n"
        "    scene.set_timestep(kwargs.get('timestep', 1 / 250))\n",
        encoding="utf-8",
    )
    (robot / "planner.py").write_text(
        "def configure(factory):\n"
        "    return factory(interpolation_dt=1 / 250)\n",
        encoding="utf-8",
    )
    force_source = (
        "\n    def configure(self, joint):\n"
        "        joint.set_drive_property(stiffness=1, damping=1, force_limit=10)\n"
        if force_limit
        else ""
    )
    (robot / "robot.py").write_text(
        "class Robot:\n"
        "    def set_arm_joints(self, position, velocity, arm):\n"
        "        for joint in self.joints:\n"
        "            joint.set_drive_target(position[0])\n"
        "            joint.set_drive_velocity_target(velocity[0])\n"
        + force_source,
        encoding="utf-8",
    )
    (embodiment / "config.yml").write_text(
        yaml.safe_dump(
            {
                "urdf_path": "./panda.urdf",
                "planner": "curobo",
                "arm_joints_name": [list(JOINTS), list(JOINTS)],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (embodiment / "curobo.yml").write_text(
        yaml.safe_dump(
            {
                "robot_cfg": {
                    "kinematics": {
                        "cspace": {
                            "joint_names": [*JOINTS, "panda_finger_joint1"],
                            "max_acceleration": 15.0,
                            "max_jerk": 500.0,
                        }
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    joints = []
    for index, name in enumerate(JOINTS):
        velocity = 2.175 if index < 4 else 2.61
        joints.append(
            f'<joint name="{name}" type="revolute"><limit lower="-{index + 1}" '
            f'upper="{index + 1}" velocity="{velocity}" effort="{87 if index < 4 else 12}"/>'
            "</joint>"
        )
    (embodiment / "panda.urdf").write_text(
        "<robot name=\"panda\">" + "".join(joints) + "</robot>\n",
        encoding="utf-8",
    )
    runtime = root / "runtime-python"
    runtime.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' '{\"python\":\"3.10.0\",\"sapien\":\"3.0.0b1\","
        "\"curobo\":\"0.7.8\"}'\n",
        encoding="utf-8",
    )
    runtime.chmod(0o755)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=PAOS Test",
            "-c",
            "user.email=paos-test@example.invalid",
            "commit",
            "-q",
            "-m",
            "provider fixture",
        ],
        check=True,
    )
    return runtime


def _derive(root: Path, runtime: Path, arm: str = "left") -> MotionCapabilityDocument:
    return derive_robotwin_motion_capability(
        root.resolve(),
        embodiment_id="franka-panda",
        arm_id=arm,
        runtime_python=runtime.resolve(),
    )


def test_derives_per_joint_provider_capability_without_motion_authority(tmp_path: Path):
    runtime = _write_provider_tree(tmp_path)
    left = _derive(tmp_path, runtime, "left")
    right = _derive(tmp_path, runtime, "right")

    assert left.joint_order == JOINTS
    assert left.limits.velocity_upper_radps == pytest.approx(
        (2.175, 2.175, 2.175, 2.175, 2.61, 2.61, 2.61)
    )
    assert left.limits.velocity_lower_radps == pytest.approx(
        tuple(-value for value in left.limits.velocity_upper_radps)
    )
    assert left.limits.acceleration_radps2 == (15.0,) * 7
    assert left.limits.jerk_radps3 == (500.0,) * 7
    assert left.timing.planner_dt_s == pytest.approx(0.004)
    assert left.timing.simulator_default_dt_s == pytest.approx(0.004)
    assert left.timing.controller_dt_s is None
    assert left.enforcement.joint_velocity == "planner_constrained"
    assert left.enforcement.cartesian_velocity == "unknown"
    assert left.enforcement.joint_effort == "unknown"
    assert left.controller_qualification_ref is None
    assert left.motion_authorized is False
    assert left.arm_id == "left" and right.arm_id == "right"
    assert motion_capability_digest(left) != motion_capability_digest(right)
    assert {source.role for source in left.sources} == {
        "robot_description",
        "embodiment_profile",
        "planner_profile",
        "planner_source",
        "simulator_source",
        "controller_source",
    }


def test_validation_rederives_sources_and_remains_non_authoritative(tmp_path: Path):
    runtime = _write_provider_tree(tmp_path)
    capability = _derive(tmp_path, runtime)
    validation = validate_robotwin_motion_capability(
        capability,
        tmp_path.resolve(),
        runtime_python=runtime.resolve(),
        verifier_id="paos-source-validator/v1",
    )

    assert validation.capability_sha256 == motion_capability_digest(capability)
    assert validation.status == "validated_planner_constraints"
    assert validation.independent_execution_qualification is False
    assert validation.controller_enforced is False
    assert validation.motion_authorized is False

    planner = tmp_path / "envs" / "robot" / "planner.py"
    planner.write_text(planner.read_text() + "# changed after capture\n", encoding="utf-8")
    with pytest.raises(MotionCapabilityError, match="does not match provider sources"):
        validate_robotwin_motion_capability(
            capability,
            tmp_path.resolve(),
            runtime_python=runtime.resolve(),
            verifier_id="paos-source-validator/v1",
        )


def test_canonical_digest_is_stable_across_mapping_key_order(tmp_path: Path):
    runtime = _write_provider_tree(tmp_path)
    capability = _derive(tmp_path, runtime)
    payload = capability.model_dump(mode="json")
    reversed_payload = dict(reversed(tuple(payload.items())))

    assert canonical_motion_capability(payload) == canonical_motion_capability(reversed_payload)
    assert motion_capability_digest(payload) == motion_capability_digest(reversed_payload)


def test_runtime_python_symlink_is_supported_but_source_symlinks_are_rejected(tmp_path: Path):
    runtime = _write_provider_tree(tmp_path)
    runtime_link = tmp_path / "runtime-python-link"
    runtime_link.symlink_to(runtime.name)
    capability = derive_robotwin_motion_capability(
        tmp_path.resolve(),
        embodiment_id="franka-panda",
        arm_id="left",
        runtime_python=runtime_link,
    )
    assert capability.provider.runtime_python_version == "3.10.0"

    urdf = tmp_path / "assets" / "embodiments" / "franka-panda" / "panda.urdf"
    target = tmp_path / "panda-real.urdf"
    urdf.rename(target)
    urdf.symlink_to(target)
    with pytest.raises(MotionCapabilityError, match="unavailable or unsafe"):
        _derive(tmp_path, runtime)


def test_capability_can_bind_external_provider_controller_source(tmp_path: Path):
    runtime = _write_provider_tree(tmp_path)
    controller = tmp_path / "paos_adapter_controller.py"
    controller.write_text(
        "class CapabilityBoundedDriveController:\n    pass\n", encoding="utf-8"
    )
    capability = derive_robotwin_motion_capability(
        tmp_path.resolve(),
        embodiment_id="franka-panda",
        arm_id="left",
        runtime_python=runtime.resolve(),
        controller_source_path=controller.resolve(),
        controller_id="paos-robotwin-capability-bounded-drive-target",
    )
    assert capability.provider.controller_id == "paos-robotwin-capability-bounded-drive-target"
    assert capability.sources[-1].relative_path == "paos_adapter/paos_adapter_controller.py"
    assert capability.enforcement.drive_velocity_target is True
    validation = validate_robotwin_motion_capability(
        capability,
        tmp_path.resolve(),
        runtime_python=runtime.resolve(),
        verifier_id="paos-source-validator/v1",
        controller_source_path=controller.resolve(),
        controller_id="paos-robotwin-capability-bounded-drive-target",
    )
    assert validation.status == "validated_planner_constraints"


def test_joint_order_timing_and_controller_claims_fail_closed(tmp_path: Path):
    runtime = _write_provider_tree(tmp_path)
    profile_path = tmp_path / "assets" / "embodiments" / "franka-panda" / "curobo.yml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["robot_cfg"]["kinematics"]["cspace"]["joint_names"][0:2] = reversed(
        profile["robot_cfg"]["kinematics"]["cspace"]["joint_names"][0:2]
    )
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    with pytest.raises(MotionCapabilityError, match="joint order"):
        _derive(tmp_path, runtime)

    timing_root = tmp_path / "timing-provider"
    runtime = _write_provider_tree(timing_root)
    planner = timing_root / "envs" / "robot" / "planner.py"
    planner.write_text(
        planner.read_text(encoding="utf-8") + "\ndef other(factory):\n    return factory(time_step=1 / 100)\n",
        encoding="utf-8",
    )
    with pytest.raises(MotionCapabilityError, match="timing is absent or ambiguous"):
        _derive(timing_root, runtime)

    other_root = tmp_path / "force-provider"
    other_runtime = _write_provider_tree(other_root, force_limit=True)
    with pytest.raises(ValueError, match="force-limit binding is not proven"):
        _derive(other_root, other_runtime)


def test_invalid_identity_and_validation_escalation_are_rejected(tmp_path: Path):
    runtime = _write_provider_tree(tmp_path)
    with pytest.raises(MotionCapabilityError, match="embodiment identity"):
        derive_robotwin_motion_capability(
            tmp_path.resolve(),
            embodiment_id="../../outside",
            arm_id="left",
            runtime_python=runtime.resolve(),
        )

    capability = _derive(tmp_path, runtime)
    validation = validate_robotwin_motion_capability(
        capability,
        tmp_path.resolve(),
        runtime_python=runtime.resolve(),
        verifier_id="paos-source-validator/v1",
    ).model_dump(mode="json")
    validation["controller_enforced"] = True
    validation["independent_execution_qualification"] = True
    with pytest.raises(ValueError):
        MotionCapabilityValidation.model_validate(validation)

    validation["controller_enforced"] = False
    validation["independent_execution_qualification"] = False
    validation["checks"] = ["source_digests"]
    with pytest.raises(ValueError, match="checks are incomplete"):
        MotionCapabilityValidation.model_validate(validation)


def test_artifact_json_round_trip_preserves_digest(tmp_path: Path):
    runtime = _write_provider_tree(tmp_path)
    capability = _derive(tmp_path, runtime)
    encoded = canonical_motion_capability(capability)
    parsed = MotionCapabilityDocument.model_validate_json(encoded)
    assert parsed == capability
    assert motion_capability_digest(parsed) == motion_capability_digest(capability)
    assert json.loads(encoded)["motion_authorized"] is False
