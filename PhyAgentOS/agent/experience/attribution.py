"""Deterministic guards for consuming capability facts during evolution."""

from __future__ import annotations

from dataclasses import dataclass

from PhyAgentOS.agent.experience.contracts import (
    CapabilityOutcomeSummary,
    ExperienceAssessment,
    TaskEpisode,
)

_SEMANTIC_ATTRIBUTION_OWNERS = {
    "input",
    "binding",
    "readiness",
    "planner",
    "execution",
    "settlement",
}


@dataclass(frozen=True)
class EvolutionAttributionDecision:
    allowed: bool
    reason: str
    event_payload: dict[str, object]


def assess_evolution_attribution(episode: TaskEpisode) -> EvolutionAttributionDecision:
    """Block learning writes when capability state is unknown or unsettled."""
    summary: CapabilityOutcomeSummary = episode.outcome.capability_outcome_summary
    status_counts = summary.status_counts
    blocked_statuses = {
        status: status_counts.get(status, 0)
        for status in ("unknown", "cancelled", "stopped")
        if status_counts.get(status, 0)
    }
    if summary.projection_error_count:
        reason = "capability_projection_error"
    elif blocked_statuses:
        reason = "capability_outcome_unsettled"
    else:
        return EvolutionAttributionDecision(True, "ready", {})
    return EvolutionAttributionDecision(
        False,
        reason,
        {
            "reason": reason,
            "status_counts": dict(sorted(blocked_statuses.items())),
            "projection_error_count": summary.projection_error_count,
            "projection_error_codes": list(summary.projection_error_codes),
        },
    )


def build_analyzer_attribution_context(episode: TaskEpisode) -> dict[str, object]:
    """Build a provider-neutral hint; the analyzer still owns semantic attribution."""
    summary = episode.outcome.capability_outcome_summary
    owner_counts = dict(sorted(summary.failure_owner_counts.items()))
    evidence_counts = dict(sorted(summary.evidence_availability_counts.items()))
    failed_count = summary.status_counts.get("failed", 0)
    owner_total = sum(owner_counts.values())
    usable_evidence = evidence_counts.get("complete", 0) + evidence_counts.get("partial", 0)
    infrastructure_only = (
        failed_count > 0
        and owner_total > 0
        and owner_counts.get("infrastructure", 0) == owner_total
    )
    evidence_limit_only = (
        failed_count > 0
        and sum(evidence_counts.values()) > 0
        and usable_evidence == 0
        and not owner_counts
    )
    return {
        "version": "capability_attribution_context_v1",
        "authority": "advisory_execution_fact",
        "task_success_authorized": False,
        "failure_owner_counts": owner_counts,
        "evidence_availability_counts": evidence_counts,
        "required_lesson_reason": (
            "external_or_infrastructure"
            if infrastructure_only
            else "evidence_limit"
            if evidence_limit_only
            else None
        ),
        "requires_semantic_attribution_owners": sorted(
            _SEMANTIC_ATTRIBUTION_OWNERS.intersection(owner_counts)
        ),
    }


def validate_assessment_attribution(
    episode: TaskEpisode, assessment: ExperienceAssessment
) -> EvolutionAttributionDecision:
    """Reject only assessment claims that contradict deterministic attribution facts."""
    context = build_analyzer_attribution_context(episode)
    expected_reason = context["required_lesson_reason"]
    if expected_reason is None or not assessment.failure_observations:
        return EvolutionAttributionDecision(True, "ready", {})
    conflicts = [
        item.eligibility.reason
        for item in assessment.failure_observations
        if item.eligibility.reason != expected_reason
    ]
    if not conflicts:
        return EvolutionAttributionDecision(True, "ready", {})
    reason = f"{expected_reason}_misattributed"
    return EvolutionAttributionDecision(
        False,
        reason,
        {
            "reason": reason,
            "required_lesson_reason": expected_reason,
            "conflicting_reason_count": len(conflicts),
        },
    )


__all__ = [
    "EvolutionAttributionDecision",
    "assess_evolution_attribution",
    "build_analyzer_attribution_context",
    "validate_assessment_attribution",
]
