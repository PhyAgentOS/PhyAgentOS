"""OpenPI adapter for PiperGo2 via Isaac Sim remote target."""

from __future__ import annotations

from typing import Any

import numpy as np

from PhyAgentOS.runtime.adapters.openpi.base_openpi_adapter import BaseOpenPIAdapter
from PhyAgentOS.runtime.errors import AdapterError


class PiperGo2IsaacPolicyAdapter(BaseOpenPIAdapter):
    """Map PiperGo2 Isaac runtime observations to OpenPI policy inputs."""

    def input_observation_contract(self) -> dict[str, Any]:
        return {
            "sensors": {
                "front_rgb": {"kind": "image", "dtype": "uint8", "layout": "HWC"},
                "wrist_rgb": {"kind": "image", "dtype": "uint8", "layout": "HWC"},
                "proprio": {"kind": "vector", "dtype": "float32", "shape": [8]},
            }
        }

    def output_action_contract(self) -> dict[str, Any]:
        return {"actions": {"dtype": "float32", "shape": ["T", 8]}}

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
            raise AdapterError(f"PiperGo2 Isaac observation missing key: {exc.args[0]}") from exc

        prompt = str(session_ctx.get("task_description", "")).strip()
        isaac_meta = runtime_observation.get("isaacsim") or {}
        scene_cn = str(isaac_meta.get("scene_description_cn", "")).strip()
        if scene_cn and scene_cn not in prompt:
            prompt = f"{prompt} | scene: {scene_cn}" if prompt else f"scene: {scene_cn}"

        state_array = np.asarray(state, dtype=np.float32).reshape(-1)
        state_dim = self._state_dim(session_ctx)
        if state_array.shape[0] > state_dim:
            state_array = state_array[:state_dim]
        elif state_array.shape[0] < state_dim:
            padded = np.zeros((state_dim,), dtype=np.float32)
            padded[: state_array.shape[0]] = state_array
            state_array = padded

        payload: dict[str, Any] = {
            "observation/image": self._image_array(image, "front_rgb"),
            "observation/wrist_image": self._image_array(wrist_image, "wrist_rgb"),
            "observation/state": state_array,
            "prompt": prompt,
        }
        third = sensors.get("third_rgb")
        if third is not None:
            payload["observation/third_image"] = self._image_array(third["data"], "third_rgb")
        return payload

    def from_policy_output(
        self,
        policy_output: dict[str, Any],
        session_ctx: dict[str, Any],
    ) -> dict[str, Any]:
        action_dim = self._action_dim(session_ctx)
        return super().from_policy_output(
            policy_output,
            {**session_ctx, "action_dim": action_dim},
        )

    @staticmethod
    def _state_dim(session_ctx: dict[str, Any]) -> int:
        for key in ("state_dim",):
            if key in session_ctx:
                return int(session_ctx[key])
        obs_cfg = session_ctx.get("observation")
        if isinstance(obs_cfg, dict) and "state_dim" in obs_cfg:
            return int(obs_cfg["state_dim"])
        return 8

    @staticmethod
    def _action_dim(session_ctx: dict[str, Any]) -> int:
        if "action_dim" in session_ctx:
            return int(session_ctx["action_dim"])
        action_cfg = session_ctx.get("action")
        if isinstance(action_cfg, dict) and "action_dim" in action_cfg:
            return int(action_cfg["action_dim"])
        return 8

    def _image_array(self, image: Any, name: str) -> np.ndarray:
        array = np.asarray(image)
        if array.size == 0:
            raise AdapterError(f"PiperGo2 Isaac `{name}` image is empty")
        if array.ndim != 3:
            raise AdapterError(f"PiperGo2 Isaac `{name}` image must have rank 3, got {array.shape}")
        if np.issubdtype(array.dtype, np.floating):
            array = (np.clip(array, 0.0, 1.0) * 255.0).astype(np.uint8)
        else:
            array = array.astype(np.uint8, copy=False)
        return np.ascontiguousarray(array)
