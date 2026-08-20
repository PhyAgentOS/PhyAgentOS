# PhyAgentOS Developer Manual

> Documentation version: 0.1.4.post4. This manual is for PAOS, Forge Gateway, evidence, verifier, and Agent-tool developers.

## 1. Development principles

Changes touching embodied execution must preserve these invariants:

1. Forge Gateway is the only robot execution entry point.
2. Gateway terminal state is execution fact; task success follows verification policy.
3. Only PAOS generates session and command IDs; callers cannot provide or reuse them.
4. A session with recorded dispatch intent is never automatically POSTed again.
5. Gateway session, command, request, action, command identity, and policy identity all match.
6. A written Execution Record cannot be overwritten by verification, review, or retention.
7. Evidence preserves real source, sequence, source time when present, and PAOS receive time; it never fabricates authoritative association.
8. Verifier prompts, public verdicts, and Recovery Requests are independent of `action_type`.
9. Parent `replanned` and child creation occur in one SQLite transaction.
10. Execution, evidence, verification, recovery, and persistence changes include failure and restart tests.

## 2. Module map

| Area | Path | Responsibility |
|:-----|:-----|:---------------|
| Agent integration | `PhyAgentOS/agent/loop.py` | Register tools, inject capability summary, handle system events |
| Agent tools | `PhyAgentOS/agent/tools/forge.py` | JSON schemas, call context, Orchestrator facade |
| Public contracts | `PhyAgentOS/verification/contracts.py` | Task, Session, Execution, Evidence, Verdict, Recovery, state machine |
| Verification request | `PhyAgentOS/verification/request_builder.py` | Resolve bundle, validate digest/window/requirements, build multimodal request |
| Verification engine | `PhyAgentOS/verification/engine.py` | Stateless model call and timeout |
| Verification service | `PhyAgentOS/verification/service.py` | Child process, readiness, authentication, strict JSON output |
| Verifier facade | `PhyAgentOS/agent/session_verifier.py` | Budgets, attempts, retention, lessons, review |
| Gateway client | `PhyAgentOS/forge/client.py` | `httpx.AsyncClient` wrapper for Agent API |
| Observation | `PhyAgentOS/forge/observation.py` | Async WebSockets, bounded per-source latest frames, validation |
| Evidence writer | `PhyAgentOS/forge/evidence.py` | Safe paths, atomic writes, SHA-256, snapshots, bundles |
| Adapter | `PhyAgentOS/forge/adapter.py` | One-action execution, identity, polling, timeout, cancellation, mapping |
| Store | `PhyAgentOS/forge/store.py` | SQLite WAL, transactions, state, events, atomic replan |
| Orchestrator | `PhyAgentOS/forge/orchestrator.py` | Async tasks, modes, restart, recovery, notification |
| Configuration | `PhyAgentOS/config/schema.py` | Forge, evidence, verification, and embodiment schemas |

## 3. Public models

### 3.1 `ForgeTaskRequest`

```python
ForgeTaskRequest(
    task_description="Place the red object in the tray",
    action_type="<gateway-advertised-action>",
    inputs={...},
    verification=TaskVerificationContract(...),
    execution_timeout_s=300.0,
)
```

`inputs` must contain finite JSON values. NaN, Infinity, non-serializable objects, and blank `task_description` or `action_type` values are rejected.

### 3.2 `TaskVerificationContract`

When `mode != off`, goal and at least one criterion are required. Criteria and constraints cannot contain blank items. Evidence policy requires `rgb_image` by default and may override sources per task. Empty task sources fall back to Forge target configuration or readiness discovery.

### 3.3 `ExecutionRecord`

This model is `frozen=True` and contains:

- PAOS/Gateway session and command IDs;
- Gateway API and instance identity;
- action type and policy ID;
- normalized execution status;
- generic capability `result_semantics` and `completion` declarations;
- Gateway timeline, outputs, and error.

Never put a task verdict into this model or change Gateway `succeeded` to `failed` because a verifier rejected the semantic result.

### 3.4 `EvidenceBundle`

Each artifact has phase, kind, source ID, sequence, capture/receive time, media type, byte size, SHA-256, a safe workspace-relative URI, and retention state. `EvidenceQuality` separately records completeness, association, missing requirements, stale artifacts, and errors.

