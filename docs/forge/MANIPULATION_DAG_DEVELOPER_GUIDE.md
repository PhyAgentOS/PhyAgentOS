# PAOS Manipulation Planning Developer Guide

This guide is normative for the current PAOS manipulation-planning extension.
It derives ownership from PAOS task, Skill, Tool, Gateway, Evidence, and Verifier
contracts. External projects may provide failure cases, but do not define this
architecture and are not runtime dependencies.

## Ownership Matrix

| Concern | Authoritative owner | Non-owner |
|:--|:--|:--|
| User task lifecycle, recovery budget, revisions | `AgentTaskRecord`, `PlanRevision`, SQLite, `AgentTaskCoordinator` | Skill DAG, adapter, worker |
| Semantic subtask dependencies | Skill-scoped `WorkflowDag` projection | PAOS core manipulation types, RoboTwin adapter |
| Tool execution and concurrency | ToolSpec, Runtime, Gateway invocation | DAG, selector, readiness worker |
| Candidate/arm adaptation and route geometry | embodiment/benchmark adapter and versioned profile | Skill, AgentTask store |
| IK, collision, limits, complete-route feasibility | readiness provider and immutable evidence | selector, Verifier |
| Measured before/after outcome | sensor/simulation probe evidence | readiness verdict |
| User-level success or replan verdict | `ForgeTaskVerifier` against `TaskVerificationContract` | probe, adapter, selector |

## Where the DAG Lives

The canonical pick-place DAG is `WORKFLOW_DAG` in
`examples/forge-skills/pick-place-workflow/src/pick_place_workflow/long_horizon.py`.
Each `WorkflowNodeSpec` declares a provider-neutral `tool_id`, Tool semantics,
`depends_on`, and required opaque bindings. `WorkflowDag` validates identity,
unknown dependencies and cycles, computes immutable node/DAG digests, and returns
ready nodes from a caller-supplied completed-node set. `LongHorizonWorkflow`
freezes that DAG identity into its state and uses dependency-derived ready nodes
as the only successful-result admission rule; it does not advance by tuple index.

It deliberately does not persist status, append a revision, create an invocation,
retry a Tool, or lock a robot. `LongHorizonWorkflow` is a replayable reducer over
terminal Tool results. `begin_recovery(revision_id)` only rebinds the projection
after `AgentTaskCoordinator.begin_revision()` has already created the revision.
This prevents a second task scheduler from competing with PAOS SQLite truth.

For multi-resource workflows, a node may declare a symbolic
`ResourceRequirement` (single, alternative, independent-parallel, or atomic
group). The Skill planner produces an `ArmAssignment` only after the adapter has
projected a scene-bound `CapabilitySnapshot` and readiness has evaluated the
candidate/arm options. The assignment is an auditable no-motion binding; it is
not a resource lease. Sequential arm switching may use explicit park nodes.
True simultaneous bimanual work requires one Gateway-owned atomic route bundle
with one timeline, inter-arm collision scope, cancellation scope, and evidence
bundle; two independent Action posts must not be treated as synchronized.

The current six nodes form a linear DAG. The action nodes require opaque
`capability_snapshot_ref` and `assignment_ref` bindings; terminal responses may
carry them forward, but the reducer never dereferences provider payloads. This
prevents `object.acquire` or `object.place` from being admitted without an
adapter-produced, readiness-backed resource assignment. A future atomic
bimanual node must additionally bind `coordination_group_ref`; until an atomic
Gateway route provider exists, that mode remains fail-closed. Actual parallel
execution must still be scheduled through PAOS Tool records and Gateway
concurrency. `depends_on` is not a cross-Tool lease, and the reducer is not a
Runtime scheduler.

## Core Manipulation Projection

`PhyAgentOS.forge.manipulation` contains only types shared with adapters:

- `ManipulationIntent` binds one ready DAG node to task/revision/node, entity,
  observation, observation frame, scene revision, calibration, candidate set,
  criteria, constraints, and allowed arms.
- `RouteFailure` records one bounded candidate/arm rejection.
- `ReplanSignal` is a no-motion recovery hint for the existing PAOS recovery path.
- `ReplanCoordinator` validates and digests that hint; it never mutates a task.

The core also exposes provider-neutral projections for multi-resource planning:
`ResourceRequirement` describes symbolic resource semantics, `CapabilitySnapshot`
binds a profile-owned capability view to one observation/scene revision,
`ArmAssignment` records a readiness-backed no-motion resource choice, and
`CoordinationGroup` reserves the identity contract for a future atomic route
bundle. These objects are projections, not locks, invocations, or motion grants.

The `manipulation.capabilities` Query is the Skill-facing discovery seam. It
accepts only scene/observation/calibration identity, returns a validated
`CapabilitySnapshot`, and returns `unavailable` on provider failure or binding
drift. It has no task, revision, planner, Gateway, or motion side effect.

There is no core `ManipulationDag`, retry lineage, resource lock, route planner, or
provider branch. Those would duplicate existing PAOS owners or leak embodiment
policy into the core. `ResourceRequirement` is deliberately symbolic; the
concrete arm is selected by the Skill planner from adapter/readiness evidence.

