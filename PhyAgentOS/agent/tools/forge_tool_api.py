"""Agent Tool wrappers for the Forge Gateway Tool API."""

from __future__ import annotations

import asyncio
import json
from collections.abc import MutableSet
from typing import Any, Awaitable, Callable

from PhyAgentOS.agent.tools.base import Tool
from PhyAgentOS.forge.tool_client import (
    ForgeToolAPIError,
    ForgeToolAPITimeoutError,
    ForgeToolClient,
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


async def _call(operation: Callable[[], Awaitable[dict[str, Any]]]) -> str:
    try:
        return _json(await operation())
    except ForgeToolAPIError as exc:
        error: dict[str, Any] = {
            "type": (
                "timeout" if isinstance(exc, ForgeToolAPITimeoutError) else "gateway_tool_api"
            ),
            "message": str(exc),
        }
        if exc.status_code is not None:
            error["status_code"] = exc.status_code
        if exc.error_code is not None:
            error["code"] = exc.error_code
        if exc.retryable is not None:
            error["retryable"] = exc.retryable
        if isinstance(exc, ForgeToolAPITimeoutError):
            error["remote_state"] = "unknown"
            error["stopped"] = False
        return _json({"ok": False, "error": error})


class ForgeToolContextTool(Tool):
    def __init__(self, client: ForgeToolClient) -> None:
        self.client = client

    @property
    def name(self) -> str:
        return "forge_tool_context"

    @property
    def description(self) -> str:
        return (
            "Read a configured Forge Tool's full input/output schema together with live binding, "
            "readiness, endpoint status, and robot frame context before invoking it."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return _single_string_schema("tool_id")

    async def execute(self, tool_id: str) -> str:
        return await _call(lambda: self._describe(tool_id))

    async def _describe(self, tool_id: str) -> dict[str, Any]:
        spec, context = await asyncio.gather(
            self.client.get_tool(tool_id),
            self.client.get_tool_context(tool_id),
        )
        return {
            "ok": True,
            "data": {
                "tool": spec["data"],
                "context": context["data"],
            },
        }


class ForgeToolQueryTool(Tool):
    def __init__(self, client: ForgeToolClient) -> None:
        self.client = client

    @property
    def name(self) -> str:
        return "forge_tool_query"

    @property
    def description(self) -> str:
        return (
            "Invoke a configured synchronous Forge Query by stable tool_id and return its "
            "terminal response."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return _invoke_schema("tool_id", include_timeout=True, include_operation=False)

    async def execute(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        caller_id: str | None = None,
        timeout_ms: int | None = None,
    ) -> str:
        return await _call(
            lambda: self.client.invoke_query_tool(
                tool_id,
                arguments,
                caller_id=caller_id,
                timeout_ms=timeout_ms,
            )
        )


class ForgeToolStartActionTool(Tool):
    def __init__(
        self,
        client: ForgeToolClient,
        invocation_ids: MutableSet[str] | None = None,
    ) -> None:
        self.client = client
        self.invocation_ids = invocation_ids if invocation_ids is not None else set()

    @property
    def name(self) -> str:
        return "forge_tool_start_action"

    @property
    def description(self) -> str:
        return (
            "Start an asynchronous Forge Action. Acceptance does not mean completion; use the "
            "returned invocation_id with status and result tools."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return _invoke_schema("tool_id", include_timeout=True, include_operation=False)

    async def execute(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        caller_id: str | None = None,
        timeout_ms: int | None = None,
    ) -> str:
        try:
            response = await self.client.invoke_action(
                tool_id,
                arguments,
                caller_id=caller_id,
                timeout_ms=timeout_ms,
            )
            data = response.get("data")
            invocation_id = data.get("invocation_id") if isinstance(data, dict) else None
            if not isinstance(invocation_id, str) or not invocation_id:
                raise ForgeToolAPIError(
                    "Forge Gateway Action response omitted invocation_id",
                    payload=response,
                )
            self.invocation_ids.add(invocation_id)
            return _json(response)
        except ForgeToolAPIError as exc:
            return await _call(_raise(exc))


class ForgeToolActionStatusTool(Tool):
    def __init__(
        self,
        client: ForgeToolClient,
        invocation_ids: MutableSet[str] | None = None,
    ) -> None:
        self.client = client
        self.invocation_ids = invocation_ids if invocation_ids is not None else set()

    @property
    def name(self) -> str:
        return "forge_tool_action_status"

    @property
    def description(self) -> str:
        return (
            "Read an Action invocation phase. The terminal phase unknown means execution outcome "
            "cannot be proven and must not be treated as stopped."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return _single_string_schema("invocation_id")

    async def execute(self, invocation_id: str) -> str:
        return await self._execute(invocation_id)

    async def _execute(self, invocation_id: str) -> str:
        try:
            response = await self.client.invocation_status(invocation_id)
            if _is_terminal(response):
                self.invocation_ids.discard(invocation_id)
            return _json(response)
        except ForgeToolAPIError as exc:
            return await _call(_raise(exc))


class ForgeToolActionResultTool(Tool):
    def __init__(
        self,
        client: ForgeToolClient,
        invocation_ids: MutableSet[str] | None = None,
    ) -> None:
        self.client = client
        self.invocation_ids = invocation_ids if invocation_ids is not None else set()

    @property
    def name(self) -> str:
        return "forge_tool_action_result"

    @property
    def description(self) -> str:
        return (
            "Read an Action result. A pending response is non-terminal; unknown is not evidence "
            "that physical execution stopped."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return _single_string_schema("invocation_id")

    async def execute(self, invocation_id: str) -> str:
        return await self._execute(invocation_id)

    async def _execute(self, invocation_id: str) -> str:
        try:
            response = await self.client.invocation_result(invocation_id)
            if _is_terminal(response):
                self.invocation_ids.discard(invocation_id)
            return _json(response)
        except ForgeToolAPIError as exc:
            return await _call(_raise(exc))


class ForgeToolCancelActionTool(Tool):
    def __init__(self, client: ForgeToolClient) -> None:
        self.client = client

    @property
    def name(self) -> str:
        return "forge_tool_cancel_action"

    @property
    def description(self) -> str:
        return (
            "Request cancellation of an Action. requested or accepted only acknowledges control "
            "delivery; check status/result for the execution outcome."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return _single_string_schema("invocation_id")

    async def execute(self, invocation_id: str) -> str:
        return await _call(lambda: self.client.cancel_invocation(invocation_id))


def build_forge_tool_api_tools(
    client: ForgeToolClient,
    *,
    invocation_ids: MutableSet[str] | None = None,
) -> list[Tool]:
    """Build the six Tool API wrappers with shared local Action tracking."""
    tracked = invocation_ids if invocation_ids is not None else set()
    return [
        ForgeToolContextTool(client),
        ForgeToolQueryTool(client),
        ForgeToolStartActionTool(client, tracked),
        ForgeToolActionStatusTool(client, tracked),
        ForgeToolActionResultTool(client, tracked),
        ForgeToolCancelActionTool(client),
    ]


def _single_string_schema(name: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {name: {"type": "string", "minLength": 1}},
        "required": [name],
        "additionalProperties": False,
    }


def _invoke_schema(
    identity_name: str,
    *,
    include_timeout: bool,
    include_operation: bool = True,
) -> dict[str, Any]:
    properties: dict[str, Any] = {
        identity_name: {"type": "string", "minLength": 1},
        "arguments": {"type": "object"},
        "caller_id": {"type": "string", "minLength": 1},
    }
    required = [identity_name, "arguments"]
    if include_operation:
        properties["operation"] = {"type": "string", "minLength": 1}
        required.insert(1, "operation")
    if include_timeout:
        properties["timeout_ms"] = {"type": "integer", "minimum": 1}
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _raise(exc: ForgeToolAPIError) -> Callable[[], Awaitable[dict[str, Any]]]:
    async def raiser() -> dict[str, Any]:
        raise exc

    return raiser


def _is_terminal(response: dict[str, Any]) -> bool:
    data = response.get("data")
    if not isinstance(data, dict):
        return False
    terminal = {
        "completed",
        "succeeded",
        "failed",
        "cancelled",
        "canceled",
        "stopped",
    }
    if any(
        isinstance(data.get(field), str)
        and data[field].lower() in terminal
        for field in ("phase", "status", "state")
    ):
        return True
    result = data.get("result")
    return (
        data.get("status") == "available"
        and isinstance(result, dict)
        and isinstance(result.get("status"), str)
        and result["status"].lower() in terminal
    )


__all__ = [
    "ForgeToolActionResultTool",
    "ForgeToolActionStatusTool",
    "ForgeToolCancelActionTool",
    "ForgeToolContextTool",
    "ForgeToolQueryTool",
    "ForgeToolStartActionTool",
    "build_forge_tool_api_tools",
]
