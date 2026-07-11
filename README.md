<div align="center">
  <img src="docs/imgs/logo_en.png" alt="PhyAgentOS" width="560">

  <h3>Self-Evolving Physical Agent Operating System<br>A Unified Runtime Foundation for Embodied Intelligence</h3>

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

## 📢 Changelog

| Version | Date | Update |
|:------|:-----|:-------|
| ![v0.1.7](https://img.shields.io/badge/v0.1.7-11648A) | 2026-07-11 | General Game Agent: 3-game progressive environment (Minecraft → Stardew Valley → Don't Starve); Epistemic Memory for long-horizon experience accumulation; Self-evolving analytics pipeline |
| ![v0.1.6](https://img.shields.io/badge/v0.1.6-47A882) | 2026-06-27 | Support for Behavior 1K; SessionVerifier for Agent verification; VerifySessionTool |
| ![v0.1.5](https://img.shields.io/badge/v0.1.5-47A882) | 2026-06-11 | Cleaned protocol files and docs; game scenario separated to `general-game-agent` branch; main branch now focused on sim & real |
| ![v0.1.4](https://img.shields.io/badge/v0.1.4-11648A) | 2026-06-5 | Optimize the user-friendly onboarding process; Communication Protocol Specification; More reasonable coding standards; Game Agent & Benchmarking ready |
| ![v0.1.3](https://img.shields.io/badge/v0.1.3-11648A) | 2026-05-25 | Strict separation of `PolicySkillRuntime` / `BuiltinSkillRuntime`; Game Agent & Benchmarking ready |
| ![v0.1.2](https://img.shields.io/badge/v0.1.2-11648A) | 2026-05-20 | Perception plugin system: `SensorConfig` / `PerceptionConfig` YAML + `EnvironmentWriter` auditable writeback |
| ![v0.1.1](https://img.shields.io/badge/v0.1.1-11648A) | 2026-05-18 | Session-Centered Runtime MVP: `DummySimTarget` + `DummyAdapter` + `DummyClient` serial pipeline |
| ![v0.1.0](https://img.shields.io/badge/v0.1.0-11648A) | 2026-04-29 | Hackathon baseline: plugin-based HAL, ReKep / SAM3 real-robot grasping & VLN full pipeline |

---

## 🧭 The Three Paradigms & What's Missing

Three approaches dominate embodied intelligence today — and each leaves a gap that PhyAgentOS fills:

| Paradigm | What It Does | What It Doesn't Do |
|:--|:--|:--|
| **VLA (π0, OpenVLA, FluxVLA)** | End-to-end visuomotor control — "see → act" | No task decomposition, no failure recovery, no cross-embodiment reuse |
| **Code-as-Policies (LLM→Code→Robot)** | Generate executable plans from language | Fragile to real-world variation; no closed-loop verification; brittle across hardware |
| **World Models (video→prediction)** | Predict future states from current observations | Predictions ≠ actions; no execution grounding, no safety guardrails |

**PhyAgentOS doesn't replace any of these — it orchestrates them.** It sits between models and hardware as a unified runtime that answers: *what to call, who executes it, how to verify success, and what to do when it fails.*

---

## 🤔 Why PhyAgentOS?

Traditional "LLM-direct-to-hardware" approaches tightly couple reasoning to execution — switching robots means rewriting the entire pipeline. PhyAgentOS changes this through **Cognitive-Physical Decoupling + Session-Centered Runtime**:

<table>
<tr><td width="32">🔌</td><td><b>One Codebase, Any Hardware</b> — Adding a new robot means implementing one Target Adapter (~100 lines); zero changes to the scheduling layer. 19 embodiments supported across real robots, simulators, and games.</td></tr>
<tr><td>🛡️</td><td><b>Three Safety Layers</b> — Critic validation → Strict Preflight → Target-side SafetyGuard; mandatory for real-robot deployment.</td></tr>
<tr><td>📋</td><td><b>Fully Auditable</b> — State, actions, and perception results are written to Markdown + YAML files; every step is traceable and reproducible.</td></tr>
<tr><td>🔄</td><td><b>Zero-Friction Migration</b> — The same Session protocol runs identically across sim and real targets.</td></tr>
<tr><td>🎮</td><td><b>Game → Sim → Real Closed Loop</b> — Validate cognitive strategies in low-cost game environments (Minecraft / Stardew Valley / Don't Starve), then migrate the same intelligence layer to simulation (LIBERO / Behavior 1K) and real robots with zero cognitive-layer changes.</td></tr>
<tr><td>🧠</td><td><b>Self-Evolving</b> — Epistemic Memory accumulates long-horizon experience; Lessons learned from failures are recorded and reused. Benchmarking is orchestration: auto-evaluate policies (π0, π0.5, OpenVLA, X-VLA), aggregate evidence, and evolve.</td></tr>
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
  <td><code>PolicySkillRuntime</code> maintains policy closed-loop + <code>BuiltinSkillRuntime</code> manages agent interactive loop</td>
</tr>
<tr>
  <td>🛡️</td>
  <td><b>Strict Preflight</b></td>
  <td>Runtime validation checks (target / sensor / perception / adapter contract / action contract / tool); failures are <code>rejected</code> before execution starts</td>
</tr>
<tr>
  <td>✅</td>
  <td><b>SessionVerifier</b></td>
  <td>Semantic verification of execution results — compares initial vs. final RGB observations, task definitions, and workspace history; marks sessions <code>succeeded</code> / <code>failed</code> / <code>replanned</code> with evidence stored in <code>LESSONS.md</code></td>
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
  <td>🧠</td>
  <td><b>Epistemic Memory</b></td>
  <td>Long-horizon experience accumulation across sessions; lessons from failures are automatically recorded, retrieved, and applied to future tasks — enabling self-evolution over deployment cycles</td>
</tr>
<tr>
  <td>📊</td>
  <td><b>Benchmarking as Orchestration</b></td>
  <td>Evaluation is a first-class skill: auto-select benchmarks, queue tasks, execute in parallel, aggregate evidence, and produce experiment reports — currently supporting π0, π0.5, OpenVLA, and X-VLA on LIBERO and Behavior 1K</td>
</tr>
</table>

---

## 🎮 Game → Sim → Real Pipeline

PhyAgentOS enables a unique **three-stage validation closed loop** where the intelligence layer stays constant and only the execution target changes:

```
Game (Cognitive Validation)       Sim (Policy Benchmarking)        Real (Physical Deployment)
─────────────────────────         ────────────────────────         ──────────────────────────
Minecraft → Stardew Valley        LIBERO → Behavior 1K             Franka · Go2 · PIPER
    → Don't Starve                                                 AgileX · RM65-B · BOBABOT
         │                                │                              │
         └────────同一个 Session 协议，零认知层改动────────────────┘
```

1. **Game**: Low-cost, high-concurrency environments to validate planning, memory, and decision-making with minimal physics complexity
2. **Sim**: Benchmark policies on standard embodied tasks; "evaluation as orchestration" — the agent picks, queues, runs, and reports
3. **Real**: The same protocols, same intelligence layer, now driving physical robots with full safety guardrails

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
paos agent
```
</td>
</tr>
<tr>
<td align="center">4</td>
<td>

**Optional: Connect Runtime Services**

```bash
# LIBERO benchmark TargetWS machine
MUJOCO_GL=egl PYTHONWARNINGS=ignore \
conda run -n liberopi python PhyAgentOS/runtime/targets/remote/libero/server.py \
  --host 0.0.0.0 --port 9002

# pi0.5 policy machine
conda run -n lerobot-pi python -m PhyAgentOS.runtime.policy.openpi.lerobot_pi0_server \
  --model-dir /path/to/pi05/checkpoint --host 0.0.0.0 --port 8000
```
</td>
</tr>
</table>

`paos agent` and `paos gateway` create the runtime workspace and start the
session watchdog automatically when runtime is enabled in config. Runtime
targets are declared in `TARGETS.md`, executable runtimes in `SKILLRUNTIME.md`,
and the Agent queues work by appending sessions to `SESSIONS.md`.

Agent-side semantic verification is disabled by default. Enable it in
`~/.PhyAgentOS/config.json` when runtime completion must be checked against the
final RGB observations and workspace history:

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

With verification enabled, a runtime-successful session moves through
`awaiting_verification` and `verifying`. The Agent then marks it `succeeded` or
`failed`, or marks it `replanned` and appends a replacement `pending` session.
Evidence is stored under `artifacts/runtime/<session_id>/`, and every verdict
is recorded in `LESSONS.md`. `rgbRetention` accepts `all`, `failed`, or `none`;
the default `failed` policy removes RGB after successful verification while
retaining failed and replanned evidence. The Agent can call `verify_session`
to process a waiting session or review a terminal session whose RGB remains.

```bash
paos agent -m "run the configured LIBERO benchmark task"
```

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
| 🎮 | `game` | Local | Minecraft, Stardew Valley, Don't Starve — cognitive validation with minimal physics |
| 🧪 | `simulation` | Remote | RoboCasa, LIBERO, Behavior 1K — benchmark evaluation & batch experience mining |
| 🤖 | `real_robot` | Remote | Franka, Go2, PIPER AgileX, RM65-B RealMan, BOBABOT, XLeRobot — 7 real robots, 12+ sim variants, 19 total embodiments |

> All targets are registered in `TARGETS.md`, identified by `target_adapter://` URI.
> More examples & demos → [Project Website](https://phy-agent-os.net/)

---

## 📖 Documentation

| Document | Audience | Description |
|:-----|:-----|:-----|
| [🌐 Website](https://phy-agent-os.net/docs/en/architecture.html) | Everyone | Full docs, architecture details, demos |
| [📘 User Manual](https://phy-agent-os.net/docs/en/api-reference.html) | Users | Installation, deployment, and operation guide |
| [📙 Dev Guide](https://phy-agent-os.net/docs/en/developer-guide.html) | Developers | Secondary development, hardware integration, plugin authoring |

---

## 🤝 Contributing

PRs and Issues are welcome! Check our development roadmap here → [Dev Plan](https://phy-agent-os.net/docs/en/developer-guide.html).

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
