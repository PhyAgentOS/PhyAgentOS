"""Policy adapter: PhyAgentOS B1K runtime obs -> OmniGibson obs for serve_b1k websocket."""

from __future__ import annotations

from typing import Any

import numpy as np

from PhyAgentOS.runtime.adapters.behavior1k.obs_keys import (
    B1K_ACTION_DIM,
    HEAD_RGB_KEY,
    LEFT_WRIST_RGB_KEY,
    PROPRIO_KEY,
    RIGHT_WRIST_RGB_KEY,
)
from PhyAgentOS.runtime.adapters.openpi.base_openpi_adapter import BaseOpenPIAdapter
from PhyAgentOS.runtime.errors import AdapterError


class Behavior1kOpenPIPolicyAdapter(BaseOpenPIAdapter):
    """Convert B1K TargetWS observations to OmniGibson keys expected by ``serve_b1k.py``."""

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
        return {"actions": {"dtype": "float32", "shape": ["T", B1K_ACTION_DIM]}}

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
            raise AdapterError(f"B1K OpenPI observation missing key: {exc.args[0]}") from exc

        proprio_vec = np.asarray(proprio, dtype=np.float32).reshape(-1)
        if proprio_vec.size != 256:
            raise AdapterError(f"B1K proprio must have shape [256], got {proprio_vec.shape}")

        # serve_b1k B1KPolicyWrapper.process_obs reads these OmniGibson keys.
        return {
            HEAD_RGB_KEY: _image_uint8_hwc(head, "head_rgb"),
            LEFT_WRIST_RGB_KEY: _image_uint8_hwc(left, "left_wrist_rgb"),
            RIGHT_WRIST_RGB_KEY: _image_uint8_hwc(right, "right_wrist_rgb"),
            PROPRIO_KEY: proprio_vec,
            "prompt": str(session_ctx.get("task_description", "")),
        }

    def from_policy_output(
        self,
        policy_output: dict[str, Any],
        session_ctx: dict[str, Any],
    ) -> dict[str, Any]:
        session_ctx = {**session_ctx, "action_dim": B1K_ACTION_DIM}
        return super().from_policy_output(policy_output, session_ctx)


def _image_uint8_hwc(image: Any, name: str) -> np.ndarray:
    array = np.asarray(image)
    if array.size == 0:
        raise AdapterError(f"B1K `{name}` image is empty")
    if array.ndim != 3:
        raise AdapterError(f"B1K `{name}` image must have rank 3, got {array.shape}")
    if array.shape[-1] == 4:
        array = array[..., :3]
    if array.shape[-1] != 3:
        raise AdapterError(f"B1K `{name}` must be HWC RGB, got {array.shape}")
    if np.issubdtype(array.dtype, np.floating):
        array = (np.clip(array, 0.0, 1.0) * 255.0).astype(np.uint8)
    return np.ascontiguousarray(array.astype(np.uint8, copy=False))
