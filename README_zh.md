<div align="center">
  <img src="docs/imgs/logo_en.png" alt="PhyAgentOS" width="560">

  <h3>认知与物理解耦 —— 面向具身智能的 Session-Centered 运行时</h3>

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
    <a href="https://sysu-hcp-eai.github.io/PhyAgentOS-website/">
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
| ![v0.1.7](https://img.shields.io/badge/v0.1.7-47A882) | 2026-07-5 | 支持 Policy loop 以及 Target native builtin 路径的 Benchmarking，并加入了 Agent 验证与失败恢复服务 ｜
| ![v0.1.6](https://img.shields.io/badge/v0.1.6-47A882) | 2026-06-27 | 支持 Behavior 1K Benchmark；用于 Agent 校验的 SessionVerfier; VerifySessionTool|
| ![v0.1.5](https://img.shields.io/badge/v0.1.5-47A882) | 2026-06-11 | 清理协议文件及文档，game 场景分离至 `general-game-agent` 分支独立推进；当前分支聚焦仿真 & 真机重构 |
| ![v0.1.4](https://img.shields.io/badge/v0.1.4-11648A) | 2026-06-5 | 优化用户友好的启动流程; 通信协议规范; 更合理的代码规范; Game Agent & Benchmarking 就绪 |
| ![v0.1.3](https://img.shields.io/badge/v0.1.3-11648A) | 2026-05-25 | `PolicySkillRuntime` / `BuiltinSkillRuntime` 边界严格分离，Game Agent & Benchmarking 就绪 |
| ![v0.1.2](https://img.shields.io/badge/v0.1.2-11648A) | 2026-05-20 | 感知插件体系：`SensorConfig` / `PerceptionConfig` YAML + `EnvironmentWriter` 可审计写回 |
| ![v0.1.1](https://img.shields.io/badge/v0.1.1-11648A) | 2026-05-18 | Session-Centered Runtime MVP：`DummySimTarget` + `DummyAdapter` + `DummyClient` 串行链路 |
| ![v0.1.0](https://img.shields.io/badge/v0.1.0-11648A) | 2026-04-29 | Hackathon 基线：插件化 HAL，ReKep / SAM3 真机抓取与 VLN 全链路 |

---

## 🤔 为什么选择 PhyAgentOS？

传统的"大模型直连硬件"方案高度耦合，换一个机器人就要重写整个执行链路。PhyAgentOS 通过 **认知-物理解耦 + Session-Centered Runtime** 彻底改变了这一点：

<table>
<tr><td width="32">🔌</td><td><b>同代码，万硬件</b> — 新增机器人只需实现一个 Target Adapter（~100 行），调度层零改动。</td></tr>
<tr><td>🛡️</td><td><b>三道安全防线</b> — Critic 校验 → Strict Preflight → Target-side SafetyGuard，真机场景不可绕过。</td></tr>
<tr><td>📋</td><td><b>全程可审计</b> — 状态、动作、感知结果以 Markdown + YAML 落盘，每一步可追溯复现。</td></tr>
<tr><td>🔄</td><td><b>零摩擦迁移</b> — 同一套 Session 协议在 sim / real 2类 target 上无差别运行。</td></tr>
</table>

<br>

<div align="center">
  <img src="docs/imgs/framework_zh.svg" alt="架构图" width="960">
  <p><sub>▲ Session-Centered Runtime 架构全览</sub></p>
</div>

---

## ✨ 核心特性

<table>
<tr>
  <td width="32">🔄</td>
  <td width="160"><b>Session-Centered Runtime</b></td>
  <td><code>WatchdogSupervisor</code> → <code>SessionRunner</code> → <code>SkillRuntime</code> → <code>TargetSessionHandle</code> 执行链路，抛弃 Driver-Center 旧架构</td>
</tr>
<tr>
  <td>🎯</td>
  <td><b>Target-Configured</b></td>
  <td> <code>debug</code> / <code>simulation</code> / <code>real_robot</code> 三类 target，<code>TARGETS.md</code> 统一注册，adapter 按需挂载</td>
</tr>
<tr>
  <td>🧩</td>
  <td><b>Adapter + Bridge</b></td>
  <td><code>TargetAdapter</code> + <code>PolicyAdapter</code> + <code>ActionBridge</code> 三段解耦，并显式声明 observation/action 契约；<code>AdapterPlan</code> 自动编排，消灭 target×skill 组合爆炸</td>
</tr>
<tr>
  <td>⚡</td>
  <td><b>双轨 Skill 运行时</b></td>
  <td><code>PolicySkillRuntime</code> 维护 policy 闭环 + <code>BuiltinSkillRuntime</code> 管理 target-native benchmark、受约束 agent 交互等内建闭环</td>
</tr>
<tr>
  <td>🛡️</td>
  <td><b>Strict Preflight</b></td>
  <td>运行时前置校验（target / sensor / perception / adapter contract / action contract / tool），不合格直接 <code>rejected</code></td>
</tr>
<tr>
  <td>📝</td>
  <td><b>文件协议矩阵</b></td>
  <td><code>TARGETS.md</code> · <code>SKILLRUNTIME.md</code> · <code>SESSIONS.md</code> · <code>ENVIRONMENT.md</code> · <code>LESSONS.md</code> + 外部 YAML</td>
</tr>
<tr>
  <td>🔐</td>
  <td><b>多层安全</b></td>
  <td>Critic 校验 → Preflight 契约检查 → Target-side SafetyGuard → Operator Override</td>
</tr>
<tr>
  <td>🌐</td>
  <td><b>Fleet 模式</b></td>
  <td>多机器人协同，shared + per-robot 工作区，优先级串行调度</td>
</tr>
</table>

---

## 🚀 5 分钟快速开始

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

**可选：连接 Runtime 服务**

下面的示例通过 `LiberoBenchmarkSkillRuntime` 的 builtin 路径，在启用
episode replan 的情况下使用官方 PI0.5 policy 评估 `libero_spatial`。
三个终端位于同一主机，所有命令均从项目根目录执行。

```bash
# 终端 1：LIBERO TargetWS
MUJOCO_GL=egl PYTHONWARNINGS=ignore \
conda run --no-capture-output -n libero \
  python PhyAgentOS/runtime/targets/remote/libero/server.py \
  --host 0.0.0.0 --port 9002 \
  --camera-height 256 --camera-width 256 \
  --max-steps 300 --num-steps-wait 10 \
  --control-mode relative --seed 7

# 终端 2：官方 OpenPI PI0.5 policy server
conda run --no-capture-output -n openpi \
  python -m PhyAgentOS.runtime.policy.openpi.native_openpi_server \
  --policy-config pi05_libero \
  --checkpoint-dir gs://openpi-assets/checkpoints/pi05_libero \
  --host 0.0.0.0 --port 8000

# 终端 3：Agent、Watchdog 与 Verification Service
paos agent --workspace ~/.PhyAgentOS/workspace -m \
  "使用 PI0.5 评估 LIBERO 的 libero_spatial suite。选择 libero_real_remote target、libero_target_benchmark builtin runtime、target_native 执行路径和 recovery 校验；task id 使用 0-9，init-state id 使用 0-49，max_steps 设为 300，replan_every_steps 设为 5，policy endpoint 使用 openpi://127.0.0.1:8000。"
```
</td>
</tr>
</table>

启动终端 3 前，需要启用 `libero_real_remote`、配置 Runtime verification，
并在 Target 配置中设置 `retry_instruction_mode: original`。
后者使 recovery attempt 保持原任务指令；需要把 verifier 返回的非空 rewrite
作为 policy 指令时，改用 `verifier_rewrite`。
完整的全局配置、Target、SkillRuntime、Session、benchmark、verification 和
远程部署参数参见 [Runtime 参数配置参考](docs/zh/04-runtime-configuration-reference.md)，
其中包含 LIBERO 配置示例。

---

## 🗂️ 协议文件

| 进入上下文逻辑 | 文件 | 所属工作区 | 功能 |
|:--|:--|:--|:--|
| 始终进入 agent system prompt | `AGENTS.md` | Agent workspace | Agent 的项目级运行规则 |
| 始终进入 agent system prompt | `SOUL.md` | Agent workspace | 身份、行为边界与助手风格 |
| 始终进入 agent system prompt | `USER.md` | Agent workspace | 用户偏好与长期画像 |
| 始终进入 agent system prompt | `TOOLS.md` | Agent workspace | 工具使用规则与可用工具说明 |
| 始终进入 agent system prompt | `SKILLS.md` | Agent workspace | 面向 Agent 的 skill 发现与加载规则 |
| 存在时进入上下文；涉及 target 时按启用 target 过滤 | `EMBODIED.md` | Agent workspace | Target 能力的人类可读描述 |
| 存在时作为状态进入上下文，不是 bootstrap 规则 | `ENVIRONMENT.md` | Agent/runtime workspace | 当前 target、场景与环境状态 |
| 存在时作为记忆/状态进入上下文 | `LESSONS.md` | Agent workspace | 运行经验、失败记录与修正建议 |
| 存在时作为任务状态进入上下文 | `TASK.md` | Agent workspace | 多步任务拆解与进度 |
| Runtime 协议；创建 session 前读取 | `RUNTIME.md` | Runtime workspace | 写入合法 runtime session 的说明 |
| Runtime 协议；创建 session 前读取 | `TARGETS.md` | Runtime workspace | 已启用 target、endpoint/adapter/config 引用、支持的 skill runtime |
| Runtime 协议；创建 session 前读取 | `SKILLRUNTIME.md` | Runtime workspace | Policy/builtin skill runtime 注册表与执行契约 |
| Runtime 队列/状态；Agent 与 watchdog 写入 | `SESSIONS.md` | Runtime workspace | 待执行、执行中、已完成 session 与结果 |

`SKILLS.md` 服务 Agent 能力与 skill 发现；`SKILLRUNTIME.md` 服务 runtime
执行契约，并与 `TARGETS.md`、`SESSIONS.md` 配套使用。

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
│   │   └── remote/libero/     #   LIBERO benchmark TargetWS server + proxy
│   ├── skillruntime/          #   PolicySkillRuntime / BuiltinSkillRuntime
│   ├── adapters/              #   TargetAdapter / PolicyAdapter / Bridge
│   │   ├── libero/            #   LIBERO target adapter
│   │   └── openpi/            #   OpenPI policy adapters
│   ├── policy/openpi/         #   OpenPI client + LeRobot pi0-family server
│   ├── perception/            #   感知运行时 / EnvironmentWriter
│   ├── preflight/             #   RuntimeCompatibilityPreflight
│   └── schemas/               #   Pydantic Schema
│
├── configs/runtime/           # Sensor / Perception / Contract YAML
├── scripts/                   # 工具脚本
├── workspace/                 # Agent 工作区；runtime 文件可按配置共用该目录
├── docs/                      # 文档
└── tests/                     # 测试
```

---

## 🏷️ 支持目标

| | Kind | 位置 | 示例 |
|:--|:-----|:-----|:-----|
| 🐛 | `debug` | Local | echo / mock / dry-run —— 零硬件验证协议链路 |
| 🧪 | `simulation` | Remote | RoboCasa、LIBERO —— Benchmark 评测与批量经验挖掘 |
| 🤖 | `real_robot` | Remote | Franka、Go2、XLeRobot、AgileX PIPER —— 真实运行 |

> 全部 target 通过 `TARGETS.md` 统一注册，`target_adapter://` URI 标识 adapter。
> 更多实例与演示 → [项目网站](https://phy-agent-os.net/)

---

## 📖 文档

| 文档 | 面向 | 说明 |
|:-----|:-----|:-----|
| [🌐 项目网站](https://phy-agent-os.net/docs/en/architecture.html) | 所有人 | 完整文档、架构详解、Demo 演示 |
| [📘 用户手册](https://phy-agent-os.net/docs/en/api-reference.html) | 使用者 | 安装部署、运行操作指南 |
| [📙 开发指南](https://phy-agent-os.net/docs/en/developer-guide.html) | 开发者 | 二次开发、硬件接入、插件编写 |

---

## 🤝 参与贡献

欢迎提交 PR 和 Issue，我们的开发计划可以在此处查看👉 [开发计划](https://phy-agent-os.net/docs/en/developer-guide.html)。

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
