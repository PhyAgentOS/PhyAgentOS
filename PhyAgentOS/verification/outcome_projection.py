"""Project versioned Forge capability summaries into task-level execution facts."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

SUMMARY_VERSION = "capability_outcome_summary_v1"
_STATUSES = {"succeeded", "failed", "cancelled", "stopped", "unknown"}
_CAPABILITY_PHASES = {
    "approach",
    "contact",
    "close",
    "lift",
    "hold",
    "transport",
    "descent",
    "release",
    "retreat",
    "none",
}
_FAILURE_OWNERS = {
    "none",
    "input",
    "binding",
    "readiness",
    "planner",
    "execution",
    "settlement",
    "operator",
    "infrastructure",
}
_EVIDENCE_AVAILABILITY = {"complete", "partial", "none", "unknown"}
_ARTIFACT_REF = re.compile(r"^artifact://[^/]+/.+$")
_METRIC_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SUMMARY_KEYS = {
    "version",
    "capability_phase",
    "status",
    "failure_owner",
    "failure_code",
    "world_change_started",
    "outcome_known",
    "evidence_availability",
    "artifact_refs",
    "bounded_metric_names",
}
_OPTIONAL_SUMMARY_KEYS = {"post_release_evidence"}


@dataclass(frozen=True)
class PostReleaseEvidenceProjection:
    availability: str
    opaque_artifact_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapabilityOutcomeProjection:
    version: str
    record_id: str
    tool_id: str
    semantics: str
    invocation_id: str | None
    attempt_id: str | None
    status: str
    capability_phase: str
    failure_owner: str | None
    failure_code: str | None
    world_change_started: bool
    outcome_known: bool
    evidence_availability: str
    opaque_artifact_refs: tuple[str, ...] = ()
    bounded_metric_names: tuple[str, ...] = ()
    post_release_evidence: PostReleaseEvidenceProjection | None = None
    authority: str = "execution_fact_only"
    task_success_authorized: bool = False


@dataclass(frozen=True)
class CapabilityOutcomeProjectionError:
    record_id: str
    code: str
    message: str


@dataclass(frozen=True)
class CapabilityOutcomeProjectionResult:
    projections: tuple[CapabilityOutcomeProjection, ...] = field(default_factory=tuple)
    errors: tuple[CapabilityOutcomeProjectionError, ...] = field(default_factory=tuple)


def project_terminal_outcomes(records: Iterable[Any]) -> CapabilityOutcomeProjectionResult:
    """Project valid summaries without treating malformed data as task evidence."""

    projections: list[CapabilityOutcomeProjection] = []
    errors: list[CapabilityOutcomeProjectionError] = []
    for record in records:
        if not _is_terminal_action(record):
            continue
        record_id = _text(getattr(record, "record_id", None)) or "unknown-record"
        response = getattr(record, "response", None)
        summary = _summary_from_response(response)
        if summary is None:
            if _has_terminal_result(response):
                errors.append(
                    CapabilityOutcomeProjectionError(
                        record_id,
                        "missing_summary",
                        "terminal Action result omitted capability outcome summary",
                    )
                )
            continue
        error = _validate_summary(summary, record_status=getattr(record, "status", None))
        if error is not None:
            errors.append(CapabilityOutcomeProjectionError(record_id, error, "capability outcome summary failed contract validation"))
            continue
        projections.append(
            CapabilityOutcomeProjection(
                version=summary["version"],
                record_id=record_id,
                tool_id=_text(getattr(record, "tool_id", None)) or "unknown-tool",
                semantics=_text(getattr(record, "semantics", None)) or "action",
                invocation_id=_text(getattr(record, "invocation_id", None)),
                attempt_id=_text(getattr(record, "attempt_id", None)),
                status=summary["status"],
                capability_phase=summary["capability_phase"],
                failure_owner=summary["failure_owner"],
                failure_code=summary["failure_code"],
                world_change_started=summary["world_change_started"],
                outcome_known=summary["outcome_known"],
                evidence_availability=summary["evidence_availability"],
                opaque_artifact_refs=tuple(summary["artifact_refs"]),
                bounded_metric_names=tuple(summary["bounded_metric_names"]),
                post_release_evidence=(
                    PostReleaseEvidenceProjection(
                        availability=summary["post_release_evidence"]["availability"],
                        opaque_artifact_refs=tuple(
                            summary["post_release_evidence"]["artifact_refs"]
                        ),
                    )
                    if "post_release_evidence" in summary
                    else None
                ),
            )
        )
    return CapabilityOutcomeProjectionResult(tuple(projections), tuple(errors))


def projection_to_dict(projection: CapabilityOutcomeProjection) -> dict[str, Any]:
    """Return a redacted JSON-safe projection for verifier context."""

    value = asdict(projection)
    value["opaque_artifact_refs"] = list(projection.opaque_artifact_refs)
    value["bounded_metric_names"] = list(projection.bounded_metric_names)
    if projection.post_release_evidence is not None:
        value["post_release_evidence"]["opaque_artifact_refs"] = list(
            projection.post_release_evidence.opaque_artifact_refs
        )
    return value


def _is_terminal_action(record: Any) -> bool:
    return (
        getattr(record, "semantics", None) == "action"
        and getattr(record, "status", None) in _STATUSES
    )


def _summary_from_response(response: Any) -> dict[str, Any] | None:
    if not isinstance(response, dict):
        return None
    data = response.get("data")
    if not isinstance(data, dict):
        return None
    result = data.get("result")
    if not isinstance(result, dict):
        return None
    summary = result.get("capability_outcome_summary")
    return summary if isinstance(summary, dict) else None


def _has_terminal_result(response: Any) -> bool:
    if not isinstance(response, dict):
        return False
    data = response.get("data")
    return isinstance(data, dict) and isinstance(data.get("result"), dict)


def _validate_summary(summary: dict[str, Any], *, record_status: Any) -> str | None:
    if set(summary) - (_SUMMARY_KEYS | _OPTIONAL_SUMMARY_KEYS) or not _SUMMARY_KEYS.issubset(summary):
        return "invalid_summary_fields"
    if not isinstance(summary["version"], str) or summary["version"] != SUMMARY_VERSION:
        return "unsupported_summary_version"
    if not isinstance(summary["status"], str) or summary["status"] not in _STATUSES:
        return "invalid_summary_status"
    if record_status in _STATUSES and summary["status"] != record_status:
        return "summary_status_mismatch"
    if not isinstance(summary["capability_phase"], str) or summary["capability_phase"] not in _CAPABILITY_PHASES:
        return "invalid_capability_phase"
    owner = summary["failure_owner"]
    if owner is not None and (not isinstance(owner, str) or owner not in _FAILURE_OWNERS):
        return "invalid_failure_owner"
    code = summary["failure_code"]
    if code is not None and (not isinstance(code, str) or not code.strip()):
        return "invalid_failure_code"
    if summary["status"] == "unknown" and summary["outcome_known"] is not False:
        return "invalid_unknown_outcome"
    if summary["status"] == "succeeded" and (owner not in {None, "none"} or code is not None):
        return "invalid_success_failure_fields"
    if summary["status"] != "succeeded" and (owner in {None, "none"} or code is None):
        return "invalid_failure_fields"
    if not isinstance(summary["world_change_started"], bool) or not isinstance(summary["outcome_known"], bool):
        return "invalid_summary_boolean"
    if (
        not isinstance(summary["evidence_availability"], str)
        or summary["evidence_availability"] not in _EVIDENCE_AVAILABILITY
    ):
        return "invalid_evidence_availability"
    if _validate_refs(summary["artifact_refs"], summary["evidence_availability"]) is not None:
        return "invalid_artifact_refs"
    metrics = summary["bounded_metric_names"]
    if not isinstance(metrics, list) or any(
        not isinstance(name, str) or _METRIC_NAME.fullmatch(name) is None for name in metrics
    ) or len({name for name in metrics if isinstance(name, str)}) != len(metrics):
        return "invalid_metric_names"
    if "post_release_evidence" in summary:
        evidence = summary["post_release_evidence"]
        if (
            not isinstance(evidence, dict)
            or set(evidence) != {"availability", "artifact_refs"}
            or not isinstance(evidence["availability"], str)
            or evidence["availability"] not in _EVIDENCE_AVAILABILITY
            or _validate_refs(evidence["artifact_refs"], evidence["availability"]) is not None
        ):
            return "invalid_post_release_evidence"
    return None


def _validate_refs(refs: Any, availability: str) -> str | None:
    if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
        return "invalid"
    if len(set(refs)) != len(refs) or any(_ARTIFACT_REF.fullmatch(ref) is None for ref in refs):
        return "invalid"
    if availability == "none" and refs:
        return "invalid"
    if availability in {"complete", "partial"} and not refs:
        return "invalid"
    return None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = [
    "SUMMARY_VERSION",
    "CapabilityOutcomeProjection",
    "CapabilityOutcomeProjectionError",
    "CapabilityOutcomeProjectionResult",
    "PostReleaseEvidenceProjection",
    "project_terminal_outcomes",
    "projection_to_dict",
]
