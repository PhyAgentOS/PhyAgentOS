---
name: kai0-libero
description: Run LIBERO benchmark batches with the kai0 policy and read back benchmark results.
metadata: {"PhyAgentOS":{"always":false,"requires":{"runtime":["kai0-libero"]}}}
---

# kai0-libero Benchmark

Use this skill to run LIBERO evaluation batches through the kai0 policy and read
results back. The skill owns two stable Tool IDs:

- `kai0_libero.benchmark` — **Action**; run a LIBERO batch (suite × task_ids ×
  init_state_ids × num_runs) with the kai0 policy in simulation and return the
  benchmark result.
- `kai0_libero.policy` — **Session**; own the persistent kai0 inference service
  (openpi serve_policy). `start` attaches to a running server or launches the
  bundled weights with a three-stage readiness gate; the ready session is reused
  across batches; `stop` is the session's only termination path and releases the GPU.

Discover the live schema, readiness, and context of either tool before calling it;
never invent unavailable suites, episode ranges, or limits. The gateway rejects
schema-invalid arguments before they reach the endpoint.

Use the PAOS bridge tools for the Action tool: `forge_tool_context`,
`forge_tool_start_action`, `forge_tool_action_status`, `forge_tool_action_result`,
and `forge_tool_cancel_action`. The bridge tool names are transport operations;
always pass the stable Tool ID explicitly. Do not use shell commands or construct
Gateway HTTP requests directly. Session bridge operations, when available, follow
the same pattern (start/status/stop/result against `kai0_libero.policy`).

This Skill owns task-level Tool selection, sequencing, and polling only. It must not
drive the policy, the simulator, or the inference server directly.

## 1. The benchmark Action tool

### 1.1 Interpret the request

Map the user's evaluation request onto the Tool arguments:

- `suite` (required): one of `libero_spatial`, `libero_object`, `libero_goal`,
  `libero_10`. The official protocol for kai0-libero is `libero_spatial`.
- `task_ids` (optional): task index list, each 0-9. Omit for the full task set.
- `init_state_ids` (optional): init state list, each 0-49. **Default is `[0]`** — a
  smoke-scale single init state per task. Pass the explicit full range for a full run.
- `num_runs` (optional): 1-5, default 1. The official protocol uses 1.
- `max_steps` (optional): 1-1000, default 300. The official `libero_spatial` protocol
  freezes `max_steps = 220`; use 220 for protocol-aligned spatial runs.
- `seed` (optional, default 0): deterministic per-episode layouts.

Hard limit: `len(task_ids) × len(init_state_ids) × num_runs ≤ 500` per invocation. The
endpoint rejects larger batches with the current limit — split them into multiple
invocations instead. A full `libero_spatial` official run is exactly 10 × 50 × 1 = 500.

Example for a full official spatial run:

```json
{
  "tool_id": "kai0_libero.benchmark",
  "arguments": {"suite": "libero_spatial", "max_steps": 220}
}
```

### 1.2 Start and track the Action

1. Call `forge_tool_context` for `kai0_libero.benchmark`; require it to be ready.
2. Start through `forge_tool_start_action`. A `202` with an invocation ID is admission,
   not completion.
3. Retain the invocation ID. Poll `forge_tool_action_status` with bounded intervals
   and a task deadline (full batches take up to several hours; progress events are
   advisory and carry episode counters).
4. Only one batch runs at a time: a second invoke while a run is active is rejected
   with `BUSY` and the active `run_id` — poll the existing invocation instead of
   retrying blindly.
5. Fetch the terminal result with `forge_tool_action_result`. The result carries:
   `run_id`, `status` (`succeeded`/`failed`/`cancelled`/`partial`),
   `completed_episodes`, `total_episodes`, `success_rate`, `result_file`, and
   `failure_summary`. Report success only for a terminal `succeeded` result.

### 1.3 Cancel

