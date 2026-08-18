# Forge Integration Contract

> PhyAgentOS 0.1.4.post4 · Forge Gateway 1.0.0 · API `paos-forge-gateway-mvp-plus.v1` · [中文](README_zh.md)

This document is the technical contract for the only robot-execution path supported by PhyAgentOS. Gateway, Forge Runtime, Dora dataflows, policies, and hardware integrations remain external and are not modified by PAOS.

`move-arm-by-ee` uses the parallel Gateway Tool API execution plane and an
explicitly managed local Dora dataflow; it does not reuse the high-level
`ForgeSessionOrchestrator`. See
[move-arm-by-ee Skill Runtime](move-arm-by-ee-skill-runtime.md).

For the as-built Skill/Tool/Endpoint/ToolCall/ToolSpec relationships, runtime
boundaries, and the planned two-supply-chain download model, see
[PAOS Skill Runtime and Forge Tool Architecture](skill-runtime-tool-architecture.md).

The Chinese
[PAOS Skill Runtime collaborative development guide](skill-runtime-development-guide.md)
documents the source/install layouts, nine-node topology, canonical repository
boundaries, and local development and acceptance workflow.

The initial machine-readable Skill/Runtime package index and its publication,
archive, lock, installation, and security contract are documented in
[PAOS Forge Package Index (Chinese)](paos-forge-packages_zh.md). See the
[YAML index](paos-forge-packages.yaml) and
[JSON Schema](paos-forge-packages.schema.json) for validation inputs. The index
is a publication contract; the current PAOS installer does not consume it.

## 1. Design boundary

```text
Agent goal + criteria
        │
        ▼
ForgeTaskRequest
        │
        ▼
ForgeSessionOrchestrator ───── persistence / restart / recovery
        │
        ▼
ForgeAdapter ── HTTP/WS ── Forge Gateway ── Forge Runtime / Dora
        │
        ├── immutable ExecutionRecord
        └── EvidenceBundle
                   │
                   ▼
             ForgeTaskVerifier
                   │
                   ▼
          VerificationVerdict
                   │
             optional RecoveryRequest
```

The adapter never decides task success. The verifier never issues a robot command. Planner is the only component that converts a recovery request into a newly planned action.

## 2. Supported topology

- One PAOS process configures one Gateway endpoint.
- Gateway advertises serialized actions, and one root lineage occupies the PAOS execution slot until verification/recovery is terminal.
- One PAOS/Forge session represents one high-level Gateway action.
- Longer tasks are decomposed by Planner across multiple actions or recovery children.
- Gateway 1.0.0 evidence association is `best_effort` only.
- Legacy Runtime/Target/SkillRuntime/Watchdog/SessionRunner/file-queue compatibility is absent by design.

## 3. Startup contract

`ForgeSessionOrchestrator.start()` calls `GET /agent/runtime/capabilities`. Startup fails unless the decoded `data` contains:

```json
{
  "api_version": "paos-forge-gateway-mvp-plus.v1",
  "supports": {
    "sessions": true,
    "command_id": true,
    "runtime_context": true,
    "serial_actions_only": true
  },
  "actions": {}
}
```

`actions` maps action type to a capability object. PAOS uses generic fields such as:

```json
{
  "description": "Human-readable capability",
  "required_parameters": [],
  "input_mapping": {},
  "policy_id": "stable-policy-identity",
  "command": "stable-command-identity",
  "result_semantics": "command_completed",
  "completion": {}
}
```

The capability summary is injected into Agent context. Every submitted `action_type` must exist in the cached map. `result_semantics` and `completion` are copied into the Execution Record; they do not select a verifier implementation.

## 4. Public contracts

### 4.1 `ForgeTaskRequest`

```text
version = forge_task_request_v1
task_description
action_type
inputs
verification: TaskVerificationContract
execution_timeout_s
source = paos-agent
```

Task and action text are non-empty. Inputs are finite JSON. Session and command IDs are deliberately absent.

### 4.2 `TaskVerificationContract`

```text
version = task_verification_contract_v1
mode = off | audit | enforce | recovery
goal
success_criteria[]
constraints[]
evidence_policy {
  profile
  required_kinds[]
  required_sources[]
  minimum_association = best_effort | authoritative
}
```

Non-`off` requires a goal and at least one criterion. Gateway 1.0.0 cannot satisfy `authoritative`; such a request fails before dispatch.

### 4.3 `ExecutionRecord`

`paos_execution_record_v1` is frozen and records normalized Gateway facts: session/command/API/instance/action/policy identity, status, generic result semantics/completion, timeline, outputs, and execution error. No verifier may replace it.

### 4.4 `EvidenceBundle`

`forge_evidence_bundle_v1` records session/command identity, capture window, artifacts, and quality. Every artifact has a unique ID, phase, kind, source, sequence, timestamps, media type, size, SHA-256, safe URI, and retention tombstone fields.

