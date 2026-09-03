# Changelog

All notable changes to PhyAgentOS are documented here. Categories follow Keep a Changelog.

## [v2.8.16] - 2026-09-03

Implemented the clean-room, adapter-side single-view perception composition:
semantic entity binding to LocateAnything proposals, bounded proposal-worker
shutdown, SAM2 box segmentation in its separate environment, deterministic
RGB-D localization, transactional derived artifacts, and projection through
the existing provider-neutral `scene.understand` Gateway contract. PAOS and
RoboTwin20 remain free of model-environment dependencies, and every result is
Query evidence with `motion_authorized=false`.

实现 clean-room、adapter-side 单视角感知 composition：语义实体绑定
LocateAnything proposal，关闭 proposal worker 后再在独立环境运行 SAM2 box
segmentation，然后确定性生成 RGB-D 定位和事务式派生资产，最终通过既有
provider-neutral `scene.understand` Gateway 契约投影。PAOS 和 RoboTwin20 不引入模型
环境依赖，所有结果仍是 `motion_authorized=false` 的 Query 证据。

### Detailed changes

- `PhyAgentOS/forge/capability_runtime/understanding.py:L461-L601` binds every derived artifact to the current request's observation, revision, frame, and calibration.
- `examples/forge-adapters/robotwin20/src/robotwin20_adapter/single_view_perception.py:L1-L707` composes proposal, segmentation, localization, artifact materialization, rollback, and ambiguity handling.
- `examples/forge-adapters/robotwin20/src/robotwin20_adapter/process_worker.py:L1-L212` and `perception_profile.py:L1-L153` add bounded JSONL process lifecycle and profile-only environment wiring.
- `examples/forge-adapters/robotwin20/runtime/locateanything_worker.py:L1-L242`, `sam2_worker.py:L1-L186`, and `worker_protocol.py:L1-L60` are adapter-owned entrypoints for the two existing isolated model environments.
- `examples/forge-adapters/robotwin20/profiles/robotwin20/perception.yaml:L1-L56` externalizes interpreters, model revision, checkpoint, CUDA device, caches, artifact roots, and timeouts.
- Adapter/workflow tests cover worker protocol failures, request binding, proposal ambiguity, mask/depth/calibration validation, artifact traversal and rollback, and the no-motion Gateway route.

### Validation

- PAOS/workflow/adapter suite: `281 passed, 2 skipped`; model-side tests skip because PAOS intentionally has no NumPy/Pillow.
- Isolated adapter numerical/worker suite: `27 passed`.
- Real no-motion composition on an existing RoboTwin RGB-D capture returned one LocateAnything proposal, an aligned SAM2 mask, 788 camera-frame points, all three derived artifacts, and `motion_authorized=false`; both worker processes exited.
- Ruff, compileall, and `git diff --check` passed. A system-Python whole-suite attempt was not accepted because that interpreter lacks PAOS `loguru` and asyncio test dependencies.
- `.codegraph/` and `.cursor/` remain untracked and are not staged.

## [v2.8.15] - 2026-09-03

Extended the provider-neutral `scene.understand` Query with auditable derived
perception artifacts for instance masks, object point clouds, and metric
localization. Every artifact is bound to the observation, scene revision,
entity, frame, calibration, source lineage, and root provenance; no Action or
motion authorization was added. The independent RoboTwin adapter forwards only
plain mappings and remains free of PAOS, simulator, Torch, and model imports.

扩展 provider-neutral `scene.understand` Query，增加可审计的实例 mask、目标点云和度量定位
派生资产。每个资产绑定 observation、scene revision、entity、frame、calibration、source
lineage 和 root provenance；没有增加 Action 或运动授权。独立 RoboTwin adapter 只转发普通
mapping，仍不依赖 PAOS、仿真器、Torch 或模型导入。

### Validation

- `268 passed` for the workflow and RoboTwin adapter suites.
- Ruff, compileall, ToolSpec YAML equality, and `git diff --check` passed.
- `.codegraph/` and `.cursor/` remain untracked and were not staged.

## [v2.8.14] - 2026-09-03

整理两条 provider-neutral 感知接入方案：单视角
`LocateAnything → SAM2 → RGB-D localization`，以及多视角
`MultiViewObservationSet → cross-view segmentation/identity/geometry fusion`。
明确多视角不是 RoboTwin Skill 或模型 Tool；融合实体几何可供
`scene.understand` / `grasp.propose`，Global SceneGeometry 仅作为独立可选输出，
所有结果仍须经过 PAOS provenance、frame/calibration 和 fail-closed 门禁。

Consolidated two provider-neutral perception paths: single-view
`LocateAnything → SAM2 → RGB-D localization`, and multi-view
`MultiViewObservationSet → cross-view segmentation/identity/geometry fusion`.
Clarified that multi-view is neither a RoboTwin Skill nor a model Tool; fused
entity geometry may feed `scene.understand` / `grasp.propose`, while Global
SceneGeometry remains a separate optional output under PAOS provenance,
frame/calibration, and fail-closed gates.

### Validation

- `git diff --check` passed.
- Execution document audit confirms no direct Agent-to-model/Dora/SDK path and no implicit camera motion.
- `.codegraph/` and `.cursor/` remain untracked and were not staged.

## [v2.8.13] - 2026-09-03

