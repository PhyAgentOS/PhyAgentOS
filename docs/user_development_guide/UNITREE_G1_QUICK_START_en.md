# Unitree G1 Quick Start Guide

> Target branch: `preview` · [中文](UNITREE_G1_QUICK_START.md)

This guide explains how to connect a Unitree G1 humanoid robot to the
`g1_real_builtin` Target in PhyAgentOS over a wired network from a Linux host.
The current integration supports posture changes, short-distance low-speed
movement, and preset arm gestures. It does not support navigation, rough-terrain
mobility, or extended autonomous operation.

> [!WARNING]
> The G1 is a physical motion system with precision joints and arm mechanisms.
> For initial tests, clear the surrounding area to at least 2 meters, place the
> robot on a level non-slip surface, and keep an operator within immediate
> emergency-stop range. Complete `--dry-run` first. Test stand, stop, and sit
> commands before attempting movement or arm gestures. During arm gesture tests
> ensure nothing is in the arm's path to avoid clamping or collision damage.

## 1. Integration Overview

PhyAgentOS and Unitree SDK2 run in separate Python environments:

```text
PhyAgentOS (Python >= 3.11)
        │  TargetWS / WebSocket, default 127.0.0.1:9030
        ▼
G1 TargetWS Server (Python 3.10 + Unitree SDK2)
        │  CycloneDDS over the wired interface
        ▼
Unitree G1 (default 192.168.137.1)
```

Compared to Go2, G1 introduces an additional **G1ArmActionClient** module for
arm preset motions. A single TargetWS Server instance initializes both
`LocoClient` and `G1ArmActionClient` SDK clients simultaneously.

The default values are shown below. Replace them consistently if your robot or
host uses different settings.

| Item | Default |
|---|---|
| G1 IP | `192.168.137.1` |
| Host wired IP | `192.168.137.222/24` |
| SDK interface | `enp4s0` (use the value detected on your host) |
| TargetWS endpoint | `targetws://127.0.0.1:9030` |

## 2. Prepare the Robot and Host

Recommended prerequisites:

- a Unitree G1 with a sufficiently charged battery;
- an Ubuntu/Linux host with wired Ethernet;
- an Ethernet cable;
- Conda or Miniconda;
- an API key for a supported model provider;
- a clear, level, non-slip test area (recommended radius 2 meters or more);
- ensure nothing obstructs the G1 arm's path.

Connect the cable and power on the robot. In the host network settings, set the
wired IPv4 method to manual, use `192.168.137.222` as the address, and use
`255.255.255.0` (`/24`) as the subnet mask. A direct connection normally does
not need a gateway or DNS server.

Identify the wired interface and confirm its address:

```bash
ip -brief address
ip route
```

Older systems may also use:

```bash
ifconfig
```

Record the name of the interface carrying `192.168.137.222`, such as `enp4s0`.
Do not copy the example verbatim.

Verify the host can reach the robot:

```bash
ping -c 4 192.168.137.1
```

Only proceed once you receive replies. If the ping fails, check the Ethernet
cable, robot power, host static IP, subnet mask, and interface state.

## 3. Install PhyAgentOS

Create a Python 3.11 environment and install the `preview` branch:

```bash
conda create -n paos python=3.11 -y
conda activate paos

git clone --branch preview --single-branch https://github.com/PhyAgentOS/PhyAgentOS.git
cd PhyAgentOS
python -m pip install -U pip
pip install -e .
```

Verify the CLI entry point:

```bash
paos --help
```

All subsequent commands referencing `PhyAgentOS/...` must be run from the
repository root.

## 4. Install the Unitree SDK2 Environment

The Unitree SDK2 uses a separate Python 3.10 environment; the `paos`
environment does not need to install the SDK.

```bash
conda create -n g1-sdk python=3.10 -y
conda activate g1-sdk
python -m pip install -U pip setuptools wheel

pip install "cyclonedds==0.10.2" numpy opencv-python websockets msgpack

cd ~
git clone https://github.com/unitreerobotics/unitree_sdk2_python.git
cd unitree_sdk2_python
pip install -e .
```

If the last step reports that CycloneDDS cannot be found, build CycloneDDS
0.10.x first, then reinstall the SDK:

```bash
cd ~
git clone --branch releases/0.10.x https://github.com/eclipse-cyclonedds/cyclonedds.git
cd cyclonedds
mkdir -p build install
cd build
cmake .. -DCMAKE_INSTALL_PREFIX=../install
cmake --build . --target install

cd ~/unitree_sdk2_python
export CYCLONEDDS_HOME=~/cyclonedds/install
pip install -e .
```

Verify the SDK imports:

```bash
conda run -n g1-sdk python - <<'PY'
from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
from unitree_sdk2py.g1.arm.g1_arm_action_client import G1ArmActionClient
print("g1-sdk import ok")
PY
```