### 4.5 `VerificationVerdict`

`verification_verdict_v1` uses:

```text
verdict = success | failure | replan_required | inconclusive
criteria[] = criterion + satisfied|unsatisfied|unknown + evidence_refs
evidence_refs[]
reason
lesson
recovery_context? = unmet_criteria + preserved_constraints + guidance
```

The output covers every input criterion exactly once and cites only artifact IDs from the resolved Evidence Bundle.

### 4.6 `RecoveryRequest`

`recovery_request_v1` is non-executable. It carries parent ID, unmet criteria, preserved constraints, action-independent guidance, evidence references, and deadline.

## 5. Identity and mutation order

PAOS creates path-safe randomized identities before persistence:

```text
session_id = forge_<16 hex>
command_id = command_<16 hex>
root_session_id = session_id for the root
```

Fresh-action order:

1. Store `ForgeSessionRecord(status=accepted)` in a transaction.
2. Start the observation collector for non-`off` tasks.
3. Persist before entities and snapshot manifest.
4. Persist `dispatch_attempted_at` and the `dispatching` event.
5. POST `/agent/sessions` exactly once.
6. Validate response identity.
7. Poll only the requested session.

The dispatch-intent boundary deliberately prefers “do not repeat an unknown physical action” over automatic at-least-once delivery.

## 6. Gateway Agent API

| Method | Path | Contract |
|:-------|:-----|:---------|
| GET | `/agent/runtime/capabilities` | Version, supports, actions, instance identity |
| GET | `/agent/runtime/status` | Live status for `forge_get_context` |
| GET | `/agent/runtime/context` | Readiness/context and optional source discovery |
| POST | `/agent/runtime/reset` | Explicit reset when PAOS has no active lineage |
| POST | `/agent/sessions` | Create a session with PAOS IDs, action, instruction, source, inputs |
| GET | `/agent/sessions/{session_id}` | Only Gateway execution-terminal source |
| POST | `/agent/sessions/{session_id}/cancel` | Best-effort cancellation with reason |

The client accepts a top-level object or an object under `data`. HTTP errors, non-object JSON, and `ok=false` fail the operation.

## 7. Response correlation

Every create/get response must satisfy:

```text
session.session_id == requested session_id
command.command_id == requested command_id
command.session_id == requested session_id
command.request_id == requested command_id
session.action_type == requested action_type
command.action_type == requested action type
command.policy_id == capability.policy_id (when declared)
command.command == capability.command (when declared)
```

Terminal acceptance additionally requires:

```text
session.status == command.status
status in succeeded | failed | cancelled
```

PAOS does not infer terminal state from command output, policy semantics, image stability, robot stability, elapsed fixed delay, or WebSocket messages.

## 8. Observation contract

### 8.1 Images

Gateway `/ws/images` emits:

```json
{
  "type": "image",
  "id": "front",
  "seq": 42,
  "timestamp": 1785744000.123,
  "content_type": "image/jpeg",
  "data": "<base64>"
}
```

PAOS validates source, non-negative sequence, finite optional timestamp, permitted image media type, Base64, decoded size, and magic bytes. It stores the Gateway timestamp as `captured_at` and local arrival as `received_at`.

### 8.2 State

Gateway `/ws/state` emits JSON objects. PAOS enforces the entity-size limit. Because the v1 contract has no uniform source timestamp, state artifacts use `captured_at=null` and retain only local `received_at`.

### 8.3 Freshness

For every required image source:

```text
before received before session POST
after.sequence > before.sequence
after.received_at >= terminal_observed_at
```

State required by the task must also be received after terminal observation for the after snapshot.

The collector retains the newest valid frame per source, ignores lower/duplicate sequences, reconnects after failure, and keeps recent errors bounded.

## 9. Evidence writing and resolution

Artifact files are atomically written below:

```text
<workspace>/artifacts/forge/<session_id>/
├── execution_record.json
├── before_snapshot.json
├── after_snapshot.json
├── evidence_bundle.json
├── verification_result.json
└── evidence/
```

Writers reject path escape and source-name collisions. Snapshot reads and Verification Request building revalidate path, entity presence, byte size, SHA-256, image media type, Bundle identity, capture-window ordering, completeness, required kinds/sources, and minimum association.

The Bundle quality block distinguishes:

- `complete`;
- `association_quality`;
- `capture_authority=paos_forge_adapter`;
- missing requirements;
- stale artifacts;
- collection/validation errors.

Evidence problems are data, not execution-terminal inference.

## 10. Lifecycle

```text
accepted → capturing_before → dispatching → running → finalizing
         ├─ off ───────────────────────────→ succeeded|failed|timed_out|cancelled
         └─ non-off → awaiting_verification → verifying
                                                ├→ succeeded|failed
                                                └→ awaiting_replan → replanned|failed
```