Fixed the GPT Responses strict JSON schema by declaring `spatial_envelopes.unit`
as a typed string const. Added recursive regression checks because the fake
Responses client does not validate request schemas. Updated the RoboTwin
adapter diagnosis and README to keep recognition, segmentation, metric
localization, grasp-pose proposal, readiness, and execution in their PAOS
use-case boundaries; the current GPT provider remains RGB semantic-only.

修正 GPT Responses strict JSON schema，为 `spatial_envelopes.unit` 补充
`type: string`，并增加递归回归校验，避免 Fake client 遗漏真实 API 的请求阶段错误。
同步更新 RoboTwin adapter 诊断与 README，明确识别、分割、度量定位、抓取位姿、准入和执行的
PAOS 用例归属；当前 GPT provider 仍只负责 RGB 语义理解。

### Validation

- `261 passed` for the adapter/workflow suites.
- Ruff, compileall, and `git diff --check` passed.
- `.codegraph/` and `.cursor/` remain untracked and were not staged.

## [v2.8.12] - 2026-09-03

Added an adapter-side `FilesystemArtifactResolver` for external RoboTwin
observation artifacts. It safely maps opaque RGB artifact references to files
under an explicitly external absolute root, rejects traversal/non-image refs,
and enables the GPT scene-understanding provider to consume real runtime
captures without exposing paths or assets to PAOS.

为外部 RoboTwin observation artifact 增加 adapter 侧 `FilesystemArtifactResolver`。它只在显式外部绝对根目录
下安全解析 opaque RGB artifact 引用，拒绝路径穿越和非图像引用，使 GPT 场景理解 provider 能读取真实 runtime
capture，同时不向 PAOS 暴露路径或资产。

### Validation

- `260 passed in 2.62s` for the adapter/workflow suites.
- Ruff, compileall, and `git diff --check` passed.
- Complete `ForgeToolClient -> Fake Gateway -> generic endpoint -> RoboTwin provider -> GPT client` route
  is covered by a fake Responses client test.
- No live API call was attempted because `HEPHAESTUS_RELAY_API_KEY` remains absent; no real model result is claimed.
- `.codegraph/` and `.cursor/` remain untracked and were not staged.

## [v2.8.11] - 2026-09-02

Added the clean-room, adapter-owned GPT-5.6-sol Responses provider for
`scene.understand`. It follows the existing Hephaestus relay configuration
shape (`gpt-5.6-sol`, Responses API, configurable relay base URL) without
importing or reusing Hephaestus code. Images are resolved through an injected
opaque-artifact resolver, credentials are read only at invocation time, and
the adapter emits only the provider-neutral scene-understanding fields.

收录独立 adapter 自有的 GPT-5.6-sol Responses `scene.understand` provider。它参考 Hephaestus 已验证的
relay 配置格式（`gpt-5.6-sol`、Responses API、可配置 base URL），但不导入或复用 Hephaestus 代码。图像通过
注入式 opaque-artifact resolver 解析，凭据只在调用时读取，adapter 只输出 provider-neutral 场景理解字段。

### Detailed changes

- `examples/forge-adapters/robotwin20/src/robotwin20_adapter/openai_scene_understanding.py:L1-L350` adds the
  isolated provider, closed JSON schema, data-URL conversion, and fail-closed credential/artifact/response paths.
- `PhyAgentOS/forge/capability_runtime/understanding.py:L15-L285` normalizes plain mappings at the Gateway edge
  and binds claim provenance to requested observation artifacts; PAOS still has no RoboTwin/SAPIEN/Torch/OpenAI
  dependency.
- `examples/forge-adapters/robotwin20/src/robotwin20_adapter/understanding.py:L14-L86` keeps the Python 3.10
  adapter independent from PAOS's Python 3.11+ runtime.
- `examples/forge-adapters/robotwin20/src/robotwin20_adapter/__init__.py:L12-L42` exports the provider seam and
  schema while keeping the OpenAI SDK lazy; `pyproject.toml:L8-L9` makes OpenAI an adapter-only optional extra.
- `examples/forge-adapters/robotwin20/tests/test_openai_scene_understanding.py:L1-L158` and
  `tests/test_scene_understand_provider.py:L85-L116` cover fake Responses payloads, closed schema, missing
  credentials/artifacts, provider-specific fields, and unbound provenance.
- `docs/forge/ROBOTWIN_ADAPTER_REFACTOR_DIAGNOSIS.md:L268-L298` now records that the provider is implemented but
  no live GPT result is claimed without the external API key; Gateway/Dora and the remaining five providers are
  still pending.

### Validation

- Adapter/workflow tests: `258 passed in 2.60s`.
- Ruff, compileall, and `git diff --check` passed.
- RoboTwin20 Python `3.10.21` imported the adapter successfully.
- The live desktop-tidy invocation failed closed before network transmission because
  `HEPHAESTUS_RELAY_API_KEY` was absent; no real model result is claimed.
- `.codegraph/` and `.cursor/` remain untracked and were not staged.

## [v2.8.10] - 2026-09-02

Removed the duplicate provider-neutral `RoboTwinUnderstandingSnapshot` from
the adapter. The compatibility name now aliases PAOS's
`UnderstandingSnapshot`, so the adapter only translates inference inputs and
outputs while PAOS remains the sole owner of the public scene-understanding
snapshot contract.

移除 adapter 中重复的 provider-neutral `RoboTwinUnderstandingSnapshot`。兼容名称现在指向 PAOS 的
`UnderstandingSnapshot`，adapter 只负责 inference 输入/输出转换，PAOS 继续作为 scene-understand snapshot
公共契约的唯一所有者。

