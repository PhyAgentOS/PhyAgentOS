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


class DeferredAction:
    def __init__(self, runtime):
        self.runtime = runtime
        self.started_with = None

    def admit(self, arguments):
        def start(invocation_id, attempt_id):
            self.started_with = (invocation_id, attempt_id)
            assert invocation_id in self.runtime._invocations
            return ActionAdmission(
                terminal_result={
                    "status": "succeeded",
                    "invocation_id": invocation_id,
                    "attempt_id": attempt_id,
                }
            )

        return ActionAdmission(start=start)


class FailingDeferredAction:
    def admit(self, arguments):
        def start(invocation_id, attempt_id):
            raise RuntimeError("simulated provider start failure")

        return ActionAdmission(start=start)


class MalformedDeferredAction:
    def admit(self, arguments):
        return ActionAdmission(start=lambda invocation_id, attempt_id: {"status": "succeeded"})


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
async def test_deferred_action_starts_after_invocation_identity_is_allocated():
    runtime = CapabilityRuntime()
    action = DeferredAction(runtime)
    runtime.register_tool(ACTION, action)
    transport = CapabilityRuntimeTransport(runtime)
    async with ForgeToolClient("http://runtime", transport=transport) as client:
        accepted = await client.invoke_action("object.acquire", {})
        invocation_id = accepted["data"]["invocation_id"]
        assert action.started_with is not None
        assert action.started_with[0] == invocation_id
        result = await client.invocation_result(invocation_id)
        assert result["data"]["status"] == "succeeded"
        assert result["data"]["result"]["attempt_id"] == action.started_with[1]


@pytest.mark.asyncio
async def test_deferred_action_start_failure_is_terminal_failure_with_identity():
    runtime = CapabilityRuntime()
    runtime.register_tool(ACTION, FailingDeferredAction())
    transport = CapabilityRuntimeTransport(runtime)
    async with ForgeToolClient("http://runtime", transport=transport) as client:
        accepted = await client.invoke_action("object.acquire", {})
        invocation_id = accepted["data"]["invocation_id"]
        result = await client.invocation_result(invocation_id)
        assert result["data"]["status"] == "failed"
        assert result["data"]["result"]["failure_code"] == "action_start_failed"


@pytest.mark.asyncio
async def test_malformed_deferred_start_leaves_a_queryable_failed_invocation():
    runtime = CapabilityRuntime()
    runtime.register_tool(ACTION, MalformedDeferredAction())
    transport = CapabilityRuntimeTransport(runtime)
    async with ForgeToolClient("http://runtime", transport=transport) as client:
        with pytest.raises(Exception):
            await client.invoke_action("object.acquire", {})
        assert len(runtime._invocations) == 1
        invocation_id = next(iter(runtime._invocations))
        result = await client.invocation_result(invocation_id)
        assert result["data"]["status"] == "failed"
        assert result["data"]["result"]["failure_code"] == "invalid_action_start_result"


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
