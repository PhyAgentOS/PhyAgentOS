# PhyAgentOS Operations Manual

> Version: 0.1.4.post4 · [中文](README.md)

This manual is for deployment, demonstrations, and operations. It focuses on running the Forge execution–evidence–verification–recovery loop reliably. See the [User Manual](../en/02-user-manual.md) for installation and task authoring, and the [Configuration Reference](../en/04-forge-configuration-reference.md) for exact parameters.

## 1. Runtime model

```text
User/Channel → AgentLoop → Forge tools → ForgeSessionOrchestrator
                                            │
                       ┌────────────────────┼───────────────────┐
                       ▼                    ▼                   ▼
                 Forge Gateway       SQLite event log     Verifier process
                       │                    │                   │
                       └──────────── execution + evidence ──────┘
```

Use `paos agent` for interactive or one-message work and `paos gateway` for long-running channels, Cron, and Heartbeat. Both use the same Orchestrator semantics when `forge.enabled=true`.

## 2. Pre-deployment checks

### PAOS host

- Python 3.11/3.12 environment and dependencies are available.
- `~/.PhyAgentOS/config.json` permissions are controlled and credentials are not in Git.
- Workspace is writable and sized for evidence.
- `agents.verification.servicePort` is free.
- Host time is reliable for cross-component audit.
- A long-running process supervisor and log collection are available.

### Forge Gateway

- `baseUrl` is reachable from the PAOS host.
- `/agent/runtime/capabilities` reports exact API version and required supports.
- `/agent/runtime/status` and `/agent/runtime/context` work.
- Planned actions appear in capabilities.
- `/ws/images` publishes required sources with increasing sequences.
- `/ws/state` is available when robot state is required.
- Gateway, Forge Runtime, Dora, and robot/simulator safety checks are complete according to their own documentation.

### Verification

- `serviceEnabled` is true for non-`off` work.
- Verifier model supports images and strict JSON.
- `evidenceRetention` satisfies privacy, audit, and disk policy.
- Replan budget and deadline fit site-response requirements.

## 3. Startup and health

Start Forge first, then PAOS:

```bash
paos status
paos agent --config /path/to/config.json --workspace /path/to/workspace
```

Long-running service:

```bash
paos gateway --config /path/to/config.json --workspace /path/to/workspace --verbose
```

After startup ask the Agent for a read-only check:

```text
Call forge_get_context. Report Gateway API version, supports, actions, status, readiness, and image sources. Do not reset or execute an action.
```

Orchestrator accepts work only after capability validation. Verification Service startup failure is cached as an explicit error; non-`off` work is refused before execution when the verifier is unavailable.

## 4. Task monitoring

Record the returned `session_id` and `command_id`. Use `forge_get_session` through the Agent and inspect:

| Field | Operational meaning |
|:------|:--------------------|
| `status` | Current PAOS state or final task result |
| `dispatch_attempted_at` | Whether the “never automatically resend” boundary was crossed |
| `gateway_last_response` | Last known Gateway session/command response |
| `execution.status` | Gateway execution fact |
| `verification.status/verdict` | Verification phase and semantic decision |
| `recovery_request.deadline` | Latest time for Planner child creation |
| `error_code/error_message` | Failure layer and detail |

Do not rely on Gateway `succeeded` alone. In `enforce` or `recovery`, task success requires PAOS `status=succeeded` and a `success` verdict.

## 5. Cancellation and reset

Request cancellation through the Agent:

```text
Use forge_cancel_session to cancel <session_id> and provide an operational reason.
```

After dispatch, PAOS requests Gateway cancellation and stores the response. Cancellation is not a hardware emergency stop; retain independent E-stop, operator override, and safe-shutdown procedures.

Reset only when no active lineage exists:

```text
First query the session and confirm it is terminal, then call forge_reset. Never reset during execution.
```

Orchestrator rejects reset while work is active.

## 6. Graceful shutdown

