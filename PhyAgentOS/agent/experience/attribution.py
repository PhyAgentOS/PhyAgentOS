"""Deterministic guards for consuming capability facts during evolution."""

from __future__ import annotations

from dataclasses import dataclass

from PhyAgentOS.agent.experience.contracts import CapabilityOutcomeSummary, TaskEpisode


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


__all__ = ["EvolutionAttributionDecision", "assess_evolution_attribution"]
