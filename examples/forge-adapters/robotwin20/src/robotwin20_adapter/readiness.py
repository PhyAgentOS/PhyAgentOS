"""Clean-room readiness evaluator seam for the RoboTwin20 adapter.

The evaluator is deliberately a provider boundary.  It receives only the
provider-neutral ``manipulation.prepare`` request and returns readiness
evidence; it never imports PAOS, RoboTwin, SAPIEN, a planner, or an actuator.
The generic PAOS endpoint remains responsible for final schema projection and
the immutable ``motion_authorized=false`` boundary.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Callable, Mapping, Protocol


class ReadinessAdapterError(RuntimeError):
    """The adapter cannot produce contract-valid readiness evidence."""


class ReadinessEvaluator(Protocol):
    """Injected no-motion evaluator, usually backed by a separate worker."""

    def evaluate(self, request: Mapping[str, Any]) -> Mapping[str, Any] | None: ...


_OBSERVATION_REF = re.compile(r"^observation://[^/]+/[^/]+$")
_CANDIDATE_SET_REF = re.compile(r"^candidate-set://[^/]+/.+$")
_CANDIDATE_REF = re.compile(r"^candidate://[^/]+/.+$")
_ENTITY_REF = re.compile(r"^entity://[^/]+$")
_ARTIFACT_REF = re.compile(r"^artifact://[^/]+/.+$")
_CHECK_KEYS = frozenset({"kinematic", "collision", "workspace"})
_CHECK_STATUSES = frozenset({"pass", "fail", "unknown"})
_PREPARED_KEYS = frozenset({"candidate_ref", "entity_ref", "checks", "evidence", "qualification"})
_REQUEST_KEYS = frozenset(
    {
        "observation_ref",
        "scene_revision",
        "frame_id",
        "calibration_ref",
        "freshness_ms",
        "max_age_ms",
        "candidate_set_ref",
        "candidates",
    }
)
_RESULT_KEYS = frozenset({"prepared_candidates", "provider_available"})


class RoboTwinReadinessEvaluator:
    """Adapt an injected readiness service to the generic PAOS provider port."""

    def __init__(self, evaluator: ReadinessEvaluator | Callable[[Mapping[str, Any]], Any]) -> None:
        if not callable(getattr(evaluator, "evaluate", None)) and not callable(evaluator):
            raise TypeError("readiness evaluator must expose evaluate(request) or be callable")
        self.evaluator = evaluator

    def evaluate(self, request: Mapping[str, Any]) -> Mapping[str, Any] | None:
        """Return only validated readiness evidence; never an action admission."""
        _validate_request(request)
        projected = {key: deepcopy(request[key]) for key in _REQUEST_KEYS}
        evaluate = getattr(self.evaluator, "evaluate", None)
        raw = evaluate(projected) if callable(evaluate) else self.evaluator(projected)
        if raw is None:
            return None
        if not isinstance(raw, Mapping):
            raise ReadinessAdapterError("readiness evaluator must return an object or null")
        unknown = set(raw) - _RESULT_KEYS
        if unknown:
            raise ReadinessAdapterError(
                "readiness evaluator returned provider-specific fields: "
                + ", ".join(sorted(unknown))
            )
        provider_available = raw.get("provider_available", True)
        if not isinstance(provider_available, bool):
            raise ReadinessAdapterError("readiness evaluator provider_available must be boolean")
        prepared = raw.get("prepared_candidates", ())
        if not isinstance(prepared, (list, tuple)):
            raise ReadinessAdapterError("readiness evaluator prepared_candidates must be an array")
        candidates = {
            item["candidate_ref"]: item["entity_ref"] for item in request["candidates"]
        }
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in prepared:
            if not isinstance(item, Mapping) or set(item) != _PREPARED_KEYS:
                raise ReadinessAdapterError("readiness evaluator returned an invalid prepared candidate")
            candidate_ref = item.get("candidate_ref")
            if (
                not isinstance(candidate_ref, str)
                or _CANDIDATE_REF.fullmatch(candidate_ref) is None
                or candidate_ref in seen
                or candidate_ref not in candidates
            ):
                raise ReadinessAdapterError("readiness evaluator returned an unbound candidate")
            seen.add(candidate_ref)
            entity_ref = item.get("entity_ref")
            if entity_ref != candidates[candidate_ref]:
                raise ReadinessAdapterError("readiness evaluator returned an unbound entity")
            checks = item.get("checks")
            if (
                not isinstance(checks, Mapping)
                or set(checks) != _CHECK_KEYS
                or any(checks[key] not in _CHECK_STATUSES for key in _CHECK_KEYS)
                or any(checks[key] != "pass" for key in _CHECK_KEYS)
            ):
                raise ReadinessAdapterError("readiness evaluator returned non-passing checks")
            evidence = item.get("evidence")
            if not isinstance(evidence, list) or not evidence or any(
                not isinstance(ref, str) or _ARTIFACT_REF.fullmatch(ref) is None for ref in evidence
            ):
                raise ReadinessAdapterError("readiness evaluator returned invalid evidence")
            if item.get("qualification") != "prepared":
                raise ReadinessAdapterError("readiness evaluator returned invalid qualification")
            normalized.append(dict(item))
        return {"prepared_candidates": tuple(normalized), "provider_available": provider_available}

    # PAOS's preparation endpoint names the provider call ``prepare``; keep
    # this thin alias so the adapter can be injected without importing PAOS.
    def prepare(self, request: Mapping[str, Any]) -> Mapping[str, Any] | None:
        return self.evaluate(request)


def _validate_request(request: Mapping[str, Any]) -> None:
    if not isinstance(request, Mapping):
        raise ReadinessAdapterError("readiness request must be an object")
    if set(request) != _REQUEST_KEYS:
        raise ReadinessAdapterError("readiness request fields do not match the public contract")
    observation_ref = request["observation_ref"]
    revision = request["scene_revision"]
    frame_id = request["frame_id"]
    if (
        not isinstance(observation_ref, str)
        or _OBSERVATION_REF.fullmatch(observation_ref) is None
        or not isinstance(revision, str)
        or not revision.strip()
        or not isinstance(frame_id, str)
        or not frame_id.strip()
        or observation_ref != f"observation://{revision}/{frame_id}"
    ):
        raise ReadinessAdapterError("readiness request observation identity is invalid")
    candidate_set_ref = request["candidate_set_ref"]
    if (
        not isinstance(candidate_set_ref, str)
        or _CANDIDATE_SET_REF.fullmatch(candidate_set_ref) is None
        or candidate_set_ref != f"candidate-set://{revision}/{frame_id}"
    ):
        raise ReadinessAdapterError("readiness request candidate-set identity is invalid")
    candidates = request["candidates"]
    if not isinstance(candidates, list):
        raise ReadinessAdapterError("readiness request candidates must be an array")
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ReadinessAdapterError("readiness request candidate must be an object")
        candidate_ref = candidate.get("candidate_ref")
        entity_ref = candidate.get("entity_ref")
        if (
            not isinstance(candidate_ref, str)
            or _CANDIDATE_REF.fullmatch(candidate_ref) is None
            or candidate_ref in seen
            or not isinstance(entity_ref, str)
            or _ENTITY_REF.fullmatch(entity_ref) is None
        ):
            raise ReadinessAdapterError("readiness request candidate identity is invalid")
        seen.add(candidate_ref)


__all__ = ["ReadinessAdapterError", "ReadinessEvaluator", "RoboTwinReadinessEvaluator"]
