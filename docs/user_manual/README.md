# PhyAgentOS 运行手册

> 版本：v0.1.6 · [English](README_en.md)

本手册由 PhyAgentOS 开发团队面向部署、演示和运行维护人员编写。它聚焦“如何稳定运行”，架构总览与完整配置说明见[主用户手册](../zh/02-user-manual.md)。

## 1. 运行模型

PhyAgentOS 由 Agent 控制面和 Runtime 执行面组成：

```text
User/Channel → AgentLoop → SESSIONS.md → WatchdogSupervisor
                                      → Preflight
                                      → SessionRunner
                                      → Target + SkillRuntime + Policy
```

`paos agent` 适合本地交互和单轮调用；`paos gateway` 适合长期在线 Channel、Cron 与 Heartbeat。两者都会在 `runtime.enabled=true` 时准备 Runtime 工作区，并按 `runtime.autostartWatchdog` 启动 Watchdog。

## 2. 首次部署

```bash
git clone https://github.com/PhyAgentOS/PhyAgentOS.git
cd PhyAgentOS
python -m pip install -e .
paos onboard
```

编辑 `~/.PhyAgentOS/config.json`，至少设置模型和对应 Provider。检查配置：

```bash
paos status
```

启动交互：

```bash
paos agent
paos agent -m "列出当前可用的 Runtime Target"
```

## 3. 上线前检查

### Agent

- `agents.defaults.model` 能匹配已配置 Provider。
- `agents.defaults.workspace` 可写。
- 如使用 MCP，逐项确认 command/url 和凭据。
- 对外 Channel 使用 allowlist/mention policy 限制入口。

### Runtime

- `runtime.workspace` 指向预期工作区；未设置时与 Agent workspace 相同。
- `TARGETS.md` 仅启用计划使用的 Target。
- Remote Target Endpoint 使用 `targetws://host:port`。
- Policy Endpoint 使用 `dummy://`、`openpi://`、`policyws://` 或 `b1k-ws://`。
- Runtime Contract、Adapter ID、Action Shape 与 Target ID 一致。

### 外部服务

- TargetWS 与 Policy Server 必须先于 Session 启动。
- 用独立健康探针确认端口可达，不以进程存在代替协议可用。
- Simulator/Robot 依赖使用独立环境，避免污染 Agent 环境。

## 4. 工作区观察点

| 观察点 | 正常信号 | 异常信号 |
|---|---|---|
| `TARGETS.md` | Target enabled 且 Endpoint 正确 | Target ID/Contract 不匹配 |
| `SESSIONS.md` | 状态持续向终态推进 | 长时间停留 pending/running |
| `LOG.md` | 每次执行有历史记录 | Session 完成但无日志 |
| `ENVIRONMENT.md` | Target snapshot 时间更新 | Target 状态陈旧或错误 workspace |
| `artifacts/runtime/<id>/episode.json` | 结果、步数、错误字段完整 | Artifact 缺失或路径不可读 |
| `LESSONS.md` | 拒绝/失败有可操作说明 | 只有文本报错，无 Session 关联 |

## 5. Session 运维

普通执行链：

```text
pending → claimed → preflight_checking → running → finalizing → terminal
```

运维规则：

1. 不手工把 running Session 改成 succeeded。
2. Preflight rejected 时修正 Contract/Registry 后创建或显式重跑 Session。
3. `--session-id` 会重置目标 Session，限调试和受控复现使用。
4. `depends_on` 在 v0.1.6 尚未由 Scheduler 强制执行，不能作为生产编排保证。
5. 执行超时后 Target cleanup 是 best effort；外部 Runtime 必须实现幂等 cancel/close。

## 6. 无硬件验收

```bash
python scripts/init_runtime_workspace.py --workspace /tmp/paos-runtime
python scripts/run_runtime_watchdog.py \
  --workspace /tmp/paos-runtime --once --session-id sess_dummy_smoke
```

验收条件：

- `SESSIONS.md` 中状态为 `succeeded`
- `result.success=true`
- `artifacts/runtime/sess_dummy_smoke/episode.json` 存在
- `LOG.md` 包含该 Session

## 7. 场景入口

| 场景 | Target 入口 | Policy 入口 |
|---|---|---|
| LIBERO | `PhyAgentOS/runtime/targets/remote/libero/server.py` | `PhyAgentOS.runtime.policy.openpi.lerobot_pi0_server` |
| Isaac Sim | `PhyAgentOS/runtime/targets/remote/isaacsim/server.py` | Dummy/OpenPI 或 CommandSim |
| BEHAVIOR-1K | `external/b1k_bench/scripts/start_behavior1k_server.sh` | `start_b1k_openpi_policy_server.sh` |

旧 `hal/hal_watchdog.py --driver ...` 不属于 v0.1.6 当前运行入口。

## 8. 语义验收运维

Session 选择 `audit` 或 `recovery` 后，policy-loop 完成会进入 `awaiting_verification`。Verification Service 由 `paos agent` 自动管理，SessionVerifier 与 target-native episode verification 都通过该服务取得模型 verdict。

`evidenceRetention`：

- `all`：全部保留，便于复核但占用空间最大。
- `failed`：成功删除，失败/replan 保留。
- `none`：有效 verdict 后全部删除；默认。

## 9. 故障分层

| 阶段 | 常见错误 | 首要检查 |
|---|---|---|
| 配置加载 | Provider/API Key | `paos status`、模型前缀 |
| 调度 | pending 不动 | Watchdog、Target enable、引用 |
| Preflight | rejected | `missing_items`、Contract、Adapter |
| Target 连接 | protocol/connect error | Endpoint、服务顺序、网络 |
| Policy 推理 | timeout/payload error | Policy Scheme、Shape、超时 |
| 执行 | failed/timed_out | `episode.json`、Target status |
| 语义验收 | awaiting/error | Bundle、RGB、Verifier Provider |

## 10. 当前安全边界

v0.1.6 默认 Runtime 以仿真为主。当前 Preflight 不是完整真机安全认证；真实机器人集成必须在 Target 端独立实现并验证急停、工作空间、速度/力限制、Operator Override 和故障安全。

## 相关文档

- [主用户手册](../zh/02-user-manual.md)
- [框架介绍](../zh/01-framework-introduction.md)
- [开发者手册](../zh/03-developer-manual.md)
