"""Domain adapters built on the strict PAOS state-file protocol."""

from __future__ import annotations

import inspect
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from PhyAgentOS.state_io.protocol import (
    ParsedStateFile,
    ProjectionResult,
    StateFileError,
    canonical_sha256,
    parse_state_file,
    write_projection,
)


@dataclass(frozen=True)
class TargetShadowReport:
    """Deterministic validation result; it never authorizes an Action."""

    valid: bool
    errors: tuple[str, ...]
    differences: tuple[str, ...]
    candidate_sha256: str | None
    motion_authorized: bool = False


class TargetProfileApproval(BaseModel):
    """Human approval bound to TARGETS content and its comparison baseline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_by: str = Field(min_length=1)
    confirmed_at: str = Field(min_length=1)
    decision: str = "approve"

    @field_validator("approval_id", "approved_by")
    @classmethod
    def normalize_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or any(char in normalized for char in "/\\"):
            raise ValueError("approval identity must be non-empty and path-safe")
        return normalized

    @field_validator("confirmed_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        normalized = value.strip()
        try:
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("confirmed_at must be ISO-8601") from exc
        if parsed.tzinfo is None:
            raise ValueError("confirmed_at must include a timezone")
        return normalized

    @field_validator("decision")
    @classmethod
    def require_approval(cls, value: str) -> str:
        if value != "approve":
            raise ValueError("decision must be 'approve'")
        return value


@dataclass(frozen=True)
class TargetProfileCandidate:
    """Approved capability candidate; never an Action-admission decision."""

    source_sha256: str
    baseline_sha256: str
    profile_id: str
    data: Mapping[str, Any]
    differences: tuple[str, ...]
    motion_authorized: bool = False


@dataclass(frozen=True)
class SessionPreview:
    """Dry-run task previews produced without touching AgentTaskStore."""

    source: ParsedStateFile
    previews: tuple[dict[str, Any], ...]


class SessionCompileError(StateFileError):
    """Raised when an approved session cannot be promoted safely."""


class SessionCompileApproval(BaseModel):
    """Human approval bound to one immutable SESSIONS.md content digest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_by: str = Field(min_length=1)
    confirmed_at: str = Field(min_length=1)
    decision: str = "approve"

    @field_validator("approval_id", "approved_by")
    @classmethod
    def normalize_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or any(char in normalized for char in "/\\"):
            raise ValueError("approval identity must be non-empty and path-safe")
        return normalized

    @field_validator("confirmed_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        normalized = value.strip()
        try:
            parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("confirmed_at must be ISO-8601") from exc
        if parsed.tzinfo is None:
            raise ValueError("confirmed_at must include a timezone")
        return normalized

    @field_validator("decision")
    @classmethod
    def require_approval(cls, value: str) -> str:
        if value != "approve":
            raise ValueError("decision must be 'approve'")
        return value


@dataclass(frozen=True)
class SessionCompileResult:
    """Promotion result; it contains no execution or motion authorization."""

    source_sha256: str
    compiled: tuple[Any, ...]
    reused: tuple[Any, ...]
    motion_authorized: bool = False


def _state_origin_key(source_sha256: str, session_id: str) -> str:
    return f"statefile+sessions://{source_sha256}/{session_id}"


def _approval_for_source(
    approval: SessionCompileApproval | Mapping[str, Any], source_sha256: str
) -> SessionCompileApproval:
    try:
        normalized = (
            approval
            if isinstance(approval, SessionCompileApproval)
            else SessionCompileApproval.model_validate(approval)
        )
    except Exception as exc:
        raise SessionCompileError("invalid human approval credential") from exc
    if normalized.source_sha256 != source_sha256:
        raise SessionCompileError(
            "human approval is bound to a different SESSIONS.md content digest"
        )
    return normalized


def _require_keys(value: Mapping[str, Any], required: set[str], label: str) -> list[str]:
    errors: list[str] = []
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required)
    if missing:
        errors.append(f"{label} missing field(s): {', '.join(missing)}")
    if unknown:
        errors.append(f"{label} unknown field(s): {', '.join(unknown)}")
    return errors


def _finite_number(value: Any, label: str) -> str | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        return f"{label} must be a finite number"
    return None


