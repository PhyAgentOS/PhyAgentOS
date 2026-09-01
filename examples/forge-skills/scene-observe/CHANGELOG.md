# Change Log

## v0.3.0 (2026-09-01) - codex

- [sense] [feat] [completed] Added the provider-neutral `grasp.propose` Query as the third
  capability on a separate branch. It converts one verified scene understanding result into
  a generic grasp candidate set with candidate identity, frame/calibration binding,
  provenance, confidence/score, bounded funnel evidence, and explicit empty-candidate
  semantics while staying synchronous, read-only, and free of IK, planning, collision
  checking, Actions, Sessions, and motion authorization.
- [sense] [feat] [完成] 在独立分支上新增 provider-neutral `grasp.propose` Query 作为第三个能力。
  它把一个已验证的 scene understanding 结果转换为带候选身份、frame/calibration 绑定、
  provenance、置信度/评分、有界漏斗证据和明确空候选语义的通用抓取候选集；保持同步只读，
  不包含 IK、规划、碰撞检测、Action、Session 或运动授权。

### Verification

- Added `contracts/grasp.propose.tool.yaml`, `src/scene_observe/grasp_proposal.py`, and
  `tests/test_grasp_propose.py`; updated the Fake Gateway routes, Bundle manifest, and
  workflow guidance.
- Input requires the named observation reference, scene revision, frame, calibration,
  freshness, `max_age_ms`, and observation-bound targets. Stale and missing-calibration
  inputs fail closed before the provider runs; an empty target list returns `status=empty`
  without fabricated candidates.
- Output preserves `candidate_set_ref`, per-candidate identity/frame/provenance, reconciled
  funnel counts, and ambiguity evidence. Qualification is limited to `proposed`,
  `low_confidence`, and `ambiguous`; no field expresses IK success, collision clearance,
  reachability, or action admission, and `motion_authorized` stays `false`.
- The Fake Gateway advertises all three Query specs, reflects grasp-provider availability
  in the `grasp.propose` context, and fails closed when the provider is not configured.
- Tests use PAOS's real `ForgeToolClient.invoke_query_tool("grasp.propose", ...)` through the
  documented Gateway routes and prove no Action, Session, invocation, or motion route exists.

## v0.1.0 (2026-09-01) - codex

- [sense] [feat] Provider-neutral `scene.observe` Query contract, endpoint interface,
  no-motion Fake Gateway transport, and PAOS ForgeToolClient conformance tests.

## v0.1.1 (2026-09-01) - codex

- [sense] [fix] [completed] Added the named `observation_ref` required by the PAOS
  perception architecture so downstream Query capabilities can bind to one immutable
  observation without importing a provider or simulator.
- [sense] [fix] [完成] 增加 PAOS 感知架构要求的命名 `observation_ref`，使下游 Query
  能绑定一个不可变观测，而无需导入 provider 或仿真器。

### Verification

- `scene.observe` ToolSpec/output now requires `observation_ref` with the
  `observation://<scene_revision>/<frame>` shape.
- `pytest`: 7 passed; `ruff check`: passed; `compileall`: passed.
- Changed files: `contracts/scene.observe.tool.yaml`,
  `src/scene_observe/fake_gateway.py`, `tests/test_scene_observe.py`.

## v0.2.0 (2026-09-01) - codex

- [sense] [feat] [completed] Added the provider-neutral `scene.understand` Query as a
  separate capability branch. It will consume one named observation, preserve
  provenance/frame/calibration bindings, and return entity claims, relations,
  spatial envelopes, confidence, and ambiguity without motion or provider fields.
- [sense] [feat] [完成] 新增 provider-neutral `scene.understand` Query 独立能力分支。
  它将消费一个命名观测，保留 provenance/frame/calibration 绑定，并返回实体声明、关系、
  空间包络、置信度和歧义信息；不包含运动或 provider 字段。

### Verification

- Added `contracts/scene.understand.tool.yaml`, `src/scene_observe/understanding.py`,
  and `tests/test_scene_understand.py`; updated the Bundle manifest, workflow guidance,
  and Fake Gateway routes.
- Input requires the named observation reference, scene revision, frame, calibration,
  freshness, and artifact references. Output preserves entity/relation/spatial provenance
  and confidence while keeping `motion_authorized=false`.
- `pytest`: 13 passed; `ruff check`: passed; `compileall`: passed; Bundle archive
  validation passed (SHA-256 `d1766c1965e6b6dd664d4a5b08d79719e3826855e7b99a0f8d71e2373f912f20`, 12839 bytes).
- Fake Gateway advertises both Query specs while reflecting understanding-provider
  availability in the `scene.understand` context; unavailable providers remain fail-closed.
- [sense] [feat] Provider-neutral `scene.observe` Query contract, endpoint interface,
  no-motion Fake Gateway transport, and PAOS ForgeToolClient conformance tests.
