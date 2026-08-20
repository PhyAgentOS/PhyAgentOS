# PhyAgentOS Communication Architecture

> Version: 0.1.4.post4 · [中文](COMMUNICATION.md)

## 1. Five communication boundaries

PhyAgentOS does not mix user messaging, physical execution, and verification on one internal bus:

1. **User-message boundary:** Channel ↔ MessageBus ↔ AgentLoop.
2. **Agent/Forge orchestration boundary:** Agent tools ↔ `ForgeSessionOrchestrator`.
3. **PAOS/Gateway boundary:** async HTTP plus WebSocket.
4. **Verifier boundary:** Orchestrator ↔ independent Verification Service process.
5. **Persistence boundary:** Orchestrator ↔ SQLite; Adapter/Verifier ↔ workspace artifacts.

```text
External Channel
      │ InboundMessage / OutboundMessage
      ▼
  MessageBus ─ AgentLoop ─ Forge tools ─ Orchestrator
                                          │
                ┌─────────────────────────┼────────────────────┐
                ▼                         ▼                    ▼
          HTTP / WebSocket             SQLite          Verification HTTP
                ▼                         ▼                    ▼
          Forge Gateway             Event Store          Child process
                │
                ▼
        Forge Runtime / Dora
```

## 2. User-message boundary

A Channel converts external input into `InboundMessage`. AgentLoop loads context by `session_key`, invokes the model and tools, and emits `OutboundMessage`. CLI one-message mode may call `process_direct`, but the internal Planner and Forge tools remain the same.

A Channel must not:

- call Gateway directly;
- write SQLite or artifacts directly;
- generate or reuse Forge session/command IDs;
- report Gateway `succeeded` directly as task success.

## 3. Agent/Orchestrator boundary

The seven Forge tools are the Agent's only execution interface:

```text
forge_execute_task
forge_get_session
forge_cancel_session
forge_get_context
forge_reset
verify_forge_session
create_replanned_forge_session
```

`forge_execute_task` immediately returns generated IDs and `accepted`; it does not block a model call on physical execution. Orchestrator progresses in the background and routes terminal state back to the originating `session_key` through a system event.

A completion event contains:

```json
{
  "session_id": "...",
  "root_session_id": "...",
  "status": "succeeded|failed|timed_out|cancelled",
  "execution_status": "succeeded|failed|timed_out|cancelled|unknown",
  "verification_verdict": "success|failure|replan_required|inconclusive|null",
  "error_code": null,
  "error_message": null
}
```

A recovery event carries parent, goal, criteria, preserved constraints, unmet criteria, guidance, evidence references, and deadline. It instructs Planner to call `create_replanned_forge_session` but contains no executable action.

## 4. PAOS/Gateway HTTP

| Method | Path | PAOS use | State effect |
|:-------|:-----|:---------|:-------------|
| GET | `/agent/runtime/capabilities` | Startup contract and action discovery | Validate/cache before work |
| GET | `/agent/runtime/status` | Live `forge_get_context` status | Read only |
| GET | `/agent/runtime/context` | Readiness, image sources, context | Read only/source discovery |
| POST | `/agent/runtime/reset` | Explicit reset | Only without active lineage |
| POST | `/agent/sessions` | Create one high-level action | Called after durable dispatch intent |
| GET | `/agent/sessions/{session_id}` | Only execution-terminal source | queued/running/terminal |
| POST | `/agent/sessions/{session_id}/cancel` | Timeout, user cancel, graceful shutdown | Persist cancel response |

`ForgeGatewayClient` uses `httpx.AsyncClient`, disables proxy-environment inheritance (`trust_env=False`), and consistently decodes JSON objects. HTTP errors and `ok=false` become `ForgeGatewayError`, retaining status code for restart-404 semantics.

## 5. Session and command identity

PAOS generates:

```text
session_id = forge_<random>
command_id = command_<random>
```

Every response after POST preserves:

```text
response session_id == PAOS session_id
response command_id == PAOS command_id
command.session_id == PAOS session_id
command.request_id == PAOS command_id
session.action_type == request.action_type
command action_type/policy_id/command == advertised capability
```

PAOS does not accept a new Gateway-generated ID as an alias. Parsing may select a command only when strict identity validation ultimately succeeds.

## 6. PAOS/Gateway WebSocket

### `/ws/images`

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

PAOS stores Gateway `timestamp` as `captured_at` when present and independently records local `received_at`. Per-source sequence participates in the before/after boundary.

### `/ws/state`

Each message is a JSON object. Gateway 1.0.0 has no uniform source-timestamp field, so PAOS preserves the payload and local `received_at` with `captured_at=null`.

### Connection semantics

- HTTP(S) base URL maps automatically to WS(S).
- Images and state use independent connections and reconnection loops.
- Collector retains only the highest legal sequence per source.
- Non-required sources may be ignored.
- Connection/message/validation errors enter Bundle quality instead of masquerading as evidence.

## 7. Gateway terminal semantics

The only terminal source is `GET /agent/sessions/{session_id}`. PAOS accepts:

```text
session.status == command.status == succeeded | failed | cancelled
```

PAOS never infers terminal state from fixed waiting, robot stability, image change, command outputs, or WebSocket state.

The PAOS execution deadline produces `timed_out` followed by cancellation; this is not a native Gateway terminal report.

## 8. Verification Service boundary

The child process exposes local HTTP:

| Method | Path | Use |
|:-------|:-----|:----|
| GET | `/healthz` | Bounded readiness check |
| POST | `/v1/verify-task` | Submit `forge_verification_request_v1` |

Requests require a randomly derived `X-PAOS-Admin-Token`. The service receives resolved public contracts, multimodal evidence, history, and lessons only. It never accesses Gateway or creates a recovery child.

## 9. Persistence boundary

### SQLite

SQLite stores `ForgeSessionRecord` JSON, unique identities, indexed status, and append-only events. It is Orchestrator's recovery source; business code does not mutate tables directly.

### Artifacts

Adapter uses atomic replacement for:

```text
execution_record.json
before_snapshot.json / after_snapshot.json
evidence_bundle.json
evidence/*
```

Verifier writes `verification_result.json` and `LESSONS.md`. Artifact URIs are relative to the workspace and are resolved and checked again on read.

### Consistency boundary

SQLite and files are not one cross-resource transaction. Therefore ordering matters: before entities/manifest complete before their reference is stored; dispatch intent is durable before HTTP mutation; a written Execution Record is reused across a database-commit crash window but fails on identity mismatch.

## 10. Trust boundary

| Data | Trust policy |
|:-----|:-------------|
| Gateway capabilities | Strict version and shape; revalidate action identity in every response |
| Gateway JSON | Object required; HTTP or `ok=false` fails |
| WebSocket image | Validate Base64, size, media type, magic bytes, sequence |
| Artifact | Revalidate safe URI, existence, byte size, SHA-256, media type |
| Verifier output | Validate JSON, Pydantic, exact criteria, known evidence refs |
| Recovery guidance | Planner context only, never a command |

## Next reading

- [Integration Development Guide](README_en.md)
- [Developer Manual](../en/03-developer-manual.md)
- [Forge Integration Contract](../forge/README.md)
