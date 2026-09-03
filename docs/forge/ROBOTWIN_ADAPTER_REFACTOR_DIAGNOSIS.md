# RoboTwin Adapter Refactor Diagnosis

> 诊断日期：2026-09-02
> 适用基线：PAOS v1.0.0、Forge Tool API、当前 `feature/long-horizon-workflow` 分支

## 1. 结论

Hephaestus 中已有观察、场景理解、抓取候选、几何准入、获取和放置等真实能力，但本次迁移不应把
Hephaestus 源码复制到 PAOS，也不应把六个 ToolEndpoint 全部放入一个 RoboTwin 专属 workspace。

正确目标是：保留 PAOS 的 provider-neutral ToolSpec，在独立的 capability runtime 中实现通用 ToolEndpoint
语义，以抽象 provider port 调用环境实现；RoboTwin 2.0 只是一个可替换的 `EnvironmentAdapter` profile。

```text
ForgeToolClient
  → Generic Gateway Tool API
  → Generic ToolEndpoint
  → Capability Runtime
  → Provider Port
  → EnvironmentAdapter(profile=robotwin20|maniskill|replay|...)
  → Dora
  → robot/simulator
```

这样同一组 ToolSpec、`pick-place-workflow` Skill workflow、AgentTask、verification 和 experience 可以跨 RoboTwin、ManiSkill、
回放或其他环境复用。

这里的“复用”不意味着把仿真器的内部真值当成感知结果。RoboTwin/SAPIEN 的 actor/entity 列表、
segmentation、object metadata、精确 pose 和 `check_success()` 都是仿真内部事实，只能用于仿真调试、
对照或验收证据；它们不能填充面向真实物理世界的 observation/understanding 输出，也不能授予动作准入。
真实世界的观察必须来自相机、深度、力/触觉或其他明确声明的传感器，场景理解必须由独立的 perception
provider 从这些观测 artifacts 推断，并保留传感器 provenance、时间戳、frame 和 calibration。

## 2. 规范依据