### Validation

- `251 passed` for the adapter/workflow suites.
- Ruff, compileall, and `git diff --check` passed.
- Provider-specific output remains fail-closed and the ForgeToolClient/Fake Gateway path is unchanged.

## [v2.8.9] - 2026-09-02

Moved the provider-neutral `manipulation.prepare` Query implementation into
the PAOS-owned generic capability runtime. The runtime owns candidate binding,
preparation identity, workspace/kinematic/collision check validation, evidence
projection, stale/empty/unavailable/invalid states, and the fixed
`motion_authorized: false` boundary. The Skill module is now a compatibility
export only; no robot, simulator, or model dependency was added.

将 provider-neutral `manipulation.prepare` Query 实现迁移到 PAOS 自有 generic capability runtime。运行时统一
持有候选绑定、preparation identity、workspace/kinematic/collision 检查校验、证据投影、
stale/empty/unavailable/invalid 状态以及固定的 `motion_authorized: false` 边界。Skill 模块仅保留兼容导出，
未加入机器人、仿真器或模型依赖。

### Validation

- `250 passed` for the adapter/workflow suites.
- Ruff, compileall, and `git diff --check` passed.
- `manipulation.prepare` remains read-only; no Action/Session/motion route is created.

## [v2.8.8] - 2026-09-02

Moved the provider-neutral `grasp.propose` Query implementation into the
PAOS-owned generic capability runtime. The runtime now owns the strict
ToolSpec, observation/frame/calibration binding, candidate and candidate-set
identity, funnel reconciliation, provenance validation, stale/empty/
unavailable/invalid states, and fail-closed provider error projection. The
Skill module is now a compatibility export only, and preparation imports the
shared candidate validator directly from PAOS. No YOLO, GraspGen, RoboTwin,
SAPIEN, Torch, Dora, or Hephaestus dependency was added.

将 provider-neutral `grasp.propose` Query 实现迁移到 PAOS 自有 generic capability runtime。运行时统一持有
严格 ToolSpec、observation/frame/calibration 绑定、候选与候选集身份、funnel 对账、provenance 校验、
stale/empty/unavailable/invalid 状态以及 provider 异常的 fail-closed 投影；Skill 模块仅保留兼容导出，
准备能力直接导入 PAOS 的候选校验器。未加入 YOLO、GraspGen、RoboTwin、SAPIEN、Torch、Dora 或 Hephaestus
依赖。

### Validation

- `249 passed` for the adapter/workflow suites.
- Ruff, compileall, and `git diff --check` passed.
- `grasp.propose` remains Query-only; no Action/Session/motion route is created.

## [v2.8.7] - 2026-09-02

Moved the provider-neutral `scene.understand` contract into the PAOS-owned
generic capability runtime. ToolSpec validation, observation/artifact binding,
scene-graph snapshot validation, stale rejection, provider error projection,
and Query result projection now live under
`PhyAgentOS.forge.capability_runtime.understanding`. The Skill module is only a
compatibility export; no Hephaestus, RoboTwin, SAPIEN, Torch, YOLO, Dora, or
motion dependency was added.

将 provider-neutral `scene.understand` 契约迁移到 PAOS 自有的 generic capability runtime。ToolSpec 校验、
observation/artifact 绑定、场景图 snapshot 校验、stale 拒绝、provider 错误投影和 Query 结果投影均由
`PhyAgentOS.forge.capability_runtime.understanding` 持有；Skill 模块仅保留兼容导出。未加入 Hephaestus、
RoboTwin、SAPIEN、Torch、YOLO、Dora 或运动依赖。

### Validation

- `248 passed in 2.64s` for adapter/workflow tests.
- Ruff, compileall, and `git diff --check` passed.
- Existing Skill imports remain compatible while resolving to the PAOS-owned implementation.

## [v2.8.6] - 2026-09-02

Added the independent RoboTwin adapter seam for the existing provider-neutral
`scene.understand` Query. `RoboTwinSceneUnderstandingProvider` accepts an
injected inference service, forwards only `scene.observe` identity/artifact
references, and rejects provider-specific fields. The generic endpoint now
projects provider failures as explicit `understanding_provider_error` results.
No detector/VLM/YOLO or simulator truth is included.

按 v1.0 扩展原则，在现有 provider-neutral `scene.understand` Query 后增加独立 RoboTwin adapter seam。
`RoboTwinSceneUnderstandingProvider` 只转发 `scene.observe` 身份与 artifact 引用，拒绝 provider 专有字段；
通用 endpoint 将 provider 异常投影为明确的 `understanding_provider_error` 结果。不包含检测器、VLM、YOLO
或仿真真值。

### Validation

- `248 passed in 2.65s` for adapter/workflow tests.
- Ruff, compileall, and `git diff --check` passed.
- No Action/Session/motion route or simulator/model import was added.

## [v2.8.5] - 2026-09-02

Unified Fake Gateway and RoboTwin `scene.observe` results behind the existing
`ForgeToolClient.invoke_query_tool` path. Added a runtime-only
`RoboTwinObservationProvider` that projects camera/depth/state captures into
provider-neutral observation identity, frame, calibration, freshness, and typed
artifact references. The adapter accepts either the external runtime capture
seam or the injected `RoboTwin20Adapter` seam; PAOS remains free of RoboTwin,
SAPIEN, Torch, and model imports. Relaxed the Fake Gateway artifact-reference
validator to accept capture subpaths, and added equality/integration tests.

