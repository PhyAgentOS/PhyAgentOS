# Unitree G1 接入技术方案

## 概述

Unitree G1 双足人形机器人接入 PhyAgentOS，通过 `unitree_sdk2_python` 统一通信，采用与 Go2 完全一致的 TargetWS 架构。

**接入状态**：✅ 已完成（2026-07-28）

---

## 1. SDK 能力分析

### 1.1 unitree_sdk2py 中 G1 模块

```
unitree_sdk2py/g1/
├── loco/
│   ├── g1_loco_api.py        # API ID 定义
│   └── g1_loco_client.py     # LocoClient - 运动控制服务 (sport)
├── arm/
│   ├── g1_arm_action_api.py   # API ID 定义
│   └── g1_arm_action_client.py # G1ArmActionClient - 手臂动作服务 (arm)
└── audio/
    ├── g1_audio_api.py
    └── g1_audio_client.py      # AudioClient - 语音/LED (后续扩展)
```

### 1.2 Go2 vs G1 SDK 对比

| | Go2 | G1 |
|---|---|---|
| **SDK 类** | 单一 `SportClient`（sport 服务） | **两个独立 Client** |
| **Loco 控制** | `SportClient` | `LocoClient`（sport 服务） |
| **手臂/手势** | 无 | `G1ArmActionClient`（arm 服务） |
| **语音/LED** | 无 | `AudioClient`（voice 服务，后续扩展） |

---

## 2. 完整文件清单

### 2.1 核心运行时文件 (5个)

| 文件 | 行数 | 说明 |
|------|------|------|
| `PhyAgentOS/runtime/targets/remote/g1/__init__.py` | 1 | 模块入口 |
| `PhyAgentOS/runtime/targets/remote/g1/server.py` | 793 | TargetWS Server (核心) |
| `PhyAgentOS/runtime/targets/remote/g1/README.md` | 132 | 部署文档 |
| `PhyAgentOS/runtime/adapters/g1/__init__.py` | 1 | 模块入口 |
| `PhyAgentOS/runtime/adapters/g1/target_adapter.py` | 39 | G1BuiltinTargetAdapter |

### 2.2 配置文件 (5个)

| 文件 | 行数 | 说明 |
|------|------|------|
| `PhyAgentOS/templates/configs/runtime/contracts/g1_builtin.runtime.yaml` | 66 | 模板契约 |
| `workspaces/g1_real/configs/runtime/contracts/g1_builtin.runtime.yaml` | 76 | 工作区契约 |
| `workspaces/g1_real/TARGETS.md` | 48 | Target 注册 |
| `workspaces/g1_real/SKILLRUNTIME.md` | 24 | SkillRuntime 定义 |
| `workspaces/g1_real/EMBODIED.md` | 86 | 集成指南 |

### 2.3 文档 (4个)

| 文件 | 说明 |
|------|------|
| `docs/g1_integration_design.md` | 设计方案 |
| `docs/user_development_guide/UNITREE_G1_QUICK_START.md` | 中文快速上手 |
| `docs/user_development_guide/UNITREE_G1_QUICK_START_en.md` | 英文快速上手 |
| `examples/g1_driver_config.json` | 驱动配置示例 |

### 2.4 修改的文件 (2个)

| 文件 | 修改内容 |
|------|------|
| `PhyAgentOS/runtime/adapters/factory.py` | 第10行: import G1BuiltinTargetAdapter; 第83行: 注册 target_adapter |
| `PhyAgentOS/runtime/targets/factory.py` | 第17行: import G1RemoteTargetProxy; 第102行: 注册 G1RemoteTargetProxy |

---

## 3. server.py 架构

### 3.1 整体结构

