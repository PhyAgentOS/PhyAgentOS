"""Dummy wiggle policy adapter for BEHAVIOR-1K smoke tests (paos side)."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from PhyAgentOS.runtime.adapters.openpi.base_openpi_adapter import BaseOpenPIAdapter
from PhyAgentOS.runtime.errors import AdapterError


class Behavior1kDummyPolicyAdapter(BaseOpenPIAdapter):
    """Generate gentle periodic R1Pro joint actions without an external policy server."""

    def __init__(self, *, action_dim: int = 23, chunk_size: int = 1) -> None:
        self.action_dim = int(action_dim)
        self.chunk_size = int(chunk_size)
        self._step = 0

    def input_observation_contract(self) -> dict[str, Any]:
        return {
            "sensors": {
                "head_rgb": {"kind": "image", "dtype": "uint8", "layout": "HWC"},
                "left_wrist_rgb": {"kind": "image", "dtype": "uint8", "layout": "HWC"},
                "right_wrist_rgb": {"kind": "image", "dtype": "uint8", "layout": "HWC"},
                "proprio": {"kind": "vector", "dtype": "float32", "shape": [256]},
            }
        }

    def output_action_contract(self) -> dict[str, Any]:
        return {"actions": {"dtype": "float32", "shape": ["T", self.action_dim]}}

    def to_policy_input(
        self,
        runtime_observation: dict[str, Any],
        session_ctx: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            sensors = runtime_observation["sensors"]
            head = sensors["head_rgb"]["data"]
            left = sensors["left_wrist_rgb"]["data"]
            right = sensors["right_wrist_rgb"]["data"]
            proprio = sensors["proprio"]["data"]
        except KeyError as exc:
            raise AdapterError(f"BEHAVIOR-1K dummy observation missing key: {exc.args[0]}") from exc
        return {
            "observation/head_rgb": np.asarray(head, dtype=np.uint8),
            "observation/left_wrist_rgb": np.asarray(left, dtype=np.uint8),
            "observation/right_wrist_rgb": np.asarray(right, dtype=np.uint8),
            "observation/state": np.asarray(proprio, dtype=np.float32),
            "prompt": str(session_ctx.get("task_description", "")),
        }

    def from_policy_output(
        self,
        policy_output: dict[str, Any],
        session_ctx: dict[str, Any],
    ) -> dict[str, Any]:
        del policy_output, session_ctx
        chunk_size = max(1, self.chunk_size)
        actions = np.stack([self._wiggle_action(self._step + i) for i in range(chunk_size)], axis=0)
        self._step += chunk_size
        return {
            "actions": actions.astype(np.float32, copy=False),
            "action_contract": {
                "id": "behavior1k_dummy_wiggle_v1",
                "shape": [chunk_size, self.action_dim],
                "dtype": "float32",
                "normalized": False,
            },
        }

    def _wiggle_action(self, step: int) -> np.ndarray:
        t = step * 0.04
        action = np.zeros(self.action_dim, dtype=np.float32)
        action[0:3] = [
            0.06 * math.sin(t * 0.8),
            0.04 * math.sin(t * 0.6 + 0.5),
            0.05 * math.sin(t * 0.5 + 1.0),
        ]
        action[3:7] = [0.035 * math.sin(t + i * 0.7) for i in range(4)]
        action[7:14] = [0.05 * math.sin(t * 0.9 + i * 0.55) for i in range(7)]
        action[15:22] = [0.10 * math.sin(t * 1.2 + i * 0.65) for i in range(7)]
        action[14] = 0.25 * math.sin(t * 1.6)
        action[22] = 0.35 * math.sin(t * 1.8 + 0.3)
        return action
