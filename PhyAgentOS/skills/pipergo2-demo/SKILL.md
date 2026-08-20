---
name: pipergo2-demo
description: Plan and execute a PiperGo2 demo through the configured Forge Gateway.
metadata: {"PhyAgentOS":{"always":false,"available":true},"nanobot":{"emoji":"🧪"}}
---

# PiperGo2 Demo Skill

Use only the Forge Agent tools:

1. Call `forge_get_context` and choose an action advertised by the live Action Manifest.
2. Translate the user's goal into `task_description`, `action_type`, and complete `inputs`.
3. Supply an action-agnostic verification contract with explicit goal, success criteria,
   constraints, and evidence requirements.
4. Call `forge_execute_task` once. Do not invent command IDs or poll in a tight loop.
5. Treat Gateway `succeeded` as an execution fact and wait for the verification outcome.
