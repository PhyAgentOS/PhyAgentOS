"""Generic remote target proxy backed by the runtime RPC protocol."""

from __future__ import annotations

from typing import Any

from PhyAgentOS.runtime.communication.target_ws_client import TargetWSClient
from PhyAgentOS.runtime.targets.base import BaseRolloutTarget


class RemoteTargetProxy(BaseRolloutTarget):
    """Expose a remote TargetRuntime through the local rollout target interface."""

    def __init__(self, client: TargetWSClient, *, config: dict[str, Any] | None = None):
        self.client = client
        self.config = dict(config or {})
        self._session_id: str | None = None
        self._skillruntime_id: str | None = None

    def build(self) -> None:
        self.client.connect()

    def describe(self) -> dict[str, Any]:
        return self.client.call("target.describe", {})

    def configure_session(self, session_ctx: dict[str, Any]) -> dict[str, Any]:
        self._remember_session(session_ctx)
        return self.client.call(
            "target.configure_session",
            session_ctx,
            session_id=self._session_id,
            skillruntime_id=self._skillruntime_id,
        )

    def start_session(self, session_ctx: dict[str, Any]) -> dict[str, Any]:
        self._remember_session(session_ctx)
        return self.client.call(
            "target.start_session",
            session_ctx,
            session_id=self._session_id,
            skillruntime_id=self._skillruntime_id,
        )

    def reset(self, session_ctx: dict[str, Any]) -> dict[str, Any]:
        self._remember_session(session_ctx)
        return self.client.call(
            "target.reset",
            session_ctx,
            session_id=self._session_id,
            skillruntime_id=self._skillruntime_id,
        )

    def observe(self) -> dict[str, Any]:
        return self.client.call(
            "target.observe",
            {},
            session_id=self._session_id,
            skillruntime_id=self._skillruntime_id,
        )

    def observe_for_environment(self, session_ctx: dict[str, Any]) -> dict[str, Any]:
        self._remember_session(session_ctx)
        return self.client.call(
            "target.observe",
            {"environment_refresh": True},
            session_id=self._session_id,
            skillruntime_id=self._skillruntime_id,
        )

    def action_chunk(self, executable_action_chunk: dict[str, Any]) -> dict[str, Any]:
        return self.client.call(
            "target.action_chunk",
            executable_action_chunk,
            session_id=self._session_id,
            skillruntime_id=self._skillruntime_id,
        )

    def execution_status(self) -> dict[str, Any]:
        return self.client.call(
            "target.execution_status",
            {},
            session_id=self._session_id,
            skillruntime_id=self._skillruntime_id,
        )

    def describe_target_tools(self) -> dict[str, Any]:
        return self.client.call(
            "agent_tool.describe",
            {},
            session_id=self._session_id,
            skillruntime_id=self._skillruntime_id,
        )

    def call_target_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.client.call(
            "agent_tool.call",
            {"tool_name": tool_name, "arguments": arguments},
            session_id=self._session_id,
            skillruntime_id=self._skillruntime_id,
        )

    def run_benchmark(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.client.call(
            "target.benchmark",
            payload,
            session_id=self._session_id,
            skillruntime_id=self._skillruntime_id,
            expected_response_type="target.benchmark",
        )

    def cancel(self, reason: str) -> None:
        self.client.call(
            "target.cancel",
            {"reason": reason},
            session_id=self._session_id,
            skillruntime_id=self._skillruntime_id,
        )

    def close(self) -> None:
        try:
            if self.client.connected:
                self.client.call(
                    "target.close",
                    {},
                    session_id=self._session_id,
                    skillruntime_id=self._skillruntime_id,
                )
        finally:
            self.client.close()

    def _remember_session(self, session_ctx: dict[str, Any]) -> None:
        self._session_id = session_ctx.get("session_id", self._session_id)
        skillruntime_ref = session_ctx.get("skillruntime_ref")
        if isinstance(skillruntime_ref, str) and skillruntime_ref.startswith("skillruntime://"):
            self._skillruntime_id = skillruntime_ref.removeprefix("skillruntime://")
