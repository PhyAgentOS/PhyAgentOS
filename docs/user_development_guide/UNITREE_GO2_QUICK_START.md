# Unitree Go2 快速接入手册

> 适用分支：`preview` · [English](UNITREE_GO2_QUICK_START_en.md)

本手册说明如何在 Linux 主机上通过有线网络，将 Unitree Go2 接入
PhyAgentOS 的 `go2_real_builtin` Target。当前接入面向姿态切换和短距离、
低速运动，不支持导航、视觉伺服或长时间自主移动。

> [!WARNING]
> Go2 是真实运动设备。首次运行时请清空机器人周围区域，将机器人放在平整、
> 防滑地面上，并安排操作员在急停范围内全程监护。先完成 `--dry-run`，
> 再依次测试站立、停止和趴下，最后才测试短距离移动。

## 1. 接入结构

PhyAgentOS Agent 和 Unitree SDK2 使用两个独立的 Python 环境：

```text
PhyAgentOS（Python >= 3.11）
        │  TargetWS / WebSocket，默认 127.0.0.1:9010
        ▼
Go2 TargetWS Server（Python 3.10 + Unitree SDK2）
        │  CycloneDDS，经有线网卡
        ▼
Unitree Go2（默认 192.168.123.161）
```

默认值如下；如果你的设备或主机不同，请在后续命令中同步替换。

| 项目 | 默认值 |
|---|---|
| Go2 有线 IP | `192.168.123.161` |
| 主机有线 IP | `192.168.123.222/24` |
| SDK 网卡 | `enp4s0`（以实际查询结果为准） |
| TargetWS 地址 | `targetws://127.0.0.1:9010` |

## 2. 准备硬件与主机

建议准备：

- Unitree Go2 及电量充足的电池；
- 带有线网口的 Ubuntu/Linux 主机；
- 网线；
- Conda 或 Miniconda；
- 可用的模型服务 API Key；
- 无障碍、平整、防滑的测试区域。

接通网线并启动机器人。在图形网络设置中，将主机有线连接的 IPv4 方法设为
“手动”，地址填写 `192.168.123.222`，子网掩码填写 `255.255.255.0`
（即 `/24`）。点对点连接通常不需要网关和 DNS。

<p align="center">
  <img src="../imgs/unitree_go2/host-static-ip.png" alt="设置主机有线静态 IP" width="520">
</p>

查询有线网卡名称和地址：

```bash
ip -brief address
ip route
```

旧版系统也可以使用：

```bash
ifconfig
```

记录包含 `192.168.123.222` 的网卡名称，例如 `enp4s0`。不要直接照抄示例中的
网卡名。

<p align="center">
  <img src="../imgs/unitree_go2/verify-network-interface.png" alt="查询有线网卡名称和地址" width="520">
</p>

验证主机可以访问机器人：

```bash
ping -c 4 192.168.123.161
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
conda create -n go2-sdk python=3.10 -y
conda activate go2-sdk
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
conda run -n go2-sdk python - <<'PY'
from unitree_sdk2py.go2.sport.sport_client import SportClient
import cyclonedds
print("go2-sdk import ok")
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

<p align="center">
  <img src="../imgs/unitree_go2/agent-config.png" alt="PhyAgentOS 配置文件示例" width="520">
</p>

编辑 `~/.PhyAgentOS/config.json`，配置所选模型和对应 Provider 的 API Key，
并启用 Go2 Target。以下仅展示需要关注的字段；请把它们合并到 `paos onboard`
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
      "go2_real_builtin": true
    }
  }
}
```

不要把真实 API Key 提交到 Git 仓库或粘贴到公开日志中。

<p align="center">
  <img src="../imgs/unitree_go2/provider-api-key.png" alt="配置模型 Provider 和 API Key" width="520">
</p>

`runtime.targetEnabled` 的值优先于 `TARGETS.md` 中的 `enabled`，这是推荐的启用
方式。也可以在运行时工作区的 `TARGETS.md` 中把
`go2_real_builtin.enabled` 改为 `true`：

<p align="center">
  <img src="../imgs/unitree_go2/enable-go2-target.png" alt="在 TARGETS.md 中启用 Go2 Target" width="520">
</p>

如果机器人 IP、主机 IP 或网卡名不是默认值，请同步更新工作区文件：

- `~/.PhyAgentOS/workspace/TARGETS.md` 中 `go2_real_builtin.config`；
- `~/.PhyAgentOS/workspace/EMBODIED.md` 中 `go2_real_builtin` 的
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
conda run --no-capture-output -n go2-sdk \
  python PhyAgentOS/runtime/targets/remote/go2/server.py \
  --host 0.0.0.0 \
  --port 9010 \
  --network-interface enp4s0 \
  --robot-ip 192.168.123.161 \
  --dry-run
