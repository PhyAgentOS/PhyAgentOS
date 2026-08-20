# PhyAgentOS 框架介绍

> 文档版本：0.1.4.post4 · 实现基线：2026-08-03 Forge-only 源码。本文只把源码、配置 Schema 和测试覆盖的行为称为“当前能力”。

## 1. 项目定位

PhyAgentOS 是面向具身任务的 Agent 与任务级编排框架。当前版本将所有机器人执行收敛到 Forge Gateway 1.0.0：Agent 负责理解用户目标、选择 Gateway action、定义成功标准和处理恢复；Forge 负责动作落地；PAOS 在二者之间建立可持久化、可验证、可恢复的系统边界。

这种边界解决的不是“如何在 PAOS 中实现每一种机器人动作”，而是四个更稳定的问题：

1. 怎样确认派发的是哪个 session、哪个 command 和哪个 action。
2. 怎样把 Gateway 的执行终态保留为不可改写的事实。
3. 怎样把动作前后观测组织为可引用、可校验的证据。
4. 怎样依据系统级 goal 和 criteria 判断任务是否成功，并在必要时交回 Planner。

## 2. 三类事实

PhyAgentOS 不把“命令完成”与“任务完成”混为一谈。

| 层次 | 公共模型 | 回答的问题 | 写入者 |
|:-----|:---------|:-----------|:-------|
| 执行事实 | `ExecutionRecord` | Gateway 接收并执行了什么，最终状态是什么？ | `ForgeAdapter` |
| 观测证据 | `EvidenceBundle` | PAOS 在执行前后看到了什么，证据是否完整？ | `ForgeEvidenceWriter` |
| 任务判定 | `VerificationVerdict` | 每一条 success criterion 是否满足？ | `ForgeTaskVerifier` |

Verifier 可以引用 Execution Record，但不能覆盖它。显式复核可以追加新的 verification attempt，但不能修改原任务终态。

## 3. 当前架构

```text
CLI / Channels / Cron / Heartbeat
                │
                ▼
        AgentLoop + Planner
                │ Forge tools
                ▼
      ForgeSessionOrchestrator
        │          │          │
        │          │          └── system event → Agent Planner
        │          └── SQLite sessions + append-only events
        ▼
     ForgeAdapter ───────────────► ForgeTaskVerifier
        │                              │
        │ HTTP: capabilities/session   │ task contract
        │ WS: images/state             │ execution + evidence
        ▼                              ▼
  Forge Gateway 1.0.0             semantic verdict
        │
        ▼
 Forge Runtime / Dora / robot or simulator
```

### 3.1 Agent 控制面

AgentLoop 负责消息、上下文、模型、工具调用与 Planner 决策。启用 Forge 后，Agent 获得 capabilities 摘要和七个 Forge 工具。任务提交是异步的：工具先返回 PAOS 生成的 session/command ID，后台编排完成后再通过 system event 唤醒原对话。

### 3.2 Forge 编排面

`ForgeSessionOrchestrator` 是 PAOS 中唯一机器人任务编排器。它负责：

- 启动时校验 Gateway API 和 supports；
- 事务创建任务并限制单活动 lineage；
- 调用 Adapter 执行与采集证据；
- 按 verification mode 终结、验证或请求恢复；
- 在重启后按照持久化事实恢复，而不重复未知动作；
- 把完成或 recovery 消息路由回原始 Agent session。

### 3.3 Forge 执行面

Forge Gateway、Forge Runtime、Dora dataflow、策略与硬件控制器位于 PAOS 外部。PAOS 不修改其源码，也不绕过 Gateway 直接调用内部组件。

## 4. 公共契约

当前公共边界位于 `PhyAgentOS/verification/contracts.py`：

| 模型 | 版本 | 作用 |
|:-----|:-----|:-----|
| `ForgeTaskRequest` | `forge_task_request_v1` | 高层 action、inputs、task description、verification 和 timeout |
| `TaskVerificationContract` | `task_verification_contract_v1` | mode、goal、criteria、constraints 和 evidence policy |
| `ForgeSessionRecord` | `forge_session_record_v1` | PAOS 状态、lineage、Gateway 响应、Execution、Verification 和 Recovery |
| `ExecutionRecord` | `paos_execution_record_v1` | 不可变 Gateway 执行事实 |
| `EvidenceBundle` | `forge_evidence_bundle_v1` | capture window、artifact、digest、URI 和质量 |
| `VerificationVerdict` | `verification_verdict_v1` | 总体 verdict、逐 criterion 结论、evidence refs、reason 和 lesson |
| `RecoveryRequest` | `recovery_request_v1` | 未满足标准、需保留约束、证据引用、指导与 deadline |

这些模型不包含 `grasp_verify_enabled` 一类动作专用字段。不同 action 的成功语义由任务 criteria 表达，动作的执行语义由 Gateway capability 中的通用 `result_semantics` 和 `completion` 描述。

## 5. 生命周期

