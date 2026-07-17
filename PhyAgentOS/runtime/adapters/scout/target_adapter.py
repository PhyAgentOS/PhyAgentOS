"""Target adapter for Scout 2.0 builtin command sessions."""
from __future__ import annotations
from typing import Any
from PhyAgentOS.runtime.adapters.base import BaseTargetAdapter
from PhyAgentOS.runtime.watchdog.errors import AdapterError

class ScoutTargetAdapter(BaseTargetAdapter):
    def output_observation_contract(self) -> dict[str, Any]:
        return {
            "observation_type": "multimodal",
            "channels": ["camera", "odom", "lidar"],
            "semantics": "Scout 2.0 提供 RGB 摄像头、里程计、LiDAR 数据",
        }
    def input_action_contract(self) -> dict[str, Any]:
        return {
            "tools": ["execute_step"],
            "action_chunks": "not_supported",
        }
    def to_runtime_observation(self, raw_obs: dict[str, Any], target_info: dict[str, Any]) -> dict[str, Any]:
        return {
            "observation_id": raw_obs.get("observation_id", "scout_obs"),
            "target_info": target_info,
            "camera": raw_obs.get("camera"),
            "odom": raw_obs.get("odom"),
            "lidar": raw_obs.get("lidar"),
        }
    def to_executable_action_chunk(self, action_chunk: dict[str, Any], target_info: dict[str, Any]) -> dict[str, Any]:
        del action_chunk, target_info
        raise AdapterError("Scout builtin target does not accept action chunks; use execute_step")
