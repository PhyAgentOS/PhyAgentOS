"""Pure Tool admission checks; the caller performs any accepted invocation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .contracts import PlanGraph, ToolCallEnvelope, ToolSpecPolicy
from .dag import derive_ready_nodes


class AdmissionContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scene_revision: str = Field(min_length=1)
    evidence_refs: frozenset[str] = Field(default_factory=frozenset)
    resources_in_use: frozenset[str] = Field(default_factory=frozenset)
    settlements: tuple[tuple[str, str], ...] = ()
    condition_facts: tuple[tuple[str, bool], ...] = ()

    @model_validator(mode="before")
    @classmethod
    def normalize_maps(cls, obj: object) -> object:
        if isinstance(obj, Mapping):
            normalized = dict(obj)
            for key in ("settlements", "condition_facts"):
                value = normalized.get(key)
                if isinstance(value, Mapping):
                    normalized[key] = tuple(value.items())
            return normalized
        return obj

    @field_validator("settlements", "condition_facts")
    @classmethod
    def unique_fact_keys(cls, value: tuple[tuple[str, object], ...]) -> tuple[tuple[str, object], ...]:
        keys = [item[0] for item in value]
        if len(keys) != len(set(keys)):
            raise ValueError("admission context fact keys must be unique")
        return value


class AdmissionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: bool
    code: str
    detail: str
    node_id: str
    tool_id: str
    motion_authorized: Literal[False] = False


def admit_tool_call(
    graph: PlanGraph,
    call: ToolCallEnvelope,
    tool: ToolSpecPolicy,
    context: AdmissionContext,
) -> AdmissionDecision:
    """Check identity, readiness, evidence, scene, resources, and semantics."""
    def reject(code: str, detail: str) -> AdmissionDecision:
        return AdmissionDecision(allowed=False, code=code, detail=detail, node_id=call.node_id, tool_id=call.tool_id)

    node = next((item for item in graph.nodes if item.node_id == call.node_id), None)
    if node is None or call.task_id != graph.task_id or call.revision_id != graph.revision_id:
        return reject("identity_mismatch", "call is not bound to this task graph")
    if call.tool_id != tool.tool_id or call.tool_spec_digest != tool.spec_digest:
        return reject("tool_binding_mismatch", "ToolSpec identity or digest does not match")
    if call.semantics != tool.semantics:
        return reject("semantics_mismatch", "Tool semantics do not match the ToolSpec")
    if tool.capabilities and node.capability not in tool.capabilities:
        return reject("capability_mismatch", "Tool is not declared for this node capability")
    if call.scene_revision != context.scene_revision:
        return reject("stale_scene", "call scene revision is stale")
    settlements = dict(context.settlements)
    condition_facts = dict(context.condition_facts)
    if call.node_id not in derive_ready_nodes(graph, settlements, set(context.evidence_refs), condition_facts):
        return reject("node_not_ready", "node dependencies, evidence, or conditions are not satisfied")
    required = set(node.required_evidence) | set(tool.required_evidence)
    if not required.issubset(context.evidence_refs):
        return reject("missing_evidence", "required evidence is unavailable")
    for precondition in tool.preconditions:
        if precondition.startswith("evidence:"):
            if precondition.removeprefix("evidence:") not in context.evidence_refs:
                return reject("precondition_failed", f"precondition {precondition!r} is not satisfied")
        elif precondition not in {"node_ready", "scene_current"} and condition_facts.get(precondition) is not True:
            return reject("precondition_failed", f"precondition {precondition!r} is not satisfied")
    claims = {claim.resource_class for claim in tool.resource_claims} | {
        claim.resource_class for claim in node.resources
    }
    if claims & set(context.resources_in_use):
        return reject("resource_conflict", "a required symbolic resource is already in use")
    return AdmissionDecision(allowed=True, code="admitted", detail="Tool call is structurally admissible", node_id=call.node_id, tool_id=call.tool_id)


__all__ = ["AdmissionContext", "AdmissionDecision", "admit_tool_call"]