### 3.5 `VerificationVerdict`

The verifier returns exactly one `CriterionVerdict` for each input success criterion and copies the criterion verbatim. `success` requires every criterion to be `satisfied`. `failure` and `replan_required` require at least one unmet or unknown item. `replan_required` also requires action-independent `recovery_context`.

## 4. State machine and transactions

`ALLOWED_FORGE_TRANSITIONS` defines every legal transition. Every Store update loads the model, applies a mutation, validates the transition, updates time, writes JSON, appends an event, and commits.

SQLite tables:

```text
forge_sessions
  session_id PRIMARY KEY
  command_id UNIQUE
  root_session_id
  parent_session_id UNIQUE
  status
  record_json
  created_at / updated_at

forge_events
  event_id PRIMARY KEY
  session_id FOREIGN KEY
  event_type
  created_at
  payload_json
```

Task creation and replan use `BEGIN IMMEDIATE`, keeping one non-terminal lineage even when multiple Store instances submit concurrently.

## 5. Gateway startup contract

`ForgeAdapter.validate_capabilities()` requires:

```json
{
  "api_version": "paos-forge-gateway-mvp-plus.v1",
  "supports": {
    "sessions": true,
    "command_id": true,
    "runtime_context": true,
    "serial_actions_only": true
  },
  "actions": {
    "<action_type>": {
      "policy_id": "...",
      "command": "...",
      "result_semantics": "command_completed",
      "completion": {},
      "required_parameters": [],
      "input_mapping": {}
    }
  }
}
```

Action metadata informs Planner selection and the Execution Record. It never chooses a verifier branch.

## 6. Adapter execution protocol

The ordering for a fresh task is mandatory:

1. Validate action capability.
2. Start image/state collectors for non-`off` work.
3. Await required sources and atomically persist the before snapshot.
4. Let Orchestrator persist `dispatching` and dispatch intent.
5. POST `/agent/sessions`.
6. Validate session, command, and action identity in the create response.
7. Poll `/agent/sessions/{session_id}`.
8. Accept only `succeeded | failed | cancelled`; request cancellation on timeout.
9. After observing terminal state, await higher image sequences and write the after snapshot.
10. Write immutable Execution Record and Evidence Bundle.

Gateway payload:

```json
{
  "session_id": "forge_<generated>",
  "command_id": "command_<generated>",
  "action_type": "...",
  "instruction": "...",
  "source": "paos-agent",
  "inputs": {}
}
```

Terminal acceptance requires all of:

```text
session.session_id == requested session_id
command.command_id == requested command_id
command.session_id == requested session_id
command.request_id == requested command_id
session.action_type == requested action_type
command.action_type/policy_id/command == advertised capability identity
session.status == command.status in succeeded|failed|cancelled
```

## 7. Observation and evidence

The collector retains only the highest legal sequence for each required image source. Duplicate or out-of-order frames do not replace the latest frame. It reconnects after disconnection and keeps a bounded recent-error list.

Accepted entities are:

- `image/jpeg` / `image/jpg`;
- `image/png`;
- `image/webp`;
- JSON robot state.

Beyond Base64 and decoded size limits, image magic bytes are verified. Artifact filenames include a safe source label, source digest, and sequence to avoid collisions after source sanitization. Every URI is workspace-relative and rejects `..`.

Before model invocation, `VerificationRequestBuilder` revalidates:

- bundle/session/command identity;
- completeness and minimum association;
- capture-window ordering;
- required kinds and sources in both phases;
- retained entity existence, byte size, and SHA-256;
- image media type against bytes;
- unique evidence IDs.

## 8. Verification Service

`ForgeTaskVerifier` starts an independent Python child process. It listens on configured host/port, authenticates with a per-process `X-PAOS-Admin-Token`, and exposes:

```text
GET  /healthz
POST /v1/verify-task
```

The request version is `forge_verification_request_v1`. Startup readiness is bounded; model calls are limited by `timeoutS` and `maxVerifierCallsPerRun`.

The prompt contains only:

- task goal, success criteria, and constraints;
- immutable Execution Record;
- Evidence Bundle and entities;
- root-lineage history;
- LESSONS;
- valid evidence IDs.

