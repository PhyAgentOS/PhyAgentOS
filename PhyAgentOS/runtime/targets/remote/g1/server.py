"""Standalone TargetWS server for Unitree G1 builtin commands.

Run this in an environment that has unitree_sdk2py installed. The server speaks
the same msgpack-over-WebSocket TargetWS protocol used by the PhyAgentOS runtime.
"""

from __future__ import annotations

import argparse
import logging
import math
import time
import traceback
from typing import Any

import msgpack

RPC_VERSION = "phyagentos.runtime_rpc.v2"
logger = logging.getLogger(__name__)

DEFAULT_LIMITS = {
    "vx": (-0.8, 0.8),
    "vy": (-0.2, 0.2),
    "vyaw": (-0.5, 0.5),
}
SDK_OK = 0


class TargetProtocolError(Exception):
    """Raised when an RPC or command payload is invalid."""


def packb(payload: Any) -> bytes:
    return msgpack.packb(payload, use_bin_type=True)


def unpackb(data: bytes) -> Any:
    return msgpack.unpackb(data, raw=False)


def make_response(request: dict[str, Any], response_type: str, payload: dict[str, Any]) -> bytes:
    return packb(
        {
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
        }
    )


class G1LocoBackend:
    """Thin wrapper around Unitree LocoClient."""

    def __init__(self, *, network_interface: str, robot_ip: str, dry_run: bool = False):
        self.network_interface = network_interface
        self.robot_ip = robot_ip
        self.dry_run = dry_run
        self._client = None
        self._initialized = False
        self.command_log: list[dict[str, Any]] = []

    def connect(self) -> None:
        if self._initialized:
            return
        if self.dry_run:
            self._initialized = True
            self.command_log.append({"command": "connect", "dry_run": True})
            return
        try:
            from unitree_sdk2py.core.channel import ChannelFactoryInitialize
            from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
        except ModuleNotFoundError as exc:
            raise TargetProtocolError(
                "unitree_sdk2py/cyclonedds is required outside --dry-run; "
                "install it in the G1 TargetWS environment"
            ) from exc
        ChannelFactoryInitialize(0, self.network_interface)
        client = LocoClient()
        client.SetTimeout(10.0)
        client.Init()
        ret = client.SwitchToUserCtrl()
        if ret != 0 and not self.dry_run:
            logger.warning("SwitchToUserCtrl returned error code %d", ret)
        self._client = client
        self._initialized = True

    def squat2stand(self) -> Any:
        self.connect()
        return self._call("Squat2StandUp")

    def balance_stand(self, balance_mode: int = 1) -> Any:
        self.connect()
        return self._call("BalanceStand", balance_mode)

    def lie2stand(self) -> Any:
        self.connect()
        return self._call("Lie2StandUp")

    def stand2squat(self) -> Any:
        self.connect()
        return self._call("StandUp2Squat")

    def sit(self) -> Any:
        self.connect()
        return self._call("Sit")

    def damp(self) -> Any:
        self.connect()
        return self._call("Damp")

    def zero_torque(self) -> Any:
        self.connect()
        return self._call("ZeroTorque")

    def stop_move(self) -> Any:
        self.connect()
        return self._call("StopMove")

    def set_velocity(
        self, vx: float, vy: float, omega: float, duration: float = 1.0
    ) -> Any:
        self.connect()
        return self._call_raw_set_velocity(vx, vy, omega, duration)

    def move(self, *, vx: float, vy: float, vyaw: float, duration_s: float) -> dict[str, Any]:
        self.connect()
        response = self._call_raw_set_velocity(vx, vy, vyaw, duration_s)
        return {
            "move_steps": 1,
            "elapsed_s": round(duration_s, 3),
            "responses": [_safe_response(response)],
            "stop_response": None,
        }

    def close(self) -> None:
        if self._initialized:
            try:
                self.stop_move()
            except Exception:
                logger.debug("G1 stop during close failed", exc_info=True)

    def _call_raw_set_velocity(
        self, vx: float, vy: float, omega: float, duration: float
    ) -> Any:
        record = {
            "command": "SetVelocity",
            "args": [vx, vy, omega, duration],
            "dry_run": self.dry_run,
        }
        self.command_log.append(record)
        if self.dry_run:
            return {"dry_run": True, "method": "SetVelocity", "args": [vx, vy, omega, duration]}
        if self._client is None:
            raise TargetProtocolError("G1 LocoClient is not initialized")
        response = self._client.SetVelocity(vx, vy, omega, duration)
        record["response"] = _safe_response(response)
        logger.info("G1 SetVelocity args=%s response=%s", [vx, vy, omega, duration], record["response"])
        return response

    def _call(self, method_name: str, *args: Any) -> Any:
        record = {"command": method_name, "args": list(args), "dry_run": self.dry_run}
        self.command_log.append(record)
        if self.dry_run:
            return {"dry_run": True, "method": method_name, "args": list(args)}
        if self._client is None:
            raise TargetProtocolError("G1 LocoClient is not initialized")
        method = getattr(self._client, method_name)
        response = method(*args)
        record["response"] = _safe_response(response)
        logger.info("G1 SDK call %s args=%s response=%s", method_name, list(args), record["response"])
        return response


