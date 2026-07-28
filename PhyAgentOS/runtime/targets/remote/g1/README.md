# Unitree G1 TargetWS

**Target**: `g1_real_builtin` · **Endpoint**: `targetws://127.0.0.1:9030`

This target exposes a constrained builtin-control surface for a Unitree G1
bipedal humanoid through the PhyAgentOS TargetWS protocol. It covers loco
posture switching, short low-speed velocity control, and 16 preset arm gestures.

---

## Network defaults

- Robot IP: `192.168.137.1`
- Host wired IP: `192.168.137.222`
- Host SDK interface: `enp4s0`
- TargetWS endpoint: `targetws://127.0.0.1:9030`

---

## Create the SDK environment

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

If `pip install -e .` reports missing CycloneDDS, build it first:

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

Verify the SDK:

```bash
conda run -n g1-sdk python - <<'PY'
from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
from unitree_sdk2py.g1.arm.g1_arm_action_client import G1ArmActionClient
print("g1-sdk import ok")
PY
```

---

## Start the TargetWS Server

Dry-run mode (no real robot communication):

```bash
conda run -n g1-sdk python PhyAgentOS/runtime/targets/remote/g1/server.py \
  --host 0.0.0.0 --port 9030 \
  --network-interface enp4s0 --robot-ip 192.168.137.1 \
  --dry-run
```

Real robot mode:

```bash
conda run -n g1-sdk python PhyAgentOS/runtime/targets/remote/g1/server.py \
  --host 0.0.0.0 --port 9030 \
  --network-interface enp4s0 --robot-ip 192.168.137.1
```

---

## Runtime Commands

The builtin skill runtime calls `execute_step` with one of these commands:

```yaml
execution:
  steps:
    - command: squat2stand
    - command: balance_stand
    - command: move
      params:
        vx: 0.8
        vy: 0.0
        vyaw: 0.0
        step: 1.0
    - command: high_wave     # arm gesture
    - command: stop_move
    - command: sit
```

**Loco posture commands**: `squat2stand`, `balance_stand`, `lie2stand`,
`stand2squat`, `sit`, `damp`, `zero_torque`, `stop_move`

**Velocity control**: `move` with `vx/vy/vyaw/step`

**Arm gestures** (must be in standing state):
`release_arm`, `two_hand_kiss`, `left_kiss`, `right_kiss`, `hands_up`,
`clap`, `high_five`, `hug`, `heart`, `right_heart`, `reject`, `right_hand_up`,
`x_ray`, `face_wave`, `high_wave`, `shake_hand`

**Velocity limits enforced by the server**:

| Parameter | Range |
|-----------|:-----:|
| `vx` | [-0.8, 0.8] m/s |
| `vy` | [-0.2, 0.2] m/s |
| `vyaw` | [-0.5, 0.5] rad/s |
| `step` | [0.1, 2.0] s |

---

## Safety Notes

- **G1 is bipedal** — balance is limited. Do not use for stairs, slopes, rough
  terrain, or unsupervised tasks.
- **Arm gestures are fast actuation** with large joint travel. Ensure clearance
  around the arms before execution.
- Never expose raw SDK calls to the agent.
- Test posture changes first, then short movement, before attempting arm gestures.