Malformed service output is normalized to `inconclusive`, then checked again by public models and the exact-criteria validator. `audit` records the error; `enforce` and `recovery` fail closed.

## 9. Recovery

The verifier may recommend `replan_required` but cannot output action types, policy parameters, or Gateway inputs. Orchestrator creates a `RecoveryRequest` and sends an `InboundMessage(channel="system")` to the original Agent session.

When Planner calls `create_replanned_forge_session`:

- parent is still `awaiting_replan`;
- deadline is not expired;
- replan budget remains;
- child inherits verification contract, root lineage, origin routing, and source;
- Planner supplies new task description, action type, and inputs;
- PAOS generates fresh session and command IDs;
- parent terminal transition and child creation commit atomically;
- duplicate calls return the existing child.

## 10. Extension workflows

### 10.1 Add a Gateway action

Action implementation and registration happen in Forge Gateway/Runtime, not PAOS:

1. Publish stable action identity in Gateway capabilities.
2. Declare `required_parameters`, `input_mapping`, `result_semantics`, and `completion`.
3. Return complete, consistent session/command identities from create and get.
4. Keep terminal states within the supported contract.
5. Add only generic contract/fake-Gateway tests in PAOS—never an action-specific verifier flag.

### 10.2 Add an evidence source

Publish a stable `id`, monotonically increasing `seq`, legal `content_type`, and Base64 data on Gateway `/ws/images`. An optional `timestamp` must be real source time. Reference that source from PAOS target configuration or the task evidence policy.

A new evidence kind must extend public contracts, collection/writing, request resolution, retention, and end-to-end tests together. Do not hide private artifact paths in action manifests.

### 10.3 Add an Agent tool

Only add a tool when the seven generic Forge tools cannot represent the capability. A new tool must not accept caller-supplied session/command IDs, POST directly to Gateway, or bypass Store/Orchestrator.

## 11. Errors and observability

Stable error prefixes support operational triage:

| Category | Examples |
|:---------|:---------|
| Gateway contract | `FORGE_GATEWAY_API_UNSUPPORTED`, `FORGE_GATEWAY_CAPABILITY_MISSING` |
| Action/correlation | `FORGE_ACTION_UNSUPPORTED`, `FORGE_EXECUTION_STATE_LOST` |
| Evidence | `FORGE_EVIDENCE_CONFIGURATION_REQUIRED`, `FORGE_EVIDENCE_UNAVAILABLE`, `VERIFICATION_EVIDENCE_UNAVAILABLE` |
| Verification | `VERIFICATION_INVALID_VERDICT`, `VERIFICATION_CALL_BUDGET_EXHAUSTED`, `VERIFICATION_SERVICE_UNAVAILABLE` |
| Recovery | `VERIFICATION_REPLAN_LIMIT_REACHED`, `VERIFICATION_REPLAN_TIMEOUT` |
| Execution | `GATEWAY_EXECUTION_TIMEOUT`, `GATEWAY_SESSION_FAILED`, `FORGE_SESSION_CANCELLED` |

The SQLite event log is the orchestration audit source. Raw Gateway create/last/cancel responses remain in the session record. Public artifacts provide cross-process readable facts.

## 12. Testing

```bash
python -m pip install -e ".[dev]"
pytest
ruff check PhyAgentOS tests
python -m compileall -q PhyAgentOS tests
```

Tests should cover:

- model versions, required fields, illegal states/verdicts/URIs/digests;
- Store concurrency, one active lineage, transitions, atomic replan;
- Gateway API/support/action/identity/terminal/cancel/reset;
- multiple sources, ordering, duplicates, stale frames, disconnects, invalid media, oversize artifacts;
- all four modes, missing evidence, service errors, retention, and review immutability;
- restart before POST, 404 after intent, late capture, interrupted verification, recovery deduplication;
- tool registration, system-event routing, and Forge-disabled behavior;
- repository guard against the removed execution architecture.

Optional black-box tests connect only through `FORGE_GATEWAY_URL` and never modify Gateway source or configuration.

## Next reading

- [Integration Development Guide](../user_development_guide/README_en.md)
- [Communication Architecture](../user_development_guide/COMMUNICATION_en.md)
- [Forge Integration Contract](../forge/README.md)
- [Configuration Reference](04-forge-configuration-reference.md)
