"""Immutable, provider-neutral planning protocol models."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_DIGEST = r"^[0-9a-f]{64}$"
_STATUS = Literal["succeeded", "failed", "unknown", "cancelled", "stopped"]


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _identity(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    value = value.strip()
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"{label} must be non-empty and path-safe")
    return value


def _digest(value: str, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(_DIGEST, value):
        raise ValueError(f"{label} must be a SHA-256 hex digest")
    return value


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResourceClaim(_Frozen):
    """Symbolic resource claim; concrete lock ownership remains outside planning."""

    resource_class: str = Field(min_length=1)
    mode: Literal["exclusive", "shared"] = "exclusive"
    quantity: int = Field(default=1, ge=1)


class PlanNode(_Frozen):
    """One semantic obligation, not one fixed Tool call."""

    node_id: str
    obligation_id: str
    capability: str
    dependencies: tuple[str, ...] = ()
    conditions: tuple[str, ...] = ()
    required_evidence: tuple[str, ...] = ()
    produced_evidence: tuple[str, ...] = ()
    resources: tuple[ResourceClaim, ...] = ()
    effects: tuple[str, ...] = ()
    retry_of: str | None = None

    @field_validator("node_id", "obligation_id", "capability")
    @classmethod
    def identity(cls, value: str) -> str:
        return _identity(value, "plan node identity")

    @field_validator("dependencies", "conditions", "required_evidence", "produced_evidence", "effects")
    @classmethod
    def unique_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("plan node values must be unique")
        return value


def plan_node_digest(node: PlanNode | dict[str, Any]) -> str:
    """Return the immutable identity digest for one semantic node.

    The digest intentionally excludes no fields: changing an obligation,
    dependency, evidence requirement, resource claim, or retry lineage creates
    a different node identity for execution attribution.
    """
    value = node.model_dump(mode="json") if isinstance(node, BaseModel) else dict(node)
    return canonical_sha256(value)


class PlanningExecutionBinding(_Frozen):
    """Complete attribution from one Tool execution to a PlanGraph node."""

    node_id: str
    node_digest: str = Field(pattern=_DIGEST)
    obligation_id: str
    input_binding_digest: str = Field(pattern=_DIGEST)
    decision_trace_ref: str

    @field_validator("node_id", "obligation_id")
    @classmethod
    def binding_identity(cls, value: str) -> str:
        return _identity(value, "planning execution binding identity")

    @field_validator("decision_trace_ref")
    @classmethod
    def trace_reference(cls, value: str) -> str:
        if not value.startswith("artifact://") or len(value) <= len("artifact://"):
            raise ValueError("decision_trace_ref must be an artifact:// reference")
        return value


class PlanGraph(_Frozen):
    """Concrete task graph bound to one PAOS PlanRevision."""

    schema_version: Literal["paos-plan-graph/v1"] = "paos-plan-graph/v1"
    task_id: str
    revision_id: str
    graph_digest: str = Field(pattern=_DIGEST)
    planner_decision_digest: str = Field(pattern=_DIGEST)
    policy_snapshot_digest: str = Field(pattern=_DIGEST)
    nodes: tuple[PlanNode, ...] = Field(min_length=1)

    @field_validator("task_id", "revision_id")
    @classmethod
    def graph_identity(cls, value: str) -> str:
        return _identity(value, "plan graph identity")

    @model_validator(mode="after")
    def valid_digest_and_nodes(self) -> "PlanGraph":
        ids = [node.node_id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("plan graph node identities must be unique")
        known = set(ids)
        for node in self.nodes:
            if node.node_id in node.dependencies:
                raise ValueError("plan graph cannot contain self dependency")
            if not set(node.dependencies).issubset(known):
                raise ValueError("plan graph dependency references an unknown node")
            if node.retry_of is not None and node.retry_of not in known:
                raise ValueError("plan graph retry_of references an unknown node")
        if self.graph_digest != plan_graph_digest(self):
            raise ValueError("plan graph digest does not match its content")
        return self


def plan_graph_digest(graph: PlanGraph | dict[str, Any]) -> str:
    value = graph.model_dump(mode="json") if isinstance(graph, BaseModel) else dict(graph)
    value.setdefault("schema_version", "paos-plan-graph/v1")
    value.pop("graph_digest", None)
    return canonical_sha256(value)


class ToolSpecPolicy(_Frozen):
    """Planning-only projection of a frozen ToolSpec."""

    schema_version: Literal["paos-tool-spec-policy/v1"] = "paos-tool-spec-policy/v1"
    tool_id: str
    semantics: Literal["query", "action", "session"]
    spec_digest: str = Field(pattern=_DIGEST)
    capabilities: tuple[str, ...] = ()
    preconditions: tuple[str, ...] = ()
    required_evidence: tuple[str, ...] = ()
    produced_evidence: tuple[str, ...] = ()
    expected_effects: tuple[str, ...] = ()
    resource_claims: tuple[ResourceClaim, ...] = ()
    scene_write_behavior: Literal["none", "new_revision", "unknown"] = "none"
    failure_classes: tuple[str, ...] = ()
    idempotency: Literal["idempotent", "at_most_once", "unknown"] = "unknown"

    @field_validator("tool_id")
    @classmethod
    def tool_identity(cls, value: str) -> str:
        return _identity(value, "tool identity")


class ToolCallEnvelope(_Frozen):
    """Agent proposal; it contains references/digests, not raw provider secrets."""

    schema_version: Literal["paos-tool-call/v1"] = "paos-tool-call/v1"
    task_id: str
    revision_id: str
    node_id: str
    tool_id: str
    tool_spec_digest: str = Field(pattern=_DIGEST)
    input_binding_digest: str = Field(pattern=_DIGEST)
    arguments: dict[str, Any] = Field(default_factory=dict)
    caller_id: str | None = None
    scene_revision: str
    idempotency_key: str
    semantics: Literal["query", "action", "session"]

    @field_validator("task_id", "revision_id", "node_id", "tool_id", "scene_revision", "idempotency_key")
    @classmethod
    def call_identity(cls, value: str) -> str:
        return _identity(value, "tool call identity")

    @field_validator("arguments")
    @classmethod
    def finite_arguments(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            json.dumps(value, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("Tool call arguments must contain finite JSON values") from exc
        return value

    @field_validator("caller_id")
    @classmethod
    def caller_identity(cls, value: str | None) -> str | None:
        return None if value is None else _identity(value, "caller_id")


class ToolResultEnvelope(_Frozen):
    """Execution projection supplied by the caller after Gateway completion."""

    schema_version: Literal["paos-tool-result/v1"] = "paos-tool-result/v1"
    task_id: str
    revision_id: str
    node_id: str
    tool_id: str
    status: _STATUS
    world_changed: bool = False
    output_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    new_scene_revision: str | None = None
    failure_code: str | None = None
    failure_owner: str | None = None

    @field_validator("task_id", "revision_id", "node_id", "tool_id")
    @classmethod
    def result_identity(cls, value: str) -> str:
        return _identity(value, "tool result identity")

    @model_validator(mode="after")
    def result_consistency(self) -> "ToolResultEnvelope":
        if self.status == "succeeded" and self.failure_code is not None:
            raise ValueError("successful Tool result cannot contain failure_code")
        if self.status != "succeeded" and self.world_changed:
            raise ValueError("non-successful Tool result cannot assert world_changed")
        if self.world_changed and not self.new_scene_revision:
            raise ValueError("world-changing result must provide new_scene_revision")
        return self


class NodeSettlement(_Frozen):
    schema_version: Literal["paos-node-settlement/v1"] = "paos-node-settlement/v1"
    task_id: str
    revision_id: str
    node_id: str
    status: Literal[
        "completed", "failed", "outcome_unknown", "blocked_by_dependency", "stale", "cancelled_before_start"
    ]
    evidence_refs: tuple[str, ...] = ()
    failure_code: str | None = None
    source_tool_id: str | None = None


class ReplanDelta(_Frozen):
    schema_version: Literal["paos-replan-delta/v1"] = "paos-replan-delta/v1"
    task_id: str
    revision_id: str
    preserve_node_ids: tuple[str, ...] = ()
    cancel_node_ids: tuple[str, ...] = ()
    invalidate_node_ids: tuple[str, ...] = ()
    retry_parent_node_id: str | None = None
    fresh_evidence_requirements: tuple[str, ...] = ()
    reason: str = Field(min_length=1)


class DecisionTrace(_Frozen):
    schema_version: Literal["paos-decision-trace/v1"] = "paos-decision-trace/v1"
    task_id: str
    revision_id: str
    node_id: str
    candidate_tool_ids: tuple[str, ...]
    selected_tool_id: str | None
    input_binding_digest: str | None = Field(default=None, pattern=_DIGEST)
    scene_revision: str
    context_digest: str = Field(pattern=_DIGEST)
    decision_reason: str = Field(min_length=1)
    result_status: str | None = None
    evidence_refs: tuple[str, ...] = ()
    created_at: datetime

    @field_validator("task_id", "revision_id", "node_id")
    @classmethod
    def trace_identity(cls, value: str) -> str:
        return _identity(value, "decision trace identity")

    @model_validator(mode="after")
    def valid_selection(self) -> "DecisionTrace":
        if len(self.candidate_tool_ids) != len(set(self.candidate_tool_ids)):
            raise ValueError("decision trace candidate tools must be unique")
        if self.selected_tool_id is not None and self.selected_tool_id not in self.candidate_tool_ids:
            raise ValueError("decision trace selected Tool is not a candidate")
        return self


class WorkflowPolicy(_Frozen):
    """Reusable strategy; never the current task's concrete graph."""

    schema_version: Literal["paos-workflow-policy/v1"] = "paos-workflow-policy/v1"
    policy_id: str
    version: str
    partial_order_edges: tuple[tuple[str, str], ...] = ()
    optional_tools: tuple[str, ...] = ()
    tool_selection_rules: tuple[str, ...] = ()
    parameter_binding_rules: tuple[str, ...] = ()
    applicability: tuple[str, ...] = ()
    counterexamples: tuple[str, ...] = ()
    verification_checkpoints: tuple[str, ...] = ()
    tunable_parameters: tuple[str, ...] = ()
    provider_owned_parameters: tuple[str, ...] = ()
    safety_immutable_parameters: tuple[str, ...] = ()

    @field_validator("policy_id", "version")
    @classmethod
    def policy_identity(cls, value: str) -> str:
        return _identity(value, "workflow policy identity")

    @model_validator(mode="after")
    def no_overlap_with_safety(self) -> "WorkflowPolicy":
        if set(self.tunable_parameters) & set(self.safety_immutable_parameters):
            raise ValueError("policy parameter cannot be both tunable and safety immutable")
        if set(self.provider_owned_parameters) & set(self.safety_immutable_parameters):
            raise ValueError("provider-owned parameter cannot be safety immutable")
        return self


class WorkflowPolicyCandidate(_Frozen):
    """Review-gated policy proposal derived from attributable episodes."""

    schema_version: Literal["paos-workflow-policy-candidate/v1"] = "paos-workflow-policy-candidate/v1"
    candidate_id: str
    base_policy_digest: str = Field(pattern=_DIGEST)
    proposed_policy_digest: str = Field(pattern=_DIGEST)
    source_episode_ids: tuple[str, ...] = Field(min_length=1)
    verification_receipts: tuple[str, ...] = Field(min_length=1)
    status: Literal["pending_review", "rejected", "approved", "promoted"] = "pending_review"
    change_summary: str = Field(min_length=1)

    @field_validator("candidate_id")
    @classmethod
    def candidate_identity(cls, value: str) -> str:
        return _identity(value, "policy candidate identity")


__all__ = [
    "DecisionTrace", "NodeSettlement", "PlanGraph", "PlanNode", "ReplanDelta",
    "PlanningExecutionBinding", "ResourceClaim", "ToolCallEnvelope", "ToolResultEnvelope",
    "ToolSpecPolicy", "WorkflowPolicy", "WorkflowPolicyCandidate", "canonical_sha256",
    "plan_graph_digest", "plan_node_digest",
]