- Issue cancel once with a reason via `forge_tool_cancel_action`.
- Accepted cancellation does not prove the batch has stopped: keep reconciling
  status/result until a terminal result is observed.
- Cancellation stops the batch at the current episode boundary: completed episodes are
  kept as a partial result (`status` = `partial` or `cancelled`) and the result file is
  preserved.
- Terminal invocations cannot be cancelled; a cancel on them returns the current state.

## 2. The policy Session tool

### 2.1 Lifecycle contract

`kai0_libero.policy` (operation `serve`) is a **persistent inference-service session**:

1. **start** is attach-or-launch. If the inference server already answers
   `GET /healthz` with 200, the session **attaches** to it (`owned=false`) and never
   starts or kills a process. Otherwise the node **launches** the service from the
   weights shipped in this skill bundle (`scripts/start_server.sh --ckpt <weights>
   --policy-config pi05_libero`, `owned=true`).
2. **Readiness gate** (three stages, in order): `/healthz` 200 → `infer-once` succeeds
   with `action_dim=7` → the norm_stats file sha256 matches the declared value
   (`b3a44bb28…40c960bd84`). Only after all three pass is the session accepted as
   ready. On failure the launched service is torn down and the start reports
   `READINESS_FAIL` (retryable) — fix the environment, do not retry blindly.
3. **Reuse**: a ready session serves every batch in this runtime. Do not start a new
   session per batch; a duplicate start returns the current session state instead of
   relaunching.
4. **No deadline**: sessions are unbounded by design. The gateway never marks a
   session `unknown` on a timeout — `stop` is its only termination path.
5. **stop** (the only control admitted for sessions) transitions the session through
   `stopping` to `stopped`. An `owned` session is torn down (SIGTERM to the process
   group, 30s grace, then SIGKILL) and the GPU is released; an `attached` session is
   left running. A stop on an already-stopped session is answered from the record.
6. Sessions never accept `cancel`, and Actions never accept `stop` — control commands
   are semantics-scoped and the gateway answers the other combination with
   `unsupported`.

### 2.2 Ordering with batches

- Before a batch run, ensure the session is ready (start if absent, attach if a
  server is already up).
- After the last batch of a task, `stop` the session to release the GPU — a launched
  service left running occupies the GPU beyond the task lifetime.
- A `BUSY` from the benchmark tool is about the benchmark endpoint, not the session;
  a single batch at a time, but the session stays ready across many.

## 3. Errors and replanning

- `BUSY`: a run is already active; wait for or query the active invocation. Do not
  start competing batches.
- `INVALID_ARGUMENTS`: correct the arguments per the live schema (especially the 500
  episode cap) and retry; never silently truncate a batch to make it fit.
- Timeout, transport loss, or `unknown`: reconcile the existing invocation through
  status/result before starting a new batch. An `unknown` result means the batch may
  still be running; do not blindly rerun the same configuration.
- `failed`/`partial` with `failure_summary`: read the `result_file` for per-episode
  details before rerunning.
- `READINESS_FAIL` on session start: inspect the readiness stage detail in the result;
  the service may already be running under another owner (then attach instead of
  launch).
- Missing `result_file` or incomplete result: treat as a failed invocation and re-run.

## 4. External prerequisites (not managed by this skill)

1. **Weights ship in the skill bundle** (`weights/`, ~12.4GB π0.5-libero: `params/`
   plus `assets/<repo_id>/norm_stats.json`). They are staged at packaging time and
   unpacked into the skill workspace at install; nothing is downloaded at runtime.
2. **Environment**: the node binaries carry their own runtime environments (the
   benchmark node's simulation environment and the policy node's python/jax venv are
   prepared by the node repositories' build/install steps, not by this skill).
3. **Hardware**: a GPU with ≥16GB memory for π0.5-libero inference.
4. The openpi serve_policy process is **not** an external prerequisite: its lifecycle
   belongs to the `kai0_libero.policy` session tool (attach-or-launch, §2.1).
