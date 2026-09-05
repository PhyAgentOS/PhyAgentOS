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


def test_graspgen_model_output_isolated_from_jsonl_stdout(monkeypatch, capsys):
    import importlib.util

    worker_path = Path(__file__).parents[1] / "runtime" / "graspgen_worker.py"
    monkeypatch.syspath_prepend(str(worker_path.parent))
    spec = importlib.util.spec_from_file_location("graspgen_worker_for_test", worker_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def noisy_load():
        print("model initialization log")

    def noisy_handle(request):
        print("model inference log")
        return {"request_id": request["request_id"], "status": "empty", "candidates": [], "funnel": {"decoded": 0, "canonicalized": 0, "deduplicated": 0, "retained": 0}}

    observed = {}

    def fake_serve(provider, load, handle, *, schema_version):
        observed["load"] = load
        observed["handle"] = handle
        observed["schema_version"] = schema_version
        load()
        handle({"request_id": "request-1"})
        return 0

    monkeypatch.setattr(module, "_load", noisy_load)
    monkeypatch.setattr(module, "_handle", noisy_handle)
    monkeypatch.setattr(module, "serve", fake_serve)
    assert module.main(
        [
            "--stdio-worker",
            "--checkpoint", "/tmp/checkpoint",
            "--config", "/tmp/config",
        ]
    ) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "model initialization log" in captured.err
    assert "model inference log" in captured.err
    assert observed["schema_version"] == "paos-grasp-worker/v1"
