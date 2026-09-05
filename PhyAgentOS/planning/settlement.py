"""Normalize execution outcomes without confusing unknown with failure."""

from __future__ import annotations

from .contracts import NodeSettlement, PlanNode, ToolResultEnvelope


def settle_node(node: PlanNode, result: ToolResultEnvelope, *, current_scene_revision: str) -> NodeSettlement:
    if result.node_id != node.node_id:
        raise ValueError("Tool result node does not match the settled node")
    if result.status == "succeeded":
        if result.world_changed and result.new_scene_revision == current_scene_revision:
            return NodeSettlement(task_id=result.task_id, revision_id=result.revision_id, node_id=node.node_id, status="stale", evidence_refs=result.evidence_refs, failure_code="scene_revision_not_advanced", source_tool_id=result.tool_id)
        return NodeSettlement(task_id=result.task_id, revision_id=result.revision_id, node_id=node.node_id, status="completed", evidence_refs=result.evidence_refs, source_tool_id=result.tool_id)
    if result.status in {"unknown"}:
        status = "outcome_unknown"
    elif result.status == "cancelled":
        status = "cancelled_before_start"
    else:
        status = "failed"
    return NodeSettlement(task_id=result.task_id, revision_id=result.revision_id, node_id=node.node_id, status=status, failure_code=result.failure_code or result.status, source_tool_id=result.tool_id)


__all__ = ["settle_node"]
