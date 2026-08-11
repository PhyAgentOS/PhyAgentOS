"""Built-in deterministic action bridges."""

from __future__ import annotations

from typing import Any

import numpy as np

from PhyAgentOS.runtime.adapters.base import BaseActionBridge
from PhyAgentOS.runtime.errors import AdapterError


class SafetyClampBridge(BaseActionBridge):
    """Validate numeric action chunks without changing action semantics."""

    def apply(self, action_chunk: dict[str, Any], target_info: dict[str, Any]) -> dict[str, Any]:
        actions = np.asarray(action_chunk.get("actions"), dtype=np.float32)
        if actions.ndim != 2:
            raise AdapterError(f"actions must have shape [T,A], got {actions.shape}")
        if not np.isfinite(actions).all():
            raise AdapterError("actions contain NaN or Inf")
        action_dim = int(target_info.get("action_dim", actions.shape[1]))
        if actions.shape[1] != action_dim:
            raise AdapterError(f"action shape mismatch: expected [T,{action_dim}], got {actions.shape}")
        max_chunk_size = target_info.get("max_chunk_size")
        if max_chunk_size is not None and actions.shape[0] > int(max_chunk_size):
            raise AdapterError(f"action chunk too large: {actions.shape[0]} > {max_chunk_size}")
        updated = dict(action_chunk)
        updated["actions"] = actions
        provenance = dict(updated.get("provenance", {}))
        provenance["bridges_applied"] = [*provenance.get("bridges_applied", []), "bridge://safety_clamp"]
        updated["provenance"] = provenance
        return updated