```text
accepted
  → capturing_before
  → dispatching
  → running
  → finalizing
  ├─ verification=off ───────────────→ succeeded | failed | timed_out | cancelled
  └─ non-off → awaiting_verification → verifying
                                      ├→ succeeded | failed
                                      └→ awaiting_replan → replanned | failed
```

其中：

- `accepted` 表示 PAOS 已事务化保存任务和系统生成的 ID。
- `dispatching` 前已保存 before snapshot；进入该状态时 dispatch attempt 已持久化。
- `running` 只表示 Gateway session 尚未终结。
- `finalizing` 生成 Execution Record 并尝试冻结 after snapshot。
- `awaiting_verification`/`verifying` 属于任务语义层，不改变原执行事实。
- `replanned` 是 parent 的终态；同一事务中会创建一个全新 child。

## 6. 证据模型

Gateway 1.0.0 没有 authoritative Evidence API。本阶段 PAOS 从 `/ws/images` 与 `/ws/state` 采集证据，并明确标记 `association_quality=best_effort`。

每路图像的基本边界是：

1. before frame 必须在 POST session 前接收并落盘；
2. Gateway 终态只能来自 `/agent/sessions/{session_id}`；
3. after frame 必须在 PAOS 观察到终态之后接收；
4. after sequence 必须严格高于同 source 的 before sequence。

图像需要通过 Base64、媒体类型、magic bytes、大小和 SHA-256 校验。状态消息没有 Gateway source timestamp 时，只记录 PAOS `received_at`，不会构造虚假时间。

## 7. 验证与恢复

验证模式体现的是系统策略，而非动作类型：

- `off`：按 Gateway execution status 终结。
- `audit`：记录 verdict 或错误，但保持 execution 派生终态，永不 recovery。
- `enforce`：verdict 决定结果；缺证、不可判定、非法输出和服务错误均 fail closed。
- `recovery`：与 enforce 相同，唯有合法 `replan_required` 可进入 `awaiting_replan`。

Recovery Request 不是可执行命令。它只包含 unmet criteria、preserved constraints、guidance、evidence refs 和 deadline。Planner 必须重新选择 action、重写 task description 和 inputs，再调用 `create_replanned_forge_session`。

## 8. 持久化与崩溃恢复

编排状态位于 `<workspace>/.paos/forge/orchestrator.sqlite3`，采用 SQLite WAL 与显式事务。实体 artifact 位于 `<workspace>/artifacts/forge/<session_id>/`。

关键恢复规则：

- POST 前崩溃：没有 dispatch attempt 的任务可以继续。
- 已记录 dispatch attempt：只查询原 session，禁止自动重发 POST。
- Gateway 能找到且身份匹配：继续轮询、补采 after evidence 或验证。
- Gateway 返回 404：任务失败为 `FORGE_EXECUTION_STATE_LOST`。
- `verifying` 中断：记录 abandoned attempt 后重新验证。
- `awaiting_replan`：可重新投递同一 Recovery Request；原子 child 创建去重。

## 9. 知识面与执行面的关系

Agent 工作区仍保留：

- `EMBODIED.md`：机器人的人类可读知识描述；
- `ENVIRONMENT.md`：环境或 SceneGraph 状态；
- `LESSONS.md`：执行、验证与恢复经验；
- `TASK.md`：多步骤任务规划状态。

这些文件可以进入 Agent 上下文，但不触发执行。`embodiments` 配置描述知识工作区拓扑，也不会创建额外 Gateway 或硬件 driver。

## 10. 当前实现范围

- 一个 PAOS 进程只支持一个 Forge Gateway endpoint。
- Gateway 必须严格声明 `paos-forge-gateway-mvp-plus.v1`。
- 一个 root lineage 内动作串行；verification/recovery 未终结前拒绝无关新任务。
- 一个 Forge session 对应一个高层 action。
- 证据关联质量只支持 `best_effort`。
- 旧 Runtime、Target、Policy/SkillRuntime、Watchdog、SessionRunner、Perception Pipeline 和 Markdown execution queue 已从活动代码移除，不提供兼容层或迁移器。

## 11. 代码结构

```text
PhyAgentOS/
├── agent/                 # AgentLoop、工具、Verifier client
├── forge/
│   ├── client.py          # 异步 Gateway HTTP client
│   ├── observation.py     # WebSocket 观测采集
│   ├── evidence.py        # Artifact 校验与 Evidence Bundle
│   ├── adapter.py         # 单 action 执行生命周期
│   ├── store.py           # SQLite 状态与事件
│   └── orchestrator.py    # 执行、验证、恢复、通知与重启
├── verification/         # 公共契约、request builder、engine、service
├── channels/             # 消息渠道
├── config/               # 配置模型与加载
└── templates/            # Agent 知识工作区模板
```

## 后续阅读

- [用户手册](02-user-manual.md)
- [开发者手册](03-developer-manual.md)
- [Forge 配置参考](04-forge-configuration-reference.md)
- [Forge 接入契约](../forge/README_zh.md)
- [文档索引](../README.md)
