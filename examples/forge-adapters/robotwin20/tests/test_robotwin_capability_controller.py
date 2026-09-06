from __future__ import annotations

import pytest
from robotwin_capability_controller import (
    CapabilityBoundedDriveController,
    ControllerCommandError,
    ControllerLimits,
    ControllerState,
)


def _controller():
    writes = []
    limits = ControllerLimits(
        joint_order=("j1", "j2"),
        position_lower_rad=(-1.0, -1.0),
        position_upper_rad=(1.0, 1.0),
        velocity_lower_radps=(-1.0, -1.0),
        velocity_upper_radps=(1.0, 1.0),
    )
    controller = CapabilityBoundedDriveController(limits, lambda q, dq: writes.append((q, dq)))
    return controller, writes


def test_accepts_then_requires_step_acknowledgement():
    controller, writes = _controller()
    controller.command((0.1, 0.2), (0.5, 0.5))
    assert controller.status == "running"
    assert len(writes) == 1
    controller.before_step()
    controller.after_step()
    assert controller.status == ControllerState.READY
    assert controller.counters["settled_steps"] == 1


def test_over_limit_is_rejected_before_provider_write():
    controller, writes = _controller()
    with pytest.raises(ControllerCommandError, match="velocity exceeds"):
        controller.command((0.0, 0.0), (1.01, 0.0))
    assert writes == []
    assert controller.status == "rejected"
    assert controller.counters["rejected_commands"] == 1


def test_nan_and_bad_length_fail_as_controller_fault():
    controller, writes = _controller()
    with pytest.raises(ControllerCommandError, match="non-finite"):
        controller.command((float("nan"), 0.0), (0.0, 0.0))
    assert writes == []
    assert controller.status == "fault"
    with pytest.raises(ControllerCommandError, match="fault"):
        controller.command((0.0, 0.0), (0.0, 0.0))


def test_dropped_step_and_stop_are_terminal_until_reset():
    controller, _ = _controller()
    controller.command((0.0, 0.0), (0.1, 0.1))
    controller.dropped_step()
    assert controller.status == "fault"
    with pytest.raises(ControllerCommandError, match="fault"):
        controller.before_step()
    controller.reset()
    controller.command((0.0, 0.0), (0.1, 0.1))
    controller.stop()
    assert controller.status == "stopped"
    with pytest.raises(ControllerCommandError, match="stop"):
        controller.before_step()
    controller.reset()
    assert controller.status == "ready"


def test_provider_write_failure_becomes_fault():
    controller = CapabilityBoundedDriveController(
        ControllerLimits(
            joint_order=("j1",),
            position_lower_rad=(-1.0,),
            position_upper_rad=(1.0,),
            velocity_lower_radps=(-1.0,),
            velocity_upper_radps=(1.0,),
        ),
        lambda q, dq: (_ for _ in ()).throw(RuntimeError("provider")),
    )
    with pytest.raises(ControllerCommandError, match="write failed"):
        controller.command((0.0,), (0.1,))
    assert controller.status == "fault"


def test_idle_arm_does_not_require_a_command_for_other_arm_step():
    left, _ = _controller()
    right, _ = _controller()
    left.command((0.0, 0.0), (0.1, 0.1))
    assert left.has_pending_step is True
    assert right.has_pending_step is False
