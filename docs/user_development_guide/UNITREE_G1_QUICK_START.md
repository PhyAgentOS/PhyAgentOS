# Unitree G1 快速接入手册

> 适用分支：`preview` · [English](UNITREE_G1_QUICK_START_en.md)

本手册说明如何在 Linux 主机上通过有线网络，将 Unitree G1 双足人形机器人接入
PhyAgentOS 的 `g1_real_builtin` Target。当前接入面向姿态切换、短距离低速移动
和预设手臂交互手势，不支持导航、复杂地形机动或长时间自主运行。

> [!WARNING]
> G1 是真实运动设备且包含精密关节和手臂机构。首次运行时请清空机器人周围至少 2
> 米区域，将机器人放在平整、防滑地面上，并安排操作员在急停范围内全程监护。先完成
> `--dry-run`，再依次测试站起、停止、坐下，最后才测试短距离移动和手臂动作。手臂
> 动作执行时请确保前方无障碍物，防止夹伤或碰撞。

## 1. 接入结构

PhyAgentOS Agent 和 Unitree SDK2 使用两个独立的 Python 环境：

```text
PhyAgentOS（Python >= 3.11）
        │  TargetWS / WebSocket，默认 127.0.0.1:9030
        ▼
G1 TargetWS Server（Python 3.10 + Unitree SDK2）
        │  CycloneDDS，经有线网卡
        ▼
Unitree G1（默认 192.168.137.1）
```

G1 相比 Go2 引入了额外的 **G1ArmActionClient**（手臂预设动作服务）模块，一个
TargetWS Server 实例会同时初始化 `LocoClient` 和 `G1ArmActionClient` 两个 SDK
客户端。

默认值如下；如果你的设备或主机不同，请在后续命令中同步替换。

| 项目 | 默认值 |
|---|---|
| G1 IP | `192.168.137.1` |
| 主机有线 IP | `192.168.137.222` |
| SDK 网卡 | `enp4s0`（以实际查询结果为准） |
| TargetWS 地址 | `targetws://127.0.0.1:9030` |

## 2. 准备硬件与主机

建议准备：

- Unitree G1 及电量充足的电池；
- 带有线网口的 Ubuntu/Linux 主机；
- 网线；
- Conda 或 Miniconda；
- 可用的模型服务 API Key；
- 无障碍、平整、防滑的测试区域（建议半径 2 米以上）；
- 确保 G1 手臂前方无障碍物。

接通网线并启动机器人。在图形网络设置中，将主机有线连接的 IPv4 方法设为
"手动"，地址填写 `192.168.137.222`，子网掩码填写 `255.255.255.0`
（即 `/24`）。点对点连接通常不需要网关和 DNS。

查询有线网卡名称和地址：

```bash
ip -brief address
ip route
```

旧版系统也可以使用：

```bash
ifconfig
```

记录包含 `192.168.137.222` 的网卡名称，例如 `enp4s0`。不要直接照抄示例中的
网卡名。

验证主机可以访问机器人：

```bash
ping -c 4 192.168.137.1
```

只有收到回复后再继续。如果失败，请先检查网线、机器人电源、主机静态 IP、
子网掩码和网卡状态。

## 3. 安装 PhyAgentOS

创建 Python 3.11 环境并安装 `preview` 分支：

```bash
conda create -n paos python=3.11 -y
conda activate paos

git clone --branch preview --single-branch https://github.com/PhyAgentOS/PhyAgentOS.git
cd PhyAgentOS
python -m pip install -U pip
pip install -e .
```

验证命令行入口：

```bash
paos --help
```

后续所有包含 `PhyAgentOS/...` 的命令均从仓库根目录执行。

## 4. 安装 Unitree SDK2 环境

Unitree SDK2 使用独立的 Python 3.10 环境，PhyAgentOS 的 `paos` 环境不需要
安装该 SDK。

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

如果最后一步提示找不到 CycloneDDS，请先构建 CycloneDDS 0.10.x，再重新安装
SDK：

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

验证 SDK 导入：

```bash
conda run -n g1-sdk python - <<'PY'
from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
from unitree_sdk2py.g1.arm.g1_arm_action_client import G1ArmActionClient
print("g1-sdk import ok")
PY
```

## 5. 初始化并配置 PhyAgentOS

回到仓库根目录并初始化：

```bash
conda activate paos
cd /path/to/PhyAgentOS
paos onboard
```

