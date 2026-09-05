"""Decision trace helpers that store references and digests only."""

from __future__ import annotations

from datetime import datetime, timezone

from .contracts import DecisionTrace, ToolCallEnvelope, canonical_sha256


def make_decision_trace(
    call: ToolCallEnvelope,
    *,
    candidate_tool_ids: tuple[str, ...],
    context: dict[str, object],
    reason: str,
    result_status: str | None = None,
    evidence_refs: tuple[str, ...] = (),
) -> DecisionTrace:
    if call.tool_id not in candidate_tool_ids:
        raise ValueError("selected Tool must be one of candidate_tool_ids")
    return DecisionTrace(
        task_id=call.task_id,
        revision_id=call.revision_id,
        node_id=call.node_id,
        candidate_tool_ids=candidate_tool_ids,
        selected_tool_id=call.tool_id,
        input_binding_digest=call.input_binding_digest,
        scene_revision=call.scene_revision,
        context_digest=canonical_sha256(context),
        decision_reason=reason,
        result_status=result_status,
        evidence_refs=evidence_refs,
        created_at=datetime.now(timezone.utc),
    )


__all__ = ["make_decision_trace"]
