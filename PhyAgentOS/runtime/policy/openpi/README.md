# OpenPI-Compatible Policy Runtime

This directory contains the OpenPI-compatible policy wire integration.

## Components

- `client.py`: websocket client used by runtime skills for `openpi://` and
  `policyws://` endpoints.
- `lerobot_pi0_server.py`: standalone websocket policy server for LeRobot
  pi0-family checkpoints. The checkpoint `config.json` `type` selects the
  LeRobot policy class: `pi0`, `pi05`, or `pi0fast`.
- `native_openpi_server.py`: standalone websocket policy server for official
  OpenPI checkpoints. Use this for OpenPI-native checkpoints that contain
  `params/` or official OpenPI PyTorch checkpoints, without depending on
  LeRobot policy classes.
- `../msgpack_numpy.py`: numpy msgpack wire codec used by the OpenPI-compatible
  protocol.

## Install OpenPI Environment

The exported conda environment is stored at
`PhyAgentOS/runtime/policy/openpi/environment.yml`. Create it from the
repository root:

```bash
conda env create -f PhyAgentOS/runtime/policy/openpi/environment.yml
```

## Policy Endpoint

The runtime policy endpoint is:

```text
openpi://<policy-host>:8000
```

On connect, the server returns metadata including `policy_type`, `backend`,
`model_dir`, `chunk_size`, `n_action_steps`, and `action_dim`.

## Start An Official OpenPI Policy Server

Run this in the environment that has the official OpenPI package installed:

```bash
conda run --no-capture-output -n openpi python -m PhyAgentOS.runtime.policy.openpi.native_openpi_server \
  --policy-config pi05_libero \
  --checkpoint-dir gs://openpi-assets/checkpoints/pi05_libero \
  --host 0.0.0.0 --port 8000
```

For the official OpenPI PI0 LIBERO checkpoint:

```bash
conda run --no-capture-output -n openpi python -m PhyAgentOS.runtime.policy.openpi.native_openpi_server \
  --policy-config pi0_libero \
  --checkpoint-dir gs://openpi-assets/checkpoints/pi0_libero \
  --host 0.0.0.0 --port 8000
```

OpenPI-native checkpoints usually contain `params/`; LeRobot checkpoints contain
`config.json` and `model.safetensors`. Use `native_openpi_server.py` for the
former and `lerobot_pi0_server.py` for the latter.

## Official PI0.5 4-Suite LIBERO Evaluation

This is the updated target-native benchmark flow. It creates one PAOS session
per suite and lets the LIBERO target run the 10 tasks x 50 init states loop
internally against the PI0.5 policy endpoint. Restart the LIBERO TargetWS
server from this checkout before using this flow, because it requires the
`target.benchmark` RPC.

Start both servers from the repository root.

1. Start the LIBERO TargetWS server in the `libero` environment:

```bash
MUJOCO_GL=egl PYTHONWARNINGS=ignore \
conda run --no-capture-output -n libero python PhyAgentOS/runtime/targets/remote/libero/server.py \
  --host 0.0.0.0 --port 9022 \
  --camera-height 256 --camera-width 256 \
  --max-steps 300 --num-steps-wait 10 \
  --control-mode relative
```

2. Start the official OpenPI PI0.5 policy server:

```bash
export CUDA_VISIBLE_DEVICES="#"
conda run --no-capture-output -n openpi python -m PhyAgentOS.runtime.policy.openpi.native_openpi_server \
  --policy-config pi05_libero \
  --checkpoint-dir gs://openpi-assets/checkpoints/pi05_libero \
  --host 0.0.0.0 --port 8020
```

3. Generate one target-native benchmark workspace per suite. This still
   evaluates the full 2,000-episode protocol: 4 suites x 10 tasks x 50 initial
   states.

```bash
RUN_ROOT=tests/openpi/pi05/libero_target_benchmark_$(date -u +%Y%m%dT%H%M%SZ)
export RUN_ROOT
mkdir -p "$RUN_ROOT"

for SUITE in libero_spatial libero_object libero_goal libero_10; do
  PYTHONPATH=$(pwd) conda run -n paos python scripts/prepare_libero_target_benchmark.py \
    --workspace "$RUN_ROOT/$SUITE" \
    --suite "$SUITE" \
    --policy-id pi05 \
    --target-endpoint targetws://127.0.0.1:9022 \
    --policy-endpoint openpi://127.0.0.1:8020 \
    --task-ids 0-9 \
    --init-state-ids 0-49 \
    --control-mode relative \
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

## PI0 Eval

PI0 uses the same LIBERO TargetWS server, OpenPI-native policy server,
relative control mode, session generator, watchdog, and result summarizer. To
run PI0 instead of PI0.5, change only these fields:

| Location | PI0.5 value | PI0 value |
| --- | --- | --- |
| Policy server `--policy-config` | `pi05_libero` | `pi0_libero` |
| Policy server `--checkpoint-dir` | `gs://openpi-assets/checkpoints/pi05_libero` | `gs://openpi-assets/checkpoints/pi0_libero` |
| `RUN_ROOT` | `tests/openpi/pi05/libero_target_benchmark_...` | `tests/openpi/pi0/libero_target_benchmark_...` |
| `prepare_libero_target_benchmark.py --policy-id` | `pi05` | `pi0` |

For example, the PI0 policy server command is:

```bash
conda run --no-capture-output -n openpi python -m PhyAgentOS.runtime.policy.openpi.native_openpi_server \
  --policy-config pi0_libero \
  --checkpoint-dir gs://openpi-assets/checkpoints/pi0_libero \
  --host 0.0.0.0 --port 8020
```

And the PI0 workspace generation differences are:

```bash
RUN_ROOT=tests/openpi/pi0/libero_target_benchmark_$(date -u +%Y%m%dT%H%M%SZ)

# inside the suite loop:
    --policy-id pi0 \
```

Keep `--control-mode relative`, the four suite names, `--init-state-ids 0-49`,
and the watchdog/result commands unchanged.
