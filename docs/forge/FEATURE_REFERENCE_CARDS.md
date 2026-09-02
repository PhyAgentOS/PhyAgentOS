# v1.0 Feature Reference Cards

本文件规定 PAOS v1.0 后续功能如何使用官方文档作为方案、代码和验收的共同依据。它是项目开发方法，不替代任何 Forge 契约。

## 1. 规范来源的优先级

功能设计遇到冲突时按以下顺序解释：

1. `docs/en/03-developer-manual.md`：模块边界、所有权、生命周期和测试门禁。
2. `docs/forge/README.md`：Query/Action/Session、HTTP 路由、身份、binding、evidence、verification。
3. `docs/user_development_guide/README_en.md`：ToolSpec、ToolEndpoint、Bundle、Dora profile、Fake Gateway 和发布流程。
4. `docs/en/05-agent-experience-and-skill-evolution.md`：Episode、Lesson、Candidate、promotion、rollback 和归因边界。
5. `docs/user_development_guide/COMMUNICATION_en.md`：跨边界 ID、事件、WebSocket、持久化和信任规则。
6. `docs/en/04-forge-configuration-reference.md`：配置字段、verification/evolution/runtime 开关。
7. `docs/user_manual/README_en.md`：启动、监控、取消、重启和运行时排障。
8. `docs/forge/UNIFIED_TOOL_API.md` 与 `docs/en/01-framework-introduction.md`：术语速查和架构背景。

项目自己的 Hephaestus/RoboTwin ADR 只能补充“为什么这样映射”，不能覆盖 v1.0 公共契约。所有引用应锁定 `origin/main` commit 和文档版本（当前为 `c5740a5`、`1.0.0`）。

## 2. 功能引用卡模板

每个功能在进入代码实现前都应填写一张卡。卡片可以放在对应 PR 描述或项目架构文档中。

```markdown
## Feature
- Name:
- User-visible capability:
- Baseline commit:
- Documentation version:

## Normative references
- Developer Manual: section(s)
- Forge Integration Contract: section(s)
- Integration Guide: section(s)
- Configuration/Evolution/Operations: section(s), if applicable

## Selected extension point
- Query / Action / Session / ToolEndpoint / ToolSpec /
  Skill Bundle / AgentTask / ExperienceCoordinator

## Public contract
- tool_id and operation:
- input/output schema:
- semantics, frame, unit, tolerance and readiness:

## Ownership
- physical execution truth:
- task aggregation:
- evidence:
- user-level verdict:
- experience/evolution:

## Failure and recovery
- rejected inputs:
- pending/terminal/unknown behavior:
- cancel/stop behavior:
- retry and no-blind-POST rule:

## Acceptance
- discovery/context:
- valid and invalid contract cases:
- binding and identity checks:
- evidence and verification:
- Fake Gateway/conformance:
- simulation or hardware proof:
- no-motion boundary:

## Non-goals
- no direct Agent-to-SDK call
- no second execution protocol
- no capability-specific verifier
- no automatic motion authorization
```

## 3. 文档到代码的追踪

方案必须把每条重要规范映射到实现和测试，而不是只写“符合开发者指南”。推荐使用以下表格：

| 规范要求 | 规范来源 | 实现位置 | 验收证据 |
|---|---|---|---|
| Tool 声明 `query/action/session` | Developer Manual §4 | ToolSpec、Endpoint | discovery/spec test |
| Query 通过 endpoint operation 调用 | Forge Contract §3 | `forge/tool_client.py`、Gateway adapter | route test |
| Action 保留 invocation/attempt | Forge Contract §4、§7 | Tool wrapper、AgentTask record | identity test |
| 一个全局 active AgentTask | Developer Manual §5 | AgentTask store | transaction/concurrency test |
| timeout 后不得重复 POST | Forge Contract §4 | recovery path | no-POST test |
| Lesson 不能成为 evidence | Evolution §2–3 | verifier/experience boundary | attribution test |
| Bundle 和 Node 必须校验 digest | Integration Guide §4–5 | `skill_runtime/` | archive/digest test |
| Runtime stop 需考虑未终止 invocation | Operations §5–7 | Runtime manager | restart/stop test |

如果功能不需要修改某一层，应在卡片中明确标注“无影响”，避免审查者误以为遗漏。

## 4. 按功能类型选择参考文档

| 功能 | 首要文档 | 典型扩展点 |
|---|---|---|
| 感知、场景理解、候选生成 | Integration Guide §1–3、§8–10；Forge Contract §2–3 | Query ToolSpec + ToolEndpoint |
| 物理动作 | Integration Guide §1–3、§8–10；Forge Contract §4、§7–9；Operations §5–7 | Action ToolSpec + ToolEndpoint |
| 长程或有状态流程 | Forge Contract §5、§7–10；Communication §3–6 | Session + AgentTask |
| RoboTwin/仿真器接入 | Integration Guide §4–6、§9–10；Configuration §8.1、§9 | Gateway/ToolEndpoint adapter + Dora profile；Bundle 仅冻结 wiring 与制品 |
| 证据、验证、恢复 | Developer Manual §7–8；Forge Contract §8–9 | generic verification/evidence |
| Episode、Lesson、Skill 晋升 | Evolution §1–10；Developer Manual §11 | ExperienceCoordinator |

