<div align="center">
  <img src="docs/imgs/logo_en.png" alt="PhyAgentOS" width="560">

  <h3>Cognitive–Physical Decoupling — Forge-native execution with evidence-grounded verification</h3>

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
      <img src="https://img.shields.io/badge/Tech_Report-arXiv-b31b1b?logo=arxiv&logoColor=white" alt="Tech Report">
    </a>
    <a href="https://phy-agent-os.net/">
      <img src="https://img.shields.io/badge/Website-online-FF6B35" alt="Website">
    </a>
    <a href="https://github.com/PhyAgentOS/PhyAgentOS">
      <img src="https://img.shields.io/badge/PRs-Welcome-2EA44F" alt="PRs">
    </a>
  </p>
  <p>
    <sub><a href="README.md">English</a> · <a href="README_zh.md">中文</a> · <a href="docs/README.md">Documentation</a></sub>
  </p>
</div>

---

PhyAgentOS is an agent framework for embodied tasks. The Agent plans a high-level action, the Forge adapter records what the Gateway executed, the observation collector captures before/after evidence, and the task-level verifier decides whether the user-visible goal was actually achieved.

> **The central rule:** Gateway `succeeded` is an execution fact, not proof of task success. Semantic success is determined by the task verification policy.

## 📢 Changelog

