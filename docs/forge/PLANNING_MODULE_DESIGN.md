# PAOS Planning Module Design

## Status

This document is the implementation baseline for `PhyAgentOS/planning`. It is
an approved design boundary, not a second task runtime.

## Purpose

The module represents an Agent-composed semantic subtask DAG and evaluates
whether a proposed Tool call is structurally and evidentially admissible. It
does not execute Tools, own a task lifecycle, persist facts, acquire locks, or
authorize motion.

The task-level shape is:

```text
relocate(red)  ─────┐
relocate(blue) ─────┼──> verify
```

Each semantic node may select a different Tool sequence. The old fixed
`observe -> capabilities -> understand -> propose -> prepare -> acquire ->
place` sequence remains a Skill baseline policy only; it is not the only legal
plan.

## Ownership boundary

| Boundary | Owner | Rule |
| --- | --- | --- |
| PlanGraph and Tool-call protocol | `PhyAgentOS/planning` | Immutable Pydantic contracts and pure validation only |
| Task, revision, execution facts | `forge/task.py` and SQLite | The only lifecycle authority |
| Tool transport and invocation | `forge/tool_client.py` / Gateway | The only execution plane |
| Robot capability and readiness | adapter/provider | Physical facts; fail closed |
| Semantic success | Verifier | Task-level verdict authority |
| Policy candidates and promotion | `agent/experience` / Skill Runtime | Review and independent evaluation required |

The planning module must not import Gateway clients, SQLite stores, adapter
providers, or Skill Runtime state.

## Protocols

- `PlanGraph` / `PlanNode`: current task's semantic DAG, bound to a task and
  revision digest. Nodes describe obligations, capabilities, dependencies,
  evidence, resource claims, and retry lineage.
- `ToolSpecPolicy`: planning projection of a ToolSpec. It declares
  preconditions, required/produced evidence, expected effects, resources,
  scene-write behavior, failure classes, and idempotency. It is not a second
  provider configuration source.
- `ToolCallEnvelope`: Agent proposal with task/revision/node identity,
  ToolSpec digest, input-binding digest, scene revision, and idempotency key.
- `ToolResultEnvelope`: execution result projection. `unknown`, `failed`, and
  `cancelled` are distinct; a result never grants motion authority.
- `NodeSettlement`: normalized node fact (`completed`, `failed`, `outcome_unknown`,
  `blocked_by_dependency`, `stale`, or `cancelled_before_start`).
- `ReplanDelta`: preserve/cancel/invalidate/retry instructions and fresh
  evidence requirements. The coordinator, not this module, creates a new
  `PlanRevision`.
- `DecisionTrace`: redacted, attributable record of candidate Tools, selected
  Tool, policy/context digests, and result/evidence references.
- `WorkflowPolicy`: reusable partial-order and Tool-selection policy. It is
  separate from a concrete `PlanGraph`; one successful episode never rewrites a
  policy automatically.

`PlanRevision` stores an immutable `artifact://` graph reference plus graph,
planner-decision, and policy-snapshot digests;
`ToolExecutionRecord` stores node/obligation/input-binding/decision-trace
references when a Tool call is attached to a semantic node. These are optional
for legacy records but become an all-or-nothing binding once any planning field
is supplied. SQLite continues to persist the aggregate; this module only
validates the shape.

## Dynamic Tool admission

The Agent may choose any Tool present in the frozen binding. Admission is
constrained by the ToolSpec projection and current context:

1. The node exists and is ready in the DAG.
2. The proposed Tool matches the node capability and bound ToolSpec digest.
3. Required evidence is present and references the current scene revision.
4. Resource claims do not conflict with currently held resources.
5. Action/session semantics remain subject to Gateway admission; planning only
   returns a decision.

Thus the rule is **not a fixed order, but fixed legality conditions**.

## Evolution boundary

Experience may propose changes to Tool order, optional queries, re-observation,
candidate ranking, arm preference, retry/replan strategy, and semantic
parameter binding. It may not change workspace, joint limits, collision/stop
policy, transforms, readiness, Gateway authority, or Verifier safety rules.

Only a complete attributable AgentTask episode with independent semantic
verification can produce a `WorkflowPolicyCandidate`; replay/matched evaluation
and review are required before Skill promotion.

## Failure semantics

Missing evidence, stale scene, dependency failure, resource conflict, unknown
Tool, and cycle are explicit rejection paths. Timeout/transport uncertainty is
represented as `outcome_unknown`, never as success. Replanning preserves task
identity while the PAOS coordinator owns the new revision and retry budget.

## Migration stages

1. Keep the existing Skill workflow as a deterministic baseline policy.
2. Generate an Agent-composed no-motion semantic DAG for multi-object tasks.
3. Select Tools dynamically through admission checks.
4. Record DecisionTrace and derive reviewed policy candidates.
5. Promote only reviewed, independently evaluated Skill policy versions.

The pick-place Skill exposes these modes explicitly: `baseline` uses the legacy
fixed Tool projection for compatibility/replay; `agent_composed` compiles
Agent-provided semantic subtasks into `PlanGraph` and uses dynamic Tool
candidate admission. The Skill bridge is an adapter over the planning library,
not a second planner runtime.

## Review gates

Every change to this module is reviewed across architecture integration,
failure paths, authority boundaries, configuration/provenance, and
maintainability. Tests must prove the module is pure: no Gateway calls, no
SQLite writes, no locks, and no `motion_authorized=True` output.
