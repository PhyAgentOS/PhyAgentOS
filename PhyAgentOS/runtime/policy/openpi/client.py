"""OpenPI-compatible remote policy client wrapper."""

from __future__ import annotations

import socket
import time
from typing import Any

import numpy as np
import websocket

from PhyAgentOS.runtime.errors import (
    PolicyConnectionError,
    PolicyProtocolError,
    PolicyTimeoutError,
)
from PhyAgentOS.runtime.policy.base_client import BasePolicyClient
from PhyAgentOS.runtime.policy.msgpack_numpy import packb, unpackb


class OpenPIClientPolicyWrapper(BasePolicyClient):
    """OpenPI websocket protocol client without depending on ``openpi-client``."""

    def __init__(self, host: str, port: int, timeout_s: float = 5.0):
        self.host = host
        self.port = int(port)
        self.timeout_s = float(timeout_s)
        self.uri = host if host.startswith("ws") else f"ws://{host}:{self.port}"
        if host.startswith("ws") and port:
            self.uri = f"{host}:{self.port}" if ":" not in host.removeprefix("ws://").removeprefix("wss://") else host
        self.metadata: dict[str, Any] = {}
        self._ws = self._connect()

    def _connect(self):
        try:
            ws = websocket.create_connection(self.uri, timeout=self.timeout_s, enable_multithread=True)
            ws.settimeout(self.timeout_s)
            metadata = ws.recv()
        except (socket.timeout, TimeoutError) as exc:
            raise PolicyTimeoutError(f"timed out connecting to policy server: {self.uri}") from exc
        except Exception as exc:
            raise PolicyConnectionError(f"failed to connect to policy server {self.uri}: {exc}") from exc
        if isinstance(metadata, str):
            raise PolicyProtocolError(f"policy server returned text metadata: {metadata}")
        try:
            unpacked = unpackb(metadata)
        except Exception as exc:
            raise PolicyProtocolError(f"failed to decode policy server metadata: {exc}") from exc
        if isinstance(unpacked, dict):
            self.metadata = unpacked
        return ws

    def infer(self, observation: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            self._ws.send_binary(packb(observation))
            response = self._ws.recv()
        except (socket.timeout, TimeoutError) as exc:
            raise PolicyTimeoutError(f"policy inference timed out after {self.timeout_s:.3f}s") from exc
        except Exception as exc:
            raise PolicyConnectionError(f"policy inference websocket error: {exc}") from exc
        if isinstance(response, str):
            raise PolicyProtocolError(f"policy server returned text error: {response}")
        try:
            out = unpackb(response)
        except Exception as exc:
            raise PolicyProtocolError(f"failed to decode policy response: {exc}") from exc
        latency_ms = (time.perf_counter() - started) * 1000
        if not isinstance(out, dict) or "actions" not in out:
            raise PolicyProtocolError("OpenPI response missing `actions`.")
        actions = np.asarray(out["actions"], dtype=np.float32)
        if actions.ndim == 1:
            actions = actions[None, :]
        if actions.ndim != 2:
            raise PolicyProtocolError(f"OpenPI `actions` must have shape [A] or [T,A], got {actions.shape}")
        out["actions"] = actions
        out.setdefault("policy_meta", {})
        out["policy_meta"]["policy_latency_ms"] = latency_ms
        return out

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:
            pass
