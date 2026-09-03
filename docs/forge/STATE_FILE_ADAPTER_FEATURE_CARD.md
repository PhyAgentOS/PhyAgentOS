# State File Adapter 功能引用卡

## Feature

- Name: PAOS State File Adapter v1
- User-visible capability: 解析五类 Markdown 状态文件，生成受限 projection，并提供 `TARGETS.md` shadow validation、`SESSIONS.md` dry-run 预览与人工确认后的受限 AgentTask 编译。
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
- `TARGETS.md`: `input` mode; strict capability matrix validation; explicitly approved candidate with `motion_authorized=false`; never direct admission
- `SESSIONS.md`: `input` mode; deterministic dry-run previews; one-session-at-a-time promotion only after digest-bound human approval
- `SKILLRUNTIME.md`, `LESSONS.md`: `projection` mode; atomic writes and digest-based drift checks
- `ENVIRONMENT.md`: `projection` mode; strict snapshot/provenance schema, revision matching, atomic writes, and digest-based drift checks
- Environment producer: consumes an existing `ObservationSnapshot` and explicit provenance, optionally binds the revision to an `EnvironmentAdapter.snapshot()` identity, and only writes the projection; it does not create tasks, evidence, or actions
- Evidence association: `ForgeEvidenceWriter` validates writer-owned before/after manifests and derives a stable opaque `evidence://` reference; the producer may inject phase/reference from that manifest and rejects mismatches

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
- Promotion requires `SessionCompileApproval` bound to the parsed source digest; repeated source/session compilation reuses the existing AgentTask record
- Promotion calls only `AgentTaskCoordinator.create_task()` and is rejected when another non-terminal AgentTask occupies the global slot
- Managed Forge runtimes may additionally require the current turn's `activation_id`; the adapter forwards it but never creates a Skill activation itself
- `TargetProfileApproval` binds both source and baseline digests; candidate data is a copy and remains a non-authoritative admission proposal

## Acceptance

- discovery/context: no Gateway route is added; adapter is imported as a local utility
- valid and invalid contract cases, approval failures, baseline drift, environment provenance/revision, strict SceneGraph consumption, and no-motion boundaries: covered by `tests/test_state_file_adapter.py`
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
- no multi-session batch promotion (prevents partial writes under the single-task invariant)
- no Environment Markdown as Evidence or Verifier authority; before/after semantics remain in immutable Evidence snapshots
- no producer-side sensor capture, Gateway call, Watchdog dispatch, AgentTask write, or motion authorization
- no snapshot overwrite within a phase; writer-owned manifest/version/path checks remain fail-closed