通过既有 `ForgeToolClient.invoke_query_tool` 路径统一 Fake Gateway 与 RoboTwin 的 `scene.observe` 结果。
新增 runtime-only `RoboTwinObservationProvider`，将 camera/depth/state capture 投影为 provider-neutral 的
observation identity、frame、calibration、freshness 与 typed artifact refs；支持外部 runtime capture seam
和注入式 `RoboTwin20Adapter` seam。PAOS 仍不包含 RoboTwin、SAPIEN、Torch 或模型导入；Fake Gateway
artifact ref 校验支持 capture 子路径，并新增一致性集成测试。

### Validation

- `244 passed in 2.53s` for adapter/workflow tests.
- Ruff, compileall, and `git diff --check` passed.
- External RoboTwin20 `--format scene_observe` smoke returned the expected observation reference and RGB/depth/state artifacts; OIDN CUDA warnings remain a known runtime risk.
- `.codegraph/` and `.cursor/` remain untracked and were not staged.

## [v2.8.4] - 2026-09-02

Fixed the external RoboTwin runtime working-directory boundary in
`examples/forge-adapters/robotwin20/runtime/robotwin_backend.py:L88-L101,L119-L120,L179-L184,L208-L209,L223-L224`.
Official imports, `setup_demo`, `get_obs`, and `close_env` now run under the
runtime checkout and restore the caller's cwd. This removes the real smoke
failure caused by RoboTwin's relative `assets/objects/objaverse/list.json`
lookup when launched from the PAOS root. Added the regression test at
`tests/test_robotwin_backend_contract.py:L55-L65`.

修复独立 RoboTwin runtime 的工作目录边界：官方导入、场景初始化、观测读取和关闭均在外部 runtime checkout
上下文中执行并恢复调用方 cwd，消除从 PAOS 根目录启动时的相对资产路径错误。新增 cwd 回归测试；不改变
PAOS 依赖、ToolSpec 或动作权限。

## [v2.8.3] - 2026-09-02

Added the runtime-only `RoboTwinSensorBackend` at
`examples/forge-adapters/robotwin20/runtime/robotwin_backend.py:L1-L338` and
 contract tests at `tests/test_robotwin_backend_contract.py:L1-L77`. The backend
uses the official task's rendered RGB/depth and joint/end-effector state,
persists calibration and typed external artifacts, and injects through the
provider-neutral `RoboTwin20Adapter`. It rejects simulator truth channels and
never calls action/evaluator APIs. A real `beat_block_hammer/demo_clean` seed-0
capture produced 240x320 RGB/depth artifacts; SAPIEN OIDN CUDA warnings remain a
known runtime risk.

新增 runtime-only `RoboTwinSensorBackend`，通过 provider-neutral `RoboTwin20Adapter` 暴露真实 RGB/depth/state
artifact 与 calibration；不导出 actor/segmentation truth，不调用动作或 evaluator。真实 seed-0 capture 已验证，
但 OIDN CUDA warning 仍是运行时风险。

## [v2.8.2] - 2026-09-02

Added the standard-library fail-closed preflight at
`examples/forge-adapters/robotwin20/src/robotwin20_adapter/preflight.py:L1-L284`,
its tests at `tests/test_preflight.py:L1-L75`, and the `robotwin20-preflight`
entry point in `pyproject.toml:L1-L13`. The user-provided external RoboTwin20
environment passed all 16 checks (`ready=true`), including assets, CUDA
`sm_120`, SAPIEN, Vulkan, and task import, without modifying PAOS dependencies.

新增只使用标准库的 fail-closed preflight 与测试及 console entry point。用户提供的隔离 RoboTwin20 环境 16 项
检查全部通过（`ready=true`），包含官方 assets、CUDA `sm_120`、SAPIEN、Vulkan 与 task import；PAOS 依赖未被污染。

## [v2.8.1] - 2026-09-02

Verified the isolated `RoboTwin20` conda environment and checked out the official RoboTwin 2.0 source with
its pinned `XPolicyLab` submodule under `/home/yanxu/robotwin20-runtime/RoboTwin`. Confirmed the official asset
source is the Hugging Face dataset `TianxingChen/RoboTwin2.0`; only `embodiments.zip` was downloaded and verified.
The large `background_texture.zip` and `objects.zip` archives remain for the user to download. No PAOS dependency,
wheel content, ToolSpec, Hephaestus source, or tracked simulator asset was changed.

已核对隔离 `RoboTwin20` conda 环境，并将官方 RoboTwin 2.0 源码及固定的 `XPolicyLab` 子模块 checkout 到
`/home/yanxu/robotwin20-runtime/RoboTwin`。确认官方资产来源为 Hugging Face 数据集
`TianxingChen/RoboTwin2.0`；本次仅下载并校验 `embodiments.zip`，大型 `background_texture.zip` 与
`objects.zip` 留待用户自行下载。未修改 PAOS 依赖、wheel 内容、ToolSpec、Hephaestus 源码或已跟踪仿真资产。

### Validation

- `RoboTwin20` Python `3.10.21`; SAPIEN/Torch/TorchVision/OpenCV/Gymnasium/Open3D present.
- `embodiments.zip`: `219859313` bytes, SHA-256 `6b87d7d55e106d8ff25917e0538eb1e177fc549280e8a742a8cec3cb9f953fc6`.
- Official sizes: `background_texture.zip` `10970687027` bytes; `objects.zip` `3737778549` bytes.
- `.codegraph/` and `.cursor/` remain untracked and were not staged.

