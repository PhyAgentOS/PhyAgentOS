---
name: scene-observe
description: Read a fresh, calibrated scene observation without causing a physical effect.
metadata: {"PhyAgentOS":{"always":false,"requires":{"runtime":["scene-observe"]}}}
---

# Scene Observe

Use `scene.observe` only to obtain measured observation artifacts. Before invocation,
read the ToolSpec and live context through `forge_tool_context`; use only the declared
sensor reference, frame, and freshness fields. A successful Query does not authorize
planning or motion and must not be passed directly to an Action.

The Query returns an explicit status, capture timestamp, scene revision, frame identity,
calibration reference, freshness measurement, and opaque artifact references. Treat
`unavailable`, `stale`, and `invalid` as blockers. Do not retry a stale or missing-
calibration result by weakening `max_age_ms`; obtain a new observation or operator input.

Use `scene.understand` only after a successful `scene.observe` result. Pass the returned
`observation_ref`, scene revision, frame, calibration reference, freshness, and artifact
references unchanged. The understanding Query returns entity/relation claims and spatial
envelopes with confidence and provenance; it does not authorize grasping, planning, or
motion. Reject stale, unavailable, ambiguous, or invalid results before any future Action.

Use `grasp.propose` only after a successful `scene.understand` result, in the fixed
workflow order:

```text
scene.observe
  -> scene.understand
  -> grasp.propose
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

For a long-horizon pick-and-place task, keep one AgentTask and one append-only
workflow revision across the complete sequence:

```text
observe -> understand -> propose -> prepare -> acquire -> place
```

The workflow reducer is a replayable projection over existing Tool records. It
accepts only terminal Tool results and opaque references, rejects skipped steps or
cross-scene bindings, and exposes the next declared Tool without invoking a
Gateway. `failed`, `cancelled`, and `unknown` stop automatic progression. Reconcile
an unknown invocation by its existing ID; for a recoverable failure append a new
PlanRevision on the same AgentTask and resume at the blocked step. Never create a
second execution protocol or infer task success from a single Action summary.
