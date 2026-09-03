"""Reproducible semantic-quality evaluation for the Verification Service."""

from __future__ import annotations

import hashlib
import json
import os
import random
import socket
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from PhyAgentOS.utils.atomic_file import atomic_write_text
from PhyAgentOS.verification.contracts import (
    TaskVerificationContract,
    VerificationVerdict,
    VerificationVerdictName,
)
from PhyAgentOS.verification.engine import VerificationEngine
from PhyAgentOS.verification.request_builder import build_verification_context_content
from PhyAgentOS.verification.service import (
    VerificationProviderSpec,
    VerificationServiceError,
    VerificationServiceProcess,
)
from PhyAgentOS.verification.validation import (
    VerificationVerdictBoundaryError,
    validate_verification_verdict_boundary,
)

EvaluationSplit = Literal["development", "held_out", "hazard"]
EvaluationMode = Literal["real_model", "fixture"]


class EvaluationConfigurationError(ValueError):
    """Raised when an evaluation input cannot be safely resolved."""


class ExpectedCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    criterion: str = Field(min_length=1)
    status: Literal["satisfied", "unsatisfied", "unknown"]


class ExpectedVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    verdict: VerificationVerdictName
    criteria: tuple[ExpectedCriterion, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_verdict_statuses(self) -> "ExpectedVerdict":
        statuses = [item.status for item in self.criteria]
        if self.verdict == "success" and any(status != "satisfied" for status in statuses):
            raise ValueError("expected success requires satisfied criteria")
        if self.verdict in {"failure", "replan_required"} and all(
            status == "satisfied" for status in statuses
        ):
            raise ValueError(f"expected {self.verdict} requires an unmet criterion")
        return self


class SemanticEvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,79}$")
    split: EvaluationSplit
    category: str = Field(min_length=1)
    context: dict[str, Any]
    valid_evidence_refs: tuple[str, ...]
    expected: ExpectedVerdict

    @field_validator("valid_evidence_refs")
    @classmethod
    def validate_refs(cls, refs: tuple[str, ...]) -> tuple[str, ...]:
        if len(refs) != len(set(refs)) or any(not ref.strip() for ref in refs):
            raise ValueError("valid_evidence_refs must be unique and non-empty")
        return refs

    @model_validator(mode="after")
    def validate_contract_binding(self) -> "SemanticEvaluationCase":
        contract = self.context.get("task_verification_contract")
        if not isinstance(contract, dict):
            raise ValueError("case context requires task_verification_contract")
        TaskVerificationContract.model_validate(contract)
        expected_criteria = [item.criterion for item in self.expected.criteria]
        if len(expected_criteria) != len(set(expected_criteria)):
            raise ValueError("expected criteria must be unique")
        if contract.get("success_criteria") != expected_criteria:
            raise ValueError("expected criteria must exactly match the task contract")
        if self.context.get("valid_evidence_refs") != list(self.valid_evidence_refs):
            raise ValueError("context valid_evidence_refs must match the case boundary")
        return self


class SemanticEvaluationDataset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["verification_semantic_eval_dataset_v1"]
    name: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    cases: tuple[SemanticEvaluationCase, ...]

    @model_validator(mode="after")
    def validate_case_ids(self) -> "SemanticEvaluationDataset":
        case_ids = [case.case_id for case in self.cases]
        if not self.cases:
            raise ValueError("evaluation dataset must contain cases")
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("evaluation case IDs must be unique")
        return self


class EvaluationThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_valid_rate_min: float = Field(ge=0.0, le=1.0)
    verdict_accuracy_min: float = Field(ge=0.0, le=1.0)
    criterion_status_accuracy_min: float = Field(ge=0.0, le=1.0)
    recovery_context_valid_rate_min: float = Field(ge=0.0, le=1.0)
    success_false_positive_rate_max: float = Field(ge=0.0, le=1.0)
    abstention_recall_min: float = Field(ge=0.0, le=1.0)


