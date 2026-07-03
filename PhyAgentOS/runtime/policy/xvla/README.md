# X-VLA Policy Server

This directory contains a PAOS-compatible websocket server for LeRobot X-VLA
LIBERO evaluation. It serves the same msgpack protocol consumed by
`OpenPIClientPolicyWrapper`, so runtime sessions can keep using
`openpi://<host>:<port>` policy endpoints.

## Install X-VLA Environment

The X-VLA conda environment is stored at
`PhyAgentOS/runtime/policy/xvla/environment.yml`. Create it from the repository
root:

```bash
conda env create -f PhyAgentOS/runtime/policy/xvla/environment.yml
```

## Start X-VLA For LIBERO

Run this in an environment with LeRobot X-VLA dependencies plus `msgpack` and
`websockets`. On this machine the environment is named `xvla`:

```bash
conda run --no-capture-output -n xvla python -m PhyAgentOS.runtime.policy.xvla.libero_server \
  --model-id lerobot/xvla-libero \
  --host 0.0.0.0 --port 8040 \
  --device cuda
```

X-VLA LIBERO evaluation uses absolute end-effector control. The official
4-suite commands below pass `--control-mode absolute` explicitly.

## Official 4-Suite LIBERO Evaluation

This is the updated target-native benchmark flow. It creates one PAOS session
per suite and lets the LIBERO target run the 10 tasks x 50 init states loop
internally. Restart the LIBERO TargetWS server from this checkout before using
this flow, because it requires the `target.benchmark` RPC.

Start both servers from the repository root.

1. Start the LIBERO TargetWS server in the `libero` environment:

```bash
MUJOCO_GL=egl PYTHONWARNINGS=ignore \
conda run --no-capture-output -n libero python PhyAgentOS/runtime/targets/remote/libero/server.py \
  --host 0.0.0.0 --port 9042 \
  --camera-height 256 --camera-width 256 \
  --max-steps 300 --num-steps-wait 10 \
  --control-mode absolute
```

2. Start the X-VLA policy server in the `xvla` environment:

```bash
export CUDA_VISIBLE_DEVICES="#"
conda run --no-capture-output -n xvla python -m PhyAgentOS.runtime.policy.xvla.libero_server \
  --model-id lerobot/xvla-libero \
  --host 0.0.0.0 --port 8040 \
  --device cuda \
  --image-size 224
```

3. Generate one target-native benchmark workspace per suite. This still
   evaluates the full 2,000-episode protocol: 4 suites x 10 tasks x 50 initial
   states.

```bash
RUN_ROOT=tests/xvla/libero_target_benchmark_$(date -u +%Y%m%dT%H%M%SZ)
export RUN_ROOT
mkdir -p "$RUN_ROOT"

for SUITE in libero_spatial libero_object libero_goal libero_10; do
  PYTHONPATH=$(pwd) conda run -n paos python scripts/prepare_libero_target_benchmark.py \
    --workspace "$RUN_ROOT/$SUITE" \
    --suite "$SUITE" \
    --policy-id xvla \
    --target-endpoint targetws://127.0.0.1:9042 \
    --policy-endpoint openpi://127.0.0.1:8040 \
    --task-ids 0-9 \
    --init-state-ids 0-49 \
    --control-mode absolute \
    --force-init
done
```

4. Run the benchmark sessions. With a single LIBERO target server, the suites
   run one after another. If you start one target/policy server pair per suite,
   run one watchdog per suite in parallel instead.

```bash
PYTHONPATH=$(pwd) conda run --no-capture-output -n paos python \
  scripts/run_eval_watchdog.py \
  --run-root "$RUN_ROOT"
```

5. Inspect results:

```bash
conda run --no-capture-output -n paos python \
  scripts/summarize_eval_results.py \
  --run-root "$RUN_ROOT"
```

## 4-Suite LIBERO Result

| Suite | Success | Success rate |
| --- | ---: | ---: |
| `libero_spatial` | 485 / 500 | 97.0% |
| `libero_object` | 485 / 500 | 97.0% |
| `libero_goal` | 492 / 500 | 98.4% |
| `libero_10` | 480 / 500 | 96.0% |
| Overall | 1942 / 2000 | 97.1% |
