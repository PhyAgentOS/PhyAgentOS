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
    assert "unsupported Forge verification request" in malformed[1]["error"]
    assert provider.calls == []


def test_invalid_provider_verdict_is_normalized_to_inconclusive(service_server):
    base_url, provider = service_server
    provider.content = json.dumps({"verdict": "success"})

    status, payload = _post(base_url, REQUEST)

    assert status == 200
    assert payload["verdict"] == "inconclusive"
    assert payload["verifier_status"] == "invalid_response"
    assert payload["criteria"] == []
    assert len(provider.calls) == 1


def test_provider_failure_is_exposed_as_server_error_without_fake_success(service_server):
    base_url, provider = service_server
    provider.error = RuntimeError("fixture provider failure")

    status, payload = _post(base_url, REQUEST)

    assert status == 500
    assert payload == {"error": "fixture provider failure"}
    assert len(provider.calls) == 1
