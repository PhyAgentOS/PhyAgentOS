# PAOS 状态文件架构诊断与下一步方向

> 诊断范围：PAOS v1.0 文档、当前 `PhyAgentOS-forge` 源码，以及近期抓取放置 / RoboTwin 接入诊断。
>
> 目的：记录五类报告概念与 PAOS 现行架构的对应关系，明确状态文件是否为权威中间状态，并给出下一步实现方向供审核。本文件只做架构分析，不代表已批准的代码实施。

## 1. 执行结论

PAOS 当前没有规定“中间状态必须使用 Markdown 存储”。v1.0 文档明确将旧的 Markdown queue Runtime 视为已移除；当前权威状态由 AgentTask SQLite、Gateway ToolInvocation、Evidence JSON/artifact、Runtime state store 和 Experience SQLite 分别持有。

Markdown 在 PAOS 中承担三类职责：

1. Agent 工作区上下文和人工说明（例如 `AGENTS.md`、`EMBODIED.md`、`TASK.md`、`SKILL.md`）；
2. 人类可读的输入或运维界面；
3. 由机器事实源生成的 projection（例如 Skill-scoped `references/LESSONS.md`）。

因此，报告中的 `TARGETS.md`、`SKILLRUNTIME.md`、`SESSIONS.md`、`ENVIRONMENT.md`、`LESSONS.md` 可以保留为领域接口或 projection，但不应在 PAOS 核心中形成第二套事实源、状态机或执行协议。

## 2. PAOS 文档中的权威边界

### 2.1 当前持久化布局

PAOS 文档规定的持久化结构是：

```text
<workspace>/
├── .paos/agent_tasks/tasks.sqlite3
├── .paos/evolution/experience.sqlite3
├── .paos/evolution/revisions/<skill>/
├── skills/<skill>/SKILL.md
└── artifacts/agent_tasks/<task_id>/
    ├── before_snapshot.json
    ├── after_snapshot.json
    ├── evidence_bundle.json
    └── evidence/
```

通信架构进一步将 AgentTask、Evidence、Experience、Runtime state 和 Runtime logs 分到各自存储边界。跨边界只共享不透明 reference，不共享执行所有权。

### 2.2 Markdown queue Runtime 已移除

PAOS 总文档明确指出，当前 Skill Runtime 与“已移除的 Markdown queue Runtime”不同。这意味着 Markdown 文件不再是调度队列或执行中间状态的通用替代品。

### 2.3 Session 不是 Markdown 状态协议

当前 Session/Action 生命周期以 Gateway 的 `status/result` 为终态来源，PAOS 侧由 AgentTask 聚合，并通过 `invocation_id`、`attempt_id`、`task_id` 等显式身份关联。`pending`、`unknown`、`cancelled`、`stopped` 具有严格语义，不能由 Markdown 文本推断。

### 2.4 规范依据

