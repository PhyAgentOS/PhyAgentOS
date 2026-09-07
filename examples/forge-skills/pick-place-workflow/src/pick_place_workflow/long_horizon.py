"""Replayable long-horizon workflow state over the existing Forge Tool API."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Literal

from PhyAgentOS.forge.manipulation import ResourceMode, ResourceRequirement

WORKFLOW_ID = "pick-and-place"
WORKFLOW_VERSION = "pick_and_place_workflow_v5"
WORKFLOW_DAG_VERSION = "pick_and_place_semantic_dag_v4"

_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]+$")
_OBSERVATION_REF = re.compile(r"^observation://([^/]+)/([^/]+)$")
_CANDIDATE_SET_REF = re.compile(r"^candidate-set://([^/]+)/(.+)$")
_PREPARATION_REF = re.compile(r"^preparation://([^/]+)/(.+)$")
_ACQUIRE_INVOCATION_REF = re.compile(r"^invocation://object-acquire/[^/]+$")
_PLACE_INVOCATION_REF = re.compile(r"^invocation://object-place/[^/]+$")
_ARTIFACT_REF = re.compile(r"^artifact://[^/]+/.+$")
_DESTINATION_REF = re.compile(r"^destination://[^\s]+$")
_KNOWN_BINDINGS = {
    "observation_ref",
    "candidate_set_ref",
    "preparation_ref",
    "acquire_invocation_ref",
    "invocation_ref",
    "destination_ref",
    "post_release_evidence_ref",
    "capability_snapshot_ref",
    "assignment_ref",
    "coordination_group_ref",
}

_QUERY_SUCCESS = {"available"}
_ACTION_SUCCESS = {"succeeded"}
_STOP_STATUSES = {"failed", "cancelled", "stopped", "unknown", "empty", "invalid", "unavailable", "stale"}


class WorkflowTransitionError(ValueError):
    """Raised when a workflow transition would violate its append-only order."""


class WorkflowBindingError(ValueError):
    """Raised when a step result is not bound to the workflow's immutable inputs."""


@dataclass(frozen=True)
class WorkflowNodeSpec:
    """Skill-scoped semantic node; it is not a task or execution record."""

    node_id: str
    tool_id: str
    semantics: Literal["query", "action"]
    depends_on: tuple[str, ...] = ()
    required_bindings: tuple[str, ...] = ()
    resource_requirement: ResourceRequirement | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.node_id, str)
            or _SAFE_ID.fullmatch(self.node_id) is None
            or not isinstance(self.tool_id, str)
            or _SAFE_ID.fullmatch(self.tool_id) is None
            or self.semantics not in {"query", "action"}
        ):
            raise WorkflowBindingError("workflow DAG node identity is invalid")
        if (
            not isinstance(self.depends_on, tuple)
            or len(self.depends_on) != len(set(self.depends_on))
            or any(not isinstance(item, str) or _SAFE_ID.fullmatch(item) is None for item in self.depends_on)
        ):
            raise WorkflowBindingError("workflow DAG dependencies are invalid")
        if (
            not isinstance(self.required_bindings, tuple)
            or len(self.required_bindings) != len(set(self.required_bindings))
            or set(self.required_bindings) - _KNOWN_BINDINGS
        ):
            raise WorkflowBindingError("workflow DAG required bindings are invalid")


@dataclass(frozen=True)
class WorkflowDag:
    """Validated immutable projection consumed before PAOS Tool execution."""

    version: str
    workflow_id: str
    nodes: tuple[WorkflowNodeSpec, ...]

    def __post_init__(self) -> None:
        if self.version != WORKFLOW_DAG_VERSION or self.workflow_id != WORKFLOW_ID:
            raise WorkflowBindingError("unsupported workflow DAG identity")
        if not isinstance(self.nodes, tuple) or any(
            not isinstance(node, WorkflowNodeSpec) for node in self.nodes
        ):
            raise WorkflowBindingError("workflow DAG nodes must be an immutable node tuple")
        node_ids = tuple(node.node_id for node in self.nodes)
        if not node_ids or len(node_ids) != len(set(node_ids)):
            raise WorkflowBindingError("workflow DAG node identities must be unique")
        known = set(node_ids)
        visited: set[str] = set()
        visiting: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise WorkflowBindingError("workflow DAG must be acyclic")
            if node_id in visited:
                return
            visiting.add(node_id)
            node = next(item for item in self.nodes if item.node_id == node_id)
            if set(node.depends_on) - known or node.node_id in node.depends_on:
                raise WorkflowBindingError("workflow DAG dependency is invalid")
            for dependency in node.depends_on:
                visit(dependency)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in node_ids:
            visit(node_id)
    def ready_nodes(self, completed: set[str]) -> tuple[WorkflowNodeSpec, ...]:
        """Return deterministic ready nodes without executing or mutating a task."""

        if not isinstance(completed, set) or any(not isinstance(item, str) for item in completed):
            raise WorkflowBindingError("completed nodes must be a string set")
        known = {node.node_id for node in self.nodes}
        if not completed <= known:
            raise WorkflowBindingError("completed nodes are not part of the workflow DAG")
        return tuple(
            node
            for node in self.nodes
            if node.node_id not in completed and set(node.depends_on) <= completed
        )


