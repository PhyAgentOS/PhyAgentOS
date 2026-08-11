"""pi0.5 adapter for OpenPI-compatible policy payloads."""

from __future__ import annotations

from typing import Any

import numpy as np

from PhyAgentOS.runtime.adapters.openpi.base_openpi_adapter import BaseOpenPIAdapter
from PhyAgentOS.runtime.errors import AdapterError


class OpenPIPi05Adapter(BaseOpenPIAdapter):
    """Map canonical PhyAgentOS observations to pi0.5 OpenPI policy inputs."""

    def input_observation_contract(self) -> dict[str, Any]:
        return {
            "sensors": {
                "front_rgb": {"kind": "image", "dtype": "uint8", "layout": "HWC"},
                "wrist_rgb": {"kind": "image", "dtype": "uint8", "layout": "HWC"},
                "proprio": {"kind": "vector", "dtype": "float32", "shape": [8]},
            }
        }

    def output_action_contract(self) -> dict[str, Any]:
        return {"actions": {"dtype": "float32", "shape": ["T", 7]}}

    def to_policy_input(
        self,
        runtime_observation: dict[str, Any],
        session_ctx: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            sensors = runtime_observation["sensors"]
            image = sensors["front_rgb"]["data"]
            wrist_image = sensors["wrist_rgb"]["data"]
            state = sensors["proprio"]["data"]
        except KeyError as exc:
            raise AdapterError(f"OpenPI pi0.5 observation missing key: {exc.args[0]}") from exc

        image_array = self._image_array(image, "front_rgb")
        wrist_array = self._image_array(wrist_image, "wrist_rgb")
        state_array = np.asarray(state, dtype=np.float32)
        if state_array.shape != (8,):
            raise AdapterError(f"OpenPI pi0.5 state must have shape [8], got {state_array.shape}")

        payload = {
            "observation/image": image_array,
            "observation/wrist_image": wrist_array,
            "observation/state": state_array,
            "prompt": str(session_ctx["task_description"]),
        }
        if _is_xvla_session(session_ctx):
            payload["observation/eef_mat"] = _optional_matrix(sensors.get("eef_mat", {}).get("data"))
            payload["session_id"] = session_ctx.get("session_id")
        return payload

    def from_policy_output(
        self,
        policy_output: dict[str, Any],
        session_ctx: dict[str, Any],
    ) -> dict[str, Any]:
        session_ctx = {**session_ctx, "action_dim": 7}
        return super().from_policy_output(policy_output, session_ctx)

    def _image_array(self, image: Any, name: str) -> np.ndarray:
        array = np.asarray(image)
        if array.size == 0:
            raise AdapterError(f"OpenPI pi0.5 `{name}` image is empty")
        if array.ndim != 3:
            raise AdapterError(f"OpenPI pi0.5 `{name}` image must have rank 3, got {array.shape}")
        if array.shape[-1] != 3 and array.shape[0] != 3:
            raise AdapterError(f"OpenPI pi0.5 `{name}` image must be HWC or CHW RGB, got {array.shape}")
        if np.issubdtype(array.dtype, np.floating):
            array = np.clip(array, 0.0, 1.0)
            array = (array * 255.0).astype(np.uint8)
        else:
            array = array.astype(np.uint8, copy=False)
        return np.ascontiguousarray(array)


def _optional_matrix(matrix: Any) -> np.ndarray | None:
    if matrix is None:
        return None
    array = np.asarray(matrix, dtype=np.float32)
    if array.shape != (3, 3):
        raise AdapterError(f"OpenPI pi0.5 `eef_mat` must have shape [3,3], got {array.shape}")
    return np.ascontiguousarray(array)


def _is_xvla_session(session_ctx: dict[str, Any]) -> bool:
    benchmark = session_ctx.get("benchmark") or {}
    policy_id = benchmark.get("policy_id") if isinstance(benchmark, dict) else None
    if str(policy_id or "").lower() == "xvla":
        return True
    return "xvla" in str(session_ctx.get("skillruntime_ref", "")).lower()
