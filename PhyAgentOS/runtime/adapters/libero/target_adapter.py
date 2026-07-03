"""Target adapter for LIBERO benchmark remote observations."""

from __future__ import annotations

from typing import Any

import numpy as np

from PhyAgentOS.runtime.adapters.base import BaseTargetAdapter
from PhyAgentOS.runtime.watchdog.errors import AdapterError


class LiberoTargetAdapter(BaseTargetAdapter):
    """Convert LIBERO raw observations to PhyAgentOS runtime observations."""

    def output_observation_contract(self) -> dict[str, Any]:
        return _libero_observation_contract()

    def input_action_contract(self) -> dict[str, Any]:
        return _libero_action_contract()

    def to_runtime_observation(self, raw_obs: dict[str, Any], target_info: dict[str, Any]) -> dict[str, Any]:
        try:
            front_rgb = raw_obs["agentview_image"]
            wrist_rgb = raw_obs["robot0_eye_in_hand_image"]
            eef_pos = raw_obs["robot0_eef_pos"]
            eef_quat = raw_obs["robot0_eef_quat"]
            gripper_qpos = raw_obs["robot0_gripper_qpos"]
        except KeyError as exc:
            raise AdapterError(f"LIBERO observation missing key: {exc.args[0]}") from exc
        eef_mat = raw_obs.get("robot0_eef_mat")

        state = np.concatenate(
            [
                np.asarray(eef_pos, dtype=np.float32).reshape(3),
                _quat_to_axisangle(np.asarray(eef_quat, dtype=np.float32).reshape(4)),
                _gripper_state(gripper_qpos),
            ]
        ).astype(np.float32)
        if state.shape != (8,):
            raise AdapterError(f"LIBERO proprio state must have shape [8], got {state.shape}")

        sensors = {
            "front_rgb": {
                "kind": "image",
                "observation_key": "agentview_image",
                "data": _image_array(front_rgb, "agentview_image"),
                "dtype": "uint8",
                "layout": "HWC",
            },
            "wrist_rgb": {
                "kind": "image",
                "observation_key": "robot0_eye_in_hand_image",
                "data": _image_array(wrist_rgb, "robot0_eye_in_hand_image"),
                "dtype": "uint8",
                "layout": "HWC",
            },
            "proprio": {
                "kind": "vector",
                "observation_key": "libero_eef_axisangle_gripper_step",
                "data": state,
                "dtype": "float32",
            },
        }
        if eef_mat is not None:
            sensors["eef_mat"] = {
                "kind": "matrix",
                "observation_key": "robot0_eef_mat",
                "data": _eef_matrix_or_none(eef_mat),
                "dtype": "float32",
                "shape": [3, 3],
            }

        return {
            "observation_id": raw_obs.get("observation_id", f"libero_obs_{target_info.get('step_index', 0)}"),
            "sensors": sensors,
            "target_info": target_info,
            "libero": {
                "benchmark_name": raw_obs.get("benchmark_name", target_info.get("benchmark_name")),
                "task_id": raw_obs.get("task_id", target_info.get("task_id")),
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
            raise AdapterError(f"LIBERO executable actions must have shape [T,A], got {actions.shape}")
        if actions.shape[1] != 7:
            raise AdapterError(f"LIBERO action shape mismatch: expected [T,7], got {actions.shape}")
        max_chunk_size = target_info.get("max_chunk_size")
        if max_chunk_size is not None and actions.shape[0] > int(max_chunk_size):
            raise AdapterError(f"LIBERO action chunk too large: {actions.shape[0]} > {max_chunk_size}")
        if not np.isfinite(actions).all():
            raise AdapterError("LIBERO actions contain NaN or Inf")

        contract = dict(action_chunk.get("action_contract", {}))
        contract.setdefault("id", target_info.get("action_contract_id", "libero_delta_eef_gripper_v1"))
        contract.setdefault("shape", [actions.shape[0], actions.shape[1]])
        contract.setdefault("dtype", "float32")
        contract.setdefault("normalized", False)
        return {
            "chunk_id": action_chunk.get("chunk_id", "libero_chunk"),
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
        raise AdapterError(f"LIBERO `{name}` image is empty")
    if array.ndim != 3:
        raise AdapterError(f"LIBERO `{name}` image must have rank 3, got {array.shape}")
    if array.shape[-1] != 3:
        raise AdapterError(f"LIBERO `{name}` image must be HWC RGB, got {array.shape}")
    if np.issubdtype(array.dtype, np.floating):
        array = (np.clip(array, 0.0, 1.0) * 255.0).astype(np.uint8)
    return np.ascontiguousarray(array.astype(np.uint8, copy=False))


def _libero_observation_contract() -> dict[str, Any]:
    return {
        "sensors": {
            "front_rgb": {"kind": "image", "dtype": "uint8", "layout": "HWC"},
            "wrist_rgb": {"kind": "image", "dtype": "uint8", "layout": "HWC"},
            "proprio": {"kind": "vector", "dtype": "float32", "shape": [8]},
        }
    }


def _libero_action_contract() -> dict[str, Any]:
    return {"actions": {"dtype": "float32", "shape": ["T", 7]}}


def _quat_to_axisangle(quat: np.ndarray) -> np.ndarray:
    quat = quat.astype(np.float32, copy=True)
    quat[3] = np.clip(quat[3], -1.0, 1.0)
    den = np.sqrt(max(0.0, 1.0 - float(quat[3] * quat[3])))
    if den < 1e-8:
        return np.zeros(3, dtype=np.float32)
    return (quat[:3] * (2.0 * np.arccos(quat[3]) / den)).astype(np.float32)


def _gripper_state(gripper_qpos: Any) -> np.ndarray:
    values = np.asarray(gripper_qpos, dtype=np.float32).reshape(-1)
    if values.size == 0:
        raise AdapterError("LIBERO `robot0_gripper_qpos` is empty")
    if values.size == 1:
        values = np.repeat(values, 2)
    return values[:2].astype(np.float32)


def _eef_matrix_or_none(eef_mat: Any) -> np.ndarray | None:
    if eef_mat is None:
        return None
    matrix = np.asarray(eef_mat, dtype=np.float32)
    if matrix.shape != (3, 3):
        raise AdapterError(f"LIBERO `robot0_eef_mat` must have shape [3,3], got {matrix.shape}")
    return np.ascontiguousarray(matrix)
