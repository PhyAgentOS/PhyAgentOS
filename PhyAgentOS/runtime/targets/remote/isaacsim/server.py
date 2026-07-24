"""Standalone TargetWS server backed by Isaac Sim rollout (InternUtopia).

Runs in the Isaac/InternUtopia conda environment. Does NOT import PhyAgentOS
(pydantic/py3.11+ would conflict). Speaks TargetWS msgpack-over-websocket.

Launch (Isaac env, from repo root):

  python PhyAgentOS/runtime/targets/remote/isaacsim/server.py \\
    --config external/isaac_env/configs/pipergo2_manipulation.json --gui --port 9003

Legacy rollout WS remains available via ``python -m external.rollout --port 8765``.
"""

from __future__ import annotations

import argparse
import json
import logging
import queue
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Dict

import msgpack
import numpy as np

RPC_VERSION = "phyagentos.runtime_rpc.v2"
logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[5]


def _ensure_rollout_import_paths() -> None:
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    ext_root = str(_REPO_ROOT / "external")
    if ext_root not in sys.path:
        sys.path.insert(0, ext_root)


def _pack_array(obj: Any) -> Any:
    if isinstance(obj, (np.ndarray, np.generic)) and obj.dtype.kind in ("V", "O", "c"):
        raise ValueError("Unsupported dtype: %s" % obj.dtype)
    if isinstance(obj, np.ndarray):
        return {
            "__ndarray__": True,
            "data": obj.tobytes(),
            "dtype": obj.dtype.str,
            "shape": obj.shape,
        }
    if isinstance(obj, np.generic):
        return {"__npgeneric__": True, "data": obj.item(), "dtype": obj.dtype.str}
    return obj


def _unpack_array(obj: Dict[Any, Any]) -> Any:
    if obj.get("__ndarray__"):
        return np.ndarray(buffer=obj["data"], dtype=np.dtype(obj["dtype"]), shape=obj["shape"])
    if obj.get("__npgeneric__"):
        return np.dtype(obj["dtype"]).type(obj["data"])
    return obj


def packb(payload: Any) -> bytes:
    return msgpack.packb(payload, use_bin_type=True, default=_pack_array)


def unpackb(data: bytes) -> Any:
    return msgpack.unpackb(data, raw=False, object_hook=_unpack_array)


def make_response(request: Dict[str, Any], response_type: str, payload: Dict[str, Any]) -> bytes:
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


class TargetProtocolError(Exception):
    pass


ISAAC_DEFAULT_CONFIG = {
    "robot_id": "",
    "action_dim": 8,
    "max_chunk_size": 50,
    "max_steps": 600,
    "action_name": "arm_joint_controller",
    "control_wrap": "list",
    "pass_through_control": False,
    "rollout_reset_each_session": False,
    "image_key": "camera1",
    "wrist_image_key": "camera2",
    "third_image_key": "camera3",
    "state_dim": 8,
    "image_size": 224,
}


