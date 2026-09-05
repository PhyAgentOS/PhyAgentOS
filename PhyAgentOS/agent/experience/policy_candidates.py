"""Review-gated planning-policy candidate lifecycle.

This component records candidate evidence in the Experience ledger.  It never
changes a running AgentTask or writes a Skill directly; promotion is delegated
to an explicitly supplied Skill Runtime callback.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from PhyAgentOS.agent.experience.store import ExperienceStore
from PhyAgentOS.planning import WorkflowPolicyCandidate, WorkflowPolicyReplayReceipt


class PolicyCandidateError(ValueError):
    """A candidate lifecycle transition is not admissible."""


class WorkflowPolicyCandidateManager:
    def __init__(
        self,
        store: ExperienceStore,
        *,
        min_support_episodes: int = 3,
        promotion_callback: Callable[[WorkflowPolicyCandidate], str] | None = None,
    ) -> None:
        self.store = store
        self.min_support_episodes = max(1, int(min_support_episodes))
        self.promotion_callback = promotion_callback

    def submit(self, candidate: WorkflowPolicyCandidate) -> WorkflowPolicyCandidate:
        """Aggregate support for the same base/proposed policy pair."""
        matching = next(
            (
                item
                for item in self.store.list_workflow_policy_candidates()
                if item.base_policy_digest == candidate.base_policy_digest
                and item.proposed_policy_digest == candidate.proposed_policy_digest
                and item.status not in {"rejected", "promoted"}
            ),
            None,
        )
        if matching is not None and matching.candidate_id != candidate.candidate_id:
            candidate = matching.model_copy(
                update={
                    "source_episode_ids": tuple(
                        dict.fromkeys(matching.source_episode_ids + candidate.source_episode_ids)
                    ),
                    "verification_receipts": tuple(
                        dict.fromkeys(matching.verification_receipts + candidate.verification_receipts)
                    ),
                    "change_summary": candidate.change_summary,
                }
            )
        return self.store.upsert_workflow_policy_candidate(candidate)

    def record_replay(
        self, receipt: WorkflowPolicyReplayReceipt
    ) -> WorkflowPolicyCandidate:
        candidate = self.store.get_workflow_policy_candidate(receipt.candidate_id)
        if candidate is None:
            raise PolicyCandidateError("policy replay references an unknown candidate")
        if candidate.status != "pending_review":
            raise PolicyCandidateError("policy replay is only accepted for pending candidates")
        if (
            receipt.base_policy_digest != candidate.base_policy_digest
            or receipt.proposed_policy_digest != candidate.proposed_policy_digest
        ):
            raise PolicyCandidateError("policy replay policy digests do not match the candidate")
        if receipt.source_episode_id not in candidate.source_episode_ids:
            raise PolicyCandidateError("policy replay source is not a candidate episode")
        existing = self.store.list_policy_replay_receipts(candidate.candidate_id)
        if any(item.replay_id == receipt.replay_id for item in existing):
            return candidate
        self.store.add_policy_replay_receipt(receipt)
        receipts = tuple(dict.fromkeys(candidate.verification_receipts + (receipt.receipt_ref,)))
        updated = candidate.model_copy(update={"verification_receipts": receipts})
        self.store.update_workflow_policy_candidate(
            updated, event_type="workflow_policy_replay_attached"
        )
        return updated

    def review(
        self, candidate_id: str, *, approved: bool, reviewer_id: str
    ) -> WorkflowPolicyCandidate:
        candidate = self.store.get_workflow_policy_candidate(candidate_id)
        if candidate is None:
            raise PolicyCandidateError("policy candidate does not exist")
        if candidate.status != "pending_review":
            raise PolicyCandidateError("only pending policy candidates can be reviewed")
        if not reviewer_id.strip():
            raise PolicyCandidateError("reviewer_id must be non-empty")
        receipts = self.store.list_policy_replay_receipts(candidate_id)
        if approved:
            if len(set(candidate.source_episode_ids)) < self.min_support_episodes:
                raise PolicyCandidateError("candidate lacks independent episode support")
            if not receipts or any(
                not item.independent or item.verdict != "pass" for item in receipts
            ):
                raise PolicyCandidateError("candidate lacks passing independent replay evidence")
        updated = candidate.model_copy(
            update={
                "status": "approved" if approved else "rejected",
                "reviewer_id": reviewer_id.strip(),
                "reviewed_at": datetime.now(timezone.utc),
            }
        )
        self.store.update_workflow_policy_candidate(
            updated,
            event_type=("workflow_policy_candidate_approved" if approved else "workflow_policy_candidate_rejected"),
        )
        return updated

    def promote(self, candidate_id: str) -> WorkflowPolicyCandidate:
        candidate = self.store.get_workflow_policy_candidate(candidate_id)
        if candidate is None:
            raise PolicyCandidateError("policy candidate does not exist")
        if candidate.status != "approved":
            raise PolicyCandidateError("only an approved policy candidate can be promoted")
        if self.promotion_callback is None:
            raise PolicyCandidateError("Skill Runtime promotion callback is not configured")
        promotion_ref = self.promotion_callback(candidate)
        if not isinstance(promotion_ref, str) or not promotion_ref.startswith("artifact://"):
            raise PolicyCandidateError("promotion callback must return an artifact:// reference")
        updated = candidate.model_copy(update={"status": "promoted", "promotion_ref": promotion_ref})
        self.store.update_workflow_policy_candidate(
            updated, event_type="workflow_policy_candidate_promoted"
        )
        return updated


__all__ = ["PolicyCandidateError", "WorkflowPolicyCandidateManager"]
