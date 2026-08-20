# PhyAgentOS Framework Introduction

> Documentation version: 0.1.4.post4 · implementation baseline: Forge-only source on 2026-08-03. This document calls a behavior current only when source, configuration schemas, and tests support it.

## 1. Positioning

PhyAgentOS is an agent and task-orchestration framework for embodied work. The current release converges all robot execution on Forge Gateway 1.0.0. The Agent understands the user goal, selects a Gateway action, defines success, and handles recovery. Forge performs the action. PAOS supplies the persistent, verifiable, recoverable boundary between them.

The boundary is not designed to implement every robot action inside PAOS. It answers four more stable questions:

1. Which session, command, and action were dispatched?
2. How is the Gateway terminal result preserved as an immutable fact?
3. How are observations around the action turned into validated evidence?
4. How do system-level goals and criteria determine success and return control to the Planner when needed?

## 2. Three kinds of fact

PhyAgentOS does not equate command completion with task completion.

| Layer | Public model | Question answered | Writer |
|:------|:-------------|:------------------|:-------|
| Execution fact | `ExecutionRecord` | What did Gateway accept and how did it terminate? | `ForgeAdapter` |
| Observation evidence | `EvidenceBundle` | What did PAOS observe before and after, and is the evidence complete? | `ForgeEvidenceWriter` |
| Task decision | `VerificationVerdict` | Is each success criterion satisfied? | `ForgeTaskVerifier` |

The verifier may cite an Execution Record but cannot replace it. An explicit review appends another verification attempt without changing the original terminal task state.

## 3. Current architecture

```text
CLI / Channels / Cron / Heartbeat
                │
                ▼
        AgentLoop + Planner
                │ Forge tools
                ▼
      ForgeSessionOrchestrator
        │          │          │
        │          │          └── system event → Agent Planner
        │          └── SQLite sessions + append-only events
        ▼
     ForgeAdapter ───────────────► ForgeTaskVerifier
        │                              │
        │ HTTP: capabilities/session   │ task contract
        │ WS: images/state             │ execution + evidence
        ▼                              ▼
  Forge Gateway 1.0.0             semantic verdict
        │
        ▼
 Forge Runtime / Dora / robot or simulator
```

### 3.1 Agent control plane

AgentLoop owns messages, context, models, tools, and Planner decisions. When Forge is enabled, the Agent receives a capability summary and seven Forge tools. Submission is asynchronous: the tool first returns PAOS-generated session and command IDs; a system event wakes the originating conversation after orchestration completes or requests recovery.

### 3.2 Forge orchestration plane

`ForgeSessionOrchestrator` is the only robot-task orchestrator in PAOS. It:

- validates Gateway API and supports at startup;
- transactionally creates tasks and enforces one active lineage;
- delegates execution and evidence capture to the adapter;
- finalizes, verifies, or requests recovery according to mode;
- resumes from persisted facts without repeating an unknown action;
- routes completion and recovery back to the original Agent session.

### 3.3 Forge execution plane

Forge Gateway, Forge Runtime, Dora dataflows, policies, and hardware controllers remain external to PAOS. PAOS neither modifies their source nor bypasses Gateway to call internal components.

## 4. Public contracts

The public boundary lives in `PhyAgentOS/verification/contracts.py`:

| Model | Version | Purpose |
|:------|:--------|:--------|
| `ForgeTaskRequest` | `forge_task_request_v1` | High-level action, inputs, task description, verification, and timeout |
| `TaskVerificationContract` | `task_verification_contract_v1` | Mode, goal, criteria, constraints, and evidence policy |
| `ForgeSessionRecord` | `forge_session_record_v1` | PAOS state, lineage, Gateway responses, execution, verification, and recovery |
| `ExecutionRecord` | `paos_execution_record_v1` | Immutable normalized Gateway facts |
| `EvidenceBundle` | `forge_evidence_bundle_v1` | Capture window, artifacts, digests, URIs, and quality |
| `VerificationVerdict` | `verification_verdict_v1` | Overall and per-criterion decisions, references, reason, and lesson |
| `RecoveryRequest` | `recovery_request_v1` | Unmet criteria, preserved constraints, evidence references, guidance, and deadline |

These models contain no action-specific field such as `grasp_verify_enabled`. Task criteria express success semantics. Generic Gateway capability fields such as `result_semantics` and `completion` describe execution semantics.

## 5. Lifecycle

