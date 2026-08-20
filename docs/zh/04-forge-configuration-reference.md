# Forge 配置参考

> 适用于 PhyAgentOS 0.1.4.post4 与 Forge Gateway API `paos-forge-gateway-mvp-plus.v1`。

## 1. 配置位置与命名

默认配置为 `~/.PhyAgentOS/config.json`。`paos onboard` 创建或刷新该文件。`paos agent` 与 `paos gateway` 可通过 `--config` 和 `--workspace` 覆盖当前实例路径。

Pydantic 模型接受 camelCase 和 snake_case；`paos onboard` 保存为 camelCase。根级 `runtime` 字段被明确拒绝：

```text
legacy `runtime` configuration is unsupported; remove it and configure `forge`
```

## 2. `forge`

| JSON 字段 | 类型 | 默认值 | 约束与含义 |
|:----------|:-----|:-------|:-----------|
| `enabled` | boolean | `false` | 为 false 时不创建 Orchestrator，也不注册 Forge tools。 |
| `baseUrl` | string | `http://127.0.0.1:9001` | 必须以 `http://` 或 `https://` 开头；尾部 `/` 会移除。WebSocket 自动映射为 `ws://`/`wss://`。 |
| `apiVersion` | literal | `paos-forge-gateway-mvp-plus.v1` | 唯一接受的版本，不支持降级。 |
| `requestTimeoutS` | number | `10.0` | HTTP 请求 timeout，必须大于 0。 |
| `pollIntervalS` | number | `0.5` | session GET 轮询间隔，范围 `[0.1, 5.0]` 秒。 |
| `executionTimeoutS` | number | `300.0` | task 未显式指定时的 Gateway 执行 timeout，必须大于 0。 |
| `evidence` | object | 见下表 | Adapter 侧 best-effort 证据采集设置。 |

## 3. `forge.evidence`

| JSON 字段 | 类型 | 默认值 | 约束与含义 |
|:----------|:-----|:-------|:-----------|
| `requiredImageSources` | string[] | `[]` | 全局必需图像 source。task policy 非空时优先使用 task sources；二者都空时从 runtime context readiness 发现。 |
| `captureTimeoutS` | number | `5.0` | POST 前等待 before snapshot 的上限，必须大于 0。 |
| `postCaptureTimeoutS` | number | `5.0` | 观察 Gateway terminal 后等待新 sequence 的上限，必须大于 0。 |
| `connectionTimeoutS` | number | `2.0` | 每次 WebSocket connect timeout，必须大于 0。 |
| `maxArtifactBytes` | integer | `8388608` | 单个 image/state message 的最大实体大小，必须大于 0。 |
| `associationQuality` | literal | `best_effort` | Gateway 1.0.0 唯一支持值。 |

Source 解析优先级：

```text
task.verification.evidence_policy.required_sources（非空）
    > forge.evidence.requiredImageSources（非空）
    > /agent/runtime/context readiness.images keys
```

## 4. `agents.verification`

| JSON 字段 | 类型 | 默认值 | 约束与含义 |
|:----------|:-----|:-------|:-----------|
| `serviceEnabled` | boolean | `true` | 是否创建独立 Verification Service。非 `off` task 要求为 true 且服务可用。 |
| `model` | string/null | `null` | null 时使用 `agents.defaults.model`。 |
| `provider` | string/null | `null` | null 时按 verifier model 自动匹配 Provider。显式值必须存在于 providers。 |
| `timeoutS` | number | `180.0` | 单次模型验证 timeout，必须大于 0。 |
| `evidenceRetention` | enum | `none` | `all | failed | none`。 |
| `maxReplansPerEpisode` | integer | `2` | root lineage 最大 replan 数，必须大于等于 0。 |
| `maxVerifierCallsPerRun` | integer | `50` | 当前 PAOS 进程 verifier call budget；0 表示代码层不施加该 budget。 |
| `replanTimeoutS` | number | `120.0` | Planner 创建 child 的 deadline，必须大于 0。 |
| `serviceHost` | string | `127.0.0.1` | 子进程 HTTP 服务 bind host。 |
| `servicePort` | integer | `8100` | 范围 `1..65535`；同机多实例应使用不同端口。 |

Verification Service 启动 readiness 等待为有界操作。服务启动失败不会无限阻塞；Orchestrator 会记录错误，非 `off` 新任务也会被拒绝。

## 5. `ForgeTaskRequest`

Agent tool `forge_execute_task` 接受以下业务字段；`version` 与 `source` 使用模型默认值：

| 字段 | 类型 | 必填 | 说明 |
|:-----|:-----|:-----|:-----|
| `task_description` | string | 是 | 非空高层指令，发送为 Gateway `instruction`。 |
| `action_type` | string | 是 | 必须存在于启动时缓存的 `capabilities.actions`。 |
| `inputs` | JSON object | 是 | 必须可用严格 JSON 序列化且不含 NaN/Infinity。 |
| `verification` | object | 是 | 见下一节。 |
| `execution_timeout_s` | number | 否 | 大于 0；省略时使用 `forge.executionTimeoutS`。 |