| Version | Date | Update |
|:--------|:-----|:-------|
| ![v2.0.0](https://img.shields.io/badge/v2.0.0-47A882) | 2026-08-03 | Introduced the Forge execution architecture with Forge Gateway 1.0.0, immutable execution and evidence contracts, system-level semantic verification, Planner-owned recovery, crash-safe SQLite orchestration, and complete removal of the legacy Runtime execution chain. |
| ![v0.1.7](https://img.shields.io/badge/v0.1.7-47A882) | 2026-07-05 | Added benchmarking for policy-loop and target-native builtin paths, plus the Agent verification and failure-recovery service. |
| ![v0.1.6](https://img.shields.io/badge/v0.1.6-47A882) | 2026-06-27 | Added BEHAVIOR-1K support, `SessionVerifier`, and the explicit session-verification tool. |
| ![v0.1.5](https://img.shields.io/badge/v0.1.5-47A882) | 2026-06-11 | Cleaned protocol files and documentation, moved game scenarios to the `general-game-agent` branch, and focused the main line on simulation and real-robot work. |
| ![v0.1.4](https://img.shields.io/badge/v0.1.4-11648A) | 2026-06-05 | Improved onboarding, documented communication protocols, refined coding standards, and prepared game-agent benchmarking. |
| ![v0.1.3](https://img.shields.io/badge/v0.1.3-11648A) | 2026-05-25 | Established the strict `PolicySkillRuntime` / `BuiltinSkillRuntime` separation and advanced game-agent benchmarking. |
| ![v0.1.2](https://img.shields.io/badge/v0.1.2-11648A) | 2026-05-20 | Introduced the perception plugin system with sensor/perception configuration and auditable environment writeback. |
| ![v0.1.1](https://img.shields.io/badge/v0.1.1-11648A) | 2026-05-18 | Delivered the Session-Centered Runtime MVP with the initial dummy simulation pipeline. |
| ![v0.1.0](https://img.shields.io/badge/v0.1.0-11648A) | 2026-04-29 | Released the hackathon baseline with the plugin HAL and early ReKep, SAM3, grasping, and VLN workflows. |

## Why PhyAgentOS?

<table>
<tr><td width="32">🧭</td><td width="190"><b>One execution boundary</b></td><td>Robot actions enter through one versioned Forge Gateway contract; the Agent never reaches into a policy, simulator, Dora node, or hardware SDK.</td></tr>
<tr><td>🔎</td><td><b>Evidence before verdict</b></td><td>Validated images and optional robot state are captured around the command and stored with source, sequence, time, size, digest, and retention metadata.</td></tr>
<tr><td>🧠</td><td><b>Action-agnostic verification</b></td><td>The verifier receives the goal, criteria, constraints, execution facts, evidence, lineage history, and lessons—never an action-specific verification switch.</td></tr>
<tr><td>🧱</td><td><b>Crash-safe orchestration</b></td><td>SQLite transactions persist identity, state transitions, and dispatch intent before mutation. A restart queries an attempted session and never blindly repeats POST.</td></tr>
<tr><td>🔄</td><td><b>Planner-owned recovery</b></td><td>A recovery verdict produces non-executable context. The normal Planner must create a fresh child action with new session and command IDs.</td></tr>
</table>

## Architecture

```text
User / Channel / Scheduled Event
              │
              ▼
      AgentLoop + Planner
              │  Forge tools
              ▼
   ForgeSessionOrchestrator ───────► SQLite session + event store
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
Forge Runtime + Dora + robot/simulator
```

The system keeps three records separate:

1. **Execution** — what command the Gateway accepted and how it terminated.
2. **Evidence** — what PAOS observed before and after that command.
3. **Verdict** — whether each system-level success criterion is satisfied.

## Core features

| Area | Current capability |
|:-----|:-------------------|
| Forge contract | Strictly accepts `paos-forge-gateway-mvp-plus.v1` and requires sessions, command IDs, runtime context, and serialized actions. |
| Async orchestration | Submission returns immediately; execution, evidence capture, verification, notification, and recovery continue in the background. |
| Identity validation | Gateway session ID, command ID, request ID, action type, command identity, and policy identity must all match. |
| Evidence | Async `/ws/images` and `/ws/state` collection with bounded latest-frame buffers, media validation, SHA-256, and per-source sequence boundaries. |
| Verification | `off`, `audit`, `enforce`, and `recovery` modes with structured per-criterion verdicts. |
| Recovery | Atomic parent/child transition, bounded replans, deadlines, fresh IDs, and normal-Planner wake-up through system events. |
| Persistence | SQLite WAL event log plus workspace-relative JSON/image artifacts; immutable Execution Records survive review and retention. |
| Agent platform | CLI and multi-channel gateway, provider abstraction, tools, skills, MCP, memory, Cron, Heartbeat, and knowledge workspaces. |

## 5-minute quick start

### 1. Install

```bash
git clone https://github.com/PhyAgentOS/PhyAgentOS.git
cd PhyAgentOS
python -m pip install -e .

# Development and tests
python -m pip install -e ".[dev]"
```

Python 3.11 or 3.12 is recommended. Forge Gateway is an external service and must be started separately.

### 2. Initialize the workspace

```bash
paos onboard
```

This creates `~/.PhyAgentOS/config.json` and the default workspace at `~/.PhyAgentOS/workspace`.

### 3. Configure a provider and Forge

The configuration file is serialized in camelCase; snake_case keys are also accepted.

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

The `front` source is only an example. Use a source ID advertised by your Gateway context, or leave the global list empty and let PAOS discover ready image sources. A task requesting `authoritative` association is rejected before execution because Gateway 1.0.0 only supports `best_effort` evidence association.

### 4. Start the Agent

Start Forge Gateway first, then choose one of the PAOS entry points:

```bash
# Interactive CLI
paos agent

# One request; waits if the Agent submits a Forge task
paos agent -m "Inspect Forge capabilities, then place the object in the target area and verify the visible result."

# Long-running channels, Cron, Heartbeat, Agent, and Forge orchestration
paos gateway
```

Use `paos status` to inspect the local model/workspace configuration. Use `forge_get_context` through the Agent for startup-cached action capabilities plus live Forge readiness, status, and context.

## Verification modes

| Mode | Task contract | Final result | Recovery |
|:-----|:--------------|:-------------|:---------|
| `off` | Goal and criteria optional | Follows Gateway execution status | Never |
| `audit` | Goal and at least one criterion required | Preserves execution-derived terminal state; records verdict/error | Never |
| `enforce` | Goal and at least one criterion required | Verdict controls success; missing evidence, invalid output, errors, and `inconclusive` fail closed | Never |
| `recovery` | Goal and at least one criterion required | Same fail-closed behavior; `replan_required` enters recovery | Planner creates a fresh child |

A typical non-`off` contract looks like this:

```json
{
  "mode": "recovery",
  "goal": "The red block is inside the tray.",
  "success_criteria": [
    "The red block is visibly within the tray boundary.",
    "No other object has been displaced outside the workspace."
  ],
  "constraints": [
    "Do not move the blue block."
  ],
  "evidence_policy": {
    "required_kinds": ["rgb_image"],
    "required_sources": ["front"],
    "minimum_association": "best_effort"
  }
}
```

## Agent-facing Forge tools

| Tool | Purpose |
|:-----|:--------|
| `forge_execute_task` | Submit one high-level action and return fresh PAOS session/command IDs immediately. |
| `forge_get_session` | Read the persisted task, Gateway execution, evidence, verdict, recovery, and errors. |
| `forge_cancel_session` | Cancel a non-terminal task and request Gateway cancellation if already dispatched. |
| `forge_get_context` | Read startup-cached capabilities plus live runtime status, readiness, and context. |
| `forge_reset` | Explicitly reset the Gateway only when no PAOS lineage is active. |
| `verify_forge_session` | Review a terminal session using retained evidence without changing its terminal state or Execution Record. |
| `create_replanned_forge_session` | Atomically create one fresh child for an `awaiting_replan` parent. |

These tools are registered only when `forge.enabled` is true.

## Persistence and workspace

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

`EMBODIED.md`, `ENVIRONMENT.md`, and SceneGraph remain knowledge surfaces. They are not execution queues. PAOS no longer reads or generates the former Runtime Markdown queue files.

## Supported scope

- One PAOS process configures one Forge Gateway endpoint.
- One root task lineage owns the serialized execution slot until verification or recovery terminates.
- One Forge session represents one high-level Gateway action; the Planner decomposes longer tasks.
- Gateway, Forge Runtime, Dora dataflows, policy internals, and hardware drivers remain outside this repository.
- Gateway 1.0.0 evidence correlation is `best_effort`; PAOS does not fabricate authoritative timestamps or causality.
- Legacy PAOS Runtime, Target, SkillRuntime, Watchdog, SessionRunner, and Markdown execution queue compatibility is intentionally removed.

## Project structure

```text
PhyAgentOS/
├── PhyAgentOS/agent/          # AgentLoop, tools, memory, verifier integration
├── PhyAgentOS/forge/          # Gateway client, observations, adapter, store, orchestrator
├── PhyAgentOS/verification/   # Public contracts, request builder, engine, service
├── PhyAgentOS/channels/       # Messaging channels
├── PhyAgentOS/config/         # Configuration schema and loading
├── PhyAgentOS/templates/      # Agent knowledge/workspace templates
├── docs/                      # English, Chinese, operations, integration, Forge docs
├── plan/                      # Historical design and review reports
└── tests/                     # Contract, store, Gateway, evidence, verifier, E2E tests
```

## Documentation

| Document | Audience | Description |
|:---------|:---------|:------------|
| [Documentation index](docs/README.md) | Everyone | Bilingual reading paths and document map |
| [Framework introduction](docs/en/01-framework-introduction.md) | Architects and users | Design, boundaries, lifecycle, and current scope |
| [User manual](docs/en/02-user-manual.md) | Operators and users | Installation, configuration, tasks, artifacts, and troubleshooting |
| [Developer manual](docs/en/03-developer-manual.md) | Contributors | Contracts, invariants, extension points, and tests |
| [Forge configuration reference](docs/en/04-forge-configuration-reference.md) | Deployers | Exact Forge, evidence, verification, and task fields |
| [Operations manual](docs/user_manual/README_en.md) | Operations | Startup, monitoring, restart, cancellation, and incident handling |
| [Integration guide](docs/user_development_guide/README_en.md) | Integrators | Connecting Gateway actions without action-specific verifier code |
| [Forge integration contract](docs/forge/README.md) | Gateway/PAOS developers | HTTP/WebSocket, identity, evidence, verification, recovery, and restart contracts |

## Development

```bash
python -m pip install -e ".[dev]"
pytest
ruff check PhyAgentOS tests
python -m compileall -q PhyAgentOS tests
```

Optional black-box tests may use `FORGE_GATEWAY_URL` to connect to a running compatible Gateway. Tests and PAOS documentation must not mutate the Gateway source or configuration.

## Contributing

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