- [文档索引的 Runtime 与兼容边界](../README.md#runtime-and-compatibility-boundaries)：当前 Skill Runtime 与已移除的 Markdown queue Runtime 明确分离；
- [框架介绍的持久化章节](../zh/01-framework-introduction.md#10-持久化)：列出 AgentTask、Experience、Skill revision 和 Evidence artifact 的实际存储；
- [通信架构的持久化边界](../user_development_guide/COMMUNICATION.md#10-持久化边界)：规定 AgentTask、Evidence、Experience、Runtime state 和 logs 的所有权；
- [Forge Tool API 契约](README_zh.md#8-agenttask-模型)：规定 AgentTask 状态机、Gateway invocation 终态来源和恢复语义；
- [Agent 经验与 Skill 自进化](../zh/05-agent-experience-and-skill-evolution.md#9-持久化投影与可观测性)：规定 `experience.sqlite3` 为事实源、Skill `LESSONS.md` 为人工审阅 projection。

## 3. 五个报告概念的映射

| 报告概念 | 当前 PAOS 对应 | 推荐定位 | 当前缺口 |
|---|---|---|---|
| `TARGETS.md` | `EMBODIED.md`、ToolSpec、Runtime/Profile、provider readiness | 能力矩阵的输入/可读 projection；结构化 schema 才是约束权威 | 没有统一 capability schema，也没有在所有 Action admission 中统一执行硬件能力否决 |
| `SKILLRUNTIME.md` | `skill.yaml`、manifest-v2、`RuntimeProfile`、`RuntimeManager` | Manifest 的说明性 projection | 不能再增加第二份 profile、Gateway 或 Node 配置源 |
| `SESSIONS.md` | Gateway Session、`AgentTaskRecord`、`AgentTaskStore`、Runtime state | 声明式意图输入，编译成 AgentTask | 没有文件到 AgentTask 的幂等编译器；不能让文件直接成为生命周期事实 |
| `ENVIRONMENT.md` | `load_environment_doc()`、SceneGraph Query、Observation/Evidence Snapshot | 环境知识和快照 projection | 文件尚不是带 revision/provenance 的环境事实源，Verifier 主要消费 Evidence Snapshot |
| `LESSONS.md` | `experience.sqlite3`、ExperienceCoordinator、Skill-scoped projection | 人工审阅和 Skill-scoped projection | 根文件在 evolution 模式下不是全局 Prompt 或 Verifier 输入 |

## 4. 为什么必须分离 Markdown 与机器事实

### 4.1 安全约束不能只存在于 Prompt

硬件关节范围、速度、工作空间和动作权限必须在 Runtime/Profile/Action admission 中确定性校验。Agent 读取 Markdown 后自行判断不能构成物理安全门。

### 4.2 事务状态不能依赖文本覆盖

长程抓取放置会同时涉及 Query、Action、Session、pending、timeout、unknown、cancel、replan 和 recovery。SQLite/WAL、事件记录和显式 invocation identity 比 Markdown 更适合并发、恢复和审计。

### 4.3 环境验收需要不可变证据

“物体是否已被抓取或放置”需要 before/after snapshot、scene revision、frame、calibration、时间戳和 artifact provenance。直接比较两个 Markdown 文件容易丢失这些关联，也容易被错误修改。

### 4.4 自主进化需要稳定的事实链

经验只能从完成且语义验证的 AgentTask 进入：

```text
Skill activation
  → AgentTask / PlanRevision
  → ToolExecutionRecord
  → Evidence + VerificationVerdict
  → redacted TaskEpisode
  → LessonCluster / SkillCandidate
  → guarded promotion
  → Skill/Lesson projection
```

Markdown 修改不能直接算作执行经验，也不能绕过支持门槛、抽象校验、作用域绑定、held-out/hazard 验证或 rollback。

## 5. 推荐的统一协议

### 5.1 输入型文件

`SESSIONS.md`、人工维护的 `TARGETS.md` 或环境说明可以作为声明式输入，但必须经过：

```text
Markdown
  → 解析与 schema 校验
  → 生成稳定 task/reference/revision identity
  → 写入权威 Store
```

解析器必须支持幂等、版本校验、未知字段拒绝和失败不调度。解析失败不能创建半有效任务。

### 5.2 Projection 型文件

`ENVIRONMENT.md` 和 Skill-scoped `LESSONS.md` 可以由机器事实源原子生成；`SKILLRUNTIME.md` 当前没有生产
producer：

```text
Manifest / Evidence / Experience Store
  → bounded projection
  → Markdown
```

人工修改 projection 不改变事实源；下一次同步可以覆盖 projection，或明确报告 drift，但不能静默改变执行语义。

### 5.3 唯一权威源表

| 领域 | 唯一机器权威 |
|---|---|
| 物理能力与动作限制 | validated Capability Profile / target schema |
| Skill Runtime | manifest-v2 + locked Node/Profile |
| 任务生命周期 | `AgentTaskStore` SQLite |
| Gateway 执行事实 | Gateway ToolResult / invocation events |
| 环境验收证据 | immutable before/after Evidence Snapshot |
| Lesson/Evolution | `experience.sqlite3` |
| Markdown | 输入界面或可读 projection |

## 6. 对抓取放置工作流的影响

当前 `pick-place-workflow` 已经具备 provider-neutral 六 Tool 纵向切片：

```text
scene.observe
  → scene.understand
  → grasp.propose
  → manipulation.prepare
  → object.acquire
  → object.place
```

已有 generic capability runtime、Fake Gateway、ToolSpec、证据和经验接口；当前尚缺真实 Gateway/Dora wiring、完整真实 provider、抓取/放置执行器和端到端真实验收。感知部分的单视角 adapter composition 已完成无动作协议验收，但不能等同于抓取成功。

因此，上层设置应先冻结以下最小契约，再继续抓取放置：

1. 能力矩阵字段、版本和 Action admission 归属；
2. `task_id`、`revision_id`、`record_id`、`invocation_id`、`attempt_id` 的身份边界；
3. `scene_revision`、`observation_ref`、`candidate_set_ref`、`preparation_ref` 和 before/after evidence 的关联规则；
4. Query/Action/Session 的状态转移、unknown 和 no-blind-retry 语义；
5. 哪些失败可进入 Experience，哪些只能保留诊断；
6. `motion_authorized=false` 的 no-motion 边界和真实执行的独立审批条件。

不需要先完成五个 Markdown 文件，也不应在此阶段实现独立 Markdown queue Runtime。

## 7. 推荐下一步实现方向（审核后调整）

### 审核结论：先做受限文件适配，符合 PAOS 扩展原则

“文件适配先于抓取放置闭环”本身不违反 PAOS 原则，反而能在低风险阶段暴露上层契约问题。成立的
前提是：适配器只解析、投影、dry-run、shadow validation 和 drift，不拥有 Watchdog、Gateway、
AgentTask 生命周期或 Action admission。Markdown 仍不是第二事实源，也不能直接触发物理执行。

#### 阶段 A：冻结最小上层与文件契约

- 建立权威源和所有权表；
- 固定状态、身份、revision、provenance、幂等和 projection 规则；
- 定义 Capability Profile 的最小 schema，并规定 `TARGETS.md` 只能先做 shadow validation；
- 定义 `SESSIONS.md` 仅作为声明式意图输入，不作为状态事实；
- 定义 `ENVIRONMENT.md` 只能投影带 revision/provenance 的可信 snapshot；
- 确定 Evolution 可修改和不可修改边界。

#### 阶段 B：实现无副作用文件适配与回放验证

- `SKILLRUNTIME.md`：从 manifest/Profile/Runtime 状态生成只读 projection；
- `ENVIRONMENT.md`：从 snapshot/Evidence 引用生成带来源和时间戳的 projection；
- `LESSONS.md`：从 `experience.sqlite3` 按 Skill 作用域生成 projection；
- `TARGETS.md`：解析、schema 校验、单位/范围检查和 Capability Profile shadow 对比，不改变 admission；
- `SESSIONS.md`：先实现 parse/validate 和 AgentTask dry-run preview，不写入生命周期或调度状态；
- 用 Fake Store、Fake Gateway、回放样例覆盖幂等、未知字段、失败回滚、projection drift 和 no-motion；
- 任一解析失败均不得创建任务、更新事实源或启动执行。

#### 阶段 C：提升已验证的输入边界

- 在人工确认和幂等校验后，才允许 `SESSIONS.md` 编译为 `AgentTaskRecord`；
- 只有通过 schema/profile 校验的 `TARGETS.md` 结构化结果，才可作为未来 admission 的候选输入；
- 保持 SQLite、Gateway、Evidence 和 Experience 各自的唯一权威，不把 Markdown 写回为事实源；
- 在此阶段仍不创建 Markdown queue Runtime，也不授权任何物理动作。

#### 阶段 D：继续抓取放置纵向闭环

- 让 `grasp.propose` 消费正式绑定的定位/点云 artifact；
- 让 `manipulation.prepare` 消费能力约束并保持 no-motion；
- 完成 `object.acquire` / `object.place` 的真实 provider-neutral Action admission；
- 将 before/after evidence 与放置语义验收接通；
- 保持 Fake Gateway、无动作和 fail-closed 测试，并将失败分类为 workflow failure 或 diagnostic-only failure。

#### 阶段 E：接入受控自主进化

只有当文件适配和抓取放置都产生稳定的 AgentTask、Evidence、VerificationVerdict 和 failure-owner 后，
才纳入 LessonCluster 或 SkillCandidate 晋升。文件解析成功、projection 更新或 dry-run 预览本身都不能
成为进化证据。

### 7.1 第一阶段实现状态（v2.10.0）

已实现 `PhyAgentOS.state_io` 的受限适配骨架，当前只覆盖文件协议验证和无副作用预览：

- `protocol.py` 要求单一 fenced JSON/YAML state block、固定 `paos.state-file.v1` 元数据、有限 JSON 值，
  并提供原子 projection 写入和基于 canonical data digest 的 drift 拒绝；
- `adapters.py` 提供 `TARGETS.md` 的 capability matrix shadow validation，校验 profile、观测模态、动作空间
  和数值限幅，但固定返回 `motion_authorized=false`；
- `SESSIONS.md` 只生成确定性的 dry-run preview，不创建 `.paos/agent_tasks/tasks.sqlite3`，不调用
  AgentTaskCoordinator，不调度 Watchdog；
- `ENVIRONMENT.md` 由严格的 snapshot/provenance producer 生成，Skill-scoped `LESSONS.md` 继续由
  `experience.sqlite3` 的 Evolution producer 生成；`SKILLRUNTIME.md` 暂无生产 producer，通用 renderer 已不再作为
  `state_io` 公共 API。事实源仍由 RuntimeState、Evidence/Snapshot 和 `experience.sqlite3` 持有；
- 测试覆盖结构化块缺失、未知字段、非法限幅、projection drift、确定性 preview 和 no-motion 边界。

本阶段没有把文件适配器接入 AgentLoop、Watchdog、Gateway 或 Action admission。下一阶段若要允许
`SESSIONS.md` 编译为 `AgentTaskRecord`，必须另行增加人工确认、幂等 compiler、公开 Coordinator 调用和
事务 conformance；不能直接扩展当前 dry-run 函数的副作用。

### 7.2 阶段 C 首个受限 promotion 实现（v3.0.0）

已增加一个仍位于 `state_io` 适配边界内的 promotion 入口：

- `SessionCompileApproval` 是不可变、`extra=forbid` 的人工确认凭据，必须携带源文件 canonical SHA-256、审批人、审批编号和带时区的 ISO-8601 时间；文件 digest 变化会使审批失效。
- `compile_sessions_to_agent_tasks()` 默认只编译一个 session；多 session 文件必须显式选择 `session_id`，从而避免在全局单一非终态 AgentTask 约束下产生部分写入。
- 编译前通过 `AgentTaskStore.active()` 检查全局非终态任务，并以 `statefile+sessions://<digest>/<session_id>` 作为稳定 origin identity；重复编译返回已有记录，不创建重复任务。
- 真正创建只调用 `AgentTaskCoordinator.create_task()`；`parent_task_id` 与 `retry_limit` 作为 AgentTaskRecord 的声明式字段保存，且父任务必须已存在并处于终态。
- 该 promotion 仍不调用 Gateway、Watchdog 或 Action admission，结果固定 `motion_authorized=false`；因此它提升的是“任务意图输入边界”，不是执行权限。

该阶段的 promotion gate 是人工凭据、源 digest、全局活动任务、父任务身份和幂等性测试全部通过。抓取放置动作、证据闭环和自主进化仍保持在后续阶段。

#### TARGETS candidate 边界

阶段 C 同时增加 `promote_targets_candidate()`：它要求 `TARGETS.md` 通过严格 shadow validation，并要求
`TargetProfileApproval` 同时绑定候选源 digest 与当前 baseline digest。返回值只是不可用于 admission 的
Capability Profile candidate，固定 `motion_authorized=false`，不写 Runtime/Profile 权威配置，也不改变任何
Action 限幅。baseline 漂移、审批不匹配或 schema 失败均 fail-closed；真正的 Runtime/Profile admission 仍需
另行设计并审核。

#### 阶段 C candidate 代码审查结论

本轮审查确认：审批 schema 使用 `extra=forbid`、source/baseline digest 双重绑定，candidate promotion 不产生
任何执行副作用；同时补上了 `profile_id` 的 path-safe 校验，避免能力身份被路径语义污染。18 项定向测试覆盖
成功、非法输入、审批 decision/时间戳、baseline drift、显式差异批准、输入文件不变和 no-motion 边界。
candidate 外壳虽为 frozen dataclass，但其中嵌套 `data` 仍是普通映射；它目前只作为非权威比较/replay 结果，
不得被当作可变 Runtime 配置或直接传入 admission。若未来需要跨进程缓存 candidate，应再定义深度不可变/序列化契约。

### 7.3 ENVIRONMENT projection 实现状态（v3.2.0）

本阶段完成的是文件适配层，不是环境事实链的全部接入：

- `EnvironmentProjectionData` 要求 `scene_revision`、opaque `snapshot_ref`、`phase`、带时区的 `captured_at`、`source_id`、`frame`、`calibration_ref` 和结构化 `scene_graph`；`scene_revision` 必须与 envelope 的 `paos.revision` 一致。
- `render_environment_projection()` 和 `parse_environment_projection()` 只接受 `paos.mode=projection` 和上述 schema，错误来源、revision、时间戳或 scene graph 结构均 fail-closed。
- `SceneGraphQueryTool` 已切换到严格 parser；缺失、旧版或损坏的 `ENVIRONMENT.md` 返回 bounded error，不再静默回退为空环境。
- 模板已切换为 `paos.state-file.v1` projection envelope，并明确 Markdown 不是 Evidence、Verifier 或任务生命周期事实源。

已补上受限的 `EnvironmentProjectionProducer`：它只接受已捕获的 `ObservationSnapshot` 与显式
`scene_revision`、`snapshot_ref`、phase、source/frame/calibration 和 scene graph 元数据，并通过
`render_environment_projection()` 原子生成 `ENVIRONMENT.md`。`publish_from_adapter()` 只读取
EnvironmentAdapter 的 sanitized `snapshot()` 身份并校验 revision；不会捕获传感器、调用 Gateway、
创建 AgentTask、调度 Watchdog 或授权动作。producer 仍不把 Markdown 变成 Evidence/Verifier 事实源。

已进一步补上 `ForgeEvidenceWriter` 关联：writer 对 before/after manifest 做版本、phase 和路径校验，
为 writer-owned snapshot 生成稳定 opaque `evidence://` URI；producer 可由该 manifest 自动注入 phase 与
reference，并拒绝调用方提供的不匹配值。writer 现在拒绝同一 phase 的不同内容覆盖，保持 snapshot 不可变。

已增加基础 Verifier/Evidence boundary conformance：`VerificationRequestBuilder` 不能把
`ENVIRONMENT.md` projection 解析为 Evidence Bundle，`ForgeTaskVerifier` 也会拒绝将 projection URI
作为 verdict evidence reference。完整 LLM 语义 verdict、真实 Gateway replay/failure conformance 仍未完成，
因此阶段 B 仍未完全结束，阶段 D 抓取放置闭环暂不启动。

随后补充了 Evidence request-level conformance：完整 bundle 的 capture window、必需 kind/source、
authoritative association、artifact retention、byte size/digest、媒体类型和结构化 JSON 均在
不可变 bundle replay 中被重新校验；跨工作区复制后 artifact identity 与结构化事实保持一致。该测试
验证的是 Evidence 消费边界，不等同于已经完成 LLM 语义 verdict 或真实 Gateway replay。

当前又增加了 `ForgeTaskVerifier` 的本地 verdict contract conformance：验证 success 必须逐条满足
criteria，replan 必须携带 recovery context，criteria 集合和 evidence reference 必须精确绑定，
malformed model response 必须 fail-closed。该 conformance 通过替换模型启动 seam 的确定性 fixture
执行，不启动验证子进程、不调用模型或 Gateway；因此 provider-backed LLM 语义质量和真实服务 replay
仍需单独验收。

随后增加 Verification Service HTTP 层 replay/failure conformance：使用进程内 deterministic provider
验证授权 token、请求 envelope、重复 replay、一致 verdict normalization、invalid model response 和
provider failure。该测试覆盖真实 HTTP handler 与 `VerificationEngine` 的组合，但不启动生产子进程、
不连接外部 provider；因此 `VerificationServiceProcess` 的 provider-spec 启动链和真实模型质量仍需
在独立环境中验收。

本轮进一步补充了文件适配的 Fake Store/Fake Gateway replay、未知字段失败前置、编译失败无残留、
projection drift 保留旧内容和 no-motion conformance。这里的 replay 只证明适配器输入/投影的确定性和
失败边界，不把 Fake Gateway 变成生产执行路径，也不把 Markdown 提升为事实源。

需要明确：阶段 B 清单中的 `SKILLRUNTIME.md` producer 和额外的 `LESSONS.md` producer 是可选的可观测性
projection，不是 PAOS 核心生命周期或执行权限的前置条件。本项目当前不把 generic renderer 暴露为已实现模块，
也不实现第二套 Runtime 或 Experience 配置源；后续只有在运维审阅需求明确时才补充由 manifest/Runtime state 或
`experience.sqlite3` 生成的只读 projection。阶段 B 的必要关闭条件应优先看 Evidence 语义验收和
跨环境 replay/failure 覆盖，而不是“五个 Markdown 文件是否全部有 producer”。

### 7.4 v3.5.0 修复与第二轮审查结论

本轮修复与代码审查的逐文件记录见 [`STATE_FILE_IMPLEMENTATION_REVIEW_20260903.md`](STATE_FILE_IMPLEMENTATION_REVIEW_20260903.md)。
审查已关闭 AgentTask origin/migration/update validation、Evidence manifest/bundle/retention、ENVIRONMENT prompt、TARGETS/SESSIONS schema、
provider/service configuration 和 HTTP failure-path 的已知缺口。验证结果为仓库测试 `105 passed`，并另行通过
pick-place 示例测试 `241 passed`；没有把这些测试中的 Fake Store/provider 当作生产实现证据。

当前仍只实现必要的受限文件边界：`TARGETS.md` 是 shadow candidate，`SESSIONS.md` 是经人工确认后通过
Coordinator 的意图输入，`ENVIRONMENT.md` 是带 provenance 的 projection；`SKILLRUNTIME.md` 没有生产 producer，
Skill-scoped `LESSONS.md` 由 Experience ledger 生成。provider-spec 生产子进程门禁已完成；真实模型语义质量、真实 Gateway 和
抓取放置闭环仍需独立门禁，不能因为文件适配或 fixture smoke 通过而提前启动。

最终复审另外确认：AgentTask 的可变更新现在必须重新通过完整 record schema；robot-state 与 verifier structured JSON
拒绝非标准数值；Evidence retention 只在终态通过持久化 Bundle 身份和 RequestBuilder 已验证路径集合后执行，recovery
中间态保留证据。上述修复不改变 Markdown、Evidence、Runtime、Gateway 和 Experience 各自的事实 owner。

### 不推荐方案：先完整实现五个 Markdown 状态文件

该方案短期看起来结构完整，但会造成：

- Markdown 与 SQLite/Gateway 双重事实源；
- 第二套 Session/Watchdog 状态机；
- 环境文件可被误当作成功证据；
- Skill Runtime manifest 与 Markdown 配置漂移；
- 自主进化消费未经验证的中间文本。

## 8. 自主进化边界

### 可以进化

- Skill 工作流顺序；
- 重新观测和检查点；
- replan 和恢复建议；
- failure pattern 的抽象描述；
- Skill-scoped Lesson；
- 经过验证的 managed workflow block。

### 不可由自主进化直接修改

- 关节、速度、负载和工作空间硬限制；
- Action admission 安全门；
- Gateway 执行事实；
- AgentTask 生命周期和身份规则；
- Evidence 完整性和 provenance 规则；
- Verifier 的基础安全约束；
- Runtime 制品、Gateway identity 和 digest。

这样得到的是“根据真实执行经验改进未来的 Skill-use”，而不是“让模型自行修改物理真相或执行权限”。

## 9. 用户审核闸门

在进入下一轮实现前，请审核以下方向是否成立：

1. 是否同意 Markdown 文件只作为输入界面或 projection，不作为 PAOS 核心的唯一事实源；
2. 是否同意 `AgentTaskStore`、Gateway、Evidence 和 `experience.sqlite3` 分别保留各自权威；
3. 是否同意先冻结最小上层契约，再继续 `pick-place-workflow`；
4. 是否同意 `TARGETS` 的物理限制必须由 schema/profile/admission 确定性执行；
5. 是否同意自主进化只改变 Skill workflow/Lesson，不直接修改安全边界和执行事实；
6. 是否同意先完成受限文件适配（projection、shadow validation、dry-run 和回放验证），再推进
   `grasp.propose → manipulation.prepare → acquire/place` 的证据闭环。

审核通过后，下一阶段应以“上层契约冻结 + 无副作用文件适配验证”为实施目标；抓取放置闭环在该验证
通过后推进，且任何阶段都不创建第二套 Markdown 执行协议。

## 10. v3.8.3 门禁状态更新

完整 `gpt-5.6-sol/high` held-out + hazard 评估已完成并通过正式质量门禁：7 个 case 全部返回合法 verdict，contract、criterion、
recovery-context 均为 `1.0`，`success_false_positive_rate=0`，总体 verdict accuracy 为 `0.8571428571428571`，运行目录为
`artifacts/evals/verification/20260904T034715.434600Z-42a21625/`。其中一个 held-out replan case 被模型判为 `inconclusive`，
held-out accuracy 为 `0.75`，但高于当前总体阈值 `0.8`；该残余风险已记录，不把门禁通过描述为完美语义正确。

因此，Verification 语义质量门禁现在可以关闭。执行顺序仍未跳过物理边界：下一步是 Gateway/Dora 的无动作 wiring、失败/超时/身份
conformance 和代码审查；之后才是抓取放置闭环，最后才是基于可归因执行证据的受控自主进化。该评估没有连接 Gateway、Dora、Action 或硬件，
也没有授予 motion authorization。

## 11. v3.9.0 阶段验收澄清

本阶段“之前五个模块”是五个验收维度：架构集成、失败路径、权威边界、配置、可维护性；不是要求重新实现
`TARGETS.md`、`SKILLRUNTIME.md`、`SESSIONS.md`、`ENVIRONMENT.md`、`LESSONS.md`。这些文件继续遵循各自的
projection/input 与 SQLite、Gateway、Evidence、Runtime、experience ledger 事实源边界。

Gateway/Dora 无动作 wiring 已通过 provider-neutral `CapabilityRuntimeTransport` 接入既有 Runtime/ToolClient，覆盖
discovery/context、Query、Action/Session 生命周期、身份关联、timeout/unknown、cancel/stop、并发和 no-POST recovery。
该结果只证明协议与边界实现，不证明真实 Dora 进程或物理执行可用；抓取放置闭环与受控自主进化仍按顺序后置。

## 12. v3.10.0 抓取放置阶段状态

抓取放置阶段现已完成协议级证据闭环：固定六步 workflow reducer 可从标准 Gateway terminal response 提取
opaque identity，并要求 place 的 `acquire_invocation_ref` 与前一步成功 acquire 一致；成功 place 还必须提供完整
`post_release_evidence` artifact。该阶段仍是 no-motion/replay 语义，未连接真实 Dora、Action executor、机器人或硬件。

完成后按架构集成、失败路径、权威边界、配置、可维护性五个维度复审通过；下一阶段才可在独立 adapter/profile 门禁下讨论真实
环境接入，任何物理动作仍需额外的 Runtime/Profile/Action admission 与硬件安全证据。

## 13. EnvironmentAdapter 阶段状态与下一步

EnvironmentAdapter 接入门禁已按上述顺序启动并完成首个 provider-neutral observation seam。核心
`ObservationEndpoint` 负责 `scene.observe` Query 的输入、freshness、frame、calibration、scene revision、artifact
和错误投影；`ObservationSource` 负责注入式传感器捕获；RoboTwin20 adapter 只负责 profile、reset/snapshot 与
camera/depth/state artifact 投影。`OBSERVATION_TOOL_SPEC` 必须由部署方显式注册到 CapabilityRuntime，不能由
HTTP transport 或 adapter 偷含环境语义。

本阶段五维复审通过：架构集成无第二执行平面，provider 异常/不可用/stale/绑定漂移 fail-closed，RoboTwin actor/entity
truth 不进入 observation，profile/path/calibration 不硬编码到核心 runtime，测试与错误码保持可维护。专项测试 10 passed，
根仓库 161 passed，RoboTwin 无第三方依赖子集 16 passed；完整 RoboTwin 测试因当前 PAOS 环境缺少 `numpy` 与
`pick_place_workflow` 路径未收集，不构成完整真实 adapter 验收。

因此当前可确认的是“核心 observation contract 与 no-motion adapter 边界完成”，不是“真实 RoboTwin/Gateway/Dora 或
硬件完成”。下一步按架构顺序是让 `scene.understand` 消费正式绑定的 observation/geometry artifacts，并以同样五维
标准进行审查；之后才讨论真实 Gateway/Dora provider wiring。多视角 observation、GraspGen live checkpoint、prepare/action
executor 和自主进化 promotion 继续后置。
