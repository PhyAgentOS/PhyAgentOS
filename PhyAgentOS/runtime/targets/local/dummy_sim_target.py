"""Dependency-free local target used for runtime smoke tests."""

from __future__ import annotations

from typing import Any

import numpy as np

from PhyAgentOS.runtime.errors import TargetStepError
from PhyAgentOS.runtime.targets.local.base import BaseLocalTarget


class DummySimTarget(BaseLocalTarget):
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = dict(config or {})
        self.step_idx = 0
        self._built = False
        self._last_status: dict[str, Any] = {"accepted": True, "safety_status": "idle", "executed_steps": 0}

    def build(self) -> None:
        self._built = True

    def describe(self) -> dict[str, Any]:
        action_cfg = self.config.get("action", {})
        state_dim = self._config_int("state_dim", default=self._nested_int("observation", "state_dim", 8))
        return {
            "runtime": "DummySimTargetRuntime",
            "observation_schema": {
                "image.front_rgb": {"dtype": "uint8", "layout": "HWC"},
                "image.wrist_rgb": {"dtype": "uint8", "layout": "HWC"},
                "state.proprio": {"dtype": "float32", "shape": [state_dim]},
            },
            "action_contract": {
                "id": action_cfg.get("id", "dummy_delta_eef_gripper_v1"),
                "shape": ["T", self._config_int("action_dim", default=self._nested_int("action", "action_dim", 7))],
            },
        }

    def configure_session(self, session_ctx: dict[str, Any]) -> dict[str, Any]:
        return {"configured": True, "session_id": session_ctx.get("session_id")}

    def start_session(self, session_ctx: dict[str, Any]) -> dict[str, Any]:
        return {"started": True, "session_id": session_ctx.get("session_id")}

    def reset(self, session_ctx: dict[str, Any]) -> dict[str, Any]:
        self.step_idx = 0
        self._last_status = {"accepted": True, "safety_status": "ok", "executed_steps": 0}
        return self.observe()

    def observe(self) -> dict[str, Any]:
        image_size = self._config_int("image_size", default=self._nested_int("observation", "image_size", 224))
        state_dim = self._config_int("state_dim", default=self._nested_int("observation", "state_dim", 8))
        return {
            "image": np.zeros((image_size, image_size, 3), dtype=np.uint8),
            "wrist_image": np.zeros((image_size, image_size, 3), dtype=np.uint8),
            "state": np.zeros((state_dim,), dtype=np.float32),
        }

    def _step(self, action: np.ndarray) -> dict[str, Any]:
        action_array = np.asarray(action, dtype=np.float32)
        action_dim = self._config_int("action_dim", default=self._nested_int("action", "action_dim", 7))
        if action_array.ndim != 1 or action_array.shape[0] < action_dim:
            raise TargetStepError(f"expected action vector with at least {action_dim} dims, got {action_array.shape}")
        self.step_idx += 1
        done = self.step_idx >= self._config_int("success_after_steps", default=5)
        return {
            "obs": self.observe(),
            "reward": float(done),
            "done": done,
            "info": {"success": done, "step_idx": self.step_idx},
        }

    def action_chunk(self, executable_action_chunk: dict[str, Any]) -> dict[str, Any]:
        actions = np.asarray(executable_action_chunk.get("actions"), dtype=np.float32)
        if actions.ndim != 2:
            raise TargetStepError(f"expected action chunk [T,A], got {actions.shape}")
        chunk_id = executable_action_chunk.get("chunk_id", "dummy_chunk")
        total_reward = 0.0
        last_transition: dict[str, Any] | None = None
        for action in actions:
            last_transition = self._step(action)
            total_reward += float(last_transition.get("reward", 0.0))
            if bool(last_transition.get("done", False)) or bool(last_transition.get("info", {}).get("success", False)):
                break
        executed_steps = int(self.step_idx)
        success = bool(last_transition and last_transition.get("info", {}).get("success", False))
        self._last_status = {
            "chunk_id": chunk_id,
            "accepted": True,
            "buffered_steps": max(0, int(actions.shape[0]) - executed_steps),
            "executed_steps": executed_steps,
            "target_step_index": self.step_idx,
            "need_replan": not success,
            "safety_status": "ok",
            "success": success,
            "done": bool(last_transition and last_transition.get("done", False)),
            "reward": total_reward,
            "obs": last_transition["obs"] if last_transition else self.observe(),
        }
        return self._last_status

    def execution_status(self) -> dict[str, Any]:
        return dict(self._last_status)

    def cancel(self, reason: str) -> None:
        self._last_status = {**self._last_status, "cancelled": True, "cancel_reason": reason}

    def close(self) -> None:
        self._built = False

    def _nested_int(self, section: str, key: str, default: int) -> int:
        value = self.config.get(section)
        if isinstance(value, dict) and key in value:
            return int(value[key])
        return int(default)

    def _config_int(self, key: str, default: int) -> int:
        return int(self.config.get(key, default))
