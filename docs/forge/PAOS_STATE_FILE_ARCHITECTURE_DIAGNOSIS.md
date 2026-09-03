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

`SKILLRUNTIME.md`、`ENVIRONMENT.md` 和 Skill-scoped `LESSONS.md` 可以由机器事实源原子生成：

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
- `SKILLRUNTIME.md`、`ENVIRONMENT.md`、`LESSONS.md` 目前只提供通用 projection 写入入口，事实源仍由
  RuntimeState、Evidence/Snapshot 和 `experience.sqlite3` 持有；
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
