# PhyAgentOS Framework Introduction

> Documentation version: v0.1.6. We describe a feature as current only when it is supported by repository source, shipped templates, and tests.

## 1. Project Positioning

PhyAgentOS provides an Agent and an execution runtime for embodied-intelligence tasks. We separate natural-language planning from physical execution into two control planes:

- Track A (Agent) handles messages, context, model calls, tools, memory, and task planning.
- Track B (Runtime) handles Session scheduling, compatibility checks, Target/Policy execution, state writeback, and artifacts.
- The two planes exchange targets, capabilities, and execution state through Markdown + YAML workspace protocols.

This boundary does not hide hardware differences. It confines them to Targets, Adapters, Policy Clients, and Runtime Contracts so the Agent can depend on a stable Session protocol.

## 2. Current Architecture

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

An actual Session follows this path:

1. `SessionScheduler` selects a dependency-ready pending Session from `SESSIONS.md`.
2. `SessionRegistry` atomically claims it and advances it to `preflight_checking`.
3. `RuntimeCompatibilityPreflight` validates references, endpoints, runtime registration, adapters, contracts, sensors, and action contracts.
4. `SessionRunner` calls `build`, `configure_session`, and `start_session`; it
   owns reset for normal policy-loop Sessions, while a target-native benchmark
   delegates reset to its declared SkillRuntime/Target interface.
5. A Skill Runtime can observe, execute action chunks, refresh the environment, or call constrained Target tools only through `TargetSessionHandle`.
6. The Watchdog writes the episode, history, and final state. A policy-loop
   Session using `audit` or `recovery` enters `awaiting_verification`;
   target-native verification occurs at episode attempt boundaries and its root
   Session is not verified again.

## 3. File Protocol

| File | Writer | Current responsibility |
|---|---|---|
| `RUNTIME.md` | RuntimeWorkspaceManager | Generated instructions for creating Sessions; not runtime state |
| `TARGETS.md` | User/developer; enable overrides may apply at startup | Target registry, endpoints, adapters, and config references |
| `SKILLRUNTIME.md` | User/developer | Skill Runtime registry, policies/adapters, and I/O contracts |
| `SESSIONS.md` | Agent + Watchdog + Verifier | Session queue, state, result, and verification metadata |
| `ENVIRONMENT.md` | Runtime/Perception | Target snapshots, objects, scene relations, and perception runs |
| `LESSONS.md` | Runtime/Verifier | Auditable failures and semantic-verification lessons |

Sensor, Perception, and Runtime Contract data lives in external YAML so device calibration, models, and action constraints are not embedded in Markdown registries.

## 4. Implemented Capabilities

### 4.1 Agent Control Plane

- `paos onboard`, `paos agent`, `paos gateway`, `paos status`, and OAuth provider login.
- CLI, 11 Channel implementations, Cron, Heartbeat, MCP, built-in tools, and background subagents.
- File-based context, JSONL sessions, token-window consolidation, and long-term memory.
- Agent-owned Verification Service for model-backed prompts and strict verdict
  normalization, with SessionVerifier applying policy-loop outcomes and
  target-native benchmarks requesting episode verdicts at attempt boundaries.

### 4.2 Runtime Execution Plane

- Session state machine, atomic claims, dependency/priority scheduling, timeouts, and failure writeback.
- `PolicySkillRuntime` and `BuiltinSkillRuntime` execution backends.
- Target/Policy adapters, explicit action bridges, and strict AdapterPlan construction.
- msgpack-over-WebSocket remote Target protocol with an isomorphic lifecycle for local Targets.
- Target-configured Perception, Environment v2 reconciliation, and episode artifacts.

### 4.3 Registered Runtimes