`replanned`, `succeeded`, `failed`, `timed_out`, and `cancelled` are PAOS terminal states. Parent `replanned` and child `accepted` commit atomically.

## 11. Verification semantics

| Mode | Execution/evidence behavior | Finalization |
|:-----|:----------------------------|:-------------|
| `off` | No verification bundle or verifier call | Map execution status |
| `audit` | Capture and verify when possible; errors recorded | Preserve execution-derived state; never recover |
| `enforce` | Complete evidence and valid verifier required | `success` succeeds; everything else fails closed |
| `recovery` | Same strict verification | Only valid `replan_required` enters recovery |

The verifier prompt contains only goal, criteria, constraints, immutable execution, evidence, lineage history, lessons, and valid evidence references. It must never branch on action type or emit an executable action.

## 12. Verification Service

PAOS starts a child service with a serializable provider specification and bounded readiness check:

```text
GET  /healthz
POST /v1/verify-task
X-PAOS-Admin-Token: <per-process token>
```

Model calls are bounded by timeout and per-process budget. Output is normalized and then validated again for model shape, verdict consistency, exact criteria, and known evidence references.

## 13. Recovery semantics

For a valid recovery verdict, Orchestrator:

1. Collects unmet/unknown criteria.
2. Preserves original plus verifier-provided constraints.
3. Deduplicates evidence references.
4. Creates a deadline-bounded Recovery Request.
5. Sends a system message to the original Agent session.
6. Waits for normal Planner to call `create_replanned_forge_session`.

Child creation requires an awaiting parent, live deadline, and remaining budget. Child inherits verification contract and routing but receives a new action description, action type, inputs, session ID, and command ID. Repeated creation for the same parent returns the existing child.

## 14. Restart rules

| Persisted state | Resume rule |
|:----------------|:------------|
| No dispatch attempt | Continue normal action path |
| Dispatch attempt exists | GET original session only; never POST |
| Matching Gateway session | Continue poll/finalize/verify |
| Gateway 404 | Fail `FORGE_EXECUTION_STATE_LOST` |
| Persisted Execution Record exists | Reuse only if identity matches |
| `verifying` | Append abandoned attempt and return to awaiting verification |
| `awaiting_replan` | Redeliver recovery context; atomic child creation deduplicates |

Graceful PAOS shutdown requests cancellation for every active Gateway session and stores the result.

## 15. Evidence retention and review

| Policy | Deletion rule |
|:-------|:--------------|
| `all` | Retain all entities |
| `failed` | Delete entities when final PAOS state is `succeeded` |
| `none` | Delete entities after verification |

Deletion leaves a tombstone in the Bundle: URI, source, time, sequence, size, digest, `retained=false`, and `deleted_at`. Execution Record remains intact.

`verify_forge_session` is an explicit review of a terminal session. It requires retained evidence, appends an attempt, and may update the latest verification view. It never changes task terminal state or the Execution Record.

## 16. Failure behavior

| Failure | Required behavior |
|:--------|:------------------|
| Unsupported API/supports | Refuse startup |
| Unsupported action | Refuse before persistence/dispatch |
| Authoritative evidence requested | Refuse before dispatch |
| Missing before evidence in audit | Dispatch may continue; record incomplete bundle/error |
| Missing before evidence in enforce/recovery | Fail before POST |
| Execution timeout | Request cancel; retain last response/evidence/cancel response |
| Missing/invalid evidence at verification | Audit records; enforce/recovery fail closed |
| Invalid verdict/service failure | Audit records; enforce/recovery fail closed |
| Replan budget/deadline exhausted | Fail parent and write lesson |
| Gateway session lost after dispatch | Fail without repeating action |

## 17. Conformance tests

A compatible integration covers:

- capability version/support/action validation;
- create/get/cancel/reset response envelopes;
- session/command/request/action/policy/command identity;
- all supported Gateway terminal states and timeout;
- multiple sources, reconnect, ordering, duplicates, stale frames, invalid Base64/media/size;
- before-before-POST and after-after-terminal boundaries;
- all verification modes, invalid output, service timeout, retention, review;
- Store concurrency, legal transitions, one active lineage, atomic replan;
- restart before/after dispatch, lost session, late evidence, interrupted verification;
- Agent tool exposure only when Forge is enabled and correct system-event routing.

Optional black-box tests connect through `FORGE_GATEWAY_URL`; they do not modify Gateway source or configuration.

## Related documentation

- [Framework Introduction](../en/01-framework-introduction.md)
- [User Manual](../en/02-user-manual.md)
- [Developer Manual](../en/03-developer-manual.md)
- [Configuration Reference](../en/04-forge-configuration-reference.md)
- [Integration Development Guide](../user_development_guide/README_en.md)
- [Communication Architecture](../user_development_guide/COMMUNICATION_en.md)
