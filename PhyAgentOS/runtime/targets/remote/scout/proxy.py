"""Scout-specific remote target proxy."""

from __future__ import annotations

from typing import Any

from PhyAgentOS.runtime.communication.target_ws_client import TargetWSClient
from PhyAgentOS.runtime.targets.remote.proxy import RemoteTargetProxy


SCOUT_DEFAULT_CONFIG = {
    "scout_ip": "192.168.1.100",
    "ros_master_uri": "http://192.168.1.100:11311",
    "action_dim": 2,
    "max_chunk_size": 1,
    "max_steps": 100,
}


class ScoutRemoteTargetProxy(RemoteTargetProxy):
    """Remote target proxy with Scout 2.0 defaults."""

    def __init__(self, client: TargetWSClient, *, config: dict[str, Any] | None = None):
        merged = {**SCOUT_DEFAULT_CONFIG, **dict(config or {})}
        super().__init__(client, config=merged)

    def configure_session(self, session_ctx: dict[str, Any]) -> dict[str, Any]:
        merged_ctx = self._with_scout_config(session_ctx)
        return super().configure_session(merged_ctx)

    def reset(self, session_ctx: dict[str, Any]) -> dict[str, Any]:
        merged_ctx = self._with_scout_config(session_ctx)
        return super().reset(merged_ctx)

    def _with_scout_config(self, session_ctx: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(session_ctx.get("metadata", {}))
        scout_config = {**SCOUT_DEFAULT_CONFIG, **self.config, **metadata.get("scout", {})}
        metadata["scout"] = scout_config
        return {**session_ctx, "metadata": metadata, "scout": scout_config}
