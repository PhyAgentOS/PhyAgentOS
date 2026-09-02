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
- 当前没有 YOLO/Ultralytics 检测器、真实相机感知、抓取模型或机器人执行器接入；`grasp.propose` 仍是
  provider-neutral 候选契约，Fake provider 结果不代表检测或抓取完成；
- Skill Runtime、Bundle、binding、AgentTask、verification 和 experience 基础；
- 已修正 RoboTwin 不应绑定 Skill 的文档边界。

当前尚未具备：

- generic capability runtime 的 Gateway HTTP/Dora 生产 wiring、持久化 invocation backend 和完整 Action
  executor（当前仅有无仿真依赖的 in-process foundation）；
- RoboTwin20 `EnvironmentAdapter`；
- 真实 Gateway/ToolEndpoint HTTP server；
- RoboTwin 对应 Dora flow、locked Node 和 profile；
- 六个真实能力的 PAOS 端到端验证。

因此不能声称“六个 RoboTwin Skill 已接入”，也不能把 RoboTwin 的 ground truth 称为真实感知。准确表述是：

> PAOS 公共能力契约、`pick-place-workflow` 编排和验证骨架已完成；Hephaestus 的真实能力只能作为
> clean-room 重构的需求/行为参考；新的、环境可替换的 capability runtime、真实传感器感知 Port
> 和 RoboTwin adapter 仍需按本文顺序独立实现。

## 12. English summary

The migration must be a clean reimplementation of the capability boundary, not a code copy from Hephaestus.
Keep six stable provider-neutral ToolSpecs under one clearly named `pick-place-workflow` Skill. PAOS v1.0
still requires an independent generic capability runtime: implement generic ToolEndpoint semantics against
abstract provider ports, and place RoboTwin 2.0, SAPIEN, task, embodiment, benchmark, and simulator details in
a separate environment adapter selected by profile. Simulation actor/entity truth, segmentation, metadata, and
`check_success()` are comparison/acceptance facts, not real-world perception. Real deployment must use sensor
artifacts and replaceable perception providers. The same Skill and ToolSpecs must remain usable with RoboTwin,
ManiSkill, replay, or future hardware profiles.
