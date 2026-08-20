# PhyAgentOS 开发者手册

> 文档版本：0.1.4.post4。本文面向 PAOS、Forge Gateway、Evidence、Verifier 与 Agent 工具开发者。

## 1. 开发原则

涉及具身执行的改动必须保持以下不变量：

1. Forge Gateway 是唯一机器人执行入口。
2. Gateway terminal 是执行事实；任务成功由 verification policy 决定。
3. session/command ID 只由 PAOS 生成，调用方不能指定或复用。
4. 已记录 dispatch attempt 的 session 永不自动重复 POST。
5. Gateway session、command、request、action、command identity 和 policy identity 必须匹配。
6. Execution Record 写入后不可被 Verifier、review 或 retention 覆盖。
7. Evidence 必须保留真实来源、sequence、source time（若有）和 PAOS received time；不制造权威关联。
8. Verifier prompt、公共 Verdict 和 Recovery Request 与具体 `action_type` 无关。
9. parent `replanned` 与 child 创建必须在一个 SQLite 事务中完成。
10. 修改执行、证据、验证、恢复或持久化时必须覆盖失败路径和重启路径。

## 2. 模块地图

| 领域 | 路径 | 责任 |
|:-----|:-----|:-----|
| Agent 编排接入 | `PhyAgentOS/agent/loop.py` | 注册 Forge tools、注入 capability 摘要、处理 system event |
| Agent tools | `PhyAgentOS/agent/tools/forge.py` | JSON Schema、调用上下文与 Orchestrator facade |
| 公共契约 | `PhyAgentOS/verification/contracts.py` | Task、Session、Execution、Evidence、Verdict、Recovery 模型与状态机 |
| Verification request | `PhyAgentOS/verification/request_builder.py` | 解析 Bundle、验证 digest/窗口/要求、构造多模态请求 |
| Verification engine | `PhyAgentOS/verification/engine.py` | 无状态模型调用与 timeout |
| Verification service | `PhyAgentOS/verification/service.py` | 独立进程、readiness、鉴权和严格 JSON 输出 |
| Verifier facade | `PhyAgentOS/agent/session_verifier.py` | budget、attempt、retention、lesson 与 review |
| Gateway client | `PhyAgentOS/forge/client.py` | `httpx.AsyncClient` 的 Agent API 封装 |
| Observation | `PhyAgentOS/forge/observation.py` | 异步 WebSocket、多 source 最新帧缓存与校验 |
| Evidence writer | `PhyAgentOS/forge/evidence.py` | 安全路径、原子写入、SHA-256、snapshot 与 Bundle |
| Adapter | `PhyAgentOS/forge/adapter.py` | 单 action 执行、identity、poll、timeout、cancel 和映射 |
| Store | `PhyAgentOS/forge/store.py` | SQLite WAL、事务、状态、事件和原子 replan |
| Orchestrator | `PhyAgentOS/forge/orchestrator.py` | 异步任务、mode、restart、recovery 和通知 |
| 配置 | `PhyAgentOS/config/schema.py` | Forge、Evidence、Verification、Embodiment Schema |

## 3. 公共模型

### 3.1 `ForgeTaskRequest`

```python
ForgeTaskRequest(
    task_description="Place the red object in the tray",
    action_type="<gateway-advertised-action>",
    inputs={...},
    verification=TaskVerificationContract(...),
    execution_timeout_s=300.0,
)
```

`inputs` 必须是有限 JSON 值；NaN、Infinity、不可序列化对象和空 `task_description`/`action_type` 被拒绝。

### 3.2 `TaskVerificationContract`

`mode != off` 时，goal 与至少一个 criterion 必填。criteria 和 constraints 中不能有空字符串。Evidence policy 默认要求 `rgb_image`，并允许任务覆盖 source；source 为空时使用 target-level Forge 配置或 readiness 发现。

### 3.3 `ExecutionRecord`

模型设置 `frozen=True`。它包含：

- PAOS/Gateway session ID 与 command ID；
- Gateway API/instance；
- action type 与 policy ID；
- normalized execution status；
- capability 声明的通用 `result_semantics` 和 `completion`；
- Gateway timeline、outputs 与 error。

不得在该模型中写入 task verdict，也不得因为 Verifier 不认可结果而把 Gateway `succeeded` 改为 `failed`。

### 3.4 `EvidenceBundle`

每个 artifact 包含 phase、kind、source ID、sequence、captured/received time、media type、byte size、SHA-256、安全 workspace-relative URI、retention 状态。`EvidenceQuality` 单独记录 completeness、association、missing requirements、stale artifacts 和 errors。