class IsaacSimRuntime:
    """Isaac Sim target runtime wrapping a rollout runner."""

    AGENT_TOOLS = [
        {
            "name": "execute_step",
            "description": "Execute one language/command/control rollout step",
            "parameters": {"step": "object"},
        }
    ]

    def __init__(self, runner: Any, config: Dict[str, Any] | None = None):
        self.runner = runner
        self.config = dict(ISAAC_DEFAULT_CONFIG)
        self.config.update(config or {})
        self.session_id = None
        self.step_idx = 0
        self.success = False
        self.done = False
        self._total_reward = 0.0
        self._last_obs: Dict[str, Any] | None = None
        self._last_status: Dict[str, Any] = {"accepted": True, "safety_status": "idle", "executed_steps": 0}

    def describe(self) -> Dict[str, Any]:
        return {
            "runtime": "IsaacSimRemoteTargetRuntime",
            "robot_id": self.config.get("robot_id", ""),
            "observation_schema": {
                "images": {"camera1": "uint8 HWC", "camera2": "uint8 HWC"},
                "state": {"dtype": "float32", "shape": [self.config["state_dim"]]},
            },
            "action_contract": {
                "id": "isaac_joint_control_v1",
                "shape": ["T", int(self.config["action_dim"])],
                "dtype": "float32",
                "max_chunk_size": int(self.config["max_chunk_size"]),
            },
            "agent_tools": self.AGENT_TOOLS,
        }

    def configure_session(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        self._merge_ctx(ctx)
        return {"configured": True, "session_id": self.session_id, "isaacsim": self._metadata()}

    def start_session(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        self._merge_ctx(ctx)
        return {"started": True, "session_id": self.session_id, "isaacsim": self._metadata()}

    def reset(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        self._merge_ctx(ctx)
        reset_payload = dict(ctx.get("reset_payload") or {})
        if ctx.get("task_description") and "vla_task_text" not in reset_payload:
            reset_payload.setdefault("vla_task_text", ctx["task_description"])
        if self.config.get("rollout_reset_each_session"):
            reset_payload["force"] = True
        robot_id = str(self.config.get("robot_id", "")).strip()
        if robot_id:
            reset_payload.setdefault("robot_id", robot_id)
        result = self.runner.reset(reset_payload)
        rollout_obs = result.get("obs") if isinstance(result.get("obs"), dict) else result
        self.step_idx = 0
        self.success = False
        self.done = False
        self._total_reward = 0.0
        self._last_obs = self._format_obs(rollout_obs if isinstance(rollout_obs, dict) else {})
        self._last_status = self._base_status(reward=0.0)
        return self._last_obs

    def observe(self, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
        if self._last_obs is None:
            obs = self.runner.observe()
            self._last_obs = self._format_obs(obs.get("obs", obs) if isinstance(obs, dict) else obs)
        return self._last_obs

    def action_chunk(self, chunk: Dict[str, Any]) -> Dict[str, Any]:
        actions = np.asarray(chunk.get("actions"), dtype=np.float32)
        action_dim = int(self.config["action_dim"])
        if actions.ndim != 2 or actions.shape[1] != action_dim:
            raise TargetProtocolError("Isaac expected actions [%s,%d], got %s" % ("T", action_dim, actions.shape))
        max_chunk = int(self.config["max_chunk_size"])
        if actions.shape[0] > max_chunk:
            raise TargetProtocolError("Isaac action chunk too large: %d" % actions.shape[0])

        chunk_reward = 0.0
        for row in actions:
            transition = self.runner.step(self._control_payload(row))
            self.step_idx += 1
            chunk_reward += float(transition.get("reward", 0.0))
            obs = transition.get("obs")
            if isinstance(obs, dict):
                self._last_obs = self._format_obs(obs)
            info = dict(transition.get("info") or {})
            if info.get("success"):
                self.success = True
            if transition.get("done"):
                self.done = True
            if self.step_idx >= int(self.config.get("max_steps", 600)):
                self.done = True
            if self.done:
                break

        self._total_reward += chunk_reward
        self._last_status = self._base_status(reward=chunk_reward, chunk_id=chunk.get("chunk_id"))
        return dict(self._last_status)

    def execution_status(self) -> Dict[str, Any]:
        return dict(self._last_status)

    def describe_agent_tools(self) -> Dict[str, Any]:
        return {"tools": self.AGENT_TOOLS}

    def call_agent_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name != "execute_step":
            raise TargetProtocolError("unknown agent tool: %s" % tool_name)
        step_def = dict(arguments.get("step") or {})
        payload = self._encode_step(step_def)
        transition = self.runner.step(payload)
        self.step_idx += 1
        obs = transition.get("obs")
        if isinstance(obs, dict):
            self._last_obs = self._format_obs(obs)
        info = dict(transition.get("info") or {})
        success = bool(info.get("success", False))
        if str(payload.get("mode", "")).lower() == "control":
            success = True
        message = str(info.get("message", ""))
        reward = float(transition.get("reward", 0.0))
        self._total_reward += reward
        if success:
            self.success = True
        self._last_status = self._base_status(reward=reward)
        return {
            "tool_name": tool_name,
            "result": {
                "success": success,
                "message": message,
                "reward": reward,
                "info": info,
                "step_idx": self.step_idx,
            },
        }

    def cancel(self, reason: str) -> Dict[str, Any]:
        self._last_status = dict(self._last_status)
        self._last_status.update({"cancelled": True, "cancel_reason": reason})
        return {"cancelled": True, "reason": reason}

    def close(self) -> Dict[str, Any]:
        if not self.config.get("close_sim_on_session_end", False):
            return {"closed": False, "kept_alive": True}
        try:
            self.runner.close()
        except Exception:
            pass
        return {"closed": True}

    def tick_idle(self) -> None:
        """Keep physics/GUI alive between TargetWS sessions."""
        tick = getattr(self.runner, "_idle_step_if_due", None)
        if callable(tick):
            tick()

    def _merge_ctx(self, ctx: Dict[str, Any]) -> None:
        self.session_id = ctx.get("session_id", self.session_id)
        isaac_cfg = dict(ctx.get("isaacsim") or {})
        metadata = dict(ctx.get("metadata") or {})
        metadata_isaac = dict(metadata.get("isaacsim") or {})
        self.config.update({**metadata_isaac, **isaac_cfg})

    def _control_payload(self, action: np.ndarray) -> Dict[str, Any]:
        action_name = str(self.config.get("action_name", "arm_joint_controller"))
        wrap = str(self.config.get("control_wrap", "list")).lower()
        robot_id = str(self.config.get("robot_id", "")).strip()
        if self.config.get("pass_through_control"):
            payload: Dict[str, Any] = {"mode": "control", "action": {action_name: [[float(x) for x in action.tolist()]]}}
        elif wrap == "nested_list":
            payload = {"mode": "control", "action": {action_name: [[float(x) for x in action.tolist()]]}}
        else:
            payload = {"mode": "control", "action": {action_name: [action.tolist()]}}
        if robot_id:
            payload["robot_id"] = robot_id
        return payload

    def _encode_step(self, step_def: Dict[str, Any]) -> Dict[str, Any]:
        robot_id = str(self.config.get("robot_id", "")).strip()
        if "mode" in step_def:
            payload = dict(step_def)
        elif "text" in step_def:
            payload = {"mode": "language", "text": str(step_def["text"]).strip()}
        elif "command" in step_def:
            payload = {
                "mode": "command",
                "command": str(step_def["command"]),
                "params": dict(step_def.get("params") or {}),
            }
        elif "action" in step_def and isinstance(step_def["action"], dict):
            payload = {"mode": "control", "action": step_def["action"]}
            if "sim_steps" in step_def:
                payload["sim_steps"] = step_def["sim_steps"]
        else:
            raise TargetProtocolError("unsupported step definition: %r" % step_def)
        if robot_id:
            payload.setdefault("robot_id", robot_id)
        return payload

    def _format_obs(self, rollout_obs: Dict[str, Any]) -> Dict[str, Any]:
        image_size = int(self.config.get("image_size", 224))
        state_dim = int(self.config.get("state_dim", 8))
        image_key = str(self.config.get("image_key", "camera1"))
        wrist_key = str(self.config.get("wrist_image_key", "camera2"))
        third_key = str(self.config.get("third_image_key", "camera3"))

        images = rollout_obs.get("images") or {}
        image = images.get(image_key) or np.zeros((image_size, image_size, 3), dtype=np.uint8)
        wrist = images.get(wrist_key) or np.zeros((image_size, image_size, 3), dtype=np.uint8)
        state = rollout_obs.get("state")
        if state is None:
            state = np.zeros((state_dim,), dtype=np.float32)
        state = np.asarray(state, dtype=np.float32).reshape(-1)
        if state.shape[0] < state_dim:
            padded = np.zeros((state_dim,), dtype=np.float32)
            padded[: state.shape[0]] = state
            state = padded
        else:
            state = state[:state_dim]

        formatted = {
            "observation_id": "isaac_obs_%d" % self.step_idx,
            "images": {
                image_key: np.asarray(image, dtype=np.uint8),
                wrist_key: np.asarray(wrist, dtype=np.uint8),
            },
            "state": state,
            "robot_xy": rollout_obs.get("robot_xy"),
            "scene_description_cn": rollout_obs.get("scene_description_cn"),
            "runtime": rollout_obs.get("runtime"),
        }
        third = images.get(third_key)
        if third is not None:
            formatted["images"][third_key] = np.asarray(third, dtype=np.uint8)
        return formatted

    def _metadata(self) -> Dict[str, Any]:
        return {"robot_id": self.config.get("robot_id", ""), "step_index": self.step_idx}

    def _base_status(self, *, reward: float, chunk_id: str | None = None) -> Dict[str, Any]:
        status = {
            "accepted": True,
            "buffered_steps": 0,
            "executed_steps": self.step_idx,
            "target_step_index": self.step_idx,
            "need_replan": not self.success,
            "safety_status": "ok",
            "success": bool(self.success),
            "done": bool(self.done),
            "reward": reward,
            "obs": self._last_obs,
            "isaacsim": self._metadata(),
        }
        if chunk_id:
            status["chunk_id"] = chunk_id
        return status


def _dispatch(runtime: IsaacSimRuntime, request: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
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


class _PendingRpc:
    __slots__ = ("request", "response_queue")

    def __init__(self, request: Dict[str, Any], response_queue: queue.Queue):
        self.request = request
        self.response_queue = response_queue


class TargetWsServer:
    """Sync TargetWS server; sim RPC runs on the main thread queue."""

    def __init__(self, runtime: IsaacSimRuntime):
        self.runtime = runtime
        self._pending: queue.Queue[_PendingRpc] = queue.Queue()
        self._shutdown = threading.Event()

    def handle(self, websocket: Any) -> None:
        peer = getattr(websocket, "remote_address", None)
        logger.info("TargetWS client connected: %s", peer)
        try:
            for raw in websocket:
                if isinstance(raw, str):
                    err = make_response(
                        {"seq": 0},
                        "runtime.error",
                        {"error_code": "BAD_PAYLOAD", "message": "expected binary msgpack"},
                    )
                    websocket.send(err)
                    continue
                request = unpackb(raw)
                resp_q: queue.Queue = queue.Queue(maxsize=1)
                self._pending.put(_PendingRpc(request, resp_q))
                try:
                    response = resp_q.get(timeout=3600.0)
                except queue.Empty:
                    response = make_response(
                        request,
                        "runtime.error",
                        {"error_code": "TIMEOUT", "message": "sim request timed out on main thread"},
                    )
                websocket.send(response)
        except Exception as exc:
            if type(exc).__name__ != "ConnectionClosed":
                logger.info("TargetWS client disconnected: %s (%s)", peer, exc)

    def run_main_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                pending = self._pending.get(timeout=0.25)
            except queue.Empty:
                self.runtime.tick_idle()
                continue
            request = pending.request
            try:
                rtype, payload = _dispatch(self.runtime, request)
                pending.response_queue.put(make_response(request, rtype, payload))
            except Exception as exc:
                pending.response_queue.put(
                    make_response(
                        request,
                        "runtime.error",
                        {
                            "error_code": type(exc).__name__,
                            "message": str(exc),
                            "traceback": traceback.format_exc(),
                        },
                    )
                )


def _run_targetws_server(server: TargetWsServer, host: str, port: int) -> None:
    from websockets.sync.server import serve as sync_serve

    with sync_serve(server.handle, host, port, max_size=None) as ws_server:
        ws_server.serve_forever()


def serve_blocking(host: str, port: int, config: dict[str, Any], *, gui: bool) -> None:
    _ensure_rollout_import_paths()
    from isaac_env.server import create_runner

    runner = create_runner(config, gui=gui)
    runtime = IsaacSimRuntime(runner, config.get("targetws") or config.get("isaacsim") or {})
    server = TargetWsServer(runtime)
    ws_thread = threading.Thread(
        target=_run_targetws_server,
        args=(server, host, port),
        name="isaac-targetws",
        daemon=True,
    )
    ws_thread.start()
    print("Isaac Sim TargetWS server listening on targetws://%s:%d" % (host, port), flush=True)
    try:
        server.run_main_loop()
    except KeyboardInterrupt:
        server._shutdown.set()
        print("\n[isaacsim/server] stopped", flush=True)
    finally:
        if not runtime.config.get("close_sim_on_shutdown", False):
            print("[isaacsim/server] keeping Isaac Sim alive until process exit", flush=True)
        else:
            try:
                runner.close()
            except Exception:
                pass

def main() -> None:
    parser = argparse.ArgumentParser(description="Isaac Sim TargetWS server")
    parser.add_argument(
        "--config",
        default=str(_REPO_ROOT / "external" / "rollout" / "configs" / "pipergo2_manipulation.json"),
        help="Rollout JSON config",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9003)
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config_path = Path(args.config).expanduser().resolve()
    with config_path.open(encoding="utf-8") as handle:
        config = json.load(handle)

    gui = bool(args.gui) and not args.headless
    _ensure_rollout_import_paths()
    from isaac_env.bootstrap import bootstrap_rollout_process

    bootstrap_rollout_process(config, gui=gui)
    serve_blocking(args.host, args.port, config, gui=gui)


if __name__ == "__main__":
    main()