```
PhyAgentOS/runtime/targets/remote/g1/server.py (793行)
│
├── class TargetProtocolError          # 协议错误 (第29行)
│
├── 工具函数
│   ├── packb() / unpackb()            # msgpack 编解码
│   ├── make_response()                # 构造 RPC 响应
│   ├── _safe_response()               # 安全序列化
│   ├── _float_param() / _clip()       # 参数裁剪
│   ├── _raise_for_sdk_error()         # SDK 错误检查
│   ├── _normalize_command()           # 命令归一化
│   ├── _normalize_arm_action()        # 手臂动作归一化
│   └── _clip_move_params()            # 移动参数裁剪
│
├── class G1LocoBackend                # Loco SDK 封装 (第58行)
│   ├── connect()  // SwitchToUserCtrl()
│   ├── squat2stand() / lie2stand()    # FSM 姿态切换
│   ├── balance_stand()                # 平衡站立
│   ├── stand2squat() / sit()          # 下蹲/坐下
│   ├── damp() / zero_torque()         # 阻尼/零扭矩
│   ├── stop_move()                    # 停止
│   ├── set_velocity()                 # 速度控制
│   └── move()                         # 分段移动
│
├── class G1ArmBackend                 # Arm SDK 封装 (第181行)
│   └── ACTION_MAP = {16个动作}
│   ├── connect()
│   └── execute_arm_action()           # 执行预设手势
│
├── class G1ArmActionRuntime           # 手臂动作运行层 (第286行)
│   ├── AGENT_TOOLS
│   ├── execute_step()                 # 执行手臂动作
│   └── describe_agent_tools()         # 描述工具
│
├── class G1BuiltinRuntime             # 主运行类 (第340行)
│   ├── AGENT_TOOLS                    # execute_step 工具定义
│   ├── ARM_COMMANDS                   # 16个手臂动作集合
│   ├── describe()
│   ├── configure_session() / start_session()
│   ├── reset() / observe()
│   ├── action_chunk() / execution_status()
│   ├── call_agent_tool() → _execute_step()  # 核心命令分发
│   ├── cancel() / close()
│   └── _execute_step()                # 命令路由器
│       ├── 8 Loco 姿势
│       ├── 1 Velocity Control (move)
│       └── 16 Arm Gestures
│
└── serve_blocking() / main()          # WebSocket 服务
```

### 3.2 关键常量

```python
DEFAULT_LIMITS = {
    "vx": (-0.8, 0.8),      # 前后速度 m/s
    "vy": (-0.2, 0.2),      # 横向速度 m/s
    "vyaw": (-0.5, 0.5),    # 偏航角速度 rad/s
}
SDK_OK = 0
```

### 3.3 安全机制

- **参数裁剪**：所有 move 参数自动裁剪到安全范围
- **SDK 错误检查**：非0错误码自动抛出 `TargetProtocolError`
- **dry-run 模式**：`--dry-run` 不连接真实机器人
- **Auto-stop**：move 命令结束自动调用 `stop_move()`

---

## 4. 命令集（27个）

### 4.1 Loco 姿势命令（8个）

| Command | 含义 | SDK 调用 |
|---------|------|----------|
| `squat2stand` | 蹲姿→站起 | `LocoClient.Squat2StandUp()` → `SetFsmId(706)` |
| `balance_stand` | 平衡站立 | `LocoClient.BalanceStand(mode)` → `SetBalanceMode()` |
| `lie2stand` | 躺姿→站起 | `LocoClient.Lie2StandUp()` → `SetFsmId(702)` |
| `stand2squat` | 站起→蹲下 | `LocoClient.StandUp2Squat()` → `SetFsmId(706)` |
| `sit` | 坐下 | `LocoClient.Sit()` → `SetFsmId(3)` |
| `damp` | 阻尼模式 | `LocoClient.Damp()` → `SetFsmId(1)` |
| `zero_torque` | 零扭矩安全模式 | `LocoClient.ZeroTorque()` → `SetFsmId(0)` |
| `stop_move` | 停止移动 | `LocoClient.StopMove()` → `SetVelocity(0,0,0)` |

### 4.2 速度控制命令（1个）