## [v2.8.0] - 2026-09-02

Implemented the first RoboTwin 2.0 adapter slice: an environment-owned lifecycle seam and sensor-only observation
source that can be connected to camera/depth/state outputs without importing RoboTwin into PAOS.

### Changed

- Added an independently packaged `robotwin20` adapter with explicit backend and sensor artifact protocols.
- Requires RGB/depth/state artifacts, frame, calibration, timestamp, and scene revision; rejects missing or
  simulator-ground-truth-only observations.
- Added no-motion tests; no YOLO, SAPIEN, robot SDK, Dora, or actuator dependencies were added to PAOS.

## [v2.7.0] - 2026-09-02

Implemented the simulator-free generic capability runtime foundation for the next integration phase.

### Changed

- Added reusable ToolEndpoint registration, discovery/context, Query dispatch, and bounded Action lifecycle
  primitives under `PhyAgentOS.forge`, with provider ports defined independently of RoboTwin, SAPIEN, YOLO,
  robot SDKs, and hardware.
- Added no-motion conformance tests and documented that this phase does not implement perception models or
  physical execution.

## [v2.6.3] - 2026-09-02

Corrected the documented extension order so the independent generic capability runtime is implemented before
any RoboTwin adapter work.

### Changed

- Added the simulator-free generic ToolEndpoint/provider-port phase to the bilingual user development guides.
- RoboTwin remains a profile-selected EnvironmentAdapter and simulation ground truth remains comparison-only.

## [v2.6.2] - 2026-09-02

Renamed the six-Tool workflow Skill to `pick-place-workflow` and corrected the RoboTwin perception boundary.

### Changed

- The Skill name now describes the complete observe → understand → propose → prepare → acquire → place workflow;
  the six stable Tool IDs are unchanged.
- PAOS v1.0 still requires an independent generic capability runtime. RoboTwin actor/entity truth, segmentation,
  object metadata, internal poses, and `check_success()` are simulation comparison/acceptance facts only; real
  deployment must use sensor artifacts and replaceable perception providers.
- Renamed `examples/forge-skills/scene-observe/` to `examples/forge-skills/pick-place-workflow/` and synchronized
  package imports, tests, manifest, and runtime discovery fixtures.

### Validation

- `220 passed`; `ruff check`; `compileall`; and `git diff --check` passed.
- No Dora, real Gateway server, RoboTwin, hardware, or motion route was started.

## [v2.6.1] - 2026-09-02

Saved and reviewed the RoboTwin adapter refactor diagnosis, separating reusable capability runtime semantics
from environment-specific adapters.

### Added

- Added `docs/forge/ROBOTWIN_ADAPTER_REFACTOR_DIAGNOSIS.md` with ownership boundaries, six-Tool migration seams,
  clean-room reimplementation rules, profile strategy, and acceptance gates.

### Changed

- Added diagnosis links to the Forge contract and documentation index.

### Security

- Documentation-only change; no Hephaestus, PAOS runtime, Gateway implementation, simulator, hardware, or motion path changed.

## [v2.6.0] - 2026-09-02

Clarified the v1.0 PAOS boundary for simulator integration and corrected the RoboTwin execution order.

### Changed

- Skills expose provider-neutral ToolSpecs and workflow guidance; RoboTwin 2.0 remains an independent
  Gateway/ToolEndpoint/Dora/simulator runtime.
- Documented that RoboTwin task, SAPIEN, embodiment, and benchmark configuration belongs in the adapter/profile,
  while a Skill Bundle freezes only runtime wiring and locked artifacts.

### Security

- Documentation-only change; no PAOS runtime, Gateway implementation, simulator, hardware, or motion path changed.

## [v2.5.3] - 2026-09-02

Added a reusable v1.0 feature-reference-card method for planning and reviewing PAOS extensions.

### Added

- Added `docs/forge/FEATURE_REFERENCE_CARDS.md`, linking normative documentation, selected extension points, ownership, failure semantics, implementation modules, tests, and PR traceability.

### Security

- Documentation-only change; no Gateway, Runtime, simulator, hardware, or motion path changed.

## [v2.5.1] - 2026-09-02

Backfilled the v2.5.0 verification-context commit and root index record.

### Changed

- Recorded commit `d6f6a74` and synchronized the bilingual monthly log with the root index.

### Security

- Documentation-only change; no runtime, Gateway, simulator, hardware, or motion path changed.

## [v2.5.0] - 2026-09-02

Added bound AgentTask verification-context integration coverage.

### Added

- Added an integration test that routes bound Query and bounded Action execution facts through
  `VerificationRequestBuilder` into the generic verifier context.
- Verified frozen binding/revision/invocation identity, execution-fact-only capability projections,
  opaque capability artifact references, and the absence of motion authorization in verifier input.

### Security

- The test uses only the Fake Gateway no-motion path and starts no Dora, simulator, hardware, or
  motion route.

## [v2.4.0] - 2026-09-02

Added ExperienceCoordinator recovery-episode integration coverage.

### Added

- Added tests confirming one recovered AgentTask becomes one processed TaskEpisode with preserved
  `replan_required → success` lineage delivered to the analyzer.
- Added assertions that capability facts alone do not create Skill candidates or Lesson clusters.

### Security

- Recovery episode tests execute no real Action, Session, Dora, hardware, or motion route.

