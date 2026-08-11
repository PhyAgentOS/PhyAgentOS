"""Compatibility shim: re-exports shared exception types from the neutral base module.

Since the issue #83 fix, shared exception types live in
``PhyAgentOS.runtime.errors``. This module is kept only for backward
compatibility - legacy callers may still use
``from PhyAgentOS.runtime.watchdog.errors import X``, but new code should
import directly from ``PhyAgentOS.runtime.errors``.
"""

from __future__ import annotations

from PhyAgentOS.runtime.errors import (
    AdapterError,
    PolicyClientError,
    PolicyConnectionError,
    PolicyProtocolError,
    PolicyTimeoutError,
    RuntimeErrorBase,
    SchemaValidationError,
    SessionTimeoutError,
    TargetBuildError,
    TargetConnectionError,
    TargetProtocolError,
    TargetResetError,
    TargetStepError,
    error_code_for,
    terminal_status_for,
)

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
