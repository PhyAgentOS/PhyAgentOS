"""Dummy target adapter for dependency-free runtime smoke tests."""

from __future__ import annotations

from typing import Any

import numpy as np

from PhyAgentOS.runtime.adapters.base import BaseTargetAdapter
from PhyAgentOS.runtime.errors import AdapterError


class DummySimTargetAdapter(BaseTargetAdapter):
    def output_observation_contract(self) -> dict[str, Any]:
        return {
            "sensors": {
                "front_rgb": {"kind": "image", "dtype": "uint8", "layout": "HWC"},
                "wrist_rgb": {"kind": "image", "dtype": "uint8", "layout": "HWC"},
                "proprio": {"kind": "vector", "dtype": "float32", "shape": [8]},
            }
        }

    def input_action_contract(self) -> dict[str, Any]:
        return {"actions": {"dtype": "float32", "shape": ["T", 7]}}

    def to_runtime_observation(self, raw_obs: dict[str, Any], target_info: dict[str, Any]) -> dict[str, Any]:
        sensors = {
            "front_rgb": {
                "kind": "image",
                "observation_key": "image.front_rgb",
                "data": np.asarray(raw_obs.get("image"), dtype=np.uint8),
                "dtype": "uint8",
                "layout": "HWC",
            },
            "wrist_rgb": {
                "kind": "image",
                "observation_key": "image.wrist_rgb",
                "data": np.asarray(raw_obs.get("wrist_image"), dtype=np.uint8),
                "dtype": "uint8",
                "layout": "HWC",
            },
            "proprio": {
                "kind": "vector",
                "observation_key": "state.proprio",
                "data": np.asarray(raw_obs.get("state"), dtype=np.float32),
                "dtype": "float32",
            },
        }
        if any(value["data"].shape == () for value in sensors.values()):
            raise AdapterError("dummy target observation missing image, wrist_image, or state")
        return {
            "observation_id": f"dummy_obs_{target_info.get('step_index', 0)}",
            "sensors": sensors,
            "target_info": target_info,
        }

    def to_executable_action_chunk(
        self,
        action_chunk: dict[str, Any],
        target_info: dict[str, Any],
    ) -> dict[str, Any]:
        actions = np.asarray(action_chunk.get("actions"), dtype=np.float32)
        if actions.ndim != 2:
            raise AdapterError(f"executable actions must have shape [T,A], got {actions.shape}")
        action_dim = int(target_info.get("action_dim", actions.shape[1]))
        if actions.shape[1] != action_dim:
            raise AdapterError(f"action shape mismatch: expected [T,{action_dim}], got {actions.shape}")
        contract = dict(action_chunk.get("action_contract", {}))
        contract.setdefault("id", target_info.get("action_contract_id", "dummy_delta_eef_gripper_v1"))
        contract.setdefault("shape", [actions.shape[0], actions.shape[1]])
        contract.setdefault("dtype", "float32")
        contract.setdefault("normalized", False)
        return {
            "chunk_id": action_chunk.get("chunk_id", "dummy_chunk"),
            "source_observation_id": action_chunk.get("source_observation_id"),
            "source_policy_seq": action_chunk.get("source_policy_seq"),
            "action_contract": contract,
            "provenance": action_chunk.get("provenance", {}),
            "actions": actions,
            "safety": {
                "require_target_side_validation": True,
                "stop_on_timeout": True,
                "stop_on_nan": True,
            },
        }