def _validate_limits(limits: Any) -> list[str]:
    if not isinstance(limits, dict) or not limits:
        return ["limits must be a non-empty object"]
    errors: list[str] = []
    for name, value in limits.items():
        if not isinstance(name, str) or not name.strip():
            errors.append("limits contains an invalid name")
            continue
        if isinstance(value, dict):
            unknown = sorted(set(value) - {"min", "max", "value"})
            if unknown:
                errors.append(f"limits.{name} unknown field(s): {', '.join(unknown)}")
                continue
            if "min" in value and "max" in value:
                lower, upper = value["min"], value["max"]
                if isinstance(lower, list) and isinstance(upper, list):
                    if len(lower) != len(upper):
                        errors.append(f"limits.{name} min/max lengths differ")
                        continue
                    pairs = zip(lower, upper)
                else:
                    pairs = [(lower, upper)]
                for index, (left, right) in enumerate(pairs):
                    left_error = _finite_number(left, f"limits.{name}.min[{index}]")
                    right_error = _finite_number(right, f"limits.{name}.max[{index}]")
                    if left_error:
                        errors.append(left_error)
                    if right_error:
                        errors.append(right_error)
                    if not left_error and not right_error and float(left) > float(right):
                        errors.append(f"limits.{name} min exceeds max at index {index}")
                continue
            value = value.get("value")
        if isinstance(value, list):
            for index, item in enumerate(value):
                error = _finite_number(item, f"limits.{name}[{index}]")
                if error:
                    errors.append(error)
        else:
            error = _finite_number(value, f"limits.{name}")
            if error:
                errors.append(error)
    return errors


def _validate_targets(data: Mapping[str, Any], baseline: Mapping[str, Any] | None) -> TargetShadowReport:
    required = {"profile_id", "observation_modalities", "action_space", "limits"}
    errors = _require_keys(data, required, "targets")
    for field in ("profile_id",):
        if field in data:
            value = data[field]
            if not isinstance(value, str) or not value.strip():
                errors.append(f"targets.{field} must be a non-empty string")
            elif value.strip() in {".", ".."} or any(char in value for char in "/\\"):
                errors.append(f"targets.{field} must be path-safe")
    for field in ("observation_modalities", "action_space"):
        value = data.get(field)
        if not isinstance(value, list) or not value or not all(isinstance(item, str) and item.strip() for item in value):
            errors.append(f"targets.{field} must be a non-empty list of strings")
    if "limits" in data:
        errors.extend(_validate_limits(data["limits"]))
    differences: list[str] = []
    if baseline is not None:
        for key in sorted(set(data) | set(baseline)):
            if data.get(key) != baseline.get(key):
                differences.append(key)
    digest = None if errors else canonical_sha256(dict(data))
    return TargetShadowReport(not errors, tuple(errors), tuple(differences), digest)


def parse_targets_shadow(path: str | Path, *, baseline: Mapping[str, Any] | None = None) -> TargetShadowReport:
    """Parse `TARGETS.md` and validate it without changing admission policy."""

    parsed = parse_state_file(path, expected_kind="targets")
    if parsed.mode != "input":
        raise StateFileError(f"{parsed.path}: TARGETS.md must use paos.mode=input")
    return _validate_targets(parsed.data, baseline)


def promote_targets_candidate(
    path: str | Path,
    *,
    baseline: Mapping[str, Any],
    approval: TargetProfileApproval | Mapping[str, Any],
) -> TargetProfileCandidate:
    """Return an explicitly approved TARGETS candidate without changing admission."""

    parsed = parse_state_file(path, expected_kind="targets")
    if parsed.mode != "input":
        raise StateFileError(f"{parsed.path}: TARGETS.md must use paos.mode=input")
    if not isinstance(baseline, Mapping) or not baseline:
        raise StateFileError("TARGETS promotion requires a non-empty baseline mapping")
    report = _validate_targets(parsed.data, baseline)
    if not report.valid or report.candidate_sha256 is None:
        raise StateFileError(
            f"{parsed.path}: invalid TARGETS candidate: {'; '.join(report.errors)}"
        )
    try:
        normalized = (
            approval
            if isinstance(approval, TargetProfileApproval)
            else TargetProfileApproval.model_validate(approval)
        )
    except Exception as exc:
        raise StateFileError("invalid TARGETS human approval credential") from exc
    baseline_sha256 = canonical_sha256(dict(baseline))
    if normalized.source_sha256 != parsed.data_sha256:
        raise StateFileError("TARGETS approval is bound to a different source digest")
    if normalized.baseline_sha256 != baseline_sha256:
        raise StateFileError("TARGETS approval is bound to a different baseline digest")
    return TargetProfileCandidate(
        source_sha256=parsed.data_sha256,
        baseline_sha256=baseline_sha256,
        profile_id=str(parsed.data["profile_id"]).strip(),
        data=dict(parsed.data),
        differences=report.differences,
        motion_authorized=False,
    )


