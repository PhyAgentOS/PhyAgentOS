# Unitree Go2 TargetWS

This target exposes a small, constrained builtin-control surface for a Unitree
Go2 through the PhyAgentOS TargetWS protocol. It is intended for posture changes
and short low-speed movement only.

## Network

Default local setup:

- Robot IP: `192.168.123.161`
- Host wired IP: `192.168.123.222`
- Host SDK interface: `enp4s0`
- TargetWS endpoint: `targetws://127.0.0.1:9010`

The `paos` environment does not need Unitree SDK2. Run this server from a
separate SDK environment and let PhyAgentOS connect over TargetWS.

## Create The SDK Environment

```bash
conda create -n go2-sdk python=3.10 -y
conda activate go2-sdk
python -m pip install -U pip setuptools wheel
```

Install the Unitree SDK2 Python dependencies and the TargetWS server
dependencies:

```bash
pip install "cyclonedds==0.10.2" numpy opencv-python websockets msgpack
```

Install Unitree SDK2 Python from source:

```bash
cd ~
git clone https://github.com/unitreerobotics/unitree_sdk2_python.git
cd unitree_sdk2_python
pip install -e .
```

If `pip install -e .` reports that CycloneDDS cannot be located, build
CycloneDDS and export `CYCLONEDDS_HOME` before reinstalling the SDK:

```bash
cd ..
git clone https://github.com/eclipse-cyclonedds/cyclonedds -b releases/0.10.x
cd cyclonedds
mkdir build install
cd build
cmake .. -DCMAKE_INSTALL_PREFIX=../install
cmake --build . --target install

cd ~/unitree_sdk2_python
export CYCLONEDDS_HOME=~/cyclonedds/install
pip install -e .
```

## Verify The SDK

Check imports:

```bash
conda run -n go2-sdk python - <<'PY'
from unitree_sdk2py.go2.sport.sport_client import SportClient
import cyclonedds
print("go2-sdk import ok")
PY
```

## Start The TargetWS Server

Dry-run mode does not import or command the Unitree SDK. Use it to test
PhyAgentOS runtime plumbing:

```bash
conda run -n go2-sdk python PhyAgentOS/PhyAgentOS/runtime/targets/remote/go2/server.py \
  --host 0.0.0.0 \
  --port 9010 \
  --network-interface enp4s0 \
  --robot-ip 192.168.123.161 \
  --dry-run
```

Real robot mode:

```bash
conda run -n go2-sdk python PhyAgentOS/PhyAgentOS/runtime/targets/remote/go2/server.py \
  --host 0.0.0.0 \
  --port 9010 \
  --network-interface enp4s0 \
  --robot-ip 192.168.123.161
```

## Runtime Commands

The builtin skill runtime calls `execute_step` with one of these commands:

```yaml
execution:
  steps:
    - command: stand_up
    - command: balance_stand
    - command: move
      params:
        vx: 0.5
        vy: 0.0
        vyaw: 0.0
        duration_s: 1.0
    - command: stop
    - command: stand_down
```

Allowed commands:

- `stand_up`
- `balance_stand`
- `recovery_stand`
- `stand_down` / `squat`
- `damp`
- `stop`
- `move`

Move limits enforced by the server:

- `vx`: `[-0.5, 0.5]`
- `vy`: `[-0.2, 0.2]`
- `vyaw`: `[-0.5, 0.5]`
- `duration_s`: `[0.1, 1.0]`

Every `move` command ends by calling `StopMove()`.

## Safety Notes

- Test with the robot on a clear floor and the operator nearby.
- Start with `stand_up`, `balance_stand`, `stop`, and `stand_down` before trying movement.
- Use short movement tests first, for example `vx=0.5` and `duration_s=1.0`.
- Do not expose raw SDK calls to the agent.
- Do not use this target for navigation, visual servoing, or long autonomous
  movement. This v1 target is deliberately a small builtin command surface.
