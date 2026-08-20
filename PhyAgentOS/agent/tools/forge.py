"""Agent tools for the single Forge Gateway execution path."""

from __future__ import annotations

import json
from typing import Any

from PhyAgentOS.agent.tools.base import Tool
from PhyAgentOS.forge.orchestrator import ForgeSessionOrchestrator
from PhyAgentOS.verification.contracts import ForgeTaskRequest, TaskVerificationContract


def _json(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json", exclude_none=True)
    return json.dumps(value, ensure_ascii=False)


class ForgeExecuteTaskTool(Tool):
    def __init__(self, orchestrator: ForgeSessionOrchestrator) -> None:
        self.orchestrator = orchestrator
        self.channel = "cli"
        self.chat_id = "direct"
        self.session_key: str | None = None

    def set_context(
        self, channel: str, chat_id: str, session_key: str | None = None
    ) -> None:
        self.channel = channel
        self.chat_id = chat_id
        self.session_key = session_key or f"{channel}:{chat_id}"

    @property
    def name(self) -> str:
        return "forge_execute_task"

    @property
    def description(self) -> str:
        return (
            "Submit one high-level action to the configured Forge Gateway. The call returns "
            "immediately; execution, evidence capture, semantic verification, and recovery "
            "continue asynchronously. Gateway succeeded is not task success."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_description": {"type": "string", "minLength": 1},
                "action_type": {"type": "string", "minLength": 1},
                "inputs": {"type": "object"},
                "verification": _verification_schema(),
                "execution_timeout_s": {"type": "number", "minimum": 0.1},
            },
            "required": ["task_description", "action_type", "inputs", "verification"],
            "additionalProperties": False,
        }

    async def execute(
        self,
        task_description: str,
        action_type: str,
        inputs: dict[str, Any],
        verification: dict[str, Any],
        execution_timeout_s: float | None = None,
    ) -> str:
        request = ForgeTaskRequest(
            task_description=task_description,
            action_type=action_type,
            inputs=inputs,
            verification=TaskVerificationContract.model_validate(verification),
            execution_timeout_s=(
                execution_timeout_s
                if execution_timeout_s is not None
                else self.orchestrator.config.execution_timeout_s
            ),
        )
        record = await self.orchestrator.submit(
            request,
            channel=self.channel,
            chat_id=self.chat_id,
            session_key=self.session_key,
        )
        return _json(
            {
                "ok": True,
                "session_id": record.session_id,
                "command_id": record.command_id,
                "status": record.status.value,
                "message": "Forge task accepted; completion will arrive as a system event.",
            }
        )


class ForgeGetSessionTool(Tool):
    def __init__(self, orchestrator: ForgeSessionOrchestrator) -> None:
        self.orchestrator = orchestrator

    @property
    def name(self) -> str:
        return "forge_get_session"

    @property
    def description(self) -> str:
        return "Read the persisted Forge execution, evidence, verification, and recovery state."

    @property
    def parameters(self) -> dict[str, Any]:
        return _session_id_schema()

    async def execute(self, session_id: str) -> str:
        return _json(self.orchestrator.get_session(session_id))


class ForgeCancelSessionTool(Tool):
    def __init__(self, orchestrator: ForgeSessionOrchestrator) -> None:
        self.orchestrator = orchestrator

    @property
    def name(self) -> str:
        return "forge_cancel_session"

    @property
    def description(self) -> str:
        return "Cancel a non-terminal Forge task and request Gateway cancellation when dispatched."

    @property
    def parameters(self) -> dict[str, Any]:
        schema = _session_id_schema()
        schema["properties"]["reason"] = {"type": "string", "minLength": 1}
        return schema

    async def execute(self, session_id: str, reason: str = "agent_requested") -> str:
        return _json(await self.orchestrator.cancel_session(session_id, reason=reason))


class ForgeGetContextTool(Tool):
    def __init__(self, orchestrator: ForgeSessionOrchestrator) -> None:
        self.orchestrator = orchestrator

    @property
    def name(self) -> str:
        return "forge_get_context"

    @property
    def description(self) -> str:
        return "Read live Forge capabilities, readiness, status, and runtime context."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    async def execute(self) -> str:
        return _json(await self.orchestrator.get_context())


class ForgeResetTool(Tool):
    def __init__(self, orchestrator: ForgeSessionOrchestrator) -> None:
        self.orchestrator = orchestrator

    @property
    def name(self) -> str:
        return "forge_reset"

    @property
    def description(self) -> str:
        return "Reset Forge only when no PAOS Forge task lineage is active."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"inputs": {"type": "object"}},
            "additionalProperties": False,
        }

    async def execute(self, inputs: dict[str, Any] | None = None) -> str:
        return _json(await self.orchestrator.reset(inputs))


class VerifyForgeSessionTool(Tool):
    def __init__(self, orchestrator: ForgeSessionOrchestrator) -> None:
        self.orchestrator = orchestrator

    @property
    def name(self) -> str:
        return "verify_forge_session"

    @property
    def description(self) -> str:
        return (
            "Review a terminal Forge session using its immutable Execution Record and retained "
            "Evidence Bundle. A review never changes the session terminal status."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return _session_id_schema()

    async def execute(self, session_id: str) -> str:
        return _json(await self.orchestrator.review(session_id))


class CreateReplannedForgeSessionTool(Tool):
    def __init__(self, orchestrator: ForgeSessionOrchestrator) -> None:
        self.orchestrator = orchestrator

    @property
    def name(self) -> str:
        return "create_replanned_forge_session"

    @property
    def description(self) -> str:
        return (
            "Atomically create one fresh Forge child for a parent awaiting replan. The Planner "
            "must provide a newly planned action and cannot provide or reuse command IDs."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "parent_session_id": {"type": "string", "minLength": 1},
                "task_description": {"type": "string", "minLength": 1},
                "action_type": {"type": "string", "minLength": 1},
                "inputs": {"type": "object"},
                "execution_timeout_s": {"type": "number", "minimum": 0.1},
            },
            "required": [
                "parent_session_id",
                "task_description",
                "action_type",
                "inputs",
            ],
            "additionalProperties": False,
        }

    async def execute(
        self,
        parent_session_id: str,
        task_description: str,
        action_type: str,
        inputs: dict[str, Any],
        execution_timeout_s: float | None = None,
    ) -> str:
        child = await self.orchestrator.create_replanned(
            parent_session_id,
            task_description=task_description,
            action_type=action_type,
            inputs=inputs,
            execution_timeout_s=execution_timeout_s,
        )
        return _json(
            {
                "ok": True,
                "parent_session_id": parent_session_id,
                "child_session_id": child.session_id,
                "command_id": child.command_id,
                "status": child.status.value,
            }
        )


def _session_id_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"session_id": {"type": "string", "minLength": 1}},
        "required": ["session_id"],
        "additionalProperties": False,
    }


def _verification_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["off", "audit", "enforce", "recovery"]},
            "goal": {"type": "string"},
            "success_criteria": {"type": "array", "items": {"type": "string"}},
            "constraints": {"type": "array", "items": {"type": "string"}},
            "evidence_policy": {
                "type": "object",
                "properties": {
                    "profile": {"type": "string"},
                    "required_kinds": {"type": "array", "items": {"type": "string"}},
                    "required_sources": {"type": "array", "items": {"type": "string"}},
                    "minimum_association": {
                        "type": "string",
                        "enum": ["best_effort", "authoritative"],
                    },
                },
                "additionalProperties": False,
            },
        },
        "required": ["mode"],
        "additionalProperties": False,
    }
