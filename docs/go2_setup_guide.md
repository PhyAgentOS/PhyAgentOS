# Go2 机器人接入 PhyAgentOS 完整指南

> 本文档面向**零经验用户**，从零开始一步步完成 Unitree Go2 机器人与 PhyAgentOS 的接入。  
> 预计耗时：1-2 小时（取决于网络配置）。

---

## 目录

1. [整体架构概览](#1-整体架构概览)
2. [准备工作](#2-准备工作)
3. [网络配置](#3-网络配置)
4. [安装 SDK 环境](#4-安装-sdk-环境)
5. [验证 SDK 安装](#5-验证-sdk-安装)
6. [启动 TargetWS 服务](#6-启动-targetws-服务)
7. [配置 PhyAgentOS Target](#7-配置-phyagentos-target)
8. [启动运行时并测试](#8-启动运行时并测试)
   - [8.1 配置 LLM Provider](#81-配置-llm-provider自然语言控制必备)
   - [8.2 确保 TargetWS 服务正在运行](#82-确保-targetws-服务正在运行)
   - [8.3 启动 PhyAgentOS 运行时](#83-启动-phyagentos-运行时)
   - [8.4 执行测试步骤（手动命令模式）](#84-执行测试步骤手动命令模式)
   - [8.5 自然语言控制 Go2（推荐方式）](#85-自然语言控制-go2推荐方式)
   - [8.6 通过 Agent 工具调用](#86-通过-agent-工具调用)
9. [常用命令速查](#9-常用命令速查)
10. [常见问题排查](#10-常见问题排查)
    - [Q1: ping 不通](#q1-ping-192168123161-不通)
    - [Q2: ModuleNotFoundError](#q2-modulenotfounderror-no-module-named-unitree_sdk2py)
    - [Q3: ConnectionRefusedError](#q3-connectionrefusederror-或-connection-timed-out)
    - [Q4: CycloneDDS 安装失败](#q4-sdk-报错-cyclonedds-cannot-be-located)
    - [Q5: 机器人不站起](#q5-机器人不站起)
    - [Q6: SDK 错误码](#q6-go2-sdk-command-move-returned-error-code-x)
    - [Q7: 运行时连接失败](#q7-phyagentos-运行时连接失败)
    - [Q8: 机器人移动异常](#q8-机器人移动异常或不受控)
    - [Q9: 自然语言控制不工作](#q9-自然语言控制不工作)
11. [安全须知](#11-安全须知)

---

## 附录

- [A: Dry-Run 演示脚本](#附录-adry-run-演示脚本) — 无需真机的完整演示
- [B: 完整部署脚本](#附录-b完整部署脚本) — 一键环境检查和启动
- [C: 文件清单](#附录-c文件清单) — 关键文件索引
- [D: 术语表](#附录-d术语表) — 专业术语解释
- [E: 故障排查流程图](#附录-e故障排查流程图) — 快速定位问题

---

## 1. 整体架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                   PhyAgentOS Runtime                        │
│              (AI 智能体 / 策略网络)                          │
└──────────────────┬──────────────────────────────────────────┘
                   │  targetws://127.0.0.1:9010
                   │  (WebSocket + msgpack)
                   ▼
┌─────────────────────────────────────────────────────────────┐
│            Go2 TargetWS Server (server.py)                  │
│         运行在 go2-sdk conda 环境中                           │
└──────────────────┬──────────────────────────────────────────┘
                   │  CycloneDDS (UDP/DDS 协议)
                   │  网络接口: enp4s0
                   ▼
┌─────────────────────────────────────────────────────────────┐
│         Unitree SDK2 SportClient (Python)                   │
└──────────────────┬──────────────────────────────────────────┘
                   │  UDP 数据报
                   │  IP: 192.168.123.161
                   ▼
┌─────────────────────────────────────────────────────────────┐
│                    Go2 本体机器狗                            │
│            (Unitree Go2 Quadruped Robot)                    │
└─────────────────────────────────────────────────────────────┘
```

**核心设计思想**：
- **隔离环境**：Go2 控制代码运行在独立的 `go2-sdk` conda 环境中，不影响 PhyAgentOS 主环境
- **服务代理**：通过 TargetWS 协议（WebSocket）将机器人控制暴露为标准化接口
- **安全约束**：仅暴露受约束的 `execute_step` 工具，禁止直接调用原始 SDK

---

## 2. 准备工作

### 2.1 硬件清单

| 物品 | 数量 | 备注 |
|------|------|------|
| Unitree Go2 机器人 | 1 | 确保已充电 |
| 以太网网线 | 1 | 用于连接电脑和机器人 |
| 运行 PhyAgentOS 的电脑 | 1 | Linux 系统 |

### 2.2 软件要求

- **操作系统**：Ubuntu Linux (推荐 20.04 或 22.04)
- **Python**：3.10
- **Conda**：已安装 Miniconda 或 Anaconda
- **Git**：已安装
- **PhyAgentOS**：已在主环境中克隆并配置

### 2.3 确认你的网络接口名称

打开终端，运行：

```bash
ip addr show
```

找到你的**有线网卡**名称，通常是以下之一：
- `enp4s0`（最常见的桌面主机）
- `eth0`（服务器常见）
- `enp3s0` 等

> **记录下来**，后续配置需要用到。本文档默认使用 `enp4s0`。

---

## 3. 网络配置

### 3.1 物理连接

1. 用**以太网网线**将电脑的有线网口与 Go2 机器人连接
2. 打开 Go2 电源开关（在机身底部或侧面）
3. 等待约 30 秒，机器人会启动并广播自己的 IP

### 3.2 确认机器人 IP

Go2 默认 IP 为 `192.168.123.161`。在电脑上 ping 测试：

```bash
ping -c 3 192.168.123.161
```

如果看到类似以下输出，说明网络连接正常：
```
64 bytes from 192.168.123.161: icmp_seq=1 ttl=64 time=1.23 ms
64 bytes from 192.168.123.161: icmp_seq=2 ttl=64 time=0.98 ms
```

**如果 ping 不通**，请检查：
- 网线是否插好
- 是否连接到了**有线网卡**（不是 WiFi）
- 电脑的有线 IP 是否需要手动设置（见下方）

### 3.3 配置电脑的有线 IP（如需）

Go2 使用 `192.168.123.x` 网段。你需要将电脑有线网口的 IP 设置为**同一网段的另一个地址**，例如：

```bash
# 假设你的有线网卡是 enp4s0
sudo ip addr add 192.168.123.222/24 dev enp4s0
sudo ip link set enp4s0 up
```

> **永久配置方法**取决于你的发行版：
> - **Ubuntu (Netplan)**: 编辑 `/etc/netplan/01-netcfg.yaml`
> - **CentOS/RHEL**: 编辑 `/etc/sysconfig/network-scripts/ifcfg-<接口名>`
>
> 推荐使用**静态 IP**，避免每次重启后重新配置。

### 3.4 再次测试连接

```bash
ping -c 3 192.168.123.161
```

确认能 ping 通后再继续下一步。

---

## 4. 安装 SDK 环境

### 4.1 创建 conda 环境

Go2 的 SDK 与 PhyAgentOS 的主环境**完全隔离**，避免依赖冲突。

```bash
# 创建独立的 conda 环境
conda create -n go2-sdk python=3.10 -y
conda create -n go2-sdk python=3.10 -c conda-forge --override-channels -y

# 激活环境
conda activate go2-sdk
```

### 4.2 升级 pip

```bash
python -m pip install -U pip setuptools wheel
```

### 4.3 安装基础依赖

```bash
pip install "cyclonedds==0.10.2" numpy opencv-python websockets msgpack
```

> **说明**：
> - `cyclonedds==0.10.2`：Unitree SDK2 使用的 DDS（数据分发服务）中间件
> - `msgpack` 和 `websockets`：TargetWS 协议所需的通信库
> - `numpy` 和 `opencv-python`：机器人数据处理

### 4.4 安装 Unitree SDK2 Python

从源码安装（这是获取最新 SDK 的唯一方式）：

```bash
# 进入你的工作目录（可以换成任意位置）
cd /home/$(whoami)

# 克隆 Unitree SDK2 Python
git clone https://github.com/unitreerobotics/unitree_sdk2_python.git
cd unitree_sdk2_python

# 以 editable 模式安装
pip install -e .
```

### 4.5 处理 SDK 安装失败的情况

**如果** `pip install -e .` 报错说找不到 CycloneDDS，则需要手动编译 CycloneDDS：

```bash
# 回到工作目录
cd /home/$(whoami)

# 克隆 CycloneDDS（0.10.x 分支，与 SDK 兼容）
git clone https://github.com/eclipse-cyclonedds/cyclonedds -b releases/0.10.x
cd cyclonedds

# 编译安装
mkdir build install
cd build
cmake .. -DCMAKE_INSTALL_PREFIX=../install
cmake --build . --target install

# 重新安装 Unitree SDK2
cd /home/$(whoami)/unitree_sdk2_python

# 设置环境变量，告诉 SDK 去哪里找 CycloneDDS
export CYCLONEDDS_HOME=/home/$(whoami)/cyclonedds/install

# 重新安装
pip install -e .
```

> **提示**：如果你在执行上述命令时遇到 `cmake: command not found`，需要先安装编译工具：
> ```bash
> sudo apt update
> sudo apt install -y cmake build-essential
> ```

---

## 5. 验证 SDK 安装

在 `go2-sdk` 环境中运行以下命令：

```bash
conda run -n go2-sdk python - <<'PY'
from unitree_sdk2py.go2.sport.sport_client import SportClient
import cyclonedds
print("Go2 SDK 导入成功 ✓")
PY
```

**预期输出**：
```
Go2 SDK 导入成功 ✓
```

**如果报错**，请检查：
1. 是否在执行 `conda activate go2-sdk` 后运行的？
2. `cyclonedds` 是否正确安装？运行 `pip show cyclonedds` 确认
3. 如果提示找不到 CycloneDDS 共享库，设置环境变量：
   ```bash
   export LD_LIBRARY_PATH=/home/$(whoami)/cyclonedds/install/lib:$LD_LIBRARY_PATH
   ```

---

## 6. 启动 TargetWS 服务

### 6.1 首次启动（推荐 Dry-Run 模式）

**Dry-Run 模式**不会连接真实机器人，仅测试 PhyAgentOS 与 TargetWS 之间的通信管道是否正常。

```bash
conda run -n go2-sdk python /home/$(whoami)/git/PhyAgentOS/PhyAgentOS/runtime/targets/remote/go2/server.py \
  --host 0.0.0.0 \
  --port 9010 \
  --network-interface enp4s0 \
  --robot-ip 192.168.123.161 \
  --dry-run
```

**参数说明**：

| 参数 | 值 | 说明 |
|------|-----|------|
| `--host` | `0.0.0.0` | 监听所有网卡（允许本地连接） |
| `--port` | `9010` | TargetWS 服务端口 |
| `--network-interface` | `enp4s0` | **改成你第 2.3 步查到的网卡名** |
| `--robot-ip` | `192.168.123.161` | Go2 机器人的 IP |
| `--dry-run` | （有） | 不连接真实机器人，仅模拟 |

**预期输出**：
```
Go2 TargetWS server listening on targetws://0.0.0.0:9010
Go2 TargetWS client connected: ('127.0.0.1', xxxxx)
```

**测试方法**：打开另一个终端，运行：
```bash
python -c "
import asyncio
import websockets

async def test():
    async with websockets.connect('ws://127.0.0.1:9010') as ws:
        await ws.send(b'test')
        response = await ws.recv()
        print('TargetWS 连接正常 ✓')

asyncio.run(test())
"
```

### 6.2 正式模式（连接真实机器人）

确认 Dry-Run 正常后，**关闭 Dry-Run 服务**（Ctrl+C），然后启动真实模式：

```bash
conda run -n go2-sdk python /home/$(whoami)/git/PhyAgentOS/PhyAgentOS/runtime/targets/remote/go2/server.py \
  --host 0.0.0.0 \
  --port 9010 \
  --network-interface enp4s0 \
  --robot-ip 192.168.123.161
```

> **重要**：这个服务**必须始终保持运行**，PhyAgentOS 会通过它控制机器人。

**预期输出**：
```
Go2 TargetWS server listening on targetws://0.0.0.0:9010
```

如果机器人连接成功，会在日志中看到类似：
```
INFO ... Go2 SDK call StandUp args=() response=0
```

> **如果报错**：
> - `Connection refused`：检查网线是否插好、机器人是否开机
> - `ModuleNotFoundError`：确认你在 `go2-sdk` 环境中运行
> - `Timeout`：检查机器人 IP 是否正确（`ping 192.168.123.161`）

---

## 7. 配置 PhyAgentOS Target

### 7.1 启用 Go2 Target

编辑 `PhyAgentOS/templates/TARGETS.md` 文件，找到 `go2_real_builtin` 部分，将 `enabled: false` 改为 `enabled: true`：

```yaml
- id: go2_real_builtin
  target_class: remote
  target_kind: real_robot
  embodiment: unitree_go2
  enabled: true                    # ← 改为 true
  workspace: workspaces/go2_real
  ...
```

### 7.2 确认网络配置

在同一文件的 `config` 部分，确认以下配置与你的实际环境一致：

```yaml
    config:
      robot_ip: 192.168.123.161      # Go2 机器人 IP
      host_ip: 192.168.123.222       # 电脑有线 IP
      network_interface: enp4s0      # 你的有线网卡名
```

### 7.3 确认 Target 定义

确保 `TARGETS.md` 中包含以下内容（如果不存在则添加）：

```yaml
- id: go2_real_builtin
  target_class: remote
  target_kind: real_robot
  embodiment: unitree_go2
  enabled: false                    # 使用时改为 true
  workspace: workspaces/go2_real
  supported_skillruntimes:
    - go2_builtin_command
  runtime:
    target_runtime: Go2RemoteTargetProxy
    target_endpoint: targetws://127.0.0.1:9010
    target_adapter: target_adapter://go2_builtin_adapter
    runtime_contract_ref: configs/runtime/contracts/go2_builtin.runtime.yaml
  observation:
    observation_type: empty
    empty_observation_allowed: true
    empty_observation_semantics: Go2 builtin command sessions do not require observation data.
  perception:
    enabled: false
    strict_preflight: true
    sensor_config_ref: null
    perception_config_ref: null
    artifact_dir: null
  config:
    robot_ip: 192.168.123.161
    host_ip: 192.168.123.222
    network_interface: enp4s0
    action_dim: 1
    max_chunk_size: 1
    control_hz: 10
    safety_limits:
      vx: [-0.5, 0.5]
      vy: [-0.2, 0.2]
      vyaw: [-0.5, 0.5]
      duration_s: [0.1, 1.0]
```

### 7.4 确认 SkillRuntime 定义

确保 `PhyAgentOS/templates/SKILLRUNTIME.md` 中包含：

```yaml
- id: go2_builtin_command
  runtime: CommandSimSkillRuntime
  runtime_kind: builtin
  loop_mode: builtin_command_loop
  agent_exposure: constrained_target_tools
  supported_target_kinds:
    - real_robot
```

---

## 8. 启动运行时并测试

> **前置条件**：启动 PhyAgentOS 之前，请确保 TargetWS 服务已在后台运行（见 [第 6 步](#6-启动-targetws-服务)）。

### 8.1 配置 LLM Provider（自然语言控制必备）

如果你希望通过**自然语言**与 Go2 交互（见 [第 8.5 节](#85-自然语言控制-go2)），需要配置 LLM 模型。

查看 `PhyAgentOS/` 下的配置文件（如 `configs/` 目录），或使用环境变量指定模型：

```bash
# 使用 OpenAI 模型
export OPENAI_API_KEY="your-api-key"
export OPENAI_MODEL="gpt-4o"  # 或 gpt-3.5-turbo

# 使用通义千问
export DASHSCOPE_API_KEY="your-dashscope-key"

# 或使用其他 LiteLLM 支持的模型
# 见 PhyAgentOS/PhyAgentOS/providers/litellm_provider.py
```

> **推荐模型**：GPT-4o、Claude、通义千问 2.5+。模型需要能理解结构化命令（YAML）并遵循工具调用约束。

### 8.2 确保 TargetWS 服务正在运行

在**第一个终端**中，确认 TargetWS 服务正在运行：

```bash
# 检查进程
conda run -n go2-sdk pgrep -a python

# 或在另一个终端测试连接
nc -zv localhost 9010
```

如果服务未运行，回到 [第 6 步](#6-启动-targetws-服务) 启动。

### 8.3 启动 PhyAgentOS 运行时

在 PhyAgentOS 主环境中，启动运行时并连接 Go2 Target：

```bash
# 进入 PhyAgentOS 目录
cd /home/$(whoami)/git/PhyAgentOS

# 启动运行时（具体命令取决于你的使用方式）
# 方式 1：通过 Python API
python -c "
from PhyAgentOS.runtime import Runtime
rt = Runtime()
rt.load_targets()
rt.load_skillruntimes()
# 启动 Go2 会话
session = rt.create_session(
    target_id='go2_real_builtin',
    skillruntime_id='go2_builtin_command',
    execution={
        'steps': [
            {'command': 'stand_up'}
        ]
    }
)
session.run()
"

# 方式 2：通过配置文件启动（如有）
# python scripts/run.py --config configs/go2_test.yaml
```

### 8.4 执行测试步骤（手动命令模式）

> **适用场景**：直接通过结构化 YAML 命令控制机器人，不经过 LLM。

**推荐测试顺序**（⚠️ 严格按此顺序，确保安全）：

#### 测试 1：站起

```yaml
execution:
  steps:
    - command: stand_up
```

**预期结果**：机器人从趴下状态缓慢站起，四足稳固支撑身体。

> **如果机器人不站起**：检查是否在地面上（需要平坦坚硬的地面），尝试 `recovery_stand`。

#### 测试 2：平衡站立

```yaml
execution:
  steps:
    - command: balance_stand
```

**预期结果**：机器人进入主动平衡模式，能轻微抵抗外力。

#### 测试 3：停止并趴下

```yaml
execution:
  steps:
    - command: stop
    - command: stand_down
```

**预期结果**：机器人原地停止运动，然后缓慢趴下。

#### 测试 4：短距离移动（⚠️ 确保周围空间足够）

```yaml
execution:
  steps:
    - command: stand_up
    - command: balance_stand
    - command: move
      params:
        vx: 0.3           # 前进速度 (m/s)，范围 [-0.5, 0.5]
        vy: 0.0           # 侧向速度 (m/s)，范围 [-0.2, 0.2]
        vyaw: 0.0         # 旋转速度 (rad/s)，范围 [-0.5, 0.5]
        duration_s: 1.0   # 移动时长 (秒)，范围 [0.1, 1.0]
    - command: stop
    - command: stand_down
```

**预期结果**：机器人向前慢速移动约 1 米后自动停止。

> **速度字段说明**：
> - `vx`：前后方向（正=前进，负=后退）
> - `vy`：左右方向（正=向左，负=向右）
> - `vyaw`：绕轴旋转（正=逆时针，负=顺时针）

#### 测试 5：阻尼模式（感受机器人重量）

```yaml
execution:
  steps:
    - command: damp
```

**预期结果**：机器人关节释放阻尼，你可以手动推动它的身体（用于调试）。

### 8.5 自然语言控制 Go2（推荐方式）

> **这是最直观的控制方式**：像和人说话一样控制机器人，LLM Agent 自动将你的自然语言翻译成结构化命令。

#### 8.5.1 控制链路

```
你说: "让Go2站起来向前走一步然后趴下"
    ↓
paos CLI 接收你的输入（交互式对话 / 单次命令）
    ↓
AgentLoop 的 LLM 理解意图
    ↓
LLM 参考 EMBODIED.md（Go2 能力描述）+ TARGETS.md（目标配置）
    ↓
LLM 输出结构化 YAML → 写入 SESSIONS.md
execution:
  steps:
    - command: stand_up
    - command: balance_stand
    - command: move
      params: {vx: 0.3, vy: 0.0, vyaw: 0.0, duration_s: 0.5}
    - command: stop
    - command: stand_down
    ↓
Watchdog 后台调度 → CommandSimSkillRuntime → execute_step
    ↓
Go2 TargetWS Server → Unitree SDK → 机器狗执行
    ↓
执行结果反馈给 LLM → LLM 回复你
"Go2 已经站起来了，向前移动了半步，然后趴下了。"
```

#### 8.5.2 使用方式

**方式 1：单次命令**

```bash
# 输入一句话，执行完自动退出
paos run "让Go2站起来向前走一步然后趴下"
```

**方式 2：交互式多轮对话**（推荐）

```bash
# 进入交互式 REPL
paos
```

进入后像聊天一样对话：

```
> 让Go2站起来

[Agent 正在执行...]
✓ 已发送: Go2 正在站起...

> 好的，现在让它向前走两步

[Agent 正在翻译并执行...]
✓ 已发送: 向前移动 0.5 秒后停止

> 停下来

[Agent 正在执行...]
✓ 已发送: 发送停止命令

> 好了，趴下吧

[Agent 正在执行...]
✓ 已发送: Go2 正在趴下...
```

> **提示**：在交互模式中，你可以随时打断、追加指令或修改动作，Agent 会动态调整执行计划。

#### 8.5.3 中英文输入示例

Agent 完全支持中英文混合输入，LLM 会自动解析：

```
# 中文输入
> 让Go2站起来，平衡站立，然后向前走一步再回来，最后趴下

# 英文输入
> Make Go2 stand up, move forward for 1 second, turn left, then stop and lie down

# 混合输入（同样支持）
> 先 stand_up，然后 move 0.5m 向前，最后 stand_down

# 自然描述（LLM 会自行拆解为具体命令）
> Go2 在原地转个圈，然后朝我走两步
```

#### 8.5.4 中文命令映射（内置）

`server.py` 的 `_normalize_command` 函数已内置中英文别名映射：

| 中文输入 | 映射为 |
|---------|--------|
| 站起 / 起立 | `stand_up` |
| 平衡站立 | `balance_stand` |
| 恢复站立 | `recovery_stand` |
| 蹲下 / 趴下 | `stand_down` |
| 停止 | `stop` |
| 阻尼 | `damp` |

对于 `move` 命令，LLM 会根据你的描述自动选择合适的参数：
- "向前走" → `vx > 0, vy = 0`
- "向左转" → `vyaw < 0`
- "后退" → `vx < 0`

#### 8.5.5 Agent 的安全机制

Agent 在生成命令时**严格遵守安全约束**，这些约束由 `EMBODIED.md`、`SKILLRUNTIME.md` 和运行时契约注入给 LLM：

```yaml
# Agent 无法执行的"危险操作"（会被拒绝）：
- 超出速度限制: vx > 0.5 → LLM 会自动裁剪
- 超长时间移动: duration_s > 1.0 → 会被提示使用多次短移动
- 原始 SDK 调用: raw_sdk_command → 直接禁止
- 自主导航: long-range navigation → 明确说明不支持
```

实际例子：
```
你说: "让Go2以 2m/s 的速度冲出去"

Agent 回复:
"⚠️ 安全限制：Go2 的最大速度为 0.5m/s，我已将速度限制在安全范围内。
 正在执行: vx=0.5, duration_s=1.0"
```

#### 8.5.6 Agent 的多轮推理

Agent 不是简单地把一句话翻译成一条命令，而是能进行**多步推理**：

```
你说: "让 Go2 表演个起身、走两步、蹲下的动作"

Agent 推理过程:
1. "起身" → stand_up + balance_stand
2. "走两步" → move (vx=0.3, duration_s=0.5) + stop
3. "蹲下" → damp + stand_down (阻尼模式比直接趴下更优雅)

生成 steps:
- command: stand_up
- command: balance_stand
- command: move, params: {vx: 0.3, duration_s: 0.5}
- command: stop
- command: damp
- command: stand_down
```

#### 8.5.7 环境依赖确认

要让自然语言控制正常工作，请确认以下配置：

| 配置项 | 位置 | 说明 |
|--------|------|------|
| LLM Provider | 环境变量 / 配置文件 | 支持 OpenAI、Anthropic、通义千问等 |
| Go2 Target | `TARGETS.md` | `enabled: true` |
| SkillRuntime | `SKILLRUNTIME.md` | `go2_builtin_command` 已定义 |
| EMBODIED.md | 模板目录 | 包含 Go2 能力描述（自动加载） |
| Runtime Contract | 合约 YAML | 安全限制已配置 |

### 8.6 通过 Agent 工具调用

> **适用场景**：开发者通过代码直接调用 Agent 的工具接口，适用于自动化流程集成。

如果你想通过代码让 Agent 直接控制机器人，它只能使用 `execute_step` 工具：

```python
# Agent 调用示例
agent.call_tool(
    tool_name="execute_step",
    arguments={
        "step": {
            "command": "move",
            "params": {
                "vx": 0.5,
                "vy": 0.0,
                "vyaw": 0.0,
                "duration_s": 0.5
            }
        }
    }
)
```

---

## 9. 常用命令速查

### 支持的命令

| 命令 | 说明 | 需要运动能力 |
|------|------|:-----------:|
| `stand_up` | 从趴下状态站起 | ✓ |
| `balance_stand` | 进入主动平衡站立 | - |
| `recovery_stand` | 恢复站立（用于摔倒后） | ✓ |
| `stand_down` | 从站立状态趴下 | - |
| `squat` | 蹲下（等同于 `stand_down`） | - |
| `damp` | 阻尼模式（释放关节） | - |
| `stop` | 紧急停止所有运动 | - |
| `move` | 受约束的移动 | ✓ |

### 移动参数

```yaml
- command: move
  params:
    vx: 0.3         # 前进/后退速度 (m/s)，范围 [-0.5, 0.5]，默认 0
    vy: 0.0         # 左/右横移速度 (m/s)，范围 [-0.2, 0.2]，默认 0
    vyaw: 0.0       # 旋转速度 (rad/s)，范围 [-0.5, 0.5]，默认 0
    duration_s: 1.0 # 移动持续时间 (秒)，范围 [0.1, 1.0]，默认 1
```

### 服务管理

```bash
# 查看 TargetWS 服务状态
conda run -n go2-sdk pgrep -a "server.py"

# 停止服务
# 在服务终端按 Ctrl+C

# 重启服务
conda run -n go2-sdk python PhyAgentOS/PhyAgentOS/runtime/targets/remote/go2/server.py \
  --host 0.0.0.0 \
  --port 9010 \
  --network-interface enp4s0 \
  --robot-ip 192.168.123.161

# Dry-Run 模式（不连接机器人）
conda run -n go2-sdk python PhyAgentOS/PhyAgentOS/runtime/targets/remote/go2/server.py \
  --host 0.0.0.0 \
  --port 9010 \
  --network-interface enp4s0 \
  --robot-ip 192.168.123.161 \
  --dry-run

# 详细日志模式
conda run -n go2-sdk python PhyAgentOS/PhyAgentOS/runtime/targets/remote/go2/server.py \
  --host 0.0.0.0 \
  --port 9010 \
  --network-interface enp4s0 \
  --robot-ip 192.168.123.161 \
  --verbose
```

### 网络诊断

```bash
# 测试与机器人的连通性
ping -c 5 192.168.123.161

# 测试 TargetWS 服务是否监听
nc -zv localhost 9010

# 查看所有网络接口
ip addr show

# 查看路由表
ip route show

# 查看 UDP 端口占用
ss -ulnp | grep 9010
```

---

## 10. 常见问题排查

### Q1: `ping 192.168.123.161` 不通

**可能原因**：
1. 网线未连接或连接松动
2. Go2 机器人未开机
3. 连接到了 WiFi 而不是有线网卡
4. 电脑的 IP 不在同一网段

**解决方法**：
```bash
# 1. 检查网线
# 看网口指示灯是否闪烁

# 2. 确认 Go2 已开机
# 听到风扇声或看到指示灯亮起

# 3. 确认使用的是有线网卡
ip addr show | grep 192.168.123

# 4. 手动设置电脑 IP
sudo ip addr add 192.168.123.222/24 dev enp4s0
sudo ip link set enp4s0 up

# 5. 再次测试
ping -c 3 192.168.123.161
```

### Q2: `ModuleNotFoundError: No module named 'unitree_sdk2py'`

**原因**：没有在 `go2-sdk` conda 环境中运行，或 SDK 未正确安装。

**解决方法**：
```bash
# 1. 确认环境
conda activate go2-sdk

# 2. 确认包已安装
pip list | grep unitree

# 3. 如果未安装，重新安装
cd /home/$(whoami)/unitree_sdk2_python
pip install -e .

# 4. 验证
python -c "from unitree_sdk2py.go2.sport.sport_client import SportClient; print('OK')"
```

### Q3: `ConnectionRefusedError` 或 `Connection timed out`

**原因**：TargetWS 服务未启动，或端口被占用。

**解决方法**：
```bash
# 1. 检查服务是否运行
ps aux | grep "server.py"

# 2. 检查端口是否被占用
ss -ulnp | grep 9010

# 3. 如果被占用，找到进程并杀死
lsof -i :9010
kill -9 <PID>

# 4. 重新启动服务
conda run -n go2-sdk python PhyAgentOS/PhyAgentOS/runtime/targets/remote/go2/server.py \
  --host 0.0.0.0 \
  --port 9010 \
  --network-interface enp4s0 \
  --robot-ip 192.168.123.161
```

### Q4: SDK 报错 `CycloneDDS cannot be located`

**解决方法**：手动编译 CycloneDDS（见 [第 4.5 步](#45-处理-sdk-安装失败的情况)）。

### Q5: 机器人不站起

**可能原因**：
1. 机器人在柔软表面（地毯、床）上
2. 机器人检测到障碍物
3. IMU 数据异常

**解决方法**：
```bash
# 1. 将机器人放在平坦坚硬的地面上
# 2. 确保机身水平放置（不要倾斜）
# 3. 尝试 recovery_stand 而不是 stand_up
# 4. 检查机器人是否有物理损坏
```

### Q6: `Go2 SDK command Move returned error code X`

**含义**：SDK 返回错误码（非 0 表示失败）。

**常见错误码**：
- `1`：超时
- `2`：参数超限
- `3`：安全保护触发

**解决方法**：
```bash
# 1. 检查是否超出速度/时间限制
# vx: [-0.5, 0.5]
# vy: [-0.2, 0.2]
# vyaw: [-0.5, 0.5]
# duration_s: [0.1, 1.0]

# 2. 检查机器人电量（低电量可能限制运动）

# 3. 查看详细日志（使用 --verbose 启动）
conda run -n go2-sdk python server.py --verbose ...
```

### Q7: PhyAgentOS 运行时连接失败

**排查步骤**：
```bash
# 1. 确认 TargetWS 服务正在运行
ps aux | grep server.py

# 2. 确认端口可访问
nc -zv localhost 9010

# 3. 检查 TARGETS.md 配置
# enabled 是否为 true？
# target_endpoint 是否正确？

# 4. 检查 SkillRuntime 定义
# go2_builtin_command 是否存在？

# 5. 查看 PhyAgentOS 日志
tail -f /var/log/phyagentos/runtime.log
# 或查看终端输出
```

### Q8: 机器人移动异常或不受控

**紧急处理**：
```yaml
# 立即发送停止命令
execution:
  steps:
    - command: stop
```

**物理紧急停止**：长按 Go2 机身顶部的电源按钮 5 秒。

**预防措施**：
- 始终在开阔空间测试
- 保持手在机器人附近
- 使用短时长移动（`duration_s=0.5`）先测试
- 移动前确保 `stand_up` 和 `balance_stand` 正常工作

### Q9: 自然语言控制不工作

**症状**：`paos run "让Go2站起来"` 执行后没有反应或报错。

**排查步骤**：
```bash
# 1. 确认 TargetWS 服务正在运行
nc -zv localhost 9010

# 2. 确认 LLM Provider 已配置
echo $OPENAI_API_KEY        # 或 $DASHSCOPE_API_KEY
echo $OPENAI_MODEL           # 确认设置了模型

# 3. 测试 LLM 连通性
python -c "from PhyAgentOS.providers import LiteLLMProvider; print('OK')"

# 4. 检查 TARGETS.md 中 Go2 是否启用
grep "enabled:" PhyAgentOS/templates/TARGETS.md

# 5. 查看详细日志
conda run -n go2-sdk python server.py --verbose  # TargetWS 日志
tail -f /tmp/go2_server.log                       # 后台服务日志
```

**常见原因**：
1. LLM API Key 未设置或过期
2. TargetWS 服务未启动
3. `TARGETS.md` 中 `enabled: false`
4. 网络问题导致 Agent 无法写入 SESSIONS.md

---

## 11. 安全须知

### ⚠️ 必须遵守

1. **测试环境**
   - 在**开阔、平坦、坚硬**的地面上测试
   - 移除周围障碍物（桌椅、宠物、儿童）
   - 确保机器人有至少 2 米 × 2 米的运动空间

2. **测试顺序**
   - 严格按照：`stand_up` → `balance_stand` → `stop` → `stand_down` 的顺序
   - 先测试站起/趴下，再测试移动
   - 先用小参数测试（`vx=0.3, duration_s=0.5`）

3. **操作员位置**
   - 测试时站在机器人**旁边**
   - 手放在能**立即扶住**机器人的位置
   - 不要远离机器人

4. **安全限制**
   - **禁止**暴露原始 SDK 命令给 Agent
   - **禁止**用于导航、视觉伺服或长时间自主移动
   - **禁止**超出安全限制参数（见下方）

### 安全限制速查

```
vx（前后速度）：     [-0.5,  0.5] m/s
vy（左右速度）：     [-0.2,  0.2] m/s
vyaw（旋转速度）：   [-0.5,  0.5] rad/s
duration_s（时长）： [0.1,   1.0] 秒
```

所有参数超出范围会被**自动裁剪**到限制内，但**不建议**依赖此行为。

### 🚨 紧急停止

**软件停止**（优先）：
```yaml
- command: stop
```

**物理停止**（如软件失效）：
- 长按 Go2 机身顶部电源按钮 **5 秒**
- 或直接切断电源（不推荐，可能损坏关节）

---

## 附录 B：完整部署脚本

以下脚本可以一键完成环境检查和服务器启动：

```bash
#!/bin/bash
# go2_setup_and_start.sh
# 用法: bash go2_setup_and_start.sh

set -e

# 配置变量（根据实际情况修改）
ROBOT_IP="192.168.123.161"
NETWORK_INTERFACE="enp4s0"
TARGETWS_PORT=9010
PHYAGENTOS_DIR="/home/$(whoami)/git/PhyAgentOS"

echo "===== Step 1: 检查网络连通性 ====="
if ! ping -c 2 -W 1 $ROBOT_IP > /dev/null 2>&1; then
    echo "❌ 无法连接到机器人 $ROBOT_IP"
    echo "请检查："
    echo "  1. 网线是否插好"
    echo "  2. 机器人是否开机"
    echo "  3. 是否连接到正确的网卡 ($NETWORK_INTERFACE)"
    exit 1
fi
echo "✓ 机器人连接正常"

echo ""
echo "===== Step 2: 检查/创建 conda 环境 ====="
if conda env list | grep -q "^go2-sdk "; then
    echo "✓ go2-sdk 环境已存在"
else
    echo "创建 go2-sdk 环境..."
    conda create -n go2-sdk python=3.10 -y
    echo "✓ 环境创建完成"
fi

echo ""
echo "===== Step 3: 安装依赖 ====="
conda run -n go2-sdk pip list | grep -q cyclonedds && echo "✓ cyclonedds 已安装" || {
    echo "安装 cyclonedds..."
    conda run -n go2-sdk pip install "cyclonedds==0.10.2" numpy opencv-python websockets msgpack
}

conda run -n go2-sdk pip list | grep -q unitree_sdk2py && echo "✓ unitree_sdk2py 已安装" || {
    echo "安装 unitree_sdk2py..."
    cd /home/$(whoami)
    if [ ! -d unitree_sdk2_python ]; then
        git clone https://github.com/unitreerobotics/unitree_sdk2_python.git
    fi
    cd unitree_sdk2_python
    conda run -n go2-sdk pip install -e .
}

echo ""
echo "===== Step 4: 验证 SDK ====="
conda run -n go2-sdk python -c "
from unitree_sdk2py.go2.sport.sport_client import SportClient
import cyclonedds
print('✓ SDK 导入成功')
"

echo ""
echo "===== Step 5: 启动 TargetWS 服务 ====="
echo "将在后台启动服务..."
echo "配置："
echo "  机器人 IP: $ROBOT_IP"
echo "  网络接口: $NETWORK_INTERFACE"
echo "  TargetWS 端口: $TARGETWS_PORT"
echo ""
echo "如需停止服务，运行: pkill -f 'server.py'"
echo ""

conda run -n go2-sdk nohup python "$PHYAGENTOS_DIR/PhyAgentOS/runtime/targets/remote/go2/server.py" \
    --host 0.0.0.0 \
    --port $TARGETWS_PORT \
    --network-interface $NETWORK_INTERFACE \
    --robot-ip $ROBOT_IP \
    > /tmp/go2_server.log 2>&1 &

SERVER_PID=$!
echo "✓ TargetWS 服务已启动 (PID: $SERVER_PID)"
echo "日志: tail -f /tmp/go2_server.log"
```

---

## 附录 C：文件清单

以下是本方案涉及的所有关键文件：

| 文件 | 作用 |
|------|------|
| `PhyAgentOS/runtime/targets/remote/go2/server.py` | TargetWS 服务端（核心控制） |
| `PhyAgentOS/runtime/targets/remote/go2/README.md` | 部署文档 |
| `PhyAgentOS/runtime/adapters/go2/target_adapter.py` | 运行时适配器 |
| `PhyAgentOS/templates/configs/runtime/contracts/go2_builtin.runtime.yaml` | 运行时行为契约 |
| `PhyAgentOS/templates/TARGETS.md` | Target 注册定义 |
| `PhyAgentOS/templates/SKILLRUNTIME.md` | SkillRuntime 定义 |
| `PhyAgentOS/templates/EMBODIED.md` | 集成指南 |
| `examples/go2_driver_config.json` | 驱动配置示例 |

---

## 附录 D：术语表

| 术语 | 说明 |
|------|------|
| **TargetWS** | PhyAgentOS 的 Target WebSocket 协议，标准化的机器人控制接口 |
| **Target** | 代表一个物理或仿真机器人的抽象实体 |
| **SkillRuntime** | 定义机器人如何执行技能/命令的运行时环境 |
| **Target Adapter** | 将机器人特定数据转换为 PhyAgentOS 标准格式的适配器 |
| **SportClient** | Unitree SDK2 提供的高层控制客户端（负责站起、移动等） |
| **CycloneDDS** | 开源的 DDS（数据分发服务）中间件，用于机器人通信 |
| **Builtin Command** | PhyAgentOS 的内置命令格式，用于直接控制机器人 |
| **execute_step** | Agent 可用的唯一工具，用于执行单个机器人命令 |
| **Dry-Run** | 模拟模式，不连接真实机器人，用于测试通信管道 |
| **Constrained Tools** | 受限制的工具集，仅暴露安全的子集给 Agent |

---

## 附录 E：故障排查流程图

```
Go2 无法连接
    │
    ├─ 1. ping 192.168.123.161 是否通？
    │   ├─ 否 → 检查网线、机器人电源、网卡配置
    │   └─ 是 ↓
    │
    ├─ 2. TargetWS 服务是否运行？
    │   ├─ 否 → 启动 server.py
    │   └─ 是 ↓
    │
    ├─ 3. nc -zv localhost 9010 是否通？
    │   ├─ 否 → 检查端口占用、防火墙
    │   └─ 是 ↓
    │
    ├─ 4. SDK 导入是否成功？
    │   ├─ 否 → 重新安装 cyclonedds + unitree_sdk2py
    │   └─ 是 ↓
    │
    └─ 5. TARGETS.md enabled 是否为 true？
        ├─ 否 → 改为 true
        └─ 是 → 查看 PhyAgentOS 日志排查
```

---

**文档版本**: v1.0  
**最后更新**: 2026-07-17  
**适用 PhyAgentOS 版本**: preview 分支  
**适用机器人**: Unitree Go2 (四足机器狗)