WORKFLOW_DAG = WorkflowDag(
    version=WORKFLOW_DAG_VERSION,
    workflow_id=WORKFLOW_ID,
    nodes=(
        WorkflowNodeSpec("observe", "scene.observe", "query"),
        WorkflowNodeSpec(
            "capabilities",
            "manipulation.capabilities",
            "query",
            ("observe",),
            ("observation_ref", "capability_snapshot_ref"),
        ),
        WorkflowNodeSpec(
            "understand", "scene.understand", "query", ("observe",),
            ("observation_ref",),
        ),
        WorkflowNodeSpec(
            "propose", "grasp.propose", "query", ("understand", "capabilities"),
            ("observation_ref", "capability_snapshot_ref"),
        ),
        WorkflowNodeSpec(
            "prepare",
            "manipulation.prepare",
            "query",
            ("propose",),
            ("observation_ref", "candidate_set_ref", "capability_snapshot_ref"),
        ),
        WorkflowNodeSpec(
            "acquire",
            "object.acquire",
            "action",
            ("prepare",),
            (
                "observation_ref", "candidate_set_ref", "preparation_ref",
                "capability_snapshot_ref", "assignment_ref", "invocation_ref",
            ),
            ResourceRequirement(
                mode=ResourceMode.ALTERNATIVE_RESOURCE,
                substitution_allowed=True,
            ),
        ),
        WorkflowNodeSpec(
            "place",
            "object.place",
            "action",
            ("acquire",),
            (
                "observation_ref",
                "candidate_set_ref",
                "preparation_ref",
                "acquire_invocation_ref",
                "invocation_ref",
                "destination_ref",
                "post_release_evidence_ref",
                "capability_snapshot_ref",
                "assignment_ref",
            ),
            ResourceRequirement(
                mode=ResourceMode.ALTERNATIVE_RESOURCE,
                substitution_allowed=True,
            ),
        ),
    ),
)
_STEP_SPECS = tuple(
    (node.node_id, node.tool_id, node.semantics) for node in WORKFLOW_DAG.nodes
)
_STEP_IDS = tuple(node.node_id for node in WORKFLOW_DAG.nodes)


@dataclass(frozen=True)
class WorkflowStep:
    step_id: str
    tool_id: str
    semantics: Literal["query", "action"]
    status: str = "pending"
    references: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    reason: str | None = None

    def __post_init__(self) -> None:
        refs = _references_dict(self.references)
        object.__setattr__(self, "references", MappingProxyType(refs))


@dataclass(frozen=True)
class WorkflowState:
    version: str
    workflow_id: str
    dag_version: str
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


def _step_tuple(dag: WorkflowDag) -> tuple[WorkflowStep, ...]:
    return tuple(
        WorkflowStep(node.node_id, node.tool_id, node.semantics)
        for node in dag.nodes
    )