def _session_preview(parsed: ParsedStateFile) -> SessionPreview:
    if parsed.mode != "input":
        raise StateFileError(f"{parsed.path}: SESSIONS.md must use paos.mode=input")
    sessions = parsed.data.get("sessions")
    if not isinstance(sessions, list) or not sessions:
        raise StateFileError(f"{parsed.path}: data.sessions must be a non-empty list")
    previews: list[dict[str, Any]] = []
    seen_session_ids: set[str] = set()
    for index, item in enumerate(sessions):
        if not isinstance(item, dict):
            raise StateFileError(f"{parsed.path}: sessions[{index}] must be an object")
        required = {"session_id", "intent", "acceptance_criteria", "retry_limit"}
        missing = sorted(required - set(item))
        if missing:
            raise StateFileError(
                f"sessions[{index}] missing field(s): {', '.join(missing)}"
            )
        session_id = item["session_id"]
        if not isinstance(session_id, str) or not session_id.strip() or any(char in session_id for char in "/\\"):
            raise StateFileError(f"{parsed.path}: sessions[{index}].session_id must be path-safe")
        session_id = session_id.strip()
        if session_id in seen_session_ids:
            raise StateFileError(f"{parsed.path}: duplicate session_id {session_id!r}")
        seen_session_ids.add(session_id)
        if not isinstance(item["intent"], str) or not item["intent"].strip():
            raise StateFileError(f"{parsed.path}: sessions[{index}].intent must be non-empty")
        criteria = item["acceptance_criteria"]
        if not isinstance(criteria, list) or not criteria or not all(isinstance(value, str) and value.strip() for value in criteria):
            raise StateFileError(f"{parsed.path}: sessions[{index}].acceptance_criteria must be non-empty strings")
        retry_limit = item["retry_limit"]
        if not isinstance(retry_limit, int) or isinstance(retry_limit, bool) or retry_limit < 0:
            raise StateFileError(f"{parsed.path}: sessions[{index}].retry_limit must be a non-negative integer")
        allowed = required | {"parent_task_id", "task_description"}
        unknown = sorted(set(item) - allowed)
        if unknown:
            raise StateFileError(f"{parsed.path}: sessions[{index}] unknown field(s): {', '.join(unknown)}")
        task_description = item.get("task_description", item["intent"])
        if not isinstance(task_description, str) or not task_description.strip():
            raise StateFileError(f"{parsed.path}: sessions[{index}].task_description must be non-empty")
        parent_task_id = item.get("parent_task_id")
        if parent_task_id is not None and (
            not isinstance(parent_task_id, str)
            or not parent_task_id.strip()
            or parent_task_id.strip() in {".", ".."}
            or any(char in parent_task_id for char in "/\\")
        ):
            raise StateFileError(f"{parsed.path}: sessions[{index}].parent_task_id must be path-safe")
        seed = {"source_digest": parsed.data_sha256, "session": item}
        previews.append(
            {
                "preview_status": "dry_run",
                "session_id": session_id,
                "task_id": f"task_preview_{canonical_sha256(seed)[:24]}",
                "task_description": task_description.strip(),
                "acceptance_criteria": [value.strip() for value in criteria],
                "parent_task_id": parent_task_id.strip() if isinstance(parent_task_id, str) else None,
                "retry_limit": retry_limit,
                "agent_task_write": False,
                "watchdog_dispatch": False,
                "motion_authorized": False,
            }
        )
    return SessionPreview(parsed, tuple(previews))


