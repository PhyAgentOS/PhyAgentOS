# Embodied Targets

This file is the human-readable counterpart of `TARGETS.md`.
Each section uses `## Target: <target_id>` so the agent can load only enabled targets from `TARGETS.md`, after applying `runtime.targetEnabled` config overrides.

## Target: libero_real_remote

### Identity

- **Name**: libero_real_remote
- **Type**: remote simulation target
- **Target Class**: remote
- **Target Kind**: simulation
- **Runtime**: LiberoRemoteTargetProxy
- **Workspace**: workspaces/libero_real

### Supported Skills

| Skill | Runtime Kind | Description |
|---|---|---|
| `pi05_libero_remote` | policy | Closed-loop PI0.5 / OpenPI policy execution through the runtime session protocol. |

### Observation Contract

- **Observation Type**: multimodal
- **Empty Observation Allowed**: false
- **Image Channels**: `observation/image`, `observation/wrist_image`
- **State Channel**: `observation/state`
- **Prompt Channel**: `prompt`
- **Camera Resolution**: 256 x 256

### Action Contract

- **Action Representation**: delta_eef_pose_gripper
- **Action Dimension**: 7
- **Frame**: base
- **Chunk Mode**: variable-length chunks, default up to 50 actions
- **Policy Hz**: 20
- **Max Steps**: 280
- **Warmup Wait Steps**: 10

### Runtime Connection

- **Target Endpoint**: `targetws://libero-host:9002`
- **Target Adapter**: `target_adapter://libero_adapter`
- **Runtime Contract**: `configs/runtime/contracts/libero_real.runtime.yaml`
- **Policy Skill**: `pi05_libero_remote`

### Perception

- **Enabled**: false
- **Strict Preflight**: true
- **Sensor Config**: none
- **Perception Config**: none
- **Artifact Directory**: none

### Safety and Constraints

- Runtime sessions must be appended to `SESSIONS.md`; direct action queues are not supported.
- Preflight must verify target enablement, adapter compatibility, observation schema, policy adapter, and action contract before execution.
- Do not invent endpoints or adapter URIs. Use values from `TARGETS.md` unless the user explicitly overrides them.

## Target: go2_real_builtin

### Identity

- **Name**: go2_real_builtin
- **Type**: Unitree Go2 real robot target
- **Target Class**: remote
- **Target Kind**: real_robot
- **Runtime**: Go2RemoteTargetProxy
- **Workspace**: workspaces/go2_real

### Supported Skills

| Skill | Runtime Kind | Description |
|---|---|---|
| `go2_builtin_command` | builtin | Constrained TargetWS command loop for basic Go2 posture and short movement actions. |

### Runtime Connection

- **Target Endpoint**: `targetws://127.0.0.1:9010`
- **Target Adapter**: `target_adapter://go2_builtin_adapter`
- **Runtime Contract**: `configs/runtime/contracts/go2_builtin.runtime.yaml`
- **Robot IP**: `192.168.123.161`
- **Host Wired IP**: `192.168.123.222`
- **SDK Network Interface**: `enp4s0`

### Allowed Commands

- `stand_up`
- `balance_stand`
- `recovery_stand`
- `stand_down` / `squat`
- `damp`
- `stop`
- `move` with short low-speed velocity control

### Session Requirements

- Use `skillruntime://go2_builtin_command`.
- Every executable Go2 session must include structured `execution.steps`; do not rely on `task_description` as the command payload.
- Example: `execution.steps: [{command: stand_up}]`.
- For movement, prefer an explicit posture sequence: `stand_up`, `balance_stand`, then `move`.
- For `move`, velocity fields must be nested under `params`, for example `steps: [{command: move, params: {vx: 0.5, vy: 0.0, vyaw: 0.0, duration_s: 1.0}}]`.

### Safety and Constraints

- Move limits are `vx [-0.5, 0.5]`, `vy [-0.2, 0.2]`, `vyaw [-0.5, 0.5]`, and `duration_s [0.1, 1.0]`.
- The target server stops movement after every `move` command.
- Do not request raw SDK commands, long-range autonomous navigation, or arbitrary action chunks through this target.
- Run first tests in an open area, and prefer `stop` before changing tasks.
