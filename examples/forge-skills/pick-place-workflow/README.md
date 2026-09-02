# Pick and Place Workflow Forge Skill

This directory is an independently installable Forge Skill source bundle for the
provider-neutral `scene.observe`, `scene.understand`, `grasp.propose`,
`manipulation.prepare`, `object.acquire`, and `object.place` Query/Action contracts. It is an
example integration and is not part
of the `PhyAgentOS` Python distribution.

The Skill is intentionally named `pick-place-workflow` because it describes the
complete six-tool workflow. It is not a `scene-observe` Skill and does not claim
that observation alone includes grasping or manipulation.

The implementation deliberately has no simulator, robot SDK, camera driver, or
actuator dependency. `FakeGatewayTransport` is used for contract and workflow tests;
deployment adapters can replace the observation, understanding, proposal, and
preparation providers without changing the ToolSpec or PAOS Agent route.
It also does not include YOLO/Ultralytics or any other detector; a provider result
from `grasp.propose` is a contract-shaped proposal fixture, not object detection or
successful grasp execution.

The fixed capability workflow is:

```text
scene.observe -> scene.understand -> grasp.propose -> manipulation.prepare -> object.acquire -> object.place
```

`manipulation.prepare` evaluates workspace, kinematic, and collision readiness
for proposed candidates and returns evidence-bound prepared candidates. It does
not execute commands, create an Action or Session, or authorize motion;
`motion_authorized` is always `false`. Results remain bound to the observation,
scene revision, frame, calibration, and candidate-set references, so a later
execution layer must perform its own admission checks.

`object.acquire` is the first physical-effect boundary. It consumes a fresh,
calibration-bound preparation reference through the standard Action admission
route and is reconciled through `/invocations`; approach, contact, close, lift,
and hold remain Gateway-internal phases. A terminal result contains only the
redacted `capability_outcome_summary_v1`, not provider or simulator payloads.

`object.place` is a separate bounded physical-effect Action. It consumes a
terminal successful acquire invocation, the same immutable scene/candidate
bindings, and an opaque `destination_ref`; transport, descent, release, and
retreat remain Gateway-internal. Its terminal summary adds typed
`post_release_evidence` for downstream verification, without exposing
coordinates, simulator parameters, or controller details.

Long-horizon orchestration remains an AgentTask concern. The bundle exposes a
replayable reducer for the fixed six-step pick-and-place sequence; it stores only
step status and opaque references, delegates all execution to the existing
ForgeToolClient/AgentTask path, and uses append-only revisions for recovery. It
does not add a Gateway route, Session, cross-Tool lease, or motion authorization.

## Validation

```bash
PYTHONPATH=src:/home/yanxu/PhyAgentOS-forge \
  python -m pytest -q tests
```

The tests use PAOS's real `ForgeToolClient` with an `httpx.MockTransport` and therefore
exercise discovery, readiness/context, ToolSpec binding, and Query invocation through
the documented Gateway routes. No test enables or performs motion.
