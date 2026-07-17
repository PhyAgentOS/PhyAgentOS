# PiperGo2 Isaac Sim 仿真接入指南

> 从零开始接入 PhyAgentOS 的 **Isaac Sim 仿真环境**，直观感受 AI Agent 控制虚拟机器人。
> 无需任何真实硬件，只要有带 GPU 的 Linux 电脑即可。

---

## 目录

1. [整体架构概览](#1-整体架构概览)
2. [什么是 PiperGo2](#2-什么是-pipergo2)
3. [准备工作](#3-准备工作)
4. [安装 Python 环境](#4-安装-python-环境)
5. [准备仿真场景资产](#5-准备仿真场景资产)
6. [配置 Isaac Sim 路径](#6-配置-isaac-sim-路径)
7. [启动仿真环境](#7-启动仿真环境)
8. [发送任务让机器人动起来](#8-发送任务让机器人动起来)
9. [尝试更多交互](#9-尝试更多交互)
10. [常见问题排查](#10-常见问题排查)
11. [安全须知](#11-安全须知)

---

## 1. 整体架构概览

```
┌──────────────────────────────────────────────────────────────────┐
│                    用户（你）                                      │
│          "让 PiperGo2 走向桌子"                                   │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                  PhyAgentOS Watchdog                             │
│          读取 SESSIONS.md → 调度执行                              │
└──────────────────┬───────────────────────────────────────────────┘
                   │ targetws://127.0.0.1:9003
                   │ WebSocket + msgpack
                   ▼
┌──────────────────────────────────────────────────────────────────┐
│        Isaac Sim TargetWS Server                                 │
│  (PhyAgentOS/runtime/targets/remote/isaacsim/server.py)          │
│  协议翻译层：TargetWS ↔ Isaac Sim Rollout API                      │
└──────────────────┬───────────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────────┐
│      PiperGo2ManipulationRunner (PiperGo2 仿真驱动)               │
│  路径管理 · 导航 · 臂控制 · 场景描述                               │
└──────────────────┬───────────────────────────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────────────────────────┐
│          Isaac Sim / Omniverse 仿真引擎                           │
│  ├── 渲染引擎 (RTX 光线追踪)                                      │
│  ├── 物理引擎 (PhysX)                                             │
│  └── USD 场景 (asserts/merom_scene_baked.usd)                    │
└──────────────────────────────────────────────────────────────────┘
                   │
                   ▼
         🖥️ 弹出 Isaac Sim GUI 窗口
         (看到机械狗走动的实时画面)
```

**一句话总结**：

```
你说指令 → Watchdog 调度 → TargetWS 协议 → Isaac Sim 仿真 → 窗口里看到机械狗动起来
```

---

## 2. 什么是 PiperGo2

PiperGo2 是 PhyAgentOS 项目中的一个**仿真四足机械臂机器人**，它结合了：

- **四足底盘**：类似 Go2 的机器狗身体，可以移动和导航
- **机械臂**：7 自由度机械臂 + 夹爪，可以抓取物体
- **多摄像头**：俯视、手腕、侧视 3 个摄像头

在 Isaac Sim 仿真环境中，它是一个完整的虚拟机器人，运行在 NVIDIA Isaac Sim 物理仿真引擎中，支持 RTX 光线追踪渲染。

> **与 Go2 的区别**：
> - Go2 = 真实的 Unitree 机器狗，通过 TargetWS + Unitree SDK 控制
> - PiperGo2 = 仿真机械狗臂，通过 TargetWS + Isaac Sim 控制
> - 两者共享同一个 PhyAgentOS 接入框架，但后端完全不同

---

## 3. 准备工作

### 3.1 硬件要求

| 项目 | 最低要求 | 推荐 |
|------|---------|------|
| GPU | NVIDIA RTX 2080 (8GB VRAM) | RTX 3080+ (12GB+) |
| 内存 | 16 GB | 32 GB |
| 磁盘 | 50 GB 可用空间 | 100 GB+ SSD |
| OS | Ubuntu 20.04 / 22.04 | Ubuntu 22.04 |
| 显示器 | X11 桌面 | 本地桌面或 VNC |

> **关键**：必须有 NVIDIA GPU + 驱动。Isaac Sim 是 GPU 渲染的，CPU 无法运行。

### 3.2 软件要求

- **NVIDIA 驱动**：≥ 535（运行 `nvidia-smi` 验证）
- **CUDA**：12.x（驱动自带）
- **Python**：3.11（通过 conda 管理）
- **Conda**：Miniconda3 或 Anaconda
- **Git**：已安装
- **X11 显示服务**：有桌面环境的 Linux，或 SSH + X11 转发 / VNC

### 3.3 验证 GPU

```bash
nvidia-smi
```

看到类似输出说明正常：
```
+-----------------------------------------------------------------------------+
| NVIDIA-SMI 535.129.03   Driver Version: 535.129.03   CUDA Version: 12.2     |
|-------------------------------+----------------------+----------------------+
| GPU  Name        Persistence-M| Bus-Id        Disp.A | Volatile Uncorr. ECC |
| Fan  Temp  Perf  Pwr:Usage/Cap|         Memory-Usage | GPU-Util  Compute M. |
|===============================+======================+======================|
|   0  NVIDIA RTX A6000    Off  | 00000000:25:00.0 Off |                    0 |
|  0%   38C    P8    18W / 300W |   2304MiB / 49140MiB |      0%      Default |
+-------------------------------+----------------------+----------------------+
```

> 如果 `nvidia-smi` 报错，请先安装 NVIDIA 驱动。

### 3.4 验证显示环境

**有桌面环境**：
```bash
echo $DISPLAY
# 应该输出 :0 或 :1 之类的
```

**通过 SSH 连接**：
```bash
# 选项 1: X11 转发（需要本地安装 X Server，Mac 用 XQuartz）
ssh -X user@server

# 选项 2: VNC（推荐服务器环境）
# 安装 TigerVNC 或 TightVNC
```

---

## 4. 安装 Python 环境

### 4.1 克隆 PhyAgentOS 仓库

```bash
cd /home/$(whoami)
git clone https://github.com/PhyAgentOS/PhyAgentOS.git
cd PhyAgentOS
```

> 如果已经在本地克隆了，确认分支：
> ```bash
> cd /home/$(whoami)/git/PhyAgentOS
> git checkout preview
> ```

### 4.2 创建 conda 环境

```bash
# 创建环境
conda env create -f environment.yml

# 激活环境
conda activate paos
```

> **首次创建可能需要 5-15 分钟**，取决于网络速度。环境包含：
> - Python 3.11
> - PyTorch 2.9
> - usd-core 26.3
> - InternUtopia 2.2.1
> - 各种物理引擎依赖（Pinocchio, Assimp, HPP-FCL 等）

### 4.3 验证环境

```bash
python -c "import torch; print('PyTorch:', torch.__version__)"
python -c "import usd_core; print('USD:', usd_core.USDAPI_VERSION)"
python -c "import websockets; print('WebSockets:', websockets.__version__)"
```

> **如果 import 失败**：确认 `conda activate paos` 已执行。

---

## 5. 准备仿真场景资产

Isaac Sim 仿真需要场景文件（USD），包括房间、桌子、物体等。

### 5.1 检查 asserts 目录

```bash
ls asserts/
```

如果看到类似以下内容，说明已有场景文件：
```
merom_scene_baked.usd
robots/pipergo2/
robots/aliengo/
```

### 5.2 如果没有 asserts 目录

**情况 A：你有 PhyAgentOS3 仓库**

```bash
# 在你的 PhyAgentOS 仓库根目录执行
ln -sf /path/to/PhyAgentOS3/asserts asserts
```

**情况 B：从 PhyAgentOS3 单独链接**

```bash
# 如果你的 PhyAgentOS3 在这里
ln -sf /home/zyserver/work/my_project/PhyAgentOS3/asserts asserts
```

> **如果两个都不存在**，需要参考 PhyAgentOS3 文档下载场景资产。通常是一个 `asserts.zip` 文件，解压到仓库根目录。

### 5.3 验证场景文件

```bash
ls asserts/merom_scene_baked.usd
ls asserts/robots/pipergo2/pipergo2.usd
ls asserts/robots/aliengo/policy/move_by_speed/aliengo_loco_model_4000.pt
```

三个文件都应该存在。

---

## 6. 配置 Isaac Sim 路径

### 6.1 检查配置文件

打开 `rollout/configs/pipergo2_manipulation_gui.json`：

```bash
cat rollout/configs/pipergo2_manipulation_gui.json | head -20
```

你会看到 Isaac Sim 的路径配置：

```json
{
  "isaac_env": {
    "display": ":1",
    "env": {
      "ISAAC_PATH": "/home/zyserver/isaacsim3",
      "CARB_APP_PATH": "/home/zyserver/isaacsim3/kit",
      "EXP_PATH": "/home/zyserver/isaacsim3/apps"
    },
    "setup_python_env": "/home/zyserver/isaacsim3/setup_python_env.sh"
  }
}
```

### 6.2 设置你的 Isaac Sim 路径

**如果你的 Isaac Sim 安装在其他地方**，修改以下三个值：

1. 找到你的 Isaac Sim 安装目录（常见位置）：
   ```bash
   # 常见位置
   ls /home/$(whoami)/isaac-sim/
   ls /opt/isaac-sim/
   ls ~/isaacsim/
   find ~ -name "isaac-sim" -type d 2>/dev/null | head -5
   ```

2. 修改 `pipergo2_manipulation_gui.json` 中的路径：
   ```bash
   # 用编辑器打开
   nano rollout/configs/pipergo2_manipulation_gui.json
   
   # 修改 ISAAC_PATH、CARB_APP_PATH、EXP_PATH、setup_python_env
   # 例如：
   "ISAAC_PATH": "/home/你用户名/isaac-sim",
   "setup_python_env": "/home/你用户名/isaac-sim/setup_python_env.sh"
   ```

> **如果没有安装 Isaac Sim**：这是最大的前置依赖。你需要从 [NVIDIA Omniverse](https://developer.nvidia.com/isaac-sim) 下载并安装 Isaac Sim 3.x 版本。安装过程可能需要 30 分钟 + 20GB 空间。

### 6.3 设置 DISPLAY 环境变量

```bash
# 确认 DISPLAY 已设置
echo $DISPLAY
# 应该输出 :0 或 :1

# 如果没有设置
export DISPLAY=:0
```

---

## 7. 启动仿真环境

### 7.1 启动 Isaac Sim（终端 A）

打开**第一个终端**，执行：

```bash
cd /home/$(whoami)/git/PhyAgentOS

# 激活环境
conda activate paos

# 启动 Isaac Sim 仿真 + TargetWS 服务
bash scripts/start_isaacsim_gui.sh pipergo2 9003
```

**等待启动**：

首次启动 Isaac Sim 需要 **3-10 分钟**。你会看到：

1. **Isaac Sim 窗口弹出**（Merom 房间场景 + PiperGo2 机械狗）
2. **终端持续输出日志**

当终端出现以下信息时，说明启动成功：

```
Isaac Sim TargetWS server listening on targetws://0.0.0.0:9003
```

> ⚠️ **重要**：这个终端**必须保持运行**。仿真窗口会在 Isaac Sim 关闭时退出。

### 7.2 查看仿真窗口

启动成功后，你应该看到一个窗口：

```
┌────────────────────────────────────────────┐
│  Isaac Sim 3.x — Merom Scene              │
│                                            │
│     ┌──────────────────┐                   │
│     │                  │                   │
│     │   🐕 机械狗      │  房间场景          │
│     │   (PiperGo2)     │                   │
│     │                  │  ┌───┐            │
│     │                  │  │桌子│            │
│     │                  │  └───┘            │
│     └──────────────────┘                   │
│                                            │
│  [渲染：RTX 光线追踪] [物理：PhysX]         │
└────────────────────────────────────────────┘
```

### 7.3 确认服务就绪

在 Isaac Sim 窗口启动完成后，TargetWS 服务已经监听在 `9003` 端口：

```bash
# 在另一个终端检查（可选）
nc -zv localhost 9003
```

---

## 8. 发送任务让机器人动起来

### 8.1 发送导航命令

打开**第二个终端**（终端 B），发送第一个任务：

```bash
cd /home/$(whoami)/git/PhyAgentOS

# 激活环境
conda activate paos

# 发送导航任务
python scripts/run_runtime_watchdog.py \
  --workspace workspaces/pipergo2_isaac_sim \
  --session-id sess_piper_language_nav \
  --once
```

**你会看到的效果**：

1. 终端 B 开始输出 Watchdog 执行日志
2. **Isaac Sim 窗口中**，PiperGo2 机械狗开始移动，走向房间里的桌子
3. 执行完成后，终端显示 `success: true`

**终端输出示例**：
```
INFO ... Watchdog polling session sess_piper_language_nav ...
INFO ... Preflight check passed ...
INFO ... CommandSimSkillRuntime executing ...
INFO ... step 1: language="go to desk"
INFO ... navigate_to_named(waypoint_key=desk) ...
INFO ... Session succeeded! dist=0.0651 settled=60
```

### 8.2 任务执行过程可视化

```
时间线:

t=0s  [机械狗] 站立在房间入口处
        │
        │ Watchdog 读取 SESSIONS.md
        │ session: "go to desk"
        │
        ▼
t=3s  [机械狗] 开始移动，四肢交替迈步
        │
        │ Isaac Sim 以 240Hz 物理仿真
        │ 机械狗朝桌子方向前进
        │
        ▼
t=12s [机械狗] 到达桌子附近（距离 6.5 厘米）
        │
        │ 导航完成
        │ Watchdog 记录结果
        │
        ▼
t=13s [终端 B] Session succeeded! ✓
```

### 8.3 再次发送同一个任务

Isaac Sim 窗口**不会关闭**，可以反复发送任务：

```bash
# 直接重新运行相同的命令
python scripts/run_runtime_watchdog.py \
  --workspace workspaces/pipergo2_isaac_sim \
  --session-id sess_piper_language_nav \
  --once
```

每次执行，机械狗都会从当前位置走向桌子。

---

## 9. 尝试更多交互

### 9.1 可用任务一览

| session_id | 效果 | 难度 |
|------------|------|------|
| `sess_piper_language_nav` | 机械狗走向桌子 | ⭐ 入门 |
| `sess_piper_language_describe` | 描述场景内容（不动腿） | ⭐ 入门 |
| `sess_piper_action_arm` | 机械臂关节运动 | ⭐⭐ 进阶 |

### 9.2 尝试场景描述

```bash
python scripts/run_runtime_watchdog.py \
  --workspace workspaces/pipergo2_isaac_sim \
  --session-id sess_piper_language_describe \
  --once
```

**效果**：机械狗保持静止，但在终端输出房间的场景描述。终端 A 日志会显示摄像头采集的图像信息。

### 9.3 尝试机械臂运动

```bash
python scripts/run_runtime_watchdog.py \
  --workspace workspaces/pipergo2_isaac_sim \
  --session-id sess_piper_action_arm \
  --once
```

**效果**：机械狗的机械臂做关节运动（类似挥手）。你会在 Isaac Sim 窗口中看到 7 自由度机械臂的各个关节转动。

### 9.4 自定义任务

你可以直接在 `SESSIONS.md` 中添加新任务：

```bash
nano workspaces/pipergo2_isaac_sim/SESSIONS.md
```

在 `sessions:` 列表下添加：

```yaml
- session_id: sess_piper_custom
  goal_id: goal_piper_custom
  target_ref: target://pipergo2_isaac_remote
  skillruntime_ref: skillruntime://pipergo2_command_sim
  task_description: custom arm test
  status: pending
  execution:
    max_steps: 8
    steps:
    - mode: control
      action:
        arm_joint_controller:
        - - 0.0
          - 0.5
          - -0.5
          - 0.0
          - 0.5
          - 0.0
          - 0.0
          - 0.5
      sim_steps: 120
```

然后运行：
```bash
python scripts/run_runtime_watchdog.py \
  --workspace workspaces/pipergo2_isaac_sim \
  --session-id sess_piper_custom \
  --once
```

---

## 10. 常见问题排查

### Q1: `asserts/` 目录不存在

```bash
ls: asserts/: No such file or directory
```

**解决方法**：
```bash
# 链接 PhyAgentOS3 的 asserts 目录
ln -sf /path/to/PhyAgentOS3/asserts asserts

# 或者下载 asserts.zip 解压到仓库根目录
# 参考 PhyAgentOS3 文档
```

### Q2: Isaac Sim 窗口不弹出 / 黑屏

```
# 检查 DISPLAY
echo $DISPLAY
# 应该输出 :0 或 :1

# 如果没有输出
export DISPLAY=:0

# 如果是 SSH 连接，需要 X11 转发
ssh -X user@server

# 或者使用 VNC
```

### Q3: 终端 B 立即报错 `RUNTIME_PREFLIGHT_FAILED`

**常见原因**：
1. 终端 A 的 Isaac Sim 服务未启动
2. `9003` 端口未被监听

**检查方法**：
```bash
# 确认 TargetWS 在运行
nc -zv localhost 9003
# 应该输出: Succeeded!

# 如果连接失败
ss -ulnp | grep 9003
# 应该看到 python 进程监听 9003
```

### Q4: 机械狗不移动 / 机械臂几乎不动

**原因**：臂控需要足够的仿真步数。

**解决方法**：
- 导航任务：使用 `sess_piper_language_nav`（已配置足够步数）
- 臂控任务：确保 `sim_steps: 120+`（默认 30 可能不够）

### Q5: Isaac Sim 启动特别慢（> 10 分钟）

**正常现象**：首次启动 Isaac Sim 需要：
- 加载 RTX 光追驱动
- 编译 shader
- 初始化 PhysX 物理引擎

**首次启动可能需要 3-10 分钟，后续启动会快很多。**

### Q6: `LD_LIBRARY_PATH changed` 自动重启

这是 **正常行为**。Isaac Sim 首次加载时，bootstrap 脚本会检测到库路径变化，自动重新启动进程一次。终端会显示：

```
[isaac-bootstrap] LD_LIBRARY_PATH changed, re-execing process...
```

等待即可，不需要干预。

### Q7: Isaac Sim 安装问题

**如果还没有安装 Isaac Sim**：

```bash
# 1. 从 NVIDIA 下载
# https://developer.nvidia.com/isaac-sim

# 2. 安装后，确认路径
ls /home/你用户名/isaac-sim/
ls /home/你用户名/isaac-sim/setup_python_env.sh

# 3. 更新配置文件中的路径
nano rollout/configs/pipergo2_manipulation_gui.json
```

### Q8: 多机器人场景 (Merom)

如果你想看更复杂的场景（PiperGo2 + Franka 机械臂 + G1）：

```bash
# 终端 A: 启动 Merom 多机器人场景
bash scripts/start_isaacsim_gui.sh merom 9003

# 终端 B: 发送 PiperGo2 导航任务
python scripts/run_runtime_watchdog.py \
  --workspace workspaces/merom_isaac_sim \
  --session-id sess_merom_piper_nav \
  --once

# 终端 B: 发送 Franka 抓取任务
python scripts/run_runtime_watchdog.py \
  --workspace workspaces/merom_isaac_sim \
  --session-id sess_merom_franka_pick_place \
  --once
```

### Q9: 端口被占用

```bash
# 检查 9003 端口
lsof -i :9003

# 如果被占用，找到进程并杀死
kill -9 <PID>

# 重新启动 Isaac Sim
bash scripts/start_isaacsim_gui.sh pipergo2 9003
```

---

## 11. 安全须知

### ⚠️ 仿真环境安全说明

虽然这是仿真环境（不涉及真实机器人），但仍需注意：

1. **GPU 资源**：Isaac Sim 会占用大量 GPU 资源，运行期间避免其他重型 GPU 任务
2. **内存占用**：Isaac Sim 启动后约占用 4-8GB RAM
3. **磁盘空间**：Isaac Sim + 场景资产约占用 30-50GB 磁盘
4. **散热**：长时间运行 Isaac Sim 会导致 GPU 高温，确保机箱通风良好

### 关闭仿真

```bash
# 终端 A: 关闭 Isaac Sim 窗口（点击窗口右上角 ×）
# 或按 Ctrl+C（如果窗口没有响应）

# 确认进程已退出
ps aux | grep isaac
# 没有输出说明已退出
```

---

## 附录 A：快速参考卡

### 核心命令速查

```bash
# 1. 激活环境
conda activate paos

# 2. 启动仿真（终端 A — 保持运行）
bash scripts/start_isaacsim_gui.sh pipergo2 9003

# 3. 发送任务（终端 B）
python scripts/run_runtime_watchdog.py \
  --workspace workspaces/pipergo2_isaac_sim \
  --session-id sess_piper_language_nav \
  --once

# 4. 停止仿真
# 关闭 Isaac Sim 窗口 或 Ctrl+C
```

### 端口对照表

| 服务 | 端口 | 协议 | 说明 |
|------|------|------|------|
| Isaac Sim TargetWS | **9003** | WebSocket + msgpack | Isaac Sim 仿真后端 |
| Legacy Rollout WS | 8765 | WebSocket + msgpack | 旧版 rollout 协议（已不推荐） |
| noVNC | 31315 | WebSocket → VNC | 远程查看 Isaac 窗口 |

### 工作空间文件

```
workspaces/pipergo2_isaac_sim/
├── TARGETS.md              ← Target 注册（机器人配置）
├── SKILLRUNTIME.md         ← SkillRuntime 定义（运行行为）
├── SESSIONS.md             ← 任务列表（你要执行的任务）
├── LESSONS.md              ← 经验教训（历史问题记录）
├── LOG.md                  ← 会话日志
├── HOWTO.md                ← 操作指南（就是本文档的来源）
└── configs/
    └── runtime/
        └── contracts/
            └── isaacsim_pipergo2.runtime.yaml  ← 运行时合约
```

### 关键代码文件

```
PhyAgentOS/runtime/targets/remote/isaacsim/server.py    ← TargetWS 服务端
PhyAgentOS/runtime/adapters/isaacsim/target_adapter.py  ← 观测适配器
PhyAgentOS/runtime/adapters/factory.py                  ← 适配器注册
PhyAgentOS/runtime/watchdog/supervisor.py               ← Watchdog 调度器
PhyAgentOS/runtime/skillruntime/builtin/command_sim.py  ← 命令执行器
rollout/pipergo2_runner.py                               ← PiperGo2 仿真驱动
rollout/configs/pipergo2_manipulation_gui.json          ← 仿真配置
scripts/start_isaacsim_gui.sh                           ← 启动脚本
scripts/run_runtime_watchdog.py                         ← Watchdog 客户端
```

---

## 附录 B：架构对比 — PiperGo2 vs Go2

| 维度 | PiperGo2 (Isaac Sim) | Go2 (Unitree) |
|------|---------------------|---------------|
| **类型** | 仿真机器人 | 真实物理机器人 |
| **外观** | 机器狗 + 7 自由度机械臂 + 夹爪 | 四足机器狗（无机械臂） |
| **运行环境** | NVIDIA Isaac Sim (RTX 光追) | 真实硬件 + Unitree SDK |
| **通信后端** | Isaac Sim Rollout API (C++/PhysX) | CycloneDDS (UDP) |
| **TargetWS 端口** | 9003 | 9010 |
| **依赖** | Isaac Sim + GPU | Unitree SDK2 + conda |
| **仿真速度** | 240 Hz 物理仿真 | 实时 |
| **可视化** | Isaac Sim GUI 窗口 | 无（真机实物） |
| **调试** | 可回退、可记录、可分析 | 需物理现场 |
| **速度限制** | 由仿真参数控制 | vx[-0.5,0.5] 等硬限制 |

### 共同点

- **相同的 TargetWS 协议**：两种机器人通过同一个 TargetWS 协议接入 PhyAgentOS
- **相同的 Watchdog 调度**：Session 管理和任务调度完全一致
- **相同的 SkillRuntime 框架**：`CommandSimSkillRuntime` 两种都用
- **相同的适配器模式**：每种机器人有独立的 Target Adapter
- **相同的安全约束**：Agent 只能通过 `execute_step` 工具控制

---

## 附录 C：下一步

完成 PiperGo2 仿真体验后，你可以：

1. **继续探索 Merom 多机器人场景** — `bash scripts/start_isaacsim_gui.sh merom 9003`
2. **接入真实 Go2 机器狗** — 参考 `docs/go2_setup_guide.md`
3. **尝试 VLA 策略** — `pipergo2_isaac_vla` 使用 OpenPI 视觉语言动作模型
4. **自定义场景** — 修改 `asserts/` 中的 USD 文件
5. **开发新任务** — 编辑 `SESSIONS.md` 添加新 session

---

**文档版本**: v1.0  
**最后更新**: 2026-07-17  
**适用环境**: Isaac Sim 3.x + PhyAgentOS preview 分支  
**适用机器人**: PiperGo2 (仿真四足机械臂机器狗)
