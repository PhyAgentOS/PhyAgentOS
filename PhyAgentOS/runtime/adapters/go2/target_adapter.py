"""Target adapter for Go2 builtin command sessions."""

from __future__ import annotations

from typing import Any

from PhyAgentOS.runtime.adapters.base import BaseTargetAdapter
from PhyAgentOS.runtime.errors import AdapterError


class Go2BuiltinTargetAdapter(BaseTargetAdapter):
    """Go2 builtin sessions use constrained target tools, not action chunks."""

    def output_observation_contract(self) -> dict[str, Any]:
        return {
            "observation_type": "empty",
            "semantics": "Go2 builtin command sessions do not require observation data.",
        }

    def input_action_contract(self) -> dict[str, Any]:
        return {
            "tools": ["execute_step"],
            "action_chunks": "not_supported",
        }

    def to_runtime_observation(self, raw_obs: dict[str, Any], target_info: dict[str, Any]) -> dict[str, Any]:
        return {
            "observation_id": raw_obs.get("observation_id", "go2_empty_obs"),
            "target_info": target_info,
            "go2": raw_obs.get("go2", {}),
        }

    def to_executable_action_chunk(
        self,
        action_chunk: dict[str, Any],
        target_info: dict[str, Any],
    ) -> dict[str, Any]:
        del action_chunk, target_info
        raise AdapterError("Go2 builtin target does not accept action chunks; use execute_step")