### 3.5 `VerificationVerdict`

Verifier 必须为输入的每条 success criterion 返回且只返回一个 `CriterionVerdict`，并逐字复制 criterion。`success` 要求全部 `satisfied`；`failure`/`replan_required` 至少有一项未满足或 unknown；`replan_required` 还必须提供动作无关的 `recovery_context`。

## 4. 状态机与事务

允许转换定义在 `ALLOWED_FORGE_TRANSITIONS`。Store 的所有 update 会先加载模型、执行 mutation、验证转换、更新时间、写 JSON、追加 event，再提交事务。

SQLite 表：

```text
forge_sessions
  session_id PRIMARY KEY
  command_id UNIQUE
  root_session_id
  parent_session_id UNIQUE
  status
  record_json
  created_at / updated_at

forge_events
  event_id PRIMARY KEY
  session_id FOREIGN KEY
  event_type
  created_at
  payload_json
```

`BEGIN IMMEDIATE` 用于任务创建与 replan，确保多个 PAOS Store 实例并发提交时仍只有一个 non-terminal lineage。

## 5. Gateway 启动契约

`ForgeAdapter.validate_capabilities()` 要求：

```json
{
  "api_version": "paos-forge-gateway-mvp-plus.v1",
  "supports": {
    "sessions": true,
    "command_id": true,
    "runtime_context": true,
    "serial_actions_only": true
  },
  "actions": {
    "<action_type>": {
      "policy_id": "...",
      "command": "...",
      "result_semantics": "command_completed",
      "completion": {},
      "required_parameters": [],
      "input_mapping": {}
    }
  }
}
```

Capability 中的 action metadata 用于 Planner 选择与 Execution Record，不用于选择 verifier 分支。

## 6. Adapter 执行协议

全新任务的顺序不可交换：

1. 检查 action capability。
2. 非 `off` 时启动 images/state collectors。
3. 等待 required sources，并原子写 before snapshot。
4. Orchestrator 持久化 `dispatching`/dispatch attempt。
5. POST `/agent/sessions`。
6. 校验 create response 的 session/command/action identity。
7. 轮询 `/agent/sessions/{session_id}`。
8. 只接受 `succeeded | failed | cancelled`；timeout 时请求 cancel。
9. 观察终态后等待更高 image sequence，再写 after snapshot。
10. 写 immutable Execution Record 和 Evidence Bundle。

Gateway payload 为：

```json
{
  "session_id": "forge_<generated>",
  "command_id": "command_<generated>",
  "action_type": "...",
  "instruction": "...",
  "source": "paos-agent",
  "inputs": {}
}
```

执行终态必须同时满足：

```text
session.session_id == requested session_id
command.command_id == requested command_id
command.session_id == requested session_id
command.request_id == requested command_id
session.action_type == requested action_type
command.action_type/policy_id/command == advertised capability identity
session.status == command.status in succeeded|failed|cancelled
```

## 7. Observation 与 Evidence

Collector 为每个 required image source 只保留最高 sequence 的合法帧；重复或乱序帧不会替换最新帧。连接断开后会重连，最近错误保留有界列表。

当前接受：

- `image/jpeg`/`image/jpg`；
- `image/png`；
- `image/webp`；
- JSON robot state。

除了 Base64 长度与实体大小限制，还检查 magic bytes。Artifact filename 包含安全化 source label、source digest 和 sequence，防止不同 source 安全化后发生路径冲突。所有 URI 必须是 workspace-relative 且不能包含 `..`。

`VerificationRequestBuilder` 在调用模型前再次检查：

- Bundle 与 session/command identity；
- completeness 与 minimum association；
- capture window 顺序；
- required kind/source 在 before/after 均存在；
- entity retained、存在、大小与 SHA-256 一致；
- image media type 与实体相符；
- evidence ID 唯一。

## 8. Verification Service

`ForgeTaskVerifier` 启动一个独立 Python 子进程。服务只监听配置 host/port，使用 per-process token 的 `X-PAOS-Admin-Token`，提供：

```text
GET  /healthz
POST /v1/verify-task
```

request version 为 `forge_verification_request_v1`。启动 readiness 固定有界，模型调用受 `timeoutS` 和 `maxVerifierCallsPerRun` 限制。

Prompt 只包含：

- task goal、success criteria、constraints；
- immutable Execution Record；
- Evidence Bundle 与实体；
- root lineage history；
- LESSONS；
- 合法 evidence IDs。