class G1ArmBackend:
    """Thin wrapper around Unitree G1ArmActionClient."""

    ACTION_MAP = {
        "release_arm": 99,
        "two_hand_kiss": 11,
        "left_kiss": 12,
        "right_kiss": 13,
        "hands_up": 15,
        "clap": 17,
        "high_five": 18,
        "hug": 19,
        "heart": 20,
        "right_heart": 21,
        "reject": 22,
        "right_hand_up": 23,
        "x_ray": 24,
        "face_wave": 25,
        "high_wave": 26,
        "shake_hand": 27,
    }

    def __init__(self, *, network_interface: str, robot_ip: str, dry_run: bool = False):
        self.network_interface = network_interface
        self.robot_ip = robot_ip
        self.dry_run = dry_run
        self._client = None
        self._initialized = False
        self.command_log: list[dict[str, Any]] = []

    def connect(self) -> None:
        if self._initialized:
            return
        if self.dry_run:
            self._initialized = True
            self.command_log.append({"command": "connect", "dry_run": True})
            return
        try:
            from unitree_sdk2py.core.channel import ChannelFactoryInitialize
            from unitree_sdk2py.g1.arm.g1_arm_action_client import G1ArmActionClient
        except ModuleNotFoundError as exc:
            raise TargetProtocolError(
                "unitree_sdk2py/cyclonedds is required outside --dry-run; "
                "install it in the G1 TargetWS environment"
            ) from exc
        ChannelFactoryInitialize(0, self.network_interface)
        client = G1ArmActionClient()
        client.SetTimeout(10.0)
        client.Init()
        self._client = client
        self._initialized = True

    def execute_arm_action(self, action_id: int) -> Any:
        self.connect()
        record = {"command": "ExecuteAction", "action_id": action_id, "dry_run": self.dry_run}
        self.command_log.append(record)
        if self.dry_run:
            return {"dry_run": True, "method": "ExecuteAction", "action_id": action_id}
        if self._client is None:
            raise TargetProtocolError("G1 ArmActionClient is not initialized")
        response = self._client.ExecuteAction(action_id)
        record["response"] = _safe_response(response)
        logger.info("G1 ExecuteAction action_id=%s response=%s", action_id, record["response"])
        return response

    def close(self) -> None:
        pass  # Arm client has no explicit cleanup method


# ─── Helper utilities ───────────────────────────────────────────────


def _safe_response(response: Any) -> Any:
    if response is None or isinstance(response, (bool, int, float, str)):
        return response
    if isinstance(response, (list, tuple)):
        return [_safe_response(item) for item in response]
    if isinstance(response, dict):
        return {str(key): _safe_response(value) for key, value in response.items()}
    return repr(response)


def _float_param(params: dict[str, Any], name: str, default: float) -> float:
    value = params.get(name, default)
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise TargetProtocolError("G1 parameter %s must be numeric" % name) from exc
    if not math.isfinite(result):
        raise TargetProtocolError("G1 parameter %s must be finite" % name)
    return result


def _clip(value: float, lower: float, upper: float) -> float:
    return min(max(float(value), lower), upper)


def _raise_for_sdk_error(command: str, response: Any) -> None:
    if isinstance(response, int) and response != SDK_OK:
        raise TargetProtocolError("G1 SDK command %s returned error code %d" % (command, response))


# ─── Runtime classes ────────────────────────────────────────────────


