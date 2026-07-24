# PhyAgentOS 框架介绍

> 文档版本：v0.1.6。本文只把仓库中已有代码、模板和测试覆盖的行为称为“当前能力”。

## 1. 项目定位

PhyAgentOS 是面向具身智能任务的 Agent 与执行 Runtime。框架将自然语言规划和物理执行拆为两个控制面：

- Track A（Agent）负责消息处理、上下文、模型调用、工具、记忆和任务规划。
- Track B（Runtime）负责 Session 调度、兼容性检查、Target/Policy 执行、状态回写和 Artifact。
- 两者通过工作区中的 Markdown + YAML 协议传递目标、能力和执行状态。

这种边界的目的不是隐藏硬件差异，而是把差异限制在 Target、Adapter、Policy Client 和 Runtime Contract 中，使 Agent 只依赖稳定的 Session 协议。

## 2. 当前架构

```text
CLI / Channels / Cron / Heartbeat
                │
                ▼
        AgentLoop + Tools
                │ append pending session
                ▼
 TARGETS.md + SKILLRUNTIME.md + SESSIONS.md
                │
                ▼
       WatchdogSupervisor
                │ claim → preflight
                ▼
          SessionRunner
                │
        ┌───────┴────────┐
        ▼                ▼
 PolicySkillRuntime  BuiltinSkillRuntime
        │                │
        └──── TargetSessionHandle ────┐
                                      ▼
                         local/remote RolloutTarget
```

一次 Session 的实际链路为：

1. `SessionScheduler` 从 `SESSIONS.md` 选择满足依赖的 pending Session。
2. `SessionRegistry` 原子 claim，并推进到 `preflight_checking`。
3. `RuntimeCompatibilityPreflight` 校验引用、Endpoint、Runtime 注册、Adapter、Contract、Sensor 和 Action Contract。
4. `SessionRunner` 依次调用 `build`、`configure_session` 和 `start_session`；
   普通 policy-loop Session 由它负责 reset，target-native benchmark 则把 reset
   交给声明过的 SkillRuntime/Target interface。
5. Skill Runtime 只能经 `TargetSessionHandle` 观察、执行 Action Chunk、刷新环境或调用受约束的 Target Tool。
6. Watchdog 写入 Episode、历史和最终状态；使用 `audit` 或 `recovery` 的
   policy-loop Session 进入 `awaiting_verification`，target-native verification
   则发生在 episode attempt 边界，root Session 不再重复校验。

## 3. 文件协议

| 文件 | 写入者 | 当前职责 |
|---|---|---|
| `RUNTIME.md` | RuntimeWorkspaceManager | 自动生成的 Session 编写规则，不是运行状态 |
| `TARGETS.md` | 用户/开发者，启动时可应用 enable override | Target 注册表、Endpoint、Adapter 和配置引用 |
| `SKILLRUNTIME.md` | 用户/开发者 | Skill Runtime 注册表、Policy/Adapter 和输入输出契约 |
| `SESSIONS.md` | Agent + Watchdog + Verifier | Session 队列、状态、结果与验收元数据 |
| `ENVIRONMENT.md` | Runtime/Perception | Target 快照、对象、场景关系和感知运行记录 |
| `LESSONS.md` | Runtime/Verifier | 可审计的失败与语义验收经验 |

Sensor、Perception 和 Runtime Contract 使用外部 YAML，避免把设备标定、模型和动作约束内联到 Markdown 注册表。

## 4. 当前已实现能力

### 4.1 Agent 控制面

- `paos onboard`、`paos agent`、`paos gateway`、`paos status` 和 OAuth provider login。
- CLI、11 个 Channel 实现、Cron、Heartbeat、MCP、内置工具和后台 Subagent。
- 文件化上下文、会话 JSONL、Token 窗口压缩和长期记忆。
- Agent 管理的 Verification Service 统一模型 prompt 和严格 verdict 规范化；
  SessionVerifier 应用 policy-loop 结论，target-native benchmark 在 attempt
  边界请求 episode verdict。

### 4.2 Runtime 执行面

- Session 状态机、原子 claim、依赖/优先级调度、超时和失败写回。
- `PolicySkillRuntime` 与 `BuiltinSkillRuntime` 两类执行后端。
- Target/Policy Adapter、显式 Action Bridge 和严格 AdapterPlan。
- msgpack-over-WebSocket 的远程 Target 协议；本地 Target 使用同构生命周期。
- Target-configured Perception、Environment v2 合并写回和 Episode Artifact。

