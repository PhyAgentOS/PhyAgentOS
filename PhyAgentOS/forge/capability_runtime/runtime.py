"""Generic provider-neutral ToolEndpoint runtime.

This module owns ToolSpec registration, discovery/context, Query dispatch, and
the Gateway-side bookkeeping for bounded Actions.  It deliberately has no
simulator, model, camera, robot SDK, or Dora dependency.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from .ports import ActionAdmission, ActionEndpoint, QueryEndpoint


class CapabilityRuntimeError(RuntimeError):
    """Base error for invalid generic runtime registration or dispatch."""


class DuplicateToolError(CapabilityRuntimeError):
    """Raised when a ToolSpec identity is registered twice."""


class UnknownToolError(CapabilityRuntimeError):
    """Raised when a requested ToolSpec or operation is not registered."""


class ToolContractError(CapabilityRuntimeError):
    """Raised when a ToolSpec violates the provider-neutral registration contract."""


_SEMANTICS = {"query", "action", "session"}
_REQUIRED_SPEC_KEYS = {"tool_id", "endpoint_id", "operation", "semantics"}
_FORBIDDEN_PROVIDER_TERMS = re.compile(
    r"(?:robotwin|sapien|ultralytics|\byolo\b|dora|vendor[-_ ]?sdk)", re.IGNORECASE
)


@dataclass(frozen=True)
class EndpointRegistration:
    """Immutable public ToolSpec plus its private operation handler."""

    spec: dict[str, Any]
    endpoint: object
    context: dict[str, Any]


@dataclass
class Invocation:
    """Gateway-owned Action lifecycle state."""

    invocation_id: str
    attempt_id: str
    tool_id: str
    arguments: dict[str, Any]
    pending_polls: int
    terminal_result: dict[str, Any]
    caller_id: str | None = None
    timeout_ms: int | None = None
    status: str = "accepted"
    cancel_requested: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _provider_neutral(spec: Mapping[str, Any]) -> bool:
    try:
        serialized = json.dumps(spec, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return False
    return _FORBIDDEN_PROVIDER_TERMS.search(serialized) is None


def _validate_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(spec, Mapping):
        raise ToolContractError("ToolSpec must be an object")
    missing = sorted(_REQUIRED_SPEC_KEYS - set(spec))
    if missing:
        raise ToolContractError(f"ToolSpec is missing required field(s): {', '.join(missing)}")
    value = dict(spec)
    for key in ("tool_id", "endpoint_id", "operation"):
        if not isinstance(value[key], str) or not value[key].strip():
            raise ToolContractError(f"ToolSpec {key} must be a non-empty string")
    if value["semantics"] not in _SEMANTICS:
        raise ToolContractError(f"unsupported ToolSpec semantics: {value['semantics']!r}")
    if not _provider_neutral(value):
        raise ToolContractError("ToolSpec contains provider-specific simulator/model terms")
    return value


class CapabilityRuntime:
    """Register generic ToolEndpoints and expose Gateway-facing lifecycle methods."""

    def __init__(self) -> None:
        self._tools: dict[str, EndpointRegistration] = {}
        self._operations: dict[tuple[str, str], EndpointRegistration] = {}
        self._invocations: dict[str, Invocation] = {}

    def register_tool(
        self,
        spec: Mapping[str, Any],
        endpoint: QueryEndpoint | ActionEndpoint,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        normalized = _validate_spec(spec)
        tool_id = normalized["tool_id"]
        endpoint_key = (normalized["endpoint_id"], normalized["operation"])
        if tool_id in self._tools or endpoint_key in self._operations:
            raise DuplicateToolError(f"ToolEndpoint already registered: {tool_id}")
        base_context = {"ready": True, "binding_error": None}
        if context is not None:
            base_context.update(dict(context))
        registration = EndpointRegistration(normalized, endpoint, base_context)
        self._tools[tool_id] = registration
        self._operations[endpoint_key] = registration

    def list_tools(self) -> dict[str, Any]:
        return {"tools": [self._tools[key].spec.copy() for key in sorted(self._tools)]}

    def get_tool(self, tool_id: str) -> dict[str, Any]:
        return self._registration(tool_id).spec.copy()

    def get_context(self, tool_id: str) -> dict[str, Any]:
        return self._registration(tool_id).context.copy()

    def get_tool_context(self, tool_id: str) -> dict[str, Any]:
        """Compatibility name matching the ForgeToolClient discovery vocabulary."""
        return self.get_context(tool_id)

    def invoke_query(
        self,
        endpoint_id: str,
        operation: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        registration = self._operation(endpoint_id, operation)
        if registration.spec["semantics"] != "query":
            raise ToolContractError(f"Tool {registration.spec['tool_id']!r} is not a Query")
        if registration.context.get("ready") is not True:
            raise CapabilityRuntimeError(
                str(registration.context.get("binding_error") or "ToolEndpoint is not ready")
            )
        handler = registration.endpoint
        invoke = getattr(handler, "invoke", None)
        if not callable(invoke):
            raise ToolContractError("Query ToolEndpoint does not expose invoke(arguments)")
        try:
            result = invoke(dict(arguments or {}))
        except Exception as exc:  # provider failures are runtime failures, never fake success
            raise CapabilityRuntimeError("Query ToolEndpoint provider failed") from exc
        if not isinstance(result, Mapping):
            raise ToolContractError("Query ToolEndpoint returned a non-object result")
        return dict(result)

    def start_action(
        self,
        tool_id: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        caller_id: str | None = None,
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        registration = self._registration(tool_id)
        if registration.spec["semantics"] not in {"action", "session"}:
            raise ToolContractError(f"Tool {tool_id!r} is not an Action or Session")
        if registration.context.get("ready") is not True:
            raise CapabilityRuntimeError(
                str(registration.context.get("binding_error") or "ToolEndpoint is not ready")
            )
        if caller_id is not None and (not isinstance(caller_id, str) or not caller_id.strip()):
            raise ToolContractError("caller_id must be a non-empty string when provided")
        if timeout_ms is not None and (
            isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) or timeout_ms < 1
        ):
            raise ToolContractError("timeout_ms must be a positive integer when provided")
        max_concurrency = registration.context.get("max_concurrency", 1)
        if isinstance(max_concurrency, bool) or not isinstance(max_concurrency, int) or max_concurrency < 1:
            raise ToolContractError("Tool context max_concurrency must be a positive integer")
        active = sum(
            item.tool_id == tool_id
            and item.status not in {"succeeded", "failed", "cancelled", "stopped", "unknown"}
            for item in self._invocations.values()
        )
        if active >= max_concurrency:
            raise CapabilityRuntimeError(f"Tool {tool_id!r} concurrency limit is exhausted")
        admit = getattr(registration.endpoint, "admit", None)
        if not callable(admit):
            raise ToolContractError("Action ToolEndpoint does not expose admit(arguments)")
        try:
            admission = admit(dict(arguments or {}))
        except Exception as exc:  # admission failures must fail closed
            raise CapabilityRuntimeError("Action ToolEndpoint admission failed") from exc
        if not isinstance(admission, ActionAdmission):
            raise ToolContractError("Action ToolEndpoint returned an invalid admission")
        if isinstance(admission.pending_polls, bool) or admission.pending_polls < 0:
            raise ToolContractError("Action admission pending_polls must be non-negative")
        invocation_id = f"invocation://{tool_id.replace('.', '-')}/{uuid4().hex[:16]}"
        attempt_id = f"attempt://{tool_id.replace('.', '-')}/{uuid4().hex[:16]}"
        invocation = Invocation(
            invocation_id=invocation_id,
            attempt_id=attempt_id,
            tool_id=tool_id,
            arguments=dict(arguments or {}),
            pending_polls=admission.pending_polls,
            terminal_result=dict(admission.terminal_result),
            caller_id=caller_id,
            timeout_ms=timeout_ms,
        )
        self._invocations[invocation_id] = invocation
        return {
            "invocation_id": invocation_id,
            "attempt_id": attempt_id,
            "phase": "accepted",
        }

    def invocation_status(self, invocation_id: str) -> dict[str, Any]:
        invocation = self._invocation(invocation_id)
        self._advance(invocation)
        return {
            "invocation_id": invocation.invocation_id,
            "attempt_id": invocation.attempt_id,
            "tool_id": invocation.tool_id,
            "caller_id": invocation.caller_id,
            "status": invocation.status,
            "cancel_requested": invocation.cancel_requested,
        }

    def invocation_result(self, invocation_id: str) -> dict[str, Any]:
        invocation = self._invocation(invocation_id)
        self._advance(invocation)
        result = dict(invocation.terminal_result)
        if invocation.status not in {"succeeded", "failed", "cancelled", "stopped", "unknown"}:
            return {
                "status": "pending",
                "invocation_id": invocation.invocation_id,
                "attempt_id": invocation.attempt_id,
            }
        return {
            "status": invocation.status,
            "invocation_id": invocation.invocation_id,
            "attempt_id": invocation.attempt_id,
            "result": result,
        }

    def cancel_invocation(self, invocation_id: str) -> dict[str, Any]:
        invocation = self._invocation(invocation_id)
        if invocation.status in {"succeeded", "failed", "cancelled", "stopped", "unknown"}:
            return {"accepted": False, "status": invocation.status}
        invocation.cancel_requested = True
        invocation.status = "cancel_requested"
        return {"accepted": True, "status": "cancel_requested"}

    def _advance(self, invocation: Invocation) -> None:
        if invocation.status in {"cancel_requested", "succeeded", "failed", "cancelled", "stopped", "unknown"}:
            return
        if invocation.pending_polls > 0:
            invocation.pending_polls -= 1
            invocation.status = "running"
            return
        terminal = invocation.terminal_result.get("status")
        invocation.status = terminal if terminal in {"succeeded", "failed", "cancelled", "stopped", "unknown"} else "unknown"

    def _registration(self, tool_id: str) -> EndpointRegistration:
        try:
            return self._tools[tool_id]
        except KeyError as exc:
            raise UnknownToolError(f"unknown ToolSpec: {tool_id}") from exc

    def _operation(self, endpoint_id: str, operation: str) -> EndpointRegistration:
        try:
            return self._operations[(endpoint_id, operation)]
        except KeyError as exc:
            raise UnknownToolError(f"unknown ToolEndpoint operation: {endpoint_id}/{operation}") from exc

    def _invocation(self, invocation_id: str) -> Invocation:
        try:
            return self._invocations[invocation_id]
        except KeyError as exc:
            raise UnknownToolError(f"unknown invocation: {invocation_id}") from exc


__all__ = [
    "CapabilityRuntime",
    "CapabilityRuntimeError",
    "DuplicateToolError",
    "EndpointRegistration",
    "Invocation",
    "ToolContractError",
    "UnknownToolError",
]
