"""BEHAVIOR-1K-specific remote target proxy."""

from __future__ import annotations

from typing import Any

import numpy as np

from PhyAgentOS.runtime.communication.target_ws_client import TargetWSClient
from PhyAgentOS.runtime.errors import TargetProtocolError
from PhyAgentOS.runtime.targets.remote.proxy import RemoteTargetProxy

BEHAVIOR1K_DEFAULT_CONFIG = {
    "task_name": "turning_on_radio",
    "instance_id": 0,
    "action_dim": 23,
    "max_chunk_size": 50,
    "max_steps": 200,
}


class Behavior1KRemoteTargetProxy(RemoteTargetProxy):
    """Remote target proxy with BEHAVIOR-1K R1Pro defaults and action validation."""

    def __init__(self, client: TargetWSClient, *, config: dict[str, Any] | None = None):
        merged = {**BEHAVIOR1K_DEFAULT_CONFIG, **dict(config or {})}
        super().__init__(client, config=merged)

    def configure_session(self, session_ctx: dict[str, Any]) -> dict[str, Any]:
        return super().configure_session(self._with_behavior1k_config(session_ctx))

    def reset(self, session_ctx: dict[str, Any]) -> dict[str, Any]:
        return super().reset(self._with_behavior1k_config(session_ctx))

    def action_chunk(self, executable_action_chunk: dict[str, Any]) -> dict[str, Any]:
        actions = np.asarray(executable_action_chunk.get("actions"), dtype=np.float32)
        if actions.ndim != 2:
            raise TargetProtocolError(f"BEHAVIOR-1K actions must have shape [T,A], got {actions.shape}")
        action_dim = int(self.config.get("action_dim", BEHAVIOR1K_DEFAULT_CONFIG["action_dim"]))
        if actions.shape[1] != action_dim:
            raise TargetProtocolError(f"BEHAVIOR-1K actions must have shape [T,{action_dim}], got {actions.shape}")
        if not np.isfinite(actions).all():
            raise TargetProtocolError("BEHAVIOR-1K actions contain NaN or Inf")
        max_chunk_size = int(self.config.get("max_chunk_size", BEHAVIOR1K_DEFAULT_CONFIG["max_chunk_size"]))
        if actions.shape[0] > max_chunk_size:
            raise TargetProtocolError(f"BEHAVIOR-1K action chunk too large: {actions.shape[0]} > {max_chunk_size}")
        updated = dict(executable_action_chunk)
        updated["actions"] = np.ascontiguousarray(actions, dtype=np.float32)
        return super().action_chunk(updated)

    def close(self) -> None:
        """Disconnect TargetWS only; keep the B1K server process running."""
        self.client.close()

    def _with_behavior1k_config(self, session_ctx: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(session_ctx.get("metadata", {}))
        b1k_config = {**BEHAVIOR1K_DEFAULT_CONFIG, **self.config, **metadata.get("behavior1k", {})}
        benchmark = dict(session_ctx.get("benchmark") or {})
        if benchmark.get("task_name"):
            b1k_config["task_name"] = benchmark["task_name"]
        if benchmark.get("instance_id") is not None:
            b1k_config["instance_id"] = benchmark["instance_id"]
        if session_ctx.get("task_description"):
            b1k_config.setdefault("task_description", session_ctx["task_description"])
        metadata["behavior1k"] = b1k_config
        return {
            **session_ctx,
            "metadata": metadata,
            "behavior1k": b1k_config,
        }
