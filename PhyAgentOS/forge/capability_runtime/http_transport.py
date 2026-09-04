"""Provider-neutral HTTP transport for the Forge capability runtime.

This adapter exposes the Gateway Tool API over an in-process ``httpx``
transport.  It is intended for replay, conformance, and no-motion integration;
it does not start Dora or execute a physical action.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import unquote

import httpx

from .runtime import CapabilityRuntime, CapabilityRuntimeError, UnknownToolError


class CapabilityRuntimeTransport(httpx.AsyncBaseTransport):
    """Expose one :class:`CapabilityRuntime` through Gateway HTTP routes."""

    def __init__(self, runtime: CapabilityRuntime, *, gateway_identity: str = "gateway-runtime") -> None:
        if not isinstance(gateway_identity, str) or not gateway_identity.strip():
            raise ValueError("gateway_identity must be a non-empty string")
        self.runtime = runtime
        self.gateway_identity = gateway_identity
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        try:
            if request.method == "GET" and path == "/tools":
                return self._ok({"gateway_identity": self.gateway_identity, **self.runtime.list_tools()})
            if request.method == "GET" and path.startswith("/tools/") and path.endswith("/context"):
                tool_id = unquote(path[len("/tools/") : -len("/context")])
                return self._ok(self.runtime.get_tool_context(tool_id))
            if request.method == "GET" and path.startswith("/tools/"):
                return self._ok(self.runtime.get_tool(unquote(path[len("/tools/") :])))
            if request.method == "POST" and path.startswith("/tools/") and path.endswith(":invoke"):
                return self._invoke_tool(request)
            if request.method == "GET" and path.startswith("/invocations/"):
                return self._read_invocation(request)
            if request.method == "POST" and path.startswith("/invocations/") and path.endswith("/cancel"):
                invocation_id = unquote(path[len("/invocations/") : -len("/cancel")])
                return self._ok(self.runtime.cancel_invocation(invocation_id))
            if request.method == "POST" and path.startswith("/invocations/") and path.endswith("/stop"):
                invocation_id = unquote(path[len("/invocations/") : -len("/stop")])
                return self._ok(self.runtime.stop_invocation(invocation_id))
            return self._error(404, "not_found", "Gateway route not found")
        except UnknownToolError as exc:
            return self._error(404, "not_found", str(exc))
        except (CapabilityRuntimeError, ValueError, TypeError) as exc:
            return self._error(409, "runtime_error", str(exc))

    def _invoke_tool(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        try:
            raw = json.loads(request.content or b"{}")
        except json.JSONDecodeError:
            return self._error(400, "invalid_json", "request body must be JSON")
        if not isinstance(raw, dict) or not isinstance(raw.get("arguments", {}), dict):
            return self._error(400, "invalid_json", "arguments must be an object")
        arguments = raw.get("arguments", {})
        caller_id = raw.get("caller_id")
        timeout_ms = raw.get("timeout_ms")
        if path.endswith(":invoke") and path.count("/") == 3:
            endpoint_id, operation = unquote(path[len("/tools/") : -len(":invoke")]).split("/", 1)
            result = self.runtime.invoke_query(endpoint_id, operation, arguments)
            return self._ok(result)
        tool_id = unquote(path[len("/tools/") : -len(":invoke")])
        accepted = self.runtime.start_action(
            tool_id, arguments, caller_id=caller_id, timeout_ms=timeout_ms
        )
        return httpx.Response(202, json={"ok": True, "data": accepted})

    def _read_invocation(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        is_result = path.endswith("/result")
        suffix = "/result" if is_result else ""
        invocation_id = unquote(path[len("/invocations/") : -len(suffix) if suffix else None])
        data = self.runtime.invocation_result(invocation_id) if is_result else self.runtime.invocation_status(invocation_id)
        status = 202 if is_result and data.get("status") == "pending" else 200
        return httpx.Response(status, json={"ok": True, "data": data})

    @staticmethod
    def _ok(data: dict[str, Any]) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "data": data})

    @staticmethod
    def _error(status: int, code: str, message: str) -> httpx.Response:
        return httpx.Response(status, json={"ok": False, "error": {"code": code, "message": message}})


__all__ = ["CapabilityRuntimeTransport"]
