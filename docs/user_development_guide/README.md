# PhyAgentOS 集成开发指南

> 版本：0.1.4.post4 · [English](README_en.md)

本指南面向 Forge Gateway、机器人能力、证据源、LLM Provider 和 PAOS Agent 工具的集成开发者。当前机器人执行只通过 Forge Gateway 1.0.0；PAOS 不再内置 Target/Policy/SkillRuntime/SessionRunner 扩展点。

## 1. 选择正确扩展点

| 需求 | 应修改的位置 | PAOS 侧工作 |
|:-----|:-------------|:------------|
| 新机器人/仿真环境 | Forge Runtime / Dora / hardware integration | 不新增 driver；确认 Gateway contract 可用 |
| 新高层动作 | Forge Gateway capabilities 与 action dispatch | 通常无需产品代码，只补通用 contract/E2E 测试与文档 |
| 新 policy | Forge action 背后的 policy/runtime | capability 暴露通用 policy identity/result semantics |
| 新摄像头 | Gateway `/ws/images` producer | 配置 source ID，测试 before/after sequence |
| 新结构化状态 | Gateway `/ws/state` 或公共 evidence-kind 扩展 | 若新增 kind，同时扩展 contracts/resolver/retention/test |
| 新 verifier 模型 | PAOS Provider 配置/实现 | 保证多模态输入与严格 JSON 输出 |
| 新 Agent 入口 | PAOS Channel | 经 MessageBus/AgentLoop，不能直接调用 Gateway |
| 新执行工具 | 优先复用通用 Forge tools | 不能绕过 Orchestrator/Store，也不能暴露调用方 ID |

## 2. 接入一个 Gateway action

### 2.1 Capability 声明

Gateway 在 `/agent/runtime/capabilities` 的 `actions` 中发布 action：

```json
{
  "actions": {
    "place_object": {
      "description": "Place an object in a target area.",
      "policy_id": "manipulation_policy",
      "command": "place_object",
      "required_parameters": ["object", "target"],
      "input_mapping": {
        "object": "object",
        "target": "target"
      },
      "result_semantics": "command_completed",
      "completion": {
        "source": "policy_command_status"
      }
    }
  }
}
```

字段原则：

- `description`、`required_parameters`、`input_mapping` 帮助 Planner 构造合法 inputs；
- `policy_id` 与 `command` 组成执行 identity，create/get response 必须一致；
- `result_semantics` 与 `completion` 说明 Gateway “完成”意味着什么；
- 不要在 capability 中加入 `verify_grasp`、`grasp_verify_enabled` 或 verifier prompt；
- action-specific 结果可放在 command `outputs`，但任务成功仍由 criteria 判定。

### 2.2 Create 与 Get

PAOS POST：

```json
{
  "session_id": "forge_<paos-generated>",
  "command_id": "command_<paos-generated>",
  "action_type": "place_object",
  "instruction": "Place the red object in the tray.",
  "source": "paos-agent",
  "inputs": {
    "object": "red object",
    "target": "tray"
  }
}
```

Gateway create/get 响应需要让 PAOS 解析出：

```json
{
  "ok": true,
  "data": {
    "session": {
      "session_id": "forge_<same>",
      "action_type": "place_object",
      "status": "running"
    },
    "command": {
      "command_id": "command_<same>",
      "session_id": "forge_<same>",
      "request_id": "command_<same>",
      "action_type": "place_object",
      "policy_id": "manipulation_policy",
      "command": "place_object",
      "status": "running"
    }
  }
}
```

终态时 session/command `status` 必须相同，并且只使用 `succeeded`、`failed`、`cancelled`。PAOS 不从 outputs、静稳或固定等待推断终态。

### 2.3 Cancel

`POST /agent/sessions/{session_id}/cancel` 接收 reason。Gateway 应尽力终止尚未完成的 command，并返回可持久化的 JSON 响应。即使 cancel transport 失败，PAOS 仍会保存失败详情并终结自己的任务状态。

## 3. 接入图像证据

`/ws/images` 每条消息应为 JSON：

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

要求：

