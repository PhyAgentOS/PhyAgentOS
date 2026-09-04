from __future__ import annotations

import pytest
from PhyAgentOS.forge.capability_runtime import (
    ActionAdmission,
    CapabilityRuntime,
    CapabilityRuntimeError,
    DuplicateToolError,
    ToolContractError,
)

QUERY_SPEC = {
    "tool_id": "scene.observe",
    "endpoint_id": "scene_observation",
    "operation": "observe",
    "semantics": "query",
    "description": "Return measured provider-neutral observation artifacts.",
}

ACTION_SPEC = {
    "tool_id": "object.acquire",
    "endpoint_id": "object_acquisition",
    "operation": "acquire",
    "semantics": "action",
    "description": "Admit one bounded acquisition action.",
}

SESSION_SPEC = {
    "tool_id": "workflow.session",
    "endpoint_id": "workflow",
    "operation": "run",
    "semantics": "session",
    "description": "Run one bounded provider-neutral workflow session.",
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


def test_discovery_context_and_query_dispatch_are_provider_neutral():
    runtime = CapabilityRuntime()
    runtime.register_tool(QUERY_SPEC, Query(), context={"sensor": "external"})

    assert runtime.list_tools()["tools"][0]["tool_id"] == "scene.observe"
    assert runtime.get_context("scene.observe")["ready"] is True
    assert runtime.invoke_query("scene_observation", "observe", {"sensor_ref": "front"}) == {
        "status": "available",
        "echo": {"sensor_ref": "front"},
    }


def test_registration_rejects_duplicate_and_provider_specific_specs():
    runtime = CapabilityRuntime()
    runtime.register_tool(QUERY_SPEC, Query())
    with pytest.raises(DuplicateToolError):
        runtime.register_tool(QUERY_SPEC, Query())
    with pytest.raises(ToolContractError, match="provider-specific"):
        runtime.register_tool(
            {**ACTION_SPEC, "description": "YOLO detector output"}, Action()
        )


def test_query_requires_ready_context_and_action_enforces_concurrency():
    runtime = CapabilityRuntime()
    runtime.register_tool(
        QUERY_SPEC,
        Query(),
        context={"ready": False, "binding_error": "sensor unavailable"},
    )
    with pytest.raises(CapabilityRuntimeError, match="sensor unavailable"):
        runtime.invoke_query("scene_observation", "observe", {})

    runtime = CapabilityRuntime()
    runtime.register_tool(ACTION_SPEC, Action(pending_polls=2), context={"max_concurrency": 1})
    admitted = runtime.start_action(
        "object.acquire",
        {"candidate_ref": "candidate://s/c"},
        caller_id="paos:test",
        timeout_ms=5000,
    )
    assert admitted["invocation_id"].startswith("invocation://object-acquire/")
    assert runtime.invocation_status(admitted["invocation_id"])["caller_id"] == "paos:test"
    with pytest.raises(CapabilityRuntimeError, match="concurrency"):
        runtime.start_action("object.acquire", {})


def test_action_lifecycle_is_explicit_and_cancel_does_not_claim_stop():
    runtime = CapabilityRuntime()
    runtime.register_tool(ACTION_SPEC, Action(pending_polls=1))
    admitted = runtime.start_action("object.acquire", {})
    invocation_id = admitted["invocation_id"]

    assert runtime.invocation_status(invocation_id)["status"] == "running"
    assert runtime.invocation_result(invocation_id)["status"] == "succeeded"

    runtime = CapabilityRuntime()
    runtime.register_tool(ACTION_SPEC, Action(pending_polls=2))
    invocation_id = runtime.start_action("object.acquire", {})["invocation_id"]
    cancelled = runtime.cancel_invocation(invocation_id)
    assert cancelled == {"accepted": True, "status": "cancel_requested"}
    status = runtime.invocation_status(invocation_id)
    assert status["status"] == "cancelled"
    assert status["cancel_requested"] is True
    assert runtime.invocation_result(invocation_id)["status"] == "cancelled"


def test_timeout_reconciles_to_unknown_and_does_not_report_success():
    now = [100.0]
    runtime = CapabilityRuntime(clock=lambda: now[0])
    runtime.register_tool(ACTION_SPEC, Action(pending_polls=10))
    invocation_id = runtime.start_action("object.acquire", {}, timeout_ms=1000)["invocation_id"]
    now[0] = 101.0
    assert runtime.invocation_status(invocation_id)["status"] == "unknown"
    result = runtime.invocation_result(invocation_id)
    assert result["status"] == "unknown"
    assert result["result"]["failure_code"] == "timeout"


def test_session_stop_reconciles_to_stopped_and_sessions_reject_deadlines():
    runtime = CapabilityRuntime()
    runtime.register_tool(SESSION_SPEC, Action(pending_polls=2))
    with pytest.raises(ToolContractError, match="Session invocations do not accept timeout_ms"):
        runtime.start_action("workflow.session", {}, timeout_ms=1000)
    invocation_id = runtime.start_action("workflow.session", {})["invocation_id"]
    stopped = runtime.stop_invocation(invocation_id)
    assert stopped == {"accepted": True, "status": "stop_requested"}
    assert runtime.invocation_status(invocation_id)["status"] == "stopped"
    assert runtime.invocation_result(invocation_id)["status"] == "stopped"


def test_action_admission_must_return_generic_admission():
    class InvalidAction:
        def admit(self, arguments):
            return {"status": "succeeded"}

    runtime = CapabilityRuntime()
    runtime.register_tool(ACTION_SPEC, InvalidAction())
    with pytest.raises(ToolContractError, match="invalid admission"):
        runtime.start_action("object.acquire", {})
