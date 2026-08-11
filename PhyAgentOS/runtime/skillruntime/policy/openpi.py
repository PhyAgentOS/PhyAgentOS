"""OpenPI policy skill runtime."""

from __future__ import annotations

from statistics import mean

from PhyAgentOS.runtime.adapters.factory import build_policy_adapter
from PhyAgentOS.runtime.errors import PolicyProtocolError
from PhyAgentOS.runtime.policy.base_client import BasePolicyClient
from PhyAgentOS.runtime.schemas import AdapterPlan
from PhyAgentOS.runtime.sessions.models import EnvironmentRequest, SkillContext, SkillRuntimeResult
from PhyAgentOS.runtime.skillruntime.policy.base import PolicySkillRuntime


class OpenPISkillRuntime(PolicySkillRuntime):
    """OpenPI-style policy loop using TargetSessionHandle only."""

    def __init__(self):
        self._snapshot: dict = {}

    def start(self, skill_ctx: SkillContext) -> None:
        self._snapshot = {"session_id": skill_ctx.session.session_id, "started": True}

    def cancel(self, skill_ctx: SkillContext, reason: str) -> None:
        self._snapshot = {**self._snapshot, "cancelled": True, "cancel_reason": reason}

    def snapshot(self, skill_ctx: SkillContext) -> dict:
        return dict(self._snapshot)

    def run_policy_loop(
        self,
        skill_ctx: SkillContext,
        target_handle,
        adapter_plan: AdapterPlan,
        policy_client: BasePolicyClient,
    ) -> SkillRuntimeResult:
        if not adapter_plan.policy_adapter:
            raise PolicyProtocolError("OpenPI runtime requires a policy adapter")
        policy_adapter = build_policy_adapter(adapter_plan.policy_adapter)
        latencies: list[float] = []
        total_reward = 0.0
        session_ctx = skill_ctx.session.model_dump(mode="json")
        action_cfg = skill_ctx.target.config.get("action", {})
        action_dim = skill_ctx.target.config.get("action_dim", action_cfg.get("action_dim", 7))
        session_ctx["action_dim"] = int(action_dim)
        session_ctx["policy_action_contract"] = self._policy_action_contract(skill_ctx, int(action_dim))

        for step_idx in range(skill_ctx.session.execution.max_steps):
            observation = target_handle.observe()
            if step_idx == 0 and skill_ctx.skillruntime.requires.environment_outputs:
                target_handle.request_environment_refresh(
                    EnvironmentRequest(requested_outputs=list(skill_ctx.skillruntime.requires.environment_outputs))
                )
            session_ctx["source_observation_id"] = observation.data.get("observation_id")
            policy_input = policy_adapter.to_policy_input(observation.data, session_ctx)
            action_payload = policy_client.infer(policy_input)
            policy_meta = action_payload.get("policy_meta", {})
            if "policy_latency_ms" in policy_meta:
                latencies.append(float(policy_meta["policy_latency_ms"]))
            policy_action_chunk = policy_adapter.from_policy_output(action_payload, session_ctx)
            if policy_action_chunk.get("actions") is None:
                raise PolicyProtocolError("policy returned an empty action buffer")

            status = target_handle.action_chunk(policy_action_chunk)
            total_reward += float(status.get("reward", 0.0))
            self._snapshot = {"session_id": skill_ctx.session.session_id, "step_index": step_idx, "status": status}
            if bool(status.get("success", False)) or bool(status.get("done", False)):
                return SkillRuntimeResult(
                    status="succeeded" if bool(status.get("success", False)) else "failed",
                    success=bool(status.get("success", False)),
                    final_status=status,
                    metadata={
                        "done": bool(status.get("done", False)),
                        "mean_policy_latency_ms": mean(latencies) if latencies else None,
                        "return_value": total_reward,
                    },
                )

        return SkillRuntimeResult(
            status="failed",
            success=False,
            final_status=target_handle.execution_status(),
            error_code="MAX_STEPS_EXCEEDED",
            error_message="session reached max_steps without success",
            metadata={"mean_policy_latency_ms": mean(latencies) if latencies else None, "return_value": total_reward},
        )

    def _policy_action_contract(self, skill_ctx: SkillContext, action_dim: int) -> dict:
        action_contract = skill_ctx.skillruntime.output_contract.get("action", {})
        if action_contract:
            return action_contract
        return {
            "action_space_id": "dummy_policy_delta_eef_gripper_v1",
            "shape": ["T", action_dim],
            "dtype": "float32",
            "normalized": False,
            "representation": "delta_eef_pose_gripper",
            "frame": "base",
            "chunk": {"policy_hz": skill_ctx.target.config.get("control_hz", 20)},
        }
