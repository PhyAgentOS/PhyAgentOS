# LIBERO Remote Target

This directory contains the real LIBERO TargetWS integration.

## Components

- `proxy.py`: runtime-side `LiberoRemoteTargetProxy`, used by the PhyAgentOS
  watchdog in the `paos` environment.
- `server.py`: standalone TargetWS server for a machine that has LIBERO,
  robosuite, MuJoCo, and the benchmark assets installed. It intentionally avoids
  importing the PhyAgentOS package so it can run in a LIBERO Python 3.8
  environment.

## Start The Target Server

Run this on the LIBERO machine:

```bash
MUJOCO_GL=egl PYTHONWARNINGS=ignore \
conda run --no-capture-output -n libero python PhyAgentOS/runtime/targets/remote/libero/server.py \
  --host 0.0.0.0 --port 9002 \
  --benchmark-name libero_spatial --task-id 0 --init-state-id 0 \
  --camera-height 256 --camera-width 256 \
  --max-steps 300 --num-steps-wait 10 \
  --control-mode relative
```

The runtime target endpoint is:

```text
targetws://<libero-host>:9002
```

`target.describe` returns benchmark metadata including task list information.
`target.action_chunk` and `target.execution_status` return `episode_summary`
for benchmark artifacts.

## Prepare A Full Suite Benchmark

After the LIBERO TargetWS and an OpenPI-compatible policy server are running,
create one pending runtime session per task/init-state pair:

```bash
PYTHONPATH=$(pwd) conda run -n paos python scripts/prepare_libero_suite_benchmark.py \
  --workspace /tmp/paos_libero_pi05_spatial \
  --suite libero_spatial \
  --policy-id pi05 \
  --skillruntime-id pi05_libero_remote \
  --target-endpoint targetws://127.0.0.1:9002 \
  --policy-endpoint openpi://127.0.0.1:8000 \
  --task-ids all \
  --init-state-ids 0
```

For a larger evaluation, pass a wider init-state range, for example
`--init-state-ids 0-49` if those states are available for the selected suite.

For OpenVLA:

```bash
PYTHONPATH=$(pwd) conda run -n paos python scripts/prepare_libero_suite_benchmark.py \
  --workspace /tmp/paos_libero_openvla_spatial \
  --suite libero_spatial \
  --policy-id openvla \
  --skillruntime-id openvla_libero_remote \
  --target-endpoint targetws://127.0.0.1:9002 \
  --policy-endpoint openpi://127.0.0.1:8000 \
  --task-ids all \
  --init-state-ids 0
```

For X-VLA, `--control-mode auto` selects absolute LIBERO control:

```bash
PYTHONPATH=$(pwd) conda run -n paos python scripts/prepare_libero_suite_benchmark.py \
  --workspace /tmp/paos_libero_xvla_spatial \
  --suite libero_spatial \
  --policy-id xvla \
  --skillruntime-id xvla_libero_remote \
  --target-endpoint targetws://127.0.0.1:9002 \
  --policy-endpoint openpi://127.0.0.1:8000 \
  --task-ids all \
  --init-state-ids 0
```

Then let the watchdog claim and execute sessions:

```bash
while PYTHONPATH=$(pwd) conda run -n paos python scripts/run_runtime_watchdog.py \
  --workspace /tmp/paos_libero_pi05_spatial --once; do
  sleep 1
done
```

Use the workspace path created for the selected policy, for example
`/tmp/paos_libero_openvla_spatial` or `/tmp/paos_libero_xvla_spatial`.

Results are written under the workspace's `SESSIONS.md`, `LOG.md`, and
`artifacts/runtime/<session_id>/episode.json`.

## Target-Native Suite Benchmark

For high-throughput benchmarking, the LIBERO target also exposes
`target.benchmark`. In this mode PAOS creates one session for the whole suite,
and the LIBERO target runs the task/init-state loop internally against the
policy endpoint. This avoids the per-step PAOS policy loop and keeps the result
as one benchmark artifact.

```bash
PYTHONPATH=$(pwd) conda run -n paos python scripts/prepare_libero_target_benchmark.py \
  --workspace /tmp/paos_libero_xvla_spatial_target_benchmark \
  --suite libero_spatial \
  --policy-id xvla \
  --target-endpoint targetws://127.0.0.1:9002 \
  --policy-endpoint openpi://127.0.0.1:8000 \
  --task-ids 0-9 \
  --init-state-ids 0-49 \
  --control-mode absolute \
  --force-init
```

Run the single benchmark session:

```bash
PYTHONPATH=$(pwd) conda run --no-capture-output -n paos python \
  scripts/run_runtime_watchdog.py \
  --workspace /tmp/paos_libero_xvla_spatial_target_benchmark \
  --once
```

The target server log prints per-episode progress. Summaries use the same
script:

```bash
conda run --no-capture-output -n paos python scripts/summarize_eval_results.py \
  --workspace /tmp/paos_libero_xvla_spatial_target_benchmark
```
