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
- [sense] [feat] Provider-neutral `scene.observe` Query contract, endpoint interface,
  no-motion Fake Gateway transport, and PAOS ForgeToolClient conformance tests.
