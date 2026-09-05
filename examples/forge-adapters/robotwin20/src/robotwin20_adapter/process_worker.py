"""Bounded JSON-lines client for model workers in isolated environments."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from typing import Any, Mapping
from uuid import uuid4


class ProcessWorkerError(RuntimeError):
    """An isolated worker failed its lifecycle or request protocol."""


@dataclass(frozen=True)
class ProcessWorkerConfig:
    command: tuple[str, ...]
    cwd: Path | None = None
    environment: Mapping[str, str] = field(default_factory=dict)
    startup_timeout_s: float = 180.0
    request_timeout_s: float = 60.0
    shutdown_timeout_s: float = 10.0
    max_line_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        if not self.command or any(not isinstance(item, str) or not item for item in self.command):
            raise ValueError("worker command must contain non-empty strings")
        executable = Path(self.command[0])
        if not executable.is_absolute() or not executable.is_file():
            raise ValueError("worker executable must be an existing absolute file")
        if self.cwd is not None and (not self.cwd.is_absolute() or not self.cwd.is_dir()):
            raise ValueError("worker cwd must be an existing absolute directory")
        if any(not isinstance(key, str) or not key or not isinstance(value, str) for key, value in self.environment.items()):
            raise ValueError("worker environment overrides must be string pairs")
        for name in ("startup_timeout_s", "request_timeout_s", "shutdown_timeout_s"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                raise ValueError(f"{name} must be positive")
        if (
            isinstance(self.max_line_bytes, bool)
            or not isinstance(self.max_line_bytes, int)
            or self.max_line_bytes < 256
        ):
            raise ValueError("max_line_bytes must be at least 256")


class JsonlProcessWorkerClient:
    """Lazily start one worker and serialize bounded request/reply exchanges."""

    def __init__(self, config: ProcessWorkerConfig) -> None:
        if not isinstance(config, ProcessWorkerConfig):
            raise TypeError("config must be ProcessWorkerConfig")
        self.config = config
        self._process: subprocess.Popen[str] | None = None
        self._stdout_queue: queue.Queue[str | None] = queue.Queue()
        self._stderr_tail: deque[str] = deque(maxlen=40)
        self._lock = threading.Lock()

    def request(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(payload, Mapping):
            raise TypeError("worker payload must be a mapping")
        request_id = payload.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise ProcessWorkerError("worker payload requires request_id")
        with self._lock:
            try:
                self._ensure_started()
                self._write(dict(payload))
                return self._read_reply(request_id, self.config.request_timeout_s)
            except Exception:
                self._abort()
                raise

    def release(self) -> None:
        with self._lock:
            process = self._process
            if process is None:
                return
            request_id = uuid4().hex
            try:
                if process.poll() is None:
                    self._write({"command": "shutdown", "request_id": request_id})
                    reply = self._read_reply(request_id, self.config.shutdown_timeout_s)
                    if reply.get("status") != "shutdown":
                        raise ProcessWorkerError("worker rejected shutdown")
                    try:
                        process.wait(timeout=self.config.shutdown_timeout_s)
                    except subprocess.TimeoutExpired as exc:
                        raise ProcessWorkerError("worker did not exit after shutdown") from exc
            finally:
                self._abort()

    @property
    def stderr_tail(self) -> tuple[str, ...]:
        return tuple(self._stderr_tail)

    def _ensure_started(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        self._stdout_queue = queue.Queue()
        self._stderr_tail.clear()
        environment = os.environ.copy()
        environment.update(self.config.environment)
        try:
            process = subprocess.Popen(
                list(self.config.command),
                cwd=self.config.cwd,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                start_new_session=True,
            )
        except OSError as exc:
            raise ProcessWorkerError("worker process could not be started") from exc
        self._process = process
        assert process.stdout is not None and process.stderr is not None
        threading.Thread(target=self._drain_stdout, args=(process,), daemon=True).start()
        threading.Thread(target=self._drain_stderr, args=(process,), daemon=True).start()
        deadline = monotonic() + self.config.startup_timeout_s
        while True:
            message = self._read_json(deadline)
            if message.get("event") == "worker_ready":
                return
            if message.get("event") == "worker_unavailable":
                raise ProcessWorkerError("worker reported unavailable during startup")

    def _write(self, payload: Mapping[str, Any]) -> None:
        process = self._process
        if process is None or process.poll() is not None or process.stdin is None:
            raise ProcessWorkerError("worker is not running")
        try:
            line = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
            if len(line.encode("utf-8")) > self.config.max_line_bytes:
                raise ProcessWorkerError("worker request exceeds max_line_bytes")
            process.stdin.write(line + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise ProcessWorkerError("worker request transport failed") from exc

    def _read_reply(self, request_id: str, timeout_s: float) -> Mapping[str, Any]:
        deadline = monotonic() + timeout_s
        while True:
            message = self._read_json(deadline)
            if "event" in message:
                continue
            if message.get("request_id") != request_id:
                raise ProcessWorkerError("worker response request identity mismatch")
            return message

    def _read_json(self, deadline: float) -> dict[str, Any]:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise ProcessWorkerError("worker response timed out")
        try:
            line = self._stdout_queue.get(timeout=remaining)
        except queue.Empty as exc:
            raise ProcessWorkerError("worker response timed out") from exc
        if line is None:
            detail = self._stderr_tail[-1] if self._stderr_tail else "no stderr"
            raise ProcessWorkerError(f"worker exited before a complete response: {detail}")
        if len(line.encode("utf-8")) > self.config.max_line_bytes:
            raise ProcessWorkerError("worker response exceeds max_line_bytes")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ProcessWorkerError("worker emitted non-JSON stdout") from exc
        if not isinstance(value, dict):
            raise ProcessWorkerError("worker response must be a JSON object")
        return value

    def _drain_stdout(self, process: subprocess.Popen[str]) -> None:
        assert process.stdout is not None
        try:
            for line in process.stdout:
                self._stdout_queue.put(line.rstrip("\n"))
        finally:
            self._stdout_queue.put(None)

    def _drain_stderr(self, process: subprocess.Popen[str]) -> None:
        assert process.stderr is not None
        for line in process.stderr:
            self._stderr_tail.append(line.rstrip("\n")[:2000])

    def _abort(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()


__all__ = ["JsonlProcessWorkerClient", "ProcessWorkerConfig", "ProcessWorkerError"]
