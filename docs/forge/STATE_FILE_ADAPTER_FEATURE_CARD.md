# State File Adapter 功能引用卡

## Feature

- Name: PAOS State File Adapter v1
- User-visible capability: 解析五类 Markdown 状态文件，生成受限 projection，并提供 `TARGETS.md` shadow validation 与 `SESSIONS.md` dry-run 预览。
- Baseline commit: `c5740a5`
- Documentation version: PAOS v1.0.0

## Normative references

- Developer Manual: module boundaries, AgentTask ownership, and test gates
- Forge Integration Contract: Query/Action/Session, identity, evidence, and no-blind-retry semantics
- Integration Guide: extension points, generic runtime, adapter/profile separation, and Fake Gateway conformance
- Communication: persistence, trust, and opaque-reference boundaries
- Agent Experience and Skill Evolution: authoritative `experience.sqlite3` and non-authoritative Lessons projection

## Selected extension point

- Workspace/state adapter and bounded projection utility; no new Query, Action, Session, Gateway route, or Runtime queue

## Public contract

- Protocol: `paos.state-file.v1`; one fenced JSON/YAML object with exactly `paos` and `data` keys
- Metadata: `kind`, `mode`, `revision`, `source`, optional ISO-8601 `generated_at`
- `TARGETS.md`: `input` mode; strict capability matrix validation; shadow-only report with `motion_authorized=false`
- `SESSIONS.md`: `input` mode; deterministic dry-run previews only
- `SKILLRUNTIME.md`, `ENVIRONMENT.md`, `LESSONS.md`: `projection` mode; atomic writes and digest-based drift checks

## Ownership

- physical execution truth: unchanged; Gateway/ToolEndpoint remains the sole owner
- task aggregation: unchanged; `AgentTaskCoordinator`/`AgentTaskStore` remain authoritative
- evidence: unchanged; immutable Evidence artifacts remain authoritative
- user-level verdict: unchanged; generic verifier and AgentTask finalize remain authoritative
- experience/evolution: unchanged; `experience.sqlite3` remains authoritative, projections are non-authoritative

## Failure and recovery

- Reject malformed UTF-8, missing/duplicate structured blocks, unknown fields, invalid metadata, non-finite values, and schema violations
- Projection drift is explicit; `expected_sha256` mismatch raises `StateFileDriftError`
- Parse failures never write stores, enqueue Watchdog work, call Gateway, or authorize motion
- Dry-run previews use stable content-derived IDs but are not AgentTask IDs and are never persisted

## Acceptance

- discovery/context: no Gateway route is added; adapter is imported as a local utility
- valid and invalid contract cases: covered by `tests/test_state_file_adapter.py`
- binding and identity checks: revision/source and deterministic preview identity are tested
- evidence and verification: no evidence/verdict is produced by this adapter
- Fake Gateway/conformance: not applicable; no Gateway route is created
- simulation or hardware proof: not applicable; implementation is no-motion
- no-motion boundary: every TARGETS report and session preview exposes `motion_authorized=false`

## Non-goals

- no direct Agent-to-SDK call
- no second execution protocol
- no Watchdog queue or Session state machine
- no direct SQLite writes
- no automatic motion authorization