- `id` 在重连和整个部署中保持稳定；
- 每个 source 的 `seq` 单调递增；
- `timestamp` 可省略；提供时必须有限且表示真实 source time；
- `content_type` 为 JPEG、PNG 或 WebP，且实体 magic bytes 一致；
- 单帧实体不超过 PAOS `maxArtifactBytes`；
- Gateway 终态后仍要发布至少一个更新 sequence，以满足 after 边界。

多摄像头独立维护 sequence。不要把相机名编码进 action type，也不要依赖数组顺序区分 source。

## 4. 接入 robot state

当 task `required_kinds` 包含 `robot_state` 时，PAOS 要求 before/after 都有 `/ws/state` 消息。消息必须是 JSON object，大小受 `maxArtifactBytes` 限制。

Gateway 1.0.0 state message 没有统一 source timestamp 契约，因此 PAOS 只记录 `received_at`。如果未来增加 authoritative timestamp，应先升级公共 Gateway/Evidence contract，而不是让 Adapter 猜测字段。

## 5. 设计 Task Verification Contract

集成方不为 action 创建 verifier 分支，而是帮助 Agent/用户写可观察标准。

不推荐：

```text
goal: grasp succeeded
criterion: policy returned succeeded
```

推荐：

```text
goal: object is held securely above the table
criteria:
  - final image shows the object clear of the table surface
  - gripper and object maintain visible contact
constraints:
  - no other object leaves the workspace
```

Gateway command status可以作为执行证据，但不能替代环境结果证据。

## 6. Provider 与 Verifier 接入

Verifier Provider 通过现有 Provider registry 选择。集成新 Provider 时需要支持：

- `chat_with_retry()`；
- system + multimodal user content；
- `temperature=0`；
- timeout/cancellation；
- 返回纯 JSON object；
- 在独立 Verification Service 子进程中可由 serializable provider spec 重建。

公共输出必须通过 `VerificationVerdict` 校验，并且 exactly-once 覆盖全部 criteria、只引用合法 evidence ID。

## 7. PAOS 侧扩展边界

### 可以扩展

- 新的通用 evidence kind；
- 新的 public-contract version（需要显式版本与迁移决策）；
- Gateway-neutral observation transport reliability；
- Store/event observability；
- Provider；
- Channel 或其他非执行入口。

### 不应引入

- action-specific verifier 开关或 prompt；
- PAOS 内部 robot SDK/Policy client；
- 第二套 SessionRunner 或文件 queue；
- 基于固定 sleep、静稳、outputs 猜测 Gateway terminal；
- 调用者指定 session/command ID；
- 绕过 Store 直接 POST/重发；
- 把 verdict 写回 Execution Record。

## 8. Fake Gateway 测试闭环

默认集成测试应使用本地 fake HTTP/WebSocket server，模拟真实 Gateway shape：

1. capabilities 通过严格校验；
2. collectors 接收全部 before sources；
3. 验证 before snapshot 已落盘后才允许 create；
4. create 返回匹配 identity；
5. GET 依次返回 queued/running/terminal；
6. terminal 后发布更高 sequence；
7. 断言 Execution/Evidence/Verification 与最终状态；
8. 覆盖 timeout/cancel、404 resume、断线、乱序、缺证和非法 identity。

可选真实 Gateway 测试只读取 `FORGE_GATEWAY_URL`，不得改写 Gateway 源码、配置或运行时数据。

## 9. 接入验收清单

- [ ] Gateway API version 与四项 required supports 正确。
- [ ] action capability 完整且 identity 稳定。
- [ ] required inputs/input mapping 可供 Planner 理解。
- [ ] create/get/cancel 使用一致的响应 envelope。
- [ ] `request_id == command_id`。
- [ ] session/command/action/policy/command identity 全程一致。
- [ ] terminal status 枚举与 session/command 一致。
- [ ] 每个图像 source ID 稳定、sequence 单调。
- [ ] before 可在 POST 前获得，after 可在 terminal 后获得。
- [ ] 任务标准不依赖 action-specific verifier 代码。
- [ ] Fake Gateway 成功与全部关键拒绝路径通过。

## 后续阅读

- [开发者手册](../zh/03-developer-manual.md)
- [通信架构](COMMUNICATION.md)
- [Forge 接入契约](../forge/README_zh.md)
- [配置参考](../zh/04-forge-configuration-reference.md)
