# Scene Observe Forge Skill

This directory is an independently installable Forge Skill source bundle for the
provider-neutral `scene.observe`, `scene.understand`, `grasp.propose`, and
`manipulation.prepare` Queries. It is an example integration and is not part
of the `PhyAgentOS` Python distribution.

The implementation deliberately has no simulator, robot SDK, camera driver, or
actuator dependency. `FakeGatewayTransport` is used for contract and workflow tests;
deployment adapters can replace the observation, understanding, proposal, and
preparation providers without changing the ToolSpec or PAOS Agent route.

The fixed read-only workflow is:

```text
scene.observe -> scene.understand -> grasp.propose -> manipulation.prepare
```

`manipulation.prepare` evaluates workspace, kinematic, and collision readiness
for proposed candidates and returns evidence-bound prepared candidates. It does
not execute commands, create an Action or Session, or authorize motion;
`motion_authorized` is always `false`. Results remain bound to the observation,
scene revision, frame, calibration, and candidate-set references, so a later
execution layer must perform its own admission checks.

## Validation

```bash
PYTHONPATH=src:/home/yanxu/PhyAgentOS-forge \
  python -m pytest -q tests
```

The tests use PAOS's real `ForgeToolClient` with an `httpx.MockTransport` and therefore
exercise discovery, readiness/context, ToolSpec binding, and Query invocation through
the documented Gateway routes. No test enables or performs motion.
