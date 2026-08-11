"""Target adapter for Isaac Sim remote observations and action chunks."""

from __future__ import annotations

from typing import Any

import numpy as np

from PhyAgentOS.runtime.adapters.base import BaseTargetAdapter
from PhyAgentOS.runtime.errors import AdapterError


class IsaacSimTargetAdapter(BaseTargetAdapter):
    """Convert Isaac rollout observations to canonical runtime observations."""

    def output_observation_contract(self) -> dict[str, Any]:
        return {
            "sensors": {
                "front_rgb": {"kind": "image", "dtype": "uint8", "layout": "HWC"},
                "wrist_rgb": {"kind": "image", "dtype": "uint8", "layout": "HWC"},
                "proprio": {"kind": "vector", "dtype": "float32", "shape": [8]},
            }
        }

    def input_action_contract(self) -> dict[str, Any]:
        return {"actions": {"dtype": "float32", "shape": ["T", 8]}}

    def to_runtime_observation(self, raw_obs: dict[str, Any], target_info: dict[str, Any]) -> dict[str, Any]:
        obs_cfg = target_info.get("observation") or {}
        image_size = int(obs_cfg.get("image_size", target_info.get("image_size", 224)))
        state_dim = int(obs_cfg.get("state_dim", target_info.get("state_dim", 8)))
        image_key = str(obs_cfg.get("image_key", "camera1"))
        wrist_key = str(obs_cfg.get("wrist_image_key", "camera2"))
        third_key = str(obs_cfg.get("third_image_key", "camera3"))

        images = raw_obs.get("images") or {}
        image = images.get(image_key)
        wrist_image = images.get(wrist_key)
        if image is None:
            image = np.zeros((image_size, image_size, 3), dtype=np.uint8)
        if wrist_image is None:
            wrist_image = np.zeros((image_size, image_size, 3), dtype=np.uint8)

        state = raw_obs.get("state")
        if state is None:
            state = np.zeros((state_dim,), dtype=np.float32)
        state = np.asarray(state, dtype=np.float32).reshape(-1)
        if state.shape[0] < state_dim:
            padded = np.zeros((state_dim,), dtype=np.float32)
            padded[: state.shape[0]] = state
            state = padded
        else:
            state = state[:state_dim]

        sensors: dict[str, Any] = {
            "front_rgb": {
                "kind": "image",
                "observation_key": image_key,
                "data": np.asarray(image, dtype=np.uint8),
                "dtype": "uint8",
                "layout": "HWC",
            },
            "wrist_rgb": {
                "kind": "image",
                "observation_key": wrist_key,
                "data": np.asarray(wrist_image, dtype=np.uint8),
                "dtype": "uint8",
                "layout": "HWC",
            },
            "proprio": {
                "kind": "vector",
                "observation_key": "state",
                "data": state,
                "dtype": "float32",
            },
        }
        third = images.get(third_key)
        if third is not None:
            sensors["third_rgb"] = {
                "kind": "image",
                "observation_key": third_key,
                "data": np.asarray(third, dtype=np.uint8),
                "dtype": "uint8",
                "layout": "HWC",
            }

        return {
            "observation_id": raw_obs.get("observation_id", f"isaac_obs_{target_info.get('step_index', 0)}"),
            "sensors": sensors,
            "target_info": target_info,
            "isaacsim": {
                "robot_id": target_info.get("robot_id"),
                "scene_description_cn": raw_obs.get("scene_description_cn"),
                "robot_xy": raw_obs.get("robot_xy"),
            },
        }

    def to_executable_action_chunk(
        self,
        action_chunk: dict[str, Any],
        target_info: dict[str, Any],
    ) -> dict[str, Any]:
        actions = np.asarray(action_chunk.get("actions"), dtype=np.float32)
        if actions.ndim != 2:
            raise AdapterError(f"Isaac actions must have shape [T,A], got {actions.shape}")
        action_dim = int(target_info.get("action_dim", (target_info.get("action") or {}).get("action_dim", 8)))
        if actions.shape[1] != action_dim:
            raise AdapterError(f"Isaac action shape mismatch: expected [T,{action_dim}], got {actions.shape}")
        max_chunk_size = target_info.get("max_chunk_size")
        if max_chunk_size is not None and actions.shape[0] > int(max_chunk_size):
            raise AdapterError(f"Isaac action chunk too large: {actions.shape[0]} > {max_chunk_size}")
        if not np.isfinite(actions).all():
            raise AdapterError("Isaac actions contain NaN or Inf")

        contract = dict(action_chunk.get("action_contract", {}))
        contract.setdefault("id", target_info.get("action_contract_id", "isaac_joint_control_v1"))
        contract.setdefault("shape", [actions.shape[0], actions.shape[1]])
        return {
            "chunk_id": action_chunk.get("chunk_id", "isaac_chunk"),
            "source_observation_id": action_chunk.get("source_observation_id"),
            "source_policy_seq": action_chunk.get("source_policy_seq"),
            "action_contract": contract,
            "provenance": action_chunk.get("provenance", {}),
            "actions": np.ascontiguousarray(actions, dtype=np.float32),
            "robot_id": target_info.get("robot_id"),
        }
