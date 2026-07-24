# BEHAVIOR-1K TargetWS

Standalone TargetWS server for BEHAVIOR-1K / OmniGibson (R1Pro), mirroring the LIBERO integration pattern.

## Architecture

```
Terminal A (behavior conda):  behavior1k/server.py  →  targetws://127.0.0.1:9004
Terminal B (paos conda):      run_runtime_watchdog.py / run_benchmark.py --use-watchdog
         ↓
OpenPISkillRuntime → b1k_dummy_policy_adapter (or future OpenPI adapter)
         ↓
Behavior1kTargetAdapter → Behavior1KRemoteTargetProxy → TargetWS RPC
```

## Launch

**Terminal A** — simulation server (GUI):

```bash
bash external/b1k_bench/scripts/start_behavior1k_server.sh --gui --port 9004
```

**Terminal B** — single smoke session:

```bash
conda activate paos
python scripts/run_runtime_watchdog.py \
  --workspace external/b1k_bench/workspaces/behavior1k_eval \
  --session-id sess_b1k_turning_on_radio_0_smoke \
  --once
```

**Benchmark orchestration** (default backend is `runtime_watchdog`):

```bash
python external/b1k_bench/scripts/run_benchmark.py \
  --benchmark behavior-1k \
  --suite smoke3 \
  --policy dummy_baseline \
  --tasks turning_on_radio \
  --instance-ids 0
```

Legacy native `eval.py` subprocess path remains available via `execution_backend: behavior1k_native` in `BENCHMARKS.md`.

## RPC surface

Same TargetWS v2 methods as LIBERO: `target.describe`, `reset`, `observe`, `action_chunk`, `execution_status`, `cancel`, `close`.

- Actions: `[T, 23]` float32 (R1Pro joint command vector)
- Observations: `head_rgb`, `left_wrist_rgb`, `right_wrist_rgb`, `proprio[256]`
- Task selection: `benchmark.task_name` + `benchmark.instance_id` (0–9 slot → TRO instance via `test_instances.csv`)

## Environment

| Item | Value |
|------|-------|
| Server conda | `behavior` |
| Watchdog conda | `paos` |
| Isaac path | `/home/zyserver/isaacsim3` |
| Default port | `9004` |
| BEHAVIOR-1K root | `/home/zyserver/work/BEHAVIOR-1K` |
