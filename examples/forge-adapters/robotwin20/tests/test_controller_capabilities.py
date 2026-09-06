from __future__ import annotations

import pytest

from robotwin20_adapter import (
    ControllerCapabilityDocument,
    ControllerCapabilityError,
    controller_capability_digest,
    load_controller_capability_document,
)


def _document(**overrides):
    value = {
        "schema_version": "paos-robotwin20-controller-capabilities/v1",
        "robot_id": "franka-panda",
        "arm_id": "right",
        "controller_id": "robotwin-sapien-drive-target",
        "controller_version": "unqualified-drive-target",
        "runtime_kind": "simulation",
        "operating_mode": "drive_target",
        "joint_velocity_limit_radps": 1.0,
        "cartesian_linear_speed_limit_mps": 0.20,
        "source_kind": "diagnostic_threshold",
        "enforcement": "measured_diagnostic",
        "controller_enforced": False,
        "provenance_ref": "artifact://robotwin/franka/controller-profile",
        "motion_authorized": False,
    }
    value.update(overrides)
    return value


def test_diagnostic_threshold_is_not_hard_controller_bound():
    document = ControllerCapabilityDocument.model_validate(_document())
    assert document.enforcement == "measured_diagnostic"
    assert document.controller_enforced is False
    assert len(controller_capability_digest(document)) == 64


def test_qualification_reference_is_part_of_capability_digest():
    base = ControllerCapabilityDocument.model_validate(_document())
    qualified = ControllerCapabilityDocument.model_validate(
        _document(
            source_kind="simulator_controller",
            enforcement="controller_hard",
            controller_enforced=True,
            qualification_ref="artifact://qualification/controller-v1",
        )
    )
    assert controller_capability_digest(base) != controller_capability_digest(qualified)


@pytest.mark.parametrize(
    "overrides",
    [
        {"source_kind": "diagnostic_threshold", "enforcement": "controller_hard", "controller_enforced": True, "qualification_ref": "artifact://qualification/1"},
        {"source_kind": "hardware_sdk", "enforcement": "controller_hard", "controller_enforced": True},
        {"source_kind": "adapter_policy", "enforcement": "planner_only", "controller_enforced": True},
        {"runtime_kind": "hardware", "source_kind": "simulator_controller", "enforcement": "planner_only"},
        {"joint_velocity_limit_radps": None, "cartesian_linear_speed_limit_mps": None},
    ],
)
def test_unsupported_or_unqualified_hard_bound_fails_closed(overrides):
    with pytest.raises(ValueError):
        ControllerCapabilityDocument.model_validate(_document(**overrides))


def test_loader_rejects_non_absolute_or_symlink(tmp_path):
    with pytest.raises(ControllerCapabilityError):
        load_controller_capability_document(tmp_path / "missing.yaml")


def test_loader_validates_yaml_document(tmp_path):
    path = tmp_path / "controller.yaml"
    path.write_text(
        "\n".join(
            [
                "schema_version: paos-robotwin20-controller-capabilities/v1",
                "robot_id: franka-panda",
                "arm_id: right",
                "controller_id: robotwin-sapien-drive-target",
                "controller_version: unqualified-drive-target",
                "runtime_kind: simulation",
                "operating_mode: drive_target",
                "joint_velocity_limit_radps: 1.0",
                "cartesian_linear_speed_limit_mps: 0.20",
                "source_kind: diagnostic_threshold",
                "enforcement: measured_diagnostic",
                "controller_enforced: false",
                "provenance_ref: artifact://robotwin/franka/controller-profile",
                "motion_authorized: false",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    document = load_controller_capability_document(path)
    assert document.robot_id == "franka-panda"
