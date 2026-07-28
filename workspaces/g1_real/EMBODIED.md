# EMBODIED.md — Unitree G1

## Target: g1_real_builtin

### Identity

- **Name**: g1_real_builtin
- **Type**: Unitree G1 real robot target (bipedal humanoid)
- **Target Class**: remote
- **Target Kind**: real_robot
- **Runtime**: G1RemoteTargetProxy
- **Workspace**: workspaces/g1_real

### Supported Skills

| Skill | Runtime Kind | Description |
|---|---|---|
| `g1_builtin_command` | builtin | Constrained TargetWS command loop for Loco posture, velocity control, and arm gestures. |

### Runtime Connection

- **Target Endpoint**: `targetws://127.0.0.1:9030`
- **Target Adapter**: `target_adapter://g1_builtin_adapter`
- **Runtime Contract**: `configs/runtime/contracts/g1_builtin.runtime.yaml`
- **Robot IP**: `192.168.137.1`
- **Host Wired IP**: `192.168.137.222`
- **SDK Network Interface**: `enp4s0`

### Allowed Commands

#### Loco Posture

- `squat2stand` — stand up from squat
- `balance_stand` — enter active balance stand
- `lie2stand` — stand up from lying
- `stand2squat` — stand down to squat
- `sit` — sit down (`SetFsmId(3)`)
- `damp` — enter damp mode (`SetFsmId(1)`)
- `zero_torque` — zero torque safety mode (`SetFsmId(0)`)
- `stop_move` — stop movement (`SetVelocity(0,0,0)`)

#### Velocity Control

- `move` with params `vx`, `vy`, `vyaw`, `step` — velocity control (segmented stepping)
  - `vx`: [-0.8, 0.8] m/s (forward/backward)
  - `vy`: [-0.2, 0.2] m/s (lateral)
  - `vyaw`: [-0.5, 0.5] rad/s (yaw)
  - `step`: [0.1, 2.0] s (total duration)

#### Arm Gestures

G1 supports 16 preset arm gestures via `G1ArmActionClient`:

- `release_arm` (99) — release arm to rest
- `two_hand_kiss` (11) — two-hand kiss
- `left_kiss` (12) — left kiss
- `right_kiss` (13) — right kiss
- `hands_up` (15) — raise both hands
- `clap` (17) — clap
- `high_five` (18) — high five
- `hug` (19) — hug
- `heart` (20) — make heart shape
- `right_heart` (21) — right-hand heart
- `reject` (22) — reject gesture
- `right_hand_up` (23) — raise right hand
- `x_ray` (24) — x-ray pose
- `face_wave` (25) — wave near face
- `high_wave` (26) — high wave
- `shake_hand` (27) — handshake

> **IMPORTANT**: Arm gestures require G1 to be in `balance_stand` or `squat2stand` state.

### Session Requirements

- Use `skillruntime://g1_builtin_command`.
- Every executable G1 session must include structured `execution.steps`.
- For movement, prefer an explicit posture sequence: `squat2stand`, `balance_stand`, then `move`.
- For `move`, velocity fields must be nested under `params`, for example:
  `steps: [{command: move, params: {vx: 0.8, vy: 0.0, vyaw: 0.0, step: 0.5}}]`

### Safety and Constraints

- `--host 0.0.0.0` listens on all interfaces. Use only on trusted networks.
- G1 is a bipedal humanoid with limited balance. Do not use for stairs, slopes, or rough terrain.
- Arm gestures are fast actuation with large joint travel. Ensure clearance around the arms.
- Preflight passing does not constitute official robot safety certification.