| Command | 参数 | 范围 | 说明 |
|---------|------|------|------|
| `move` | `vx`, `vy`, `vyaw`, `step` | `[0.1, 2.0]` s | 分段速度控制，结束后自动 stop |

### 4.3 手臂预设手势命令（16个）

| Command | Action ID | 说明 |
|---------|-----------|------|
| `release_arm` | 99 | 释放手臂到初始位置 |
| `two_hand_kiss` | 11 | 双手贴面 |
| `left_kiss` | 12 | 左脸贴面 |
| `right_kiss` | 13 | 右脸贴面 |
| `hands_up` | 15 | 举手 |
| `clap` | 17 | 鼓掌 |
| `high_five` | 18 | 击掌 |
| `hug` | 19 | 拥抱 |
| `heart` | 20 | 比心 |
| `right_heart` | 21 | 右手比心 |
| `reject` | 22 | 拒绝 |
| `right_hand_up` | 23 | 右手举起 |
| `x_ray` | 24 | X射线 |
| `face_wave` | 25 | 脸部挥手 |
| `high_wave` | 26 | 高处挥手 |
| `shake_hand` | 27 | 握手 |

### 4.4 中文别名映射

```python
{
    # 坐姿
    "sit down": "sit", "蹲下": "sit", "坐下": "sit", "squat": "sit",
    # 站起
    "squat2stand": "squat2stand", "squat to stand": "squat2stand",
    "蹲起": "squat2stand", "lie2stand": "lie2stand",
    # 停止
    "stop": "stop_move", "停止": "stop_move",
    # 阻尼
    "damp": "damp", "阻尼": "damp",
    # 手臂动作
    # 每个 ARM_COMMANDS 都支持空格替换下划线
}
```

---

## 5. 注册方式（Go2 风格）

### 5.1 Remote Target 注册（factory.py）

**不创建独立的 proxy.py**，直接复用 Go2 的工厂函数：

```python
# PhyAgentOS/runtime/targets/factory.py

from PhyAgentOS.runtime.targets.remote.scout.proxy import ScoutRemoteTargetProxy
from PhyAgentOS.runtime.targets.remote.proxy import RemoteTargetProxy

def build_go2_remote_target_proxy(target: TargetSpec, client: TargetWSClient) -> RemoteTargetProxy:
    return RemoteTargetProxy(client, config=target.config)

# G1 复用 Go2 的工厂函数（不创建 G1RemoteTargetProxy 类）
register_remote_target_runtime("Go2RemoteTargetProxy", build_go2_remote_target_proxy)
register_remote_target_runtime("G1RemoteTargetProxy", build_go2_remote_target_proxy)
```

### 5.2 Target Adapter 注册（adapters/factory.py）

```python
# PhyAgentOS/runtime/adapters/factory.py

from PhyAgentOS.runtime.adapters.g1.target_adapter import G1BuiltinTargetAdapter

register_target_adapter("target_adapter://g1_builtin_adapter", G1BuiltinTargetAdapter)
```

---

## 6. 配置文件详情

### 6.1 TARGETS.md（workspaces/g1_real/TARGETS.md）

```yaml
version: runtime_target_registry_v1
targets:
  - id: g1_real_builtin
    target_class: remote
    target_kind: real_robot
    embodiment: unitree_g1
    enabled: true
    workspace: workspaces/g1_real
    supported_skillruntimes:
      - g1_builtin_command
    runtime:
      target_runtime: G1RemoteTargetProxy              # ← Go2 模式
      target_endpoint: targetws://127.0.0.1:9030       # G1 端口
      target_adapter: target_adapter://g1_builtin_adapter
      runtime_contract_ref: configs/runtime/contracts/g1_builtin.runtime.yaml
    config:
      robot_ip: 192.168.137.1
      host_ip: 192.168.137.222
      network_interface: enp4s0
      safety_limits:
        vx: [-0.5, 0.5]
        vy: [-0.2, 0.2]
        vyaw: [-0.5, 0.5]
        duration_s: [0.1, 1.0]
```

