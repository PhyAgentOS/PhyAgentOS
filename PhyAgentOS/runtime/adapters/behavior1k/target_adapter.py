"""Target adapter for BEHAVIOR-1K remote observations."""

from __future__ import annotations

from typing import Any

import numpy as np

from PhyAgentOS.runtime.adapters.base import BaseTargetAdapter
from PhyAgentOS.runtime.errors import AdapterError


class Behavior1kTargetAdapter(BaseTargetAdapter):
    """Convert BEHAVIOR-1K raw observations to PhyAgentOS runtime observations."""

    def output_observation_contract(self) -> dict[str, Any]:
        return _behavior1k_observation_contract()

    def input_action_contract(self) -> dict[str, Any]:
        return _behavior1k_action_contract()

    def to_runtime_observation(self, raw_obs: dict[str, Any], target_info: dict[str, Any]) -> dict[str, Any]:
        try:
            head_rgb = raw_obs["head_rgb"]
            left_wrist_rgb = raw_obs["left_wrist_rgb"]
            right_wrist_rgb = raw_obs["right_wrist_rgb"]
            proprio = raw_obs["proprio"]
        except KeyError as exc:
            raise AdapterError(f"BEHAVIOR-1K observation missing key: {exc.args[0]}") from exc

        proprio_vec = np.asarray(proprio, dtype=np.float32).reshape(-1)
        if proprio_vec.size == 0:
            raise AdapterError("BEHAVIOR-1K proprio vector is empty")

        return {
            "observation_id": raw_obs.get("observation_id", f"behavior1k_obs_{target_info.get('step_index', 0)}"),
            "sensors": {
                "head_rgb": {
                    "kind": "image",
                    "observation_key": "head_rgb",
                    "data": _image_array(head_rgb, "head_rgb"),
                    "dtype": "uint8",
                    "layout": "HWC",
                },
                "left_wrist_rgb": {
                    "kind": "image",
                    "observation_key": "left_wrist_rgb",
                    "data": _image_array(left_wrist_rgb, "left_wrist_rgb"),
                    "dtype": "uint8",
                    "layout": "HWC",
                },
                "right_wrist_rgb": {
                    "kind": "image",
                    "observation_key": "right_wrist_rgb",
                    "data": _image_array(right_wrist_rgb, "right_wrist_rgb"),
                    "dtype": "uint8",
                    "layout": "HWC",
                },
                "proprio": {
                    "kind": "vector",
                    "observation_key": "proprio",
                    "data": proprio_vec,
                    "dtype": "float32",
                },
            },
            "target_info": target_info,
            "behavior1k": {
                "task_name": raw_obs.get("task_name", target_info.get("task_name")),
                "task_id": raw_obs.get("task_id", target_info.get("task_id")),
                "instance_id": raw_obs.get("instance_id", target_info.get("instance_id")),
                "task_description": raw_obs.get("task_description", target_info.get("task_description")),
            },
        }

    def to_executable_action_chunk(
        self,
        action_chunk: dict[str, Any],
        target_info: dict[str, Any],
    ) -> dict[str, Any]:
        actions = np.asarray(action_chunk.get("actions"), dtype=np.float32)
        if actions.ndim != 2:
            raise AdapterError(f"BEHAVIOR-1K executable actions must have shape [T,A], got {actions.shape}")
        action_dim = int(target_info.get("action_dim", 23))
        if actions.shape[1] != action_dim:
            raise AdapterError(f"BEHAVIOR-1K action shape mismatch: expected [T,{action_dim}], got {actions.shape}")
        max_chunk_size = target_info.get("max_chunk_size")
        if max_chunk_size is not None and actions.shape[0] > int(max_chunk_size):
            raise AdapterError(f"BEHAVIOR-1K action chunk too large: {actions.shape[0]} > {max_chunk_size}")
        if not np.isfinite(actions).all():
            raise AdapterError("BEHAVIOR-1K actions contain NaN or Inf")

        contract = dict(action_chunk.get("action_contract", {}))
        contract.setdefault("id", target_info.get("action_contract_id", "behavior1k_r1pro_joint_v1"))
        contract.setdefault("shape", [actions.shape[0], actions.shape[1]])
        contract.setdefault("dtype", "float32")
        contract.setdefault("normalized", False)
        return {
            "chunk_id": action_chunk.get("chunk_id", "behavior1k_chunk"),
            "source_observation_id": action_chunk.get("source_observation_id"),
            "source_policy_seq": action_chunk.get("source_policy_seq"),
            "action_contract": contract,
            "provenance": action_chunk.get("provenance", {}),
            "actions": np.ascontiguousarray(actions, dtype=np.float32),
            "safety": {
                "require_target_side_validation": True,
                "stop_on_timeout": True,
                "stop_on_nan": True,
            },
        }


def _image_array(image: Any, name: str) -> np.ndarray:
    array = np.asarray(image)
    if array.size == 0:
        raise AdapterError(f"BEHAVIOR-1K `{name}` image is empty")
    if array.ndim != 3:
        raise AdapterError(f"BEHAVIOR-1K `{name}` image must have rank 3, got {array.shape}")
    if array.shape[-1] == 4:
        array = array[..., :3]
    if array.shape[-1] != 3:
        raise AdapterError(f"BEHAVIOR-1K `{name}` image must be HWC RGB, got {array.shape}")
    if np.issubdtype(array.dtype, np.floating):
        array = (np.clip(array, 0.0, 1.0) * 255.0).astype(np.uint8)
    return np.ascontiguousarray(array.astype(np.uint8, copy=False))


def _behavior1k_observation_contract() -> dict[str, Any]:
    return {
        "sensors": {
            "head_rgb": {"kind": "image", "dtype": "uint8", "layout": "HWC"},
            "left_wrist_rgb": {"kind": "image", "dtype": "uint8", "layout": "HWC"},
            "right_wrist_rgb": {"kind": "image", "dtype": "uint8", "layout": "HWC"},
            "proprio": {"kind": "vector", "dtype": "float32", "shape": [256]},
        }
    }


def _behavior1k_action_contract() -> dict[str, Any]:
    return {"actions": {"dtype": "float32", "shape": ["T", 23]}}
