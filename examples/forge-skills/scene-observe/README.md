# Scene Observe Forge Skill

This directory is an independently installable Forge Skill source bundle for the
provider-neutral `scene.observe`, `scene.understand`, and `grasp.propose` Queries. It is an example integration and is not part
of the `PhyAgentOS` Python distribution.

The implementation deliberately has no simulator, robot SDK, camera driver, or
actuator dependency. `FakeGatewayTransport` is used for contract and workflow tests;
deployment adapters can replace its `ObservationProvider` without changing the
ToolSpec or PAOS Agent route.

## Validation

```bash
PYTHONPATH=src:/home/yanxu/PhyAgentOS-forge \
  python -m pytest -q tests
```

The tests use PAOS's real `ForgeToolClient` with an `httpx.MockTransport` and therefore
exercise discovery, readiness/context, ToolSpec binding, and Query invocation through
the documented Gateway routes. No test enables or performs motion.