```

出现以下信息表示服务已监听：

```text
Go2 TargetWS server listening on targetws://0.0.0.0:9010
```

打开终端 B，启动 Agent：

```bash
conda activate paos
cd /path/to/PhyAgentOS
paos agent
```

可以先询问“当前连接了几个机器人？”，再明确要求：

```text
使用 go2_real_builtin Target 执行 stand_up；这是 dry-run，不要执行其他动作。
```

dry-run 中不会向 Go2 发送 SDK 命令。确认 Agent 能识别
`go2_real_builtin`、创建 Session 并返回成功后，再进入真机测试。

<p align="center">
  <img src="../imgs/unitree_go2/go2-connected.png" alt="PhyAgentOS 识别到 Go2 Target" width="520">
</p>

## 7. 启动真机

先用 `Ctrl+C` 停止 dry-run Server。再次确认机器人周围无人、地面平整且操作员
就位，然后在终端 A 移除 `--dry-run`：

```bash
conda run --no-capture-output -n go2-sdk \
  python PhyAgentOS/runtime/targets/remote/go2/server.py \
  --host 0.0.0.0 \
  --port 9010 \
  --network-interface enp4s0 \
  --robot-ip 192.168.123.161
```

在终端 B 运行 `paos agent`。建议按以下顺序逐项测试，每次确认机器人状态后再
继续：

1. `让 Go2 站起。`
2. `让 Go2 进入平衡站立。`
3. `停止 Go2 的移动。`
4. `让 Go2 趴下。`

完成上述测试后，才进行一次短距离移动：

```text
让 Go2 先站起并进入平衡站立，然后以 vx=0.1、vy=0、vyaw=0 移动 0.5 秒，最后停止。
```

## 8. 支持的命令与限制

| 命令 | 说明 |
|---|---|
| `stand_up` | 站起 |
| `balance_stand` | 平衡站立 |
| `recovery_stand` | 恢复站立 |
| `stand_down` / `squat` | 趴下/下蹲 |
| `damp` | 进入阻尼状态 |
| `stop` | 调用 `StopMove()` 停止移动 |
| `move` | 短时速度控制 |

`move` 参数由 TargetWS Server 强制裁剪到以下范围：

| 参数 | 范围 | 含义 |
|---|---:|---|
| `vx` | `[-0.5, 0.5]` m/s | 前后速度 |
| `vy` | `[-0.2, 0.2]` m/s | 横向速度 |
| `vyaw` | `[-0.5, 0.5]` rad/s | 偏航角速度 |
| `duration_s` | `[0.1, 1.0]` s | 单次移动时长 |

每次 `move` 结束后，Server 都会自动调用 `StopMove()`。当前 Target 不向 Agent
暴露原始 SDK 命令，也不接受任意 Action Chunk。

## 9. 停止与断开

正常结束时：

1. 先让机器人执行 `stop`；
2. 确认安全后执行 `stand_down`；
3. 用 `Ctrl+C` 退出 `paos agent`；
4. 用 `Ctrl+C` 退出 Go2 TargetWS Server。

TargetWS Server 退出时会尝试再次调用 `StopMove()`。这不能代替现场急停和操作员
监护；遇到异常运动时应优先使用机器人的物理安全措施。

## 10. 常见问题

| 现象 | 检查与处理 |
|---|---|
| `ping` 不通 | 检查网线、电源、`192.168.123.222/24`、网卡 UP 状态；临时断开可能抢占路由的其他网络。 |
| 找不到 `unitree_sdk2py` | 确认 Server 使用 `go2-sdk` 环境，并在 `unitree_sdk2_python` 目录执行过 `pip install -e .`。 |
| 找不到 CycloneDDS | 按第 4 节构建 0.10.x，并设置 `CYCLONEDDS_HOME` 后重装 SDK。 |
| Server 启动但机器人无响应 | 再次确认 `--network-interface` 是有线网卡；检查机器人是否可 `ping`，并查看 Server 日志中的 SDK 错误码。 |
| `Connection refused` / TargetWS 不可达 | 确认 Server 正在监听 `9010`；同机使用 `targetws://127.0.0.1:9010`。跨主机时把 `TARGETS.md` 的 Endpoint 改为 Server 主机 IP，并配置防火墙。 |
| `TARGET_DISABLED` | 在 `config.json` 设置 `runtime.targetEnabled.go2_real_builtin: true`，或修改工作区 `TARGETS.md`。 |
| Agent 报模型或 API Key 错误 | 检查模型名称、Provider 选择和对应 `apiKey`；不要把 Key 配到错误的 Provider 节点。 |
| 移动参数不生效 | `move` 参数必须放在 `params` 下；超出范围的数值会被 Server 裁剪。 |

## 11. 安全与能力边界

- `--host 0.0.0.0` 会在所有主机网卡上监听。仅在可信网络中使用，并通过防火墙
  限制 `9010` 端口；同机部署时可改用 `--host 127.0.0.1`。
- 不要将原始 SDK 调用、关闭安全限制或长时间运动能力暴露给 Agent。
- 不要用本接入执行导航、视觉伺服、楼梯、复杂地形或无人监护任务。
- Preflight 通过只表示配置和运行时契约兼容，不代表完成真机安全认证。
- 变更任务前优先执行 `stop`，从低速度、短时长开始逐步验证。

## 相关文档

- [Unitree Go2 TargetWS 说明](../../PhyAgentOS/runtime/targets/remote/go2/README.md)
- [PhyAgentOS 用户手册](../zh/02-user-manual.md)
- [Runtime 参数配置参考](../zh/04-runtime-configuration-reference.md)
- [通信架构](COMMUNICATION.md)
