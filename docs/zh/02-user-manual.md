# PhyAgentOS 用户手册

> 文档版本：0.1.4.post4。本文描述当前 Forge-only 执行链。PhyAgentOS 不再提供旧 Runtime、Watchdog 或 Markdown Session queue。

## 1. 环境与安装

基础要求：

- Python 3.11 或 3.12；
- Git；
- 一个受支持的 LLM Provider；
- 一个可访问的 Forge Gateway 1.0.0；
- 非 `off` 验证需要支持图像输入和结构化 JSON 输出的模型。

```bash
git clone https://github.com/PhyAgentOS/PhyAgentOS.git
cd PhyAgentOS
python -m pip install -e .

# 运行测试或参与开发
python -m pip install -e ".[dev]"
```

安装后主要命令如下：

```text
paos onboard
paos agent
paos gateway
paos status
paos channels status
paos channels login
paos provider login <provider>
```

## 2. 初始化

```bash
paos onboard
```

默认情况下，该命令创建或刷新：

```text
~/.PhyAgentOS/config.json
~/.PhyAgentOS/workspace/
```

如果配置已存在，选择“不覆盖”会在保留已有值的同时补全新字段。配置验证失败不会静默回退到旧执行链；根级 `runtime` 字段会触发明确错误，必须删除并改用 `forge`。

使用自定义配置或工作区：

```bash
paos agent --config /path/to/config.json --workspace /path/to/workspace
paos gateway --config /path/to/config.json --workspace /path/to/workspace
```

## 3. 配置模型 Provider

最小 Provider 示例：

```json
{
  "agents": {
    "defaults": {
      "model": "openrouter/openai/gpt-4o-mini",
      "provider": "openrouter",
      "workspace": "~/.PhyAgentOS/workspace"
    }
  },
  "providers": {
    "openrouter": {
      "apiKey": "YOUR_API_KEY"
    }
  }
}
```

Agent 与 Verifier 默认使用同一模型。若要分离，设置 `agents.verification.model` 和 `agents.verification.provider`。配置中的 API key 不应提交到版本控制；长期部署还应限制配置文件的访问权限。

OAuth Provider 可以使用：

```bash
paos provider login openai-codex
paos provider login github-copilot
```

## 4. 配置 Forge