该命令会创建 `~/.PhyAgentOS/config.json` 和默认工作区
`~/.PhyAgentOS/workspace`。

编辑 `~/.PhyAgentOS/config.json`，配置所选模型和对应 Provider 的 API Key，
并启用 G1 Target。以下仅展示需要关注的字段；请把它们合并到 `paos onboard`
生成的完整 JSON 中，不要用片段覆盖整个文件。

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

不要把真实 API Key 提交到 Git 仓库或粘贴到公开日志中。

`runtime.targetEnabled` 的值优先于 `TARGETS.md` 中的 `enabled`，这是推荐的启用
方式。也可以在运行时工作区的 `TARGETS.md` 中把
`g1_real_builtin.enabled` 改为 `true`。

如果机器人 IP、主机 IP 或网卡名不是默认值，请同步更新工作区文件：

- `~/.PhyAgentOS/workspace/TARGETS.md` 中 `g1_real_builtin.config`；
- `~/.PhyAgentOS/workspace/EMBODIED.md` 中 `g1_real_builtin` 的
  Runtime Connection。

`TARGETS.md` 会在首次启动 Agent 时自动生成；如果要在首次启动前修改，可先
从仓库模板复制：

```bash
cp PhyAgentOS/templates/TARGETS.md ~/.PhyAgentOS/workspace/TARGETS.md
```

TargetWS Server 的 `--network-interface` 和 `--robot-ip` 参数仍须使用相同的
实际值。

## 6. 先完成 dry-run

打开终端 A，在仓库根目录启动不连接、不控制真机的 TargetWS Server：

```bash
conda run --no-capture-output -n g1-sdk \
  python PhyAgentOS/runtime/targets/remote/g1/server.py \
  --host 0.0.0.0 \
  --port 9030 \
  --network-interface enp4s0 \
  --robot-ip 192.168.137.1 \
  --dry-run
```

出现以下信息表示服务已监听：

```text
G1 TargetWS server listening on targetws://0.0.0.0:9030
```

打开终端 B，启动 Agent：

```bash
conda activate paos
cd /path/to/PhyAgentOS
paos agent
```

可以先询问"当前连接了几个机器人？"，再明确要求：

```text
使用 g1_real_builtin Target 执行 squat2stand；这是 dry-run，不要执行其他动作。
```

dry-run 中不会向 G1 发送 SDK 命令。确认 Agent 能识别
`g1_real_builtin`、创建 Session 并返回成功后，再进入真机测试。

## 7. 启动真机

先用 `Ctrl+C` 停止 dry-run Server。再次确认机器人周围无人、地面平整且操作员
就位，然后在终端 A 移除 `--dry-run`：

```bash
conda run --no-capture-output -n g1-sdk \
  python PhyAgentOS/runtime/targets/remote/g1/server.py \
  --host 0.0.0.0 \
  --port 9030 \
  --network-interface enp4s0 \
  --robot-ip 192.168.137.1
```

在终端 B 运行 `paos agent`。建议按以下顺序逐项测试，每次确认机器人状态后再
继续：

1. `让 G1 从蹲姿站起。`
2. `让 G1 进入平衡站立。`
3. `停止 G1 的移动。`
4. `让 G1 坐下。`

完成上述测试后，才进行一次短距离移动：

```text
让 G1 先站起并进入平衡站立，然后以 vx=0.1、vy=0、vyaw=0 移动 0.5 秒，最后停止。
```

## 8. 支持的命令与限制

### 8.1 Loco 姿势命令

| 命令 | 说明 |
|---|---|
| `squat2stand` | 从蹲姿站起（`SetFsmId(706)`） |
| `balance_stand` | 平衡站立 |
| `lie2stand` | 从躺姿恢复站立（`SetFsmId(702)`） |
| `stand2squat` | 站起→蹲下（`SetFsmId(706)`） |
| `sit` | 坐下（`SetFsmId(3)`） |
| `damp` | 阻尼模式（`SetFsmId(1)`） |
| `zero_torque` | 零扭矩 / 安全模式（`SetFsmId(0)`） |
| `stop_move` | 停止移动 |

### 8.2 速度控制命令

| 命令 | 参数 | 说明 |
|---|---|---|
| `move` | `vx`, `vy`, `vyaw`, `step` | 速度控制（分段步进模式） |

`move` 参数由 TargetWS Server 强制裁剪到以下范围：

