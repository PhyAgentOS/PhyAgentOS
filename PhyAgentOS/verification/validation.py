"""Shared fail-closed validation for semantic Verification verdicts."""

from __future__ import annotations

from collections.abc import Collection, Sequence

from PhyAgentOS.verification.contracts import VerificationVerdict


class VerificationVerdictBoundaryError(ValueError):
    """Raised when a model verdict crosses the task/evidence authority boundary."""


def validate_verification_verdict_boundary(
    *,
    expected_criteria: Sequence[str],
    valid_evidence_refs: Collection[str],
    verdict: VerificationVerdict,
) -> None:
    """Require exact criteria identity and references admitted by the request builder."""
    expected = list(expected_criteria)
    actual = [item.criterion for item in verdict.criteria]
    if len(actual) != len(expected) or set(actual) != set(expected):
        raise VerificationVerdictBoundaryError(
            "verifier must return exactly one result for each success criterion"
        )
    refs = set(verdict.evidence_refs)
    for criterion in verdict.criteria:
        refs.update(criterion.evidence_refs)
    unknown = refs - set(valid_evidence_refs)
    if unknown:
        raise VerificationVerdictBoundaryError(
            "verifier referenced unknown evidence: " + ", ".join(sorted(unknown))
        )