class QualityGateProviderBinding(BaseModel):
    """Versioned provider identity allowed to produce formal gate evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_name: str = Field(min_length=1)
    model: str = Field(min_length=1)
    api_base: str | None = None

    @model_validator(mode="after")
    def validate_provider_identity(self) -> "QualityGateProviderBinding":
        if self.provider_name == "custom":
            raise ValueError("custom providers cannot be quality-gate bindings")
        probe = self.model_dump(mode="python")
        if self.provider_name == "azure_openai":
            probe["api_key"] = "binding-validation-only"
        VerificationProviderSpec.model_validate(probe)
        return self


class SemanticEvaluationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["verification_semantic_eval_config_v1"]
    dataset: str = Field(min_length=1)
    output_root: str = Field(min_length=1)
    splits: tuple[EvaluationSplit, ...]
    repetitions: int = Field(default=1, ge=1, le=20)
    seed: int = 20260903
    timeout_s: float = Field(default=180.0, gt=0.0, le=3600.0, allow_inf_nan=False)
    startup_timeout_s: float = Field(default=10.0, gt=0.0, le=120.0, allow_inf_nan=False)
    quality_gate_provider: QualityGateProviderBinding
    thresholds: EvaluationThresholds

    @field_validator("splits")
    @classmethod
    def validate_splits(cls, splits: tuple[EvaluationSplit, ...]) -> tuple[EvaluationSplit, ...]:
        if not splits or len(splits) != len(set(splits)):
            raise ValueError("evaluation splits must be non-empty and unique")
        return splits


class EvaluationProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["verification_eval_provider_v1"]
    evaluation_mode: EvaluationMode
    provider_name: str = Field(min_length=1)
    model: str = Field(min_length=1)
    api_base: str | None = None
    api_key_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$")
    temperature: float = Field(default=0.0, ge=0.0, le=2.0, allow_inf_nan=False)
    max_tokens: int = Field(default=2048, ge=1, le=262_144)
    reasoning_effort: str | None = None


class EvaluationRunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_dir: Path
    status: Literal["completed", "blocked", "error"]
    quality_gate_eligible: bool
    quality_gate_passed: bool
    exit_code: int


def _strict_json_load(path: Path) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-standard JSON constant is not allowed: {value}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON object key: {key!r}")
            result[key] = value
        return result

    return json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=reject_constant,
        object_pairs_hook=reject_duplicates,
    )


def load_evaluation_inputs(
    config_path: Path,
    provider_config_path: Path,
) -> tuple[SemanticEvaluationConfig, SemanticEvaluationDataset, EvaluationProviderConfig]:
    config = SemanticEvaluationConfig.model_validate(_strict_json_load(config_path))
    dataset_path = (config_path.parent / config.dataset).resolve()
    dataset = SemanticEvaluationDataset.model_validate(_strict_json_load(dataset_path))
    provider = EvaluationProviderConfig.model_validate(_strict_json_load(provider_config_path))
    return config, dataset, provider


def _git_commit(repo_root: Path) -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _allocate_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _resolve_provider_spec(config: EvaluationProviderConfig) -> dict[str, Any]:
    api_key = None
    if config.api_key_env is not None:
        api_key = os.environ.get(config.api_key_env)
        if not api_key:
            raise EvaluationConfigurationError(
                f"required provider credential is unavailable: {config.api_key_env}"
            )
    if config.provider_name == "openai_codex":
        try:
            from oauth_cli_kit import get_token

            token = get_token()
            if not getattr(token, "access", None) or not getattr(token, "account_id", None):
                raise RuntimeError("incomplete token")
        except Exception as exc:
            raise EvaluationConfigurationError(
                "OpenAI Codex OAuth credentials are unavailable to oauth-cli-kit"
            ) from exc
    spec = {
        "provider_name": config.provider_name,
        "model": config.model,
        "api_key": api_key,
        "api_base": config.api_base,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "reasoning_effort": config.reasoning_effort,
    }
    try:
        return VerificationProviderSpec.model_validate(spec).model_dump(mode="json")
    except Exception as exc:
        raise EvaluationConfigurationError(
            f"provider specification is invalid: {type(exc).__name__}"
        ) from exc


def _create_run_dir(output_root: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = output_root / f"{timestamp}-{uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _write_json(path: Path, payload: Any) -> None:
    atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
    )


def _safe_error_code(exc: Exception) -> str:
    if isinstance(exc, VerificationVerdictBoundaryError):
        return "verdict_contract_invalid"
    if isinstance(exc, VerificationServiceError):
        message = str(exc)
        if "HTTP 504" in message:
            return "provider_timeout"
        if "HTTP 500" in message:
            return "provider_failed"
        return "verification_service_error"
    return type(exc).__name__


def _base_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    completed = [record for record in records if record["status"] == "completed"]
    verdict_correct = sum(record.get("verdict_correct", False) for record in records)
    criterion_total = sum(record.get("criterion_total", 0) for record in records)
    criterion_correct = sum(record.get("criterion_correct", 0) for record in records)
    recovery_valid = sum(record.get("recovery_context_valid", False) for record in records)
    non_success = [record for record in records if record["expected_verdict"] != "success"]
    false_success = sum(record.get("predicted_verdict") == "success" for record in non_success)
    expected_abstentions = [
        record for record in records if record["expected_verdict"] == "inconclusive"
    ]
    predicted_abstentions = [
        record for record in completed if record["predicted_verdict"] == "inconclusive"
    ]
    covered = [
        record for record in completed if record["predicted_verdict"] != "inconclusive"
    ]
    confusion = Counter(
        (record["expected_verdict"], record.get("predicted_verdict", "error"))
        for record in records
    )

    def ratio(numerator: int, denominator: int) -> float:
        return numerator / denominator if denominator else 0.0

    return {
        "attempts": total,
        "completed_attempts": len(completed),
        "contract_valid_rate": ratio(len(completed), total),
        "verdict_accuracy": ratio(verdict_correct, total),
        "criterion_status_accuracy": ratio(criterion_correct, criterion_total),
        "recovery_context_valid_rate": ratio(recovery_valid, total),
        "success_false_positive_rate": ratio(false_success, len(non_success)),
        "selective_calibration": {
            "probability_calibration_supported": False,
            "coverage": ratio(len(covered), len(completed)),
            "selective_accuracy": ratio(
                sum(record.get("verdict_correct", False) for record in covered),
                len(covered),
            ),
            "abstention_precision": ratio(
                sum(
                    record["expected_verdict"] == "inconclusive"
                    for record in predicted_abstentions
                ),
                len(predicted_abstentions),
            ),
            "abstention_recall": ratio(
                sum(
                    record.get("predicted_verdict") == "inconclusive"
                    for record in expected_abstentions
                ),
                len(expected_abstentions),
            ),
        },
        "confusion_matrix": {
            f"{expected}->{predicted}": count
            for (expected, predicted), count in sorted(confusion.items())
        },
    }


def _score(records: list[dict[str, Any]], thresholds: EvaluationThresholds) -> dict[str, Any]:
    metrics = _base_metrics(records)
    metrics["by_split"] = {
        split: _base_metrics([record for record in records if record["split"] == split])
        for split in ("development", "held_out", "hazard")
        if any(record["split"] == split for record in records)
    }
    checks = {
        "contract_valid_rate": metrics["contract_valid_rate"]
        >= thresholds.contract_valid_rate_min,
        "verdict_accuracy": metrics["verdict_accuracy"] >= thresholds.verdict_accuracy_min,
        "criterion_status_accuracy": metrics["criterion_status_accuracy"]
        >= thresholds.criterion_status_accuracy_min,
        "recovery_context_valid_rate": metrics["recovery_context_valid_rate"]
        >= thresholds.recovery_context_valid_rate_min,
        "success_false_positive_rate": metrics["success_false_positive_rate"]
        <= thresholds.success_false_positive_rate_max,
        "abstention_recall": metrics["selective_calibration"]["abstention_recall"]
        >= thresholds.abstention_recall_min,
    }
    metrics["threshold_checks"] = checks
    metrics["thresholds_passed"] = all(checks.values())
    return metrics


def _selected_cases(
    dataset: SemanticEvaluationDataset,
    config: SemanticEvaluationConfig,
    max_cases: int | None,
) -> list[SemanticEvaluationCase]:
    cases = [case for case in dataset.cases if case.split in config.splits]
    random.Random(config.seed).shuffle(cases)
    if max_cases is not None:
        if max_cases < 1:
            raise EvaluationConfigurationError("max_cases must be positive")
        cases = cases[:max_cases]
    if not cases:
        raise EvaluationConfigurationError("selected evaluation splits contain no cases")
    return cases


def _quality_gate_eligibility(
    *,
    config: SemanticEvaluationConfig,
    provider_config: EvaluationProviderConfig,
    max_cases: int | None,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if provider_config.evaluation_mode != "real_model":
        reasons.append("evaluation_mode_is_not_real_model")
    if provider_config.provider_name == "custom":
        reasons.append("custom_provider_is_not_quality_gate_trusted")
    binding = config.quality_gate_provider
    if (
        provider_config.provider_name,
        provider_config.model,
        provider_config.api_base,
    ) != (binding.provider_name, binding.model, binding.api_base):
        reasons.append("provider_identity_does_not_match_quality_gate_binding")
    if max_cases is not None:
        reasons.append("partial_case_selection")
    return not reasons, reasons


def run_semantic_evaluation(
    *,
    config_path: Path,
    provider_config_path: Path,
    repo_root: Path,
    max_cases: int | None = None,
) -> EvaluationRunSummary:
    config_path = config_path.resolve()
    provider_config_path = provider_config_path.resolve()
    repo_root = repo_root.resolve()
    config, dataset, provider_config = load_evaluation_inputs(
        config_path,
        provider_config_path,
    )
    dataset_path = (config_path.parent / config.dataset).resolve()
    output_root = (config_path.parent / config.output_root).resolve()
    selected = _selected_cases(dataset, config, max_cases)
    gate_eligible, gate_ineligibility_reasons = _quality_gate_eligibility(
        config=config,
        provider_config=provider_config,
        max_cases=max_cases,
    )
    run_dir = _create_run_dir(output_root)
    atomic_write_text(run_dir / "results.jsonl", "")
    manifest = {
        "version": "verification_semantic_eval_run_v1",
        "status": "initializing",
        "run_id": run_dir.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(repo_root),
        "config_path": str(config_path),
        "config_sha256": _sha256(config_path),
        "dataset_name": dataset.name,
        "dataset_version": dataset.dataset_version,
        "dataset_path": str(dataset_path),
        "dataset_sha256": _sha256(dataset_path),
        "provider_config_path": str(provider_config_path),
        "provider_config_sha256": _sha256(provider_config_path),
        "provider": {
            "evaluation_mode": provider_config.evaluation_mode,
            "provider_name": provider_config.provider_name,
            "model": provider_config.model,
            "api_base_configured": provider_config.api_base is not None,
            "api_key_source": provider_config.api_key_env,
            "temperature": provider_config.temperature,
            "max_tokens": provider_config.max_tokens,
            "reasoning_effort": provider_config.reasoning_effort,
        },
        "quality_gate_policy": {
            "provider_binding": config.quality_gate_provider.model_dump(mode="json"),
            "full_case_selection_required": True,
        },
        "quality_gate_eligible": False,
        "quality_gate_passed": False,
        "quality_gate_ineligibility_reasons": gate_ineligibility_reasons,
        "seed": config.seed,
        "splits": list(config.splits),
        "repetitions": config.repetitions,
        "runtime": {
            "python_version": sys.version.split()[0],
            "checkpoint_path": None,
            "checkpoint_identity": provider_config.model,
        },
        "selected_case_ids": [case.case_id for case in selected],
        "metrics_path": "metrics.json",
        "results_path": "results.jsonl",
    }
    _write_json(run_dir / "run_manifest.json", manifest)

    try:
        provider_spec = _resolve_provider_spec(provider_config)
    except EvaluationConfigurationError as exc:
        terminal_reasons = [*gate_ineligibility_reasons, "evaluation_preflight_blocked"]
        manifest["status"] = "blocked"
        manifest["blocker"] = str(exc)
        manifest["quality_gate_ineligibility_reasons"] = terminal_reasons
        manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(run_dir / "run_manifest.json", manifest)
        _write_json(
            run_dir / "metrics.json",
            {
                "status": "blocked",
                "quality_gate_eligible": False,
                "quality_gate_passed": False,
                "quality_gate_ineligibility_reasons": terminal_reasons,
                "blocker": str(exc),
            },
        )
        return EvaluationRunSummary(
            run_dir=run_dir,
            status="blocked",
            quality_gate_eligible=False,
            quality_gate_passed=False,
            exit_code=2,
        )

    service = VerificationServiceProcess(
        engine=VerificationEngine(
            provider=object(),
            model="parent-process-does-not-run-inference",
            timeout_s=config.timeout_s,
        ),
        host="127.0.0.1",
        port=_allocate_loopback_port(),
        session_secret=uuid4().hex,
        provider_spec=provider_spec,
        startup_timeout_s=config.startup_timeout_s,
        max_request_bytes=64 * 1024 * 1024,
    )
    records: list[dict[str, Any]] = []
    manifest["status"] = "running"
    _write_json(run_dir / "run_manifest.json", manifest)
    results_path = run_dir / "results.jsonl"
    try:
        service.start()
        for case in selected:
            for repetition in range(config.repetitions):
                started = time.monotonic()
                record: dict[str, Any] = {
                    "case_id": case.case_id,
                    "split": case.split,
                    "category": case.category,
                    "repetition": repetition,
                    "expected_verdict": case.expected.verdict,
                }
                try:
                    data = service.verify_task(build_verification_context_content(case.context))
                    verdict = VerificationVerdict.model_validate(data)
                    validate_verification_verdict_boundary(
                        expected_criteria=[item.criterion for item in case.expected.criteria],
                        valid_evidence_refs=set(case.valid_evidence_refs),
                        verdict=verdict,
                    )
                    expected_status = {
                        item.criterion: item.status for item in case.expected.criteria
                    }
                    actual_status = {item.criterion: item.status for item in verdict.criteria}
                    expected_unmet = {
                        item.criterion
                        for item in case.expected.criteria
                        if item.status != "satisfied"
                    }
                    recovery_context_valid = (
                        verdict.recovery_context is not None
                        and bool(verdict.recovery_context.guidance.strip())
                        and set(verdict.recovery_context.unmet_criteria) == expected_unmet
                        if verdict.verdict == "replan_required"
                        else verdict.recovery_context is None
                    )
                    record.update(
                        {
                            "status": "completed",
                            "predicted_verdict": verdict.verdict,
                            "verdict_correct": verdict.verdict == case.expected.verdict,
                            "criterion_total": len(expected_status),
                            "criterion_correct": sum(
                                actual_status.get(criterion) == status
                                for criterion, status in expected_status.items()
                            ),
                            "recovery_context_valid": recovery_context_valid,
                            "verdict": verdict.model_dump(mode="json"),
                        }
                    )
                except Exception as exc:
                    record.update(
                        {
                            "status": "error",
                            "error_code": _safe_error_code(exc),
                            "verdict_correct": False,
                            "criterion_total": len(case.expected.criteria),
                            "criterion_correct": 0,
                            "recovery_context_valid": False,
                        }
                    )
                record["latency_ms"] = round((time.monotonic() - started) * 1000, 3)
                records.append(record)
                with results_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
    except Exception as exc:
        terminal_reasons = [*gate_ineligibility_reasons, "evaluation_runtime_error"]
        manifest["status"] = "error"
        manifest["error_code"] = _safe_error_code(exc)
        manifest["quality_gate_ineligibility_reasons"] = terminal_reasons
        manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(run_dir / "run_manifest.json", manifest)
        _write_json(
            run_dir / "metrics.json",
            {
                "status": "error",
                "quality_gate_eligible": False,
                "quality_gate_passed": False,
                "quality_gate_ineligibility_reasons": terminal_reasons,
                "error_code": _safe_error_code(exc),
            },
        )
        return EvaluationRunSummary(
            run_dir=run_dir,
            status="error",
            quality_gate_eligible=False,
            quality_gate_passed=False,
            exit_code=2,
        )
    finally:
        service.stop()

    metrics = _score(records, config.thresholds)
    quality_gate_passed = gate_eligible and metrics["thresholds_passed"]
    metrics.update(
        {
            "status": "completed",
            "quality_gate_eligible": gate_eligible,
            "quality_gate_passed": quality_gate_passed,
            "quality_gate_ineligibility_reasons": gate_ineligibility_reasons,
            "evaluation_mode": provider_config.evaluation_mode,
        }
    )
    _write_json(run_dir / "metrics.json", metrics)
    manifest["status"] = "completed"
    manifest["quality_gate_eligible"] = gate_eligible
    manifest["quality_gate_passed"] = quality_gate_passed
    manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(run_dir / "run_manifest.json", manifest)
    return EvaluationRunSummary(
        run_dir=run_dir,
        status="completed",
        quality_gate_eligible=gate_eligible,
        quality_gate_passed=quality_gate_passed,
        exit_code=0 if quality_gate_passed else 1,
    )
