"""Adapter-local trajectory execution control contracts.

This module deliberately does not pretend that a SAPIEN drive target is a hard
Cartesian velocity limiter.  The current RoboTwin backend exposes only a
measured-speed guard; a future backend may opt into ``hard_bounded`` only after
independent qualification.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

ControllerMode = Literal["diagnostic_measured_guard", "hard_bounded"]


class ControllerUnavailableError(RuntimeError):
    """The selected execution mode is not provided by the backend."""


class SpeedLimitViolationError(RuntimeError):
    """A measured simulator step exceeded the immutable Cartesian-speed gate."""

    def __init__(self, details: Mapping[str, Any]) -> None:
        self.details = dict(details)
        super().__init__("simulator motion exceeds waypoint linear-speed limit")


@dataclass(frozen=True)
class ControllerCapabilities:
    controller_id: str
    controller_version: str
    hard_cartesian_speed_limit: bool
    measured_speed_guard: bool

    def validate(self) -> None:
        if not self.controller_id or not self.controller_version:
            raise ControllerUnavailableError("controller identity is missing")
        if not isinstance(self.hard_cartesian_speed_limit, bool) or not isinstance(
            self.measured_speed_guard, bool
        ):
            raise ControllerUnavailableError("controller capability flags are invalid")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "paos-robotwin20-execution-controller/v1",
            "controller_id": self.controller_id,
            "controller_version": self.controller_version,
            "hard_cartesian_speed_limit": self.hard_cartesian_speed_limit,
            "measured_speed_guard": self.measured_speed_guard,
        }


class SpeedBoundedExecutionController:
    """Common adapter seam for qualified and diagnostic execution backends."""

    def __init__(self, capabilities: ControllerCapabilities, *, mode: ControllerMode) -> None:
        capabilities.validate()
        if mode not in {"diagnostic_measured_guard", "hard_bounded"}:
            raise ControllerUnavailableError("controller mode is invalid")
        self.capabilities = capabilities
        self.mode = mode

    def preflight(self, *, max_linear_speed_mps: float, timestep_s: float) -> None:
        if (
            not math.isfinite(float(max_linear_speed_mps))
            or float(max_linear_speed_mps) <= 0
            or not math.isfinite(float(timestep_s))
            or float(timestep_s) <= 0
        ):
            raise ControllerUnavailableError("controller speed limit or timestep is invalid")
        if self.mode == "hard_bounded" and not self.capabilities.hard_cartesian_speed_limit:
            raise ControllerUnavailableError("backend has no hard Cartesian speed limiter")
        if self.mode == "diagnostic_measured_guard" and not self.capabilities.measured_speed_guard:
            raise ControllerUnavailableError("backend has no measured-speed guard")

    def measure_step(
        self,
        *,
        previous_position: Sequence[float],
        current_position: Sequence[float],
        timestep_s: float,
        max_linear_speed_mps: float,
        details: Mapping[str, Any],
    ) -> float:
        self.preflight(max_linear_speed_mps=max_linear_speed_mps, timestep_s=timestep_s)
        if len(previous_position) != 3 or len(current_position) != 3:
            raise ControllerUnavailableError("Cartesian position must contain three coordinates")
        displacement = [float(current_position[i]) - float(previous_position[i]) for i in range(3)]
        if any(not math.isfinite(value) for value in displacement):
            raise ControllerUnavailableError("Cartesian position contains non-finite values")
        speed = math.sqrt(sum(value * value for value in displacement)) / float(timestep_s)
        if not math.isfinite(speed) or speed > float(max_linear_speed_mps) + 1e-3:
            violation = dict(details)
            violation.update({"observed_mps": speed, "limit_mps": float(max_linear_speed_mps)})
            raise SpeedLimitViolationError(violation)
        return speed


def build_robotwin_drive_target_controller(
    *, mode: ControllerMode, expected: Mapping[str, Any] | None = None
) -> SpeedBoundedExecutionController:
    """Build the current RoboTwin/SAPIEN drive-target controller seam.

    ``set_arm_joints`` does not expose a hard Cartesian limiter, so hard mode is
    intentionally unavailable.  Diagnostic mode remains useful for collecting
    measured-speed evidence and failing closed on violations.
    """

    capabilities = ControllerCapabilities(
            controller_id="robotwin-sapien-drive-target",
            controller_version="unqualified-drive-target",
            hard_cartesian_speed_limit=False,
            measured_speed_guard=True,
        )
    if expected is not None and dict(expected) != capabilities.as_dict() | {"mode": mode}:
        raise ControllerUnavailableError("controller policy does not match backend capabilities")
    return SpeedBoundedExecutionController(capabilities, mode=mode)


__all__ = [
    "ControllerCapabilities",
    "ControllerMode",
    "ControllerUnavailableError",
    "SpeedBoundedExecutionController",
    "SpeedLimitViolationError",
    "build_robotwin_drive_target_controller",
]
