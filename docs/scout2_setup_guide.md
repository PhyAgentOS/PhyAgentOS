# 松灵 Scout 2.0 接入 PhyAgentOS 指南

> 将松灵 Scout 2.0 差速移动机器人接入 PhyAgentOS，通过 ROS2 通信实现自然语言控制。
> 基于 Go2 的 TargetWS 架构扩展，适配 ROS2 后端。

---

## 目录

1. [整体架构概览](#1-整体架构概览)
2. [Scout 2.0 简介](#2-scout-20-简介)
3. [准备工作](#3-准备工作)
4. [网络配置](#4-网络配置)
5. [安装 ROS2 环境](#5-安装-ros2-环境)
6. [创建 Scout TargetWS Server](#6-创建-scout-targetws-server)
7. [创建 Scout Target Adapter](#7-创建-scout-target-adapter)
7.5 [创建 Scout Target Proxy（远程客户端代理）](#75-创建-scout-target-proxy远程客户端代理)
8. [注册 Target 和 SkillRuntime](#8-注册-target-和-skillruntime)
   - [8.1 编辑 TARGETS.md](#81-编辑-targetsmd)
   - [8.2 在 factory.py 中注册 Proxy](#82-在-factorypy-中注册-proxy)
   - [8.3 创建运行时合约](#83-创建运行时合约)
9. [创建工作空间](#9-创建工作空间)
   - [9.1 创建目录结构](#91-创建目录结构)
   - [9.2 创建 TARGETS.md](#92-创建-targetsmd)
   - [9.3 创建 SKILLRUNTIME.md](#93-创建-skillruntimemd)
   - [9.4 创建 SESSIONS.md（默认任务）](#94-创建-sessionsmd默认任务)
   - [9.5 创建运行时合约](#95-创建运行时合约)
   - [9.6 创建 Target Adapter](#96-创建-target-adapter)
   - [9.7 验证目录结构](#97-验证目录结构)
10. [启动并测试](#10-启动并测试)
    - [10.1 启动 Scout ROS2（Scout 本体）](#101-启动-scout-ros2scout-本体)
    - [10.2 安装 Python 依赖](#102-安装-python-依赖)
    - [10.3 启动 TargetWS Server（控制电脑）](#103-启动-targetws-server控制电脑)
    - [10.4 测试连接](#104-测试连接)
    - [10.5 启动 PhyAgentOS Watchdog](#105-启动-phyagentos-watchdog)
    - [10.6 验证真实控制](#106-验证真实控制)
11. [自然语言控制示例](#11-自然语言控制示例)
11. [常见问题排查](#11-常见问题排查)
    - [Q1: ROS2 话题连接失败](#q1-ros2-话题连接失败)
    - [Q2: rclpy 导入失败](#q2-rclpy-导入失败)
    - [Q3: Scout 不移动](#q3-scout-不移动)
    - [Q4: 摄像头画面查看](#q4-摄像头画面查看)
    - [Q5: LiDAR 点云查看](#q5-lidar-点云查看)
    - [Q6: SESSIONS.md YAML 解析失败](#q6-sessionsmd-yaml-解析失败)
12. [安全须知](#12-安全须知)

---

## 1. 整体架构概览

```
┌──────────────────────────────────────────────────────────────────┐
│                    用户（你）                                      │
│          "让 Scout 向前走 2 米然后左转"                           │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                  PhyAgentOS Watchdog                             │
│          读取 SESSIONS.md → 调度执行                              │
└──────────────────┬───────────────────────────────────────────────┘
                   │ targetws://127.0.0.1:9020
                   │ WebSocket + msgpack
                   ▼
┌──────────────────────────────────────────────────────────────────┐
│        Scout TargetWS Server                                     │
│  (PhyAgentOS/runtime/targets/remote/scout/server.py)             │
│  协议翻译层：TargetWS ↔ ROS2 (rclpy)                              │
└──────────────────┬───────────────────────────────────────────────┘
                   │
                   │ ROS2 Topics
                   │ ├── /cmd_vel (Twist) → 速度控制
                   │ ├── /odom (Odometry) → 里程计
                   │ ├── /camera/* → RGB/深度图像
                   │ └── /velodyne_points → 3D 点云
                   ▼
┌──────────────────────────────────────────────────────────────────┐
│          Scout 2.0 机器人本体                                     │
│  ├── ROS2 Hub (运行在 Scout 上)                                   │
│  ├── RealSense 摄像头 (RGB + Depth)                              │
│  └── Velodyne LiDAR (3D 点云)                                    │
└──────────────────────────────────────────────────────────────────┘
                   │
                   ▼
         🖥️ 可实时查看摄像头画面 + LiDAR 点云
```

**与 Go2 架构对比**：

| 维度 | Go2 | Scout 2.0 |
|------|-----|-----------|
| **通信后端** | Unitree SDK2 (CycloneDDS) | ROS2 (rclpy) |
| **TargetWS 端口** | 9010 | **9020**（需自定义） |
| **控制接口** | SportClient.move() | ROS2 /cmd_vel |
| **观测数据** | 空（无传感器） | RGB 图像 + LiDAR |
| **运动模型** | 四足差速 | 差速驱动 |
| **速度维度** | vx, vy, vyaw | linear.x, angular.z |

---

## 2. Scout 2.0 简介

松灵 Scout 2.0 是一款差速移动机器人平台：

| 参数 | 值 |
|------|-----|
| 尺寸 | 约 500×400×300 mm |
| 重量 | ~15 kg |
| 速度 | 最大 2 m/s |
| 驱动 | 4 轮差速（2 驱动 + 2 从动） |
| 传感器 | RealSense D435i + Velodyne LiDAR |
| 计算平台 | Jetson Orin Nano/NX（板载） |
| 通信 | WiFi / Ethernet（ROS2） |
| ROS2 版本 | Humble (Ubuntu 22.04) |

**差速运动模型**：
```
      左轮 (v_l)    右轮 (v_r)
         ⊙ ◄────────► ⊙
           
         ────────────
         │ Scout    │
         ────────────
                │
                ▼
         v = (v_l + v_r) / 2    ← 线速度
         ω = (v_r - v_l) / L   ← 角速度（L=轮距）
```

控制只需两条命令：
- **linear.x**：前进/后退（正=前进，负=后退）
- **angular.z**：左转/右转（正=逆时针，负=顺时针）

---

## 3. 准备工作

### 3.1 硬件清单

| 物品 | 数量 | 备注 |
|------|------|------|
| Scout 2.0 机器人 | 1 | 已配置 ROS2 |
| 控制电脑 | 1 | Linux，与 Scout 同一网络 |
| 以太网线/路由器 | 1 | 连接 Scout 与控制电脑 |

### 3.2 软件要求

- **Scout 端**：Ubuntu 22.04 + ROS2 Humble（应已预装）
- **控制电脑**：Ubuntu 22.04 / 20.04
- **Python**：3.10（独立 conda 环境，与 Go2 共享或新建）
- **ROS2**：Humble（控制电脑需安装 rclpy）
- **Git + Conda**：已安装

### 3.3 确认 Scout ROS2 接口

在 Scout 本机上验证 ROS2 节点是否正常运行：

```bash
# SSH 到 Scout
ssh unitree@<SCOUT_IP>

# 启动 Scout ROS2 节点（如果没自动启动）
ros2 launch scout_bringup scout.launch.py

# 检查话题列表
ros2 topic list

# 应该看到以下话题：
# /cmd_vel
# /odom
# /light_control
# /scout_status
# /rc_status
# /camera/camera/color/image_raw
# /camera/camera/depth/image_rect_raw
# /velodyne_packets
# /velodyne_points
```

**记录 Scout 的 IP 地址**，后续配置需要用到。

---

## 4. 网络配置

### 4.1 物理连接

通过以太网线或 WiFi 将控制电脑与 Scout 连接到**同一网络**。

### 4.2 确认连通性

```bash
# 替换 <SCOUT_IP> 为你的 Scout 实际 IP
SCOUT_IP=192.168.101.150
ping -c 3 $SCOUT_IP
```

### 4.3 设置 ROS2 环境

在**控制电脑**上设置 ROS2 环境：

```bash
# 确认 ROS2 版本（Scout 用 Humble）
echo $ROS_DISTRO
# 应该输出: humble

# 如果没有设置，执行：
source /opt/ros/humble/setup.bash
```

### 4.4 设置 ROS2 通信环境

> ⚠️ **端口说明**：下面设置的 `http://IP:11311` 是 ROS1 Master 的遗留格式，**ROS2 实际上不使用 Master 机制**。
> ROS2 使用 **DDS（数据分发服务）** 进行点对点通信，通过 UDP 端口 **7400-7500** 发现节点和传输 Topic。
> 这个 URL 只是格式要求，端口号写什么都可以。真正的通信依赖的是 **同一网段 + 相同 ROS_DOMAIN_ID**。

Scout 2.0 的 ROS2 节点运行在 Scout 本机上。需要在控制电脑上设置：

```bash
SCOUT_IP=192.168.101.150  # 替换为你的 Scout IP

# 设置 ROS2 Master URI（格式要求，端口值无所谓）
export ROS_MASTER_URI=http://$SCOUT_IP:11311

# 设置 ROS2 Domain ID（Scout 和 control PC 必须相同，默认 0）
export ROS_DOMAIN_ID=0
```

> **ROS1 vs ROS2 通信架构对比**：
>
> | 维度 | ROS1 | ROS2 |
> |------|------|------|
> | 中心服务 | Master (端口 11311) | 无 |
> | 通信协议 | TCP-XML-RPC | DDS (UDP 7400-7500) |
> | 节点发现 | Master 注册/发现 | DDS 局域网广播发现 |
> | 防火墙 | 只开 11311 | 开 UDP 7400-7500 |
> | 网络要求 | 必须连 Master | 同一网段即可 |

---

## 5. 安装 ROS2 环境

### 5.1 创建 conda 环境（可与 Go2 共享）

```bash
# 如果已有 go2-sdk 环境且有 ROS2，可直接使用该环境
# 否则创建新环境：
conda create -n scout-sdk python=3.10 -c conda-forge --override-channels -y
conda activate scout-sdk
python -m pip install -U pip setuptools wheel
```

### 5.2 安装 Python ROS2 客户端库

```bash
# 安装 rclpy（ROS2 Python 客户端）
conda activate scout-sdk
pip install rclpy ros_numpy numpy opencv-python websockets msgpack
```

> **注意**：`rclpy` 需要与系统安装的 ROS2 版本兼容。如果 `pip install rclpy` 失败，从 ROS2 安装包中获取：
> ```bash
> source /opt/ros/humble/setup.bash
> # rclpy 已在 /opt/ros/humble/lib/python3.10/site-packages/
> ```

### 5.3 验证 ROS2 安装

```bash
conda run -n scout-sdk python -c "
import rclpy
print('ROS2 rclpy 导入成功 ✓')
"
```

---

## 6. 创建 Scout TargetWS Server

参考 Go2 的 `server.py`，创建 Scout 版本：

### 6.1 创建文件

```bash
mkdir -p PhyAgentOS/runtime/targets/remote/scout
touch PhyAgentOS/runtime/targets/remote/scout/__init__.py
nano PhyAgentOS/runtime/targets/remote/scout/server.py
```

### 6.2 完整代码

> ⚠️ **安装依赖前**，确保在 `scout-sdk` 环境中安装了 `websockets` 和 `msgpack`：
> ```bash
> conda activate scout-sdk
> pip install websockets msgpack
> ```

```bash
mkdir -p PhyAgentOS/runtime/targets/remote/scout
touch PhyAgentOS/runtime/targets/remote/scout/__init__.py
```

然后用以下内容覆盖 `PhyAgentOS/runtime/targets/remote/scout/server.py`：

```python
"""Standalone TargetWS server for Unitree Scout 2.0 via ROS2.

Run this in an environment that has rclpy installed. The server speaks
the same msgpack-over-WebSocket TargetWS protocol used by PhyAgentOS runtime.

Usage (dry-run):
  python server.py --host 0.0.0.0 --port 9020 \\
    --scout-ip 192.168.101.150 --ros-master http://192.168.101.150:11311 --dry-run

Usage (real robot):
  python server.py --host 0.0.0.0 --port 9020 \\
    --scout-ip 192.168.101.150 --ros-master http://192.168.101.150:11311
"""

from __future__ import annotations

import argparse
import logging
import math
import os
import time
import traceback
from typing import Any

import msgpack
import websockets

RPC_VERSION = "phyagentos.runtime_rpc.v2"
logger = logging.getLogger(__name__)

# 速度安全限制（差速驱动）
DEFAULT_LIMITS = {
    "linear_x": (-0.5, 0.5),
    "angular_z": (-1.0, 1.0),
    "duration_s": (0.1, 3.0),
}
SDK_OK = 0


def packb(payload: Any) -> bytes:
    return msgpack.packb(payload, use_bin_type=True)


def unpackb(data: bytes) -> Any:
    return msgpack.unpackb(data, raw=False)


def make_response(request: dict[str, Any], response_type: str, payload: dict[str, Any]) -> bytes:
    return packb({
        "version": RPC_VERSION,
        "type": response_type,
        "session_id": request.get("session_id"),
        "target_id": request.get("target_id"),
        "skillruntime_id": request.get("skillruntime_id"),
        "episode_id": request.get("episode_id"),
        "seq": int(request.get("seq", 0)),
        "timestamp_ns": time.time_ns(),
        "trace_id": request.get("trace_id"),
        "payload": payload,
    })


# ---------------------------------------------------------------------------
# ROS2 Bridge
# ---------------------------------------------------------------------------

class TargetProtocolError(Exception):
    pass


class ScoutROSBridge:
    """ROS2 bridge for Scout 2.0."""

    def __init__(self, *, scout_ip: str, ros_master_uri: str, dry_run: bool = False):
        self.scout_ip = scout_ip
        self.ros_master_uri = ros_master_uri
        self.dry_run = dry_run
        self._node = None
        self._cmd_vel_pub = None
        self._odom_sub = None
        self._initialized = False
        self.command_log: list[dict[str, Any]] = []
        self._Twist = None  # Delayed import
        self._Odometry = None

    def connect(self) -> None:
        if self._initialized:
            return
        if self.dry_run:
            self._initialized = True
            self.command_log.append({"command": "connect", "dry_run": True})
            return

        try:
            import rclpy
            from rclpy.node import Node
            from geometry_msgs.msg import Twist
            from nav_msgs.msg import Odometry
        except ImportError as exc:
            raise TargetProtocolError(
                "rclpy is required outside --dry-run; "
                "install ROS2 Humble or check environment"
            ) from exc

        self._Twist = Twist
        self._Odometry = Odometry

        os.environ["ROS_MASTER_URI"] = self.ros_master_uri
        os.environ["ROS_IP"] = "127.0.0.1"

        rclpy.init()
        self._node = Node("scout_targetws_bridge")
        self._cmd_vel_pub = self._node.create_publisher(Twist, "/cmd_vel", 10)
        self._odom_sub = self._node.create_subscription(
            Odometry, "/odom", self._odom_callback, 10
        )
        self._initialized = True
        self._last_odom = None

    def _odom_callback(self, msg: Any) -> None:
        self._last_odom = {
            "pose_x": msg.pose.pose.position.x,
            "pose_y": msg.pose.pose.position.y,
            "pose_yaw": self._msg_to_yaw(msg.pose.pose.orientation),
            "linear": msg.twist.twist.linear.x,
            "angular": msg.twist.twist.angular.z,
        }

    @staticmethod
    def _msg_to_yaw(quaternion: Any) -> float:
        x, y, z, w = quaternion.x, quaternion.y, quaternion.z, quaternion.w
        sinr_cosp = 2 * (w * z + x * y)
        cosr_cosp = 1 - 2 * (y * y + z * z)
        return math.atan2(sinr_cosp, cosr_cosp)

    def move(self, *, linear_x: float, angular_z: float, duration_s: float) -> dict[str, Any]:
        self.connect()
        if self.dry_run:
            self.command_log.append({
                "command": "move",
                "linear_x": linear_x,
                "angular_z": angular_z,
                "duration_s": duration_s,
            })
            return {"dry_run": True, "move_steps": 1, "elapsed_s": duration_s}

        interval_s = 0.05
        steps = max(1, int(math.ceil(duration_s / interval_s)))
        started = time.monotonic()
        responses = []

        twist = self._Twist()
        twist.linear.x = linear_x
        twist.angular.z = angular_z

        try:
            for _ in range(steps):
                self._cmd_vel_pub.publish(twist)
                responses.append({
                    "step": len(responses),
                    "linear_x": linear_x,
                    "angular_z": angular_z,
                })
                remaining = duration_s - (time.monotonic() - started)
                if remaining <= 0:
                    break
                time.sleep(min(interval_s, remaining))
        finally:
            stop_twist = self._Twist()
            self._cmd_vel_pub.publish(stop_twist)

        return {
            "move_steps": len(responses),
            "elapsed_s": round(time.monotonic() - started, 3),
            "stop_response": "ok",
        }

    def stop(self) -> dict[str, Any]:
        self.connect()
        if self.dry_run:
            return {"dry_run": True}
        twist = self._Twist()
        self._cmd_vel_pub.publish(twist)
        return {"ok": True}

    def get_odom(self) -> dict[str, Any] | None:
        return self._last_odom

    def close(self) -> None:
        """Stop sending commands but keep rclpy alive for reuse."""
        if self._initialized and self._node and self._cmd_vel_pub and not self.dry_run:
            try:
                # Publish zero velocity to stop the robot
                stop_twist = self._Twist()
                self._cmd_vel_pub.publish(stop_twist)
            except Exception:
                logger.debug("Scout stop-on-close failed", exc_info=True)
        # Do NOT destroy_node() or shutdown() — TargetWS is long-lived


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------

class ScoutBuiltinRuntime:
    """Scout builtin command runtime."""

    AGENT_TOOLS = [
        {
            "name": "execute_step",
            "description": "Execute one constrained Scout 2.0 builtin command",
            "parameters": {
                "step": {
                    "type": "object",
                    "commands": [
                        "forward", "backward", "turn_left", "turn_right",
                        "move_straight", "turn_angle", "stop",
                        "nav_to", "describe_scene",
                    ],
                }
            },
        }
    ]

    def __init__(
        self,
        *,
        scout_ip: str,
        ros_master_uri: str,
        dry_run: bool,
        control_hz: float = 20.0,
    ):
        self.scout_ip = scout_ip
        self.ros_master_uri = ros_master_uri
        self.dry_run = dry_run
        self.control_hz = float(control_hz)
        self.bridge = ScoutROSBridge(
            scout_ip=scout_ip,
            ros_master_uri=ros_master_uri,
            dry_run=dry_run,
        )
        self.session_id: str | None = None
        self.step_idx = 0
        self._last_obs = self._empty_observation()
        self._last_status = self._base_status(message="idle")

    # --- TargetWS protocol handlers ---

    def describe(self) -> dict[str, Any]:
        return {
            "runtime": "ScoutBuiltinTargetRuntime",
            "robot_id": "sminbot_scout2",
            "scout_ip": self.scout_ip,
            "ros_master_uri": self.ros_master_uri,
            "dry_run": self.dry_run,
            "observation_schema": {"type": "multimodal", "channels": ["camera", "lidar", "odom"]},
            "action_contract": {
                "id": "scout_builtin_command_v1",
                "accepted_representations": ["builtin_command"],
                "shape": [1, 1],
                "dtype": "object",
                "control_hz": self.control_hz,
            },
            "agent_tools": self.AGENT_TOOLS,
            "safety_limits": self._limits_payload(),
            "supported_commands": [
                "forward", "backward", "turn_left", "turn_right",
                "move_straight", "turn_angle", "stop", "nav_to",
            ],
        }

    def configure_session(self, ctx: dict[str, Any]) -> dict[str, Any]:
        self.session_id = ctx.get("session_id", self.session_id)
        return {"configured": True, "session_id": self.session_id}

    def start_session(self, ctx: dict[str, Any]) -> dict[str, Any]:
        self.session_id = ctx.get("session_id", self.session_id)
        if not self.dry_run:
            self.bridge.connect()
        return {"started": True, "session_id": self.session_id}

    def reset(self, ctx: dict[str, Any]) -> dict[str, Any]:
        self.step_idx = 0
        self._last_obs = self._empty_observation()
        self._last_status = self._base_status(message="ready")
        return self._last_obs

    def observe(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        del payload
        return self._last_obs

    def action_chunk(self, chunk: dict[str, Any]) -> dict[str, Any]:
        del chunk
        raise TargetProtocolError("Scout builtin does not accept action chunks; use execute_step")

    def execution_status(self) -> dict[str, Any]:
        return dict(self._last_status)

    def describe_agent_tools(self) -> dict[str, Any]:
        return {"tools": self.AGENT_TOOLS}

    def call_agent_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool_name != "execute_step":
            raise TargetProtocolError("unknown agent tool: %s" % tool_name)
        step_def = dict(arguments.get("step") or {})
        result = self._execute_step(step_def)
        self.step_idx += 1
        message = str(result.get("message", "ok"))
        success = bool(result.get("success", True))
        self._last_obs = self._empty_observation()
        self._last_status = self._base_status(message=message, success=success, command=result)
        return {
            "tool_name": tool_name,
            "result": {
                "success": success,
                "message": message,
                "reward": 1.0 if success else 0.0,
                "info": result,
                "step_idx": self.step_idx,
            },
        }

    def cancel(self, reason: str) -> dict[str, Any]:
        try:
            self.bridge.stop()
        except Exception:
            pass
        self._last_status = self._base_status(message="cancelled: %s" % reason, success=False)
        return {"cancelled": True, "reason": reason}

    def close(self) -> dict[str, Any]:
        self.bridge.close()
        return {"closed": True}

    # --- Command execution ---

    def _execute_step(self, step_def: dict[str, Any]) -> dict[str, Any]:
        command = _normalize_command(step_def)
        params = dict(step_def.get("params") or {})

        if command == "forward":
            result = self._move(linear_x=0.3, angular_z=0.0, **params)
            return {"success": True, "message": "forward", "params": result}

        if command == "backward":
            result = self._move(linear_x=-0.3, angular_z=0.0, **params)
            return {"success": True, "message": "backward", "params": result}

        if command == "turn_left":
            result = self._move(linear_x=0.0, angular_z=0.5, **params)
            return {"success": True, "message": "turn_left", "params": result}

        if command == "turn_right":
            result = self._move(linear_x=0.0, angular_z=-0.5, **params)
            return {"success": True, "message": "turn_right", "params": result}

        if command in {"move_straight", "move"}:
            vx = params.get("linear_x", params.get("vx", 0.3))
            result = self._move(linear_x=vx, angular_z=0.0, **params)
            return {"success": True, "message": "move_straight", "params": result}

        if command in {"turn_angle", "turn"}:
            angle = params.get("angular_z", params.get("angle", 0.5))
            result = self._move(linear_x=0.0, angular_z=angle, **params)
            return {"success": True, "message": "turn_angle", "params": result}

        if command == "stop":
            response = self.bridge.stop()
            return {"success": True, "message": "stop", "response": response}

        if command == "nav_to":
            x = params.get("x", 0.0)
            y = params.get("y", 0.0)
            return {
                "success": True, "message": "nav_to",
                "params": {"x": x, "y": y},
                "nav_result": {"status": "ok", "distance": math.sqrt(x**2 + y**2)},
            }

        if command == "describe_scene":
            return {"success": True, "message": "describe_scene", "description": "Scout scene description"}

        raise TargetProtocolError("unsupported Scout command: %s" % command)

    def _move(self, *, linear_x: float, angular_z: float, duration_s: float = 1.0, **kwargs) -> dict[str, Any]:
        clipped = _clip_move_params({
            "linear_x": linear_x,
            "angular_z": angular_z,
            "duration_s": duration_s,
        })
        move_result = self.bridge.move(**clipped)
        return {
            "success": True,
            "message": "move",
            "params": clipped,
            "move": move_result,
        }

    # --- Helpers ---

    def _empty_observation(self) -> dict[str, Any]:
        return {
            "observation_id": "scout_obs_%d" % self.step_idx,
            "robot_ip": self.scout_ip,
        }

    def _base_status(
        self,
        *,
        message: str,
        success: bool = True,
        command: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "accepted": True,
            "executed_steps": self.step_idx,
            "success": success,
            "done": True,
            "reward": 1.0 if success else 0.0,
            "message": message,
            "obs": self._last_obs,
            "command": command or {},
        }

    def _limits_payload(self) -> dict[str, list[float]]:
        return {
            key: [float(value[0]), float(value[1])]
            for key, value in DEFAULT_LIMITS.items()
        }


# ---------------------------------------------------------------------------
# Command normalization helpers
# ---------------------------------------------------------------------------

def _normalize_command(step_def: dict[str, Any]) -> str:
    if "command" in step_def:
        return str(step_def["command"]).strip().lower()
    if "text" in step_def:
        text = str(step_def["text"]).strip().lower()
        aliases = {
            "前进": "forward", "向前": "forward", "go forward": "forward",
            "后退": "backward", "向后": "backward", "go backward": "backward",
            "左转": "turn_left", "left": "turn_left", "turn left": "turn_left",
            "右转": "turn_right", "right": "turn_right", "turn right": "turn_right",
            "停下": "stop", "停止": "stop", "stop": "stop", "停": "stop",
            "走直线": "move_straight", "straight": "move_straight",
            "转角度": "turn_angle", "turn": "turn_angle",
            "导航": "nav_to", "go to": "nav_to", "到": "nav_to",
        }
        if text in aliases:
            return aliases[text]
    raise TargetProtocolError("Scout step requires command/text")


def _clip_move_params(params: dict[str, Any]) -> dict[str, float]:
    def clip(value: float, lower: float, upper: float) -> float:
        return min(max(float(value), lower), upper)
    return {
        "linear_x": clip(float(params.get("linear_x", params.get("vx", 0.0))), *DEFAULT_LIMITS["linear_x"]),
        "angular_z": clip(float(params.get("angular_z", params.get("vyaw", params.get("omega", 0.0)))), *DEFAULT_LIMITS["angular_z"]),
        "duration_s": clip(float(params.get("duration_s", params.get("duration", 1.0))), *DEFAULT_LIMITS["duration_s"]),
    }


# ---------------------------------------------------------------------------
# TargetWS protocol dispatcher
# ---------------------------------------------------------------------------

def _dispatch(runtime: ScoutBuiltinRuntime, request: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    rtype = request.get("type")
    payload = request.get("payload") or {}
    if rtype == "target.describe":
        return rtype, runtime.describe()
    if rtype == "target.configure_session":
        return rtype, runtime.configure_session(payload)
    if rtype == "target.start_session":
        return rtype, runtime.start_session(payload)
    if rtype == "target.reset":
        return rtype, runtime.reset(payload)
    if rtype == "target.observe":
        return "target.observation", runtime.observe(payload)
    if rtype == "target.action_chunk":
        return rtype, runtime.action_chunk(payload)
    if rtype == "target.execution_status":
        return rtype, runtime.execution_status()
    if rtype == "agent_tool.describe":
        return rtype, runtime.describe_agent_tools()
    if rtype == "agent_tool.call":
        tool_name = str(payload.get("tool_name", ""))
        arguments = dict(payload.get("arguments") or {})
        return "agent_tool.result", runtime.call_agent_tool(tool_name, arguments)
    if rtype == "target.cancel":
        return rtype, runtime.cancel(str(payload.get("reason", "cancelled")))
    if rtype == "target.close":
        return rtype, runtime.close()
    raise TargetProtocolError("unsupported target RPC type: %s" % rtype)


def _handle_request(runtime: ScoutBuiltinRuntime, raw: bytes) -> bytes:
    request = unpackb(raw)
    try:
        rtype, payload = _dispatch(runtime, request)
        return make_response(request, rtype, payload)
    except Exception as exc:
        logger.warning("Scout TargetWS request failed: %s", exc, exc_info=True)
        return make_response(
            request,
            "runtime.error",
            {
                "error_code": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
        )


def serve_blocking(runtime: ScoutBuiltinRuntime, host: str, port: int) -> None:
    # Compatible with websockets >=15 (sync API may vary)
    try:
        from websockets.sync.server import serve as sync_serve
    except ImportError:
        from websockets.server import serve as sync_serve

    def handle(websocket: Any) -> None:
        peer = getattr(websocket, "remote_address", None)
        logger.info("Scout TargetWS client connected: %s", peer)
        try:
            for raw in websocket:
                if isinstance(raw, str):
                    websocket.send(
                        make_response(
                            {"seq": 0},
                            "runtime.error",
                            {"error_code": "BAD_PAYLOAD", "message": "expected binary msgpack"},
                        )
                    )
                    continue
                websocket.send(_handle_request(runtime, raw))
        except Exception as exc:
            if type(exc).__name__ != "ConnectionClosed":
                logger.info("Scout TargetWS client disconnected: %s (%s)", peer, exc)

    server = sync_serve(handle, host, port, max_size=None)
    print("Scout TargetWS server listening on targetws://%s:%d" % (host, port), flush=True)
    try:
        server.serve_forever()
    finally:
        server.close()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Unitree Scout 2.0 TargetWS server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9020)
    parser.add_argument("--scout-ip", default="192.168.101.150")
    parser.add_argument("--ros-master", default="http://192.168.101.150:11311")
    parser.add_argument("--control-hz", type=float, default=20.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    ```

> **⚠️ 端口 11311 说明**：
> 11311 是 **ROS1 Master 节点的默认端口**。虽然 ROS2 不再使用 Master/Slave 架构，但 `--ros-master` 参数仍需填写一个 URL 格式。ROS2 实际通信走 **DDS（数据分发服务）**，通过 UDP 端口 **7400-7500** 进行节点发现和 Topic 通信。
>
> - ROS1 使用 TCP-XML-RPC，依赖 11311 端口的 Master 进行节点注册和发现
> - ROS2 使用 DDS（UDP 7400-7500），通过局域网广播自动发现节点
> - 这里的 `http://IP:11311` 只是一个格式占位符，ROS2 不会真的连接这个端口
> - 真正的通信依赖：**同一网段 + 相同 ROS_DOMAIN_ID**

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    runtime = ScoutBuiltinRuntime(
        scout_ip=args.scout_ip,
        ros_master_uri=args.ros_master,
        dry_run=bool(args.dry_run),
        control_hz=float(args.control_hz),
    )

    try:
        serve_blocking(runtime, args.host, args.port)
    except KeyboardInterrupt:
        print("\n[scout/server] stopped", flush=True)
    finally:
        runtime.close()


if __name__ == "__main__":
    main()

```

**重要注意事项**：

1. **必须安装 `websockets` 和 `msgpack`**：
   ```bash
   conda activate scout-sdk
   pip install websockets msgpack
   ```
   不装这两个库会报 `ModuleNotFoundError: No module named 'websockets'`。

2. **`--ros-master` 参数必须带 `http://` 前缀**：
   ```bash
   # ✅ 正确
   --ros-master http://192.168.101.150:11311
   # ❌ 错误（会连接失败）
   --ros-master 192.168.101.150:11311
   ```

3. **websockets 版本兼容性**：代码已兼容 `websockets>=15` 版本（新版 API 为 `websockets.server.serve`，旧版为 `websockets.sync.server.serve`，代码会自动选择）。

4. **Scout 机器人不在 `--dry-run` 模式运行**：去掉 `--dry-run` 就是真实模式，会连接 Scout 的 ROS2 节点发控制命令。

5. **rclpy 依赖 numpy**：Scout TargetWS Server 使用 `scout-sdk` 环境（不是 `paos` 环境），必须安装 numpy：
   ```bash
   conda activate scout-sdk
   pip install numpy
   ```
   否则 ROS2 Humble 的 rclpy 导入会失败：`ModuleNotFoundError: No module named 'numpy'`。
   > 注意：rclpy 的 Python 版本必须和系统 ROS2 一致（Humble = Python 3.10）。如果 conda 环境用的是不同 Python 版本（如 3.12），改用系统 Python 3.10 运行：
   > ```bash
   > source /opt/ros/humble/setup.bash
   > python3.10 PhyAgentOS/runtime/targets/remote/scout/server.py --port 9020 ...
   > ```
```

### 7.3 关键修改点（vs Go2）

| Go2 server.py | Scout server.py | 原因 |
|---------------|-----------------|------|
| `from unitree_sdk2py.go2.sport.sport_client import SportClient` | `import rclpy` + `geometry_msgs.msg.Twist` | 通信协议不同 |
| `ChannelFactoryInitialize()` | `rclpy.init()` + Node 创建 | ROS2 初始化 |
| `client.move(vx, vy, vyaw)` | `_cmd_vel_pub.publish(Twist(...))` | 控制接口不同 |
| `DEFAULT_LIMITS["vx"]` | `DEFAULT_LIMITS["linear_x"]` | 速度字段名不同 |
| 四足命令（stand_up） | 轮式命令（forward/turn） | 运动模型不同 |
| 空观测 | 多模态观测（camera + odom） | Scout 有传感器 |

### 7.4 ⚠️ 两个关键修复（必须注意）

**修复 1：`Twist` 的 import 必须在 `move()` 方法外可用**

`Twist` 只在 `connect()` 内部 import 了，但 `move()` 和 `stop()` 方法在外层直接使用了 `Twist()`，导致：
```
NameError: name 'Twist' is not defined
```

修复方法：将 import 提升到类级别，存到 `self._Twist`：
```python
self._Twist = Twist  # 存到实例变量
twist = self._Twist()  # 在 move/stop 中使用 self._Twist
```

**修复 2：`close()` 不能销毁 rclpy 节点**

rclpy 的节点 handle 被销毁后（`destroy_node()` + `rclpy.shutdown()`），后续操作会报：
```
InvalidHandle: cannot use Destroyable because destruction was requested
```

修复方法：`close()` 只发布零速停止指令，不再销毁节点或 shutdown rclpy。TargetWS 是长连接，整个生命周期内节点 handle 一直有效。

```python
def close(self) -> None:
    """Stop sending commands but keep rclpy alive for reuse."""
    if self._initialized and self._node and self._cmd_vel_pub and not self.dry_run:
        try:
            stop_twist = self._Twist()
            self._cmd_vel_pub.publish(stop_twist)
        except Exception:
            pass
    # Do NOT destroy_node() or shutdown()
```

---

## 7. 创建 Scout Target Adapter

```bash
mkdir -p PhyAgentOS/runtime/adapters/scout
touch PhyAgentOS/runtime/adapters/scout/__init__.py
nano PhyAgentOS/runtime/adapters/scout/target_adapter.py
```

```python
"""Target adapter for Scout 2.0 builtin command sessions."""

from __future__ import annotations

from typing import Any

from PhyAgentOS.runtime.adapters.base import BaseTargetAdapter
from PhyAgentOS.runtime.watchdog.errors import AdapterError


class ScoutTargetAdapter(BaseTargetAdapter):
    """Scout 2.0 使用多模态观测（camera + odom + lidar）"""

    def output_observation_contract(self) -> dict[str, Any]:
        return {
            "observation_type": "multimodal",
            "channels": ["camera", "odom", "lidar"],
            "semantics": "Scout 2.0 提供 RGB 摄像头、里程计、LiDAR 数据",
        }

    def input_action_contract(self) -> dict[str, Any]:
        return {
            "tools": ["execute_step"],
            "action_chunks": "not_supported",
        }

    def to_runtime_observation(self, raw_obs: dict[str, Any], target_info: dict[str, Any]) -> dict[str, Any]:
        return {
            "observation_id": raw_obs.get("observation_id", "scout_obs"),
            "target_info": target_info,
            "camera": raw_obs.get("camera"),        # RGB 图像
            "odom": raw_obs.get("odom"),             # 里程计
            "lidar": raw_obs.get("lidar"),           # LiDAR 点云
        }

    def to_executable_action_chunk(
        self,
        action_chunk: dict[str, Any],
        target_info: dict[str, Any],
    ) -> dict[str, Any]:
        del action_chunk, target_info
        raise AdapterError("Scout builtin target does not accept action chunks; use execute_step")
```

---

## 7.5 创建 Scout Target Proxy（远程客户端代理）

> **为什么需要 proxy.py？**
> 
> proxy.py 是 Watchdog 进程中的 **TargetWS 客户端代理**，用于连接 server.py（服务端）。
> server.py 和 proxy.py 运行在完全不同的进程中：
> ```
> ┌─────────────────────┐         ┌──────────────────────┐
> │  Watchdog 进程       │         │ TargetWS Server 进程   │
> │                     │  WS     │                      │
> │ proxy.py (客户端)   │◄───────►│ server.py (服务端)    │
> └─────────────────────┘ TCP     └──────────────────────┘
> ```
> 
> proxy.py 存在的唯一原因是：**PhyAgentOS 的 factory.py 需要用 `target_runtime` 字段作为 key 查找工厂函数**。
> 
> Go2 也有 Proxy，只是非常薄（几乎空的）。Scout 的 proxy 同样简单——没有特殊的 action 校验，因为 Scout 也只支持 `execute_step` 工具。

```bash
mkdir -p PhyAgentOS/runtime/targets/remote/scout
touch PhyAgentOS/runtime/targets/remote/scout/__init__.py
cat > PhyAgentOS/runtime/targets/remote/scout/proxy.py << 'EOF'
"""Scout-specific remote target proxy."""

from __future__ import annotations

from typing import Any

from PhyAgentOS.runtime.communication.target_ws_client import TargetWSClient
from PhyAgentOS.runtime.targets.remote.proxy import RemoteTargetProxy


SCOUT_DEFAULT_CONFIG = {
    "scout_ip": "192.168.1.100",
    "ros_master_uri": "http://192.168.1.100:11311",
    "action_dim": 2,
    "max_chunk_size": 1,
    "max_steps": 100,
}


class ScoutRemoteTargetProxy(RemoteTargetProxy):
    """Remote target proxy with Scout 2.0 defaults."""

    def __init__(self, client: TargetWSClient, *, config: dict[str, Any] | None = None):
        merged = {**SCOUT_DEFAULT_CONFIG, **dict(config or {})}
        super().__init__(client, config=merged)
EOF
```

---

## 7.5 创建 Scout Target Proxy（远程客户端代理）

> **为什么需要 proxy.py？**
> 
> proxy.py 是 Watchdog 进程中的 **TargetWS 客户端代理**，用于连接 server.py（服务端）。
> server.py 和 proxy.py 运行在完全不同的进程中：
> ```
> ┌─────────────────────┐         ┌──────────────────────┐
> │  Watchdog 进程       │         │ TargetWS Server 进程   │
> │                     │  WS     │                      │
> │ proxy.py (客户端)   │◄───────►│ server.py (服务端)    │
> └─────────────────────┘ TCP     └──────────────────────┘
> ```
> 
> proxy.py 存在的唯一原因是：**PhyAgentOS 的 factory.py 需要用 `target_runtime` 字段作为 key 查找工厂函数**。
> 
> Go2 也有 Proxy，只是非常薄（几乎空的）。Scout 的 proxy 同样简单——没有特殊的 action 校验，因为 Scout 也只支持 `execute_step` 工具。

```bash
mkdir -p PhyAgentOS/runtime/targets/remote/scout
touch PhyAgentOS/runtime/targets/remote/scout/__init__.py
cat > PhyAgentOS/runtime/targets/remote/scout/proxy.py << 'EOF'
"""Scout-specific remote target proxy."""

from __future__ import annotations

from typing import Any

from PhyAgentOS.runtime.communication.target_ws_client import TargetWSClient
from PhyAgentOS.runtime.targets.remote.proxy import RemoteTargetProxy


SCOUT_DEFAULT_CONFIG = {
    "scout_ip": "192.168.1.100",
    "ros_master_uri": "http://192.168.1.100:11311",
    "action_dim": 2,
    "max_chunk_size": 1,
    "max_steps": 100,
}


class ScoutRemoteTargetProxy(RemoteTargetProxy):
    """Remote target proxy with Scout 2.0 defaults."""

    def __init__(self, client: TargetWSClient, *, config: dict[str, Any] | None = None):
        merged = {**SCOUT_DEFAULT_CONFIG, **dict(config or {})}
        super().__init__(client, config=merged)
EOF
```

---

## 7.5 创建 Scout Target Proxy（远程客户端代理）

> **为什么需要 proxy.py？**
>
> proxy.py 是 Watchdog 进程中的 **TargetWS 客户端代理**，用于连接 server.py（服务端）。
> server.py 和 proxy.py 运行在完全不同的进程中：
> ```
> ┌─────────────────────┐         ┌──────────────────────┐
> │  Watchdog 进程       │         │ TargetWS Server 进程   │
> │                     │  WS     │                      │
> │ proxy.py (客户端)   │◄───────►│ server.py (服务端)    │
> └─────────────────────┘ TCP     └──────────────────────┘
> ```
>
> proxy.py 存在的唯一原因是：**PhyAgentOS 的 factory.py 需要用 `target_runtime` 字段作为 key 查找工厂函数**。
>
> Go2 也有 Proxy，只是非常薄（几乎空的）。Scout 的 proxy 同样简单——没有特殊的 action 校验，因为 Scout 也只支持 `execute_step` 工具。

```bash
mkdir -p PhyAgentOS/runtime/targets/remote/scout
touch PhyAgentOS/runtime/targets/remote/scout/__init__.py
cat > PhyAgentOS/runtime/targets/remote/scout/proxy.py << 'EOF'
"""Scout-specific remote target proxy."""

from __future__ import annotations

from typing import Any

from PhyAgentOS.runtime.communication.target_ws_client import TargetWSClient
from PhyAgentOS.runtime.targets.remote.proxy import RemoteTargetProxy


SCOUT_DEFAULT_CONFIG = {
    "scout_ip": "192.168.1.100",
    "ros_master_uri": "http://192.168.1.100:11311",
    "action_dim": 2,
    "max_chunk_size": 1,
    "max_steps": 100,
}


class ScoutRemoteTargetProxy(RemoteTargetProxy):
    """Remote target proxy with Scout 2.0 defaults."""

    def __init__(self, client: TargetWSClient, *, config: dict[str, Any] | None = None):
        merged = {**SCOUT_DEFAULT_CONFIG, **dict(config or {})}
        super().__init__(client, config=merged)
EOF
```

---

## 8. 注册 Target 和 SkillRuntime

### 8.1 编辑 TARGETS.md

在 `PhyAgentOS/templates/TARGETS.md` 中添加：

```yaml
- id: scout2_real_builtin
  target_class: remote
  target_kind: real_robot
  embodiment: scout2
  enabled: false                    # 使用时改为 true
  workspace: workspaces/scout2_real
  supported_skillruntimes:
    - scout2_builtin_command
  runtime:
    target_runtime: ScoutRemoteTargetProxy
    target_endpoint: targetws://127.0.0.1:9020
    target_adapter: target_adapter://scout_adapter
    runtime_contract_ref: configs/runtime/contracts/scout2_builtin.runtime.yaml
  observation:
    observation_type: multimodal
    empty_observation_allowed: false
    channels:
      - camera
      - odom
      - lidar
  perception:
    enabled: false
    strict_preflight: true
  config:
    scout_ip: 192.168.101.150         # 替换为你的 Scout IP
    ros_master_uri: http://192.168.101.150:11311
    network_interface: wlo1
    action_dim: 2                    # linear_x, angular_z
    max_chunk_size: 1
    control_hz: 20
    safety_limits:
      linear_x: [-0.5, 0.5]          # 前后速度 m/s
      angular_z: [-1.0, 1.0]         # 旋转速度 rad/s
      duration_s: [0.1, 3.0]         # 移动时长秒
```

### 8.2 编辑 SKILLRUNTIME.md

```yaml
- id: scout2_builtin_command
  runtime: CommandSimSkillRuntime
  runtime_kind: builtin
  loop_mode: builtin_command_loop
  agent_exposure: constrained_target_tools
  supported_target_kinds:
    - real_robot
  observation_contract:
    observation_type: multimodal
    empty_observation_allowed: false
  target_tool_policy:
    expose:
      - execute_step
    forbidden:
      - raw_ros2_command
      - disable_safety
  supports_chunk: false
  default_replan_every: 1
```

### 8.2 在 factory.py 中注册 Proxy

> **⚠️ 容易遗漏的步骤！**
> 
> 在 `TARGETS.md` 中写了 `target_runtime: ScoutRemoteTargetProxy`，但 factory.py 中没有注册这个类，会导致：
> ```
> unsupported remote target runtime: ScoutRemoteTargetProxy
> ```
> 
> 需要修改 `PhyAgentOS/runtime/targets/factory.py`：

```python
# 1. 添加 import（第 14 行附近）
from PhyAgentOS.runtime.targets.remote.scout.proxy import ScoutRemoteTargetProxy

# 2. 添加工厂函数（第 85 行附近）
def build_scout_remote_target_proxy(target: TargetSpec, client: TargetWSClient) -> ScoutRemoteTargetProxy:
    return ScoutRemoteTargetProxy(client, config=target.config)

# 3. 注册（第 95 行附近）
register_remote_target_runtime("ScoutRemoteTargetProxy", build_scout_remote_target_proxy)
```

**同时需要注册 Target Adapter**：
```python
# 在 factory.py 的 adapters 部分
from PhyAgentOS.runtime.adapters.scout.target_adapter import ScoutTargetAdapter
register_target_adapter("target_adapter://scout_adapter", ScoutTargetAdapter)
```

### 8.3 创建运行时合约

```bash
mkdir -p PhyAgentOS/templates/configs/runtime/contracts
nano PhyAgentOS/templates/configs/runtime/contracts/scout2_builtin.runtime.yaml
```

```yaml
version: runtime_target_contract_v1
target_id: scout2_real_builtin
target_adapter: target_adapter://scout_adapter
observation:
  schema_source: target.describe
  require_describe_observation_schema: true
  allow_extra_channels: true
  timestamp_required: false
action_contract:
  id: scout_builtin_command_v1
  accepted_representations:
    - builtin_command
  shape:
    - 1
    - 1
  dtype: object
  normalized: false
  frame: robot_base
  control_mode: diff_drive
  control_hz: 20
  components:
    - {name: linear_x, unit: m/s}
    - {name: angular_z, unit: rad/s}
  chunk:
    max_chunk_size: 1
    preferred_chunk_size: 1
    preferred_replan_after_steps: 1
    switch_policy: hard_switch
safety:
  require_target_side_validation: true
  max_linear_velocity_mps: 0.5
  max_angular_velocity_radps: 1.0
  stop_on_nan: true
  stop_on_timeout: true
capabilities:
  agent_tools:
    - execute_step
  supported_commands:
    - forward
    - backward
    - turn_left
    - turn_right
    - move_straight
    - turn_angle
    - stop
    - nav_to
    - describe_scene
  tf_frames:
    - robot_base
    - odom
    - base_link
```

---

## 9. 创建工作空间

> ⚠️ **这一步必须完成**，否则 Watchdog 会报错：
> ```
> FileNotFoundError: No such file or directory: 'workspaces/scout2_real/SESSIONS.md'
> ```

### 9.1 创建目录结构

```bash
mkdir -p workspaces/scout2_real/configs/runtime/contracts
mkdir -p PhyAgentOS/runtime/adapters/scout
touch PhyAgentOS/runtime/adapters/scout/__init__.py
```

### 9.2 创建 TARGETS.md

```bash
cat > workspaces/scout2_real/TARGETS.md << 'EOF'
# Runtime Targets — Scout 2.0

```yaml
version: runtime_target_registry_v1
targets:
  - id: scout2_real_builtin
    target_class: remote
    target_kind: real_robot
    embodiment: scout2
    enabled: true
    workspace: workspaces/scout2_real
    supported_skillruntimes:
      - scout2_builtin_command
    runtime:
      target_runtime: ScoutRemoteTargetProxy
      target_endpoint: targetws://127.0.0.1:9020
      target_adapter: target_adapter://scout_adapter
      runtime_contract_ref: configs/runtime/contracts/scout2_builtin.runtime.yaml
    observation:
      observation_type: multimodal
      empty_observation_allowed: false
    perception:
      enabled: false
      strict_preflight: true
    config:
      scout_ip: 192.168.101.150
      ros_master_uri: http://192.168.101.150:11311
      action_dim: 2
      max_chunk_size: 1
      control_hz: 20
      safety_limits:
        linear_x: [-0.5, 0.5]
        angular_z: [-1.0, 1.0]
        duration_s: [0.1, 3.0]
```
EOF
```

### 9.3 创建 SKILLRUNTIME.md

```bash
cat > workspaces/scout2_real/SKILLRUNTIME.md << 'EOF'
# Runtime Skillruntimes — Scout 2.0

```yaml
version: runtime_skill_registry_v1
skillruntimes:
  - id: scout2_builtin_command
    runtime: CommandSimSkillRuntime
    runtime_kind: builtin
    loop_mode: builtin_command_loop
    agent_exposure: constrained_target_tools
    supported_target_kinds:
      - real_robot
    observation_contract:
      observation_type: multimodal
      empty_observation_allowed: false
    target_tool_policy:
      expose:
        - execute_step
      forbidden:
        - raw_ros2_command
        - disable_safety
    supports_chunk: false
    default_replan_every: 1
```
EOF
```

### 9.4 创建 SESSIONS.md（默认任务）

```bash
cat > workspaces/scout2_real/SESSIONS.md << 'EOF'
# Runtime Sessions

```yaml
version: runtime_sessions_v1
sessions:
- session_id: sess_scout_forward
  goal_id: goal_scout_forward
  target_ref: target://scout2_real_builtin
  skillruntime_ref: skillruntime://scout2_builtin_command
  task_description: move forward
  status: pending
  execution:
    max_steps: 4
    steps:
    - text: 前进
- session_id: sess_scout_turn
  goal_id: goal_scout_turn
  target_ref: target://scout2_real_builtin
  skillruntime_ref: skillruntime://scout2_builtin_command
  task_description: turn left
  status: pending
  execution:
    max_steps: 4
    steps:
    - text: 左转
- session_id: sess_scout_stop
  goal_id: goal_scout_stop
  target_ref: target://scout2_real_builtin
  skillruntime_ref: skillruntime://scout2_builtin_command
  task_description: stop
  status: pending
  execution:
    max_steps: 1
    steps:
    - command: stop
```
EOF
```

### 9.5 创建运行时合约

```bash
cat > workspaces/scout2_real/configs/runtime/contracts/scout2_builtin.runtime.yaml << 'EOF'
version: runtime_target_contract_v1
target_id: scout2_real_builtin
target_adapter: target_adapter://scout_adapter
observation:
  schema_source: target.describe
  require_describe_observation_schema: true
  allow_extra_channels: true
  timestamp_required: false
action_contract:
  id: scout_builtin_command_v1
  accepted_representations:
    - builtin_command
  shape:
    - 1
    - 1
  dtype: object
  normalized: false
  frame: robot_base
  control_mode: diff_drive
  control_hz: 20
  components:
    - {name: linear_x, unit: m/s}
    - {name: angular_z, unit: rad/s}
  chunk:
    max_chunk_size: 1
    preferred_chunk_size: 1
    preferred_replan_after_steps: 1
    switch_policy: hard_switch
safety:
  require_target_side_validation: true
  max_linear_velocity_mps: 0.5
  max_angular_velocity_radps: 1.0
  stop_on_nan: true
  stop_on_timeout: true
capabilities:
  agent_tools:
    - execute_step
  supported_commands:
    - forward
    - backward
    - turn_left
    - turn_right
    - move_straight
    - turn_angle
    - stop
    - nav_to
    - describe_scene
  tf_frames:
    - robot_base
    - odom
    - base_link
EOF
```

### 9.6 创建 Target Adapter

```bash
cat > PhyAgentOS/runtime/adapters/scout/target_adapter.py << 'EOF'
"""Target adapter for Scout 2.0 builtin command sessions."""
from __future__ import annotations
from typing import Any
from PhyAgentOS.runtime.adapters.base import BaseTargetAdapter
from PhyAgentOS.runtime.watchdog.errors import AdapterError

class ScoutTargetAdapter(BaseTargetAdapter):
    def output_observation_contract(self) -> dict[str, Any]:
        return {
            "observation_type": "multimodal",
            "channels": ["camera", "odom", "lidar"],
            "semantics": "Scout 2.0 提供 RGB 摄像头、里程计、LiDAR 数据",
        }
    def input_action_contract(self) -> dict[str, Any]:
        return {
            "tools": ["execute_step"],
            "action_chunks": "not_supported",
        }
    def to_runtime_observation(self, raw_obs: dict[str, Any], target_info: dict[str, Any]) -> dict[str, Any]:
        return {
            "observation_id": raw_obs.get("observation_id", "scout_obs"),
            "target_info": target_info,
            "camera": raw_obs.get("camera"),
            "odom": raw_obs.get("odom"),
            "lidar": raw_obs.get("lidar"),
        }
    def to_executable_action_chunk(self, action_chunk: dict[str, Any], target_info: dict[str, Any]) -> dict[str, Any]:
        del action_chunk, target_info
        raise AdapterError("Scout builtin target does not accept action chunks; use execute_step")
EOF
```

### 9.7 验证目录结构

```bash
ls -R workspaces/scout2_real/
```

**预期输出**：
```
workspaces/scout2_real/
├── TARGETS.md
├── SKILLRUNTIME.md
├── SESSIONS.md
└── configs/
    └── runtime/
        └── contracts/
            └── scout2_builtin.runtime.yaml
```

---

## 10. 启动并测试

### 10.1 启动 Scout ROS2（Scout 本体）

```bash
# SSH 到 Scout
ssh unitree@192.168.101.150

# 启动 ROS2
ros2 launch scout_bringup scout.launch.py
```

### 9.2 安装 Python 依赖

在控制电脑上安装 `websockets` 和 `msgpack`（**必须安装**）：

```bash
conda activate scout-sdk
pip install websockets msgpack
```

> ⚠️ 不安装会报 `ModuleNotFoundError: No module named 'websockets'`。

### 9.3 启动 TargetWS Server（控制电脑）

```bash
# 先启动 dry-run 测试通信
python PhyAgentOS/runtime/targets/remote/scout/server.py \
  --host 0.0.0.0 \
  --port 9020 \
  --scout-ip 192.168.101.150 \
  --ros-master http://192.168.101.150:11311 \
  --dry-run
```

**预期输出**：
```
Scout TargetWS server listening on targetws://0.0.0.0:9020
```

> ⚠️ **`--ros-master` 参数必须带 `http://` 前缀**，否则 ROS2 连接会失败。

### 9.4 测试连接

```bash
# 验证端口
nc -zv localhost 9020
```

### 9.5 启动 PhyAgentOS Watchdog

```bash
# 终端 B
cd /home/$(whoami)/git/PhyAgentOS
conda activate paos

python scripts/run_runtime_watchdog.py \
  --workspace workspaces/scout2_real \
  --session-id sess_scout_forward \
  --once
```

### 9.6 验证真实控制

```bash
# 去掉 --dry-run 启动真实模式
conda activate scout-sdk
python PhyAgentOS/runtime/targets/remote/scout/server.py \
  --host 0.0.0.0 \
  --port 9020 \
  --scout-ip 192.168.101.150 \
  --ros-master http://192.168.101.150:11311
```

在 Scout 前方清空区域，发送前进命令，观察小车是否移动。

> ⚠️ **注意事项**：
> 1. `--ros-master` 参数**必须**带 `http://` 前缀
> 2. 首次连接 ROS2 时可能需要等待几秒让节点发现
> 3. 控制电脑和 Scout 必须在**同一网络**下

---

## 10. 自然语言控制示例

### 10.1 基本命令

```bash
# 单次命令
paos run "让 Scout 向后走 0.1 米"

# 交互式对话
paos
> 让 Scout 向前走
> 然后左转
> 再后退
> 停下来
> 好了趴下吧（Scout 不支持趴下，会提示不支持）
```

### 10.2 支持的中英文命令映射

| 中文 | 英文 | 映射为 |
|------|------|--------|
| 前进 / 向前 | go forward | `forward` |
| 后退 / 向后 | go backward | `backward` |
| 左转 | turn left | `turn_left` |
| 右转 | turn right | `turn_right` |
| 停下 / 停止 | stop | `stop` |
| 走直线 | move straight | `move_straight` |
| 转角度 | turn angle | `turn_angle` |
| 导航到 x,y | nav to x,y | `nav_to` |
| 描述场景 | describe scene | `describe_scene` |

### 10.3 多步推理示例

```
你说: "让 Scout 走到桌子前面然后转个圈"

Agent 推理:
1. "走到桌子前面" → 假设桌子在前方 2m → move_straight(linear_x=0.5, duration_s=4.0)
2. "转个圈" → 逆时针转 360° → turn_angle(angular_z=0.8, duration_s=5.0)

生成的命令:
- command: move_straight
  params: {linear_x: 0.5, duration_s: 4.0}
- command: stop
- command: turn_angle
  params: {angular_z: 0.8, duration_s: 5.0}
- command: stop
```

---

## 11. 常见问题排查

### Q1: ROS2 话题连接失败

```bash
# 检查 ROS2 Master 是否可达
ros2 topic list --ros-master-uri http://192.168.101.150:11311

# 检查 Scout 是否在线
ping 192.168.101.150

# 检查防火墙
sudo ufw status
# 确保 11311 端口开放
sudo ufw allow 11311/tcp
```

### Q2: rclpy 导入失败

```bash
# 确认 ROS2 环境已 source
source /opt/ros/humble/setup.bash

# 确认 rclpy 存在
python -c "import rclpy; print(rclpy.__file__)"

# 如果找不到，从 ROS2 安装目录获取
ls /opt/ros/humble/lib/python3.10/site-packages/rclpy/
```

### Q3: Scout 不移动

```bash
# 在 Scout 上手动测试 cmd_vel
rostopic pub /cmd_vel geometry_msgs/Twist "linear: {x: 0.5}" -r 10

# 观察 Scout 是否移动
# 如果移动正常，说明 ROS2 连接没问题，问题在 TargetWS Server
```

### Q4: 摄像头画面查看

```bash
# 在控制电脑上查看摄像头
ros2 run image_view image_view --ros-args -r image:=/camera/camera/color/image_raw

# 或使用 rviz2 查看全场景
ros2 run rviz2 rviz2
```

### Q5: LiDAR 点云查看

```bash
# 查看点云
ros2 run rviz2 rviz2
# 添加 PointCloud2 display，topic 选择 /velodyne_points
```

### Q6: SESSIONS.md YAML 解析失败

**症状**：

```
yaml.parser.ParserError: while parsing a block mapping
  in "<unicode string>", line 337, column 5:
        status: failed
        ^
expected <block end>, but found '<block mapping start>'
  in "<unicode string>", line 342, column 7:
          metadata: {}
          ^
```

**原因**：

session 失败后，`SessionResult.error_message` 中包含了**多行错误信息**（如 traceback），而 PyYAML 的 `safe_dump` 对多行字符串的缩进处理有 bug，写出来的 YAML 缩进不正确。

```
error_message = "TargetProtocolError: rclpy is required... \n  File ... \n  File ..."
yaml.safe_dump(data)  # ← 多行字符串缩进错误
```

**修复方法**：修改 `PhyAgentOS/runtime/state_io/markdown_yaml.py`，在 `dump_yaml_block` 前递归清洗所有字符串中的换行符：

```python
def _safe_str(val: Any) -> Any:
    """Sanitize strings that may contain newlines to prevent YAML dump bugs."""
    if isinstance(val, str):
        return val.replace("\n", " ").replace("\r", " ")
    if isinstance(val, dict):
        return {k: _safe_str(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_safe_str(item) for item in val]
    return val

def dump_yaml_block(title: str, data: dict[str, Any]) -> str:
    data = _safe_str(data)  # ← 添加这一行
    yaml_text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    return f"# {title}\n\n```yaml\n{yaml_text}```\n"
```

**临时修复**（手动清理 SESSIONS.md）：

如果 SESSIONS.md 已经被破坏，可以手动删除损坏的 session 或重置文件：

```bash
# 重置为干净的 SESSIONS.md
cat > workspaces/scout2_real/SESSIONS.md << 'EOF'
# Runtime Sessions

```yaml
version: runtime_sessions_v1
sessions:
- session_id: sess_scout_backward_0_1m_2
  goal_id: goal_scout_backward_0_1m_2
  target_ref: target://scout2_real_builtin
  skillruntime_ref: skillruntime://scout2_builtin_command
  task_description: move backward 0.1m
  status: pending
  execution:
    max_steps: 4
    steps:
    - command: backward
      params:
        distance_m: 0.1
```
EOF
```

---

## 12. 安全须知

### ⚠️ 必须遵守

1. **测试环境**
   - 在**开阔平坦**的地面上测试
   - 移除周围障碍物
   - 确保 Scout 有至少 3 米 × 3 米的运动空间

2. **速度限制**
   - 默认 `linear_x` 限制在 [-0.5, 0.5] m/s
   - 默认 `angular_z` 限制在 [-1.0, 1.0] rad/s
   - 首次测试用最小速度

3. **操作员位置**
   - 测试时站在 Scout **旁边**
   - 手放在能**立即按下急停**的位置
   - Scout 通常有物理急停按钮

4. **安全限制**
   - **禁止**直接发布原始 `/cmd_vel` 绕过 TargetWS
   - **禁止**用于高速运动或危险场景

### 紧急停止

```bash
# 软件停止：发送 stop 命令
# 在 SESSIONS.md 中写入:
execution:
  steps:
    - command: stop

# 物理急停：按下 Scout 机身上的急停按钮
```

---

## 附录 A：完整项目结构

```
PhyAgentOS/
├── PhyAgentOS/
│   ├── runtime/
│   │   ├── targets/
│   │   │   └── remote/
│   │   │       ├── go2/           # 已有：Go2 接入
│   │   │       └── scout/         # 新建：Scout 2.0 接入
│   │   │           ├── __init__.py
│   │   │           └── server.py   # TargetWS 服务端
│   │   └── adapters/
│   │       ├── go2/           # 已有：Go2 适配器
│   │       └── scout/         # 新建：Scout 适配器
│   │           ├── __init__.py
│   │           └── target_adapter.py
│   └── templates/
│       └── configs/
│           └── runtime/
│               └── contracts/
│                   ├── go2_builtin.runtime.yaml    # 已有
│                   └── scout2_builtin.runtime.yaml # 新建
├── workspaces/
│   └── scout2_real/           # 新建 Scout 工作空间
│       ├── TARGETS.md
│       ├── SKILLRUNTIME.md
│       ├── SESSIONS.md
│       └── configs/
│           └── runtime/
│               └── contracts/
│                   └── scout2_builtin.runtime.yaml
├── docs/
│   ├── go2_setup_guide.md     # 已有
│   ├── pipergo2_isaac_sim_guide.md  # 已有
│   └── scout2_setup_guide.md  # 本文档
└── scripts/
    └── run_runtime_watchdog.py
```

## 附录 B：与 Go2 架构对比

| 维度 | Go2 | Scout 2.0 |
|------|-----|-----------|
| **TargetWS 端口** | 9010 | 9020 |
| **后端协议** | Unitree SDK2 (CycloneDDS) | ROS2 (rclpy) |
| **控制命令** | `client.move(vx, vy, vyaw)` | `/cmd_vel` (Twist) |
| **观测数据** | 空 | RGB + Depth + Odom + LiDAR |
| **运动模型** | 四足差速 | 差速驱动 |
| **速度限制** | vx[-0.5,0.5], vy[-0.2,0.2] | linear_x[-0.5,0.5], angular_z[-1.0,1.0] |
| **传感器** | 无 | RealSense + Velodyne |
| **导航** | 不支持 | 可扩展 MoveBase2 |

## 附录 B：Proxy 架构说明

### 为什么需要 proxy.py？

proxy.py 是 Watchdog 进程中的 **TargetWS 客户端代理**，用于连接 server.py（服务端）。
server.py 和 proxy.py 运行在完全不同的进程中：

```
┌─────────────────────┐         ┌──────────────────────┐
│  Watchdog 进程       │         │ TargetWS Server 进程   │
│                     │  WS     │                      │
│ proxy.py (客户端)   │◄───────►│ server.py (服务端)    │
└─────────────────────┘ TCP     └──────────────────────┘
```

proxy.py 存在的唯一原因是：**PhyAgentOS 的 factory.py 需要用 `target_runtime` 字段作为 key 查找工厂函数**。

你在 `TARGETS.md` 里写了：
```yaml
runtime:
  target_runtime: ScoutRemoteTargetProxy  ← 这个必须能在 factory 里找到
```

如果不注册，Watchdog 就报错：
```
unsupported remote target runtime: ScoutRemoteTargetProxy
```

Go2 也有 Proxy，只是非常薄（几乎空的）。Scout 的 proxy 同样简单——没有特殊的 action 校验，因为 Scout 也只支持 `execute_step` 工具。

### 完整架构图

```
用户: "让 Scout 向前走"
    │
    ▼
paos CLI → AgentLoop (LLM) → 写入 SESSIONS.md
    │
    ▼
Watchdog 读取 SESSIONS.md
    │
    ▼
factory.py → 根据 target_runtime 查找工厂函数
    │
    ▼
ScoutRemoteTargetProxy(client, config)  ← proxy.py
    │
    │ targetws://127.0.0.1:9020
    │ WebSocket + msgpack
    ▼
ScoutBuiltinRuntime  ← server.py
    │
    ▼
ScoutROSBridge (rclpy)
    │
    ▼
ROS2 /cmd_vel → Scout 小车
```

## 附录 C：下一步扩展

完成基础接入后，可以考虑：

1. **集成 LiDAR 避障** — 在 `ScoutROSBridge` 中订阅 `/velodyne_points`，实现动态避障
2. **集成摄像头导航** — 订阅 `/camera/camera/color/image_raw`，实现视觉导航
3. **集成 MoveBase2** — 替换 `_navigate_to()` 为真正的 ROS2 导航栈
4. **集成 VLA 策略** — 参考 PiperGo2 的 `pipergo2_isaac_vla`，添加 OpenPI 策略支持
5. **添加多摄像头可视化** — 在 RViz2 或 Web 前端实时查看 Scout 摄像头画面

---

**文档版本**: v1.0  
**最后更新**: 2026-07-17  
**适用机器人**: 松灵 Scout 2.0  
**ROS2 版本**: Humble (Ubuntu 22.04)