### 6.2 Runtime Contract（g1_builtin.runtime.yaml）

```yaml
version: runtime_target_contract_v1
target_id: g1_real_builtin
target_adapter: target_adapter://g1_builtin_adapter

observation:
  schema_source: empty
  require_describe_observation_schema: false

action_contract:
  id: g1_builtin_command_v1
  accepted_representations: [builtin_command]
  shape: [1, 1]
  dtype: object
  control_mode: builtin_loco_api
  control_hz: 10

safety:
  max_linear_velocity_mps: 0.8        # G1 比 Go2 快（0.8 vs 0.5）
  max_angular_velocity_radps: 0.5
  stop_on_nan: true
  stop_on_timeout: true

capabilities:
  agent_tools:
    - execute_step                     # 核心命令
    - execute_arm_action               # 手臂动作
  supported_commands:                  # 完整的 27 个命令
    - squat2stand, balance_stand, lie2stand, stand2squat, sit, damp, zero_torque, stop_move
    - move
    - release_arm, two_hand_kiss, left_kiss, right_kiss, hands_up, clap, high_five, hug, heart, right_heart, reject, right_hand_up, x_ray, face_wave, high_wave, shake_hand
```

### 6.3 SKILLRUNTIME.md（workspaces/g1_real/SKILLRUNTIME.md）

```yaml
version: runtime_skill_registry_v1
skillruntimes:
  - id: g1_builtin_command
    runtime: CommandSimSkillRuntime
    runtime_kind: builtin
    loop_mode: builtin_command_loop
    agent_exposure: constrained_target_tools
    supported_target_kinds:
      - real_robot
    observation_contract:
      observation_type: empty
      empty_observation_allowed: true
    target_tool_policy:
      expose:
        - execute_step
        - execute_arm_action
      forbidden:
        - raw_sdk_command
    supports_chunk: false
    default_replan_every: 1
```

---

## 7. TargetAdapter（G1BuiltinTargetAdapter）

```python
# PhyAgentOS/runtime/adapters/g1/target_adapter.py

class G1BuiltinTargetAdapter(BaseTargetAdapter):
    """G1 builtin sessions use constrained target tools, not action chunks."""

    def output_observation_contract(self) -> dict[str, Any]:
        return {
            "observation_type": "empty",
            "semantics": "G1 builtin command sessions do not require observation data.",
        }

    def input_action_contract(self) -> dict[str, Any]:
        return {
            "tools": ["execute_step", "execute_arm_action"],  # 两个工具
            "action_chunks": "not_supported",
        }

    def to_runtime_observation(self, raw_obs, target_info):
        return {
            "observation_id": raw_obs.get("observation_id", "g1_empty_obs"),
            "target_info": target_info,
            "g1": raw_obs.get("g1", {}),
        }

    def to_executable_action_chunk(self, action_chunk, target_info):
        raise AdapterError("G1 builtin target does not accept action chunks; use execute_step")
```

---

## 8. 运行环境配置

### 8.1 网络配置

| 项目 | 值 |
|------|-----|
| Robot IP | `192.168.137.1` |
| 主机有线 IP | `192.168.137.222` |
| SDK 网卡 | `enp4s0`（以实际为准） |
| TargetWS 端口 | `9030` |
| TargetWS Endpoint | `targetws://127.0.0.1:9030` |

### 8.2 SDK 环境

```bash
# 1. 创建 conda 环境（独立于 paos）
conda create -n g1-sdk python=3.10 -y
conda activate g1-sdk

# 2. 安装依赖
pip install "cyclonedds==0.10.2" numpy opencv-python websockets msgpack

# 3. 安装 Unitree SDK2
cd ~
git clone https://github.com/unitreerobotics/unitree_sdk2_python.git
cd unitree_sdk2_python
pip install -e .

# 4. 验证
conda run -n g1-sdk python -c "
from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
from unitree_sdk2py.g1.arm.g1_arm_action_client import G1ArmActionClient
print('g1-sdk import ok')
"
```

