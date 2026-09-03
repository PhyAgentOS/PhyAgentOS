"""Domain adapters built on the strict PAOS state-file protocol."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

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


@dataclass(frozen=True)
class SessionPreview:
    """Dry-run task previews produced without touching AgentTaskStore."""

    source: ParsedStateFile
    previews: tuple[dict[str, Any], ...]


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
        if field in data and (not isinstance(data[field], str) or not data[field].strip()):
            errors.append(f"targets.{field} must be a non-empty string")
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
        errors = _require_keys(item, required, f"sessions[{index}]")
        if errors:
            raise StateFileError("; ".join(errors))
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
