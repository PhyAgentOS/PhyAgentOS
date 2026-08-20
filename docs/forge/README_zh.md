# Forge 接入契约

> PhyAgentOS 0.1.4.post4 · Forge Gateway 1.0.0 · API `paos-forge-gateway-mvp-plus.v1` · [English](README.md)

本文是 PhyAgentOS 唯一机器人执行链的技术契约。Gateway、Forge Runtime、Dora dataflow、策略与硬件集成位于 PAOS 外部，不由 PAOS 修改。

`move-arm-by-ee` 使用 Gateway Tool API，并由 `paos skill` 显式管理本地 Dora
dataflow。它与本文的高层 Agent Session API 是并列执行面，不复用
`ForgeSessionOrchestrator`。参见 [move-arm-by-ee Skill Runtime](move-arm-by-ee-skill-runtime.md)。

当前已经实现的 Skill/Tool/Endpoint/ToolCall/ToolSpec 关系、运行时边界和后续双供应链
下载设计，参见
[PAOS Skill Runtime 与 Forge Tool 架构（当前实现）](skill-runtime-tool-architecture.md)。

[PAOS Skill Runtime 协作开发指南](skill-runtime-development-guide.md)说明源码与安装目录、
九节点组成、权威仓库边界、本地开发和验收流程。

首批机器可读 Skill/Runtime 包索引及其发布、归档、lock、安装和安全约束见
[PAOS Forge 包索引规范](paos-forge-packages_zh.md)，验证输入见
[YAML 索引](paos-forge-packages.yaml)和
[JSON Schema](paos-forge-packages.schema.json)。PAOS 可通过
`paos skill install --index <path-or-url>` 读取 Schema v3 静态索引。

## 1. 设计边界

```text
Agent goal + criteria
        │
        ▼
ForgeTaskRequest
        │
        ▼
ForgeSessionOrchestrator ───── 持久化 / 重启 / 恢复
        │
        ▼
ForgeAdapter ── HTTP/WS ── Forge Gateway ── Forge Runtime / Dora
        │
        ├── immutable ExecutionRecord
        └── EvidenceBundle
                   │
                   ▼
             ForgeTaskVerifier
                   │
                   ▼
          VerificationVerdict
                   │
             optional RecoveryRequest
```

Adapter 不判断任务成功；Verifier 不生成机器人命令；只有正常 Planner 可以把 Recovery Request 转换为一个重新规划的 action。

## 2. 支持拓扑

- 一个 PAOS 进程配置一个 Gateway endpoint。
- Gateway 声明动作串行；一个 root lineage 在 verification/recovery 终结前占用 PAOS 执行槽。
- 一个 PAOS/Forge session 对应一个高层 Gateway action。
- 更长任务由 Planner 拆成多个 action 或 recovery child。
- Gateway 1.0.0 的 evidence association 只支持 `best_effort`。
- 不提供旧 Runtime/Target/SkillRuntime/Watchdog/SessionRunner/file queue 兼容性。

## 3. 启动契约

`ForgeSessionOrchestrator.start()` 调用 `GET /agent/runtime/capabilities`。解析后的 `data` 必须包含：

```json
{
  "api_version": "paos-forge-gateway-mvp-plus.v1",
  "supports": {
    "sessions": true,
    "command_id": true,
    "runtime_context": true,
    "serial_actions_only": true
  },
  "actions": {}
}
```

`actions` 把 action type 映射到 capability object。PAOS 使用的通用字段包括：

```json
{
  "description": "Human-readable capability",
  "required_parameters": [],
  "input_mapping": {},
  "policy_id": "stable-policy-identity",
  "command": "stable-command-identity",
  "result_semantics": "command_completed",
  "completion": {}
}
```

Capability 摘要会注入 Agent 上下文。每个提交的 `action_type` 必须在缓存的 map 中。`result_semantics` 与 `completion` 写入 Execution Record，但不选择 verifier 实现。

## 4. 公共契约

### 4.1 `ForgeTaskRequest`

```text
version = forge_task_request_v1
task_description
action_type
inputs
verification: TaskVerificationContract
execution_timeout_s
source = paos-agent
```

任务和 action 文本非空，inputs 是有限 JSON。模型故意不包含 session/command ID。

### 4.2 `TaskVerificationContract`

```text
version = task_verification_contract_v1
mode = off | audit | enforce | recovery
goal
success_criteria[]
constraints[]
evidence_policy {
  profile
  required_kinds[]
  required_sources[]
  minimum_association = best_effort | authoritative
}
```

非 `off` 必须提供 goal 和至少一项 criterion。Gateway 1.0.0 无法满足 `authoritative`，因此这种请求在 dispatch 前失败。

### 4.3 `ExecutionRecord`

`paos_execution_record_v1` 是 frozen model，记录规范化 Gateway 事实：session/command/API/instance/action/policy identity、status、通用 result semantics/completion、timeline、outputs 与 execution error。Verifier 不得替换它。

### 4.4 `EvidenceBundle`

`forge_evidence_bundle_v1` 记录 session/command identity、capture window、artifacts 与 quality。每个 artifact 有唯一 ID、phase、kind、source、sequence、timestamps、media type、size、SHA-256、安全 URI 与 retention tombstone 字段。