1. Stop accepting new work.
2. Query the non-terminal lineage.
3. Wait for completion, or explicitly cancel and verify physical state.
4. Send SIGINT/SIGTERM to PAOS.
5. PAOS again attempts Gateway cancellation for active work and stores the response.
6. Stop downstream services according to Forge and robot documentation.

Do not kill, restart, and repeat the user's instruction without first checking SQLite and the Gateway session for dispatch intent.

## 7. Crash-restart handling

PAOS loads non-terminal records at startup:

| Crash point | Automatic behavior | Operator action |
|:------------|:-------------------|:----------------|
| Before dispatch | Continue capture or dispatch | Observe |
| After dispatch intent | GET original session; never POST | Confirm Gateway identity |
| Gateway returns 404 | `FORGE_EXECUTION_STATE_LOST` | Inspect physical state and Gateway logs; never copy old command ID |
| Finalizing | Attempt after capture and contract writing | Inspect source and sequence |
| Verifying | Mark old attempt abandoned and retry | Inspect provider/service |
| Awaiting replan | May redeliver same recovery event | Check Planner child and deadline |

If physical state is unknown, stop automated work and require operator confirmation instead of probing with another task.

## 8. Artifacts and disk

```text
<workspace>/.paos/forge/orchestrator.sqlite3
<workspace>/.paos/forge/orchestrator.sqlite3-wal
<workspace>/.paos/forge/orchestrator.sqlite3-shm
<workspace>/artifacts/forge/<session_id>/
```

Backup guidance:

- Safest: stop PAOS, then back up SQLite and the complete `artifacts/forge/` tree.
- For live copies, use a SQLite-aware backup; never copy only the main database while ignoring WAL.
- Database and artifacts should represent the same point in time.
- Never edit `record_json` or event rows manually.
- Monitor Bundle, Execution, and event-log growth even with retention configured.

`maxArtifactBytes` is a per-entity limit, not a per-session or workspace quota.

## 9. Failure layers

### A. Startup contract

`FORGE_GATEWAY_API_UNSUPPORTED` or `FORGE_GATEWAY_CAPABILITY_MISSING`: stop accepting work and correct Gateway version/supports without downgrade.

### B. Execution identity

Identity mismatch or `FORGE_EXECUTION_STATE_LOST`: treat as a duplicate-action risk and require inspection before replanning.

### C. Evidence

`FORGE_EVIDENCE_CONFIGURATION_REQUIRED` or `FORGE_EVIDENCE_UNAVAILABLE`: inspect source IDs, WebSockets, sequences, media types, entity limits, and capture timeouts.

### D. Verification

`VERIFICATION_EVIDENCE_UNAVAILABLE`, `VERIFICATION_INVALID_VERDICT`, or `VERIFICATION_SERVICE_UNAVAILABLE`: inspect artifact integrity, retention, model, provider, port, and timeout. Do not switch a semantically enforced task to `off` merely to hide the failure.

### E. Recovery

`VERIFICATION_REPLAN_LIMIT_REACHED` or `VERIFICATION_REPLAN_TIMEOUT`: automatic continuation is over. Review lessons, unmet criteria, and physical state before the user creates a new task.

## 10. Operational acceptance checklist

- [ ] Gateway API/version/supports validation passes.
- [ ] Action capabilities and required inputs are visible.
- [ ] Required before sources arrive before POST.
- [ ] Session/command/request/action identities all match.
- [ ] Terminal state comes from session GET, not fixed wait or stability inference.
- [ ] After source sequence is higher than before and received after terminal observation.
- [ ] Execution Record and Evidence Bundle are durable.
- [ ] Non-`off` work has a goal and criteria and receives a verdict or explicit failure.
- [ ] User-facing outcome separates execution status from verification verdict.
- [ ] Recovery child has fresh IDs and traceable parent/root lineage.

## Next reading

- [User Manual](../en/02-user-manual.md)
- [Configuration Reference](../en/04-forge-configuration-reference.md)
- [Communication Architecture](../user_development_guide/COMMUNICATION_en.md)
- [Forge Integration Contract](../forge/README.md)