公共 Agent 代码只能看到 provider-neutral Tool API。`pick-place-workflow` 是一个完整的六 Tool 工作流 Skill，
不是只做观察的 Skill，也不是六个独立 Skill。Skill 只承载通用 ToolSpec 和工作流说明；RoboTwin 2.0
不是 PAOS 内部 provider，也不是能力名称的一部分。RoboTwin task、SAPIEN、embodiment、benchmark 和
厂商 SDK 参数由 Gateway/ToolEndpoint adapter 持有，Dora 负责运行时编排；Skill Bundle 只冻结 profile、
锁定 Node 制品及其启动 wiring，不把仿真器语义写入公共 ToolSpec 或 Skill 名称。RoboTwin 的 actor/entity
列表、segmentation、object metadata、精确 pose 和 `check_success()` 只能作为仿真内部辅助、对照或验收
事实，不能冒充真实物理世界的 observation/understanding；真实部署必须接入相机、深度、力/触觉等传感器
以及独立 perception provider，并保留 provenance、时间戳、frame 和 calibration。

## 5. 推荐实施顺序

1. 从 `origin/main` 建立功能分支，并记录 commit 和文档版本。
2. 填写引用卡，先确定语义、所有权、身份和失败状态。
3. 定义严格 ToolSpec：schema、frame、unit、tolerance、readiness 和 `max_concurrency`。
4. 用 Fake Gateway 覆盖 discovery、context、路由、错误和生命周期。
5. 先实现不依赖仿真器的 generic capability runtime（ToolEndpoint 生命周期、provider ports、结果投影和
   failure semantics）；PAOS 核心只增加确有必要的通用能力。
6. 再实现 EnvironmentAdapter/provider ports；RoboTwin、SAPIEN、task、embodiment、benchmark 和 SDK
   参数只存在于 adapter/profile。
7. 将 Tool、Node、profile 和依赖加入 manifest-v2 Bundle，并执行本地安装闭环。
8. 按需要接入 AgentTask、evidence、verification，再接入 ExperienceCoordinator。
9. 最后执行仿真或硬件验收，并记录确切 Bundle、Node digest、profile 和环境。

### 5.1 RoboTwin 2.0 接入顺序

RoboTwin 接入必须沿用 v1.0 的唯一物理路径，而不是创建一个与仿真器同名的 Skill：

```text
provider-neutral ToolSpec
  → Fake Gateway conformance
  → generic capability runtime
  → EnvironmentAdapter/provider ports
  → Dora profile / locked Node wiring
  → RoboTwin 2.0 task + SAPIEN runtime
```

PAOS 侧只通过 `ForgeToolClient → Gateway Tool API` 访问 ToolEndpoint；PAOS 不 import RoboTwin 或
SAPIEN，不直连 Dora，也不读取仿真器专有 task/embodiment/benchmark 字段。若某个能力只实现
`scene.observe`，不能把它伪装成包含其他 `required_tools` 的多能力 Bundle；应先让 Gateway
`/tools` 与声明的全部 required Tool contexts ready，再进行 Runtime 验收。

当前实现状态：generic capability runtime 已有无仿真依赖的 in-process foundation，但尚未接入 YOLO/Ultralytics、
真实相机或抓取模型；`grasp.propose` 的 Fake/provider-neutral 候选不能解释为 YOLO 识别结果或抓取成功。
RoboTwin20 adapter foundation 位于独立 `examples/forge-adapters/robotwin20` 包，PAOS `pyproject.toml` 不增加
RoboTwin/SAPIEN/Torch/YOLO 依赖，资产也必须通过 adapter profile 引用外部目录，不能复制进 PAOS wheel 或
control-plane 环境。

## 6. 感知抓取链路示例

`scene.observe` 和 `grasp.propose` 都是 Query，不产生物理效果：

```text
scene.observe
  → scene.understand
  → grasp.propose
  → manipulation.prepare
  → 独立的 Action/Session admission（后续功能）
```

候选、准备结果、IK 结果或 backend evaluator 都不能自动变成动作准入。每个阶段都应绑定 observation、scene revision、frame、unit 和 provenance；真实硬件和 RoboTwin 只替换 Endpoint/provider，不替换公共 ToolSpec。

## 7. 自我进化边界

自我进化只能消费完成后的、语义验证过的 AgentTask：

```text
Skill activation → AgentTask/PlanRevision → Tool records
→ VerificationVerdict → redacted TaskEpisode
→ LessonCluster 或 SkillCandidate → guarded promotion
```

单次 Tool call、capability outcome、仿真器 `check_success()`、Lesson 或 projection 都不能单独产生晋升资格。`unknown`、`cancelled`、`stopped` 和 verifier error 必须保持不可学习或仅诊断状态。跨 RoboTwin 到真机的 Skill 晋升必须有独立的 held-out/hazard/硬件证据。

## 8. PR 交付格式

PR 描述应包含：基线 commit、规范章节、选定扩展点、所有权表、非目标、测试命令和结果。若修改了公共契约，必须同时更新 schema、Fake Gateway、conformance tests 和相应文档；若只是新增 adapter，优先保持 PAOS 核心不变。

不要把官方文档全文复制到功能目录。使用章节链接和 commit pinning，项目 ADR 只保留本项目特有的映射理由和取舍。这样文档更新时可以重新审核引用，而不会产生多份互相漂移的契约。
