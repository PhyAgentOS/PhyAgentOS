from __future__ import annotations

import sys
from pathlib import Path

import pytest

from robotwin20_adapter import JsonlProcessWorkerClient, ProcessWorkerConfig, ProcessWorkerError

FIXTURE = Path(__file__).parent / "fixtures" / "jsonl_worker.py"


def _client(mode="normal", **overrides):
    values = {
        "command": (sys.executable, str(FIXTURE), "--mode", mode),
        "cwd": FIXTURE.parent,
        "startup_timeout_s": 1,
        "request_timeout_s": 1,
        "shutdown_timeout_s": 1,
    }
    values.update(overrides)
    return JsonlProcessWorkerClient(ProcessWorkerConfig(**values))


def test_worker_client_starts_lazily_releases_and_can_restart():
    client = _client()
    first = client.request({"request_id": "request-1"})
    client.release()
    second = client.request({"request_id": "request-2"})
    client.release()
    assert first["status"] == second["status"] == "available"
    assert first["pid"] != second["pid"]


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("unavailable", "reported unavailable"),
        ("wrong-id", "identity mismatch"),
        ("invalid-json", "non-JSON"),
        ("timeout", "timed out"),
    ],
)
def test_worker_protocol_failures_are_typed_and_fail_closed(mode, message):
    client = _client(mode, request_timeout_s=0.05)
    with pytest.raises(ProcessWorkerError, match=message):
        client.request({"request_id": "request-1"})


def test_worker_config_rejects_path_lookup_and_relative_cwd(tmp_path):
    with pytest.raises(ValueError, match="absolute file"):
        ProcessWorkerConfig(command=("python", str(FIXTURE)))
    with pytest.raises(ValueError, match="absolute directory"):
        ProcessWorkerConfig(command=(sys.executable, str(FIXTURE)), cwd=Path("relative"))
