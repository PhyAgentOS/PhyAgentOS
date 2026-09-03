from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from PhyAgentOS.verification import evaluation
from PhyAgentOS.verification.evaluation import (
    load_evaluation_inputs,
    run_semantic_evaluation,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = REPO_ROOT / "evals/verification/semantic_verifier_v1.json"
CONFIG_PATH = REPO_ROOT / "evals/verification/evaluation_config_v1.json"
PROVIDER_PATH = REPO_ROOT / "evals/verification/provider.openai_codex.example.json"


def _case(case_id: str, marker: str, expected_verdict: str, expected_status: str) -> dict:
    criterion = f"Criterion for {marker}."
    return {
        "case_id": case_id,
        "split": "held_out",
        "category": "fixture",
        "context": {
            "case_marker": marker,
            "task_verification_contract": {
                "success_criteria": [criterion],
            },
            "valid_evidence_refs": ["after_evidence"],
        },
        "valid_evidence_refs": ["after_evidence"],
        "expected": {
            "verdict": expected_verdict,
            "criteria": [{"criterion": criterion, "status": expected_status}],
        },
    }


def _write_inputs(tmp_path: Path, *, provider: dict) -> tuple[Path, Path]:
    dataset = {
        "version": "verification_semantic_eval_dataset_v1",
        "name": "fixture-dataset",
        "dataset_version": "1.0.0",
        "cases": [
            _case("fixture_success", "fixture_success", "success", "satisfied"),
            _case("fixture_replan", "fixture_replan", "replan_required", "unsatisfied"),
            _case(
                "fixture_inconclusive",
                "fixture_inconclusive",
                "inconclusive",
                "unknown",
            ),
        ],
    }
    config = {
        "version": "verification_semantic_eval_config_v1",
        "dataset": "dataset.json",
        "output_root": "runs",
        "splits": ["held_out"],
        "repetitions": 1,
        "seed": 7,
        "timeout_s": 2.0,
        "startup_timeout_s": 5.0,
        "quality_gate_provider": {
            "provider_name": "openai_codex",
            "model": "openai-codex/gpt-5.1-codex",
            "api_base": None,
        },
        "thresholds": {
            "contract_valid_rate_min": 1.0,
            "verdict_accuracy_min": 1.0,
            "criterion_status_accuracy_min": 1.0,
            "recovery_context_valid_rate_min": 1.0,
            "success_false_positive_rate_max": 0.0,
            "abstention_recall_min": 1.0,
        },
    }
    dataset_path = tmp_path / "dataset.json"
    config_path = tmp_path / "config.json"
    provider_path = tmp_path / "provider.json"
    dataset_path.write_text(json.dumps(dataset), encoding="utf-8")
    config_path.write_text(json.dumps(config), encoding="utf-8")
    provider_path.write_text(json.dumps(provider), encoding="utf-8")
    return config_path, provider_path


@contextmanager
def _model_server():
    requests: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length))
            requests.append(payload)
            prompt = json.dumps(payload.get("messages"), ensure_ascii=False)
            recovery_context = None
            if "fixture_success" in prompt:
                verdict = "success"
                status = "satisfied"
                criterion = "Criterion for fixture_success."
                refs = ["after_evidence"]
            elif "fixture_replan" in prompt:
                verdict = "replan_required"
                status = "unsatisfied"
                criterion = "Criterion for fixture_replan."
                refs = ["after_evidence"]
                recovery_context = {
                    "unmet_criteria": [criterion],
                    "preserved_constraints": [],
                    "guidance": "Re-observe before a bounded recovery.",
                }
            else:
                verdict = "inconclusive"
                status = "unknown"
                criterion = "Criterion for fixture_inconclusive."
                refs = []
            response = {
                "id": "fixture",
                "object": "chat.completion",
                "created": 0,
                "model": payload["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "verdict": verdict,
                                    "criteria": [
                                        {
                                            "criterion": criterion,
                                            "status": status,
                                            "evidence_refs": refs,
                                        }
                                    ],
                                    "evidence_refs": refs,
                                    "reason": "fixture",
                                    "lesson": "fixture",
                                    "recovery_context": recovery_context,
                                }
                            ),
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }
            body = json.dumps(response).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def test_versioned_dataset_has_separate_development_held_out_and_hazard_splits():
    config, dataset, provider = load_evaluation_inputs(CONFIG_PATH, PROVIDER_PATH)

    assert config.splits == ("held_out", "hazard")
    assert provider.evaluation_mode == "real_model"
    assert len(dataset.cases) == 10
    assert {case.split for case in dataset.cases} == {
        "development",
        "held_out",
        "hazard",
    }
    assert len({case.case_id for case in dataset.cases}) == len(dataset.cases)


