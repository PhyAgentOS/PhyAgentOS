from __future__ import annotations

import asyncio

import pytest

from PhyAgentOS.agent.session_verifier import (
    ForgeTaskVerifier,
    VerificationVerdictError,
)
from PhyAgentOS.verification.contracts import RecoveryContext


def _verifier(tmp_path, response):
    verifier = ForgeTaskVerifier(
        workspace=tmp_path,
        provider=object(),
        model="local-test",
        max_calls=1,
    )
    calls = []

    def start_and_verify(content):
        calls.append(content)
        return response

    verifier._start_and_verify = start_and_verify
    return verifier, calls


def _run(verifier, *, criteria=("placed",), refs=("after_rgb",)):
    return asyncio.run(
        verifier._verify_content(
            content=[{"type": "text", "text": "fixture"}],
            expected_criteria=list(criteria),
            valid_evidence_refs=set(refs),
        )
    )


def test_success_verdict_is_accepted_only_with_exact_satisfied_criteria(tmp_path):
    verifier, calls = _verifier(
        tmp_path,
        {
            "verdict": "success",
            "criteria": [
                {"criterion": "placed", "status": "satisfied", "evidence_refs": ["after_rgb"]}
            ],
            "evidence_refs": ["after_rgb"],
            "reason": "after snapshot confirms placement",
            "lesson": "none",
        },
    )
    verdict, attempt = _run(verifier)
    assert verdict.verdict == "success"
    assert attempt.verdict == "success"
    assert len(calls) == 1


def test_replan_verdict_requires_recovery_context_and_preserves_unmet_criteria(tmp_path):
    verifier, _ = _verifier(
        tmp_path,
        {
            "verdict": "replan_required",
            "criteria": [{"criterion": "placed", "status": "unknown"}],
            "evidence_refs": [],
            "reason": "after evidence is inconclusive",
            "lesson": "capture a fresh after snapshot",
            "recovery_context": {
                "unmet_criteria": ["placed"],
                "preserved_constraints": ["keep task identity"],
                "guidance": "re-observe before retrying",
            },
        },
    )
    verdict, _ = _run(verifier, refs=())
    assert verdict.verdict == "replan_required"
    assert isinstance(verdict.recovery_context, RecoveryContext)
    assert verdict.recovery_context.unmet_criteria == ["placed"]


@pytest.mark.parametrize(
    ("response", "match"),
    [
        (
            {
                "verdict": "success",
                "criteria": [],
                "reason": "missing criterion",
                "lesson": "none",
            },
            "exactly one result",
        ),
        (
            {
                "verdict": "success",
                "criteria": [{"criterion": "placed", "status": "satisfied"}],
                "evidence_refs": ["projection://environment/after"],
                "reason": "projection claims success",
                "lesson": "none",
            },
            "unknown evidence",
        ),
        (
            {
                "verdict": "failure",
                "criteria": [{"criterion": "different", "status": "unsatisfied"}],
                "reason": "criterion identity drift",
                "lesson": "none",
            },
            "exactly one result",
        ),
    ],
)
def test_invalid_model_verdicts_fail_closed(tmp_path, response, match):
    verifier, _ = _verifier(tmp_path, response)
    with pytest.raises(VerificationVerdictError, match=match):
        _run(verifier)


def test_malformed_model_response_is_rejected_without_gateway_or_service(tmp_path):
    verifier, calls = _verifier(tmp_path, {"verdict": "success"})
    with pytest.raises(VerificationVerdictError):
        _run(verifier)
    assert len(calls) == 1
    assert verifier.service._process is None
