"""Explicit projection from live, provider-neutral ToolSpecs to planning policy."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .contracts import ResourceClaim, ToolSpecPolicy, canonical_sha256


class ToolSpecProjectionError(ValueError):
    """A live ToolSpec cannot safely participate in planning admission."""


class _PlanningExtension(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(pattern=r"^paos-tool-spec-policy/v1$")
    capabilities: tuple[str, ...] = ()
    preconditions: tuple[str, ...] = ()
    required_evidence: tuple[str, ...] = ()
    produced_evidence: tuple[str, ...] = ()
    expected_effects: tuple[str, ...] = ()
    resource_claims: tuple[ResourceClaim, ...] = ()
    scene_write_behavior: str = "none"
    failure_classes: tuple[str, ...] = ()
    idempotency: str = "unknown"


_PROVIDER_PRIVATE = re.compile(
    r"(?:robotwin|sapien|xpolicylab|dora|vendor[-_ ]?sdk|ultralytics|\byolo\b)",
    re.IGNORECASE,
)


def _unique_strings(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    if len(values) != len(set(values)):
        raise ToolSpecProjectionError(f"planning {label} must contain unique values")
    if any(not value.strip() for value in values):
        raise ToolSpecProjectionError(f"planning {label} must contain non-empty values")
    return values


def project_tool_spec(spec: Mapping[str, Any]) -> ToolSpecPolicy:
    """Project only an explicit ToolSpec ``planning`` extension.

    The returned policy is a planning projection and never changes the live
    ToolSpec or grants execution authority. Missing or malformed planning
    metadata is rejected instead of guessed from provider implementation names.
    """
    if not isinstance(spec, Mapping):
        raise ToolSpecProjectionError("ToolSpec must be an object")
    value = dict(spec)
    for key in ("tool_id", "semantics"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ToolSpecProjectionError(f"ToolSpec {key} must be a non-empty string")
    if value["semantics"] not in {"query", "action", "session"}:
        raise ToolSpecProjectionError("ToolSpec semantics is unsupported")
    try:
        serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ToolSpecProjectionError("ToolSpec must contain finite JSON values") from exc
    if _PROVIDER_PRIVATE.search(serialized):
        raise ToolSpecProjectionError("ToolSpec contains provider-specific planning data")
    extension = value.get("planning")
    if not isinstance(extension, Mapping):
        raise ToolSpecProjectionError("ToolSpec is missing explicit planning extension")
    try:
        parsed = _PlanningExtension.model_validate(extension)
    except ValidationError as exc:
        raise ToolSpecProjectionError(f"invalid ToolSpec planning extension: {exc}") from exc
    for label in (
        "capabilities", "preconditions", "required_evidence", "produced_evidence",
        "expected_effects", "failure_classes",
    ):
        _unique_strings(getattr(parsed, label), label)
    try:
        policy = ToolSpecPolicy(
            tool_id=value["tool_id"],
            semantics=value["semantics"],
            spec_digest=canonical_sha256(value),
            capabilities=parsed.capabilities,
            preconditions=parsed.preconditions,
            required_evidence=parsed.required_evidence,
            produced_evidence=parsed.produced_evidence,
            expected_effects=parsed.expected_effects,
            resource_claims=parsed.resource_claims,
            scene_write_behavior=parsed.scene_write_behavior,
            failure_classes=parsed.failure_classes,
            idempotency=parsed.idempotency,
        )
    except (ValidationError, ValueError) as exc:
        raise ToolSpecProjectionError(f"invalid ToolSpec planning policy: {exc}") from exc
    return policy


__all__ = ["ToolSpecProjectionError", "project_tool_spec"]