## [v2.3.0] - 2026-09-02

Added generic AgentTask verification and recovery coverage.

### Added

- Added deterministic verifier tests for `replan_required`, append-only PlanRevision recovery, and
  final success on the same AgentTask.
- Verified recovered TaskEpisode lineage preserves both the replan-required and successful
  revisions.

### Security

- Recovery tests execute only Fake Gateway Queries and do not create motion, Session, or Dora
  execution.

## [v2.2.0] - 2026-09-02

Added governed execution record coverage after immutable Skill binding.

### Added

- Added a bound Query and bounded Action integration test through `AgentTaskCoordinator` and the
  standard Forge Tool API.
- Verified binding ID, revision ID, ToolSpec digest, invocation/attempt references, and capability
  outcome summary on persisted records.

### Security

- Execution remains on the Fake Gateway no-motion path; no real robot or simulator is invoked.

## [v2.1.0] - 2026-09-02

Added activation-to-AgentTask immutable binding integration coverage for the scene-observe Skill.

### Added

- Added tests connecting `SkillActivationManager`, `ForgeSkillBindingResolver`, and
  `AgentTaskCoordinator` through one primary Skill activation and frozen binding.
- Added fail-closed coverage for Runtime identity drift before governed Query access.

### Security

- The integration performs no Action, Session, Dora, hardware, or motion execution.

## [v2.0.0] - 2026-09-02

Added immutable Forge Skill binding coverage for the provider-neutral scene-observe Bundle.

### Added

- Added preview/freeze tests for manifest, SKILL document, Runtime identity, and all required
  ToolSpec hashes.
- Added fail-closed validation tests for Runtime replacement and ToolSpec tampering after binding.

### Security

- Binding tests execute no Action or Session and do not start Dora, hardware, or motion routes.

## [v1.9.0] - 2026-09-02

Added Runtime controller switch and rollback protection coverage.

### Added

- Added tests that block Skill Runtime switching while an AgentTask is non-terminal.
- Added rollback coverage for failed target startup and atomic active-registry replacement after a
  healthy target check.

### Security

- Tests use fake catalog/manager state only and start no Dora, Gateway, simulator, hardware, or
  motion route.

## [v1.8.0] - 2026-09-02

Added HTTP health-contract coverage for the RuntimeManager's Gateway and required Tool context
checks.

### Added

- Added a localhost-only HTTP fixture exercising real `RuntimeManager.status()` `/tools` and
  required `/context` reads.
- Added fail-closed verification that a missing or unavailable Tool context persists Runtime state
  as `failed` and prevents active-runtime publication.

### Security

- The test starts no Dora flow, hardware process, simulator, or motion route.

## [v1.7.0] - 2026-09-02

Added manifest-v2 Bundle installation and healthy Runtime discovery coverage for the
provider-neutral scene-observe Skill.

### Added

- Added isolated archive install/reload tests through `SkillInstaller` and `SkillCatalog`.
- Added fail-closed discovery tests for a single running runtime with all Tool contexts ready and
  for non-ready runtime states.

### Changed

- Marked the no-binary fake profile as `artifacts.resolver: local`; registry resolution remains
  reserved for Bundles with explicit Node locks.

## [v1.6.0] - 2026-09-02

Added a full no-motion AgentTask workflow integration fixture for the provider-neutral
scene-observe Bundle.

### Added

- Added an end-to-end test using `AgentTaskCoordinator -> ForgeToolClient -> FakeGatewayTransport`
  across observe, understand, propose, prepare, acquire, and place.
- Verified one task/revision, terminal Query/Action records, capability outcome projection, and
  synchronous `ExperienceCoordinator` `TaskEpisode` persistence.
- Covered non-terminal finalization rejection, unknown-action resend blocking, and cancellation
  reconciliation without introducing a second execution protocol or RoboTwin dependency.

## [v1.5.0] - 2026-09-02

Skill candidate support is now partitioned by bounded capability failure-owner scope. Successful
episodes with different scopes create independent candidates and cannot share promotion counts.

### Changed

- Added `capability_failure_owners` to `SkillCandidate`.
- Included owner scope in candidate identity and support matching while preserving legacy empty-scope
  compatibility and existing promotion thresholds.

## [v1.4.0] - 2026-09-02

Active Lesson counterexamples now require an exact capability failure-owner scope match. Mismatched
or scoped/legacy-missing scopes are recorded diagnostically and cannot retire or weaken a Lesson.

### Changed

- Added bounded owner-scope persistence to `ScopedLesson` and exact-scope counterexample checks.
- Preserved legacy behavior when both Lesson and episode have empty owner scopes.

## [v1.3.0] - 2026-09-02

Lesson activation now validates cross-episode capability failure-owner scope. Same-owner
observations may aggregate, while different-owner or scoped/legacy mixtures remain blocked before
synthesis and activation.

### Changed

- Added bounded owner-scope validation to LessonCluster synthesis and direct activation paths.
- Added idempotent `lesson_cluster_attribution_blocked` diagnostics without changing task verdicts,
  Tool API behavior, or Skill promotion thresholds.

## [v1.2.0] - 2026-09-02

Lesson clusters now retain a bounded capability failure-owner scope. Cross-episode observations
with different explicit root-cause owners cannot merge into one reusable Lesson pattern.

### Changed

- Added owner-scope persistence to `FailureObservation` and `LessonCluster`.
- Cluster matching rejects mismatched non-empty capability owner scopes while preserving the
  existing Skill/workflow scope and unique root-task support rules.