### 4.3 已注册 Runtime

| 类型 | 当前注册实现 |
|---|---|
| Local Target | `DummySimTargetRuntime` |
| Remote Target | `RemoteTargetProxy`、`LiberoRemoteTargetProxy`、`IsaacSimRemoteTargetProxy`、`Behavior1KRemoteTargetProxy` |
| Skill Runtime | `OpenPISkillRuntime`、`CommandSimSkillRuntime` |
| Policy Client | Dummy、OpenPI/PolicyWS、BEHAVIOR-1K WebSocket |
| Target Adapter | Dummy、LIBERO、Isaac Sim、BEHAVIOR-1K |
| Action Bridge | `bridge://safety_clamp` |

仓库模板提供 Dummy、LIBERO、PiperGo2/Merom Isaac Sim 与 BEHAVIOR-1K Target。Schema 允许 `game`、`debug`、`simulation`、`real_robot` 四类 Target，但 v0.1.6 默认注册和模板主要覆盖 simulation；Schema 支持不等于已有可运行后端。

## 5. v0.1.6 版本范围

我们对 v0.1.6 的公开能力范围作如下界定：

- Session-Centered Runtime 已取代原 Driver-Centered `hal/`、`BaseDriver` 和 `hal_watchdog.py` 路径。仓库中的部分历史示例不属于当前可安装 Runtime API。
- 当前没有注册的 `real_robot` Target Runtime。真机侧安全闭环和 Operator Override 尚未达到 HAL v3 的完整要求。
- Preflight 已校验 real-robot Tool 暴露必须受约束，但尚未完整强制 `operator_override_required`、所有 SafetyGuard 限制和在线 Healthcheck。
- `SKILLRUNTIME.md` 中部分 Isaac Sim 条目当前使用 `strict_environment_contract: false`；这与 HAL v3“第一阶段固定为 true”的目标设计不同。
- Goal Graph、Session Compiler、Fallback Chain、通用 CompositeTarget 和完整多 Target 编排尚未实现。
- Fleet 配置当前实现的是共享/实例工作区布局与上下文解析，不等同于完整的多机器人执行编排器。

## 6. 后续设计方向

以下方向来自 `PhyAgentOS HAL v3.md`，属于目标设计：

1. 将所有 Skill Runtime 收敛到严格 Environment Contract，取消模板中的非严格例外。
2. 完整实现 real-robot Target-side SafetyGuard、Workspace Bounds、Operator Override 和 Healthcheck 门禁。
3. 补齐 Agent-interactive Builtin Runtime、受约束 Target Tool Manifest 和真实机器人 Runtime。
4. 实现 Goal Graph、Session Compiler、长短期目标拆分及显式失败升级策略。
5. 扩展确定性的 Observation/Action Bridge 链，禁止隐式裁剪、补齐和表示转换。
6. 在统一 Session 协议上完善多 Target、多 Skill Runtime 与长期 Fleet 编排。

我们会在这些方向完成 Schema、Preflight、Runtime 和端到端测试后，再将其纳入当前能力文档。

## 7. 代码结构

```text
PhyAgentOS/
├── PhyAgentOS/agent/              # AgentLoop、Context、Memory、Tools、Verifier
├── PhyAgentOS/channels/           # 消息渠道
├── PhyAgentOS/config/             # 配置 Schema 与加载
├── PhyAgentOS/runtime/
│   ├── watchdog/                  # 调度、claim、状态与结果
│   ├── sessions/                  # SessionRunner、TargetSessionHandle
│   ├── targets/                   # Local/Remote RolloutTarget
│   ├── skillruntime/              # Policy/Builtin Runtime
│   ├── adapters/                  # Target/Policy Adapter 与 Bridge
│   ├── policy/                    # Policy Client/Server
│   ├── perception/                # 感知计划与 EnvironmentWriter
│   ├── communication/             # Envelope、msgpack、TargetWS
│   └── schemas/                   # Runtime Pydantic Schema
├── PhyAgentOS/templates/          # 工作区与 Runtime 模板
├── external/isaac_env/              # Isaac Sim rollout 服务
├── external/b1k_bench/      # BEHAVIOR-1K 集成
├── scripts/                       # 初始化、Watchdog、E2E 工具
└── tests/                         # 单元与 Runtime 测试
```

## 后续阅读

- [用户手册](02-user-manual.md)
- [开发者手册](03-developer-manual.md)
- [文档索引](../README.md)