```text
accepted
  → capturing_before
  → dispatching
  → running
  → finalizing
  ├─ verification=off ───────────────→ succeeded | failed | timed_out | cancelled
  └─ non-off → awaiting_verification → verifying
                                      ├→ succeeded | failed
                                      └→ awaiting_replan → replanned | failed
```

- `accepted` means PAOS transactionally stored the task and generated identities.
- The before snapshot is durable before POST; entering `dispatching` persists dispatch intent.
- `running` means the Gateway session has not reached a supported terminal state.
- `finalizing` creates the Execution Record and attempts to freeze after evidence.
- `awaiting_verification` and `verifying` operate at the task-semantic layer and do not rewrite execution facts.
- `replanned` is the parent's terminal state; a fresh child is created in the same transaction.

## 6. Evidence model

Gateway 1.0.0 has no authoritative Evidence API. PAOS therefore collects `/ws/images` and `/ws/state` and explicitly marks association as `best_effort`.

Each image source follows these boundaries:

1. A before frame is received and persisted before the session POST.
2. Gateway terminal state comes only from `/agent/sessions/{session_id}`.
3. An after frame is received after PAOS observes that terminal state.
4. Its sequence is strictly higher than the same source's before sequence.

Images pass Base64, media type, magic-byte, size, and SHA-256 validation. When state messages carry no Gateway source timestamp, PAOS records only `received_at`; it never invents a timestamp.

## 7. Verification and recovery

Verification modes represent system policy, not action types:

- `off` finalizes from Gateway execution status.
- `audit` records a verdict or error while preserving the execution-derived state and never recovers.
- `enforce` lets the verdict determine success; missing evidence, malformed output, service errors, and inconclusive results fail closed.
- `recovery` uses the same fail-closed rules, but a valid `replan_required` may enter `awaiting_replan`.

A Recovery Request is not executable. It contains only unmet criteria, preserved constraints, guidance, evidence references, and a deadline. The Planner must choose the action again, rewrite the task description and inputs, and call `create_replanned_forge_session`.

## 8. Persistence and crash recovery

Orchestration state is stored in `<workspace>/.paos/forge/orchestrator.sqlite3` using SQLite WAL and explicit transactions. Entity artifacts live under `<workspace>/artifacts/forge/<session_id>/`.

Recovery rules are deliberate:

- Before POST: work without dispatch intent can continue.
- After dispatch intent: resume performs GET only and never repeats POST.
- Matching Gateway session: polling, after capture, or verification continues.
- Gateway 404: fail as `FORGE_EXECUTION_STATE_LOST`.
- Interrupted `verifying`: record an abandoned attempt and verify again.
- `awaiting_replan`: the same Recovery Request may be delivered again; atomic child creation deduplicates it.

## 9. Knowledge and execution surfaces

The Agent workspace retains:

- `EMBODIED.md` for human-readable robot knowledge;
- `ENVIRONMENT.md` for environment or SceneGraph state;
- `LESSONS.md` for execution, verification, and recovery experience;
- `TASK.md` for multi-step planning state.

These files may enter Agent context but never dispatch execution. The `embodiments` configuration describes knowledge-workspace topology; it does not create additional Gateways or hardware drivers.

## 10. Implemented scope

- One PAOS process supports one Forge Gateway endpoint.
- Gateway must advertise `paos-forge-gateway-mvp-plus.v1` exactly.
- Actions are serialized within a root lineage; unrelated work is refused until verification or recovery terminates.
- One Forge session represents one high-level action.
- Evidence association supports `best_effort` only.
- The legacy Runtime, Target, Policy/SkillRuntime, Watchdog, SessionRunner, perception pipeline, and Markdown execution queue are removed from active code with no compatibility layer or migrator.

## 11. Code map

```text
PhyAgentOS/
├── agent/                 # AgentLoop, tools, verifier client
├── forge/
│   ├── client.py          # Async Gateway HTTP client
│   ├── observation.py     # WebSocket observation collector
│   ├── evidence.py        # Artifact validation and Evidence Bundle
│   ├── adapter.py         # One-action execution lifecycle
│   ├── store.py           # SQLite state and events
│   └── orchestrator.py    # Execution, verification, recovery, notification, restart
├── verification/         # Contracts, request builder, engine, service
├── channels/             # Messaging channels
├── config/               # Configuration models and loader
└── templates/            # Agent knowledge-workspace templates
```

## Next reading

- [User Manual](02-user-manual.md)
- [Developer Manual](03-developer-manual.md)
- [Forge Configuration Reference](04-forge-configuration-reference.md)
- [Forge Integration Contract](../forge/README.md)
- [Documentation Index](../README.md)
