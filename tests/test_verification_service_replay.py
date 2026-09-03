from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from PhyAgentOS.providers.base import LLMResponse
from PhyAgentOS.verification.engine import VerificationEngine
from PhyAgentOS.verification.service import FORGE_TASK_PROMPT, _handler

TOKEN = "service-test-token"
REQUEST = {
    "version": "forge_verification_request_v1",
    "content": [{"type": "text", "text": "fixture evidence"}],
}
SUCCESS = {
    "verdict": "success",
    "criteria": [{"criterion": "placed", "status": "satisfied", "evidence_refs": ["after_rgb"]}],
    "evidence_refs": ["after_rgb"],
    "reason": "deterministic fixture",
    "lesson": "none",
}


class DeterministicProvider:
    def __init__(self, content: str | None = None, *, error: Exception | None = None):
        self.content = content if content is not None else json.dumps(SUCCESS)
        self.error = error
        self.calls: list[dict] = []

    async def chat_with_retry(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return LLMResponse(content=self.content)


@pytest.fixture
def service_server():
    provider = DeterministicProvider()
    engine = VerificationEngine(provider=provider, model="fixture-model", timeout_s=1.0)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(engine, TOKEN))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", provider
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def _post(base_url, payload, *, token=TOKEN):
    request = Request(
        f"{base_url}/v1/verify-task",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-PAOS-Admin-Token": token},
        method="POST",
    )
    try:
        with urlopen(request, timeout=2.0) as response:  # noqa: S310 - local fixture server
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _post_raw(base_url, body: bytes, *, token=TOKEN):
    request = Request(
        f"{base_url}/v1/verify-task",
        data=body,
        headers={"Content-Type": "application/json", "X-PAOS-Admin-Token": token},
        method="POST",
    )
    try:
        with urlopen(request, timeout=2.0) as response:  # noqa: S310 - local fixture server
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_authorized_provider_backed_verdict_is_normalized_and_replayable(service_server):
    base_url, provider = service_server
    first = _post(base_url, REQUEST)
    second = _post(base_url, REQUEST)

    assert first[0] == second[0] == 200
    assert first[1] == second[1]
    assert first[1]["verdict"] == "success"
    assert len(provider.calls) == 2
    assert provider.calls[0]["model"] == "fixture-model"
    assert provider.calls[0]["temperature"] == 0.0
    assert provider.calls[0]["messages"][0]["content"] == FORGE_TASK_PROMPT


def test_unauthorized_and_invalid_requests_fail_before_provider_call(service_server):
    base_url, provider = service_server
    unauthorized = _post(base_url, REQUEST, token="wrong-token")
    malformed = _post(base_url, {"version": "wrong", "content": []})

    assert unauthorized == (403, {"error": "verification is restricted to the Agent"})
    assert malformed[0] == 400
    assert malformed[1] == {"error": "invalid_verification_request"}
    assert provider.calls == []


@pytest.mark.parametrize(
    "body",
    [
        b'{"version":"forge_verification_request_v1","content":[NaN]}',
        b'{"version":"forge_verification_request_v1","content":[],"content":[{}]}',
    ],
)
def test_nonstandard_or_ambiguous_json_fails_before_provider_call(service_server, body):
    base_url, provider = service_server

    assert _post_raw(base_url, body) == (
        400,
        {"error": "invalid_verification_request"},
    )
    assert provider.calls == []


def test_invalid_provider_verdict_is_normalized_to_inconclusive(service_server):
    base_url, provider = service_server
    provider.content = json.dumps({"verdict": "success"})

    status, payload = _post(base_url, REQUEST)

    assert status == 200
    assert payload["verdict"] == "inconclusive"
    assert payload["verifier_status"] == "invalid_response"
    assert payload["criteria"] == []
    assert payload["reason"] == "invalid verifier response"
    assert len(provider.calls) == 1


def test_provider_failure_is_exposed_as_server_error_without_fake_success(service_server):
    base_url, provider = service_server
    provider.error = RuntimeError("fixture provider failure")

    status, payload = _post(base_url, REQUEST)

    assert status == 500
    assert payload == {"error": "verification_provider_failed"}
    assert len(provider.calls) == 1


def test_provider_timeout_uses_stable_gateway_timeout_error(service_server):
    base_url, provider = service_server
    provider.error = TimeoutError("provider detail must stay server-side")

    status, payload = _post(base_url, REQUEST)

    assert status == 504
    assert payload == {"error": "verification_provider_timeout"}
    assert "provider detail" not in json.dumps(payload)


def test_oversized_request_is_rejected_before_provider_call():
    provider = DeterministicProvider()
    engine = VerificationEngine(provider=provider, model="fixture-model", timeout_s=1.0)
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        _handler(engine, TOKEN, max_request_bytes=1024),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.server_port}"
        status, payload = _post(
            base_url,
            {
                "version": "forge_verification_request_v1",
                "content": [{"type": "text", "text": "x" * 2048}],
            },
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)

    assert status == 413
    assert payload == {"error": "verification_request_too_large"}
    assert provider.calls == []


def test_request_content_type_is_required(service_server):
    base_url, provider = service_server
    request = Request(
        f"{base_url}/v1/verify-task",
        data=json.dumps(REQUEST).encode("utf-8"),
        headers={
            "Content-Type": "text/plain",
            "X-PAOS-Admin-Token": TOKEN,
        },
        method="POST",
    )
    with pytest.raises(HTTPError) as error:
        urlopen(request, timeout=2.0)  # noqa: S310 - local fixture server
    assert error.value.code == 415
    assert json.loads(error.value.read().decode("utf-8")) == {
        "error": "content_type_must_be_application_json"
    }
    assert provider.calls == []