### 8.3 启动 Server

```bash
# Dry-run 模式（不连接机器人）
conda run -n g1-sdk python PhyAgentOS/runtime/targets/remote/g1/server.py \
  --host 0.0.0.0 --port 9030 \
  --network-interface enp4s0 --robot-ip 192.168.137.1 \
  --dry-run

# 真机模式
conda run -n g1-sdk python PhyAgentOS/runtime/targets/remote/g1/server.py \
  --host 0.0.0.0 --port 9030 \
  --network-interface enp4s0 --robot-ip 192.168.137.1
```

---

## 9. Go2 vs G1 对比

| 维度 | Go2 | G1 |
|------|-----|-----|
| **SDK 后端** | `Go2SportBackend`（单 Client） | `G1LocoBackend` + `G1ArmBackend`（双 Client） |
| **运行层** | `Go2BuiltinRuntime` | `G1BuiltinRuntime` + `G1ArmActionRuntime` |
| **命令数** | 8 个 | **27 个** |
| **Adapter 工具** | `execute_step`（1个） | `execute_step` + `execute_arm_action`（2个） |
| **Proxy 类** | 无（复用 RemoteTargetProxy） | **无，复用 Go2 工厂函数** |
| **安全限制** | vx[-0.5, 0.5] m/s | vx[-0.8, 0.8] m/s（G1 更快） |
| **端口** | 9010 | **9030** |
| **环境名** | `go2-sdk` | **`g1-sdk`** |

---

## 10. 安全与能力边界

### 10.1 安全限制

```
vx（前后速度）：     [-0.8,  0.8] m/s
vy（左右速度）：     [-0.2,  0.2] m/s
vyaw（旋转速度）：   [-0.5,  0.5] rad/s
duration_s（时长）： [0.1,   2.0] s
```

### 10.2 能力边界

- **不允许**：楼梯、斜坡、复杂地形、长时间自主移动
- **不允许**：暴露在开放环境的无人监护任务
- **手臂手势**：执行时确保手臂路径有充足空间，防止夹伤或碰伤
- **Preflight**：通过只表示配置兼容，不代表完成真机安全认证

---

## 11. 部署检查清单

- [ ] ✅ `PhyAgentOS/runtime/targets/remote/g1/server.py`（793行）
- [ ] ✅ `PhyAgentOS/runtime/targets/remote/g1/__init__.py`
- [ ] ✅ `PhyAgentOS/runtime/targets/remote/g1/README.md`
- [ ] ✅ `PhyAgentOS/runtime/adapters/g1/target_adapter.py`
- [ ] ✅ `PhyAgentOS/runtime/adapters/factory.py` 注册 `g1_builtin_adapter`
- [ ] ✅ `PhyAgentOS/runtime/targets/factory.py` 注册 `G1RemoteTargetProxy`
- [ ] ✅ `workspaces/g1_real/TARGETS.md`（target: g1_real_builtin）
- [ ] ✅ `workspaces/g1_real/SKILLRUNTIME.md`
- [ ] ✅ `workspaces/g1_real/EMBODIED.md`
- [ ] ✅ `PhyAgentOS/templates/configs/runtime/contracts/g1_builtin.runtime.yaml`
- [ ] ✅ `docs/g1_integration_design.md`
- [ ] ✅ `docs/user_development_guide/UNITREE_G1_QUICK_START.md`
- [ ] ✅ `docs/user_development_guide/UNITREE_G1_QUICK_START_en.md`

---

**文档版本**: v1.0  
**最后更新**: 2026-07-28  
**适用分支**: `preview`  
**适用机器人**: Unitree G1 (双足人形)  
**参考文档**: `UNITREE_G1_QUICK_START.md`（用户指南）