非法服务输出会被规范为 `inconclusive`，随后公共模型和 exact-criteria validator 继续校验。`audit` 记录错误；`enforce`/`recovery` fail closed。

## 9. Recovery

Verifier 只能建议 `replan_required`，不能输出 action type、策略参数或 Gateway input。Orchestrator 从 verdict 构造 `RecoveryRequest`，通过 `InboundMessage(channel="system")` 唤醒原 Agent session。

Planner 调用 `create_replanned_forge_session` 时：

- parent 必须仍为 `awaiting_replan`；
- deadline 未过期；
- replan budget 未耗尽；
- child 继承 verification contract、root lineage、来源路由与 source；
- Planner 重新提供 task description、action type、inputs；
- PAOS 生成新的 session/command ID；
- parent terminal 与 child create 原子提交；重复调用返回已有 child。

## 10. 扩展工作流

### 10.1 新增 Gateway action

action 实现与注册发生在 Forge Gateway/Runtime 仓库，而不是 PAOS：

1. 在 Gateway capabilities 中发布稳定 action identity。
2. 明确 `required_parameters`、`input_mapping`、`result_semantics` 和 `completion`。
3. 保证 create/get 返回完整且一致的 session/command identity。
4. 保证终态枚举符合契约。
5. 在 PAOS 中只增加通用 contract/fake Gateway 测试；不要添加 action-specific verifier flag。

### 10.2 新增证据 source

在 Gateway `/ws/images` 发布稳定 `id`、单调递增 `seq`、合法 `content_type` 和 Base64 数据；可选 `timestamp` 必须是真实 source time。PAOS target config 或 task evidence policy 引用 source ID。

需要新 evidence kind 时，应同时扩展公共契约、采集/写入、request builder、retention 和端到端测试，而不是在 action manifest 中塞入私有路径。

### 10.3 新增 Agent tool

只有当能力不能由七个通用 Forge tools 表达时才新增。新 tool 不得让调用者指定 session/command ID，不得直接 POST Gateway，不得绕过 Store/Orchestrator。

## 11. 错误与可观测性

稳定错误前缀用于运维分层：

| 类别 | 示例 |
|:-----|:-----|
| Gateway contract | `FORGE_GATEWAY_API_UNSUPPORTED`, `FORGE_GATEWAY_CAPABILITY_MISSING` |
| Action/correlation | `FORGE_ACTION_UNSUPPORTED`, `FORGE_EXECUTION_STATE_LOST` |
| Evidence | `FORGE_EVIDENCE_CONFIGURATION_REQUIRED`, `FORGE_EVIDENCE_UNAVAILABLE`, `VERIFICATION_EVIDENCE_UNAVAILABLE` |
| Verification | `VERIFICATION_INVALID_VERDICT`, `VERIFICATION_CALL_BUDGET_EXHAUSTED`, `VERIFICATION_SERVICE_UNAVAILABLE` |
| Recovery | `VERIFICATION_REPLAN_LIMIT_REACHED`, `VERIFICATION_REPLAN_TIMEOUT` |
| Execution | `GATEWAY_EXECUTION_TIMEOUT`, `GATEWAY_SESSION_FAILED`, `FORGE_SESSION_CANCELLED` |

SQLite event log 是编排审计源；Gateway 原始 create/last/cancel response 保存在 session record 中；公共 Artifact 提供跨进程可读事实。

## 12. 测试

```bash
python -m pip install -e ".[dev]"
pytest
ruff check PhyAgentOS tests
python -m compileall -q PhyAgentOS tests
```

测试应覆盖：

- model version、必填字段、非法状态/verdict/URI/digest；
- Store 并发、单活动 lineage、transition、原子 replan；
- Gateway API/support/action/identity/terminal/cancel/reset；
- 多 source、乱序、重复、陈旧帧、断线、非法媒体、超大 artifact；
- 四种 mode、缺证、Verifier 服务错误、retention 和 review 不改终态；
- restart 的 POST 前、POST 后 404、补采、验证中断与 recovery 去重；
- Agent tool 注册、system event 路由和 Forge disabled；
- repository guard，防止旧执行体系返回活动代码。

可选黑盒测试只通过 `FORGE_GATEWAY_URL` 连接运行中的 Gateway，不修改其源码或配置。

## 后续阅读

- [集成开发指南](../user_development_guide/README.md)
- [通信架构](../user_development_guide/COMMUNICATION.md)
- [Forge 接入契约](../forge/README_zh.md)
- [配置参考](04-forge-configuration-reference.md)