class G1ArmActionRuntime:
    """Handles arm preset gesture commands."""

    AGENT_TOOLS = [
        {
            "name": "execute_arm_action",
            "description": "Execute a preset arm gesture on the G1 robot",
            "parameters": {
                "action": {
                    "type": "string",
                    "enum": sorted(G1ArmBackend.ACTION_MAP.keys()),
                    "description": "Name of the preset gesture to execute",
                }
            },
        }
    ]

    def __init__(self, *, backend: G1ArmBackend, g1_info: dict[str, Any]):
        self._backend = backend
        self._g1_info = g1_info

    def execute_step(self, step_def: dict[str, Any]) -> dict[str, Any]:
        action_name = _normalize_arm_action(step_def)
        if action_name not in G1ArmBackend.ACTION_MAP:
            raise TargetProtocolError(
                "unknown arm action: %s. Available: %s"
                % (action_name, ", ".join(sorted(G1ArmBackend.ACTION_MAP.keys())))
            )
        action_id = G1ArmBackend.ACTION_MAP[action_name]
        response = self._backend.execute_arm_action(action_id)
        _raise_for_sdk_error("ExecuteAction(%s)" % action_name, response)
        return {
            "success": True,
            "message": "arm_action:%s" % action_name,
            "action_name": action_name,
            "action_id": action_id,
            "info": {"g1": self._g1_info},
        }

    def describe_agent_tools(self) -> dict[str, Any]:
        return {"tools": self.AGENT_TOOLS}


def _normalize_arm_action(step_def: dict[str, Any]) -> str:
    if "action" in step_def:
        return str(step_def["action"]).strip().lower().replace(" ", "_")
    if "text" in step_def:
        text = str(step_def["text"]).strip().lower()
        aliases = {k.replace("_", " "): k for k in G1ArmBackend.ACTION_MAP}
        if text in aliases:
            return aliases[text]
    raise TargetProtocolError("arm action requires action/text field")


