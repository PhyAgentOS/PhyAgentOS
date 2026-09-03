from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from PhyAgentOS.verification.engine import VerificationEngine
from PhyAgentOS.verification.service import (
    VERIFICATION_SERVICE_ID,
    VerificationServiceError,
    VerificationServiceProcess,
)

SUCCESS = {
    "verdict": "success",
    "criteria": [
        {
            "criterion": "placed",
            "status": "satisfied",
            "evidence_refs": ["after_rgb"],
        }
    ],
    "evidence_refs": ["after_rgb"],
    "reason": "deterministic subprocess fixture",
    "lesson": "Preserve the verified placement evidence.",
}


class _UpstreamState:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.authorization: list[str | None] = []
        self.status = 200
        self.delay_s = 0.0
        self.verdict = SUCCESS


def _upstream_handler(state: _UpstreamState):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            content_length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(content_length))
            state.requests.append(payload)
            state.authorization.append(self.headers.get("Authorization"))
            if state.delay_s:
                time.sleep(state.delay_s)
            if state.status != 200:
                self._send({"error": {"message": "bounded upstream failure"}}, state.status)
                return
            self._send(
                {
                    "id": "chatcmpl-verification-fixture",
                    "object": "chat.completion",
                    "created": 0,
                    "model": payload.get("model", "fixture-model"),
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": json.dumps(state.verdict),
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                },
                200,
            )

        def _send(self, payload: dict[str, Any], status: int) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


@contextmanager
def _openai_compatible_upstream() -> Iterator[tuple[str, _UpstreamState]]:
    state = _UpstreamState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _upstream_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _service(*, upstream_url: str, timeout_s: float = 1.0) -> VerificationServiceProcess:
    return VerificationServiceProcess(
        engine=VerificationEngine(provider=object(), model="parent-only", timeout_s=timeout_s),
        host="127.0.0.1",
        port=_unused_local_port(),
        session_secret="subprocess-conformance-secret",
        provider_spec={
            "provider_name": "custom",
            "model": "fixture-model",
            "api_key": "fixture-api-key",
            "api_base": upstream_url,
            "temperature": 0.0,
            "max_tokens": 321,
        },
        startup_timeout_s=5.0,
        max_request_bytes=1024 * 1024,
    )


def test_provider_spec_starts_production_subprocess_and_cleans_it_up():
    with _openai_compatible_upstream() as (upstream_url, upstream):
        service = _service(upstream_url=upstream_url)
        service.start()
        child = service._process
        try:
            assert child is not None
            assert child.poll() is None

            verdict = service.verify_task(
                [{"type": "text", "text": "deterministic evidence"}]
            )

            assert verdict["verdict"] == SUCCESS["verdict"]
            assert verdict["criteria"] == SUCCESS["criteria"]
            assert verdict["evidence_refs"] == SUCCESS["evidence_refs"]
            assert verdict["reason"] == SUCCESS["reason"]
            assert verdict["lesson"] == SUCCESS["lesson"]
            assert verdict["version"] == "verification_verdict_v1"
            assert verdict["verifier_status"] == "completed"
            assert verdict["recovery_context"] is None
            assert len(upstream.requests) == 1
            request = upstream.requests[0]
            assert request["model"] == "fixture-model"
            assert request["temperature"] == 0.0
            assert request["max_tokens"] == 321
            assert request["messages"][0]["role"] == "system"
            assert request["messages"][1]["content"] == [
                {"type": "text", "text": "deterministic evidence"}
            ]
            assert upstream.authorization == ["Bearer fixture-api-key"]
        finally:
            service.stop()

        assert child.poll() is not None


def test_provider_failure_crosses_real_subprocess_as_stable_error():
    with _openai_compatible_upstream() as (upstream_url, upstream):
        upstream.status = 400
        service = _service(upstream_url=upstream_url)
        service.start()
        try:
            with pytest.raises(VerificationServiceError, match=r"HTTP 500.*verification_provider_failed"):
                service.verify_task([{"type": "text", "text": "fixture evidence"}])
        finally:
            service.stop()

        assert len(upstream.requests) == 1


def test_provider_timeout_crosses_real_subprocess_as_stable_error():
    with _openai_compatible_upstream() as (upstream_url, upstream):
        upstream.delay_s = 0.5
        service = _service(upstream_url=upstream_url, timeout_s=0.1)
        service.start()
        try:
            with pytest.raises(VerificationServiceError, match=r"HTTP 504.*verification_provider_timeout"):
                service.verify_task([{"type": "text", "text": "fixture evidence"}])
        finally:
            service.stop()

        # Cancellation may happen before the HTTP client finishes writing the
        # request; either zero or one upstream request is valid for this gate.
        assert len(upstream.requests) <= 1


def test_private_readiness_requires_the_child_session_token():
    with _openai_compatible_upstream() as (upstream_url, _):
        service = _service(upstream_url=upstream_url)
        service.start()
        try:
            from urllib.error import HTTPError
            from urllib.request import Request, urlopen

            with pytest.raises(HTTPError) as error:
                urlopen(Request(service._url("/readyz"), method="GET"), timeout=1.0)  # noqa: S310
            assert error.value.code == 403
            assert json.loads(error.value.read()) == {
                "error": "verification is restricted to the Agent"
            }

            request = Request(
                service._url("/readyz"),
                headers={"X-PAOS-Admin-Token": service.session_token},
                method="GET",
            )
            with urlopen(request, timeout=1.0) as response:  # noqa: S310
                assert json.loads(response.read()) == {
                    "ok": True,
                    "service": VERIFICATION_SERVICE_ID,
                }
        finally:
            service.stop()
