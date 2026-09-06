from __future__ import annotations

import pytest
from trajectory_controller import (
    ControllerCapabilities,
    ControllerUnavailableError,
    SpeedBoundedExecutionController,
    SpeedLimitViolationError,
    build_robotwin_drive_target_controller,
)


def test_drive_target_backend_is_explicitly_diagnostic_only():
    controller = build_robotwin_drive_target_controller(mode="diagnostic_measured_guard")
    controller.preflight(max_linear_speed_mps=0.2, timestep_s=0.004)
    with pytest.raises(ControllerUnavailableError, match="no hard Cartesian"):
        build_robotwin_drive_target_controller(mode="hard_bounded").preflight(
            max_linear_speed_mps=0.2, timestep_s=0.004
        )


def test_controller_policy_binding_rejects_identity_or_mode_drift():
    with pytest.raises(ControllerUnavailableError, match="policy"):
        build_robotwin_drive_target_controller(
            mode="diagnostic_measured_guard",
            expected={
                "controller_id": "other-controller",
                "controller_version": "v1",
                "hard_cartesian_speed_limit": False,
                "measured_speed_guard": True,
                "mode": "diagnostic_measured_guard",
            },
        )


def test_measure_step_returns_speed_and_binds_details():
    controller = build_robotwin_drive_target_controller(mode="diagnostic_measured_guard")
    speed = controller.measure_step(
        previous_position=(0.0, 0.0, 0.0),
        current_position=(0.0004, 0.0, 0.0),
        timestep_s=0.004,
        max_linear_speed_mps=0.2,
        details={"phase": "transport", "step": 7},
    )
    assert speed == pytest.approx(0.1)


def test_measure_step_fails_closed_with_violation_evidence():
    controller = build_robotwin_drive_target_controller(mode="diagnostic_measured_guard")
    with pytest.raises(SpeedLimitViolationError) as caught:
        controller.measure_step(
            previous_position=(0.0, 0.0, 0.0),
            current_position=(0.001, 0.0, 0.0),
            timestep_s=0.004,
            max_linear_speed_mps=0.2,
            details={"phase": "contact", "step": 3},
        )
    assert caught.value.details == {
        "phase": "contact",
        "step": 3,
        "observed_mps": pytest.approx(0.25),
        "limit_mps": 0.2,
    }


@pytest.mark.parametrize(
    "capabilities",
    [
        ControllerCapabilities("", "v1", False, True),
        ControllerCapabilities("controller", "", False, True),
    ],
)
def test_invalid_controller_identity_is_rejected(capabilities):
    with pytest.raises(ControllerUnavailableError, match="identity"):
        SpeedBoundedExecutionController(capabilities, mode="diagnostic_measured_guard")


def test_invalid_measurement_inputs_fail_closed():
    controller = build_robotwin_drive_target_controller(mode="diagnostic_measured_guard")
    with pytest.raises(ControllerUnavailableError, match="three coordinates"):
        controller.measure_step(
            previous_position=(0.0, 0.0),
            current_position=(0.0, 0.0, 0.0),
            timestep_s=0.004,
            max_linear_speed_mps=0.2,
            details={},
        )
