"""Public task, execution, evidence, verdict, and Forge session contracts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

VerificationMode = Literal["off", "audit", "enforce", "recovery"]
VerificationVerdictName = Literal[
    "success", "failure", "replan_required", "inconclusive"
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class VerificationEvidencePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: str = "semantic_default"
    required_kinds: list[str] = Field(default_factory=lambda: ["rgb_image"])
    required_sources: list[str] = Field(default_factory=list)
    minimum_association: Literal["best_effort", "authoritative"] = "best_effort"


class TaskVerificationContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["task_verification_contract_v1"] = "task_verification_contract_v1"
    mode: VerificationMode = "off"
    goal: str = ""
    success_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    evidence_policy: VerificationEvidencePolicy = Field(
        default_factory=VerificationEvidencePolicy
    )

    @field_validator("goal")
    @classmethod
    def normalize_goal(cls, value: str) -> str:
        return value.strip()

    @field_validator("success_criteria", "constraints")
    @classmethod
    def normalize_items(cls, values: list[str]) -> list[str]:
        normalized = [str(item).strip() for item in values]
        if any(not item for item in normalized):
            raise ValueError("verification text items must be non-empty")
        return normalized

    @model_validator(mode="after")
    def require_semantic_contract(self) -> "TaskVerificationContract":
        if self.mode != "off":
            if not self.goal:
                raise ValueError("verification goal is required when mode is not off")
            if not self.success_criteria:
                raise ValueError(
                    "at least one success criterion is required when verification mode is not off"
                )
        return self


class ExecutionTimeline(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    created_at: float | None = None
    updated_at: float | None = None
    sent_at: float | None = None
    terminal_observed_at: datetime | None = None


class ExecutionError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str | None = None
    message: str = ""


class ExecutionRecord(BaseModel):
    """Immutable facts reported by Forge Gateway, never a task verdict."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["paos_execution_record_v1"] = "paos_execution_record_v1"
    runtime: Literal["forge_gateway"] = "forge_gateway"
    session_id: str
    command_id: str
    gateway_api_version: str
    gateway_instance_id: str | None = None
    action_type: str
    policy_id: str | None = None
    status: Literal[
        "queued",
        "sent",
        "running",
        "succeeded",
        "failed",
        "timed_out",
        "cancelled",
        "unknown",
    ] = "unknown"
    result_semantics: str = "command_completed"
    completion: dict[str, Any] = Field(default_factory=dict)
    timeline: ExecutionTimeline = Field(default_factory=ExecutionTimeline)
    outputs: dict[str, Any] = Field(default_factory=dict)
    error: ExecutionError | None = None


class EvidenceCaptureWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    before_command_at: datetime | None = None
    command_terminal_at: datetime | None = None
    after_command_at: datetime | None = None


class EvidenceArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    phase: Literal["before", "during", "after"]
    kind: str
    source_id: str
    captured_at: float | None = None
    received_at: datetime
    sequence: int | None = Field(default=None, ge=0)
    media_type: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(ge=0)
    uri: str
    retained: bool = True
    deleted_at: datetime | None = None

    @field_validator("uri")
    @classmethod
    def validate_uri(cls, value: str) -> str:
        normalized = value.replace("\\", "/")
        if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("evidence uri must be a safe workspace-relative path")
        return normalized


class EvidenceQuality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    complete: bool
    association_quality: Literal["best_effort", "authoritative"] = "best_effort"
    capture_authority: str = "paos_forge_adapter"
    missing_requirements: list[str] = Field(default_factory=list)
    stale_artifacts: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class EvidenceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["forge_evidence_bundle_v1"] = "forge_evidence_bundle_v1"
    bundle_id: str
    session_id: str
    command_id: str
    gateway_instance_id: str | None = None
    capture_window: EvidenceCaptureWindow = Field(default_factory=EvidenceCaptureWindow)
    artifacts: list[EvidenceArtifact] = Field(default_factory=list)
    quality: EvidenceQuality
    created_at: datetime = Field(default_factory=utc_now)


class CriterionVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion: str = Field(min_length=1)
    status: Literal["satisfied", "unsatisfied", "unknown"]
    evidence_refs: list[str] = Field(default_factory=list)


class RecoveryContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unmet_criteria: list[str] = Field(default_factory=list)
    preserved_constraints: list[str] = Field(default_factory=list)
    guidance: str = ""


class VerificationVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["verification_verdict_v1"] = "verification_verdict_v1"
    verdict: VerificationVerdictName
    criteria: list[CriterionVerdict]
    evidence_refs: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)
    lesson: str = Field(min_length=1)
    recovery_context: RecoveryContext | None = None
    verifier_status: Literal["completed", "invalid_response"] = "completed"

    @model_validator(mode="after")
    def require_recovery_context(self) -> "VerificationVerdict":
        if self.verdict == "replan_required" and self.recovery_context is None:
            raise ValueError("replan_required verdict requires recovery_context")
        statuses = [item.status for item in self.criteria]
        if self.verdict == "success" and any(status != "satisfied" for status in statuses):
            raise ValueError("success verdict requires every criterion to be satisfied")
        if self.verdict in {"failure", "replan_required"} and statuses and all(
            status == "satisfied" for status in statuses
        ):
            raise ValueError(
                f"{self.verdict} verdict requires at least one unmet or unknown criterion"
            )
        return self


class VerificationAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: str
    created_at: datetime = Field(default_factory=utc_now)
    source: Literal["auto", "tool"] = "auto"
    mode: Literal["apply", "review"] = "apply"
    verdict: VerificationVerdictName | None = None
    error: str | None = None
    abandoned: bool = False


