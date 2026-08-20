"""Asynchronous best-effort observation collection from Forge Gateway."""

from __future__ import annotations

import asyncio
import base64
import binascii
import inspect
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse, urlunparse


class ForgeObservationError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class CapturedImage:
    source_id: str
    sequence: int
    captured_at: float | None
    received_at: datetime
    media_type: str
    data: bytes


@dataclass(frozen=True)
class CapturedState:
    received_at: datetime
    payload: dict[str, Any]


@dataclass(frozen=True)
class ObservationSnapshot:
    captured_at: datetime
    images: dict[str, CapturedImage] = field(default_factory=dict)
    state: CapturedState | None = None


ConnectionFactory = Callable[[str, float], Awaitable[Any] | Any]


async def _default_connection_factory(url: str, timeout_s: float) -> Any:
    from websockets.asyncio.client import connect

    return await connect(url, open_timeout=timeout_s, proxy=None)


class ForgeObservationCollector:
    """Keep only the newest validated frame for each requested source."""

    def __init__(
        self,
        base_url: str,
        *,
        required_image_sources: list[str],
        max_artifact_bytes: int,
        require_state: bool = False,
        connection_timeout_s: float = 2.0,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.required_image_sources = tuple(dict.fromkeys(required_image_sources))
        self.max_artifact_bytes = max(1, int(max_artifact_bytes))
        self.require_state = bool(require_state)
        self.connection_timeout_s = max(0.1, float(connection_timeout_s))
        self.connection_factory = connection_factory or _default_connection_factory
        self._condition = asyncio.Condition()
        self._latest_images: dict[str, CapturedImage] = {}
        self._latest_state: CapturedState | None = None
        self._errors: list[str] = []
        self._closed = False
        self._tasks: list[asyncio.Task] = []
        self._connections: list[Any] = []

    @property
    def errors(self) -> list[str]:
        return list(self._errors)

    async def start(self) -> None:
        if self._tasks:
            return
        self._closed = False
        for name, path, handler in (
            ("images", "/ws/images", self._handle_image_message),
            ("state", "/ws/state", self._handle_state_message),
        ):
            self._tasks.append(
                asyncio.create_task(
                    self._receive_loop(path, handler), name=f"paos-forge-{name}"
                )
            )

    async def close(self) -> None:
        self._closed = True
        async with self._condition:
            self._condition.notify_all()
        for connection in list(self._connections):
            try:
                result = connection.close()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                pass
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        self._connections.clear()

    async def wait_for_before(self, timeout_s: float) -> ObservationSnapshot:
        return await self._wait_for_snapshot(None, None, timeout_s)

    async def wait_for_after(
        self,
        before: ObservationSnapshot,
        *,
        terminal_observed_at: datetime,
        timeout_s: float,
    ) -> ObservationSnapshot:
        return await self._wait_for_snapshot(before, terminal_observed_at, timeout_s)

    async def latest_snapshot(self) -> ObservationSnapshot:
        async with self._condition:
            return self._snapshot()

    async def _wait_for_snapshot(
        self,
        before: ObservationSnapshot | None,
        terminal_observed_at: datetime | None,
        timeout_s: float,
    ) -> ObservationSnapshot:
        deadline = asyncio.get_running_loop().time() + max(0.0, float(timeout_s))
        async with self._condition:
            while not self._closed:
                if self._ready(before, terminal_observed_at):
                    return self._snapshot(terminal_observed_at)
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                try:
                    await asyncio.wait_for(self._condition.wait(), min(remaining, 0.2))
                except TimeoutError:
                    pass
        phase = "before" if before is None else "fresh after"
        raise ForgeObservationError(
            f"FORGE_EVIDENCE_UNAVAILABLE: missing {phase} sources: "
            + ", ".join(self._missing(before, terminal_observed_at) or ["unknown"])
        )

    def _ready(
        self,
        before: ObservationSnapshot | None,
        terminal_observed_at: datetime | None,
    ) -> bool:
        for source in self.required_image_sources:
            current = self._latest_images.get(source)
            if current is None:
                return False
            if before is not None:
                previous = before.images.get(source)
                if (
                    previous is None
                    or current.sequence <= previous.sequence
                    or terminal_observed_at is None
                    or current.received_at < terminal_observed_at
                ):
                    return False
        if self.require_state:
            if self._latest_state is None:
                return False
            if terminal_observed_at is not None and self._latest_state.received_at < terminal_observed_at:
                return False
        return True

    def _missing(
        self,
        before: ObservationSnapshot | None,
        terminal_observed_at: datetime | None,
    ) -> list[str]:
        missing: list[str] = []
        for source in self.required_image_sources:
            current = self._latest_images.get(source)
            previous = before.images.get(source) if before is not None else None
            if current is None or (
                before is not None
                and (
                    previous is None
                    or current.sequence <= previous.sequence
                    or terminal_observed_at is None
                    or current.received_at < terminal_observed_at
                )
            ):
                missing.append(f"image:{source}")
        if self.require_state and (
            self._latest_state is None
            or (
                terminal_observed_at is not None
                and self._latest_state.received_at < terminal_observed_at
            )
        ):
            missing.append("state:ws/state")
        return missing

    def _snapshot(
        self, terminal_observed_at: datetime | None = None
    ) -> ObservationSnapshot:
        state = self._latest_state
        if (
            state is not None
            and terminal_observed_at is not None
            and state.received_at < terminal_observed_at
        ):
            state = None
        return ObservationSnapshot(
            captured_at=utc_now(),
            images=dict(self._latest_images),
            state=state,
        )

    async def _receive_loop(self, path: str, handler: Callable[[Any], Awaitable[None]]) -> None:
        url = self._ws_url(path)
        while not self._closed:
            connection = None
            try:
                connection = self.connection_factory(url, self.connection_timeout_s)
                if inspect.isawaitable(connection):
                    connection = await connection
                self._connections.append(connection)
                while not self._closed:
                    raw = await connection.recv()
                    if raw is None:
                        raise ForgeObservationError(f"Gateway WebSocket {path} closed")
                    await handler(raw)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not self._closed:
                    await self._record_error(f"{path}: {exc}")
                    await asyncio.sleep(0.1)
            finally:
                if connection is not None:
                    try:
                        result = connection.close()
                        if inspect.isawaitable(result):
                            await result
                    except Exception:
                        pass
                    if connection in self._connections:
                        self._connections.remove(connection)

    async def _handle_image_message(self, raw: Any) -> None:
        try:
            payload = self._parse_json(raw, "image")
            if payload.get("type") != "image":
                return
            source = payload.get("id")
            if not isinstance(source, str) or not source:
                raise ValueError("image message has no source id")
            if self.required_image_sources and source not in self.required_image_sources:
                return
            sequence = int(payload["seq"])
            if sequence < 0:
                raise ValueError("negative sequence")
            timestamp = payload.get("timestamp")
            captured_at = float(timestamp) if timestamp is not None else None
            if captured_at is not None and not math.isfinite(captured_at):
                raise ValueError("non-finite timestamp")
            media_type = str(payload.get("content_type") or "").split(";", 1)[0].lower()
            if not media_type.startswith("image/"):
                raise ValueError(f"unsupported media type: {media_type!r}")
            encoded = payload.get("data")
            if not isinstance(encoded, str):
                raise ValueError("image data must be base64 string")
            if len(encoded) > ((self.max_artifact_bytes + 2) // 3) * 4 + 4:
                raise ValueError("encoded image exceeds configured artifact limit")
            data = base64.b64decode(encoded, validate=True)
            if not data or len(data) > self.max_artifact_bytes:
                raise ValueError("decoded image exceeds configured artifact limit")
            if not self._matches_media_type(data, media_type):
                raise ValueError("image bytes do not match declared media type")
        except (KeyError, TypeError, ValueError, binascii.Error, json.JSONDecodeError) as exc:
            await self._record_error(f"invalid image message: {exc}")
            return
        image = CapturedImage(source, sequence, captured_at, utc_now(), media_type, data)
        async with self._condition:
            previous = self._latest_images.get(source)
            if previous is None or image.sequence > previous.sequence:
                self._latest_images[source] = image
                self._condition.notify_all()

    async def _handle_state_message(self, raw: Any) -> None:
        try:
            raw_size = len(raw) if isinstance(raw, bytes) else len(str(raw).encode("utf-8"))
            if raw_size > self.max_artifact_bytes:
                raise ValueError("state message exceeds configured artifact limit")
            payload = self._parse_json(raw, "state")
        except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            await self._record_error(f"invalid state message: {exc}")
            return
        async with self._condition:
            self._latest_state = CapturedState(utc_now(), payload)
            self._condition.notify_all()

    @staticmethod
    def _parse_json(raw: Any, kind: str) -> dict[str, Any]:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        if not isinstance(raw, str):
            raise ValueError(f"{kind} WebSocket message must be text JSON")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError(f"{kind} WebSocket message must be an object")
        return value

    async def _record_error(self, message: str) -> None:
        async with self._condition:
            self._errors.append(message)
            self._errors = self._errors[-50:]
            self._condition.notify_all()

    def _ws_url(self, path: str) -> str:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"}:
            raise ForgeObservationError(f"unsupported Gateway URL: {self.base_url}")
        return urlunparse(
            (
                "wss" if parsed.scheme == "https" else "ws",
                parsed.netloc,
                parsed.path.rstrip("/") + path,
                "",
                "",
                "",
            )
        )

    @staticmethod
    def _matches_media_type(data: bytes, media_type: str) -> bool:
        if media_type in {"image/jpeg", "image/jpg"}:
            return data.startswith(b"\xff\xd8\xff")
        if media_type == "image/png":
            return data.startswith(b"\x89PNG\r\n\x1a\n")
        if media_type == "image/webp":
            return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
        return False