def test_dataset_loader_rejects_duplicate_json_keys(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"version":"verification_semantic_eval_config_v1",'
        '"version":"verification_semantic_eval_config_v1"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        load_evaluation_inputs(config_path, PROVIDER_PATH)


def test_config_rejects_custom_quality_gate_provider_binding(tmp_path):
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    config["quality_gate_provider"] = {
        "provider_name": "custom",
        "model": "fixture-model",
        "api_base": "http://127.0.0.1:9000/v1",
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="custom providers cannot be quality-gate bindings"):
        load_evaluation_inputs(config_path, PROVIDER_PATH)


def test_fixture_smoke_runs_through_production_subprocess_but_cannot_pass_gate(tmp_path):
    with _model_server() as (api_base, requests):
        config_path, provider_path = _write_inputs(
            tmp_path,
            provider={
                "version": "verification_eval_provider_v1",
                "evaluation_mode": "fixture",
                "provider_name": "custom",
                "model": "fixture-model",
                "api_base": api_base,
                "api_key_env": None,
                "temperature": 0.0,
                "max_tokens": 512,
                "reasoning_effort": None,
            },
        )
        summary = run_semantic_evaluation(
            config_path=config_path,
            provider_config_path=provider_path,
            repo_root=REPO_ROOT,
        )

    assert summary.status == "completed"
    assert summary.exit_code == 1
    assert summary.quality_gate_eligible is False
    assert summary.quality_gate_passed is False
    assert len(requests) == 3

    metrics = json.loads((summary.run_dir / "metrics.json").read_text())
    manifest = json.loads((summary.run_dir / "run_manifest.json").read_text())
    results = [
        json.loads(line)
        for line in (summary.run_dir / "results.jsonl").read_text().splitlines()
    ]
    assert metrics["thresholds_passed"] is True
    assert metrics["verdict_accuracy"] == 1.0
    assert metrics["recovery_context_valid_rate"] == 1.0
    assert metrics["selective_calibration"]["probability_calibration_supported"] is False
    assert metrics["selective_calibration"]["abstention_recall"] == 1.0
    assert manifest["provider"]["evaluation_mode"] == "fixture"
    assert manifest["provider"]["api_key_source"] is None
    assert manifest["quality_gate_ineligibility_reasons"] == [
        "evaluation_mode_is_not_real_model",
        "custom_provider_is_not_quality_gate_trusted",
        "provider_identity_does_not_match_quality_gate_binding",
    ]
    assert "no-key" not in json.dumps(manifest)
    assert len(results) == 3


def test_missing_real_model_credential_creates_blocked_non_eligible_run(tmp_path, monkeypatch):
    monkeypatch.delenv("PAOS_TEST_MISSING_API_KEY", raising=False)
    config_path, provider_path = _write_inputs(
        tmp_path,
        provider={
            "version": "verification_eval_provider_v1",
            "evaluation_mode": "real_model",
            "provider_name": "custom",
            "model": "unavailable-model",
            "api_base": "https://example.invalid/v1",
            "api_key_env": "PAOS_TEST_MISSING_API_KEY",
            "temperature": 0.0,
            "max_tokens": 512,
            "reasoning_effort": None,
        },
    )

    first = run_semantic_evaluation(
        config_path=config_path,
        provider_config_path=provider_path,
        repo_root=REPO_ROOT,
    )
    second = run_semantic_evaluation(
        config_path=config_path,
        provider_config_path=provider_path,
        repo_root=REPO_ROOT,
    )

    assert first.status == second.status == "blocked"
    assert first.exit_code == second.exit_code == 2
    assert first.run_dir != second.run_dir
    metrics = json.loads((first.run_dir / "metrics.json").read_text())
    manifest = json.loads((first.run_dir / "run_manifest.json").read_text())
    assert metrics == {
        "blocker": "required provider credential is unavailable: PAOS_TEST_MISSING_API_KEY",
        "quality_gate_eligible": False,
        "quality_gate_ineligibility_reasons": [
            "custom_provider_is_not_quality_gate_trusted",
            "provider_identity_does_not_match_quality_gate_binding",
            "evaluation_preflight_blocked",
        ],
        "quality_gate_passed": False,
        "status": "blocked",
    }
    assert len(manifest["provider_config_sha256"]) == 64
    assert manifest["runtime"]["checkpoint_identity"] == "unavailable-model"
    assert (first.run_dir / "results.jsonl").read_text() == ""


def test_invalid_provider_spec_creates_blocked_run_instead_of_leaking_schema_error(tmp_path):
    config_path, provider_path = _write_inputs(
        tmp_path,
        provider={
            "version": "verification_eval_provider_v1",
            "evaluation_mode": "real_model",
            "provider_name": "custom",
            "model": "invalid-model",
            "api_base": None,
            "api_key_env": None,
            "temperature": 0.0,
            "max_tokens": 512,
            "reasoning_effort": None,
        },
    )

    summary = run_semantic_evaluation(
        config_path=config_path,
        provider_config_path=provider_path,
        repo_root=REPO_ROOT,
    )

    assert summary.status == "blocked"
    assert summary.exit_code == 2
    metrics = json.loads((summary.run_dir / "metrics.json").read_text())
    assert metrics["status"] == "blocked"
    assert metrics["quality_gate_passed"] is False
    assert metrics["blocker"] == "provider specification is invalid: ValidationError"


def test_real_model_label_on_custom_fixture_endpoint_cannot_pass_quality_gate(tmp_path):
    with _model_server() as (api_base, requests):
        config_path, provider_path = _write_inputs(
            tmp_path,
            provider={
                "version": "verification_eval_provider_v1",
                "evaluation_mode": "real_model",
                "provider_name": "custom",
                "model": "fixture-model",
                "api_base": api_base,
                "api_key_env": None,
                "temperature": 0.0,
                "max_tokens": 512,
                "reasoning_effort": None,
            },
        )
        summary = run_semantic_evaluation(
            config_path=config_path,
            provider_config_path=provider_path,
            repo_root=REPO_ROOT,
        )

    assert len(requests) == 3
    assert summary.status == "completed"
    assert summary.quality_gate_eligible is False
    assert summary.quality_gate_passed is False
    assert summary.exit_code == 1
    metrics = json.loads((summary.run_dir / "metrics.json").read_text())
    assert metrics["thresholds_passed"] is True
    assert metrics["quality_gate_ineligibility_reasons"] == [
        "custom_provider_is_not_quality_gate_trusted",
        "provider_identity_does_not_match_quality_gate_binding",
    ]


def test_partial_case_selection_is_never_quality_gate_eligible(tmp_path):
    with _model_server() as (api_base, requests):
        config_path, provider_path = _write_inputs(
            tmp_path,
            provider={
                "version": "verification_eval_provider_v1",
                "evaluation_mode": "fixture",
                "provider_name": "custom",
                "model": "fixture-model",
                "api_base": api_base,
                "api_key_env": None,
                "temperature": 0.0,
                "max_tokens": 512,
                "reasoning_effort": None,
            },
        )
        summary = run_semantic_evaluation(
            config_path=config_path,
            provider_config_path=provider_path,
            repo_root=REPO_ROOT,
            max_cases=1,
        )

    assert len(requests) == 1
    assert summary.quality_gate_eligible is False
    metrics = json.loads((summary.run_dir / "metrics.json").read_text())
    assert "partial_case_selection" in metrics["quality_gate_ineligibility_reasons"]


def test_subprocess_start_failure_is_persisted_as_terminal_error(tmp_path, monkeypatch):
    config_path, provider_path = _write_inputs(
        tmp_path,
        provider={
            "version": "verification_eval_provider_v1",
            "evaluation_mode": "fixture",
            "provider_name": "custom",
            "model": "fixture-model",
            "api_base": "http://127.0.0.1:9/v1",
            "api_key_env": None,
            "temperature": 0.0,
            "max_tokens": 512,
            "reasoning_effort": None,
        },
    )

    def fail_start(self):
        raise TimeoutError("fixture startup failure")

    monkeypatch.setattr(evaluation.VerificationServiceProcess, "start", fail_start)
    summary = run_semantic_evaluation(
        config_path=config_path,
        provider_config_path=provider_path,
        repo_root=REPO_ROOT,
    )

    assert summary.status == "error"
    assert summary.exit_code == 2
    manifest = json.loads((summary.run_dir / "run_manifest.json").read_text())
    metrics = json.loads((summary.run_dir / "metrics.json").read_text())
    assert manifest["status"] == "error"
    assert manifest["error_code"] == "TimeoutError"
    assert "evaluation_runtime_error" in manifest["quality_gate_ineligibility_reasons"]
    assert metrics["status"] == "error"
    assert metrics["quality_gate_passed"] is False
    assert metrics["quality_gate_ineligibility_reasons"] == manifest[
        "quality_gate_ineligibility_reasons"
    ]