class VerificationState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["not_requested", "pending", "running", "completed", "error"] = (
        "not_requested"
    )
    bundle_ref: str | None = None
    verdict: VerificationVerdict | None = None
    attempts: list[VerificationAttempt] = Field(default_factory=list)
    error: str | None = None
    retention: dict[str, Any] | None = None


class RecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["recovery_request_v1"] = "recovery_request_v1"
    request_id: str
    parent_session_id: str
    unmet_criteria: list[str]
    preserved_constraints: list[str]
    guidance: str
    evidence_refs: list[str]
    deadline: datetime
    dispatched_at: datetime | None = None


class ForgeTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["forge_task_request_v1"] = "forge_task_request_v1"
    task_description: str = Field(min_length=1)
    action_type: str = Field(min_length=1)
    inputs: dict[str, Any] = Field(default_factory=dict)
    verification: TaskVerificationContract = Field(default_factory=TaskVerificationContract)
    execution_timeout_s: float = Field(default=300.0, gt=0)
    source: str = "paos-agent"

    @field_validator("task_description", "action_type", "source")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Forge task text fields must be non-empty")
        return normalized

    @field_validator("inputs")
    @classmethod
    def require_json_inputs(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            json.dumps(value, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("Forge task inputs must be finite JSON values") from exc
        return value


class ForgeSessionStatus(StrEnum):
    ACCEPTED = "accepted"
    CAPTURING_BEFORE = "capturing_before"
    DISPATCHING = "dispatching"
    RUNNING = "running"
    FINALIZING = "finalizing"
    AWAITING_VERIFICATION = "awaiting_verification"
    VERIFYING = "verifying"
    AWAITING_REPLAN = "awaiting_replan"
    REPLANNED = "replanned"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


TERMINAL_FORGE_STATUSES = {
    ForgeSessionStatus.REPLANNED,
    ForgeSessionStatus.SUCCEEDED,
    ForgeSessionStatus.FAILED,
    ForgeSessionStatus.TIMED_OUT,
    ForgeSessionStatus.CANCELLED,
}

ALLOWED_FORGE_TRANSITIONS: dict[ForgeSessionStatus, set[ForgeSessionStatus]] = {
    ForgeSessionStatus.ACCEPTED: {
        ForgeSessionStatus.CAPTURING_BEFORE,
        ForgeSessionStatus.DISPATCHING,
        ForgeSessionStatus.FAILED,
        ForgeSessionStatus.CANCELLED,
    },
    ForgeSessionStatus.CAPTURING_BEFORE: {
        ForgeSessionStatus.DISPATCHING,
        ForgeSessionStatus.FAILED,
        ForgeSessionStatus.CANCELLED,
    },
    ForgeSessionStatus.DISPATCHING: {
        ForgeSessionStatus.RUNNING,
        ForgeSessionStatus.FINALIZING,
        ForgeSessionStatus.FAILED,
        ForgeSessionStatus.TIMED_OUT,
        ForgeSessionStatus.CANCELLED,
    },
    ForgeSessionStatus.RUNNING: {
        ForgeSessionStatus.FINALIZING,
        ForgeSessionStatus.FAILED,
        ForgeSessionStatus.TIMED_OUT,
        ForgeSessionStatus.CANCELLED,
    },
    ForgeSessionStatus.FINALIZING: {
        ForgeSessionStatus.AWAITING_VERIFICATION,
        ForgeSessionStatus.SUCCEEDED,
        ForgeSessionStatus.FAILED,
        ForgeSessionStatus.TIMED_OUT,
        ForgeSessionStatus.CANCELLED,
    },
    ForgeSessionStatus.AWAITING_VERIFICATION: {
        ForgeSessionStatus.VERIFYING,
        ForgeSessionStatus.FAILED,
        ForgeSessionStatus.CANCELLED,
    },
    ForgeSessionStatus.VERIFYING: {
        ForgeSessionStatus.AWAITING_VERIFICATION,
        ForgeSessionStatus.AWAITING_REPLAN,
        ForgeSessionStatus.SUCCEEDED,
        ForgeSessionStatus.FAILED,
        ForgeSessionStatus.TIMED_OUT,
        ForgeSessionStatus.CANCELLED,
    },
    ForgeSessionStatus.AWAITING_REPLAN: {
        ForgeSessionStatus.REPLANNED,
        ForgeSessionStatus.FAILED,
        ForgeSessionStatus.CANCELLED,
    },
}


def validate_forge_transition(
    current: ForgeSessionStatus, next_status: ForgeSessionStatus
) -> None:
    if current == next_status:
        return
    if next_status not in ALLOWED_FORGE_TRANSITIONS.get(current, set()):
        raise ValueError(f"invalid Forge session transition: {current} -> {next_status}")


class ForgeSessionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["forge_session_record_v1"] = "forge_session_record_v1"
    session_id: str
    command_id: str
    root_session_id: str
    parent_session_id: str | None = None
    replan_attempt: int = Field(default=0, ge=0)
    request: ForgeTaskRequest
    status: ForgeSessionStatus = ForgeSessionStatus.ACCEPTED
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    dispatch_attempted_at: datetime | None = None
    terminal_at: datetime | None = None
    execution: ExecutionRecord | None = None
    verification: VerificationState = Field(default_factory=VerificationState)
    recovery_request: RecoveryRequest | None = None
    gateway_create_response: dict[str, Any] | None = None
    gateway_last_response: dict[str, Any] | None = None
    gateway_cancel_response: dict[str, Any] | None = None
    before_snapshot_ref: str | None = None
    completion_notified_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    origin_channel: str = "cli"
    origin_chat_id: str = "direct"
    origin_session_key: str | None = None

    @field_validator("session_id", "command_id", "root_session_id")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
            raise ValueError("Forge identifiers must be non-empty path-safe strings")
        return normalized
