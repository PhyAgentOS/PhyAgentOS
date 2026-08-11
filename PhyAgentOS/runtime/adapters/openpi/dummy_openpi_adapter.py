"""Dummy simulation adapter for OpenPI-style policy observations."""

from __future__ import annotations

from typing import Any

import numpy as np

from PhyAgentOS.runtime.adapters.openpi.base_openpi_adapter import BaseOpenPIAdapter
from PhyAgentOS.runtime.errors import AdapterError


class DummyOpenPIAdapter(BaseOpenPIAdapter):
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
            raise AdapterError(f"dummy observation missing key: {exc.args[0]}") from exc
        if image is None or wrist_image is None or state is None:
            raise AdapterError("dummy observation missing image, wrist_image, or state")
        return {
            "observation/image": np.asarray(image, dtype=np.uint8),
            "observation/wrist_image": np.asarray(wrist_image, dtype=np.uint8),
            "observation/state": np.asarray(state, dtype=np.float32),
            "prompt": str(session_ctx["task_description"]),
        }
