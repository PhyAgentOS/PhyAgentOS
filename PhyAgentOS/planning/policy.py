"""Workflow policy validation and digest helpers."""

from __future__ import annotations

from .contracts import WorkflowPolicy, canonical_sha256


def workflow_policy_digest(policy: WorkflowPolicy) -> str:
    return canonical_sha256(policy.model_dump(mode="json"))


def validate_policy_edges(policy: WorkflowPolicy) -> tuple[str, ...]:
    nodes = {item for edge in policy.partial_order_edges for item in edge}
    indegree = {node: 0 for node in nodes}
    children = {node: [] for node in nodes}
    seen_edges: set[tuple[str, str]] = set()
    for source, target in policy.partial_order_edges:
        if source == target:
            raise ValueError("workflow policy cannot contain self edge")
        if (source, target) in seen_edges:
            raise ValueError("workflow policy edges must be unique")
        seen_edges.add((source, target))
        indegree[target] += 1
        children[source].append(target)
    ready = sorted(node for node, count in indegree.items() if count == 0)
    order: list[str] = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for child in sorted(children[node]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
                ready.sort()
    if len(order) != len(nodes):
        raise ValueError("workflow policy contains a partial-order cycle")
    return tuple(order)


__all__ = ["validate_policy_edges", "workflow_policy_digest"]
