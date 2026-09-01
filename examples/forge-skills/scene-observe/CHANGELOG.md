# Change Log

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
- [sense] [feat] Provider-neutral `scene.observe` Query contract, endpoint interface,
  no-motion Fake Gateway transport, and PAOS ForgeToolClient conformance tests.
