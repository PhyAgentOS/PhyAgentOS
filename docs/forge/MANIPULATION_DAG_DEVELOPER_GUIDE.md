# PAOS Manipulation Planning Developer Guide

This guide is normative for the current PAOS manipulation-planning extension.
It derives ownership from PAOS task, Skill, Tool, Gateway, Evidence, and Verifier
contracts. External projects may provide failure cases, but do not define this
architecture and are not runtime dependencies.

## Ownership Matrix

| Concern | Authoritative owner | Non-owner |
|:--|:--|:--|
| User task lifecycle, recovery budget, revisions | `AgentTaskRecord`, `PlanRevision`, SQLite, `AgentTaskCoordinator` | Skill DAG, adapter, worker |
| Semantic subtask dependencies | `PhyAgentOS.planning.PlanGraph`, bound to `PlanRevision` | Skill policy/template, adapter, worker |
| Tool execution and concurrency | ToolSpec, Runtime, Gateway invocation | DAG, selector, readiness worker |
| Candidate/arm adaptation and route geometry | embodiment/benchmark adapter and versioned profile | Skill, AgentTask store |
| IK, collision, limits, complete-route feasibility | readiness provider and immutable evidence | selector, Verifier |
| Measured before/after outcome | sensor/simulation probe evidence | readiness verdict |
| User-level success or replan verdict | `ForgeTaskVerifier` against `TaskVerificationContract` | probe, adapter, selector |

The standalone [Planning Module Design](PLANNING_MODULE_DESIGN.md) defines the
new pure protocol boundary. It is a library, not a Planner service: it may
validate a graph, derive ready nodes, admit a proposed Tool, normalize a
settlement, and construct a replan delta, but it cannot call Gateway, write
SQLite, hold a lock, or grant motion authority.

## Where the DAG Lives

The current Skill workflow in
`examples/forge-skills/pick-place-workflow/src/pick_place_workflow/long_horizon.py`
is a deterministic baseline `WorkflowPolicy`/projection. A concrete task's
semantic DAG is `PhyAgentOS.planning.PlanGraph`, bound to the task's
`PlanRevision` by graph and policy digests. `WorkflowDag` remains useful for
backward-compatible replay, but it is not the only legal task graph and does
not own lifecycle facts. `LongHorizonWorkflow` freezes its baseline projection
and uses dependency-derived ready nodes; an Agent-composed graph uses the same
pure planning contracts with dynamic Tool admission.

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

The current seven nodes form a baseline dependency DAG, not a fixed execution
queue and not a universal task decomposition.
After `observe`, both `manipulation.capabilities` and `scene.understand` may be
ready; the Agent may call them in either order or in parallel. `grasp.propose`
is the explicit join and requires both terminal Query results. The
`manipulation.capabilities` Query discovers the adapter-owned capability
snapshot; the action nodes require opaque
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

The planning module now owns only provider-neutral `PlanGraph`/`PlanNode`
contracts, retry lineage, Tool admission and replan deltas. It still has no
resource lock, route planner, provider branch, or execution path. Those remain
outside the module to avoid duplicating PAOS owners or leaking embodiment policy
into the core. `ResourceRequirement` and planning `ResourceClaim` are symbolic;
the concrete arm is selected from adapter/readiness evidence.

### Controller capability and SDK boundary

`ArmCapability` may expose an adapter-owned `controller_capabilities_ref`, but
the detailed document remains outside PAOS core. It must identify the robot,
arm, controller version, runtime kind, limit units, provenance source, and
enforcement semantics (`controller_hard`, `planner_only`, or
`measured_diagnostic`). A diagnostic threshold is probe evidence only; it is
not a hardware limit and cannot be promoted by Agent or Experience. A hard
bound requires independent controller qualification before Action admission
can consider it executable.

The RoboTwin20 Franka simulation uses SAPIEN URDF articulation with CuRobo or
MPlib planning; it does not import the Franka SDK. Speed values are
provider-owned artifacts, not a universal PAOS number. A future hardware
adapter may use libfranka/frankx or another controller while reusing the same
capability snapshot and route contracts; see
`REAL_SPEED_LIMITS_ARCHITECTURE.md` for the binding and qualification rules.

The evidence boundary is reproducible from
`/home/yanxu/robotwin20-runtime/RoboTwin/scripts/requirements.txt` and the
Franka asset files; the upstream
[libfranka Robot API](https://raw.githubusercontent.com/frankaemika/libfranka/main/include/franka/robot.h)
is the reference for future hardware-controller rate limiting, not for the
current SAPIEN simulation.

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
  tests/test_planning_module.py \
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

The planning-module suite additionally covers graph digest/cycle detection,
ready-set derivation, dynamic admission (evidence, scene, capability and
resource failures), unknown/stale/cancelled settlement, transitive replan
invalidation, decision traces, policy candidates, and the `PlanRevision`/
`ToolExecutionRecord` binding fields. A passing suite still does not authorize
Gateway or robot motion.

### Current planner integration status

`AgentTaskCoordinator.create_task()` and `begin_revision()` accept a concrete
`PlanGraph` only together with an immutable `artifact://` graph reference;
their revisions persist graph/planner/policy digests. The coordinator also
provides `begin_revision_from_delta()` as the sole adapter from a pure
`ReplanDelta` to a new PAOS revision. Query, Action, and Session calls can carry
the complete `PlanningExecutionBinding`, which is persisted on the execution
record and projected as a redacted trace reference for Experience. Supplying
only part of the binding is rejected; legacy calls without planning metadata
remain supported.

Live Gateway ToolSpecs now expose an explicit, versioned `planning` extension
that is projected into the immutable `ToolSpecPolicy` carried by a Skill
binding. Missing planning metadata is not inferred, so legacy ToolSpecs remain
executable but cannot be selected by `agent_composed` admission. AgentLoop
dispatch is provided by `AgentComposedDispatch` plus the
`forge_plan_activate`/`forge_plan_ready` read-only tools. Activation requires
an injected trusted `AdmissionContext` provider; the Agent cannot submit
evidence, settlements, scene revisions, or conditions. The registry guard
checks task-bound Query/Action/Session creation calls before existing Forge
wrappers execute. Experience policy candidates are persisted with independent
replay receipts and explicit human-review/promotion transitions. These bridges
do not move lifecycle or execution ownership into `PhyAgentOS.planning`.
