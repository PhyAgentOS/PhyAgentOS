"""Runtime shared exception types and failure mapping (neutral base module).

All lower-level runtime modules (Target / Policy / Adapter / Perception /
Communication / Perception Plugin, etc.) import shared exception types from
here, avoiding a dependency inversion where the Session orchestration layer
(watchdog) is treated as a common base package.
"""

from __future__ import annotations

__all__ = [
    "RuntimeErrorBase",
    "SchemaValidationError",
    "TargetBuildError",
    "TargetResetError",
    "TargetStepError",
    "TargetConnectionError",
    "TargetProtocolError",
    "AdapterError",
    "PolicyClientError",
    "PolicyConnectionError",
    "PolicyTimeoutError",
    "PolicyProtocolError",
    "SessionTimeoutError",
    "error_code_for",
    "terminal_status_for",
]


class RuntimeErrorBase(Exception):  # noqa: N818 - historical public API name, kept for compatibility
    """Base class for recoverable runtime v2 failures."""


class SchemaValidationError(RuntimeErrorBase):
    pass


class TargetBuildError(RuntimeErrorBase):
    pass


class TargetResetError(RuntimeErrorBase):
    pass


class TargetStepError(RuntimeErrorBase):
    pass


class TargetConnectionError(RuntimeErrorBase):
    pass


class TargetProtocolError(RuntimeErrorBase):
    pass


class AdapterError(RuntimeErrorBase):
    pass


class PolicyClientError(RuntimeErrorBase):
    pass


class PolicyConnectionError(PolicyClientError):
    pass


class PolicyTimeoutError(PolicyClientError):
    pass


class PolicyProtocolError(PolicyClientError):
    pass


class SessionTimeoutError(RuntimeErrorBase):
    pass


def error_code_for(exc: Exception) -> str:
    """Return the protocol error code for an exception."""
    mapping = {
        SchemaValidationError: "SCHEMA_VALIDATION",
        TargetBuildError: "TARGET_BUILD",
        TargetResetError: "TARGET_RESET",
        TargetStepError: "TARGET_STEP",
        TargetConnectionError: "TARGET_CONNECTION",
        TargetProtocolError: "TARGET_PROTOCOL",
        AdapterError: "ADAPTER",
        PolicyTimeoutError: "POLICY_TIMEOUT",
        PolicyProtocolError: "POLICY_PROTOCOL",
        PolicyConnectionError: "POLICY_CONNECTION",
        PolicyClientError: "POLICY_CLIENT",
        SessionTimeoutError: "SESSION_TIMEOUT",
    }
    for cls, code in mapping.items():
        if isinstance(exc, cls):
            return code
    return "RUNTIME_ERROR"


def terminal_status_for(exc: Exception) -> str:
    """Return the terminal session status for an exception."""
    if isinstance(exc, SchemaValidationError):
        return "rejected"
    if isinstance(exc, SessionTimeoutError):
        return "timed_out"
    return "failed"
