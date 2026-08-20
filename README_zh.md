<div align="center">
  <img src="docs/imgs/logo_en.png" alt="PhyAgentOS" width="560">

  <h3>认知与物理解耦 —— 基于证据验证的 Forge 原生具身执行框架</h3>

  <p>
    <a href="https://github.com/PhyAgentOS/PhyAgentOS/stargazers">
      <img src="https://img.shields.io/github/stars/PhyAgentOS/PhyAgentOS?style=social" alt="Stars">
    </a>
    <a href="https://github.com/PhyAgentOS/PhyAgentOS/network/members">
      <img src="https://img.shields.io/github/forks/PhyAgentOS/PhyAgentOS?style=social" alt="Forks">
    </a>
  </p>
  <p>
    <img src="https://img.shields.io/badge/Python-≥3.11-3776AB?logo=python&logoColor=white" alt="Python">
    <img src="https://img.shields.io/badge/Version-v2.0.0-47A882" alt="Version">
    <img src="https://img.shields.io/badge/License-MIT-3DA639" alt="License">
    <a href="https://arxiv.org/pdf/2607.16636">
      <img src="https://img.shields.io/badge/技术报告-arXiv-b31b1b?logo=arxiv&logoColor=white" alt="技术报告">
    </a>
    <a href="https://phy-agent-os.net/">
      <img src="https://img.shields.io/badge/Website-online-FF6B35" alt="Website">
    </a>
    <a href="https://github.com/PhyAgentOS/PhyAgentOS">
      <img src="https://img.shields.io/badge/PRs-Welcome-2EA44F" alt="PRs">
    </a>
  </p>
  <p>
    <sub><a href="README.md">English</a> · <a href="README_zh.md">中文</a> · <a href="docs/README.md">文档</a></sub>
  </p>
</div>

---

PhyAgentOS 是一个面向具身任务的 Agent 框架。Agent 规划高层动作，Forge Adapter 记录 Gateway 的执行事实，观测采集器保存动作前后证据，任务级 Verifier 再判断用户目标是否真正达成。

> **核心规则：** Gateway 的 `succeeded` 是动作执行事实，不是任务成功证明。任务语义是否成功由 verification policy 决定。

## 📢 更新日志

