"""Synchronous WebSocket client for target runtime RPC."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse, urlunparse

from PhyAgentOS.runtime.communication.envelope import RuntimeEnvelope
from PhyAgentOS.runtime.communication.msgpack_codec import decode_msgpack, encode_msgpack
from PhyAgentOS.runtime.errors import TargetConnectionError, TargetProtocolError


class TargetWSClient:
    """Minimal msgpack-over-WebSocket client for target runtime calls."""

    def __init__(
        self,
        endpoint: str,
        *,
        target_id: str | None = None,
        timeout_s: float = 30.0,
        connect_on_init: bool = False,
    ):
        self.endpoint = endpoint
        self.target_id = target_id
        self.timeout_s = float(timeout_s)
        self._seq = 0
        self._ws = None
        if connect_on_init:
            self.connect()

    def connect(self) -> None:
        if self._ws is not None:
            return
        try:
            import websocket
        except ImportError as exc:
            raise TargetConnectionError(
                "websocket-client is required for targetws:// endpoints"
            ) from exc

        try:
            self._ws = websocket.create_connection(
                self._websocket_url(),
                timeout=self.timeout_s,
            )
        except Exception as exc:  # pragma: no cover - depends on external transport
            raise TargetConnectionError(f"failed to connect target endpoint {self.endpoint}: {exc}") from exc

    def call(
        self,
        message_type: str,
        payload: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        skillruntime_id: str | None = None,
        episode_id: str | None = None,
        trace_id: str | None = None,
        expected_response_type: str | None = None,
    ) -> dict[str, Any]:
        self.connect()
        self._seq += 1
        request = RuntimeEnvelope(
            type=message_type,
            session_id=session_id,
            target_id=self.target_id,
            skillruntime_id=skillruntime_id,
            episode_id=episode_id,
            seq=self._seq,
            timestamp_ns=time.time_ns(),
            trace_id=trace_id,
            payload=payload or {},
        )
        try:
            self._ws.send_binary(encode_msgpack(request))
            response = decode_msgpack(self._ws.recv())
        except Exception as exc:
            raise TargetProtocolError(f"target RPC {message_type} failed: {exc}") from exc

        if response.type == "runtime.error":
            error_code = response.payload.get("error_code", "TARGET_RPC_ERROR")
            message = response.payload.get("message", "target runtime returned an error")
            raise TargetProtocolError(f"{error_code}: {message}")
        expected_type = expected_response_type or self._default_response_type(message_type)
        mismatches = []
        if response.type != expected_type:
            mismatches.append(f"type {response.type!r} != {expected_type!r}")
        if response.seq != request.seq:
            mismatches.append(f"seq {response.seq} != {request.seq}")
        if response.session_id != request.session_id:
            mismatches.append(f"session_id {response.session_id!r} != {request.session_id!r}")
        if response.target_id != request.target_id:
            mismatches.append(f"target_id {response.target_id!r} != {request.target_id!r}")
        if response.skillruntime_id != request.skillruntime_id:
            mismatches.append(f"skillruntime_id {response.skillruntime_id!r} != {request.skillruntime_id!r}")
        if mismatches:
            raise TargetProtocolError(
                f"target RPC {message_type} returned mismatched response: {', '.join(mismatches)}"
            )
        return response.payload

    def close(self) -> None:
        if self._ws is None:
            return
        try:
            self._ws.close()
        finally:
            self._ws = None

    @property
    def connected(self) -> bool:
        return self._ws is not None

    def _websocket_url(self) -> str:
        parsed = urlparse(self.endpoint)
        if parsed.scheme != "targetws":
            raise TargetConnectionError(f"expected targetws:// endpoint, got {self.endpoint}")
        return urlunparse(("ws", parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))

    def _default_response_type(self, message_type: str) -> str:
        return {
            "target.observe": "target.observation",
            "agent_tool.call": "agent_tool.result",
        }.get(message_type, message_type)
