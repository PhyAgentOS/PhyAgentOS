<div align="center">
  <img src="docs/imgs/logo_en.png" alt="PhyAgentOS" width="560">

  <h3>自进化物理智能体操作系统<br>面向具身智能的统一运行时基座</h3>

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
    <img src="https://img.shields.io/badge/License-MIT-3DA639" alt="License">
    <a href="https://phy-agent-os.net/">
      <img src="https://img.shields.io/badge/🌐_Website-online-FF6B35" alt="Website">
    </a>
    <a href="https://github.com/PhyAgentOS/PhyAgentOS">
      <img src="https://img.shields.io/badge/PRs-Welcome-2EA44F" alt="PRs">
    </a>
  </p>
  <p>
    <sub><a href="./README.md">English</a> · <a href="./README_zh.md">中文</a></sub>
  </p>
</div>

---

## 📢 更新日志

| 版本 | 日期 | 更新内容 |
|:-----|:-----|:---------|
| ![v0.1.7](https://img.shields.io/badge/v0.1.7-11648A) | 2026-07-11 | General Game Agent：三阶递进游戏环境（我的世界 → 星露谷 → 饥荒）；认知记忆积累与长程经验固化；自进化分析流水线 |
| ![v0.1.6](https://img.shields.io/badge/v0.1.6-47A882) | 2026-06-27 | 支持 Behavior 1K Benchmark；用于 Agent 校验的 SessionVerifier; VerifySessionTool |
| ![v0.1.5](https://img.shields.io/badge/v0.1.5-47A882) | 2026-06-11 | 清理协议文件及文档，game 场景分离至 `general-game-agent` 分支独立推进；当前分支聚焦仿真 & 真机重构 |
| ![v0.1.4](https://img.shields.io/badge/v0.1.4-11648A) | 2026-06-5 | 优化用户友好的启动流程; 通信协议规范; 更合理的代码规范; Game Agent & Benchmarking 就绪 |
| ![v0.1.3](https://img.shields.io/badge/v0.1.3-11648A) | 2026-05-25 | `PolicySkillRuntime` / `BuiltinSkillRuntime` 边界严格分离，Game Agent & Benchmarking 就绪 |
| ![v0.1.2](https://img.shields.io/badge/v0.1.2-11648A) | 2026-05-20 | 感知插件体系：`SensorConfig` / `PerceptionConfig` YAML + `EnvironmentWriter` 可审计写回 |
| ![v0.1.1](https://img.shields.io/badge/v0.1.1-11648A) | 2026-05-18 | Session-Centered Runtime MVP：`DummySimTarget` + `DummyAdapter` + `DummyClient` 串行链路 |
| ![v0.1.0](https://img.shields.io/badge/v0.1.0-11648A) | 2026-04-29 | Hackathon 基线：插件化 HAL，ReKep / SAM3 真机抓取与 VLN 全链路 |

---

## 🧭 三条范式，各自差一口气

当前具身智能有三条主流技术路线——每一条都有自己的盲区，而 PhyAgentOS 填的就是这个缺：

| 范式 | 能做什么 | 缺什么 |
|:--|:--|:--|
| **VLA 端到端（π0, OpenVLA, FluxVLA）** | "看见 → 动作" 的连续控制 | 无任务拆解、无失败恢复、换机器人就重来 |
| **代码策略（LLM→Code→Robot）** | 用自然语言生成可执行计划 | 经不起真实世界的随机扰动；无闭环验证；换硬件就断链 |
| **世界模型（视频→预测）** | 从当前状态预测未来 | 预测 ≠ 动作；无执行落地、无安全护栏 |

**PhyAgentOS 不替代任何一条——它编排它们。** 在模型与硬件之间作为统一运行底座，回答四个问题：*该调谁、谁来执行、怎么才算成功、失败了怎么办。*

---

## 🤔 为什么选择 PhyAgentOS？

传统的"大模型直连硬件"方案高度耦合，换一个机器人就要重写整个执行链路。PhyAgentOS 通过 **认知-物理解耦 + Session-Centered Runtime** 彻底改变了这一点：

<table>
<tr><td width="32">🔌</td><td><b>同代码，万硬件</b> — 新增机器人只需实现一个 Target Adapter（~100 行），调度层零改动。已支持 19 种本体（真机 7 种、仿真 12+ 种、游戏 3 种）。</td></tr>
<tr><td>🛡️</td><td><b>三层安全护栏</b> — Critic 校验 → 严格预检 → 目标端 SafetyGuard；真机部署强制启用。</td></tr>
<tr><td>📋</td><td><b>全程可审计</b> — 状态、动作、感知结果均以 Markdown + YAML 文件记录；每一步可追溯、可复现。</td></tr>
<tr><td>🔄</td><td><b>零摩擦迁移</b> — 同一套 Session 协议在仿真和真机之间无缝运行，认知层代码零改动。</td></tr>
<tr><td>🎮</td><td><b>Game → Sim → Real 闭环</b> — 先在游戏环境（我的世界 / 星露谷 / 饥荒）低成本验证认知策略，再迁移同一智能层到仿真（LIBERO / Behavior 1K）和真机，认知层完全不变。</td></tr>
<tr><td>🧠</td><td><b>自进化</b> — 认知记忆跨会话积累长程经验；失败教训自动记录、检索、复用。评测即编排：自动评估多种策略（π0、π0.5、OpenVLA、X-VLA），聚合证据，持续进化。</td></tr>
</table>

<br>

<div align="center">
  <img src="docs/imgs/framework.svg" alt="Architecture" width="960">
  <p><sub>▲ Session-Centered Runtime 总体架构</sub></p>
</div>

---

## ✨ 核心特性

<table>
<tr>
  <td width="32">🔄</td>
  <td width="165"><b>Session-Centered Runtime</b></td>
  <td><code>WatchdogSupervisor</code> → <code>SessionRunner</code> → <code>SkillRuntime</code> → <code>TargetSessionHandle</code> 四级执行链路，替代传统 Driver-Center 架构</td>
</tr>
<tr>
  <td>🎯</td>
  <td><b>Target-Configured</b></td>
  <td>三种目标类型 — <code>debug</code> / <code>simulation</code> / <code>real_robot</code> — 在 <code>TARGETS.md</code> 中注册，按需挂载 adapter</td>
</tr>
<tr>
  <td>🧩</td>
  <td><b>Adapter + Bridge</b></td>
  <td><code>TargetAdapter</code> + <code>PolicyAdapter</code> + <code>ActionBridge</code> 三向解耦，显式 observation/action 合约；<code>AdapterPlan</code> 自动组合，消除 target×skill 组合爆炸</td>
</tr>
<tr>
  <td>⚡</td>
  <td><b>双轨 Skill Runtime</b></td>
  <td><code>PolicySkillRuntime</code> 维护策略闭环 + <code>BuiltinSkillRuntime</code> 管理 Agent 交互循环</td>
</tr>
<tr>
  <td>🛡️</td>
  <td><b>严格预检</b></td>
  <td>运行时校验（target / sensor / perception / adapter 合约 / action 合约 / tool）；不通过即 <code>rejected</code>，杜绝执行前盲飞</td>
</tr>
<tr>
  <td>✅</td>
  <td><b>SessionVerifier 语义验收</b></td>
  <td>对执行结果做语义级别验证——对比初始 vs 最终 RGB、任务定义、环境快照与历史记录；判定 <code>succeeded</code> / <code>failed</code> / <code>replanned</code>，证据存入 <code>LESSONS.md</code></td>
</tr>
<tr>
  <td>📝</td>
  <td><b>文件协议矩阵</b></td>
  <td><code>TARGETS.md</code> · <code>SKILLRUNTIME.md</code> · <code>SESSIONS.md</code> · <code>ENVIRONMENT.md</code> · <code>LESSONS.md</code> + 外部 YAML 配置</td>
</tr>
<tr>
  <td>🔐</td>
  <td><b>多层安全</b></td>
  <td>Critic 校验 → 预检合约检查 → 目标端 SafetyGuard → 操作员接管</td>
</tr>
<tr>
  <td>🌐</td>
  <td><b>集群模式</b></td>
  <td>多机器人协同，共享 + 独立工作区，基于优先级的串行调度</td>
</tr>
<tr>
  <td>🧠</td>
  <td><b>认知记忆</b></td>
  <td>跨会话积累长程经验；失败教训自动记录、检索、复用于未来任务——在部署周期中实现系统自进化</td>
</tr>
<tr>
  <td>📊</td>
  <td><b>评测即编排</b></td>
  <td>评估是第一公民能力：自动选择基准、排队执行、并行跑分、聚合证据、产出实验报告——已支持 π0、π0.5、OpenVLA、X-VLA 在 LIBERO 和 Behavior 1K 上自动评测</td>
</tr>
</table>

---

## 🎮 Game → Sim → Real 三阶验证管线

PhyAgentOS 提供业界独有的**三阶递进验证闭环**：认知层始终不变，变的只是执行目标。

```
Game（认知验证）              Sim（策略评测）              Real（物理部署）
─────────────────         ──────────────────         ──────────────────
我的世界 → 星露谷             LIBERO → Behavior 1K       Franka · Go2 · PIPER
    → 饥荒                                             AgileX · RM65-B · BOBABOT
       │                          │                          │
       └────────同一个 Session 协议，零认知层改动──────────┘
```

1. **Game**：低成本、高并发的游戏环境，剥离复杂物理，专注验证规划、记忆与决策能力
2. **Sim**：在标准具身基准上评测策略；「评测即编排」——Agent 自动选择、排队、执行、出报告
3. **Real**：同一套协议、同一个智能层，驱动真实机器人，带完整安全护栏

---

## 🚀 5 分钟快速上手

<table>
<tr>
<td width="28" align="center">1</td>
<td>

**安装**

```bash
git clone https://github.com/PhyAgentOS/PhyAgentOS.git && cd PhyAgentOS
pip install -e .            # Python ≥ 3.11
pip install -e ".[dev]"     # 开发依赖
```
</td>
</tr>
<tr>
<td align="center">2</td>
<td>

**初始化工作区**

```bash
paos onboard
```
</td>
</tr>
<tr>
<td align="center">3</td>
<td>

**启动 Agent**

```bash
paos agent
```
</td>
</tr>
<tr>
<td align="center">4</td>
<td>

**可选：接入 Runtime 服务**

```bash
# LIBERO benchmark TargetWS 服务端
MUJOCO_GL=egl PYTHONWARNINGS=ignore \
conda run -n liberopi python PhyAgentOS/runtime/targets/remote/libero/server.py \
  --host 0.0.0.0 --port 9002

# pi0.5 策略服务端
conda run -n lerobot-pi python -m PhyAgentOS.runtime.policy.openpi.lerobot_pi0_server \
  --model-dir /path/to/pi05/checkpoint --host 0.0.0.0 --port 8000
```
</td>
</tr>
</table>

`paos agent` 和 `paos gateway` 会自动创建工作区并在配置启用 runtime 时启动 session watchdog。
runtime 目标在 `TARGETS.md` 中声明，可执行 runtime 在 `SKILLRUNTIME.md` 中注册，
Agent 通过向 `SESSIONS.md` 追加 session 来排队执行任务。

Agent 端语义验证默认关闭。如需在运行时完成后根据最终 RGB 观察和工作区历史进行检查，可在 `~/.PhyAgentOS/config.json` 中启用：

```json
{
  "agents": {
    "verification": {
      "enabled": true,
      "model": null,
      "maxReplans": 1,
      "rgbRetention": "failed"
    }
  }
}
```

启用验证后，runtime 成功的 session 会依次进入 `awaiting_verification` 和 `verifying` 状态。
Agent 将其标记为 `succeeded` 或 `failed`，或标记为 `replanned` 并追加一个替换的 `pending` session。
证据存储在 `artifacts/runtime/<session_id>/` 下，每条裁决记录在 `LESSONS.md`。
`rgbRetention` 可选 `all`、`failed` 或 `none`；默认 `failed` 策略在验证成功后删除 RGB，保留失败和重规划的记录。
Agent 可以调用 `verify_session` 处理等待中的 session，或检查 RGB 尚未清除的已终止 session。

```bash
paos agent -m "run the configured LIBERO benchmark task"
```

---

## 🗂️ 协议文件

| 上下文加载方式 | 文件 | 归属 | 用途 |
|:--|:--|:--|:--|
| 始终载入 Agent 系统提示 | `AGENTS.md` | Agent 工作区 | 项目级 Agent 运行规则 |
| 始终载入 Agent 系统提示 | `SOUL.md` | Agent 工作区 | 身份、高层行为与助手风格 |
| 始终载入 Agent 系统提示 | `USER.md` | Agent 工作区 | 用户偏好与持久化档案 |
| 始终载入 Agent 系统提示 | `TOOLS.md` | Agent 工作区 | 工具使用策略与可用工具指引 |
| 始终载入 Agent 系统提示 | `SKILLS.md` | Agent 工作区 | Agent 侧 skill 发现与加载规则 |
| 启用时加载，按运行时目标过滤 | `EMBODIED.md` | Agent 工作区 | 可读的目标能力描述 |
| 作为状态（非引导策略）加载 | `ENVIRONMENT.md` | Agent/Runtime 工作区 | 当前目标与场景/环境状态 |
| 作为记忆/状态加载 | `LESSONS.md` | Agent 工作区 | 操作经验与失败笔记 |
| 作为任务状态加载 | `TASK.md` | Agent 工作区 | 多步骤任务拆解与进度 |
| 调度 session 前读取 | `RUNTIME.md` | Runtime 工作区 | 如何编写有效 runtime session |
| 调度 session 前读取 | `TARGETS.md` | Runtime 工作区 | 启用的目标、端点/adapter/配置引用、支持的 skill runtime |
| 调度 session 前读取 | `SKILLRUNTIME.md` | Runtime 工作区 | 策略/内置 skill runtime 注册表与执行合约 |
| 由 Agent 和 watchdog 写入 | `SESSIONS.md` | Runtime 工作区 | 待执行/执行中/已完成 session 及结果 |

`SKILLS.md` 用于 Agent 能力与 skill 发现。`SKILLRUNTIME.md` 用于 runtime 执行合约，与 `TARGETS.md`、`SESSIONS.md` 配合使用。

---

## 📦 项目结构

```
PhyAgentOS/
│
├── PhyAgentOS/agent/          # Track A  ─  Planner / Critic / Memory
│
├── PhyAgentOS/runtime/        # Track B  ─  执行平面
│   ├── watchdog/              #   WatchdogSupervisor
│   ├── sessions/              #   SessionRunner / TargetSessionHandle
│   ├── targets/               #   RolloutTarget (debug·sim·real)
│   │   └── remote/libero/     #   LIBERO benchmark TargetWS 服务端 + 代理
│   ├── skillruntime/          #   PolicySkillRuntime / BuiltinSkillRuntime
│   ├── adapters/              #   TargetAdapter / PolicyAdapter / Bridge
│   │   ├── libero/            #   LIBERO target adapter
│   │   └── openpi/            #   OpenPI policy adapter
│   ├── policy/openpi/         #   OpenPI 客户端 + LeRobot pi0 系列服务端
│   ├── perception/            #   感知运行时 / EnvironmentWriter
│   ├── preflight/             #   RuntimeCompatibilityPreflight
│   └── schemas/               #   Pydantic Schema
│
├── configs/runtime/           # Sensor / Perception / Contract YAML
├── scripts/                   # 工具脚本
├── workspace/                 # Agent 工作区；runtime 文件可通过配置共享
├── docs/                      # 文档
└── tests/                     # 测试
```

---

## 🏷️ 支持的目标平台

| | 类型 | 部署位置 | 示例 |
|:--|:-----|:-----|:-----|
| 🐛 | `debug` | 本地 | echo / mock / dry-run — 零硬件协议链路验证 |
| 🎮 | `game` | 本地 | 我的世界、星露谷、饥荒 — 认知验证，物理假设最小化 |
| 🧪 | `simulation` | 远端 | RoboCasa、LIBERO、Behavior 1K — 基准评测与批量经验采集 |
| 🤖 | `real_robot` | 远端 | Franka、Go2、PIPER AgileX、RM65-B RealMan、BOBABOT、XLeRobot — 真机 7 种、仿真 12+ 种，共 19 种本体 |

> 所有目标在 `TARGETS.md` 中注册，以 `target_adapter://` URI 标识。
> 更多示例 → [项目网站](https://phy-agent-os.net/)

---

## 📖 文档

| 文档 | 受众 | 说明 |
|:-----|:-----|:-----|
| [🌐 网站](https://phy-agent-os.net/docs/en/architecture.html) | 所有人 | 完整文档、架构详解、演示视频 |
| [📘 用户手册](https://phy-agent-os.net/docs/en/api-reference.html) | 用户 | 安装、部署与操作指南 |
| [📙 开发者指南](https://phy-agent-os.net/docs/en/developer-guide.html) | 开发者 | 二次开发、硬件集成、插件编写 |

---

## 🤝 参与贡献

欢迎提交 PR 和 Issue！开发路线图 → [Dev Plan](https://phy-agent-os.net/docs/en/developer-guide.html)。

---

<div align="center">

由 **中山大学 HCP Lab** · **鹏城实验室** · **X-Era Lab** 联合研发

<br>

<img src="docs/imgs/HCP.jpg" alt="HCP" height="128">
&nbsp;&nbsp;&nbsp;
<img src="docs/imgs/Pengcheng.png" alt="Pengcheng" height="128">
&nbsp;&nbsp;&nbsp;
<img src="docs/imgs/logo-xera-mark.png" alt="X-Era Lab" height="128">

<br>
<sub>MIT License · Copyright © 2025-2026 PhyAgentOS</sub>

</div>
