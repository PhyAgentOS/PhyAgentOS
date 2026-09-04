"""Replayable long-horizon workflow state over the existing Forge Tool API."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any, Literal

WORKFLOW_ID = "pick-and-place"
WORKFLOW_VERSION = "pick_and_place_workflow_v1"

_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]+$")
_OBSERVATION_REF = re.compile(r"^observation://([^/]+)/([^/]+)$")
_CANDIDATE_SET_REF = re.compile(r"^candidate-set://([^/]+)/(.+)$")
_PREPARATION_REF = re.compile(r"^preparation://([^/]+)/(.+)$")
_ACQUIRE_INVOCATION_REF = re.compile(r"^invocation://object-acquire/[^/]+$")
_PLACE_INVOCATION_REF = re.compile(r"^invocation://object-place/[^/]+$")
_ARTIFACT_REF = re.compile(r"^artifact://[^/]+/.+$")
_DESTINATION_REF = re.compile(r"^destination://[^\s]+$")

_STEP_SPECS = (
    ("observe", "scene.observe", "query"),
    ("understand", "scene.understand", "query"),
    ("propose", "grasp.propose", "query"),
    ("prepare", "manipulation.prepare", "query"),
    ("acquire", "object.acquire", "action"),
    ("place", "object.place", "action"),
)
_STEP_IDS = tuple(item[0] for item in _STEP_SPECS)
_QUERY_SUCCESS = {"available"}
_ACTION_SUCCESS = {"succeeded"}
_STOP_STATUSES = {"failed", "cancelled", "stopped", "unknown", "empty", "invalid", "unavailable", "stale"}


class WorkflowTransitionError(ValueError):
    """Raised when a workflow transition would violate its append-only order."""


class WorkflowBindingError(ValueError):
    """Raised when a step result is not bound to the workflow's immutable inputs."""


@dataclass(frozen=True)
class WorkflowStep:
    step_id: str
    tool_id: str
    semantics: Literal["query", "action"]
    status: str = "pending"
    references: dict[str, str] = field(default_factory=dict)
    reason: str | None = None


@dataclass(frozen=True)
class WorkflowState:
    version: str
    workflow_id: str
    task_id: str
    revision_id: str
    status: Literal["ready", "running", "blocked", "succeeded"]
    active_step: str | None
    steps: tuple[WorkflowStep, ...]
    block_reason: str | None = None


def _safe_id(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or _SAFE_ID.fullmatch(value) is None:
        raise WorkflowBindingError(f"{name} must be a path-safe non-empty identifier")
    return value


def _step_tuple() -> tuple[WorkflowStep, ...]:
    return tuple(WorkflowStep(step_id, tool_id, semantics) for step_id, tool_id, semantics in _STEP_SPECS)


def _references_dict(references: dict[str, Any]) -> dict[str, str]:
    if not isinstance(references, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) or not value
        for key, value in references.items()
    ):
        raise WorkflowBindingError("references must be a string-to-string object")
    allowed = {
        "observation_ref",
        "candidate_set_ref",
        "preparation_ref",
        "acquire_invocation_ref",
        "invocation_ref",
        "destination_ref",
        "post_release_evidence_ref",
    }
    if set(references) - allowed:
        raise WorkflowBindingError("workflow references contain an unknown field")
    return dict(references)


