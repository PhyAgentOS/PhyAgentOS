from __future__ import annotations

import pytest

from PhyAgentOS.forge.capability_runtime import (
    ActionAdmission,
    CapabilityRuntime,
    CapabilityRuntimeTransport,
)
from PhyAgentOS.forge.tool_client import ForgeToolClient

QUERY = {
    "tool_id": "scene.observe",
    "endpoint_id": "scene",
    "operation": "observe",
    "semantics": "query",
}
ACTION = {
    "tool_id": "object.acquire",
    "endpoint_id": "object",
    "operation": "acquire",
    "semantics": "action",
}
SESSION = {
    "tool_id": "workflow.session",
    "endpoint_id": "workflow",
    "operation": "run",
    "semantics": "session",
}


class Query:
    def invoke(self, arguments):
        return {"status": "available", "echo": arguments}


class Action:
    def __init__(self, pending_polls=1):
        self.pending_polls = pending_polls

    def admit(self, arguments):
        return ActionAdmission(
            pending_polls=self.pending_polls,
            terminal_result={"status": "succeeded", "arguments": dict(arguments)},
        )


@pytest.mark.asyncio
async def test_http_discovery_query_identity_and_action_lifecycle_are_no_motion():
    runtime = CapabilityRuntime()
    runtime.register_tool(QUERY, Query(), context={"ready": True, "motion_authorized": False})
    runtime.register_tool(ACTION, Action(pending_polls=1), context={"max_concurrency": 1, "motion_authorized": False})
    transport = CapabilityRuntimeTransport(runtime, gateway_identity="gateway-conformance")
    async with ForgeToolClient("http://runtime", transport=transport) as client:
        tools = await client.list_tools()
        assert tools["data"]["gateway_identity"] == "gateway-conformance"
        context = await client.get_tool_context("object.acquire")
        assert context["data"]["motion_authorized"] is False
        query = await client.invoke_query("scene", "observe", {"sensor": "front"})
        assert query["data"]["status"] == "available"
        accepted = await client.invoke_action("object.acquire", {"candidate": "c"}, caller_id="paos:t")
        invocation_id = accepted["data"]["invocation_id"]
        status = await client.invocation_status(invocation_id)
        assert status["data"]["caller_id"] == "paos:t"
        result = await client.invocation_result(invocation_id)
        assert result["data"]["status"] == "succeeded"
    assert all(request.method != "POST" or ":invoke" in request.url.path for request in transport.requests)


@pytest.mark.asyncio
async def test_timeout_unknown_recovery_does_not_post_again():
    now = [10.0]
    runtime = CapabilityRuntime(clock=lambda: now[0])
    runtime.register_tool(ACTION, Action(pending_polls=10))
    transport = CapabilityRuntimeTransport(runtime)
    async with ForgeToolClient("http://runtime", transport=transport) as client:
        accepted = await client.invoke_action("object.acquire", {}, timeout_ms=1000)
        invocation_id = accepted["data"]["invocation_id"]
        now[0] = 11.0
        result = await client.invocation_result(invocation_id)
        assert result["data"]["status"] == "unknown"
        post_count = len([request for request in transport.requests if request.method == "POST"])
        again = await client.invocation_result(invocation_id)
        assert again["data"]["status"] == "unknown"
        assert len([request for request in transport.requests if request.method == "POST"]) == post_count
    invoke_posts = [request for request in transport.requests if request.method == "POST" and request.url.path.endswith(":invoke")]
    assert len(invoke_posts) == 1


@pytest.mark.asyncio
async def test_cancel_and_session_stop_reconcile_to_terminal_states():
    runtime = CapabilityRuntime()
    runtime.register_tool(ACTION, Action(pending_polls=3))
    runtime.register_tool(SESSION, Action(pending_polls=3))
    transport = CapabilityRuntimeTransport(runtime)
    async with ForgeToolClient("http://runtime", transport=transport) as client:
        action = await client.invoke_action("object.acquire", {})
        action_id = action["data"]["invocation_id"]
        await client.cancel_invocation(action_id)
        assert (await client.invocation_result(action_id))["data"]["status"] == "cancelled"
        session = await client.start_session("workflow.session", {})
        session_id = session["data"]["invocation_id"]
        await client.stop_session(session_id)
        assert (await client.invocation_result(session_id))["data"]["status"] == "stopped"


@pytest.mark.asyncio
async def test_malformed_invoke_payload_is_a_client_error_and_does_not_admit():
    runtime = CapabilityRuntime()
    runtime.register_tool(ACTION, Action())
    transport = CapabilityRuntimeTransport(runtime)
    async with ForgeToolClient("http://runtime", transport=transport) as client:
        request = client._client.build_request("POST", "/tools/object.acquire:invoke", content=b"{")
        response = await client._client.send(request)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_json"
    assert not runtime._invocations