## [v0.9.0] - 2026-09-02

Capability outcome facts now flow from verified AgentTask execution records into the experience
and Skill-evolution input without changing task verdict authority or Forge execution boundaries.

### Added

- Added versioned `CapabilityOutcomeFact` and bounded `CapabilityOutcomeErrorFact` records to
  `TaskOutcomeEnvelope`.
- Added AgentTask outcome-source projection with provider-private Tool ID filtering and tests for
  redaction, unknown/failed states, malformed summaries, and diagnostic errors.

### Changed

- Experience analysis now receives only provider-neutral phase/status/owner/world-change/evidence
  facts. Artifact URIs and failure codes remain excluded, and facts/errors cannot authorize
  verdicts, learnability, or Skill/Lesson promotion.

## [v0.8.0] - 2026-09-02

Added a generic verification-layer projection for versioned Forge capability outcomes. The
projection exposes execution facts to AgentTask verification without creating a second execution
protocol or authorizing task success.

### Added

- Added `PhyAgentOS.verification.outcome_projection` for terminal Action summaries, including
  bounded validation of status, capability phase, failure ownership, evidence availability,
  opaque artifact references, metric names, and post-release evidence.
- Added AgentTask verifier-context fields for capability outcome projections and bounded projection
  errors while preserving the existing evidence allowlist and verdict flow.
- Added 14 projection tests covering valid outcomes, malformed summaries, unknown/failure paths,
  post-release evidence, missing summaries, and request-builder integration.

### Changed

- Documented the `execution_fact_only` authority boundary and fixed
  `task_success_authorized=false`; only `TaskVerificationContract` and the generic verifier may
  produce a user-level task verdict.

### Security

- Gateway artifact references remain opaque and are never promoted into `valid_evidence_refs`.
- Projection performs no Gateway calls, motion admission, retry, or PlanRevision mutation.

## [v1.0.0] - 2026-08-30

Initial stable release of PhyAgentOS.

### Security

- Upgraded `@whiskeysockets/baileys` to `7.0.0-rc14` to address
  `CVE-2026-48063` / `GHSA-qvv5-jq5g-4cgg`, and locked the Bridge dependency graph.

## [v0.2.3] - 2026-08-27

PhyAgentOS can run independently distributed Forge Skills through a task-scoped, immutable
Skill/Runtime/ToolSpec binding while keeping Gateway as the execution authority.

### Added

- Added first-class Query, Action, and Session Tool API lifecycles, including Session ownership,
  status/result reconciliation, and owned stop behavior.
- Added activation-time binding previews and task-time frozen bindings containing exact Skill
  version, manifest and workflow hashes, Runtime/Gateway identity, ToolSpec hashes, and Node locks.
- Added crash recovery that reconciles persisted invocation IDs using reads only, plus
  version-scoped Forge experience and Lessons.
- Added deterministic Skill bundle packaging and exact single-executable Node archive locks.
- Added the optional Bundle startup hook
  `bash <bundle>/start.sh <skill-name> <skill-version>` and supplies `PAOS_SKILL_NAME` and
  `PAOS_SKILL_VERSION` to rendered dataflows and Dora process environments.

### Changed

- Forge Gateway selection now comes only from one explicitly started, healthy installed Skill
  Runtime; static `forge.enabled`, `forge.baseUrl`, and `forge.apiVersion` selectors are rejected.
- Runtime state uses schema v2 so Runtime/Gateway identities, Session references, task bindings,
  and force-stop audit records are mandatory and stable across restarts.
- Action admission persists a PAOS-generated caller ID and intent before the remote request.
  Timeouts and unknown results cannot trigger an automatic POST retry.
- Runtime stop and switching account for active invocations, Sessions, and task bindings; forced
  stop records an audit event.
- Resource Registry Skill lookup uses the name endpoint. `paos skill install --version` validates
  the downloaded manifest as a client-side constraint before Node resolution and installation
  commit; schema-v3 static indexes retain version selection.
- Runtime environment identity now covers the selected dataflow path and profile file digests, so
  configuration edits and dataflow-path changes rematerialize the environment.
- Expanded the bilingual integration guide with Bundle packaging, local validation, immutable
  Node/Bundle publication order, and Registry acceptance guidance.

### Fixed

- Forge Node downloads accept Registry responses that omit duplicate digest and size fields. The
  verified Skill lock remains the digest authority, while the direct-download endpoint supplies
  the content length before the archive is downloaded and checked.
- Documented the Dora CLI v0.4.1 and `dora-message` v0.7.0 Forge Skill compatibility baseline,
  version-pinned installation methods, PATH and lifecycle checks, and RuntimeManager's automatic
  local Dora service startup.
- Startup-hook failures, missing Bash, and execution errors now persist a `failed` lifecycle state
  and diagnostic log before Dora can start, rather than leaving stale or unstarted state.
- Start, stop, install/update commit, and removal now use a non-blocking cross-process lock per
  Skill, preventing overlapping lifecycle mutations while allowing automatic release on process
  exit.

### Removed

- Removed the concrete Forge Skill, simulation profile, and remote bundle-fetch helper from the
  PhyAgentOS distribution. Forge Skills and their nodes, models, and assets are installed
  independently when required.

### Security

- Skill and Node downloads require exact size and SHA-256 metadata, archive extraction remains
  bounded and link-safe, and mutations require task ownership plus live binding revalidation.
