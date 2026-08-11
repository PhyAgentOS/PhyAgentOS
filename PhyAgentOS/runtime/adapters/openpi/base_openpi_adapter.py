"""Base adapter for OpenPI-style policy payloads."""

from __future__ import annotations

from abc import abstractmethod
from typing import Any

import numpy as np

from PhyAgentOS.runtime.adapters.base import BasePolicyAdapter
from PhyAgentOS.runtime.errors import AdapterError


class BaseOpenPIAdapter(BasePolicyAdapter):
    @abstractmethod
    def to_policy_input(
        self,
        runtime_observation: dict[str, Any],
        session_ctx: dict[str, Any],
    ) -> dict[str, Any]:
        """Convert RuntimeObservation to an OpenPI inference dict."""

    def from_policy_output(
        self,
        policy_output: dict[str, Any],
        session_ctx: dict[str, Any],
    ) -> dict[str, Any]:
        if "actions" not in policy_output:
            raise AdapterError("policy payload missing `actions`")
        actions = np.asarray(policy_output["actions"], dtype=np.float32)
        if actions.ndim == 1:
            actions = actions[None, :]
        if actions.ndim != 2:
            raise AdapterError(f"`actions` must have shape [A] or [T,A], got {actions.shape}")

        action_contract = session_ctx.get("policy_action_contract", {})
        expected_shape = action_contract.get("shape")
        if expected_shape and len(expected_shape) == 2 and isinstance(expected_shape[1], int):
            expected_dim = int(expected_shape[1])
            if actions.shape[1] != expected_dim:
                raise AdapterError(f"policy action shape mismatch: expected [T,{expected_dim}], got {actions.shape}")
        action_dim = session_ctx.get("action_dim")
        if action_dim is not None and actions.shape[1] != int(action_dim):
            raise AdapterError(f"policy action shape mismatch: expected [T,{action_dim}], got {actions.shape}")

        policy_meta = dict(policy_output.get("policy_meta", {}))
        return {
            "chunk_id": f"policy_chunk_{policy_meta.get('policy_seq', 0)}",
            "source_observation_id": session_ctx.get("source_observation_id"),
            "source_policy_seq": policy_meta.get("policy_seq", 0),
            "action_contract": {
                "id": action_contract.get("action_space_id", "dummy_policy_delta_eef_gripper_v1"),
                "representation": action_contract.get("representation", "delta_eef_pose_gripper"),
                "frame": action_contract.get("frame", "base"),
                "control_mode": action_contract.get("control_mode", "policy_delta"),
                "dtype": action_contract.get("dtype", "float32"),
                "shape": [actions.shape[0], actions.shape[1]],
                "normalized": bool(action_contract.get("normalized", False)),
                "components": action_contract.get("components", []),
            },
            "timing": {
                "policy_hz": action_contract.get("chunk", {}).get("policy_hz"),
                "horizon_steps": actions.shape[0],
            },
            "actions": actions,
            "policy_meta": policy_meta,
        }

    def should_replan(
        self,
        step_idx: int,
        action_buffer_size: int,
        target_info: dict[str, Any],
    ) -> bool:
        return action_buffer_size == 0