```json
{
  "agents": {
    "verification": {
      "serviceEnabled": true,
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

启动 PAOS 时会读取 `/agent/runtime/capabilities`。以下任一条件不满足都会拒绝启动：

- `api_version` 精确等于 `paos-forge-gateway-mvp-plus.v1`；
- `supports.sessions`、`supports.command_id`、`supports.runtime_context` 为 true；
- `supports.serial_actions_only` 为 true；
- `actions` 是对象；随后提交的 action 必须存在于该对象。

`requiredImageSources` 中的 source ID 必须与 Gateway `/ws/images` 的 `id` 一致。若列表为空，PAOS 会从 runtime context 的 image readiness 中发现 source；若仍为空，非 `off` 任务会以 `FORGE_EVIDENCE_CONFIGURATION_REQUIRED` 失败。

完整字段与默认值见 [Forge 配置参考](04-forge-configuration-reference.md)。

## 5. 启动顺序

推荐顺序：

1. 启动 Forge Runtime/Dora/机器人或仿真环境；
2. 启动 Forge Gateway 1.0.0；
3. 确认 Gateway capabilities、status、context 和图像流可用；
4. 启动 PAOS Agent 或 Gateway。

交互模式：

```bash
paos agent
```

单消息模式：

```bash
paos agent -m "先读取 Forge capabilities，再执行一个受支持动作；使用 audit 验证并报告执行事实与任务判定。"
```

如果这条消息提交了 Forge task，单消息进程不会在首次模型回复后立即退出，而会保持 Agent 和 Orchestrator 运行，直到 root lineage 终结并处理 completion/recovery system event。

长期在线模式：

```bash
paos gateway
paos gateway --port 18790 --verbose
```

该入口同时运行 Agent、已启用消息渠道、Cron、Heartbeat 和 Forge Orchestrator。

## 6. 提交第一个任务

### 6.1 先读取能力

action type 和 inputs 由 Gateway 定义，不应从文档示例猜测。可以先告诉 Agent：

```text
调用 forge_get_context，列出当前 readiness、可用 action、required inputs 和 input mapping；不要执行动作。
```

### 6.2 描述目标与验收标准

推荐在请求中明确：

- 用户目标；
- 可接受的高层动作范围；
- 每条可观察、可独立判定的 success criterion；
- 必须保留的安全或任务 constraints；
- verification mode；
- 必需的 evidence source/kind。

示例：

```text
读取 Forge 能力，选择合适的高层动作把红色物体放入托盘。
使用 recovery 验证。Goal 是“红色物体最终位于托盘内”。
Criteria：1）最终图像中红色物体完整位于托盘边界内；
2）蓝色物体仍在原区域。Constraint：不要移动蓝色物体。
使用 front 图像作为 before/after 证据。
```

Agent 最终调用 `forge_execute_task` 时，会构造：

```json
{
  "task_description": "...",
  "action_type": "<advertised action>",
  "inputs": {},
  "verification": {
    "mode": "recovery",
    "goal": "红色物体最终位于托盘内。",
    "success_criteria": [
      "最终图像中红色物体完整位于托盘边界内。",
      "蓝色物体仍在原区域。"
    ],
    "constraints": ["不要移动蓝色物体。"],
    "evidence_policy": {
      "required_kinds": ["rgb_image"],
      "required_sources": ["front"],
      "minimum_association": "best_effort"
    }
  }
}
```

session ID 与 command ID 由 PAOS 生成，调用方不能指定、复用或从旧任务复制。

## 7. 验证模式

| 模式 | 何时使用 | 行为 |
|:-----|:---------|:-----|
| `off` | 只需知道 Gateway 命令是否结束 | 不采集验证 Evidence Bundle，不调用 Verifier，按 execution status 终结。 |
| `audit` | 先评估 verifier 质量，不希望阻塞执行结果 | 缺 before 证据时仍可派发；记录 verdict/error；最终状态保持执行派生结果；永不 replan。 |
| `enforce` | 任务完成必须有语义证据 | Verifier `success` 才成功；缺证、非法输出、错误、`failure`、`replan_required`、`inconclusive` 都失败。 |
| `recovery` | 失败后允许 Planner 再尝试 | 与 enforce 一样 fail closed；合法 `replan_required` 生成 Recovery Request。 |

非 `off` 模式必须提供非空 goal 和至少一项非空 success criterion，并要求 Verification Service 可用。

## 8. 查询、取消、复核和 Reset

Agent 可使用：

- `forge_get_session(session_id)`：返回完整持久化 record；
- `forge_cancel_session(session_id, reason)`：取消非终态任务；已派发时同时请求 Gateway cancel；
- `verify_forge_session(session_id)`：复核终态 session；要求证据仍 retained；
- `forge_reset(inputs)`：没有活动 lineage 时才允许 reset；
- `forge_get_context()`：读取启动时缓存的 capabilities，以及实时 status/context。

`verify_forge_session` 是 review，不会改变 `status`、Execution Record 或原自动验证尝试；它会追加 attempt 并更新 `verification_result.json` 中的验证视图。

## 9. 状态解释

| PAOS 状态 | 含义 | 是否终态 |
|:----------|:-----|:---------|
| `accepted` | 请求与 ID 已保存 | 否 |
| `capturing_before` | 等待并持久化执行前证据 | 否 |
| `dispatching` | dispatch attempt 已保存，正在 POST | 否 |
| `running` | Gateway session 未到终态 | 否 |
| `finalizing` | 写 Execution Record 并等待 after evidence | 否 |
| `awaiting_verification` | Evidence Bundle 已就绪，等待验证 | 否 |
| `verifying` | 独立 Verification Service 正在判定 | 否 |
| `awaiting_replan` | Recovery Request 已生成，等待 Planner child | 否 |
| `replanned` | parent 已由新 child 接替 | 是 |
| `succeeded` / `failed` | PAOS 按当前 mode 终结 | 是 |
| `timed_out` / `cancelled` | 执行超时或取消 | 是 |

在 `enforce`/`recovery` 中，应同时查看：

```text
record.status
record.execution.status
record.verification.verdict.verdict
record.error_code / record.error_message
```

它们分别表示 PAOS 任务结果、Gateway 执行事实、语义判定和故障原因。

## 10. Artifact 与 retention

```text
<workspace>/.paos/forge/orchestrator.sqlite3
<workspace>/artifacts/forge/<session_id>/
  execution_record.json
  before_snapshot.json
  after_snapshot.json
  evidence_bundle.json
  verification_result.json
  evidence/
