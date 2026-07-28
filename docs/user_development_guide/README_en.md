# PhyAgentOS Integration Development Guide

> Version: v0.1.6 · [中文](README.md)

The PhyAgentOS development team provides this guide for ecosystem integrators adding Targets, policies, or execution capabilities to the current Session-Centered Runtime.

## 1. Select the Correct Extension Point

| Requirement | Extension point | Do not modify |
|---|---|---|
| New environment/robot | `BaseRolloutTarget` + TargetAdapter + Contract | AgentLoop, Scheduler |
| New policy service | `BasePolicyClient` + PolicyAdapter | Target internals |
| New closed-loop execution | Policy/Builtin SkillRuntime | Raw Target/SDK |
| New action conversion | `BaseActionBridge` | Implicit adapter truncation |
| New perception model | Perception Plugin + Config | Manual `ENVIRONMENT.md` writes |
| New message ingress | Channel | Runtime Session state machine |

## 2. Target Integration Loop

1. Define lifecycle, observation, action, and tool contracts.
2. Implement `BaseRolloutTarget`; remote Targets use `TargetWSClient`/`RemoteTargetProxy`.
3. Implement a TargetAdapter with comparable input/output contracts.
4. Add a `runtime_target_contract_v1` YAML document.
5. Register the Runtime factory.
6. Declare the Target in `TARGETS.md` with only validated Skill Runtimes.
7. Test rejection, success, timeout, cancellation, and resource release.

```python
register_local_target_runtime("MyTargetRuntime", build_my_target)
register_remote_target_runtime("MyRemoteTargetProxy", build_my_proxy)
```

v0.1.6 uses explicit Python registration, not the former Driver plugin manifest.

## 3. Skill Runtime Integration Loop

Policy path:

```text
Target.observe
→ TargetAdapter.to_runtime_observation
→ PolicyAdapter.to_policy_input
→ PolicyClient.infer
→ PolicyAdapter.from_policy_output
→ ActionBridge
→ TargetAdapter.to_executable_action_chunk
→ Target.action_chunk
```

Builtin path:

```text
BuiltinSkillRuntime
→ TargetSessionHandle.call_target_tool
→ TargetToolManifest validation
→ Target.call_target_tool
```

A Skill Runtime never receives a raw Target and never opens TargetWS itself.

## 4. Contract Design

### Observation

- TargetAdapter output covers every required PolicyAdapter sensor key.
- Shape, dtype, and layout are explicitly compatible.
- Both Target and Skill declare Empty Observation; Policy Runtime currently rejects it.

### Action

- `representation` belongs to the Target's accepted representations.
- The final dimension of 2-D action shapes matches.
- normalized → non-normalized requires an explicit denormalization bridge.
- No implicit truncation, zero-padding, or representation casts.

### Perception

- Sensor Config describes acquisition and observation schema.
- Perception Config describes models, plugins, and pipelines.
- Skill `requires` describes outputs required by this execution.

## 5. Remote Target Protocol

Use `phyagentos.runtime_rpc.v2` + msgpack:

```yaml
version: phyagentos.runtime_rpc.v2
type: target.observe
session_id: sess_001
target_id: target_001
skillruntime_id: skill_001
seq: 1
timestamp_ns: 0
trace_id: trace_001
payload: {}
```

Responses match type (`target.observe` → `target.observation`), seq, session, target, and skillruntime. Return `runtime.error` with a stable code and actionable message on failure.

See [Communication Architecture](COMMUNICATION_en.md) for ownership details.

## 6. Development Workflow

```bash
python scripts/init_runtime_workspace.py --workspace /tmp/my-runtime
# Edit TARGETS/SKILLRUNTIME/Contract/SESSIONS
python scripts/run_runtime_watchdog.py \
  --workspace /tmp/my-runtime --once --session-id <id>
pytest tests/runtime
```

Validate failure paths first: unknown Runtime, invalid endpoint, missing Adapter, incompatible shape, missing sensor, and Target timeout. An integration is operational only when rejection is deterministic too.

## 7. Artifacts and State Writeback

- Only `SessionRegistry` advances Session state.
- `ResultWriter` writes `LOG.md`, episodes, and LESSONS.
- `EnvironmentWriter` owns Environment v2 reconciliation/merge.
- Large arrays, images, and point clouds belong in artifacts, not Markdown.
- The Agent-owned Verification Service performs model-backed semantic
  verification and strict response normalization. `SessionVerifier` applies
  policy-loop verdicts, while target-native benchmarks request episode verdicts
  from the same service at attempt boundaries.

## 8. Real-Robot Requirements

The current `preview` Runtime registers the constrained `go2_real_builtin`
real-robot Target. Other physical-robot integrations must still implement
target-side emergency stop, workspace/velocity/force limits, command freshness,
operator override, disconnect stop, and idempotent cancel/close. Passing
current Preflight is not real-robot safety certification.

## 9. Merge Gates

A new Runtime integration should include:

- complete Target/Skill/Adapter/Contract registration
- reproducible Dummy or Mock tests
- accepted and rejected Preflight cases
- timeout/cancel/close resource-release cases
- one end-to-end Session artifact
- synchronized Chinese/English startup instructions and boundaries

## 10. Future Design Direction

HAL v3 continues toward strict Environment Contracts, real-robot SafetyGuard, dependency scheduling, agent-interactive runtimes, Goal Graph/Session Compiler, and Fleet orchestration. Extensions should evolve along these boundaries without reintroducing Driver-Centered cross-layer calls.

## Related Documentation

- [Unitree Go2 Quick Start Guide](UNITREE_GO2_QUICK_START_en.md)
- [Developer Manual](../en/03-developer-manual.md)
- [Communication Architecture](COMMUNICATION_en.md)
- [Operations Manual](../user_manual/README_en.md)
