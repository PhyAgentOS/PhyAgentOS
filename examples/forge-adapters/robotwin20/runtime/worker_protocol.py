"""Small stdio protocol shared by isolated perception worker entrypoints."""

from __future__ import annotations

import json
import sys
from typing import Any, Callable, Mapping

SCHEMA_VERSION = "paos-perception-worker/v1"


def emit_event(provider: str, event: str, *, request_id: str | None = None) -> None:
    value = {"schema_version": SCHEMA_VERSION, "provider": provider, "event": event}
    if request_id is not None:
        value["request_id"] = request_id
    _emit(value)


def serve(provider: str, load: Callable[[], None], handle: Callable[[Mapping[str, Any]], Mapping[str, Any]]) -> int:
    try:
        emit_event(provider, "model_load_started")
        load()
    except Exception as exc:
        print(f"{provider} model load failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        emit_event(provider, "worker_unavailable")
        return 2
    emit_event(provider, "model_load_completed")
    emit_event(provider, "worker_ready")
    for line in sys.stdin:
        request: dict[str, Any] | None = None
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("request must be a JSON object")
            request_id = request.get("request_id")
            if not isinstance(request_id, str) or not request_id:
                raise ValueError("request_id must be non-empty")
            if request.get("command") == "shutdown":
                emit_event(provider, "shutdown_started", request_id=request_id)
                _emit({"request_id": request_id, "status": "shutdown"})
                return 0
            emit_event(provider, "request_started", request_id=request_id)
            reply = dict(handle(request))
            if reply.get("request_id") != request_id:
                raise ValueError("handler changed request_id")
            _emit(reply)
            emit_event(provider, "request_completed", request_id=request_id)
        except Exception as exc:
            print(f"{provider} request failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            request_id = request.get("request_id") if isinstance(request, dict) else "invalid"
            _emit({"request_id": request_id, "status": "unavailable"})
    return 0


def _emit(value: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


__all__ = ["SCHEMA_VERSION", "emit_event", "serve"]