| 版本 | 日期 | 更新内容 |
|:-----|:-----|:---------|
| ![v2.0.0](https://img.shields.io/badge/v2.0.0-47A882) | 2026-08-03 | 引入 Forge 执行架构，全面对接 Forge Gateway 1.0.0；新增不可变 Execution/Evidence 公共契约、系统级语义验证、Planner 主导的恢复、崩溃安全 SQLite 编排，并彻底移除旧 Runtime 执行链。 |
| ![v0.1.7](https://img.shields.io/badge/v0.1.7-47A882) | 2026-07-05 | 支持 Policy loop 与 Target-native builtin 两条 Benchmark 路径，并加入 Agent 验证与失败恢复服务。 |
| ![v0.1.6](https://img.shields.io/badge/v0.1.6-47A882) | 2026-06-27 | 增加 BEHAVIOR-1K 支持、`SessionVerifier` 与显式 Session 验证工具。 |
| ![v0.1.5](https://img.shields.io/badge/v0.1.5-47A882) | 2026-06-11 | 清理协议文件与文档，将游戏场景迁移到 `general-game-agent` 分支，主线聚焦仿真与真机工作。 |
| ![v0.1.4](https://img.shields.io/badge/v0.1.4-11648A) | 2026-06-05 | 改进 onboarding、补充通信协议、优化代码规范，并推进 Game Agent 与 Benchmarking。 |
| ![v0.1.3](https://img.shields.io/badge/v0.1.3-11648A) | 2026-05-25 | 建立严格的 `PolicySkillRuntime` / `BuiltinSkillRuntime` 分离，并推进 Game Agent Benchmark。 |
| ![v0.1.2](https://img.shields.io/badge/v0.1.2-11648A) | 2026-05-20 | 引入感知插件系统、Sensor/Perception 配置与可审计的 Environment 写回。 |
| ![v0.1.1](https://img.shields.io/badge/v0.1.1-11648A) | 2026-05-18 | 发布 Session-Centered Runtime MVP 与初始 Dummy Simulation 执行链。 |
| ![v0.1.0](https://img.shields.io/badge/v0.1.0-11648A) | 2026-04-29 | 发布 Hackathon 基线，包括插件化 HAL 与早期 ReKep、SAM3、抓取和 VLN 流程。 |

## 为什么选择 PhyAgentOS？

<table>
<tr><td width="32">🧭</td><td width="190"><b>唯一执行边界</b></td><td>机器人动作统一进入版本化 Forge Gateway 契约；Agent 不直接访问策略、仿真器、Dora 节点或硬件 SDK。</td></tr>
<tr><td>🔎</td><td><b>先证据，后结论</b></td><td>命令前后的图像与可选机器人状态经过校验后落盘，保留 source、sequence、时间、大小、摘要和 retention 信息。</td></tr>
<tr><td>🧠</td><td><b>动作无关验证</b></td><td>Verifier 只接收 goal、criteria、constraints、执行事实、证据、lineage history 与 lessons，不设计动作专用开关。</td></tr>
<tr><td>🧱</td><td><b>崩溃安全编排</b></td><td>SQLite 事务持久化身份、状态与 dispatch intent。已尝试派发的任务在重启后只查询，不盲目重发 POST。</td></tr>
<tr><td>🔄</td><td><b>Planner 主导恢复</b></td><td>恢复判定只产生不可执行的上下文；正常 Planner 必须用全新 session/command ID 创建 child action。</td></tr>
</table>

## 架构

```text
用户 / 消息渠道 / 定时事件
              │
              ▼
      AgentLoop + Planner
              │  Forge tools
              ▼
   ForgeSessionOrchestrator ───────► SQLite Session + Event Store
              │
       ┌──────┴───────────────┐
       ▼                      ▼
  ForgeAdapter          ForgeTaskVerifier
       │                 goal + criteria
       │ HTTP            execution + evidence
       │ WebSocket              │
       ▼                        ▼
Forge Gateway 1.0.0       verdict / recovery request
       │
       ▼
Forge Runtime + Dora + 机器人/仿真器
```

系统始终分离三类事实：

1. **Execution**：Gateway 接收了什么命令，以及命令如何终结。
2. **Evidence**：PAOS 在命令执行前后观察到了什么。
3. **Verdict**：每一项系统级 success criterion 是否满足。

## 核心能力

| 领域 | 当前能力 |
|:-----|:---------|
| Forge 契约 | 严格接受 `paos-forge-gateway-mvp-plus.v1`，要求 sessions、command ID、runtime context 和串行动作能力。 |
| 异步编排 | 提交立即返回；执行、证据采集、验证、通知和恢复在后台继续。 |
| 身份校验 | Gateway session ID、command ID、request ID、action type、command identity 和 policy identity 必须全部匹配。 |
| 证据 | 通过 `/ws/images`、`/ws/state` 异步采集；使用有界最新帧缓存、媒体校验、SHA-256 和 source sequence 边界。 |
| 验证 | 支持 `off`、`audit`、`enforce`、`recovery`，并生成逐 criteria 的结构化 verdict。 |
| 恢复 | parent/child 原子转换、replan 预算、deadline、全新 ID 和 system event 唤醒正常 Planner。 |
| 持久化 | SQLite WAL 事件日志与工作区 JSON/图像 artifact；Execution Record 不会被复核或 retention 覆盖。 |
| Agent 平台 | CLI、多渠道 Gateway、Provider、工具、Skills、MCP、记忆、Cron、Heartbeat 和知识工作区。 |

## 5 分钟快速开始

### 1. 安装

```bash
git clone https://github.com/PhyAgentOS/PhyAgentOS.git
cd PhyAgentOS
python -m pip install -e .

# 开发与测试依赖
python -m pip install -e ".[dev]"
```

推荐 Python 3.11 或 3.12。Forge Gateway 是外部服务，需要独立启动。

### 2. 初始化工作区

```bash
paos onboard
```

该命令创建 `~/.PhyAgentOS/config.json`，并在 `~/.PhyAgentOS/workspace` 初始化默认工作区。

### 3. 配置 Provider 与 Forge

配置保存为 camelCase，同时也接受 snake_case 输入。

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.PhyAgentOS/workspace",
      "model": "openrouter/openai/gpt-4o-mini",
      "provider": "openrouter"
    },
    "verification": {
      "serviceEnabled": true,
      "evidenceRetention": "failed",
      "maxReplansPerEpisode": 2,
      "maxVerifierCallsPerRun": 50
    }
  },
  "providers": {
    "openrouter": {
      "apiKey": "YOUR_API_KEY"
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

`front` 只是示例；应填写 Gateway context 中实际可用的 source ID，也可以把全局列表留空，让 PAOS 从 readiness 中发现图像源。Gateway 1.0.0 只提供 `best_effort` 证据关联，因此要求 `authoritative` 的任务会在执行前被拒绝。

### 4. 启动 Agent

先启动 Forge Gateway，再选择一种 PAOS 入口：

```bash
# 交互式 CLI
paos agent

# 单条请求；如果 Agent 提交 Forge 任务，进程会等待该 lineage 终结
paos agent -m "先检查 Forge 能力，再把物体放入目标区域，并根据可见结果验证任务。"

# 长期运行消息渠道、Cron、Heartbeat、Agent 与 Forge 编排器
paos gateway
```

使用 `paos status` 检查本地模型与工作区配置；通过 Agent 调用 `forge_get_context` 获取启动时缓存的 action capabilities，以及实时 Forge readiness、status 和 context。

## 验证模式

| 模式 | 任务契约 | 最终结果 | 恢复 |
|:-----|:---------|:---------|:-----|
| `off` | goal/criteria 可省略 | 跟随 Gateway 执行状态 | 永不恢复 |
| `audit` | 必须提供 goal 和至少一项 criterion | 保持执行派生终态，只记录 verdict/error | 永不恢复 |
| `enforce` | 必须提供 goal 和至少一项 criterion | verdict 决定成功；缺证、非法输出、服务错误和 `inconclusive` 均 fail closed | 不恢复 |
| `recovery` | 必须提供 goal 和至少一项 criterion | 与 enforce 一样 fail closed；`replan_required` 进入恢复 | Planner 新建 child |

典型的非 `off` 契约如下：

```json
{
  "mode": "recovery",
  "goal": "红色方块位于托盘内。",
  "success_criteria": [
    "红色方块在图像中完全位于托盘边界内。",
    "没有其他物体被移出工作区。"
  ],
  "constraints": [
    "不要移动蓝色方块。"
  ],
  "evidence_policy": {
    "required_kinds": ["rgb_image"],
    "required_sources": ["front"],
    "minimum_association": "best_effort"
  }
}
```

## Agent 可用的 Forge 工具

| 工具 | 用途 |
|:-----|:-----|
| `forge_execute_task` | 提交一个高层动作并立即返回全新的 PAOS session/command ID。 |
| `forge_get_session` | 读取持久化任务、Gateway 执行、证据、verdict、recovery 与错误。 |
| `forge_cancel_session` | 取消未终结任务；若已派发，同时请求 Gateway cancel。 |
| `forge_get_context` | 读取启动时缓存的 capabilities，以及实时 runtime status、readiness 和 context。 |
| `forge_reset` | 仅在没有活动 PAOS lineage 时显式 reset Gateway。 |
| `verify_forge_session` | 用保留证据复核终态任务，不改变终态和 Execution Record。 |
| `create_replanned_forge_session` | 为 `awaiting_replan` parent 原子创建一个全新 child。 |

这些工具只在 `forge.enabled=true` 时注册。

## 持久化与工作区

```text
~/.PhyAgentOS/workspace/
├── AGENTS.md / SOUL.md / USER.md / TOOLS.md / SKILLS.md
├── EMBODIED.md / ENVIRONMENT.md / LESSONS.md / TASK.md
├── .paos/forge/orchestrator.sqlite3
└── artifacts/forge/<session_id>/
    ├── execution_record.json
    ├── evidence_bundle.json
    ├── verification_result.json
    ├── before_snapshot.json / after_snapshot.json
    └── evidence/
```

`EMBODIED.md`、`ENVIRONMENT.md` 和 SceneGraph 继续作为知识面存在，但不承担执行队列职责。PAOS 不再读取或生成旧 Runtime Markdown queue 文件。

## 支持范围

- 一个 PAOS 进程只配置一个 Forge Gateway endpoint。
- 一个 root task lineage 在验证或恢复终结前独占串行执行槽。
- 一个 Forge session 对应一个高层 Gateway action；长任务由 Planner 拆分。
- Gateway、Forge Runtime、Dora dataflow、策略内部和硬件驱动不属于本仓库修改范围。
- Gateway 1.0.0 的证据关联为 `best_effort`；PAOS 不伪造 authoritative 时间或因果关系。
- 旧 PAOS Runtime、Target、SkillRuntime、Watchdog、SessionRunner 和 Markdown 执行队列兼容性已明确移除。

## 项目结构

```text
PhyAgentOS/
├── PhyAgentOS/agent/          # AgentLoop、工具、记忆、Verifier 集成
├── PhyAgentOS/forge/          # Gateway client、观测、Adapter、Store、Orchestrator
├── PhyAgentOS/verification/   # 公共契约、请求构造、Engine、Service
├── PhyAgentOS/channels/       # 消息渠道
├── PhyAgentOS/config/         # 配置 Schema 与加载
├── PhyAgentOS/templates/      # Agent 知识/工作区模板
├── docs/                      # 中英文、运维、接入与 Forge 文档
├── plan/                      # 历史设计与评审报告
└── tests/                     # 契约、Store、Gateway、证据、Verifier、E2E 测试
```

## 文档

| 文档 | 面向 | 内容 |
|:-----|:-----|:-----|
| [文档索引](docs/README.md) | 所有人 | 双语阅读路径与完整文档地图 |
| [框架介绍](docs/zh/01-framework-introduction.md) | 架构师、用户 | 设计、边界、生命周期和当前能力 |
| [用户手册](docs/zh/02-user-manual.md) | 使用与运维人员 | 安装、配置、任务、Artifact 和排障 |
| [开发者手册](docs/zh/03-developer-manual.md) | 开发者 | 契约、不变量、扩展点和测试 |
| [Forge 配置参考](docs/zh/04-forge-configuration-reference.md) | 部署人员 | Forge、Evidence、Verification 和 Task 精确字段 |
| [运行手册](docs/user_manual/README.md) | 运维人员 | 启动、监控、重启、取消与故障处理 |
| [集成开发指南](docs/user_development_guide/README.md) | 生态开发者 | 不引入 action-specific verifier 的 Gateway action 接入方式 |
| [Forge 接入契约](docs/forge/README_zh.md) | Gateway/PAOS 开发者 | HTTP/WebSocket、身份、证据、验证、恢复和重启契约 |

## 开发验证

```bash
python -m pip install -e ".[dev]"
pytest
ruff check PhyAgentOS tests
python -m compileall -q PhyAgentOS tests
```

可选黑盒测试可以通过 `FORGE_GATEWAY_URL` 连接运行中的兼容 Gateway。测试与 PAOS 文档不得修改 Gateway 源码或配置。

## 参与贡献

欢迎提交 PR 和 Issue，我们的开发计划可以在此处查看👉 [开发计划](https://phy-agent-os.net/docs/developer-guide/)。

---

<div align="center">

由 **中山大学 HCP 实验室**、**鹏城实验室** 与 **拓元智慧** 联合开发

<br>

<img src="docs/imgs/HCP.jpg" alt="HCP" height="128">
&nbsp;&nbsp;&nbsp;
<img src="docs/imgs/Pengcheng.png" alt="Pengcheng" height="128">
&nbsp;&nbsp;&nbsp;
<img src="docs/imgs/logo-xera-mark.png" alt="X-Era Lab" height="128">

<br>
<sub>MIT License · Copyright © 2025-2026 PhyAgentOS</sub>

</div>
