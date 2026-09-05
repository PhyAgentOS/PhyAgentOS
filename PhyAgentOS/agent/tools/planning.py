"""Read-only AgentLoop tools for an active semantic planning dispatch."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PhyAgentOS.agent.planning_dispatch import AgentComposedDispatch
from PhyAgentOS.agent.tools.base import Tool
from PhyAgentOS.planning import AdmissionContext

if TYPE_CHECKING:
    from PhyAgentOS.forge.task import AgentTaskCoordinator


class ForgePlanReadyTool(Tool):
    """Expose ready semantic nodes without executing a Tool or changing state."""

    def __init__(self, dispatch: AgentComposedDispatch) -> None:
        self.dispatch = dispatch

    @property
    def name(self) -> str:
        return "forge_plan_ready"

    @property
    def description(self) -> str:
        return (
            "Read the ready semantic nodes and frozen planning Tool candidates for the "
            "active agent-composed PlanGraph. This performs no execution or motion."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    async def execute(self) -> str:
        return json.dumps(self.dispatch.describe(), ensure_ascii=False, separators=(",", ":"))


class ForgePlanActivateTool(Tool):
    """Attach a task's frozen graph to the AgentLoop admission bridge."""

    def __init__(
        self,
        coordinator: "AgentTaskCoordinator",
        setter: Callable[[AgentComposedDispatch | None], None],
        context_provider: Callable[[str], AdmissionContext] | None,
    ) -> None:
        self.coordinator = coordinator
        self.setter = setter
        self.context_provider = context_provider

    @property
    def name(self) -> str:
        return "forge_plan_activate"

    @property
    def description(self) -> str:
        return "Activate the current AgentTask PlanGraph using trusted runtime context for read-only ready-node and Tool admission checks."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "minLength": 1},
            },
            "required": ["task_id"],
            "additionalProperties": False,
        }

    async def execute(
        self,
        task_id: str,
    ) -> str:
        try:
            if self.context_provider is None:
                raise RuntimeError("trusted planning context provider is not configured")
            task = self.coordinator.get_task(task_id)
            dispatch = AgentComposedDispatch.from_task(
                task,
                context_provider=self.context_provider,
            )
            self.setter(dispatch)
            return json.dumps(dispatch.describe(), ensure_ascii=False, separators=(",", ":"))
        except Exception as exc:
            # Never leave a previous task's admission context active after a
            # failed activation attempt.
            self.setter(None)
            return json.dumps(
                {"ok": False, "error": {"type": "planning_activation", "message": str(exc)}, "motion_authorized": False},
                ensure_ascii=False,
                separators=(",", ":"),
            )


__all__ = ["ForgePlanActivateTool", "ForgePlanReadyTool"]