## Route Data Model

Keep these representations distinct:

1. Proposal candidate: perception/provider output in the observation frame.
2. Execution grasp: adapter-approved TCP contact pose in the route frame, plus
   normalized ingress and support-clear directions and adaptation provenance.
3. Attached object: geometry, digest, object frame and measured `object_T_tcp`.
4. Placement target: target object pose and destination provenance.
5. Route template: ordered approach/contact/close/lift/transport/descent/release/
   retreat Cartesian waypoints generated from the profile policy.
6. Planner trajectory: provider output checked against joint, collision, speed,
   workspace, contact and stop policies.

`release_tcp_pose` is computed as `world_T_object_target * object_T_tcp`; it is not
the target object pose copied into a TCP command. A route selection is only a
no-motion projection and remains `motion_authorized=false`.

## Frame and Calibration Contract

- `observation_frame_id` identifies the sensor frame used by `observation_ref` and
  `candidate_set_ref`.
- route `frame_id` identifies every execution pose and must equal the workspace
  bounds frame.
- positions are metres; joint speeds are radians per second; quaternions are
  normalized `xyzw`.
- calibration has an artifact reference, SHA-256 and revision. It is used once by
  the adapter to transform proposal geometry into the route frame.
- a route-frame pose must not be transformed by the calibration again.
- `object_T_tcp` is a row-major homogeneous transform with a proper rotation and
  last row `[0, 0, 0, 1]`; its provenance is mandatory.

Missing transforms, stale scene revisions, frame drift, invalid digests or
non-finite values fail closed before a planner or probe is called.

## RoboTwin and Embodiment Extension

`manipulation-planning.yaml` owns Franka arm identities, planner/workspace/limit
references, route clearances/directions, option bound and deterministic scoring.
`arm_candidates.py` expands a candidate over allowed independent arms. Bimanual
coordination is rejected until an adapter supplies one atomic synchronized route,
shared timing, inter-arm collision checking and one evidence bundle.

To add a new robot or benchmark:

1. add a strict adapter profile for topology, arms, planner, workspace, limits and
   route policy;
2. implement proposal-to-execution-grasp and destination-to-placement-target
   adaptation with transform provenance;
3. preserve the same Skill DAG and public ToolSpecs unless semantics change;
4. run no-motion generation and readiness evidence first;
5. add a simulation/hardware executor only through existing Gateway Action
   admission, cancellation and reconciliation.

Benchmark task names, actor IDs, URDFs, controllers and coordinates must not enter
the Skill DAG or PAOS core. Replacing an embodiment should therefore change the
adapter/profile and acceptance evidence, not the task lifecycle or Tool API.

## Evidence and Verdict Boundary

Route readiness checks are:

- `attached_object_collision`;
- `complete_transport_descent_retreat`;
- `contact_dynamics`;
- `workspace_and_joint_limits`;
- `stop_control`.

The external simulation probe may record before/after snapshots, displacement,
selected arm and gripper measurements as `observed_outcome`. It must not emit a
task `semantic_verdict`. The independent route-evidence verifier validates artifact
identity and readiness scopes, then returns `task_success_authorized=false`.
`ForgeTaskVerifier` alone compares task criteria with evidence and emits the
user-level verdict.

## Failure Taxonomy

Use `RouteFailure.owner` to distinguish `input`, `binding`, `planner`, `policy`,
`collision`, `readiness`, and `infrastructure`. Preserve phase, code, detail and
route digest. All-options failure returns a bounded `ReplanSignal`; stale scenes
normally request fresh observation and candidate regeneration. Unknown execution
must be reconciled by its existing invocation ID, never replayed as a new route.

Multi-resource failures additionally use `resource_unavailable`,
`coordination_conflict`, or `partial_group_failure`. A replan hint preserves the
current task/revision identity and is consumed by `AgentTaskCoordinator`, which
alone may append a new `PlanRevision`. Experience may learn assignment ordering,
candidate ranking, and switching costs from independently verified episodes, but
may never modify workspace, joint-limit, collision, stop, readiness, or motion
authority rules.

## Validation

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
PYTHONPATH=examples/forge-adapters/robotwin20/src:examples/forge-adapters/robotwin20/runtime:examples/forge-skills/pick-place-workflow/src:. \
python -m pytest -p pytest_asyncio.plugin -q \
  tests/test_manipulation.py \
  examples/forge-skills/pick-place-workflow/tests/test_long_horizon.py \
  examples/forge-adapters/robotwin20/tests/test_route_generation.py \
  examples/forge-adapters/robotwin20/tests/test_arm_candidates.py \
  examples/forge-adapters/robotwin20/tests/test_route_readiness.py \
  examples/forge-adapters/robotwin20/tests/test_route_evidence.py
```

A passing contract suite proves deterministic binding and fail-closed behavior.
It does not prove a real route, benchmark success, arbitrary grasping, or motion
authorization.