- [PAOS framework introduction](../en/01-framework-introduction.md#2-one-physical-execution-plane)：认知规划、
  Gateway 执行、ToolEndpoint/Dora/robot-simulator 物理链路分离；RoboTwin 位于末端 runtime。
- [PAOS developer manual](../en/03-developer-manual.md#12-extension-workflows)：先发布 provider-neutral
  ToolSpec，再实现 ToolEndpoint/Fake Gateway、adapter、Bundle/profile 和仿真验收。
- [Integration development guide](../user_development_guide/README_en.md#1-choose-the-integration-point)：
  机器人能力使用 Gateway Query/Action/Session ToolSpec + ToolEndpoint；仿真器参数留在 adapter/profile。
- [Forge Tool API contract](README.md#1-execution-boundary)：Gateway 是物理执行 owner；PAOS 保存 binding、
  task 和验证语义，不接管物理真值。
- Hephaestus 外部参考：`/home/yanxu/Hephaestus/docs/adr/0003-tool-embodiment-environment-adapter-boundaries.md`
  （当前仍为 proposed）：环境差异由 `CapabilityProfile`/`EmbodimentAdapter`/`EnvironmentManager`
  持有，canonical runtime 保持 admission、safety、execution 和 physical truth 的唯一所有权。

## 3. 术语和所有权

| 概念 | 责任方 | 不应承担的职责 |
|---|---|---|
| Skill (`pick-place-workflow`) | PAOS SkillsLoader/Skill Runtime | 只描述六步通用工作流；不包含 RoboTwin task、SAPIEN API、仿真真值或控制器代码 |
| ToolSpec | PAOS/Forge contract | 不暴露 provider、embodiment 或 benchmark 字段 |
| Generic ToolEndpoint | capability runtime/Gateway | 不直接解析某个仿真器对象 |
| Provider Port | capability runtime | 不拥有 HTTP、AgentTask 或 Skill 生命周期 |
| EnvironmentAdapter | 独立环境 runtime | 只管理环境生命周期和 Port 实现；不得把仿真真值伪装成真实感知或改变公共 ToolSpec/PAOS task/verdict |
| Gateway | 执行面 | 不定义用户级任务成功 |
| AgentTask | PAOS | 不直接执行机器人或仿真器 |
| Verification | PAOS | 不把 simulator `check_success()` 单独当作用户级 verdict |

## 4. 被否定的布局

以下布局不采用：

```text
paos-robotwin-adapter/
└── endpoints/
    ├── scene_observe.py
    ├── scene_understand.py
    ├── grasp_propose.py
    ├── manipulation_prepare.py
    ├── object_acquire.py
    └── object_place.py
```

问题不是目录名称本身，而是六个公共能力的实现边界会被 RoboTwin 任务和 API 牵引，最终产生：

1. `scene.observe` 等公共能力与 RoboTwin 绑定；
2. 未来 ManiSkill、replay、其他 simulator 重复实现相同 ToolEndpoint；
3. Skill、ToolSpec、Gateway 和环境配置发生语义泄漏；
4. 通过修改 tool_id 或 Skill 名称表达环境选择；
5. PAOS Agent 需要知道 provider-specific payload。

## 5. 目标分层

### 5.1 Public contract

保留六个稳定 ToolSpec：

```text
scene.observe          Query
scene.understand       Query
grasp.propose          Query
manipulation.prepare   Query
object.acquire         Action
object.place           Action
```

ToolSpec 只冻结 schema、binding、frame/unit、readiness、错误和生命周期语义。

### 5.2 Generic capability runtime

通用 runtime 可以按能力组织模块，但模块不能导入 RoboTwin 或 SAPIEN：

```text
capability_runtime/
├── observation.py
├── understanding.py
├── grasp_proposal.py
├── manipulation_preparation.py
├── acquire.py
└── place.py
ports/
├── observation_source.py
├── scene_understanding.py
├── grasp_provider.py
├── readiness_evaluator.py
└── manipulation_executor.py
```

这些模块负责公共输入验证、结果投影、provenance、错误分类、Query/Action 生命周期和 no-blind-retry
语义。

### 5.3 Environment adapter

环境适配器只实现 Port 和环境生命周期：

```text
environment_adapters/
├── robotwin20/
│   ├── environment.py
│   ├── observation_source.py
│   ├── scene_state.py
│   ├── embodiment.py
│   └── profile.yaml
├── maniskill/
└── replay/
```

RoboTwin task、SAPIEN scene、embodiment、benchmark、camera 名称和内部句柄都留在
`environment_adapters/robotwin20` 及其 profile。adapter 可以读取这些事实来驱动仿真和产生
对照证据，但公共 `scene.observe`/`scene.understand` 必须经过真实传感器/感知 Port；不得直接把
actor/entity、segmentation 或 object metadata 当作现实感知结果。

## 6. 六个能力的重构 seam

| ToolSpec | 通用 runtime 重新实现 | 环境 Port |
|---|---|---|
| `scene.observe` | freshness、frame、calibration、artifact、scene revision、结果 schema | `ObservationSource.capture()` |
| `scene.understand` | entity/relation schema、confidence、provenance、observation binding | `SceneUnderstandingProvider.understand()` |
| `grasp.propose` | candidate-set identity、候选规范化、绑定和 provenance | `GraspProposalProvider.propose()` |
| `manipulation.prepare` | workspace/kinematic/collision 三项结果编排、prepared 语义 | `ReadinessEvaluator.evaluate()` |
| `object.acquire` | Action admission、invocation、phase summary、cancel/unknown | `ManipulationExecutor.acquire()` |
| `object.place` | destination binding、release/retreat、post-release evidence | `ManipulationExecutor.place()` |

`scene.observe`、`scene.understand`、`grasp.propose`、`manipulation.prepare` 都保持 Query；只有
`object.acquire` 和 `object.place` 创建标准 Action invocation。

## 7. Hephaestus 的使用边界

Hephaestus 代码不作为新 runtime 的依赖，也不直接复制到 PAOS。可使用的只有：

- 已验证行为和输入输出语义；
- failure family、safety gate 和证据要求；
- 现有测试揭示的边界条件；
- RoboTwin/ManiSkill 运行实验作为验收参考。

不得直接依赖或搬运：

- Hephaestus `ToolRegistry`；
- `ManiSkillBackend` 私有执行路径；
- `AcquireObjectExecutor`/`RelocateObjectExecutor` 类实现；
- Hephaestus receipt、state store 或 CLI execution path；
- Hephaestus provider-specific payload。

新实现必须通过 PAOS ToolSpec 和独立 adapter contract 验证，而不是通过“旧代码可运行”证明兼容。

## 8. Skill 和 profile 设计

推荐使用名为 `pick-place-workflow` 的 provider-neutral workflow Skill，内部声明六个 ToolSpec：

```yaml
required_tools:
  - scene.observe
  - scene.understand
  - grasp.propose
  - manipulation.prepare
  - object.acquire
  - object.place
```

环境通过 profile 选择，Skill 名称不随环境变化：

```text
pick-place-workflow + profile=robotwin20
pick-place-workflow + profile=maniskill
pick-place-workflow + profile=replay
```

禁止使用以下模式：

```text
robotwin2-pick-place-workflow
maniskill-pick-place-workflow
robotwin_grasp_propose
```

如果第一阶段只有 `scene.observe`，必须使用 `required_tools: [scene.observe]` 的中性 Bundle/profile，
不能把单能力 runtime 塞进当前声明六个 required Tools 的 Bundle。

## 9. 推荐实施顺序

1. **冻结 ToolSpec**：从现有 PAOS contracts 建立 schema、binding、readiness 和 failure matrix。
2. **先写 Fake Gateway conformance**：覆盖 discovery、context、Query/Action route、identity、unknown、
   cancel/stop、并发和 no-blind-retry。
3. **实现 generic capability runtime**：不连接任何仿真器，先完成六个 ToolEndpoint 的公共生命周期。
4. **定义 EnvironmentAdapter Port**：只包含 reset/seed/snapshot、observation、scene state 和经过验证的
   execution seam，不泄漏 PAOS task 或 provider payload。
5. **实现 RoboTwin20 adapter**：在独立 `RoboTwin20` 环境中接入 task、SAPIEN、camera 和 embodiment；不修改
   PAOS ToolSpec。仿真 actor/entity、segmentation、object metadata 和内部 pose 只作为仿真辅助/对照事实。
6. **先打通真实传感器 observation**：`scene.observe` 只做 Query，验证 camera/depth/state 传感器输出、frame、
   calibration、freshness 和 artifact；不得用仿真 ground truth 代替传感器观测。
7. **依次接入 understand、propose、prepare**：每个能力先 adapter 单测，再真实 Gateway conformance。
8. **最后接入 acquire/place**：沿用标准 Action invocation/status/result/cancel，内部 phase 不暴露给 Agent。
9. **添加 Dora profile 和 locked Node**：Bundle 只冻结 wiring、profile、Node artifact 和 digest。
10. **完整仿真验收**：记录 RoboTwin commit、SAPIEN/Dora 版本、Bundle/Node digest、profile 和环境摘要。

### 9.1 两条感知接入方案的统一决策

前述单视角链路和多视角融合不是两个 Skill，也不是两个 RoboTwin 专属 Tool。它们共享 PAOS 的
`scene.observe`、`scene.understand`、`grasp.propose` 和 `manipulation.prepare` contract；差异只由
adapter/provider profile 和 capability negotiation 表达。Agent 不传 `LocateAnything`、`SAM2`、
`NVBlox` 或具体模型名，也不直接选择摄像头实现。

#### 方案 A：单视角局部感知（默认首个实现）

```text
scene.observe(sensor_ref, max_age_ms)
  -> entity binding / semantic query
  -> LocateAnything proposal (2D boxes)
  -> SAM2 mask materialization (当前 RGB)
  -> depth + intrinsics/extrinsics localization
  -> entity spatial envelope / optional pose artifact
  -> grasp.propose
  -> manipulation.prepare
```

适用条件：目标主要可见、单个 RGB-D 视角足够、需要较低延迟或 GPU 资源有限。它在一个 observation
  上完成局部实体证据，输出 `entities`、`relations`、`spatial_envelopes`；派生 mask/pose artifact
  目前只能作为 adapter 内部引用，待 generic runtime 的 derived-artifact contract 冻结后再作为公共
  结果投影。不输出仿真 actor identity，不直接产生抓取动作。

adapter 需要实现三个独立 port：

```python
class ProposalProvider(Protocol):
    def propose(self, request: ProposalRequest) -> ProposalBatch: ...

class SegmentationProvider(Protocol):
    def segment(self, request: SegmentationRequest) -> MaskBatch: ...

class MetricLocalizationProvider(Protocol):
    def localize(self, request: LocalizationRequest) -> SpatialEstimate: ...
```

LocateAnything 和 SAM2 的 worker 生命周期、Torch/CUDA、模型 revision、license、临时文件和 cleanup
只在 adapter 中管理。PAOS 只校验 artifact、frame、calibration、provenance 和结果 schema。

#### 方案 B：多视角观测集与几何融合（遮挡/覆盖需要时启用）

```text
scene.observe(observation_set_ref, max_age_ms)
  -> MultiViewObservationSet
  -> per-view proposal/mask (可复用方案 A provider)
  -> cross-view identity / mask correspondence gate
  -> fused entity mask + RGB-D geometry
  -> scene.understand projects entity evidence
  -> grasp.propose consumes fused entity geometry
  -> optional global SceneGeometry for manipulation.prepare
```

适用条件：单视角遮挡、视野覆盖不足、需要更完整的目标分割、实体点云、抓取几何或全局碰撞/unknown-space
几何。多视角不仅可以改善全局地图，也可以直接改善目标分割感知：每个视角可独立产生 proposal/mask，
或由一个视角的已绑定 proposal 投影到其他视角，再通过跨视角 identity/correspondence gate 合并为同一实体
的 mask 与 RGB-D 几何。多视角必须先形成 provider-neutral `MultiViewObservationSet`，每个 view 绑定同一
`scene_revision`、reset/control-step identity、timestamp、camera frame、intrinsics、extrinsics 和 artifact digest。

多视角 provider 至少可以产生两类可分别消费的输出：

| 输出 | 消费者 | 语义 |
|---|---|---|
| `FusedEntityPerceptionArtifact` | `scene.understand`、`grasp.propose` | 某个已绑定实体的跨视角 mask、对应关系和融合 RGB-D 点云；可用于抓取候选，但不能升级为全局碰撞图 |
| `GlobalSceneGeometryReference` | `manipulation.prepare` / planner | 完整 RGB-D 视图积分后的场景几何、自由空间和 unknown-space 证据；不是目标分割结果 |

上述两个名称是拟议的 provider-neutral artifact 类型，不是当前已发布的 Tool 输入字段。当前
`scene.understand` 没有 `derived_artifacts`，`grasp.propose` 只接受带 `spatial_envelope` 的 target，
`manipulation.prepare` 也没有 `GlobalSceneGeometryReference` 输入；在这些 generic contract 扩展前，
融合结果只能留在 adapter/provider 内部，不能伪装成现有 ToolResult 或私自增加请求字段。

多视角感知 provider 可以复用方案 A 的 LocateAnything/SAM2：LocateAnything 仍只产生 proposal，SAM2
仍只产生当前视角 mask；跨视角的实体 correspondence、mask 合并、深度投影和点云融合由 adapter-side
composition provider 负责。不能把每个实体 mask 的并集当成全局 SceneGeometry；全局几何必须消费完整
depth frames 和标定后的射线。provider 需实现有序
`begin_session → process(view_i) → fuse_entity → (optional) freeze_global_snapshot → close_session`
生命周期，任何 view 丢失、revision/calibration 不一致、identity/mask correspondence 不确定、
session/digest/count 不匹配都必须 fail-closed。

#### 方案选择与迁移顺序

1. 先实现方案 A 的 Fake provider 和单视角真实 adapter，验证 proposal、mask、depth localization、
   provenance 和 `scene.understand` 投影。
2. 当单视角在遮挡、分割质量或 coverage gate 上不足时，再增加方案 B 的 `MultiViewObservationSet`
   contract；保持单视角调用兼容，不复制 ToolEndpoint。
3. 先实现跨视角 identity/mask correspondence 和 `FusedEntityPerceptionArtifact`，供
   `scene.understand` / `grasp.propose` 使用；再按需要实现全局 SceneGeometry 供 `manipulation.prepare`
   使用，二者分别验收，不能用一个 artifact 代替另一个。
4. 若多视角需要移动相机或机器人采集新视角，该动作必须另行经过 Gateway/Runtime safety admission；
   provider 不能隐式移动硬件。
5. 两个方案都必须保持 `motion_authorized=false`，直到标准 `manipulation.prepare` 和后续 Action
   admission 完成；模型成功、mask 成功或融合成功本身都不是抓取成功。

#### 方案对照与验收门禁

| 维度 | 方案 A：单视角 | 方案 B：多视角 |
|---|---|---|
| PAOS 对外入口 | 现有 `scene.observe` + `scene.understand` | 未来扩展同一入口为 capability-gated observation set；当前尚未注册多视角字段 |
| 主要结果 | 当前视角实体/mask/空间包络 | 跨视角实体分割/几何 + 可选全局 SceneGeometry |
| 主要风险 | 遮挡、深度空洞、单视角身份歧义 | 跨视角身份漂移、mask correspondence 错配、标定/时间不一致、资源占用 |
| 必须证明 | RGB/depth 对齐、mask shape、frame/calibration/provenance | view identity、顺序、digest、integration count、单次 freeze |
| 失败语义 | provider unavailable/invalid，不能伪造 3D | typed multi-view unavailable/mismatch，不能静默降级单视角 |
| 动作权限 | 始终无动作 | 始终无动作 |

本仓库当前应按方案 A 先行：GPT provider 只覆盖 RGB 语义理解，下一步接入真实 mask 和 depth
localization；方案 B 作为同一 provider-neutral contract 上的增量 capability，待单视角 contract
和 artifact lineage 稳定后再实现。方案 B 的第一目标是跨视角分割/实体几何可被 `grasp.propose` 消费，
全局 SceneGeometry 是独立的后续输出。两者都不应命名为 `robotwin.multiview` 或 `multiview-skill`。

### 9.2 按 PAOS 架构与开发者指南的审核结论

**通过项：**

- 两个方案都沿用 `ForgeToolClient → Gateway Tool API → ToolEndpoint → Dora → adapter/provider`，没有
  direct Agent-to-model、Agent-to-Dora 或 Agent-to-SDK 路径。
- 按开发者指南“只有现有通用 Tool 无法表达能力时才新增 Agent tool”的规则，多视角目前可以表达为
  `scene.observe` 的 capability-gated observation set 和 provider 内部 composition，因此没有新增
  `multiview` ToolSpec 或 Skill。
- 多视角没有被命名为 Skill，也没有把 LocateAnything、SAM2、NVBlox、FoundationPose 写入公共
  `ToolSpec`；环境差异仍由 adapter/profile 和 capability descriptor 表达。
- 单视角和多视角都把感知、几何、准入、执行分开；mask/点云/融合结果只能作为 Query 证据，不能
  跳过 `grasp.propose`、`manipulation.prepare` 或 Action admission。
- 方案 B 明确区分跨视角实体分割/几何与全局 SceneGeometry，前者可以供 `grasp.propose` 生成抓取
  候选，后者才供规划/准入使用；不能互相替代。

**必须先补齐的 contract 缺口：**

1. 当前 `scene.observe` 只接受单个 `sensor_ref`，尚未实现 `MultiViewObservationSet`。在增加多视角
   调用前，应先冻结兼容的 provider-neutral schema（ordered view refs、scene/reset/control-step identity、
   per-view frame/calibration/artifact digests），并通过 Fake Gateway conformance；不能在 adapter 中
   私自增加未注册字段。
2. 当前 `scene.understand` 的公共 snapshot 只有 `entities`、`relations`、`spatial_envelopes` 和
   `ambiguities`，没有 `derived_artifacts` 字段。若要让融合 mask 被后续 `grasp.propose` 审计，必须先
   在 PAOS generic runtime 定义并校验派生 artifact contract；在此之前，mask 只能作为 adapter 内部输入，
   不能假装已经是公共 ToolResult。
3. 当前 `provenance` 正则只接受 `artifact://...`。`calibration://...` 应继续放在顶层
   `calibration_ref` 或一个明确的 calibration artifact ref 中，不能直接塞进现有 spatial-envelope
   provenance，否则会被 PAOS validator 拒绝。示例中的 calibration 绑定必须按此规则实现。
4. `scene.understand`、`grasp.propose` 当前都是 Query；多视角 provider 不得隐式移动相机/机器人。需要
   主动移动采集时，必须另行定义并审核一个有安全准入的 observation Action/Session。
5. 当前 `grasp.propose` 的 target 只允许 `spatial_envelope`，`manipulation.prepare` 没有全局场景几何输入。
   若要让融合实体几何或 `GlobalSceneGeometryReference` 成为公共证据，必须先扩展通用 artifact/reference
   schema、binding、provenance 和 Fake Gateway conformance；否则只能由 adapter 将已验证结果投影为现有
   中性 envelope，且不得把全局几何或 mask 并集冒充目标/碰撞事实。

**实施门禁：**

- 先以 Fake provider 证明单视角：proposal→mask→depth localization→entity artifact→grasp candidate
  的 lineage 和 fail-closed 语义。
- 再以 Fake provider 证明多视角：两视角以上、稳定顺序、同一 revision/calibration、跨视角 identity/mask
  correspondence、融合 artifact digest，以及失败时不静默降级为单视角。
- 然后在独立 RoboTwin adapter 环境接入真实 LocateAnything/SAM2 worker；PAOS 环境不安装 Torch、CUDA、
  模型或仿真依赖。
- 只有真实多视角 artifact、provider receipt、资源/cleanup 证据和 Gateway/Dora readiness 全部存在后，
  才能进行仿真验收；任何阶段都保持 `motion_authorized=false`，不把分割或融合成功称为抓取成功。

## 10. 验收门禁

### 公共 contract gate

- ToolSpec 严格 schema 与 binding 通过；
- `/tools`、`/context` 可发现；
- Query/Action/Session 使用 PAOS 标准路由；
- invocation/attempt 与 PAOS task_id 分离；
- timeout/unknown 不盲目重发；
- cancel/stop 不虚构物理停止。

### 环境 gate

- `pick-place-workflow` Skill 名称与 ToolSpec 保持环境无关；RoboTwin 通过 profile 选择；
- RoboTwin task 可以在 `RoboTwin20` 环境启动；
- 需要的 assets 已完整；
- observation source 能读取真实 RGB/depth/state 传感器输出；仿真真值仅作为独立对照，不进入公共感知结果；
- frame、calibration、scene revision 可确定；
- adapter 不向 PAOS 暴露 RoboTwin 私有字段；
- acquire/place 只有显式 Action admission 后才能执行。

### Runtime gate

- Dora flow 可由 RuntimeManager 启动；
- Gateway `/tools` ready；
- 全部 `required_tools` contexts ready；
- Bundle/Node digest 可复核；
- 从干净 PAOS 环境完成 install/start/status/stop；
- 真实仿真结果与 PAOS ToolResult、evidence、verification 记录可对齐。

## 11. 当前审核结论

当前 PAOS 仓库已经具备：

- 六个 provider-neutral ToolSpec；
- 一个职责明确的 `pick-place-workflow` Skill，用于编排六个 Tool，而不是把六个能力误称为六个 Skill；
- Fake Gateway 和 no-motion conformance；
- v1.0 所要求的独立 generic capability runtime 基础实现：ToolEndpoint 注册、发现/context、Query 分发、
  bounded Action invocation bookkeeping 和 provider-port 协议；该实现不依赖仿真器、YOLO、机器人 SDK、Dora
  或硬件，且不执行物理运动；
- 当前没有 YOLO/Ultralytics 检测器、抓取模型或机器人执行器接入；`grasp.propose` 仍是
  provider-neutral 候选契约，Fake provider 结果不代表检测或抓取完成。真实场景理解的
  adapter-side GPT Responses provider 已按 clean-room 方式实现：它只读取外部 observation artifact，
  输出闭合的 entities/relations/spatial_envelopes/ambiguities schema，并由 PAOS Gateway 做最终校验；
  provider 默认沿用 Hephaestus 已验证的 `gpt-5.6-sol`、Responses API 和 relay base URL，但不导入
  Hephaestus。当前已用外部 `CUSTOM_API_KEY` 完成真实 GPT 路径验收；RGB-only 输入返回了语义实体/关系，
  没有生成 metric spatial envelope，且不确定性标记被保留。由于请求没有 depth/calibration，metric 几何仍按
  contract 不可用，不能把模型的 2D 视觉判断当作 3D 定位。
  strict schema 中 `unit` 也已声明 `type: string`，避免 Responses API 在请求阶段拒绝 schema；
- 独立 `examples/forge-adapters/robotwin20` adapter/runtime：环境 reset/snapshot seam、注入式
  `RoboTwinSensorBackend`、camera/depth/state artifact 校验、`RoboTwinObservationProvider` 和
  provider-neutral `scene.observe` snapshot；外部 RoboTwin20 Python 3.10 runtime 已完成一次无动作
  RGB/depth/state capture。该包不进入 PAOS wheel、不依赖 RoboTwin/SAPIEN/Torch/YOLO，也不复制仿真资产；
- Skill Runtime、Bundle、binding、AgentTask、verification 和 experience 基础；
- 已修正 RoboTwin 不应绑定 Skill 的文档边界。

当前尚未具备：

- generic capability runtime 的 Gateway HTTP/Dora 生产 wiring、持久化 invocation backend 和完整 Action
  executor（当前仅有无仿真依赖的 in-process foundation）；
- RoboTwin20 到真实 Gateway/Dora 的跨进程 provider wiring（当前 runtime-only CLI 和 in-process
  provider conformance 已完成，但尚未启动生产 HTTP Gateway）；
- 真实 Gateway/ToolEndpoint HTTP server；
- RoboTwin 对应 Dora flow、locked Node 和 profile；
- `grasp.propose`、`manipulation.prepare`、`object.acquire`、`object.place` 的真实 provider 接入与六能力
  PAOS 端到端验证；当前 GPT provider 只覆盖 RGB 语义理解，尚未覆盖真实分割和 metric 3D 定位。

因此不能声称“六个 RoboTwin Skill 已接入”，也不能把 RoboTwin 的 ground truth 称为真实感知。准确表述是：

> PAOS 公共能力契约、`pick-place-workflow` 编排、generic capability runtime 基础、RoboTwin
> `scene.observe` runtime/provider conformance，以及 adapter-side `scene.understand` GPT provider
> 已完成；Hephaestus 的真实能力只作为 clean-room 重构的需求/行为参考。当前尚缺真实分割/深度定位、
> `grasp.propose` 及后续准备/执行 provider、Gateway HTTP/Dora wiring，必须继续按本文顺序独立实现。

## 12. 识别、分割、定位与抓取位姿的模块归属

这些是实现能力，不是新增 Skill，也不应通过 `robotwin2-*` 命名绑定到仿真环境。PAOS 对外仍只暴露六个
稳定 ToolSpec；模型、相机 SDK、点云库和 RoboTwin/SAPIEN 句柄留在 adapter/provider workspace。

| 后续能力 | 对外 ToolSpec | PAOS generic capability runtime | adapter/provider 实现 |
|---|---|---|---|
| RGB/depth/state 采集 | `scene.observe` | observation identity、freshness、frame、calibration、artifact 绑定 | `ObservationSource` / `EnvironmentAdapter` 读取真实传感器 |
| 目标识别/检测 | `scene.understand` | entity schema、confidence、provenance、observation binding | detector/VLM provider；不能使用 actor truth |
| 实例分割 | `scene.understand` | 校验并投影 opaque mask artifact 与 provenance | 独立 segmentation provider（YOLO/SAM 等），不使用仿真 segmentation truth |
| 3D 定位 | `scene.understand` | frame/unit/calibration 约束和 metric envelope 校验 | depth + calibration + mask/点云 localization provider；缺任一项 fail-closed |
| 多视角分割/实体几何融合 | `scene.understand` → `grasp.propose` | 校验 `MultiViewObservationSet`、跨视角 identity/mask lineage 和派生 artifact 引用 | per-view proposal/segmentation + correspondence/fusion provider；可输出融合 mask、点云和抓取几何 |
| 抓取位姿估计 | `grasp.propose` | candidate schema、候选集 identity、provenance 与 funnel | 独立 grasp proposal provider（可选 YOLO/GraspGen 等），只产候选，不授权动作 |
| IK/碰撞/工作空间准入 | `manipulation.prepare` | readiness 编排与 `motion_authorized=false` 边界 | `ReadinessEvaluator`，必须在执行前完成 |
| 实际抓取/放置 | `object.acquire` / `object.place` | Action admission 与 invocation 生命周期 | `ManipulationExecutor`；仅 Gateway 显式准入后执行 |

当前 GPT provider 只做 RGB 语义理解：它能生成实体和关系，但不能凭 RGB 生成可信分割 mask 或 metric
3D 坐标。下一步应先扩展 adapter-side typed artifact resolver 和真实 segmentation/depth localization
provider，再通过同一个 `scene.understand` contract 接入；抓取位姿单独接入 `grasp.propose`，不能塞进
`scene.observe` 或 `scene.understand` 的输出字段。

## 13. English summary

The migration must be a clean reimplementation of the capability boundary, not a code copy from Hephaestus.
Keep six stable provider-neutral ToolSpecs under one clearly named `pick-place-workflow` Skill. PAOS v1.0
still requires an independent generic capability runtime: implement generic ToolEndpoint semantics against
abstract provider ports, and place RoboTwin 2.0, SAPIEN, task, embodiment, benchmark, and simulator details in
a separate environment adapter selected by profile. Simulation actor/entity truth, segmentation, metadata, and
`check_success()` are comparison/acceptance facts, not real-world perception. Real deployment must use sensor
artifacts and replaceable perception providers. The same Skill and ToolSpecs must remain usable with RoboTwin,
ManiSkill, replay, or future hardware profiles.
