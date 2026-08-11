"""Command-driven builtin skill runtime for Isaac Sim targets."""

from __future__ import annotations

import time
from typing import Any

from PhyAgentOS.runtime.errors import AdapterError
from PhyAgentOS.runtime.schemas import AdapterPlan
from PhyAgentOS.runtime.sessions.models import SkillContext, SkillRuntimeResult
from PhyAgentOS.runtime.skillruntime.builtin.base import BuiltinSkillRuntime


class CommandSimSkillRuntime(BuiltinSkillRuntime):
    """Execute language/command/control steps via target agent tools (no policy)."""

    def __init__(self) -> None:
        self._snapshot: dict[str, Any] = {}

    def start(self, skill_ctx: SkillContext) -> None:
        self._snapshot = {"session_id": skill_ctx.session.session_id, "started": True}

    def cancel(self, skill_ctx: SkillContext, reason: str) -> None:
        self._snapshot = {**self._snapshot, "cancelled": True, "cancel_reason": reason}

    def snapshot(self, skill_ctx: SkillContext) -> dict:
        return dict(self._snapshot)

    def run_builtin_loop(
        self,
        skill_ctx: SkillContext,
        target_handle,
        adapter_plan: AdapterPlan,
    ) -> SkillRuntimeResult:
        del adapter_plan
        plan = self._resolve_plan(skill_ctx)
        if not plan:
            raise AdapterError(
                "command session requires execution.steps, execution.timeline, or task_description"
            )

        total_reward = 0.0
        last_message = ""
        plan_start = time.monotonic()

        for step_idx, step_def in enumerate(plan):
            at_s = step_def.get("at_s", step_def.get("t"))
            if at_s is not None:
                wait_s = float(at_s) - (time.monotonic() - plan_start)
                if wait_s > 0:
                    time.sleep(wait_s)

            result = target_handle.call_target_tool("execute_step", {"step": step_def})
            tool_result = dict(result.get("result") or result)
            total_reward += float(tool_result.get("reward", 0.0))
            last_message = str(tool_result.get("message") or tool_result.get("info", {}).get("message", ""))
            success = bool(tool_result.get("success", False))
            self._snapshot = {
                "session_id": skill_ctx.session.session_id,
                "step_index": step_idx,
                "last_message": last_message,
                "success": success,
            }

            if not success:
                return SkillRuntimeResult(
                    status="failed",
                    success=False,
                    error_code="COMMAND_STEP",
                    error_message=last_message or f"entry {step_idx + 1} failed",
                    metadata={"step_idx": step_idx, "step": step_def, "return_value": total_reward},
                )

        return SkillRuntimeResult(
            status="succeeded",
            success=True,
            metadata={"message": last_message, "return_value": total_reward, "num_steps": len(plan)},
        )

    @staticmethod
    def _resolve_plan(skill_ctx: SkillContext) -> list[dict[str, Any]]:
        execution = skill_ctx.session.execution
        timeline = getattr(execution, "timeline", None)
        if isinstance(timeline, list) and timeline:
            return [dict(entry) for entry in timeline]
        steps = getattr(execution, "steps", None)
        if isinstance(steps, list) and steps:
            return [dict(entry) for entry in steps]
        text = str(skill_ctx.session.task_description or "").strip()
        if text:
            return [{"text": text}]
        return []