调用方没有 `session_id` 或 `command_id` 字段。PAOS 生成 `forge_<uuid>` 与 `command_<uuid>`。

## 6. `TaskVerificationContract`

| 字段 | 类型 | 默认值 | 说明 |
|:-----|:-----|:-------|:-----|
| `mode` | enum | `off` | `off | audit | enforce | recovery`。 |
| `goal` | string | `""` | 非 `off` 必填；会 trim。 |
| `success_criteria` | string[] | `[]` | 非 `off` 至少一项；每项非空。 |
| `constraints` | string[] | `[]` | 需在验证与 recovery 中保留的限制；每项非空。 |
| `evidence_policy` | object | 默认 semantic policy | 证据要求。 |

### `evidence_policy`

| 字段 | 类型 | 默认值 | 说明 |
|:-----|:-----|:-------|:-----|
| `profile` | string | `semantic_default` | 通用 profile 标签；当前不触发 action-specific 代码。 |
| `required_kinds` | string[] | `["rgb_image"]` | before 与 after 都必须存在每种 kind。`robot_state` 会要求 `/ws/state`。 |
| `required_sources` | string[] | `[]` | 对 image kind，before/after 均需包含每个 source。 |
| `minimum_association` | enum | `best_effort` | `best_effort | authoritative`；当前 authoritative 在执行前失败。 |

## 7. Mode 行为矩阵

| 情况 | `off` | `audit` | `enforce` | `recovery` |
|:-----|:------|:--------|:----------|:-----------|
| 需要 goal/criteria | 否 | 是 | 是 | 是 |
| 创建 Evidence Bundle | 否 | 是 | 是 | 是 |
| before 缺失是否阻止 POST | 不适用 | 否 | 是 | 是 |
| Verifier error | 不适用 | 记录，保留 execution 终态 | failed | failed |
| `inconclusive` | 不适用 | 记录，保留 execution 终态 | failed | failed |
| `replan_required` | 不适用 | 不恢复 | failed | `awaiting_replan` |

## 8. `embodiments`

Embodiment 只配置知识拓扑，不选择执行 adapter：

| 字段 | 默认值 | 说明 |
|:-----|:-------|:-----|
| `mode` | `single` | `single | fleet`。 |
| `sharedWorkspace` | `~/.PhyAgentOS/workspaces/shared` | fleet 的 Agent shared workspace。 |
| `instances` | `[]` | 机器人知识 profile 列表。 |

Instance 字段：`robotId`、`workspace` 必填；`enabled=true`；`profileName` 与 `sharedEnvironment` 可选。额外字段被拒绝，因此旧 `driver` 字段必须删除。

## 9. 推荐配置

### 9.1 只验证执行链

```json
{
  "forge": {
    "enabled": true,
    "baseUrl": "http://127.0.0.1:9001"
  },
  "agents": {
    "verification": {
      "serviceEnabled": false
    }
  }
}
```

此配置只允许 `verification.mode=off` 的任务。

### 9.2 长期运行的验证配置

```json
{
  "agents": {
    "verification": {
      "serviceEnabled": true,
      "model": "openrouter/openai/gpt-4o-mini",
      "provider": "openrouter",
      "timeoutS": 180,
      "evidenceRetention": "failed",
      "maxReplansPerEpisode": 2,
      "maxVerifierCallsPerRun": 50,
      "replanTimeoutS": 120,
      "serviceHost": "127.0.0.1",
      "servicePort": 8100
    }
  },
  "forge": {
    "enabled": true,
    "baseUrl": "http://127.0.0.1:9001",
    "apiVersion": "paos-forge-gateway-mvp-plus.v1",
    "requestTimeoutS": 10,
    "pollIntervalS": 0.5,
    "executionTimeoutS": 300,
    "evidence": {
      "requiredImageSources": ["front"],
      "captureTimeoutS": 5,
      "postCaptureTimeoutS": 5,
      "connectionTimeoutS": 2,
      "maxArtifactBytes": 8388608,
      "associationQuality": "best_effort"
    }
  }
}
```

## 10. 配置检查

```bash
paos status
paos agent -m "调用 forge_get_context，仅报告 API version、supports、actions 和 readiness，不执行动作。"
```

`paos status` 检查本地 config、workspace、model 和 Provider；它不代替 `forge_get_context` 的实时 Gateway 检查。

## 后续阅读

- [用户手册](02-user-manual.md)
- [开发者手册](03-developer-manual.md)
- [运行手册](../user_manual/README.md)
- [Forge 接入契约](../forge/README_zh.md)