class LongHorizonWorkflow:
    """Append-only reducer for the canonical perception-to-placement workflow.

    The reducer never invokes a Gateway. Callers execute the declared Tool through
    their existing AgentTask/ForgeToolClient path and feed only terminal status plus
    opaque references back into :meth:`record`.
    """

    def __init__(self, state: WorkflowState) -> None:
        if state.workflow_id != WORKFLOW_ID or state.version != WORKFLOW_VERSION:
            raise WorkflowBindingError("unsupported workflow identity")
        if len(state.steps) != len(_STEP_SPECS) or tuple(step.step_id for step in state.steps) != _STEP_IDS:
            raise WorkflowBindingError("workflow steps do not match the immutable workflow")
        self._state = state

    @classmethod
    def start(cls, task_id: str, revision_id: str) -> "LongHorizonWorkflow":
        task_id = _safe_id(task_id, "task_id")
        revision_id = _safe_id(revision_id, "revision_id")
        return cls(
            WorkflowState(
                version=WORKFLOW_VERSION,
                workflow_id=WORKFLOW_ID,
                task_id=task_id,
                revision_id=revision_id,
                status="ready",
                active_step="observe",
                steps=_step_tuple(),
            )
        )

    @property
    def state(self) -> WorkflowState:
        return self._state

    def next_tool(self) -> str | None:
        if self._state.active_step is None:
            return None
        return next(step.tool_id for step in self._state.steps if step.step_id == self._state.active_step)

    def record(self, step_id: str, status: str, references: dict[str, Any] | None = None) -> WorkflowState:
        if self._state.status in {"blocked", "succeeded"}:
            raise WorkflowTransitionError("workflow is terminal until an explicit recovery revision")
        if step_id != self._state.active_step:
            raise WorkflowTransitionError(
                f"step {step_id!r} is not active; expected {self._state.active_step!r}"
            )
        index = _STEP_IDS.index(step_id)
        _, tool_id, semantics = _STEP_SPECS[index]
        refs = _references_dict(references or {})
        self._validate_step_result(index, status, refs)
        steps = list(self._state.steps)
        steps[index] = WorkflowStep(step_id, tool_id, semantics, status, refs)
        if status not in (_QUERY_SUCCESS if semantics == "query" else _ACTION_SUCCESS):
            self._state = replace(
                self._state,
                status="blocked",
                active_step=step_id,
                steps=tuple(steps),
                block_reason=status,
            )
            return self._state
        next_step = _STEP_IDS[index + 1] if index + 1 < len(_STEP_IDS) else None
        self._state = replace(
            self._state,
            status="succeeded" if next_step is None else "running",
            active_step=next_step,
            steps=tuple(steps),
            block_reason=None,
        )
        return self._state

    def record_terminal_response(self, step_id: str, response: dict[str, Any]) -> WorkflowState:
        """Record a standard Gateway terminal response without hand-built references.

        The caller must pass the ``data`` object returned by ForgeToolClient's
        status/result endpoint.  Only opaque IDs and typed evidence references
        are retained; provider payloads and coordinates never enter workflow state.
        """
        if not isinstance(response, dict):
            raise WorkflowBindingError("terminal response must be an object")
        result = response.get("result") if isinstance(response.get("result"), dict) else {}
        status = response.get("status") or result.get("status")
        if not isinstance(status, str):
            phase = response.get("phase")
            status = "succeeded" if phase == "completed" else phase
        if not isinstance(status, str):
            raise WorkflowBindingError("terminal response status is required")
        refs: dict[str, str] = {}
        for key in ("observation_ref", "candidate_set_ref", "preparation_ref", "destination_ref"):
            value = result.get(key)
            if isinstance(value, str):
                refs[key] = value
        invocation_id = response.get("invocation_id")
        if isinstance(invocation_id, str):
            refs["invocation_ref"] = invocation_id
        if step_id == "place":
            acquire_ref = result.get("acquire_invocation_ref")
            if isinstance(acquire_ref, str):
                refs["acquire_invocation_ref"] = acquire_ref
            summary = result.get("capability_outcome_summary")
            evidence = summary.get("post_release_evidence") if isinstance(summary, dict) else None
            evidence_refs = evidence.get("artifact_refs") if isinstance(evidence, dict) else None
            if (
                isinstance(evidence, dict)
                and evidence.get("availability") == "complete"
                and isinstance(evidence_refs, list)
                and evidence_refs
                and isinstance(evidence_refs[0], str)
            ):
                refs["post_release_evidence_ref"] = evidence_refs[0]
        return self.record(step_id, status, refs)

    def begin_recovery(self, revision_id: str) -> "LongHorizonWorkflow":
        """Append a PlanRevision after a failed/cancelled step without rewriting history."""

        if self._state.status != "blocked":
            raise WorkflowTransitionError("recovery requires a blocked workflow")
        revision_id = _safe_id(revision_id, "revision_id")
        active = self._state.active_step
        if active is None:
            raise WorkflowTransitionError("a completed workflow has no recoverable step")
        index = _STEP_IDS.index(active)
        steps = list(self._state.steps)
        failed = steps[index]
        steps[index] = WorkflowStep(failed.step_id, failed.tool_id, failed.semantics)
        return LongHorizonWorkflow(
            WorkflowState(
                version=self._state.version,
                workflow_id=self._state.workflow_id,
                task_id=self._state.task_id,
                revision_id=revision_id,
                status="running",
                active_step=active,
                steps=tuple(steps),
            )
        )

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-safe projection containing no provider payload or coordinates."""

        return {
            "version": self._state.version,
            "workflow_id": self._state.workflow_id,
            "task_id": self._state.task_id,
            "revision_id": self._state.revision_id,
            "status": self._state.status,
            "active_step": self._state.active_step,
            "block_reason": self._state.block_reason,
            "steps": [
                {
                    "step_id": step.step_id,
                    "tool_id": step.tool_id,
                    "semantics": step.semantics,
                    "status": step.status,
                    "references": dict(step.references),
                    "reason": step.reason,
                }
                for step in self._state.steps
            ],
        }

    def _validate_step_result(self, index: int, status: str, refs: dict[str, str]) -> None:
        _, _, semantics = _STEP_SPECS[index]
        allowed_statuses = _QUERY_SUCCESS | _ACTION_SUCCESS | _STOP_STATUSES
        if status not in allowed_statuses:
            raise WorkflowTransitionError(f"unsupported workflow status {status!r}")
        if semantics == "query" and status in _ACTION_SUCCESS:
            raise WorkflowTransitionError("query steps require a query terminal status")
        if semantics == "action" and status in _QUERY_SUCCESS:
            raise WorkflowTransitionError("action steps require an action terminal status")
        if status not in (_QUERY_SUCCESS if semantics == "query" else _ACTION_SUCCESS):
            return
        if index == 0:
            observation_ref = refs.get("observation_ref")
            if observation_ref is None or _OBSERVATION_REF.fullmatch(observation_ref) is None:
                raise WorkflowBindingError("observe requires a valid observation_ref")
            return
        prior = self._state.steps[0].references
        observation_ref = refs.get("observation_ref")
        if observation_ref != prior.get("observation_ref"):
            raise WorkflowBindingError("step observation_ref differs from scene.observe")
        if index in {2, 3, 4, 5}:
            candidate_set_ref = refs.get("candidate_set_ref")
            if candidate_set_ref is None:
                raise WorkflowBindingError("this step requires a candidate_set_ref")
            match = _CANDIDATE_SET_REF.fullmatch(candidate_set_ref)
            obs_match = _OBSERVATION_REF.fullmatch(observation_ref or "")
            if match is None or obs_match is None or match.group(1) != obs_match.group(1) or match.group(2) != obs_match.group(2):
                raise WorkflowBindingError("candidate_set_ref is not bound to the observation")
            if index > 2 and candidate_set_ref != self._state.steps[2].references.get("candidate_set_ref"):
                raise WorkflowBindingError("candidate_set_ref differs from grasp.propose")
        if index in {3, 4, 5}:
            if refs.get("preparation_ref") is None:
                raise WorkflowBindingError("this step requires a preparation_ref")
            preparation_ref = refs["preparation_ref"]
            match = _PREPARATION_REF.fullmatch(preparation_ref)
            obs_match = _OBSERVATION_REF.fullmatch(observation_ref or "")
            if match is None or obs_match is None or match.group(1) != obs_match.group(1) or match.group(2) != obs_match.group(2):
                raise WorkflowBindingError("preparation_ref is not bound to the observation")
            if index > 3 and preparation_ref != self._state.steps[3].references.get("preparation_ref"):
                raise WorkflowBindingError("preparation_ref differs from manipulation.prepare")
        if index == 4:
            acquire_ref = refs.get("invocation_ref")
            if acquire_ref is None or _ACQUIRE_INVOCATION_REF.fullmatch(acquire_ref) is None:
                raise WorkflowBindingError("acquire requires an object.acquire invocation_ref")
        if index == 5:
            acquire_ref = refs.get("acquire_invocation_ref")
            place_ref = refs.get("invocation_ref")
            if acquire_ref is None or _ACQUIRE_INVOCATION_REF.fullmatch(acquire_ref) is None:
                raise WorkflowBindingError("place requires the successful acquire invocation")
            if place_ref is None or _PLACE_INVOCATION_REF.fullmatch(place_ref) is None:
                raise WorkflowBindingError("place requires an object.place invocation_ref")
            if acquire_ref != self._state.steps[4].references.get("invocation_ref"):
                raise WorkflowBindingError("place acquire_invocation_ref differs from acquire")
            if refs.get("destination_ref") is None or _DESTINATION_REF.fullmatch(refs["destination_ref"]) is None:
                raise WorkflowBindingError("place requires an opaque destination_ref")
            evidence_ref = refs.get("post_release_evidence_ref")
            if evidence_ref is None or _ARTIFACT_REF.fullmatch(evidence_ref) is None:
                raise WorkflowBindingError(
                    "successful place requires a post_release_evidence_ref"
                )


__all__ = [
    "WORKFLOW_ID",
    "WORKFLOW_VERSION",
    "WorkflowBindingError",
    "WorkflowState",
    "WorkflowStep",
    "WorkflowTransitionError",
    "LongHorizonWorkflow",
]