| Type | Registered implementation |
|---|---|
| Local Target | `DummySimTargetRuntime` |
| Remote Target | `RemoteTargetProxy`, `LiberoRemoteTargetProxy`, `IsaacSimRemoteTargetProxy`, `Behavior1KRemoteTargetProxy` |
| Skill Runtime | `OpenPISkillRuntime`, `CommandSimSkillRuntime` |
| Policy Client | Dummy, OpenPI/PolicyWS, BEHAVIOR-1K WebSocket |
| Target Adapter | Dummy, LIBERO, Isaac Sim, BEHAVIOR-1K |
| Action Bridge | `bridge://safety_clamp` |

The shipped templates cover Dummy, LIBERO, PiperGo2/Merom Isaac Sim, and BEHAVIOR-1K targets. The schema accepts four Target kinds—`game`, `debug`, `simulation`, and `real_robot`—but the default v0.1.6 registrations and templates primarily cover simulation. Schema support alone does not imply an available backend.

## 5. v0.1.6 Scope

We define the current public scope as follows:

- Session-Centered Runtime replaces the former Driver-Centered `hal/`, `BaseDriver`, and `hal_watchdog.py` path. Historical examples may remain in the repository, but they are not the current installable Runtime API.
- No `real_robot` Target Runtime is currently registered. The complete target-side safety loop and operator-override requirements from HAL v3 remain future work.
- Preflight requires constrained tool exposure for real-robot Targets, but it does not yet enforce every `operator_override_required`, SafetyGuard, and online-health requirement.
- Some shipped Isaac Sim skills currently use `strict_environment_contract: false`; HAL v3 defines convergence to `true` as the target design.
- Goal Graph, Session Compiler, fallback chains, a general CompositeTarget, and complete multi-Target orchestration are not implemented yet.
- Fleet configuration currently provides shared/instance workspace topology and context resolution; it is not yet a complete multi-robot execution orchestrator.

## 6. Future Design Direction

The following items come from `PhyAgentOS HAL v3.md` and remain target design:

1. Converge every Skill Runtime on a strict Environment Contract and remove non-strict template exceptions.
2. Complete real-robot target-side SafetyGuard, workspace bounds, operator override, and healthcheck gates.
3. Add agent-interactive Builtin Runtimes, constrained Target Tool manifests, and real-robot runtimes.
4. Implement Goal Graph, Session Compiler, long/short-horizon decomposition, and explicit failure escalation.
5. Expand deterministic observation/action bridge chains while prohibiting implicit truncation, padding, and representation casts.
6. Build multi-Target, multi-Skill Runtime, and long-horizon Fleet orchestration on the shared Session protocol.

We promote these items to current-capability documentation only after their schemas, preflight checks, runtime implementations, and tests form an end-to-end path.

## 7. Repository Structure

```text
PhyAgentOS/
├── PhyAgentOS/agent/              # AgentLoop, context, memory, tools, verifier
├── PhyAgentOS/channels/           # Message channels
├── PhyAgentOS/config/             # Configuration schemas and loading
├── PhyAgentOS/runtime/
│   ├── watchdog/                  # Scheduling, claims, state, results
│   ├── sessions/                  # SessionRunner, TargetSessionHandle
│   ├── targets/                   # Local/remote RolloutTargets
│   ├── skillruntime/              # Policy/builtin runtimes
│   ├── adapters/                  # Target/policy adapters and bridges
│   ├── policy/                    # Policy clients/servers
│   ├── perception/                # Perception plans and EnvironmentWriter
│   ├── communication/             # Envelopes, msgpack, TargetWS
│   └── schemas/                   # Runtime Pydantic schemas
├── PhyAgentOS/templates/          # Workspace and runtime templates
├── external/isaac_env/              # Isaac Sim rollout service
├── external/b1k_bench/      # BEHAVIOR-1K integration
├── scripts/                       # Initialization, Watchdog, and E2E tools
└── tests/                         # Unit and runtime tests
```

## Further Reading

- [User Manual](02-user-manual.md)
- [Developer Manual](03-developer-manual.md)
- [Documentation Index](../README.md)
