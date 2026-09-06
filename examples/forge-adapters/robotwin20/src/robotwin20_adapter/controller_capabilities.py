"""Provider-local controller capability contract for RoboTwin profiles.

The PAOS core only carries an opaque reference to this document through
``ArmCapability``.  The document itself is adapter-owned so SDK- and
simulator-specific limits do not become a second global PAOS configuration
source.  A measured diagnostic threshold is deliberately not a hard controller
bound.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from .perception_profile import _read_unique_yaml

CONTROLLER_CAPABILITY_SCHEMA_VERSION = "paos-robotwin20-controller-capabilities/v1"
ControllerRuntime = Literal["simulation", "hardware"]
ControllerSource = Literal[
    "hardware_sdk", "controller_manual", "simulator_controller", "benchmark_policy",
    "adapter_policy", "diagnostic_threshold"
]
ControllerEnforcement = Literal["controller_hard", "planner_only", "measured_diagnostic", "unknown"]


class ControllerCapabilityError(ValueError):
    """A controller capability document is missing or semantically unsafe."""


class ControllerCapabilityDocument(BaseModel):
    """Immutable, provider-owned controller limits and their provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["paos-robotwin20-controller-capabilities/v1"] = (
        CONTROLLER_CAPABILITY_SCHEMA_VERSION
    )
    robot_id: str
    arm_id: str
    controller_id: str
    controller_version: str
    runtime_kind: ControllerRuntime
    operating_mode: str
    joint_velocity_limit_radps: float | None = None
    cartesian_linear_speed_limit_mps: float | None = None
    cartesian_angular_speed_limit_radps: float | None = None
    source_kind: ControllerSource
    enforcement: ControllerEnforcement
    controller_enforced: bool
    provenance_ref: str
    qualification_ref: str | None = None
    motion_authorized: Literal[False] = False

    @field_validator("robot_id", "arm_id", "controller_id", "controller_version", "operating_mode")
    @classmethod
    def validate_identity(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip() or any(char in value for char in "/\\"):
            raise ValueError("controller capability identity is invalid")
        return value.strip()

    @field_validator("provenance_ref", "qualification_ref")
    @classmethod
    def validate_artifact_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.startswith("artifact://") or any(
            char.isspace() for char in value
        ):
            raise ValueError("controller capability artifact reference is invalid")
        return value

    @field_validator(
        "joint_velocity_limit_radps",
        "cartesian_linear_speed_limit_mps",
        "cartesian_angular_speed_limit_radps",
    )
    @classmethod
    def validate_limit(cls, value: float | None) -> float | None:
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(float(value)) or float(value) <= 0
        ):
            raise ValueError("controller capability limit must be finite and positive")
        return None if value is None else float(value)

    @model_validator(mode="after")
    def validate_semantics(self) -> "ControllerCapabilityDocument":
        if (
            self.joint_velocity_limit_radps is None
            and self.cartesian_linear_speed_limit_mps is None
            and self.cartesian_angular_speed_limit_radps is None
        ):
            raise ValueError("controller capability document requires at least one limit")
        if self.source_kind == "diagnostic_threshold":
            if self.enforcement != "measured_diagnostic" or self.controller_enforced:
                raise ValueError("diagnostic threshold cannot claim controller enforcement")
        if self.enforcement != "controller_hard" and self.controller_enforced:
            raise ValueError("non-hard controller capability cannot claim controller enforcement")
        if self.runtime_kind == "hardware" and self.source_kind == "simulator_controller":
            raise ValueError("hardware capability cannot use simulator-controller provenance")
        if self.enforcement == "controller_hard":
            if not self.controller_enforced:
                raise ValueError("hard controller capability must be controller-enforced")
            if self.qualification_ref is None:
                raise ValueError("hard controller capability requires qualification evidence")
            if self.source_kind not in {"hardware_sdk", "controller_manual", "simulator_controller"}:
                raise ValueError("hard controller capability source is not authoritative")
        if self.enforcement == "unknown" and self.controller_enforced:
            raise ValueError("unknown enforcement cannot claim controller enforcement")
        return self


def load_controller_capability_document(path: str | os.PathLike[str]) -> ControllerCapabilityDocument:
    """Load and strictly validate an adapter-owned capability document."""

    document_path = Path(path).expanduser()
    if not document_path.is_absolute() or not document_path.is_file() or document_path.is_symlink():
        raise ControllerCapabilityError("controller capability document must be an absolute regular file")
    try:
        value = _read_unique_yaml(document_path, error_type=ControllerCapabilityError, label="controller capability document")
        return ControllerCapabilityDocument.model_validate(value)
    except ControllerCapabilityError:
        raise
    except Exception as exc:
        raise ControllerCapabilityError("controller capability document is invalid") from exc


def controller_capability_digest(value: ControllerCapabilityDocument | dict[str, Any]) -> str:
    """Digest canonical capability content for profile/route binding."""

    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else dict(value)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


__all__ = [
    "CONTROLLER_CAPABILITY_SCHEMA_VERSION",
    "ControllerCapabilityDocument",
    "ControllerCapabilityError",
    "controller_capability_digest",
    "load_controller_capability_document",
]
