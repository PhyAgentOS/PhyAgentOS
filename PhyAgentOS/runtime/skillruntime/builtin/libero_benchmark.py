"""Target-native LIBERO benchmark skill runtime."""

from __future__ import annotations

from typing import Any

from PhyAgentOS.runtime.schemas import AdapterPlan
from PhyAgentOS.runtime.sessions.models import SkillContext, SkillRuntimeResult
from PhyAgentOS.runtime.skillruntime.builtin.base import BuiltinSkillRuntime
from PhyAgentOS.runtime.watchdog.errors import AdapterError


class LiberoBenchmarkSkillRuntime(BuiltinSkillRuntime):
    """Run a complete LIBERO benchmark through the target runtime."""

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
        payload = _benchmark_payload(skill_ctx)
        result = target_handle.run_benchmark(payload)
        episodes = list(result.get("episodes") or [])
        total = int(result.get("total_episodes") or len(episodes))
        successes = int(result.get("successes") or sum(1 for episode in episodes if episode.get("success")))
        status = str(result.get("status") or ("succeeded" if total else "failed"))
        success_rate = float(result.get("success_rate") or (successes / total if total else 0.0))
        self._snapshot = {
            "session_id": skill_ctx.session.session_id,
            "status": status,
            "successes": successes,
            "total_episodes": total,
            "success_rate": success_rate,
        }
        return SkillRuntimeResult(
            status=status if status in {"succeeded", "failed", "timed_out", "cancelled"} else "failed",
            success=bool(total and status == "succeeded"),
            final_status={
                "target_step_index": int(result.get("num_steps") or 0),
                "executed_steps": int(result.get("num_steps") or 0),
                "success": bool(total and status == "succeeded"),
                "done": True,
                "reward": float(successes),
                "benchmark": {
                    "suite_id": payload.get("suite"),
                    "successes": successes,
                    "total_episodes": total,
                    "success_rate": success_rate,
                },
            },
            error_code=result.get("error_code"),
            error_message=result.get("error_message"),
            metadata={
                "benchmark_result": result,
                "return_value": float(successes),
                "mean_policy_latency_ms": result.get("mean_policy_latency_ms"),
            },
        )


def _benchmark_payload(skill_ctx: SkillContext) -> dict[str, Any]:
    session = skill_ctx.session
    benchmark = session.benchmark
    suite = benchmark.suite_id if benchmark and benchmark.suite_id else None
    if not suite:
        raise AdapterError("LIBERO benchmark session requires benchmark.suite_id")
    policy_endpoint = session.routing.policy_endpoint
    if not policy_endpoint:
        raise AdapterError("LIBERO benchmark session requires routing.policy_endpoint")
    payload = {
        "session_id": session.session_id,
        "suite": suite,
        "policy_endpoint": policy_endpoint,
        "task_ids": _runtime_hint(session, "task_ids", list(range(10))),
        "init_state_ids": _runtime_hint(session, "init_state_ids", list(range(50))),
        "max_steps": int(session.execution.max_steps),
        "num_steps_wait": int(_target_config(skill_ctx, "num_steps_wait", 10)),
        "control_mode": str(_target_config(skill_ctx, "control_mode", "relative")),
        "camera_height": int(_target_config(skill_ctx, "camera_height", 256)),
        "camera_width": int(_target_config(skill_ctx, "camera_width", 256)),
        "policy_timeout_s": float(session.timeouts.policy_timeout_s),
        "record_dir": _runtime_hint(session, "record_dir", None),
    }
    return payload


def _runtime_hint(session, key: str, default: Any) -> Any:
    for query in session.runtime_hints.perception_queries:
        if isinstance(query, dict) and key in query:
            return query[key]
    return default


def _target_config(skill_ctx: SkillContext, key: str, default: Any) -> Any:
    return skill_ctx.target.config.get(key, default)
