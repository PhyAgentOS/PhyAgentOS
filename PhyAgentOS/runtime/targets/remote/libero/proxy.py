"""LIBERO-specific remote target proxy."""

from __future__ import annotations

from typing import Any

import numpy as np

from PhyAgentOS.runtime.communication.target_ws_client import TargetWSClient
from PhyAgentOS.runtime.targets.remote.proxy import RemoteTargetProxy
from PhyAgentOS.runtime.watchdog.errors import TargetProtocolError


LIBERO_DEFAULT_CONFIG = {
    "benchmark_name": "libero_spatial",
    "task_id": 0,
    "init_state_id": 0,
    "camera_height": 256,
    "camera_width": 256,
    "action_dim": 7,
    "max_chunk_size": 50,
    "control_mode": "relative",
}


class LiberoRemoteTargetProxy(RemoteTargetProxy):
    """Remote target proxy with LIBERO-specific defaults and action validation."""

    def __init__(self, client: TargetWSClient, *, config: dict[str, Any] | None = None):
        merged = {**LIBERO_DEFAULT_CONFIG, **dict(config or {})}
        super().__init__(client, config=merged)

    def configure_session(self, session_ctx: dict[str, Any]) -> dict[str, Any]:
        merged_ctx = self._with_libero_config(session_ctx)
        return super().configure_session(merged_ctx)

    def reset(self, session_ctx: dict[str, Any]) -> dict[str, Any]:
        merged_ctx = self._with_libero_config(session_ctx)
        return super().reset(merged_ctx)

    def action_chunk(self, executable_action_chunk: dict[str, Any]) -> dict[str, Any]:
        actions = np.asarray(executable_action_chunk.get("actions"), dtype=np.float32)
        if actions.ndim != 2:
            raise TargetProtocolError(f"LIBERO actions must have shape [T,7], got {actions.shape}")
        if actions.shape[1] != 7:
            raise TargetProtocolError(f"LIBERO actions must have shape [T,7], got {actions.shape}")
        if not np.isfinite(actions).all():
            raise TargetProtocolError("LIBERO actions contain NaN or Inf")
        max_chunk_size = int(self.config.get("max_chunk_size", LIBERO_DEFAULT_CONFIG["max_chunk_size"]))
        if actions.shape[0] > max_chunk_size:
            raise TargetProtocolError(f"LIBERO action chunk too large: {actions.shape[0]} > {max_chunk_size}")
        updated = dict(executable_action_chunk)
        updated["actions"] = np.ascontiguousarray(actions, dtype=np.float32)
        return super().action_chunk(updated)

    def _with_libero_config(self, session_ctx: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(session_ctx.get("metadata", {}))
        libero_config = {**LIBERO_DEFAULT_CONFIG, **self.config, **metadata.get("libero", {})}
        benchmark = session_ctx.get("benchmark") or {}
        if isinstance(benchmark, dict):
            suite_id = benchmark.get("suite_id")
            if suite_id:
                libero_config["benchmark_name"] = str(suite_id)
            if benchmark.get("task_index") is not None:
                libero_config["task_id"] = int(benchmark["task_index"])
            if benchmark.get("instance_id") is not None:
                libero_config["init_state_id"] = int(benchmark["instance_id"])
        metadata["libero"] = libero_config
        return {
            **session_ctx,
            "metadata": metadata,
            "libero": libero_config,
        }
