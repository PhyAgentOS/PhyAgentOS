"""Tests for the PhyAgentOS.runtime.errors shared exception module.

Verifies the goal of issue #83: shared exception types are moved from the
watchdog orchestration layer into the neutral ``runtime.errors`` base module,
while ``watchdog.errors`` stays as a compatibility layer preserving backward
compatibility (same objects, ``is`` equality).
"""

from __future__ import annotations

import pytest

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


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------
def test_all_exceptions_share_runtime_error_base() -> None:
    for exc_cls in (
        SchemaValidationError,
        TargetBuildError,
        TargetResetError,
        TargetStepError,
        TargetConnectionError,
        TargetProtocolError,
        AdapterError,
        PolicyClientError,
        SessionTimeoutError,
    ):
        assert issubclass(exc_cls, RuntimeErrorBase)


def test_policy_exceptions_have_policy_client_base() -> None:
    for exc_cls in (PolicyConnectionError, PolicyTimeoutError, PolicyProtocolError):
        assert issubclass(exc_cls, PolicyClientError)


# ---------------------------------------------------------------------------
# error_code_for mapping
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("exc", "expected_code"),
    [
        (SchemaValidationError(), "SCHEMA_VALIDATION"),
        (TargetBuildError(), "TARGET_BUILD"),
        (TargetResetError(), "TARGET_RESET"),
        (TargetStepError(), "TARGET_STEP"),
        (TargetConnectionError(), "TARGET_CONNECTION"),
        (TargetProtocolError(), "TARGET_PROTOCOL"),
        (AdapterError(), "ADAPTER"),
        (PolicyTimeoutError(), "POLICY_TIMEOUT"),
        (PolicyProtocolError(), "POLICY_PROTOCOL"),
        (PolicyConnectionError(), "POLICY_CONNECTION"),
        (PolicyClientError(), "POLICY_CLIENT"),
        (SessionTimeoutError(), "SESSION_TIMEOUT"),
    ],
)
def test_error_code_for_known_exceptions(exc: Exception, expected_code: str) -> None:
    assert error_code_for(exc) == expected_code


def test_error_code_for_subclass_uses_most_specific_code() -> None:
    # A subclass must match its own code, not PolicyClientError's POLICY_CLIENT
    assert error_code_for(PolicyTimeoutError()) == "POLICY_TIMEOUT"
    assert error_code_for(PolicyConnectionError()) == "POLICY_CONNECTION"


def test_error_code_for_unknown_exception_returns_runtime_error() -> None:
    assert error_code_for(ValueError("boom")) == "RUNTIME_ERROR"


# ---------------------------------------------------------------------------
# terminal_status_for mapping
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("exc", "expected_status"),
    [
        (SchemaValidationError(), "rejected"),
        (SessionTimeoutError(), "timed_out"),
        (TargetStepError(), "failed"),
        (PolicyProtocolError(), "failed"),
        (ValueError("boom"), "failed"),
    ],
)
def test_terminal_status_for(exc: Exception, expected_status: str) -> None:
    assert terminal_status_for(exc) == expected_status


# ---------------------------------------------------------------------------
# Compatibility layer: watchdog.errors must expose the same objects as runtime.errors
# ---------------------------------------------------------------------------
def test_watchdog_errors_re_exports_same_objects() -> None:
    from PhyAgentOS.runtime.watchdog import errors as watchdog_errors

    assert watchdog_errors.RuntimeErrorBase is RuntimeErrorBase
    assert watchdog_errors.SchemaValidationError is SchemaValidationError
    assert watchdog_errors.TargetBuildError is TargetBuildError
    assert watchdog_errors.TargetResetError is TargetResetError
    assert watchdog_errors.TargetStepError is TargetStepError
    assert watchdog_errors.TargetConnectionError is TargetConnectionError
    assert watchdog_errors.TargetProtocolError is TargetProtocolError
    assert watchdog_errors.AdapterError is AdapterError
    assert watchdog_errors.PolicyClientError is PolicyClientError
    assert watchdog_errors.PolicyConnectionError is PolicyConnectionError
    assert watchdog_errors.PolicyTimeoutError is PolicyTimeoutError
    assert watchdog_errors.PolicyProtocolError is PolicyProtocolError
    assert watchdog_errors.SessionTimeoutError is SessionTimeoutError
    assert watchdog_errors.error_code_for is error_code_for
    assert watchdog_errors.terminal_status_for is terminal_status_for
