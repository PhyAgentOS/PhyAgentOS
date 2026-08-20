# PhyAgentOS 通信架构

> 版本：0.1.4.post4 · [English](COMMUNICATION_en.md)

## 1. 五个通信边界

PhyAgentOS 不用一条内部总线混合用户消息、物理执行与验证：

1. **用户消息边界**：Channel ↔ MessageBus ↔ AgentLoop。
2. **Agent/Forge 编排边界**：Agent tools ↔ `ForgeSessionOrchestrator`。
3. **PAOS/Gateway 边界**：异步 HTTP + WebSocket。
4. **Verifier 边界**：Orchestrator ↔ 独立 Verification Service 进程。
5. **持久化边界**：Orchestrator ↔ SQLite；Adapter/Verifier ↔ workspace artifacts。

```text
External Channel
      │ InboundMessage / OutboundMessage
      ▼
  MessageBus ─ AgentLoop ─ Forge tools ─ Orchestrator
                                          │
                ┌─────────────────────────┼────────────────────┐
                ▼                         ▼                    ▼
          HTTP / WebSocket             SQLite          Verification HTTP
                ▼                         ▼                    ▼
          Forge Gateway             Event Store          Child process
                │
                ▼
        Forge Runtime / Dora
```

## 2. 用户消息边界

Channel 将外部消息转换为 `InboundMessage`。AgentLoop 根据 `session_key` 加载上下文、调用模型与工具，再产生 `OutboundMessage`。CLI 单消息可直接调用 `process_direct`，但内部 Planner 与 Forge tools 相同。

Channel 不得：

- 直接调用 Gateway；
- 直接写 SQLite/Artifact；
- 生成或复用 Forge session/command ID；
- 把 Gateway `succeeded` 直接报告为任务成功。

## 3. Agent/Orchestrator 边界

Forge tools 是 Agent 唯一可用的执行接口：

```text
forge_execute_task
forge_get_session
forge_cancel_session
forge_get_context
forge_reset
verify_forge_session
create_replanned_forge_session
```

`forge_execute_task` 立即返回生成的 ID 与 `accepted`，不阻塞模型调用等待物理执行。Orchestrator 在后台推进状态，并通过 system event 把终态送回原 `session_key`。

Completion event 包含：

```json
{
  "session_id": "...",
  "root_session_id": "...",
  "status": "succeeded|failed|timed_out|cancelled",
  "execution_status": "succeeded|failed|timed_out|cancelled|unknown",
  "verification_verdict": "success|failure|replan_required|inconclusive|null",
  "error_code": null,
  "error_message": null
}
```

Recovery event 包含 parent、goal、criteria、preserved constraints、unmet criteria、guidance、evidence refs 和 deadline。它明确要求 Planner 调用 `create_replanned_forge_session`，但不携带可执行 action。

## 4. PAOS/Gateway HTTP

| Method | Path | PAOS 用途 | 状态影响 |
|:-------|:-----|:----------|:---------|
| GET | `/agent/runtime/capabilities` | 启动契约与 action 发现 | 启动前校验/缓存 |
| GET | `/agent/runtime/status` | `forge_get_context` 实时状态 | 只读 |
| GET | `/agent/runtime/context` | readiness、image source 与上下文 | 只读/证据 source 发现 |
| POST | `/agent/runtime/reset` | 显式 reset | 仅无活动 lineage |
| POST | `/agent/sessions` | 创建唯一高层 action | dispatch intent 持久化后才调用 |
| GET | `/agent/sessions/{session_id}` | 唯一执行终态来源 | queued/running/terminal |
| POST | `/agent/sessions/{session_id}/cancel` | timeout、用户取消、正常停机 | 保存 cancel response |

`ForgeGatewayClient` 使用 `httpx.AsyncClient`，关闭 proxy environment 继承（`trust_env=False`），统一解析 JSON object。HTTP 错误或 `ok=false` 转换为 `ForgeGatewayError`，并保留 HTTP status code 供 404 restart 语义使用。