- Unknown remote effects retain Runtime safety guards until explicit operator resolution.

## [v0.2.2] - 2026-08-21

PhyAgentOS now uses one Forge Query/Action Tool API execution plane while retaining Agent verification, experience, evolution, and the existing general-purpose tool platform.

### Added

- Added the AgentTask lifecycle tools `forge_task_create`, `forge_task_get`, `forge_task_begin_revision`, `forge_task_finalize`, and `forge_task_cancel` with one global non-terminal task, immutable PlanRevisions, bound Query records, Action invocation references, evidence, and aggregate verification.
- Added the Forge Tool API tools `forge_tool_context`, `forge_tool_query`, `forge_tool_start_action`, `forge_tool_action_status`, `forge_tool_action_result`, and `forge_tool_cancel_action` for bound and unbound Query/Action calls.
- Added the manifest-v2 Skill Runtime, catalog, archive validation, transactional installation, persistent runtime state, Resource Registry support, and `paos skill` / `paos forge-node` lifecycle commands.
- Added the built-in `move-arm-by-ee` v0.2 Skill with a MuJoCo profile, relative-pose Query, motion Action, gripper Action, ToolSpecs, and independently locked Forge nodes.
- Added backward-compatible AgentTask, PlanRevision, ToolInvocation, and attempt references to task experience and evolution records.

### Changed

- Robot execution now follows `AgentTask-bound or unbound call → ForgeToolClient → Gateway /tools → ToolInvocation → ToolEndpoint → Dora/robot`; operation `max_concurrency` remains the execution concurrency authority.
- Task verification now aggregates all calls bound to one AgentTask. A recovery verdict appends a bounded PlanRevision to the same task and continues through the existing verification and evolution policies.
- Skill discovery now combines workspace, installed, and built-in Skills. A healthy active Runtime contributes availability and its manifest `gateway_url` takes precedence over `forge.baseUrl`.
- `ForgeConfig` now represents `forge-tool-api.v1`; Resource Registry configuration is available through `resourceRegistry.url` or `PAOS_RESOURCE_REGISTRY_URL` and never triggers an implicit unconfigured download.
- Existing Agent tools, dynamic MCP tools, verification contracts, experience storage, evolution storage, and Skill activation remain available with their existing contracts.

### Removed

- Removed the PAOS Forge Session execution path and the seven Session-specific Agent tools: `forge_execute_task`, `forge_get_session`, `forge_cancel_session`, `forge_get_context`, `forge_reset`, `verify_forge_session`, and `create_replanned_forge_session`.
- Removed the built-in `pipergo2-demo`; `move-arm-by-ee` is the maintained robot Skill example.

### Fixed

- Cancellation acceptance, local timeout, and `unknown` invocation outcomes no longer imply that physical execution stopped and do not trigger blind retries.
- Skill and node installation now verifies SHA-256 metadata, blocks path traversal and unsafe links, validates locked node digests, and rolls back incomplete replacements.

### Security

- Runtime artifacts require verified size and digest metadata before installation; archive extraction is bounded and atomic, and no Registry download occurs without explicit configuration.

## [v0.2.1] - 2026-08-14

PhyAgentOS can turn verified Forge task outcomes into scoped, auditable workflow experience and supply activated Skill Lessons to verification as bounded, non-authoritative advice without changing the Forge execution path.

### Added

- Added explicit `activate_skill(name, role)` activation with one primary Skill, optional supporting Skills, applicable scoped Lessons, and task-to-Skill attribution.
- Added versioned task-outcome, episode, assessment, Skill candidate, failure observation, Lesson cluster, abstraction-validation, and scoped-Lesson contracts.
- Added a crash-safe SQLite WAL experience ledger, asynchronous reflection jobs, structured evolution events, Skill revision history, and generated per-Skill Lesson projections.
- Added guarded Skill creation/update after independent semantic-success support, including managed workflow blocks, workspace overrides for built-in Skills, reload validation, atomic writes, and rollback.
- Added workflow-related failure eligibility, normalized observation clustering, independent root-lineage support, Lesson synthesis, and abstraction validation.

### Changed

- Skill summaries now direct the Agent to activate a matching workflow before tool execution when evolution is enabled; direct `SKILL.md` reads are not treated as activation.
- Learned Lessons are loaded dynamically with the activated Skill. The root `LESSONS.md` remains available as legacy/human-authored material but is no longer injected globally while evolution is enabled.
- Forge verification uses the active scoped Lessons frozen with the root task's explicit Skill activations. Evolution mode never reads root `LESSONS.md` for automatic verification or review, and tasks without an activated Skill receive no learned Lesson context.
- Verifier prompts treat Lessons as untrusted, non-authoritative workflow advice that cannot establish criterion status, replace execution evidence, or appear as evidence references.
- Failures caused by unsatisfiable tasks, verifier/evidence limits, infrastructure, user constraints, or uncertain attribution remain diagnostic-only.
- Built-in Skills remain immutable; promoted revisions are written as workspace overrides and only the PAOS-managed workflow block is replaced on later updates.

### Security

- Experience records redact endpoint-, credential-, path-, executable-ID-, and action-assignment-shaped data and persist only workflow structure, input field names, opaque evidence references, and immutable record references.
- Lesson and Skill policies reject task-specific answers, fixed coordinates/values, credentials, endpoints, Gateway IDs, Action Manifest copies, prompt injection, and instructions that bypass Forge or verification.
