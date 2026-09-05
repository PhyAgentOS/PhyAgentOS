from __future__ import annotations

from datetime import datetime, timezone

import pytest

from PhyAgentOS.agent.experience.policy_candidates import (
    PolicyCandidateError,
    WorkflowPolicyCandidateManager,
)
from PhyAgentOS.agent.experience.store import ExperienceStore
from PhyAgentOS.planning import WorkflowPolicyCandidate, WorkflowPolicyReplayReceipt


def _candidate(*, candidate_id: str = "candidate-1", episodes=("episode-1",)):
    return WorkflowPolicyCandidate(
        candidate_id=candidate_id,
        base_policy_digest="1" * 64,
        proposed_policy_digest="2" * 64,
        source_episode_ids=episodes,
        verification_receipts=("artifact://replay/seed",),
        change_summary="select a fresh observation when evidence is stale",
    )


def _receipt(episode: str = "episode-1", replay: str = "replay-1", verdict: str = "pass"):
    return WorkflowPolicyReplayReceipt(
        replay_id=replay,
        candidate_id="candidate-1",
        base_policy_digest="1" * 64,
        proposed_policy_digest="2" * 64,
        source_episode_id=episode,
        receipt_ref=f"artifact://replay/{replay}",
        verdict=verdict,
        independent=True,
        runner_id="runner-a",
        created_at=datetime.now(timezone.utc),
    )


def test_candidate_support_deduplicates_and_requires_independent_review(tmp_path):
    manager = WorkflowPolicyCandidateManager(ExperienceStore(tmp_path), min_support_episodes=2)
    manager.submit(_candidate())
    manager.submit(_candidate(candidate_id="candidate-2", episodes=("episode-2",)))
    candidate = manager.store.get_workflow_policy_candidate("candidate-1")
    assert candidate is not None
    assert candidate.source_episode_ids == ("episode-1", "episode-2")
    with pytest.raises(PolicyCandidateError, match="passing independent"):
        manager.review(candidate.candidate_id, approved=True, reviewer_id="reviewer")
    manager.record_replay(_receipt())
    manager.record_replay(_receipt(episode="episode-2", replay="replay-2"))
    approved = manager.review(candidate.candidate_id, approved=True, reviewer_id="reviewer")
    assert approved.status == "approved"


def test_promotion_is_explicit_and_callback_reference_is_validated(tmp_path):
    manager = WorkflowPolicyCandidateManager(ExperienceStore(tmp_path), min_support_episodes=1)
    manager.submit(_candidate())
    manager.record_replay(_receipt())
    manager.review("candidate-1", approved=True, reviewer_id="reviewer")
    with pytest.raises(PolicyCandidateError, match="callback"):
        manager.promote("candidate-1")

    manager = WorkflowPolicyCandidateManager(
        ExperienceStore(tmp_path / "other"),
        min_support_episodes=1,
        promotion_callback=lambda _: "not-artifact",
    )
    manager.submit(_candidate())
    manager.record_replay(_receipt())
    manager.review("candidate-1", approved=True, reviewer_id="reviewer")
    with pytest.raises(PolicyCandidateError, match="artifact"):
        manager.promote("candidate-1")


def test_replay_policy_digest_drift_is_rejected(tmp_path):
    manager = WorkflowPolicyCandidateManager(ExperienceStore(tmp_path), min_support_episodes=1)
    manager.submit(_candidate())
    with pytest.raises(PolicyCandidateError, match="digests"):
        manager.record_replay(_receipt().model_copy(update={"proposed_policy_digest": "9" * 64}))