def _references_dict(references: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(references, Mapping) or any(
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
        "capability_snapshot_ref",
        "assignment_ref",
        "coordination_group_ref",
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
        if not isinstance(state, WorkflowState):
            raise WorkflowBindingError("workflow state must be a WorkflowState")
        if state.workflow_id != WORKFLOW_ID or state.version != WORKFLOW_VERSION:
            raise WorkflowBindingError("unsupported workflow identity")
        _safe_id(state.task_id, "task_id")
        _safe_id(state.revision_id, "revision_id")
        if (
            state.dag_version != WORKFLOW_DAG.version
        ):
            raise WorkflowBindingError("workflow state DAG binding is stale or invalid")
        if not isinstance(state.steps, tuple) or any(
            not isinstance(step, WorkflowStep) for step in state.steps
        ):
            raise WorkflowBindingError("workflow state steps must be immutable WorkflowSteps")
        if len(state.steps) != len(WORKFLOW_DAG.nodes) or tuple(
            step.step_id for step in state.steps
        ) != tuple(
            node.node_id for node in WORKFLOW_DAG.nodes
        ):
            raise WorkflowBindingError("workflow steps do not match the immutable workflow")
        self._dag = WORKFLOW_DAG
        self._node_by_id = {node.node_id: node for node in WORKFLOW_DAG.nodes}
        self._step_ids = tuple(self._node_by_id)
        self._state = state
        self._validate_state()

    @classmethod
    def start(
        cls,
        task_id: str,
        revision_id: str,
    ) -> "LongHorizonWorkflow":
        task_id = _safe_id(task_id, "task_id")
        revision_id = _safe_id(revision_id, "revision_id")
        initial_ready = WORKFLOW_DAG.ready_nodes(set())
        if not initial_ready:
            raise WorkflowBindingError("workflow DAG has no initial ready node")
        return cls(
            WorkflowState(
                version=WORKFLOW_VERSION,
                workflow_id=WORKFLOW_ID,
                dag_version=WORKFLOW_DAG.version,
                task_id=task_id,
                revision_id=revision_id,
                status="ready",
                active_step=initial_ready[0].node_id,
                steps=_step_tuple(WORKFLOW_DAG),
            )
        )

    @property
    def state(self) -> WorkflowState:
        return self._state

    def next_tool(self) -> str | None:
        if self._state.active_step is None:
            return None
        return self._node_by_id[self._state.active_step].tool_id

    def next_tools(self) -> tuple[str, ...]:
        """Return every currently ready Tool in deterministic DAG declaration order."""

        return tuple(node.tool_id for node in self._ready_nodes())

    def _completed_nodes(self) -> set[str]:
        return {
            step.step_id
            for step in self._state.steps
            if step.status in (_QUERY_SUCCESS if step.semantics == "query" else _ACTION_SUCCESS)
        }

    def _ready_nodes(self) -> tuple[WorkflowNodeSpec, ...]:
        if self._state.status in {"blocked", "succeeded"}:
            return ()
        return self._dag.ready_nodes(self._completed_nodes())

    def ready_nodes(self) -> tuple[WorkflowNodeSpec, ...]:
        """Project DAG readiness from terminal-success states only."""

        return self._ready_nodes()

    def record(self, step_id: str, status: str, references: dict[str, Any] | None = None) -> WorkflowState:
        if self._state.status in {"blocked", "succeeded"}:
            raise WorkflowTransitionError("workflow is terminal until an explicit recovery revision")
        if step_id not in self._node_by_id:
            raise WorkflowTransitionError(f"step {step_id!r} is not part of the workflow DAG")
        ready_ids = {node.node_id for node in self._ready_nodes()}
        if step_id not in ready_ids:
            raise WorkflowTransitionError(
                f"step {step_id!r} is not ready; ready nodes are {sorted(ready_ids)!r}"
            )
        step = self._node_by_id[step_id]
        refs = _references_dict(references or {})
        self._validate_step_result(step_id, status, refs)
        steps = list(self._state.steps)
        index = self._step_ids.index(step_id)
        steps[index] = WorkflowStep(step_id, step.tool_id, step.semantics, status, refs)
        if status not in (_QUERY_SUCCESS if step.semantics == "query" else _ACTION_SUCCESS):
            self._state = replace(
                self._state,
                status="blocked",
                active_step=step_id,
                steps=tuple(steps),
                block_reason=status,
            )
            return self._state
        completed = {
            item.step_id
            for item in steps
            if item.status in (_QUERY_SUCCESS if item.semantics == "query" else _ACTION_SUCCESS)
        }
        ready = self._dag.ready_nodes(completed)
        next_step = ready[0].node_id if ready else None
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
        for key in (
            "observation_ref", "candidate_set_ref", "preparation_ref", "destination_ref",
            "capability_snapshot_ref", "assignment_ref", "coordination_group_ref",
        ):
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
        """Rebind the projection after PAOS has appended a new PlanRevision.

        This reducer does not create, persist, or authorize that revision.
        """

        if self._state.status != "blocked":
            raise WorkflowTransitionError("recovery requires a blocked workflow")
        revision_id = _safe_id(revision_id, "revision_id")
        active = self._state.active_step
        if active is None:
            raise WorkflowTransitionError("a completed workflow has no recoverable step")
        index = self._step_ids.index(active)
        steps = list(self._state.steps)
        failed = steps[index]
        steps[index] = WorkflowStep(failed.step_id, failed.tool_id, failed.semantics)
        completed = {
            step.step_id
            for step in steps
            if step.status in (_QUERY_SUCCESS if step.semantics == "query" else _ACTION_SUCCESS)
        }
        ready = self._dag.ready_nodes(completed)
        if not ready:
            raise WorkflowTransitionError("recovered workflow has no ready node")
        return LongHorizonWorkflow(
            WorkflowState(
                version=self._state.version,
                workflow_id=self._state.workflow_id,
                dag_version=self._state.dag_version,
                task_id=self._state.task_id,
                revision_id=revision_id,
                status="running" if completed else "ready",
                active_step=ready[0].node_id,
                steps=tuple(steps),
            )
        )

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-safe projection containing no provider payload or coordinates."""

        return {
            "version": self._state.version,
            "dag_version": self._state.dag_version,
            "workflow_id": self._state.workflow_id,
            "task_id": self._state.task_id,
            "revision_id": self._state.revision_id,
            "status": self._state.status,
            "active_step": self._state.active_step,
            "ready_steps": [node.node_id for node in self._ready_nodes()],
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

    def _validate_step_result(self, step_id: str, status: str, refs: dict[str, str]) -> None:
        step = self._node_by_id[step_id]
        semantics = step.semantics
        allowed_statuses = _QUERY_SUCCESS | _ACTION_SUCCESS | _STOP_STATUSES
        if status not in allowed_statuses:
            raise WorkflowTransitionError(f"unsupported workflow status {status!r}")
        if semantics == "query" and status in _ACTION_SUCCESS:
            raise WorkflowTransitionError("query steps require a query terminal status")
        if semantics == "action" and status in _QUERY_SUCCESS:
            raise WorkflowTransitionError("action steps require an action terminal status")
        if status not in (_QUERY_SUCCESS if semantics == "query" else _ACTION_SUCCESS):
            return
        missing = set(step.required_bindings) - set(refs)
        if missing:
            raise WorkflowBindingError(
                f"step {step_id!r} is missing required bindings: {sorted(missing)!r}"
            )
        if step_id == "observe":
            observation_ref = refs.get("observation_ref")
            if observation_ref is None or _OBSERVATION_REF.fullmatch(observation_ref) is None:
                raise WorkflowBindingError("observe requires a valid observation_ref")
            return
        prior = self._step("observe").references
        observation_ref = refs.get("observation_ref")
        if observation_ref != prior.get("observation_ref"):
            raise WorkflowBindingError("step observation_ref differs from scene.observe")
        if step_id == "capabilities":
            capability_ref = refs.get("capability_snapshot_ref")
            if capability_ref is None or _ARTIFACT_REF.fullmatch(capability_ref) is None:
                raise WorkflowBindingError("capabilities requires a valid capability_snapshot_ref")
            return
        if step_id not in {"capabilities", "understand"}:
            capability_ref = refs.get("capability_snapshot_ref")
            if capability_ref is None or _ARTIFACT_REF.fullmatch(capability_ref) is None:
                raise WorkflowBindingError("step requires a valid capability_snapshot_ref")
            if capability_ref != self._step("capabilities").references.get("capability_snapshot_ref"):
                raise WorkflowBindingError("capability_snapshot_ref differs from manipulation.capabilities")
        if step_id in {"propose", "prepare", "acquire", "place"}:
            candidate_set_ref = refs.get("candidate_set_ref")
            if candidate_set_ref is None:
                raise WorkflowBindingError("this step requires a candidate_set_ref")
            match = _CANDIDATE_SET_REF.fullmatch(candidate_set_ref)
            obs_match = _OBSERVATION_REF.fullmatch(observation_ref or "")
            if match is None or obs_match is None or match.group(1) != obs_match.group(1) or match.group(2) != obs_match.group(2):
                raise WorkflowBindingError("candidate_set_ref is not bound to the observation")
            if step_id != "propose" and candidate_set_ref != self._step("propose").references.get("candidate_set_ref"):
                raise WorkflowBindingError("candidate_set_ref differs from grasp.propose")
        if step_id in {"prepare", "acquire", "place"}:
            if refs.get("preparation_ref") is None:
                raise WorkflowBindingError("this step requires a preparation_ref")
            preparation_ref = refs["preparation_ref"]
            match = _PREPARATION_REF.fullmatch(preparation_ref)
            obs_match = _OBSERVATION_REF.fullmatch(observation_ref or "")
            if match is None or obs_match is None or match.group(1) != obs_match.group(1) or match.group(2) != obs_match.group(2):
                raise WorkflowBindingError("preparation_ref is not bound to the observation")
            if step_id != "prepare" and preparation_ref != self._step("prepare").references.get("preparation_ref"):
                raise WorkflowBindingError("preparation_ref differs from manipulation.prepare")
        if step_id == "acquire":
            if _ARTIFACT_REF.fullmatch(refs.get("assignment_ref", "")) is None:
                raise WorkflowBindingError("acquire requires a valid assignment_ref")
            acquire_ref = refs.get("invocation_ref")
            if acquire_ref is None or _ACQUIRE_INVOCATION_REF.fullmatch(acquire_ref) is None:
                raise WorkflowBindingError("acquire requires an object.acquire invocation_ref")
        if step_id == "place":
            if _ARTIFACT_REF.fullmatch(refs.get("assignment_ref", "")) is None:
                raise WorkflowBindingError("place requires a valid assignment_ref")
            acquire_ref = refs.get("acquire_invocation_ref")
            place_ref = refs.get("invocation_ref")
            if acquire_ref is None or _ACQUIRE_INVOCATION_REF.fullmatch(acquire_ref) is None:
                raise WorkflowBindingError("place requires the successful acquire invocation")
            if place_ref is None or _PLACE_INVOCATION_REF.fullmatch(place_ref) is None:
                raise WorkflowBindingError("place requires an object.place invocation_ref")
            if acquire_ref != self._step("acquire").references.get("invocation_ref"):
                raise WorkflowBindingError("place acquire_invocation_ref differs from acquire")
            if refs.get("destination_ref") is None or _DESTINATION_REF.fullmatch(refs["destination_ref"]) is None:
                raise WorkflowBindingError("place requires an opaque destination_ref")
            evidence_ref = refs.get("post_release_evidence_ref")
            if evidence_ref is None or _ARTIFACT_REF.fullmatch(evidence_ref) is None:
                raise WorkflowBindingError(
                    "successful place requires a post_release_evidence_ref"
                )

    def _step(self, step_id: str) -> WorkflowStep:
        return self._state.steps[self._step_ids.index(step_id)]

    def _validate_state(self) -> None:
        allowed = {"pending"} | _QUERY_SUCCESS | _ACTION_SUCCESS | _STOP_STATUSES
        for step in self._state.steps:
            node = self._node_by_id[step.step_id]
            if step.tool_id != node.tool_id or step.semantics != node.semantics:
                raise WorkflowBindingError("workflow state node binding is invalid")
            if step.status not in allowed:
                raise WorkflowBindingError("workflow state contains an invalid step status")
            _references_dict(step.references)
            if step.status != "pending":
                self._validate_step_result(step.step_id, step.status, step.references)
        completed = self._completed_nodes()
        failed = tuple(
            step.step_id
            for step in self._state.steps
            if step.status not in {"pending"} | _QUERY_SUCCESS | _ACTION_SUCCESS
        )
        for node_id in completed:
            if not set(self._node_by_id[node_id].depends_on) <= completed:
                raise WorkflowBindingError("workflow state completed a node before its dependencies")
        if self._state.status == "blocked":
            if (
                len(failed) != 1
                or self._state.active_step != failed[0]
                or self._state.block_reason != self._step(failed[0]).status
                or not set(self._node_by_id[failed[0]].depends_on) <= completed
            ):
                raise WorkflowBindingError("blocked workflow state must identify one failed node")
            return
        if failed:
            raise WorkflowBindingError("non-blocked workflow state contains a failed node")
        if self._state.block_reason is not None:
            raise WorkflowBindingError("non-blocked workflow state cannot retain a block reason")
        ready = self._dag.ready_nodes(completed)
        expected_active = ready[0].node_id if ready else None
        expected_status = (
            "succeeded"
            if len(completed) == len(self._dag.nodes)
            else "ready"
            if not completed
            else "running"
        )
        if self._state.status != expected_status or self._state.active_step != expected_active:
            raise WorkflowBindingError("workflow state status does not match DAG readiness")


__all__ = [
    "WORKFLOW_ID",
    "WORKFLOW_DAG",
    "WORKFLOW_DAG_VERSION",
    "WORKFLOW_VERSION",
    "WorkflowBindingError",
    "WorkflowDag",
    "WorkflowNodeSpec",
    "WorkflowState",
    "WorkflowStep",
    "WorkflowTransitionError",
    "LongHorizonWorkflow",
]
