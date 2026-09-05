"""Pure construction of bounded replan instructions."""

from __future__ import annotations

from collections.abc import Iterable

from .contracts import NodeSettlement, PlanGraph, ReplanDelta


def build_replan_delta(
    graph: PlanGraph,
    settlement: NodeSettlement,
    *,
    retry: bool = True,
    fresh_evidence_requirements: Iterable[str] = (),
) -> ReplanDelta:
    if settlement.node_id not in {node.node_id for node in graph.nodes}:
        raise ValueError("settlement node is not in the graph")
    if settlement.status == "completed":
        raise ValueError("completed node does not require replanning")
    descendants = {settlement.node_id}
    changed = True
    while changed:
        changed = False
        for node in graph.nodes:
            if node.node_id not in descendants and set(node.dependencies) & descendants:
                descendants.add(node.node_id)
                changed = True
    invalidate = tuple(sorted(descendants - {settlement.node_id}))
    preserve = tuple(sorted(node.node_id for node in graph.nodes if node.node_id not in descendants))
    return ReplanDelta(
        task_id=graph.task_id,
        revision_id=graph.revision_id,
        preserve_node_ids=preserve,
        cancel_node_ids=(),
        invalidate_node_ids=invalidate,
        retry_parent_node_id=settlement.node_id if retry else None,
        fresh_evidence_requirements=tuple(dict.fromkeys(fresh_evidence_requirements)),
        reason=f"node {settlement.node_id} settled as {settlement.status}",
    )


__all__ = ["build_replan_delta"]