## 5. Session/command identity

PAOS 为一次动作生成：

```text
session_id = forge_<random>
command_id = command_<random>
```

POST 后每次响应都必须保持：

```text
response session_id == PAOS session_id
response command_id == PAOS command_id
command.session_id == PAOS session_id
command.request_id == PAOS command_id
session.action_type == request.action_type
command action_type/policy_id/command == advertised capability
```

PAOS 不把 Gateway 新生成的 ID 当作 alias，也不接受模糊关联。解析阶段即使只有一个 command，后续仍必须通过严格 identity 校验。

## 6. PAOS/Gateway WebSocket

### `/ws/images`

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

PAOS 记录 Gateway `timestamp` 为 `captured_at`（如果提供），并独立记录本机 `received_at`。per-source sequence 是 before/after 边界的一部分。

### `/ws/state`

消息为 JSON object。Gateway 1.0.0 没有统一 source timestamp 字段，因此 PAOS 保存完整 payload 和本机 `received_at`，`captured_at=null`。

### 连接语义

- HTTP(S) base URL 自动映射到 WS(S)；
- images 与 state 独立连接、独立重连；
- collector 只保留各 source 的最高合法 sequence；
- 非 required source 可忽略；
- 连接、消息与校验错误进入 Bundle quality，不伪装成有效证据。

## 7. Gateway terminal 语义

唯一终态源是 `GET /agent/sessions/{session_id}`。PAOS 接受：

```text
session.status == command.status == succeeded | failed | cancelled
```

PAOS 不使用固定等待、机器人静稳、图像是否变化、command outputs 内容或 WebSocket state 猜测终态。

Execution timeout 由 PAOS deadline 产生 `timed_out`，随后调用 cancel；它不是 Gateway 报告的原生 terminal。

## 8. Verification Service 边界

独立子进程提供本地 HTTP：

| Method | Path | 用途 |
|:-------|:-----|:-----|
| GET | `/healthz` | 最多等待有界 readiness |
| POST | `/v1/verify-task` | 提交 `forge_verification_request_v1` |

请求需要随机派生的 `X-PAOS-Admin-Token`。Service 只接收已解析的公共 contracts、多模态 evidence、history 和 lessons。它不访问 Gateway，也不创建 recovery child。

## 9. 持久化边界

### SQLite

SQLite 保存 `ForgeSessionRecord` JSON、唯一身份、状态索引与 append-only event。数据库是 Orchestrator 的恢复依据；业务代码不直接修改表。

### Artifact

Adapter 使用原子文件替换写：

```text
execution_record.json
before_snapshot.json / after_snapshot.json
evidence_bundle.json
evidence/*
```

Verifier 写 `verification_result.json` 与 `LESSONS.md`。Artifact URI 必须相对 workspace，读取时再次 resolve 并检查不越界。

### 一致性边界

SQLite 与 artifact 不是一个跨资源事务。因此关键顺序是：before entity/manifest 先完成再记录 reference；dispatch intent 在 HTTP mutation 前完成；Execution Record 首次写入后可在 DB commit crash window 中重新读取，但 identity 不匹配会失败。

## 10. 信任边界

| 数据 | 信任策略 |
|:-----|:---------|
| Gateway capabilities | 版本和结构严格校验，action identity 在每次 response 重验 |
| Gateway JSON | 必须为 object，HTTP/`ok=false` 失败 |
| WebSocket image | Base64、size、media type、magic bytes、sequence 全校验 |
| Artifact | safe URI、existence、byte size、SHA-256、media type 再校验 |
| Verifier output | JSON、Pydantic、exact criteria、known evidence refs 校验 |
| Recovery guidance | 只作为 Planner context，不作为命令 |

## 后续阅读

- [集成开发指南](README.md)
- [开发者手册](../zh/03-developer-manual.md)
- [Forge 接入契约](../forge/README_zh.md)
