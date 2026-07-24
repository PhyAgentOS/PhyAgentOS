# PhyAgentOS Operations Manual

> Version: v0.1.6 · [中文](README.md)

The PhyAgentOS development team provides this manual for deployment, demos, and operations. It focuses on reliable operation; see the [main user manual](../en/02-user-manual.md) for the complete architecture and configuration reference.

## 1. Runtime Model

```text
User/Channel → AgentLoop → SESSIONS.md → WatchdogSupervisor
                                      → Preflight
                                      → SessionRunner
                                      → Target + SkillRuntime + Policy
```

Use `paos agent` for local interaction and single turns. Use `paos gateway` for long-running Channels, Cron, and Heartbeat. Both prepare the Runtime workspace when `runtime.enabled=true` and start the Watchdog according to `runtime.autostartWatchdog`.

## 2. First Deployment

```bash
git clone https://github.com/PhyAgentOS/PhyAgentOS.git
cd PhyAgentOS
python -m pip install -e .
paos onboard
paos status
```

Set a model and matching Provider in `~/.PhyAgentOS/config.json`, then start:

```bash
paos agent
paos agent -m "list the available Runtime Targets"
```

## 3. Preflight Checklist

### Agent

- `agents.defaults.model` resolves to a configured Provider.
- `agents.defaults.workspace` is writable.
- Every MCP command/URL and credential is valid.
- Public Channels use allowlists or mention policies.

### Runtime

- `runtime.workspace` points to the intended workspace; otherwise it shares the Agent workspace.
- Only intended Targets are enabled in `TARGETS.md`.
- Remote Targets use `targetws://host:port`.
- Policies use `dummy://`, `openpi://`, `policyws://`, or `b1k-ws://`.
- Runtime Contract, Adapter ID, action shape, and Target ID agree.

### External Services

- Start TargetWS and Policy Server before submitting a Session.
- Probe protocol health independently; process existence is not sufficient.
- Isolate simulator/robot dependencies from the Agent environment.

## 4. Workspace Signals

| Signal | Healthy | Problem |
|---|---|---|
| `TARGETS.md` | Enabled Target and correct endpoint | Target/Contract mismatch |
| `SESSIONS.md` | State advances toward terminal | Stuck pending/running |
| `LOG.md` | One history entry per execution | Completion without history |
| `ENVIRONMENT.md` | Target snapshot timestamp advances | Stale state or wrong workspace |
| `artifacts/runtime/<id>/episode.json` | Complete result/step/error data | Missing/unreadable artifact |
| `LESSONS.md` | Actionable linked failure | Unstructured error only |

## 5. Session Operations

```text
pending → claimed → preflight_checking → running → finalizing → terminal
```

1. Never manually change a running Session to succeeded.
2. Correct the registry/contract after rejection, then create or explicitly rerun a Session.
3. `--session-id` resets a Session; use it only for controlled debugging.
4. The v0.1.6 Scheduler does not enforce `depends_on`; do not treat it as a production ordering guarantee.
5. Cleanup after execution timeout is best effort; external runtimes need idempotent cancel/close.

## 6. Hardware-Free Acceptance Test

```bash
python scripts/init_runtime_workspace.py --workspace /tmp/paos-runtime
python scripts/run_runtime_watchdog.py \
  --workspace /tmp/paos-runtime --once --session-id sess_dummy_smoke
```

Acceptance conditions:

- Session status is `succeeded`
- `result.success=true`
- `artifacts/runtime/sess_dummy_smoke/episode.json` exists
- `LOG.md` contains the Session

## 7. Scenario Entry Points

| Scenario | Target entry point | Policy entry point |
|---|---|---|
| LIBERO | `PhyAgentOS/runtime/targets/remote/libero/server.py` | `PhyAgentOS.runtime.policy.openpi.lerobot_pi0_server` |
| Isaac Sim | `PhyAgentOS/runtime/targets/remote/isaacsim/server.py` | Dummy/OpenPI or CommandSim |
| BEHAVIOR-1K | `external/b1k_bench/scripts/start_behavior1k_server.sh` | `start_b1k_openpi_policy_server.sh` |

The former `hal/hal_watchdog.py --driver ...` path is not a v0.1.6 runtime entry point.

## 8. Semantic Verification Operations

With a Session verification profile of `audit` or `recovery`, policy-loop completion enters `awaiting_verification`. `paos agent` owns the Verification Service lifecycle, and both SessionVerifier and target-native episode verification use that service for model-backed verdicts.

`evidenceRetention`:

- `all`: retain everything; best reviewability, highest storage use.
- `failed`: delete success evidence and retain failure/replan evidence.
- `none`: delete RGB after every valid verdict; default.

## 9. Failure Layers

| Stage | Typical error | First check |
|---|---|---|
| Config | Provider/API key | `paos status`, model prefix |
| Scheduling | Pending does not move | Watchdog, Target enablement, refs |
| Preflight | Rejected | `missing_items`, contracts, adapters |
| Target | Connection/protocol | Endpoint, startup order, network |
| Policy | Timeout/payload | Scheme, shape, timeout |
| Execution | Failed/timed out | `episode.json`, Target status |
| Verification | Waiting/error | Bundle, RGB, verifier Provider |

## 10. Current Safety Boundary

The v0.1.6 default Runtime primarily covers simulation. Current Preflight is not a complete real-robot safety certification. A real-robot Target must independently implement and validate emergency stop, workspace, velocity/force limits, operator override, and fail-safe behavior.

## Related Documentation

- [Main User Manual](../en/02-user-manual.md)
- [Framework Introduction](../en/01-framework-introduction.md)
- [Developer Manual](../en/03-developer-manual.md)