### 4.5 `VerificationVerdict`

`verification_verdict_v1`：

```text
verdict = success | failure | replan_required | inconclusive
criteria[] = criterion + satisfied|unsatisfied|unknown + evidence_refs
evidence_refs[]
reason
lesson
recovery_context? = unmet_criteria + preserved_constraints + guidance
```

输出必须 exactly-once 覆盖每条输入 criterion，并且只引用已解析 Bundle 中的 artifact ID。

### 4.6 `RecoveryRequest`

`recovery_request_v1` 不可执行，只包含 parent ID、unmet criteria、preserved constraints、动作无关 guidance、evidence refs 与 deadline。

## 5. Identity 与 mutation 顺序

PAOS 在持久化前生成 path-safe 随机身份：

```text
session_id = forge_<16 hex>
command_id = command_<16 hex>
root_session_id = root 的 session_id
```

新 action 的顺序：

1. 事务保存 `ForgeSessionRecord(status=accepted)`。
2. 非 `off` 启动 observation collector。
3. 持久化 before entities 和 snapshot manifest。
4. 持久化 `dispatch_attempted_at` 与 `dispatching` event。
5. 只 POST `/agent/sessions` 一次。
6. 校验 response identity。
7. 只轮询所请求的 session。

dispatch intent 边界明确优先“不要重复未知物理动作”，而不是自动 at-least-once delivery。

## 6. Gateway Agent API

| Method | Path | 契约 |
|:-------|:-----|:-----|
| GET | `/agent/runtime/capabilities` | 版本、supports、actions、instance identity |
| GET | `/agent/runtime/status` | `forge_get_context` 的实时状态 |
| GET | `/agent/runtime/context` | readiness/context 与可选 source 发现 |
| POST | `/agent/runtime/reset` | 仅无活动 lineage 时显式 reset |
| POST | `/agent/sessions` | 使用 PAOS ID、action、instruction、source、inputs 创建 session |
| GET | `/agent/sessions/{session_id}` | 唯一 Gateway execution terminal 来源 |
| POST | `/agent/sessions/{session_id}/cancel` | 带 reason 的 best-effort cancel |

Client 接受 top-level object 或 `data` 中的 object。HTTP 错误、非 object JSON 与 `ok=false` 都会失败。

## 7. Response 关联

每个 create/get response 必须满足：

```text
session.session_id == requested session_id
command.command_id == requested command_id
command.session_id == requested session_id
command.request_id == requested command_id
session.action_type == requested action_type
command.action_type == requested action type
command.policy_id == capability.policy_id（声明时）
command.command == capability.command（声明时）
```

接受 terminal 还要求：

```text
session.status == command.status
status in succeeded | failed | cancelled
```

PAOS 不从 command output、policy 语义、图像静稳、机器人静稳、固定时间或 WebSocket 消息推断终态。

## 8. Observation 契约

### 8.1 Images

Gateway `/ws/images` 发布：

```json
{
  "type": "image",
  "id": "front",
  "seq": 42,
  "timestamp": 1785744000.123,
  "content_type": "image/jpeg",
  "data": "<base64>"
}
```

PAOS 校验 source、非负 sequence、有限可选 timestamp、允许的 image media type、Base64、decoded size 和 magic bytes。Gateway timestamp 写为 `captured_at`，本机接收时间写为 `received_at`。

### 8.2 State

Gateway `/ws/state` 发布 JSON object，PAOS 强制 entity size。v1 没有统一 source timestamp，因此 state artifact 使用 `captured_at=null`，只保留本机 `received_at`。

### 8.3 Freshness

每个 required image source 满足：

```text
before 在 session POST 前接收
after.sequence > before.sequence
after.received_at >= terminal_observed_at
```

如果 task 要求 state，after snapshot 中的 state 也必须在终态观察后接收。

Collector 只保留每 source 最新合法帧，忽略更低/重复 sequence，失败后重连，并有界保存近期错误。

## 9. Evidence 写入与解析

Artifact 原子写入：

```text
<workspace>/artifacts/forge/<session_id>/
├── execution_record.json
├── before_snapshot.json
├── after_snapshot.json
├── evidence_bundle.json
├── verification_result.json
└── evidence/
```

Writer 拒绝 path escape 与 source 安全化后的命名冲突。Snapshot 读取和 Verification Request 构造会再次校验 path、entity 存在、byte size、SHA-256、image media type、Bundle identity、capture window 顺序、completeness、required kinds/sources 与 minimum association。

Bundle quality 区分：

- `complete`；
- `association_quality`；
- `capture_authority=paos_forge_adapter`；
- missing requirements；
- stale artifacts；
- collection/validation errors。

Evidence 问题是数据质量，不是执行终态推断。

## 10. 生命周期

```text
accepted → capturing_before → dispatching → running → finalizing
         ├─ off ───────────────────────────→ succeeded|failed|timed_out|cancelled
         └─ non-off → awaiting_verification → verifying
                                                ├→ succeeded|failed
                                                └→ awaiting_replan → replanned|failed
```