```

Evidence retention：

| 值 | 实体证据处理 |
|:---|:-------------|
| `all` | 全部保留 |
| `failed` | 最终成功时删除实体，失败时保留 |
| `none` | 完成验证后删除实体 |

删除实体后，Evidence Bundle 仍保留 URI、source、phase、时间、sequence、byte size、SHA-256、`retained=false` 和 `deleted_at`，以便审计。Retention 不能删除或覆盖 Execution Record。

## 11. 重启与恢复

- 未记录 dispatch attempt：Orchestrator 可以继续执行。
- 已记录 dispatch attempt：只向 Gateway GET 原 session；绝不自动重发 action。
- 原 session 存在且身份匹配：继续等待终态、采集 after 或验证。
- 原 session 404：标记 `FORGE_EXECUTION_STATE_LOST`。
- 验证中断：旧 attempt 标记 abandoned 后重试。
- 等待 replan：可以再次发送 recovery system event；child 创建通过事务去重。

正常退出时，PAOS 会尝试取消活动 Gateway session，并保存 cancel response。物理系统仍需独立的安全停机与 operator override；PAOS cancel 不替代硬件急停。

## 12. Embodiment 与知识工作区

`EMBODIED.md`、`ENVIRONMENT.md`、SceneGraph 和 `embodiments` 配置属于知识层。单机模式使用 `agents.defaults.workspace`；fleet 模式可以组织 shared + per-robot 知识工作区，但当前仍只有一个 Forge endpoint 和一个串行执行槽。

```json
{
  "embodiments": {
    "mode": "fleet",
    "sharedWorkspace": "~/.PhyAgentOS/workspaces/shared",
    "instances": [
      {
        "robotId": "robot_001",
        "workspace": "~/.PhyAgentOS/workspaces/robot_001",
        "profileName": "lab-arm",
        "enabled": true
      }
    ]
  }
}
```

该配置不包含 driver、Target 或 Gateway routing 语义。

## 13. 旧工作区清理

PAOS 不自动删除用户已有文件。升级前先备份，再按需人工移除旧执行协议：

```text
RUNTIME.md
TARGETS.md
SKILLRUNTIME.md
SESSIONS.md
configs/runtime/
artifacts/runtime/
```

保留 `EMBODIED.md`、`ENVIRONMENT.md`、`LESSONS.md`、`TASK.md` 以及其他用户知识。当前代码不会读取或生成上述旧执行协议。

## 14. 故障排查

### 启动时 API 或 capability 失败

确认 URL 指向 Forge Gateway 1.0.0，并检查 `/agent/runtime/capabilities`。版本或 required supports 不能通过配置降级。

### `FORGE_ACTION_UNSUPPORTED`

请求的 `action_type` 不在启动时缓存的 capabilities 中。先调用 `forge_get_context`，按 advertised action 和 required inputs 重新规划。Gateway capability 发生变化后应重启 PAOS，使启动校验与 Agent 摘要一起刷新。

### `FORGE_EVIDENCE_CONFIGURATION_REQUIRED`

既没有配置 `requiredImageSources`，runtime context 也没有可发现图像源。填写实际 source ID，并确认 `/ws/images` 正在发布。

### `FORGE_EVIDENCE_UNAVAILABLE`

before 或 after 窗口缺少必须 source。检查 WebSocket、媒体格式、大小限制、source ID、sequence 是否递增，以及 capture timeout。

### `FORGE_EXECUTION_STATE_LOST`

PAOS 已记录 dispatch intent，但 Gateway 返回 404。系统故意不重发未知动作；应人工核实物理世界与 Gateway 日志后，再创建新的高层任务。

### `VERIFICATION_EVIDENCE_UNAVAILABLE`

Evidence Bundle 不完整、artifact 丢失/已删除、摘要不匹配，或 capture window 无效。若要显式复核，请将 retention 设为 `all` 或在失败时使用 `failed`。

### `VERIFICATION_INVALID_VERDICT`

模型没有为每条 criterion 返回且仅返回一条合法结论，或引用了未知 evidence ID。选择更稳定的模型，不要放宽公共契约。

### `VERIFICATION_SERVICE_UNAVAILABLE`

检查 Provider、模型、`servicePort` 冲突和 verifier timeout。`audit` 会记录错误并保留 execution 结果；`enforce`/`recovery` 会 fail closed。

### Busy / active lineage

另一个 root lineage 尚未终结。先使用 `forge_get_session` 查询，必要时取消。不要直接编辑 SQLite 绕过串行约束。

## 后续阅读

- [框架介绍](01-framework-introduction.md)
- [Forge 配置参考](04-forge-configuration-reference.md)
- [运行手册](../user_manual/README.md)
- [Forge 接入契约](../forge/README_zh.md)
- [文档索引](../README.md)
