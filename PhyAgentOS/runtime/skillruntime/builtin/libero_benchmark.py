"""LIBERO-specific target-native benchmark runtime."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import urlparse

from PhyAgentOS.runtime.errors import AdapterError
from PhyAgentOS.runtime.schemas import AdapterPlan, BenchmarkJobRequest
from PhyAgentOS.runtime.sessions.models import SkillContext, SkillRuntimeResult
from PhyAgentOS.runtime.skillruntime.builtin.base import BuiltinSkillRuntime


class LiberoBenchmarkSkillRuntime(BuiltinSkillRuntime):
    """Select and drive LIBERO's typed Target benchmark job capability."""

    def __init__(self) -> None:
        self._snapshot: dict[str, Any] = {}
        self._job_id: str | None = None

    def start(self, skill_ctx: SkillContext) -> None:
        self._snapshot = {"session_id": skill_ctx.session.session_id, "state": "starting"}

    def cancel(self, skill_ctx: SkillContext, reason: str) -> None:
        self._snapshot.update({"state": "cancelling", "cancel_reason": reason})

    def snapshot(self, skill_ctx: SkillContext) -> dict:
        return dict(self._snapshot)

    def run_builtin_loop(self, skill_ctx: SkillContext, target_handle, adapter_plan: AdapterPlan) -> SkillRuntimeResult:
        del adapter_plan
        request = _benchmark_request(skill_ctx)
        ref = target_handle.benchmark_start(request)
        self._job_id = ref.job_id
        poll_interval_s = float(skill_ctx.metadata.get("benchmark_poll_interval_s", 0.25))
        while True:
            status = target_handle.benchmark_status(ref.job_id)
            self._snapshot = status.model_dump(mode="json")
            if status.state in {"succeeded", "failed", "cancelled"}:
                break
            if target_handle.session_state.cancelled:
                status = target_handle.benchmark_cancel(ref.job_id, "session cancelled")
                self._snapshot = status.model_dump(mode="json")
                break
            time.sleep(poll_interval_s)
        result = target_handle.benchmark_result(ref.job_id).model_dump(mode="json")
        total = int(result.get("total_episodes") or len(result.get("episodes") or []))
        first_successes = int(result.get("first_attempt_successes") or 0)
        state = str(result.get("status") or "failed")
        return SkillRuntimeResult(
            status=state if state in {"succeeded", "failed", "timed_out", "cancelled"} else "failed",
            success=bool(total and state == "succeeded"),
            final_status={
                "target_step_index": int(result.get("num_steps") or 0),
                "executed_steps": int(result.get("num_steps") or 0),
                "success": bool(total and state == "succeeded"),
                "done": True,
                "reward": float(first_successes),
                "benchmark": {"suite_id": request.suite_id, "first_attempt_successes": first_successes, "total_episodes": total},
            },
            error_code=result.get("error_code"),
            error_message=result.get("error_message"),
            metadata={"benchmark_result": result, "return_value": float(first_successes), "mean_policy_latency_ms": result.get("mean_policy_latency_ms")},
        )


def _benchmark_request(skill_ctx: SkillContext) -> BenchmarkJobRequest:
    session = skill_ctx.session
    benchmark = session.benchmark
    if benchmark is None or benchmark.execution_mode != "target_native":
        raise AdapterError("LiberoBenchmarkSkillRuntime requires benchmark.execution_mode=target_native")
    if not benchmark.suite_id:
        raise AdapterError("LIBERO benchmark session requires benchmark.suite_id")
    if not session.routing.policy_endpoint:
        raise AdapterError("LIBERO benchmark session requires routing.policy_endpoint")
    task_ids = _hint(session, "task_ids", list(range(10)))
    init_state_ids = _hint(session, "init_state_ids", list(range(50)))
    episodes = [{"task_id": int(task_id), "init_state_id": int(init_id)} for task_id in task_ids for init_id in init_state_ids]
    verification = dict(skill_ctx.metadata.get("verification") or {})
    replan_every_steps = (
        session.execution.replan_every_steps
        or session.runtime_hints.preferred_replan_every_steps
        or session.execution.replan_every
    )
    return BenchmarkJobRequest(
        benchmark_id=str(benchmark.benchmark_id),
        suite_id=benchmark.suite_id,
        run_id=benchmark.run_id or session.session_id,
        policy_endpoint=session.routing.policy_endpoint,
        episodes=episodes,
        max_steps=session.execution.max_steps,
        policy_timeout_s=session.timeouts.policy_timeout_s,
        control_mode=str(skill_ctx.target.config.get("control_mode", "relative")),
        evidence_mode="failed" if session.verification_profile != "strict" else "none",
        verification_profile=session.verification_profile,
        verification_endpoint=_verification_endpoint(skill_ctx, verification),
        verification_token=_episode_token(
            str(verification.get("episode_token") or ""), session.session_id, benchmark.run_id or session.session_id,
            int(session.timeouts.execute_timeout_s + float(verification.get("timeout_s", 180.0))),
        ) if verification.get("episode_token") else None,
        verification_timeout_s=float(verification.get("timeout_s", 180.0)),
        max_replans_per_episode=int(verification.get("max_replans_per_episode", 2)),
        max_verifier_calls_per_run=int(verification.get("max_verifier_calls_per_run", 50)),
        retry_instruction_mode=str(skill_ctx.target.config.get("retry_instruction_mode", "original")),
        options={
            "task_ids": task_ids,
            "init_state_ids": init_state_ids,
            "num_steps_wait": int(skill_ctx.target.config.get("num_steps_wait", 10)),
            "camera_height": int(skill_ctx.target.config.get("camera_height", 256)),
            "camera_width": int(skill_ctx.target.config.get("camera_width", 256)),
            "seed": int(skill_ctx.target.config.get("seed", 0)),
            "replan_every_steps": int(replan_every_steps),
            "record_dir": _hint(session, "record_dir", None),
        },
    )


def _hint(session, key: str, default: Any) -> Any:
    for entry in session.runtime_hints.perception_queries:
        if isinstance(entry, dict) and key in entry:
            return entry[key]
    return default


def _episode_token(secret: str, session_id: str, run_id: str, ttl_s: int) -> str:
    payload = json.dumps({"session_id": session_id, "run_id": run_id, "expires_at": int(time.time()) + max(1, ttl_s)}, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    signature = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return encoded + "." + signature


def _verification_endpoint(skill_ctx: SkillContext, settings: dict[str, Any]) -> str | None:
    if skill_ctx.session.verification_profile == "strict":
        return None
    target_endpoint = skill_ctx.session.routing.target_endpoint or skill_ctx.target.runtime.target_endpoint
    hostname = urlparse(str(target_endpoint or "").replace("targetws://", "ws://", 1)).hostname
    same_host = skill_ctx.target.target_class == "local" or hostname in {None, "localhost", "127.0.0.1", "::1"}
    endpoint = settings.get("local_service_url") if same_host else settings.get("remote_target_url")
    if not endpoint:
        raise AdapterError("remote Target verification requires agents.verification.remoteTargetUrl")
    return str(endpoint)
