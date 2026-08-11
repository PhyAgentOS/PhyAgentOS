"""WebSocket policy client for BEHAVIOR-1K ``serve_b1k.py`` (OmniGibson protocol).

Differs from ``OpenPIClientPolicyWrapper``:
- Sends full OmniGibson observation dict (not LeRobot pi0.5 keys).
- Receives ``{"action": ...}`` instead of ``{"actions": ...}``.
- Supports ``{"reset": true}`` at episode start.
"""

from __future__ import annotations

import socket
import time
from typing import Any

import numpy as np
import requests
import websocket

from PhyAgentOS.runtime.errors import (
    PolicyConnectionError,
    PolicyProtocolError,
    PolicyTimeoutError,
)
from PhyAgentOS.runtime.policy.base_client import BasePolicyClient
from PhyAgentOS.runtime.policy.msgpack_numpy import packb, unpackb


class Behavior1kWebsocketPolicyClient(BasePolicyClient):
    def __init__(self, host: str, port: int, timeout_s: float = 180.0):
        self.host = host
        self.port = int(port)
        self.timeout_s = float(timeout_s)
        self.uri = f"ws://{host}:{port}"
        self.health_url = f"http://{host}:{port}/healthz"
        self.metadata: dict[str, Any] = {}
        self._sent_reset = False
        self._ws = self._connect()

    def _connect(self):
        self._wait_for_health()
        try:
            ws = websocket.create_connection(
                self.uri,
                timeout=self.timeout_s,
                enable_multithread=True,
                skip_utf8_validation=True,
            )
            ws.settimeout(self.timeout_s)
            metadata = ws.recv()
        except (socket.timeout, TimeoutError) as exc:
            raise PolicyTimeoutError(f"timed out connecting to B1K policy server: {self.uri}") from exc
        except Exception as exc:
            raise PolicyConnectionError(f"failed to connect to B1K policy server {self.uri}: {exc}") from exc
        if isinstance(metadata, str):
            raise PolicyProtocolError(f"B1K policy server returned text metadata: {metadata}")
        try:
            unpacked = unpackb(metadata)
        except Exception as exc:
            raise PolicyProtocolError(f"failed to decode B1K policy metadata: {exc}") from exc
        if isinstance(unpacked, dict):
            self.metadata = unpacked
        return ws

    def _wait_for_health(self) -> None:
        deadline = time.monotonic() + min(self.timeout_s, 120.0)
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                response = requests.get(self.health_url, timeout=2)
                if response.ok:
                    return
            except Exception as exc:
                last_error = exc
            time.sleep(2.0)
        hint = f" ({last_error})" if last_error else ""
        raise PolicyConnectionError(f"B1K policy health check failed for {self.health_url}{hint}")

    def reset(self) -> None:
        self._sent_reset = False

    def infer(self, observation: dict[str, Any]) -> dict[str, Any]:
        if not self._sent_reset:
            try:
                self._ws.send_binary(packb({"reset": True}))
            except Exception as exc:
                raise PolicyConnectionError(f"B1K policy reset failed: {exc}") from exc
            self._sent_reset = True

        started = time.perf_counter()
        try:
            self._ws.send_binary(packb(observation))
            response = self._ws.recv()
        except (socket.timeout, TimeoutError) as exc:
            raise PolicyTimeoutError(f"B1K policy inference timed out after {self.timeout_s:.3f}s") from exc
        except Exception as exc:
            raise PolicyConnectionError(f"B1K policy inference websocket error: {exc}") from exc

        if isinstance(response, str):
            raise PolicyProtocolError(f"B1K policy server returned text error: {response}")
        try:
            out = unpackb(response)
        except Exception as exc:
            raise PolicyProtocolError(f"failed to decode B1K policy response: {exc}") from exc
        if not isinstance(out, dict):
            raise PolicyProtocolError("B1K policy response must be a dict")

        actions_raw = out.get("actions")
        if actions_raw is None:
            actions_raw = out.get("action")
        if actions_raw is None:
            raise PolicyProtocolError("B1K policy response missing `action` or `actions`")

        actions = np.asarray(actions_raw, dtype=np.float32)
        if actions.ndim == 1:
            actions = actions[None, :]
        if actions.ndim == 3 and actions.shape[0] == 1:
            actions = actions[0]
        if actions.ndim != 2:
            raise PolicyProtocolError(f"B1K policy action must have shape [T,A], got {actions.shape}")

        latency_ms = (time.perf_counter() - started) * 1000
        timing = dict(out.get("server_timing") or {})
        return {
            "actions": np.ascontiguousarray(actions, dtype=np.float32),
            "policy_meta": {
                "backend": "behavior1k_websocket",
                "policy_latency_ms": latency_ms,
                "server_timing": timing,
                "chunk_size": int(actions.shape[0]),
                "action_dim": int(actions.shape[1]),
            },
        }

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:
            pass