`replanned`、`succeeded`、`failed`、`timed_out`、`cancelled` 是 PAOS 终态。Parent `replanned` 与 child `accepted` 原子提交。

## 11. Verification 语义

| Mode | 执行/证据行为 | 终结规则 |
|:-----|:--------------|:---------|
| `off` | 不生成 verification bundle、不调用 verifier | 映射 execution status |
| `audit` | 尽可能采集/验证，记录错误 | 保持 execution 派生终态，永不 recovery |
| `enforce` | 要求完整证据与合法 verifier | 只有 `success` 成功，其余 fail closed |
| `recovery` | 同样严格验证 | 只有合法 `replan_required` 进入 recovery |

Verifier prompt 只包含 goal、criteria、constraints、immutable execution、evidence、lineage history、lessons 与合法 evidence refs。不得按 action type 分支，也不得输出可执行 action。

## 12. Verification Service

PAOS 用 serializable provider spec 启动子进程，并执行有界 readiness：

```text
GET  /healthz
POST /v1/verify-task
X-PAOS-Admin-Token: <per-process token>
```

模型调用受 timeout 与 per-process budget 限制。输出经过规范化后，再校验模型 shape、verdict consistency、exact criteria 与 known evidence refs。

## 13. Recovery 语义

收到合法 recovery verdict 后，Orchestrator：

1. 收集 unmet/unknown criteria；
2. 保留原始与 verifier 提供的 constraints；
3. 去重 evidence refs；
4. 创建带 deadline 的 Recovery Request；
5. 向原 Agent session 发送 system message；
6. 等待正常 Planner 调用 `create_replanned_forge_session`。

Child 创建要求 parent 正在等待、deadline 未到且 budget 剩余。Child 继承 verification contract 与 routing，但使用新的 action description、action type、inputs、session ID 和 command ID。同一 parent 重复创建返回已有 child。

## 14. 重启规则

| 持久化状态 | 恢复规则 |
|:-----------|:---------|
| 无 dispatch attempt | 继续正常 action 链路 |
| 有 dispatch attempt | 只 GET 原 session，绝不 POST |
| Gateway session 匹配 | 继续 poll/finalize/verify |
| Gateway 404 | 失败为 `FORGE_EXECUTION_STATE_LOST` |
| 已有 Execution Record | 仅 identity 匹配时复用 |
| `verifying` | 追加 abandoned attempt，回到 awaiting verification |
| `awaiting_replan` | 重投 recovery context；原子 child 创建去重 |

PAOS 正常退出会请求取消每个活动 Gateway session 并保存结果。

## 15. Evidence retention 与复核

| Policy | 删除规则 |
|:-------|:---------|
| `all` | 保留全部实体 |
| `failed` | 最终 PAOS 状态为 `succeeded` 时删除实体 |
| `none` | 验证后删除实体 |

删除后 Bundle 保留 tombstone：URI、source、time、sequence、size、digest、`retained=false` 和 `deleted_at`。Execution Record 保持不变。

`verify_forge_session` 对终态 session 显式复核，要求证据 retained，追加 attempt，并可更新最新 verification view。它不修改任务终态或 Execution Record。

## 16. 失败行为

| 失败 | 必须行为 |
|:-----|:---------|
| API/supports 不支持 | 拒绝启动 |
| action 不支持 | 在 persistence/dispatch 前拒绝 |
| 请求 authoritative evidence | dispatch 前拒绝 |
| audit 缺 before evidence | 可继续 dispatch；记录 incomplete bundle/error |
| enforce/recovery 缺 before | POST 前失败 |
| execution timeout | 请求 cancel；保留 last response/evidence/cancel response |
| 验证时 evidence 缺失/非法 | audit 记录；enforce/recovery fail closed |
| verdict 非法/service 失败 | audit 记录；enforce/recovery fail closed |
| replan budget/deadline 耗尽 | parent failed 并写 lesson |
| dispatch 后 Gateway session 丢失 | 失败且不重复 action |

## 17. Conformance 测试

兼容接入应覆盖：

- capability version/support/action；
- create/get/cancel/reset response envelope；
- session/command/request/action/policy/command identity；
- Gateway terminal 与 timeout；
- 多 source、重连、乱序、重复、陈旧帧、非法 Base64/media/size；
- before-before-POST 与 after-after-terminal；
- 四种 mode、非法输出、service timeout、retention、review；
- Store 并发、合法 transition、单活动 lineage、原子 replan；
- dispatch 前后重启、session 丢失、late evidence、verification 中断；
- 仅 Forge enabled 时暴露 tools，system event 路由正确。

可选黑盒测试通过 `FORGE_GATEWAY_URL` 连接，不修改 Gateway 源码或配置。

## 相关文档

- [框架介绍](../zh/01-framework-introduction.md)
- [用户手册](../zh/02-user-manual.md)
- [开发者手册](../zh/03-developer-manual.md)
- [配置参考](../zh/04-forge-configuration-reference.md)
- [集成开发指南](../user_development_guide/README.md)
- [通信架构](../user_development_guide/COMMUNICATION.md)