## 5. Initialize and Configure PhyAgentOS

Return to the repository root and initialize:

```bash
conda activate paos
cd /path/to/PhyAgentOS
paos onboard
```

This command creates `~/.PhyAgentOS/config.json` and a default workspace at
`~/.PhyAgentOS/workspace`.

Edit `~/.PhyAgentOS/config.json` to configure your chosen model and the
corresponding Provider API key, and enable the G1 Target. The snippet below
shows only the fields you need to care about; merge them into the full JSON
generated by `paos onboard` rather than overwriting the entire file with the
snippet.

```json
{
  "agents": {
    "defaults": {
      "model": "<provider>/<model>"
    }
  },
  "providers": {
    "<provider>": {
      "apiKey": "<your-api-key>"
    }
  },
  "runtime": {
    "enabled": true,
    "targetEnabled": {
      "g1_real_builtin": true
    }
  }
}
```

Do not commit real API keys to Git repositories or paste them into public logs.

The `runtime.targetEnabled` value takes precedence over `enabled` in
`TARGETS.md`, which is the recommended way to activate a target. You can also
set `g1_real_builtin.enabled` to `true` in the workspace `TARGETS.md`.

If your robot IP, host IP, or interface name differs from the defaults, update
the workspace files consistently:

- `g1_real_builtin.config` in `~/.PhyAgentOS/workspace/TARGETS.md`;
- Runtime Connection section for `g1_real_builtin` in
  `~/.PhyAgentOS/workspace/EMBODIED.md`.

`TARGETS.md` is auto-generated on the first Agent start. To modify it before
that, copy the template first:

```bash
cp PhyAgentOS/templates/TARGETS.md ~/.PhyAgentOS/workspace/TARGETS.md
```

The TargetWS Server `--network-interface` and `--robot-ip` arguments must use
the same real values.

## 6. Run dry-run First

Open Terminal A and start the TargetWS Server in dry-run mode (no real robot
communication):

```bash
conda run --no-capture-output -n g1-sdk \
  python PhyAgentOS/runtime/targets/remote/g1/server.py \
  --host 0.0.0.0 \
  --port 9030 \
  --network-interface enp4s0 \
  --robot-ip 192.168.137.1 \
  --dry-run
```

The following line indicates the server is listening:

```text
G1 TargetWS server listening on targetws://0.0.0.0:9030
```

Open Terminal B and start the Agent:

```bash
conda activate paos
cd /path/to/PhyAgentOS
paos agent
```

You can first ask "how many robots are connected?" and then explicitly request:

```text
Use the g1_real_builtin Target to execute squat2stand; this is dry-run, do
not perform any other action.
```

No SDK commands are sent to the G1 during dry-run. Once the Agent recognizes
`g1_real_builtin`, creates a Session, and returns success, proceed to real
robot testing.

## 7. Test with the Real Robot

Press `Ctrl+C` to stop the dry-run Server. Confirm again that the area around
the robot is clear, the ground is level, and an operator is in position, then
remove `--dry-run` in Terminal A:

```bash
conda run --no-capture-output -n g1-sdk \
  python PhyAgentOS/runtime/targets/remote/g1/server.py \
  --host 0.0.0.0 \
  --port 9030 \
  --network-interface enp4s0 \
  --robot-ip 192.168.137.1
```

Run `paos agent` in Terminal B. Test each item in order, confirming the robot
state before proceeding:

1. `Make the G1 stand up from a squat.`
2. `Make the G1 enter balance stand.`
3. `Stop the G1's movement.`
4. `Make the G1 sit down.`

After completing the above, try a short movement:

```text
Make the G1 stand up and enter balance stand, then move with vx=0.1, vy=0,
vyaw=0 for 0.5 seconds, and finally stop.
```

## 8. Supported Commands and Limits

### 8.1 Loco Posture Commands

| Command | Description |
|---|---|
| `squat2stand` | Stand up from squat (`SetFsmId(706)`) |
| `balance_stand` | Balance stand |
| `lie2stand` | Stand up from lying (`SetFsmId(702)`) |
| `stand2squat` | Stand up then squat (`SetFsmId(706)`) |
| `sit` | Sit down (`SetFsmId(3)`) |
| `damp` | Damp mode (`SetFsmId(1)`) |
| `zero_torque` | Zero torque / safety (`SetFsmId(0)`) |
| `stop_move` | Stop movement |

### 8.2 Velocity Control Command

| Command | Parameters | Description |
|---|---|---|
| `move` | `vx`, `vy`, `vyaw`, `step` | Velocity control (staged stepping mode) |

The TargetWS Server clips `move` parameters to the following ranges:

| Parameter | Range | Meaning |
|---|---:|---|
| `vx` | `[-0.8, 0.8]` m/s | Forward/backward speed |
| `vy` | `[-0.2, 0.2]` m/s | Lateral speed |
| `vyaw` | `[-0.5, 0.5]` rad/s | Yaw angular speed |
| `step` | `[-0.1, 2.0]` s | Total movement duration |

After each `move` completes, the Server automatically calls `StopMove()`. The
current Target does not expose raw SDK commands to the Agent, nor does it
accept arbitrary Action Chunks.

### 8.3 Arm Preset Gesture Commands

| Command | Action ID | Description |
|---|---:|---|
| `two_hand_kiss` | 11 | Two-hand kiss |
| `left_kiss` | 12 | Left kiss |
| `right_kiss` | 13 | Right kiss |
| `hands_up` | 15 | Hands up |
| `clap` | 17 | Clap |
| `high_five` | 18 | High five |
| `hug` | 19 | Hug |
| `heart` | 20 | Heart |
| `right_heart` | 21 | Right heart |
| `reject` | 22 | Reject |
| `right_hand_up` | 23 | Right hand up |
| `x_ray` | 24 | X-ray |
| `face_wave` | 25 | Face wave |
| `high_wave` | 26 | High wave |
| `shake_hand` | 27 | Handshake |
| `release_arm` | 99 | Release arm to rest |

> [!IMPORTANT]
> Arm gestures require the G1 to be in `balance_stand` or `squat2stand` state.
> If the G1 is not standing, execute a posture command first. Ensure nothing
> obstructs the robot's arms during gesture execution.

## 9. Stop and Disconnect

On normal shutdown:

1. Have the robot execute `stop_move`;
2. Once clear, execute `sit` or `damp`;
3. Press `Ctrl+C` to exit `paos agent`;
4. Press `Ctrl+C` to exit the G1 TargetWS Server.

The TargetWS Server attempts to call `StopMove()` on exit. This does not replace
an on-site emergency stop or operator supervision; for abnormal motion, use the
robot's physical safety measures first.

## 10. Troubleshooting

| Symptom | Check and resolve |
|---|---|
| `ping` fails | Check Ethernet cable, power, `192.168.137.222/24`, interface UP state; other networks may be抢占ing the route. |
| `unitree_sdk2py` not found | Confirm the Server runs in the `g1-sdk` environment and `pip install -e .` completed in the `unitree_sdk2_python` directory. |
| CycloneDDS not found | Build 0.10.x per Section 4, set `CYCLONEDDS_HOME`, and reinstall the SDK. |
| Server starts but robot unresponsive | Re-confirm `--network-interface` is the wired interface; ensure the robot is reachable by `ping`; check SDK error codes in Server logs. |
| `Connection refused` / TargetWS unreachable | Confirm the Server is listening on port `9030`; use `targetws://127.0.0.1:9030` on the same host. For remote hosts, update the `TARGETS.md` endpoint to the server host IP and configure the firewall. |
| `TARGET_DISABLED` | Set `runtime.targetEnabled.g1_real_builtin: true` in `config.json`, or update the workspace `TARGETS.md`. |
| Agent reports model or API Key error | Check the model name, Provider selection, and corresponding `apiKey`; do not assign the key to the wrong Provider node. |
| Arm gesture execution fails | Ensure the G1 is in a standing state (`balance_stand` or `squat2stand`) and nothing blocks the arm path. |
| `SwitchToUserCtrl` timeout | Confirm SDK version compatibility with G1 firmware; try power-cycling the G1 and reconnecting. |

## 11. Safety and Capability Boundaries

- `--host 0.0.0.0` listens on all host interfaces. Use only on trusted networks
  and restrict port `9030` with a firewall; use `--host 127.0.0.1` for local
  deployment.
- Do not expose raw SDK calls, disable safety limits, or enable extended
  continuous motion to the Agent.
- The G1 is a bipedal humanoid with limited balance capabilities. Do not use
  this integration for stairs, slopes, rough terrain, or unsupervised tasks.
- Arm preset gestures are fast actuation commands with large joint travel.
  Ensure adequate clearance around the arm path to avoid clamping or object
  damage.
- Preflight passing only indicates configuration and runtime contract
  compatibility; it does not constitute an official robot safety certification.
- When changing tasks, prefer `stop_move` first and verify from low speed and
  short duration incrementally.

## Related Documentation

- [Unitree G1 Integration Design](../../g1_integration_design.md)
- [PhyAgentOS User Manual](../zh/02-user-manual.md)
- [Runtime Configuration Reference](../zh/04-runtime-configuration-reference.md)
- [Communication Architecture](COMMUNICATION.md)
- [Unitree Go2 Quick Start Guide](UNITREE_GO2_QUICK_START.md)
