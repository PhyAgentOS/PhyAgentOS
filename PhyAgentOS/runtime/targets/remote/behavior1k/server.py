"""Standalone TargetWS server backed by BEHAVIOR-1K / OmniGibson simulation.

Runs in the ``behavior`` conda env (Python 3.10 + Isaac Sim + OmniGibson).
Does NOT import PhyAgentOS. Speaks TargetWS msgpack-over-websocket.

Launch (behavior env, from repo root):

  bash external/b1k_bench/scripts/start_behavior1k_server.sh --gui --port 9004

Or:

  python PhyAgentOS/runtime/targets/remote/behavior1k/server.py --gui --port 9004
"""

from __future__ import annotations

import argparse
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
    if not isinstance(obj, dict):
        return obj
    is_ndarray = obj.get("__ndarray__") or obj.get(b"__ndarray__")
    is_npgeneric = obj.get("__npgeneric__") or obj.get(b"__npgeneric__")
    if is_ndarray:
        data = obj.get("data", obj.get(b"data"))
        if isinstance(data, str):
            data = data.encode("latin1")
        dtype = obj.get("dtype", obj.get(b"dtype"))
        shape = obj.get("shape", obj.get(b"shape"))
        return np.ndarray(buffer=data, dtype=np.dtype(dtype), shape=shape)
    if is_npgeneric:
        data = obj.get("data", obj.get(b"data"))
        dtype = obj.get("dtype", obj.get(b"dtype"))
        return np.dtype(dtype).type(data)
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


def _dispatch(runtime: Any, request: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
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
    """Sync TargetWS server; OmniGibson RPC runs on the main thread queue."""

    def __init__(self, runtime: Any):
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


def serve_blocking(host: str, port: int, config: Dict[str, Any]) -> None:
    _dir = Path(__file__).resolve().parent
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))
    from eval_runtime import Behavior1KRealRuntime

    runtime = Behavior1KRealRuntime(config)
    server = TargetWsServer(runtime)
    ws_thread = threading.Thread(
        target=_run_targetws_server,
        args=(server, host, port),
        name="behavior1k-targetws",
        daemon=True,
    )
    ws_thread.start()
    print("BEHAVIOR-1K TargetWS server listening on targetws://%s:%d" % (host, port), flush=True)
    try:
        server.run_main_loop()
    except KeyboardInterrupt:
        server._shutdown.set()
        print("\n[behavior1k/server] stopped", flush=True)
    finally:
        if not runtime.config.get("close_sim_on_shutdown", False):
            print("[behavior1k/server] keeping OmniGibson alive until process exit", flush=True)


def _bootstrap_isaac_env(*, headless: bool, display: str | None, isaac_path: str, behavior1k_root: str | None) -> None:
    """Set Isaac / OmniGibson runtime env vars before importing og."""
    import os
    import sys
    from pathlib import Path

    _dir = Path(__file__).resolve().parent
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))
    from env_bootstrap import apply_behavior1k_process_env

    apply_behavior1k_process_env(
        isaac_path=isaac_path,
        behavior1k_root=behavior1k_root,
        headless=headless,
        display=display,
    )

    from omnigibson.learning.utils.config_utils import register_omegaconf_resolvers
    from omnigibson.macros import gm

    register_omegaconf_resolvers()
    gm.HEADLESS = headless


def main() -> None:
    parser = argparse.ArgumentParser(description="BEHAVIOR-1K TargetWS server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9004)
    parser.add_argument("--task-name", default="turning_on_radio")
    parser.add_argument("--instance-id", type=int, default=0)
    parser.add_argument("--max-steps", type=int, default=200)
    parser.add_argument("--gui", action="store_true")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--display", default=None)
    parser.add_argument(
        "--isaac-path",
        default=None,
        help="Isaac Sim install root (default: B1K_ISAAC_PATH or /home/zyserver/isaacsim3)",
    )
    parser.add_argument(
        "--behavior1k-root",
        default=None,
        help="BEHAVIOR-1K checkout root (default: BEHAVIOR1K_ROOT or ~/work/BEHAVIOR-1K)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    headless = bool(args.headless) and not args.gui
    isaac_path = args.isaac_path or __import__("os").environ.get("B1K_ISAAC_PATH", "/home/zyserver/isaacsim3")
    _bootstrap_isaac_env(
        headless=headless,
        display=args.display,
        isaac_path=isaac_path,
        behavior1k_root=args.behavior1k_root,
    )

    config = {
        "task_name": args.task_name,
        "instance_id": args.instance_id,
        "max_steps": args.max_steps,
        "headless": headless,
        "close_sim_on_shutdown": False,
    }
    serve_blocking(args.host, args.port, config)


if __name__ == "__main__":
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    main()
