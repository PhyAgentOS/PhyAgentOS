"""Isaac Sim-specific remote target proxy."""

from __future__ import annotations

from typing import Any

import numpy as np

from PhyAgentOS.runtime.communication.target_ws_client import TargetWSClient
from PhyAgentOS.runtime.errors import TargetProtocolError
from PhyAgentOS.runtime.targets.remote.proxy import RemoteTargetProxy

ISAAC_DEFAULT_CONFIG = {
    "robot_id": "",
    "camera_height": 224,
    "camera_width": 224,
    "action_dim": 8,
    "max_chunk_size": 50,
    "max_steps": 600,
    "image_key": "camera1",
    "wrist_image_key": "camera2",
}


class IsaacSimRemoteTargetProxy(RemoteTargetProxy):
    """Remote target proxy with Isaac Sim rollout defaults and action validation."""

    def __init__(self, client: TargetWSClient, *, config: dict[str, Any] | None = None):
        merged = {**ISAAC_DEFAULT_CONFIG, **dict(config or {})}
        super().__init__(client, config=merged)

    def configure_session(self, session_ctx: dict[str, Any]) -> dict[str, Any]:
        return super().configure_session(self._with_isaac_config(session_ctx))

    def reset(self, session_ctx: dict[str, Any]) -> dict[str, Any]:
        return super().reset(self._with_isaac_config(session_ctx))

    def action_chunk(self, executable_action_chunk: dict[str, Any]) -> dict[str, Any]:
        actions = np.asarray(executable_action_chunk.get("actions"), dtype=np.float32)
        if actions.ndim != 2:
            raise TargetProtocolError(f"Isaac actions must have shape [T,A], got {actions.shape}")
        action_dim = int(self.config.get("action_dim", ISAAC_DEFAULT_CONFIG["action_dim"]))
        if actions.shape[1] != action_dim:
            raise TargetProtocolError(f"Isaac actions must have shape [T,{action_dim}], got {actions.shape}")
        if not np.isfinite(actions).all():
            raise TargetProtocolError("Isaac actions contain NaN or Inf")
        max_chunk_size = int(self.config.get("max_chunk_size", ISAAC_DEFAULT_CONFIG["max_chunk_size"]))
        if actions.shape[0] > max_chunk_size:
            raise TargetProtocolError(f"Isaac action chunk too large: {actions.shape[0]} > {max_chunk_size}")
        updated = dict(executable_action_chunk)
        updated["actions"] = np.ascontiguousarray(actions, dtype=np.float32)
        robot_id = str(self.config.get("robot_id", "")).strip()
        if robot_id:
            updated.setdefault("robot_id", robot_id)
        return super().action_chunk(updated)

    def close(self) -> None:
        """Disconnect TargetWS only; keep the Isaac Sim server process running."""
        self.client.close()

    def _with_isaac_config(self, session_ctx: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(session_ctx.get("metadata", {}))
        isaac_config = {**ISAAC_DEFAULT_CONFIG, **self.config, **metadata.get("isaacsim", {})}
        metadata["isaacsim"] = isaac_config
        reset_payload = dict(session_ctx.get("reset_payload") or {})
        if session_ctx.get("task_description") and "vla_task_text" not in reset_payload:
            reset_payload.setdefault("vla_task_text", session_ctx["task_description"])
        return {
            **session_ctx,
            "metadata": metadata,
            "isaacsim": isaac_config,
            "reset_payload": reset_payload,
        }
