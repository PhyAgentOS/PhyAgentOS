<div align="center">
  <img src="docs/imgs/logo_en.png" alt="PhyAgentOS" width="560">

  <h3>Cognitive-Physical Decoupling — A Session-Centered Runtime for Embodied Intelligence</h3>

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
    <a href="https://arxiv.org/pdf/2607.16636">
      <img src="https://img.shields.io/badge/📄_Tech_Report-arXiv-b31b1b?logo=arxiv&logoColor=white" alt="Tech Report">
    </a>
    <a href="https://phy-agent-os.net/">
      <img src="https://img.shields.io/badge/🌐_Website-online-FF6B35" alt="Website">
    </a>
    <a href="https://github.com/PhyAgentOS/PhyAgentOS">
      <img src="https://img.shields.io/badge/PRs-Welcome-2EA44F" alt="PRs">
    </a>
  </p>
  <p>
    <a href="https://space.bilibili.com/3546880296355920?spm_id_from=333.1007.0.0">
      <img src="https://img.shields.io/badge/Bilibili-00A1D6?logo=bilibili&logoColor=white" alt="Bilibili">
    </a>
    <a href="https://www.xiaohongshu.com/user/profile/673d83e3000000001c01a183">
      <img src="https://img.shields.io/badge/Xiaohongshu-FF2442?logo=xiaohongshu&logoColor=white" alt="Xiaohongshu">
    </a>
    <a href="https://x.com/phyagentos">
      <img src="https://img.shields.io/badge/X-000000?logo=x&logoColor=white" alt="X">
    </a>
    <a href="https://www.linkedin.com/in/phyagent-os-252372401/">
      <img src="https://img.shields.io/badge/LinkedIn-0A66C2?logo=linkedin&logoColor=white" alt="LinkedIn">
    </a>
    <a href="https://discord.gg/YJztZ4wUM">
      <img src="https://img.shields.io/badge/Discord-5865F2?logo=discord&logoColor=white" alt="Discord">
    </a>
  </p>
  <p>
    <sub><a href="./README.md">English</a> · <a href="./README_zh.md">中文</a></sub>
  </p>
</div>

---

## 📢 Changelog