| 参数 | 范围 | 含义 |
|---|---:|---|
| `vx` | `[-0.8, 0.8]` m/s | 前后速度 |
| `vy` | `[-0.2, 0.2]` m/s | 横向速度 |
| `vyaw` | `[-0.5, 0.5]` rad/s | 偏航角速度 |
| `step` | `[0.1, 2.0]` s | 总移动时长 |

每次 `move` 结束后，Server 都会自动调用 `StopMove()`。当前 Target 不向 Agent
暴露原始 SDK 命令，也不接受任意 Action Chunk。

### 8.3 手臂预设手势命令

| 命令 | Action ID | 说明 |
|---|---:|---|
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
| `face_wave` | 25 | 挥手（脸部附近） |
| `high_wave` | 26 | 挥手（高处） |
| `shake_hand` | 27 | 握手 |
| `release_arm` | 99 | 释放手臂（回到初始位置） |

> [!IMPORTANT]
> 手臂手势执行前，G1 必须处于 `balance_stand` 或 `squat2stand` 状态。如果 G1
> 不在站立状态，请先执行姿势命令，再执行手势命令。手臂动作执行时请确保机器人前方
> 无障碍物。

## 9. 停止与断开

正常结束时：

1. 先让机器人执行 `stop_move`；
2. 确认安全后执行 `sit` 或 `damp`；
3. 用 `Ctrl+C` 退出 `paos agent`；
4. 用 `Ctrl+C` 退出 G1 TargetWS Server。

TargetWS Server 退出时会尝试再次调用 `StopMove()`。这不能代替现场急停和操作员
监护；遇到异常运动时应优先使用机器人的物理安全措施。

## 10. 常见问题

| 现象 | 检查与处理 |
|---|---|
| `ping` 不通 | 检查网线、电源、`192.168.137.222/24`、网卡 UP 状态；临时断开可能抢占路由的其他网络。 |
| 找不到 `unitree_sdk2py` | 确认 Server 使用 `g1-sdk` 环境，并在 `unitree_sdk2_python` 目录执行过 `pip install -e .`。 |
| 找不到 CycloneDDS | 按第 4 节构建 0.10.x，并设置 `CYCLONEDDS_HOME` 后重装 SDK。 |
| Server 启动但机器人无响应 | 再次确认 `--network-interface` 是有线网卡；检查机器人是否可 `ping`，并查看 Server 日志中的 SDK 错误码。 |
| `Connection refused` / TargetWS 不可达 | 确认 Server 正在监听 `9030`；同机使用 `targetws://127.0.0.1:9030`。跨主机时把 `TARGETS.md` 的 Endpoint 改为 Server 主机 IP，并配置防火墙。 |
| `TARGET_DISABLED` | 在 `config.json` 设置 `runtime.targetEnabled.g1_real_builtin: true`，或修改工作区 `TARGETS.md`。 |
| Agent 报模型或 API Key 错误 | 检查模型名称、Provider 选择和对应 `apiKey`；不要把 Key 配到错误的 Provider 节点。 |
| 手臂动作执行失败 | 确保 G1 处于站立状态（`balance_stand` 或 `squat2stand`），且手臂前方无障碍物。 |
| `SwitchToUserCtrl` 超时 | 确认 SDK 版本与 G1 固件兼容；尝试断电重启 G1 后重新连接。 |

## 11. 安全与能力边界

- `--host 0.0.0.0` 会在所有主机网卡上监听。仅在可信网络中使用，并通过防火墙
  限制 `9030` 端口；同机部署时可改用 `--host 127.0.0.1`。
- 不要将原始 SDK 调用、关闭安全限制或长时间连续运动能力暴露给 Agent。
- G1 是双足人形机器人，平衡能力有限。不要用本接入执行楼梯、斜坡、复杂地形或
  无人监护任务。
- 手臂预设手势是快速触发动作，执行时关节活动范围较大。操作时请确保手臂路径上有
  充足空间，避免夹伤或损坏物体。
- Preflight 通过只表示配置和运行时契约兼容，不代表完成真机安全认证。
- 变更任务前优先执行 `stop_move`，从低速度、短时长开始逐步验证。

## 相关文档

- [Unitree G1 接入方案设计](../../g1_integration_design.md)
- [PhyAgentOS 用户手册](../zh/02-user-manual.md)
- [Runtime 参数配置参考](../zh/04-runtime-configuration-reference.md)
- [通信架构](COMMUNICATION.md)
- [Unitree Go2 快速接入手册](UNITREE_GO2_QUICK_START.md)
