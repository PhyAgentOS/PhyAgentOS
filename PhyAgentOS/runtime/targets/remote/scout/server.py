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
