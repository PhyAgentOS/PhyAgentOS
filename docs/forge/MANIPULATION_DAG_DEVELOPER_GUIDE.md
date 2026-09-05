# Semantic Manipulation Planning Guide

This guide defines the first PAOS planning layer for long-horizon manipulation.
It is intentionally provider-neutral and no-motion by default.

## Design Reference and PAOS Boundary

Hephaestus is a design reference only. PAOS does not import or depend on its
classes. The useful ideas translated into PAOS contracts are immutable node and
plan digests, explicit entity/evidence/resource bindings, dependency conditions
with an `unknown` state, retry lineage, and a replan candidate that is separate
from replan authorization and execution.

PAOS remains authoritative for `AgentTaskRecord`, `PlanRevision`, SQLite task
lifecycle, CapabilityRuntime, Evidence, Verifier, and Gateway admission. The
RoboTwin adapter owns arm profiles, planner calls, route geometry, and simulator
evidence. No DAG, selector, or replan object starts a provider, simulator,
Dora, Gateway, Action, or hardware path.

## Contracts

`PhyAgentOS.forge.manipulation` provides:

- `ManipulationDag` and `ManipulationDagNode`: semantic dependency graph,
  immutable node/graph digests, bounded conditions, resource locks, expected
  effects, and retry lineage.
- `ManipulationIntent`: a node compiled with task/revision, entity,
  observation, scene, frame, calibration, and candidate-set identities. It
  always carries `motion_authorized=false`.
- `RouteFailure`: one candidate/arm rejection with phase, owner, code, and
  diagnostic detail.
- `ReplanCoordinator` and `ReplanSignal`: a bounded `replan_required`
  candidate that preserves the intent constraints. It does not mutate a task.

The existing `AgentTaskCoordinator.begin_revision()` remains the only PAOS
operation that appends a `PlanRevision` to SQLite. A caller must first place the
task in `awaiting_replan`, then pass a reviewed reason to that coordinator.

## RoboTwin Adapter

`arm_candidates.py` provides:

- `enumerate_arm_candidates(intent, candidates, profile)`: expands each grasp
  candidate over configured arms for `alternative_arm`, one configured arm for
  `single_arm`, and rejects `bimanual` until the profile supplies a synchronized
  atomic two-arm route provider. It performs identity checks only and never
  calls a planner.
- `CompleteRouteSelector`: evaluates each option through an injected
  no-motion evaluator, rejects malformed or non-passing route evidence, and
  deterministically ranks accepted complete routes by configured route length
  and speed-margin weights. Evaluator responses use
  `paos-robotwin20-route-evaluation/v1`; the selector's returned projection uses
  `paos-robotwin20-route-selection/v1`. If none pass, it returns `ReplanSignal`.

The current Franka profile is `manipulation-planning.yaml` and describes two
independent single-arm resources. `blocks_ranking_rgb` should use
`alternative_arm`, not `bimanual`; a future synchronized bimanual capability
must provide one atomic two-arm route and one evidence bundle.

## Required Bindings

Every route option and readiness result must preserve:

`task_id`, `revision_id`, `node_id`, `node_digest`, `candidate_ref`, `entity_ref`,
`candidate_set_ref`, `observation_ref`, `scene_revision`, `frame_id`,
`calibration_ref`, route geometry digest, arm identity, and evidence refs.

Any mismatch is a rejection. A stale scene requires fresh observation and a
new candidate set; it must not be repaired by changing the request in place.

## Failure and Replanning

The selector stores every failed option in `rejected_routes`. If all options
are rejected, the signal is `replan_required` with a digest over the failed
routes, preserved constraints, and current scene/candidate-set identities.
Recommended next actions are to regenerate candidates and/or refresh the
observation. The signal is not a success verdict and carries no execution
authority.

## Developer Rules

1. Keep semantic DAG code in `PhyAgentOS/forge`; do not add RoboTwin or
   planner-product branches there.
2. Keep embodiment and planner details in adapter profiles and adapter code.
3. Do not add route geometry or joint waypoints to the semantic DAG node.
4. Do not treat selector success as readiness; independent route evidence and
   manual review are still required.
5. Preserve invocation-first Action lifecycle and the existing SQLite task
   owner when execution is eventually introduced.
6. Use fresh artifact roots for every probe and preserve negative evidence.

## Validation

Run the focused contract tests, then the repository suite. A passing contract
test proves binding and fail-closed behavior, not physical reachability or
motion success.
