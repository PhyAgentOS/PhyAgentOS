---
name: pick-place-workflow
description: Execute a provider-neutral pick-and-place workflow through governed observation, grasp, preparation, acquire, and place Tools.
metadata: {"PhyAgentOS":{"always":false,"requires":{"runtime":["pick-place-workflow"]}}}
---

# Pick and Place Workflow

This Skill describes one complete provider-neutral pick-and-place workflow. It is
not a scene-observation-only Skill: `scene.observe` and `scene.understand` are the
perception steps, `grasp.propose` and `manipulation.prepare` are non-mutating
planning/readiness steps, and `object.acquire` plus `object.place` are bounded
physical-effect Actions. The Skill does not implement any provider, simulator,
camera driver, robot SDK, or task-specific success rule.

Use `scene.observe` only to obtain measured observation artifacts. Before invocation,
read the ToolSpec and live context through `forge_tool_context`; use only the declared
sensor reference, frame, and freshness fields. A successful Query does not authorize
planning or motion and must not be passed directly to an Action.

The Query returns an explicit status, capture timestamp, scene revision, frame identity,
calibration reference, freshness measurement, and opaque artifact references. Treat
`unavailable`, `stale`, and `invalid` as blockers. Do not retry a stale or missing-
calibration result by weakening `max_age_ms`; obtain a new observation or operator input.

After a successful `scene.observe` result, the Agent may call
`manipulation.capabilities` or `scene.understand`; these are independent Query
nodes and may be called in either order or in parallel. For
`manipulation.capabilities`, pass the
observation reference, scene revision, and calibration reference unchanged. This
read-only Query returns the adapter-owned, scene-bound capability snapshot used to
reason about available arms and later assignment. It does not lease a resource,
run readiness, create an invocation, or authorize motion. Treat `unavailable`,
`stale`, and `invalid` as blockers, and preserve its opaque
`capability_snapshot_ref` for every downstream step.

Use `scene.understand` after a successful `scene.observe` result. It does not
depend on the capability Query. Pass the returned
`observation_ref`, scene revision, frame, calibration reference, freshness, and artifact
references unchanged. The understanding Query returns entity/relation claims and spatial
envelopes with confidence and provenance. It may also return opaque derived artifacts for
instance masks, object point clouds, and metric localization, but only when their observation,
entity, frame, calibration, source lineage, and root provenance bindings are complete. These
artifacts are Query evidence, not grasp candidates or motion authorization. Reject stale,
unavailable, ambiguous, or invalid results before any future Action.

Use `grasp.propose` only after both `scene.understand` and
`manipulation.capabilities` have returned successful terminal results. The Agent
may satisfy those two dependencies in either order or in parallel:

```text
scene.observe
  ├─ manipulation.capabilities ─┐
  └─ scene.understand ───────────┴─ grasp.propose
  -> manipulation.prepare
  -> object.acquire
  -> object.place
```

Pass the returned observation reference, scene revision, frame, calibration reference,
freshness, and target entity claims with their spatial envelopes unchanged. Never skip the
freshness, calibration, frame, or provenance checks. The proposal Query returns
provider-neutral grasp candidates with candidate identity, frame/calibration binding,
provenance, confidence, score, and bounded funnel evidence. Candidates are proposals only:
they are not IK-verified, not collision-free, and not action-admitted, and they must not be
sent directly to an Action. An `empty` result means no candidates exist for the targets; do
not fabricate or substitute default candidates and do not loosen thresholds or skip safety
checks to obtain candidates. Any further preparation must go through an independent
`manipulation.prepare` Query, and motion authorization stays with the Gateway/Runtime
admission path.

Use `manipulation.prepare` only after a successful `grasp.propose` result. Pass the
observation reference, scene revision, frame, calibration reference, freshness,
candidate-set reference, and complete candidate records unchanged. This Query is a
non-mutating readiness assessment with three explicit checks: `workspace`,
`kinematic`, and `collision`. Only candidates with all three checks reported as
`pass` can appear as `qualification: prepared`; rejected candidates are omitted and
an empty set is returned explicitly as `status: empty`.

Preparation evidence is not an IK guarantee, collision guarantee for a future
trajectory, or execution admission. Treat `stale`, `unavailable`, and `invalid` as
blockers. Never call `invoke_action` or start a Session with this Query, and never
interpret `motion_authorized: false` as permission to bypass the Gateway/Runtime
admission path.

Use `object.acquire` only after `manipulation.prepare` returned a selected prepared
candidate and the current Tool context is ready. Create one AgentTask binding and
pass the observation, scene, frame, calibration, candidate-set, preparation,
candidate, and entity references unchanged. Start it through
`forge_tool_start_action`, then reconcile the returned `invocation_id` with the
standard status/result routes. Admission is not completion; pending, cancellation
acceptance, timeout, and `unknown` do not prove a physical stop and must not be
blindly retried.

The bounded Action owns its internal approach/contact/close/lift/hold phases. Use
the terminal `capability_outcome_summary_v1` for phase attribution only after the
Gateway result is terminal. It is execution evidence, not a replacement for
`AgentTask finalize` or the generic verification contract.

Use `object.place` only after `object.acquire` is terminal with `status: succeeded`.
Pass the same observation, scene, frame, calibration, candidate-set, preparation,
candidate, and entity references, plus the acquire invocation reference and an
opaque `destination_ref`, unchanged into the place Action. A destination reference
does not expose coordinates, simulator fields, or controller parameters; its
meaning is resolved by the Gateway profile. Transport, descent, release, and
retreat are internal bounded phases. Reconcile the place invocation through the
standard status/result/cancel routes and treat cancellation acceptance and
`unknown` as physically uncertain.

The terminal place summary includes `post_release_evidence`, which reports only
typed artifact references and their availability. This evidence is required for
verification of the released object's destination state; a successful Action is
not by itself a user-level task verdict. Do not retry release blindly or infer
placement from an unverified acquire result.

For a long-horizon pick-and-place task, keep one AgentTask and one PAOS-owned
append-only PlanRevision across the complete sequence. The Skill exposes a
read-only semantic DAG projection (`WORKFLOW_DAG`) for dependencies and ready
nodes; it does not create revisions, hold resource leases, or execute Tools:

```text
observe -> {capabilities, understand} -> propose -> prepare -> acquire -> place
```

The workflow reducer is a replayable projection over existing Tool records. It
accepts only terminal Tool results and opaque references, rejects skipped steps or
cross-scene bindings, and exposes the next declared Tool without invoking a
Gateway. `failed`, `cancelled`, and `unknown` stop automatic progression. Reconcile
an unknown invocation by its existing ID; for a recoverable failure ask the PAOS
task coordinator to append a new PlanRevision, then rebind this projection to
that revision. Never create a second execution protocol or infer task success
from a single Action summary.

For a task whose objects must be decomposed or assigned dynamically, the Agent
may select `planning_mode=agent_composed` and submit semantic subtasks to
`compose_agent_plan`. The resulting PlanGraph describes obligations and
dependencies, not a hard-coded Tool sequence. For each ready node,
`DynamicToolPlanner.candidate_tools` returns all frozen Tool candidates matching
the node capability; the Agent chooses one and `DynamicToolPlanner.admit`
performs PAOS evidence, scene, capability, resource, and ToolSpec checks before
the caller invokes the normal AgentTask/ForgeToolClient path. This bridge does
not execute Tools, create revisions, hold leases, or authorize motion. The
`baseline` reducer remains available for deterministic replay.