def parse_sessions_preview(path: str | Path) -> SessionPreview:
    """Return deterministic AgentTask previews without writing lifecycle state."""

    return _session_preview(parse_state_file(path, expected_kind="sessions"))


async def compile_sessions_to_agent_tasks(
    path: str | Path,
    *,
    coordinator: Any,
    approval: SessionCompileApproval | Mapping[str, Any],
    session_id: str | None = None,
    activation_id: str | None = None,
) -> SessionCompileResult:
    """Promote one approved declaration through the public AgentTask coordinator.

    The compiler deliberately accepts one declaration per call.  This avoids a
    partial batch when the global AgentTask slot is occupied and keeps the
    Markdown adapter from becoming a queue or scheduler.  Repeated compilation
    of the same source/session identity returns the existing task record.
    """

    preview = parse_sessions_preview(path)
    _approval_for_source(approval, preview.source.data_sha256)
    selected = list(preview.previews)
    if session_id is not None:
        selected = [item for item in selected if item["session_id"] == session_id.strip()]
        if not selected:
            raise SessionCompileError(f"session_id not found: {session_id!r}")
    elif len(selected) != 1:
        raise SessionCompileError(
            "SESSIONS.md compilation requires exactly one session; pass session_id explicitly"
        )

    store = getattr(coordinator, "store", None)
    if store is None or not hasattr(store, "find_by_origin_session_key"):
        raise SessionCompileError("coordinator does not expose the AgentTaskStore authority")
    compiled: list[Any] = []
    reused: list[Any] = []
    for item in selected:
        origin_key = _state_origin_key(preview.source.data_sha256, item["session_id"])
        existing = store.find_by_origin_session_key(origin_key)
        if len(existing) > 1:
            raise SessionCompileError(
                f"multiple AgentTasks already exist for session {item['session_id']!r}"
            )
        if existing:
            reused.append(existing[0])
            continue

        active = store.active()
        if active is not None:
            raise SessionCompileError(
                f"AgentTask {active.task_id} is still non-terminal; compilation is deferred"
            )
        parent_task_id = item["parent_task_id"]
        if parent_task_id is not None:
            try:
                parent = store.get(parent_task_id)
            except Exception as exc:
                raise SessionCompileError(
                    f"parent AgentTask not found: {parent_task_id}"
                ) from exc
            if not parent.terminal:
                raise SessionCompileError(
                    f"parent AgentTask {parent_task_id} is still non-terminal"
                )

        from PhyAgentOS.verification.contracts import TaskVerificationContract

        verification = TaskVerificationContract(
            mode="off",
            goal=item["task_description"],
            success_criteria=item["acceptance_criteria"],
            constraints=[f"retry_limit={item['retry_limit']}"],
        )
        try:
            task = coordinator.create_task(
                task_description=item["task_description"],
                verification=verification,
                activation_id=activation_id,
                origin_session_key=origin_key,
                parent_task_id=parent_task_id,
                retry_limit=item["retry_limit"],
            )
            if inspect.isawaitable(task):
                task = await task
        except Exception as exc:
            raise SessionCompileError(
                f"AgentTask compilation failed for session {item['session_id']!r}: {exc}"
            ) from exc
        compiled.append(task)
    return SessionCompileResult(
        source_sha256=preview.source.data_sha256,
        compiled=tuple(compiled),
        reused=tuple(reused),
        motion_authorized=False,
    )


def _projection(kind: str, path: str | Path, data: Mapping[str, Any], *, revision: str, source: str) -> ProjectionResult:
    if not isinstance(data, Mapping):
        raise StateFileError(f"{kind} projection data must be an object")
    return write_projection(path, kind=kind, revision=revision, source=source, data=data)


def render_skillruntime_projection(path: str | Path, runtime: Mapping[str, Any], *, revision: str, source: str) -> ProjectionResult:
    return _projection("skillruntime", path, runtime, revision=revision, source=source)


def render_environment_projection(path: str | Path, snapshot: Mapping[str, Any], *, revision: str, source: str) -> ProjectionResult:
    return _projection("environment", path, snapshot, revision=revision, source=source)


def render_lessons_projection(path: str | Path, lessons: Mapping[str, Any], *, revision: str, source: str) -> ProjectionResult:
    return _projection("lessons", path, lessons, revision=revision, source=source)
