"""Target adapter for G1 builtin command sessions."""

from __future__ import annotations

from typing import Any

from PhyAgentOS.runtime.adapters.base import BaseTargetAdapter
from PhyAgentOS.runtime.watchdog.errors import AdapterError


class G1BuiltinTargetAdapter(BaseTargetAdapter):
    """G1 builtin sessions use constrained target tools, not action chunks."""

    def output_observation_contract(self) -> dict[str, Any]:
        return {
            "observation_type": "empty",
            "semantics": "G1 builtin command sessions do not require observation data.",
        }

    def input_action_contract(self) -> dict[str, Any]:
        return {
            "tools": ["execute_step", "execute_arm_action"],
            "action_chunks": "not_supported",
        }

    def to_runtime_observation(self, raw_obs: dict[str, Any], target_info: dict[str, Any]) -> dict[str, Any]:
        return {
            "observation_id": raw_obs.get("observation_id", "g1_empty_obs"),
            "target_info": target_info,
            "g1": raw_obs.get("g1", {}),
        }

    def to_executable_action_chunk(
        self,
        action_chunk: dict[str, Any],
        target_info: dict[str, Any],
    ) -> dict[str, Any]:
        del action_chunk, target_info
        raise AdapterError("G1 builtin target does not accept action chunks; use execute_step")