class G1BuiltinRuntime:
    AGENT_TOOLS = [
        {
            "name": "execute_step",
            "description": "Execute one constrained Unitree G1 builtin loco or arm gesture command",
            "parameters": {
                "step": {
                    "type": "object",
                    "commands": [
                        # Loco posture commands
                        "squat2stand",
                        "balance_stand",
                        "lie2stand",
                        "stand2squat",
                        "sit",
                        "damp",
                        "zero_torque",
                        "stop_move",
                        # Velocity control
                        "move",
                        # Arm gesture alias (falls through to arm tool)
                        "arm_action",
                    ],
                }
            },
        }
    ]

    ARM_COMMANDS = {
        "release_arm", "two_hand_kiss", "left_kiss", "right_kiss",
        "hands_up", "clap", "high_five", "hug", "heart", "right_heart",
        "reject", "right_hand_up", "x_ray", "face_wave", "high_wave", "shake_hand",
    }

    def __init__(
        self,
        *,
        network_interface: str,
        robot_ip: str,
        dry_run: bool,
        control_hz: float = 10.0,
    ):
        self.network_interface = network_interface
        self.robot_ip = robot_ip
        self.dry_run = dry_run
        self.control_hz = float(control_hz)
        self.loco_backend = G1LocoBackend(
            network_interface=network_interface,
            robot_ip=robot_ip,
            dry_run=dry_run,
        )
        self.arm_backend = G1ArmBackend(
            network_interface=network_interface,
            robot_ip=robot_ip,
            dry_run=dry_run,
        )
        self.g1_info: dict[str, Any] = {
            "robot_ip": robot_ip,
            "network_interface": network_interface,
            "dry_run": dry_run,
        }
        self.session_id: str | None = None
        self.step_idx = 0
        self._last_obs = self._empty_observation()
        self._last_status = self._base_status(message="idle")
        self._arm_runtime = G1ArmActionRuntime(
            backend=self.arm_backend,
            g1_info=self.g1_info,
        )

    # ─── Session lifecycle ────────────────────────────────────────

    def describe(self) -> dict[str, Any]:
        return {
            "runtime": "G1BuiltinTargetRuntime",
            "robot_id": "unitree_g1",
            "robot_ip": self.robot_ip,
            "network_interface": self.network_interface,
            "dry_run": self.dry_run,
            "observation_schema": {"type": "empty"},
            "action_contract": {
                "id": "g1_builtin_command_v1",
                "accepted_representations": ["builtin_command"],
                "shape": [1, 1],
                "dtype": "object",
                "control_hz": self.control_hz,
            },
            "agent_tools": self.AGENT_TOOLS,
            "safety_limits": self._limits_payload(),
            "arm_tools": [
                {
                    "name": "ArmActionRuntime.execute_arm_action",
                    "description": "Execute a preset arm gesture",
                }
            ],
        }

    def configure_session(self, ctx: dict[str, Any]) -> dict[str, Any]:
        self._merge_ctx(ctx)
        return {"configured": True, "session_id": self.session_id, "g1": self._metadata()}

    def start_session(self, ctx: dict[str, Any]) -> dict[str, Any]:
        self._merge_ctx(ctx)
        if not self.dry_run:
            self.loco_backend.connect()
        return {"started": True, "session_id": self.session_id, "g1": self._metadata()}

    def reset(self, ctx: dict[str, Any]) -> dict[str, Any]:
        self._merge_ctx(ctx)
        self.step_idx = 0
        self._last_obs = self._empty_observation()
        self._last_status = self._base_status(message="ready")
        return self._last_obs

    def observe(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        del payload
        return self._last_obs

    def action_chunk(self, chunk: dict[str, Any]) -> dict[str, Any]:
        del chunk
        raise TargetProtocolError("G1 builtin target does not accept action chunks; use execute_step")

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

    def call_arm_action(self, action_name: str) -> dict[str, Any]:
        result = self._arm_runtime.execute_step({"action": action_name})
        self.step_idx += 1
        message = str(result.get("message", "ok"))
        success = bool(result.get("success", True))
        self._last_obs = self._empty_observation()
        self._last_status = self._base_status(message=message, success=success, command=result)
        return {
            "tool_name": "execute_arm_action",
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
            self.loco_backend.stop_move()
        except Exception:
            pass
        finally:
            self._last_status = self._base_status(message="cancelled: %s" % reason, success=False)
        return {"cancelled": True, "reason": reason}

    def close(self) -> dict[str, Any]:
        self.loco_backend.close()
        self.arm_backend.close()
        return {"closed": True}

    # ─── Command dispatcher ───────────────────────────────────────

    def _execute_step(self, step_def: dict[str, Any]) -> dict[str, Any]:
        command = _normalize_command(step_def)
        params = dict(step_def.get("params") or {})

        # ── Loco posture commands ──────────────────────────────────
        if command == "squat2stand":
            response = self.loco_backend.squat2stand()
            return _step_result("squat2stand", response)
        if command == "balance_stand":
            mode = int(params.get("balance_mode", 1))
            response = self.loco_backend.balance_stand(mode)
            return _step_result("balance_stand", response)
        if command == "lie2stand":
            response = self.loco_backend.lie2stand()
            return _step_result("lie2stand", response)
        if command in {"stand2squat"}:
            response = self.loco_backend.stand2squat()
            return _step_result("stand2squat", response)
        if command == "sit":
            response = self.loco_backend.sit()
            return _step_result("sit", response)
        if command == "damp":
            response = self.loco_backend.damp()
            return _step_result("damp", response)
        if command == "zero_torque":
            response = self.loco_backend.zero_torque()
            return _step_result("zero_torque", response)
        if command == "stop_move":
            response = self.loco_backend.stop_move()
            return _step_result("stop_move", response)

        # ── Arm gesture commands ─────────────────────────────────────
        if command in self.ARM_COMMANDS:
            action_id = G1ArmBackend.ACTION_MAP[command]
            response = self.arm_backend.execute_arm_action(action_id)
            _raise_for_sdk_error("ExecuteAction(%s)" % command, response)
            return {
                "success": True,
                "message": "arm_action:%s" % command,
                "action_name": command,
                "action_id": action_id,
            }

        # ── Velocity control ───────────────────────────────────────
        if command == "move":
            if "params" not in step_def or not isinstance(step_def.get("params"), dict):
                raise TargetProtocolError("G1 move command requires params.vx/params.vy/params.vyaw/params.step")
            clipped = _clip_move_params(params)
            move_result = self.loco_backend.move(**clipped)
            # Wait for the actual movement duration before stopping
            duration_s = clipped.get("duration_s", 0.5)
            time.sleep(duration_s)
            try:
                self.loco_backend.stop_move()
            except Exception:
                pass
            return {
                "success": True,
                "message": "move",
                "params": clipped,
                "move": move_result,
            }

        raise TargetProtocolError("unsupported G1 command: %s" % command)

    def _merge_ctx(self, ctx: dict[str, Any]) -> None:
        self.session_id = ctx.get("session_id", self.session_id)

    def _empty_observation(self) -> dict[str, Any]:
        return {
            "observation_id": "g1_obs_%d" % self.step_idx,
            "g1": self._metadata(),
        }

    def _metadata(self) -> dict[str, Any]:
        return {
            "robot_ip": self.robot_ip,
            "network_interface": self.network_interface,
            "dry_run": self.dry_run,
            "step_index": self.step_idx,
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
            "buffered_steps": 0,
            "executed_steps": self.step_idx,
            "target_step_index": self.step_idx,
            "need_replan": False,
            "safety_status": "ok" if success else "stopped",
            "success": success,
            "done": True,
            "reward": 1.0 if success else 0.0,
            "message": message,
            "obs": self._last_obs,
            "g1": self._metadata(),
            "command": command or {},
        }

    @staticmethod
    def _limits_payload() -> dict[str, list[float]]:
        return {key: [float(lo), float(hi)] for key, (lo, hi) in DEFAULT_LIMITS.items()}


# ─── Command normalization ──────────────────────────────────────────


def _normalize_command(step_def: dict[str, Any]) -> str:
    if "command" in step_def:
        return str(step_def["command"]).strip().lower()
    if "text" in step_def:
        text = str(step_def["text"]).strip().lower()
        aliases = {
            "sit down": "sit",
            "蹲下": "sit",
            "坐下": "sit",
            "squat": "sit",
            "lie2stand": "lie2stand",
            "lie to stand": "lie2stand",
            "趴下起身": "lie2stand",
            "squat2stand": "squat2stand",
            "squat to stand": "squat2stand",
            "蹲起": "squat2stand",
            "stand2squat": "stand2squat",
            "站立蹲下": "stand2squat",
            "balance stand": "balance_stand",
            "平衡站立": "balance_stand",
            "stop": "stop_move",
            "停止": "stop_move",
            "damp": "damp",
            "阻尼": "damp",
            "zero torque": "zero_torque",
            "零扭矩": "zero_torque",
        }
        if text in aliases:
            return aliases[text]
        for cmd in G1BuiltinRuntime.ARM_COMMANDS:
            if text in {cmd, cmd.replace("_", " ")}:
                return cmd
    if "mode" in step_def and str(step_def["mode"]).strip().lower() == "move":
        return "move"
    raise TargetProtocolError("G1 step requires command/text/mode")


def _clip_move_params(params: dict[str, Any]) -> dict[str, float]:
    step = _float_param(params, "step", _float_param(params, "duration_s", _float_param(params, "duration", 0.5)))
    return {
        "vx": _clip(_float_param(params, "vx", 0.0), *DEFAULT_LIMITS["vx"]),
        "vy": _clip(_float_param(params, "vy", 0.0), *DEFAULT_LIMITS["vy"]),
        "vyaw": _clip(_float_param(params, "vyaw", 0.0), *DEFAULT_LIMITS["vyaw"]),
        "duration_s": _clip(step, 0.1, 2.0),
    }


def _step_result(message: str, response: Any) -> dict[str, Any]:
    _raise_for_sdk_error(message, response)
    return {"success": True, "message": message, "response": _safe_response(response)}


# ─── TargetWS dispatch ──────────────────────────────────────────────


def _dispatch(runtime: G1BuiltinRuntime, request: dict[str, Any]) -> tuple[str, dict[str, Any]]:
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
        if tool_name == "execute_arm_action":
            action_name = str(arguments.get("action") or arguments.get("step", {}).get("action", "")).strip().lower().replace(" ", "_")
            return "agent_tool.result", runtime.call_arm_action(action_name)
        return "agent_tool.result", runtime.call_agent_tool(tool_name, arguments)
    if rtype == "target.cancel":
        return rtype, runtime.cancel(str(payload.get("reason", "cancelled")))
    if rtype == "target.close":
        return rtype, runtime.close()
    raise TargetProtocolError("unsupported target RPC type: %s" % rtype)


def _handle_request(runtime: G1BuiltinRuntime, raw: bytes) -> bytes:
    request = unpackb(raw)
    try:
        rtype, payload = _dispatch(runtime, request)
        return make_response(request, rtype, payload)
    except Exception as exc:
        logger.warning("G1 TargetWS request failed: %s", exc, exc_info=True)
        return make_response(
            request,
            "runtime.error",
            {
                "error_code": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
        )


def serve_blocking(runtime: G1BuiltinRuntime, host: str, port: int) -> None:
    from websockets.sync.server import serve as sync_serve

    def handle(websocket: Any) -> None:
        peer = getattr(websocket, "remote_address", None)
        logger.info("G1 TargetWS client connected: %s", peer)
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
                logger.info("G1 TargetWS client disconnected: %s (%s)", peer, exc)

    with sync_serve(handle, host, port, max_size=None) as server:
        print("G1 TargetWS server listening on targetws://%s:%d" % (host, port), flush=True)
        server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Unitree G1 TargetWS server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9030)
    parser.add_argument("--network-interface", default="enp4s0")
    parser.add_argument("--robot-ip", default="192.168.137.1")
    parser.add_argument("--control-hz", type=float, default=10.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    runtime = G1BuiltinRuntime(
        network_interface=args.network_interface,
        robot_ip=args.robot_ip,
        dry_run=bool(args.dry_run),
        control_hz=float(args.control_hz),
    )
    try:
        serve_blocking(runtime, args.host, args.port)
    except KeyboardInterrupt:
        print("\n[g1/server] stopped", flush=True)
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