| Version | Date | Update |
|:------|:-----|:-------|
| ![v0.1.7](https://img.shields.io/badge/v0.1.7-47A882) | 2026-07-5 | Supports benchmarking for both the policy loop and target native builtin paths; Incorporates agent verification and failure recovery server|
| ![v0.1.6](https://img.shields.io/badge/v0.1.6-47A882) | 2026-06-27 | Support for  Behavior 1K; SessionVerfier for Agent verification; VerifySessionTool|
| ![v0.1.5](https://img.shields.io/badge/v0.1.5-47A882) | 2026-06-11 | Cleaned protocol files and docs; game scenario separated to `general-game-agent` branch; main branch now focused on sim & real |
| ![v0.1.4](https://img.shields.io/badge/v0.1.4-11648A) | 2026-06-5 | Optimize the user-friendly onboarding process; Communication Protocol Specification; More reasonable coding standards; Game Agent & Benchmarking ready |
| ![v0.1.3](https://img.shields.io/badge/v0.1.3-11648A) | 2026-05-25 | Strict separation of `PolicySkillRuntime` / `BuiltinSkillRuntime`; Game Agent & Benchmarking ready |
| ![v0.1.2](https://img.shields.io/badge/v0.1.2-11648A) | 2026-05-20 | Perception plugin system: `SensorConfig` / `PerceptionConfig` YAML + `EnvironmentWriter` auditable writeback |
| ![v0.1.1](https://img.shields.io/badge/v0.1.1-11648A) | 2026-05-18 | Session-Centered Runtime MVP: `DummySimTarget` + `DummyAdapter` + `DummyClient` serial pipeline |
| ![v0.1.0](https://img.shields.io/badge/v0.1.0-11648A) | 2026-04-29 | Hackathon baseline: plugin-based HAL, ReKep / SAM3 real-robot grasping & VLN full pipeline |

---

## 🤔 Why PhyAgentOS?

Traditional "LLM-direct-to-hardware" approaches tightly couple reasoning to execution — switching robots means rewriting the entire pipeline. PhyAgentOS changes this through **Cognitive-Physical Decoupling + Session-Centered Runtime**:

<table>
<tr><td width="32">🔌</td><td><b>One Codebase, Any Hardware</b> — Adding a new robot means implementing one Target Adapter (~100 lines); zero changes to the scheduling layer.</td></tr>
<tr><td>🛡️</td><td><b>Three Safety Layers</b> — Critic validation → Strict Preflight → Target-side SafetyGuard; mandatory for real-robot deployment.</td></tr>
<tr><td>📋</td><td><b>Fully Auditable</b> — State, actions, and perception results are written to Markdown + YAML files; every step is traceable and reproducible.</td></tr>
<tr><td>🔄</td><td><b>Zero-Friction Migration</b> — The same Session protocol runs identically across sim and real targets.</td></tr>
</table>

<br>

<div align="center">
  <img src="docs/imgs/framework.svg" alt="Architecture" width="960">
  <p><sub>▲ Session-Centered Runtime Architecture Overview</sub></p>
</div>

---

## ✨ Core Features

<table>
<tr>
  <td width="32">🔄</td>
  <td width="165"><b>Session-Centered Runtime</b></td>
  <td><code>WatchdogSupervisor</code> → <code>SessionRunner</code> → <code>SkillRuntime</code> → <code>TargetSessionHandle</code> execution pipeline, replacing the legacy Driver-Center architecture</td>
</tr>
<tr>
  <td>🎯</td>
  <td><b>Target-Configured</b></td>
  <td>Three target kinds — <code>debug</code> / <code>simulation</code> / <code>real_robot</code> — registered in <code>TARGETS.md</code>, adapters attached on demand</td>
</tr>
<tr>
  <td>🧩</td>
  <td><b>Adapter + Bridge</b></td>
  <td><code>TargetAdapter</code> + <code>PolicyAdapter</code> + <code>ActionBridge</code> three-way decoupling with explicit observation/action contracts; <code>AdapterPlan</code> auto-composed, eliminating target×skill combinatorial explosion</td>
</tr>
<tr>
  <td>⚡</td>
  <td><b>Dual Skill Runtimes</b></td>
  <td><code>PolicySkillRuntime</code> maintains the policy closed loop + <code>BuiltinSkillRuntime</code> manages built-in loops such as target-native benchmarks and constrained agent interaction</td>
</tr>
<tr>
  <td>🛡️</td>
  <td><b>Strict Preflight</b></td>
  <td>Runtime validation checks (target / sensor / perception / adapter contract / action contract / tool); failures are <code>rejected</code> before execution starts</td>
</tr>
<tr>
  <td>📝</td>
  <td><b>File Protocol Matrix</b></td>
  <td><code>TARGETS.md</code> · <code>SKILLRUNTIME.md</code> · <code>SESSIONS.md</code> · <code>ENVIRONMENT.md</code> · <code>LESSONS.md</code> + external YAML configs</td>
</tr>
<tr>
  <td>🔐</td>
  <td><b>Multi-Layer Safety</b></td>
  <td>Critic validation → Preflight contract checks → Target-side SafetyGuard → Operator Override</td>
</tr>
<tr>
  <td>🌐</td>
  <td><b>Fleet Mode</b></td>
  <td>Multi-robot coordination with shared + per-robot workspaces, priority-based serial scheduling</td>
</tr>
<tr>
  <td>🖥️</td>
  <td><b>Built-in TUI</b></td>
  <td><code>paos tui</code> — full-screen interface with tiling chat, live status/logs panes, provider &amp; settings management, and Morandi themes</td>
</tr>
</table>

---

## 🚀 5-Minute Quick Start

<table>
<tr>
<td width="28" align="center">1</td>
<td>

**Install**

```bash
git clone https://github.com/PhyAgentOS/PhyAgentOS.git && cd PhyAgentOS
pip install -e .            # Python ≥ 3.11
pip install -e ".[dev]"     # Dev dependencies

```
</td>
</tr>
<tr>
<td align="center">2</td>
<td>

**Initialize Workspace**

```bash
paos onboard
```
</td>
</tr>
<tr>
<td align="center">3</td>
<td>

**Start Agent**

```bash
paos agent    # CLI chat
paos tui      # full-screen TUI
```
</td>
</tr>
<tr>
<td align="center">4</td>
<td>

**Optional: Connect Runtime Services**

The following example evaluates the official PI0.5 policy on the
`libero_spatial` suite through `LiberoBenchmarkSkillRuntime`, with episode
replanning enabled. Run the three terminals on the same host from the
repository root.

```bash
# Terminal 1: LIBERO TargetWS
MUJOCO_GL=egl PYTHONWARNINGS=ignore \
conda run --no-capture-output -n libero \
  python PhyAgentOS/runtime/targets/remote/libero/server.py \
  --host 0.0.0.0 --port 9002 \
  --camera-height 256 --camera-width 256 \
  --max-steps 300 --num-steps-wait 10 \
  --control-mode relative --seed 7

# Terminal 2: official OpenPI PI0.5 policy server
conda run --no-capture-output -n openpi \
  python -m PhyAgentOS.runtime.policy.openpi.native_openpi_server \
  --policy-config pi05_libero \
  --checkpoint-dir gs://openpi-assets/checkpoints/pi05_libero \
  --host 0.0.0.0 --port 8000

# Terminal 3: Agent, Watchdog, and Verification Service
paos agent --workspace ~/.PhyAgentOS/workspace -m \
  "Evaluate PI0.5 on LIBERO suite libero_spatial. Use target libero_real_remote, the libero_target_benchmark builtin runtime, target_native execution, recovery verification, task ids 0-9, init-state ids 0-49, max_steps 300, replan_every_steps 5, and policy endpoint openpi://127.0.0.1:8000."
```
</td>
</tr>
</table>

Before starting Terminal 3, enable `libero_real_remote`, configure Runtime
verification, and set the Target configuration to 
`retry_instruction_mode: original`. The latter keeps the original task
instruction on recovery attempts; use `verifier_rewrite` when the policy should
receive the verifier's nonempty rewrite instead. See the
[Runtime configuration reference](docs/en/04-runtime-configuration-reference.md)
for the complete global, Target, SkillRuntime, Session, benchmark,
verification, and remote-host parameter reference. The LIBERO setup is
included as an example.

---

## 🗂️ Protocol Files

| Context Loading | File | Owner | Purpose |
|:--|:--|:--|:--|
| Always loaded into the agent system prompt | `AGENTS.md` | Agent workspace | Project-level operating rules for the agent |
| Always loaded into the agent system prompt | `SOUL.md` | Agent workspace | Identity, high-level behavior, and assistant style |
| Always loaded into the agent system prompt | `USER.md` | Agent workspace | User preferences and durable profile notes |
| Always loaded into the agent system prompt | `TOOLS.md` | Agent workspace | Tool usage policy and available tool guidance |
| Always loaded into the agent system prompt | `SKILLS.md` | Agent workspace | Agent-facing skill discovery and loading rules |
| Loaded when present; filtered by enabled runtime targets where applicable | `EMBODIED.md` | Agent workspace | Human-readable target capability descriptions |
| Loaded when present as state, not bootstrap policy | `ENVIRONMENT.md` | Agent/runtime workspace | Current target and scene/environment state |
| Loaded when present as memory/state | `LESSONS.md` | Agent workspace | Operational lessons and failure notes |
| Loaded when present as task state | `TASK.md` | Agent workspace | Multi-step task decomposition and progress |
| Runtime protocol; read before scheduling sessions | `RUNTIME.md` | Runtime workspace | Instructions for writing valid runtime sessions |
| Runtime protocol; read before scheduling sessions | `TARGETS.md` | Runtime workspace | Enabled targets, endpoint/adapter/config references, supported skill runtimes |
| Runtime protocol; read before scheduling sessions | `SKILLRUNTIME.md` | Runtime workspace | Policy/builtin skill runtime registry and execution contracts |
| Runtime queue/state; written by Agent and watchdog | `SESSIONS.md` | Runtime workspace | Pending/running/completed execution sessions and results |

`SKILLS.md` is for agent capabilities and skill discovery. `SKILLRUNTIME.md` is
for runtime execution contracts; it is paired with `TARGETS.md` and `SESSIONS.md`.

---

## 📦 Project Structure

```
PhyAgentOS/
│
├── PhyAgentOS/agent/          # Track A  ─  Planner / Critic / Memory
│
├── PhyAgentOS/runtime/        # Track B  ─  Execution Plane
│   ├── watchdog/              #   WatchdogSupervisor
│   ├── sessions/              #   SessionRunner / TargetSessionHandle
│   ├── targets/               #   RolloutTarget (debug·sim·real)
│   │   └── remote/libero/     #   LIBERO benchmark TargetWS server + proxy
│   ├── skillruntime/          #   PolicySkillRuntime / BuiltinSkillRuntime
│   ├── adapters/              #   TargetAdapter / PolicyAdapter / Bridge
│   │   ├── libero/            #   LIBERO target adapter
│   │   └── openpi/            #   OpenPI policy adapters
│   ├── policy/openpi/         #   OpenPI client + LeRobot pi0-family server
│   ├── perception/            #   Perception Runtime / EnvironmentWriter
│   ├── preflight/             #   RuntimeCompatibilityPreflight
│   └── schemas/               #   Pydantic Schema
│
├── configs/runtime/           # Sensor / Perception / Contract YAML
├── scripts/                   # Utility scripts
├── workspace/                 # Agent workspace; runtime files may share it by config
├── docs/                      # Documentation
└── tests/                     # Tests
```

---

## 🏷️ Supported Targets

| | Kind | Location | Examples |
|:--|:-----|:-----|:-----|
| 🐛 | `debug` | Local | echo / mock / dry-run — zero-hardware protocol pipeline validation |
| 🧪 | `simulation` | Remote | RoboCasa, LIBERO — benchmark evaluation & batch experience mining |
| 🤖 | `real_robot` | Remote | Franka, Go2, XLeRobot, AgileX PIPER — real-world deployment |

> All targets are registered in `TARGETS.md`, identified by `target_adapter://` URI.
> More examples & demos → [Project Website](https://phy-agent-os.net/)

---

## 📖 Documentation

| Document | Audience | Description |
|:-----|:-----|:-----|
| [🌐 Website](https://phy-agent-os.net/) | Everyone | Full docs, architecture details, demos |
| [📘 User Manual](https://phy-agent-os.net/docs/api-reference/) | Users | Installation, deployment, and operation guide |
| [📙 Dev Guide](https://phy-agent-os.net/docs/developer-guide/) | Developers | Secondary development, hardware integration, plugin authoring |

---

## 🤝 Contributing

PRs and Issues are welcome! Check our development roadmap here → [Dev Plan](https://phy-agent-os.net/docs/developer-guide/).

---

<div align="center">

Jointly developed by **Sun Yat-sen University HCP Lab** & **Peng Cheng Laboratory** & **X-Era Lab**

<br>

<img src="docs/imgs/HCP.jpg" alt="HCP" height="128">
&nbsp;&nbsp;&nbsp;
<img src="docs/imgs/Pengcheng.png" alt="Pengcheng" height="128">
&nbsp;&nbsp;&nbsp;
<img src="docs/imgs/logo-xera-mark.png" alt="X-Era Lab" height="128">

<br>
<sub>MIT License · Copyright © 2025-2026 PhyAgentOS</sub>

</div>
