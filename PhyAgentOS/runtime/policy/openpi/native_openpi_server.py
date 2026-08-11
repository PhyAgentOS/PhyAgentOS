"""OpenPI-native websocket policy server for official OpenPI checkpoints.

This server loads policies through the official ``openpi`` package and serves
the same msgpack websocket protocol used by ``OpenPIClientPolicyWrapper``.
Use it for OpenPI/Orbax checkpoints that contain ``params/`` instead of
LeRobot checkpoints that contain ``model.safetensors``.
"""

from __future__ import annotations

import argparse
import asyncio
import http
import logging
import time
import traceback
from typing import Any

import numpy as np

from PhyAgentOS.runtime.errors import PolicyProtocolError
from PhyAgentOS.runtime.policy.msgpack_numpy import packb, unpackb

_DEFAULT_LIBERO_CHECKPOINTS = {
    "pi0_libero": "gs://openpi-assets/checkpoints/pi0_libero",
    "pi05_libero": "gs://openpi-assets/checkpoints/pi05_libero",
    "pi0_fast_libero": "gs://openpi-assets/checkpoints/pi0_fast_libero",
}
WEBSOCKET_KEEPALIVE_DISABLED = {
    "ping_interval": None,
    "ping_timeout": None,
}


class NativeOpenPIPolicy:
    """Thin wrapper around official OpenPI trained policies."""

    def __init__(
        self,
        *,
        policy_config: str,
        checkpoint_dir: str | None,
        default_prompt: str | None,
        pytorch_device: str | None,
    ):
        self.policy_config = _normalize_policy_config(policy_config)
        self.checkpoint_dir = checkpoint_dir or _default_checkpoint_for(self.policy_config)
        if not self.checkpoint_dir:
            raise PolicyProtocolError(
                f"checkpoint_dir is required for OpenPI config `{self.policy_config}`; "
                "pass --checkpoint-dir /path/to/checkpoint"
            )

        try:
            from openpi.policies import policy_config as openpi_policy_config
            from openpi.training import config as openpi_train_config
        except ModuleNotFoundError as exc:
            raise SystemExit(
                "Missing official `openpi` package. Run this server in the OpenPI "
                "environment, or add the OpenPI repo to PYTHONPATH."
            ) from exc

        _status("creating trained policy through official OpenPI loader")
        train_config = openpi_train_config.get_config(self.policy_config)
        self.policy = openpi_policy_config.create_trained_policy(
            train_config,
            self.checkpoint_dir,
            default_prompt=default_prompt,
            pytorch_device=pytorch_device,
        )
        _status("policy object created")
        model_config = getattr(train_config, "model", None)
        self.metadata = _msgpack_safe(
            {
                **dict(getattr(self.policy, "metadata", {}) or {}),
                "backend": "openpi_native",
                "policy_config": self.policy_config,
                "checkpoint_dir": self.checkpoint_dir,
                "default_prompt": default_prompt,
                "action_dim": 7 if "libero" in self.policy_config else None,
                "action_horizon": getattr(model_config, "action_horizon", None),
                "model_type": str(getattr(model_config, "model_type", "")) or None,
                "wire_protocol": "openpi_msgpack_numpy",
            }
        )

    def infer(self, observation: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        _validate_observation(observation)
        output = self.policy.infer(observation)
        if not isinstance(output, dict):
            raise PolicyProtocolError(f"OpenPI policy returned non-dict output: {type(output).__name__}")
        if "actions" not in output:
            raise PolicyProtocolError("OpenPI policy output missing `actions`")

        actions = np.asarray(output["actions"], dtype=np.float32)
        if actions.ndim == 1:
            actions = actions[None, :]
        if actions.ndim != 2:
            raise PolicyProtocolError(f"OpenPI `actions` must have shape [A] or [T,A], got {actions.shape}")
        if "libero" in self.policy_config:
            if actions.shape[1] < 7:
                raise PolicyProtocolError(f"LIBERO action output must have at least 7 dims, got {actions.shape}")
            actions = actions[:, :7]

        response = dict(output)
        response["actions"] = np.ascontiguousarray(actions, dtype=np.float32)
        response.setdefault("policy_meta", {})
        response["policy_meta"] = {
            **dict(response["policy_meta"]),
            "backend": "openpi_native",
            "policy_config": self.policy_config,
            "checkpoint_dir": self.checkpoint_dir,
            "policy_latency_ms": (time.perf_counter() - started) * 1000,
            "chunk_size": int(actions.shape[0]),
            "action_dim": int(actions.shape[1]),
        }
        return response


async def serve_policy(policy: NativeOpenPIPolicy, *, host: str, port: int) -> None:
    try:
        import websockets
        import websockets.asyncio.server as websocket_server
    except ModuleNotFoundError as exc:
        raise SystemExit("Missing `websockets`; install OpenPI/PhyAgentOS runtime dependencies.") from exc

    async def handler(websocket):
        await websocket.send(packb(policy.metadata))
        while True:
            try:
                message = await websocket.recv()
                if isinstance(message, str):
                    raise PolicyProtocolError("expected binary msgpack policy request")
                response = policy.infer(unpackb(message))
                await websocket.send(packb(response))
            except websockets.ConnectionClosed:
                break
            except Exception:
                await websocket.send(traceback.format_exc())
                await websocket.close(code=1011, reason="Internal policy server error")
                raise

    async with websocket_server.serve(
        handler,
        host,
        port,
        compression=None,
        max_size=None,
        process_request=_health_check,
        **WEBSOCKET_KEEPALIVE_DISABLED,
    ) as server:
        _status(f"listening on ws://{host}:{port}")
        _status(f"use policy endpoint openpi://{host}:{port} from PAOS")
        _status("health check path: /healthz")
        logging.info("OpenPI native policy server listening on ws://%s:%d", host, port)
        await server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve official OpenPI checkpoints through the PAOS policy wire protocol")
    parser.add_argument(
        "--policy-config",
        "--config",
        default="pi05_libero",
        help="OpenPI training config name, e.g. pi0_libero or pi05_libero",
    )
    parser.add_argument(
        "--checkpoint-dir",
        "--policy-dir",
        "--model-dir",
        default=None,
        help="OpenPI checkpoint directory or gs:// path. Must contain params/ for JAX checkpoints or model.safetensors for PyTorch checkpoints.",
    )
    parser.add_argument("--default-prompt", default=None)
    parser.add_argument("--pytorch-device", default=None, help="Device for PyTorch OpenPI checkpoints, e.g. cuda or cuda:0")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.INFO), force=True)
    normalized_config = _normalize_policy_config(args.policy_config)
    checkpoint_dir = args.checkpoint_dir or _default_checkpoint_for(normalized_config)
    _status("starting PAOS OpenPI native policy server")
    _status(f"policy_config={normalized_config}")
    _status(f"checkpoint_dir={checkpoint_dir or '<required>'}")
    _status(f"default_prompt={args.default_prompt or '<checkpoint default>'}")
    _status(f"pytorch_device={args.pytorch_device or '<OpenPI default>'}")
    _status(f"bind={args.host}:{args.port}")
    _status("loading checkpoint; this can take a while on first start")
    policy = NativeOpenPIPolicy(
        policy_config=args.policy_config,
        checkpoint_dir=args.checkpoint_dir,
        default_prompt=args.default_prompt,
        pytorch_device=args.pytorch_device,
    )
    _status("policy loaded; starting websocket server")
    logging.info("Loaded OpenPI policy: %s", policy.metadata)
    asyncio.run(serve_policy(policy, host=args.host, port=args.port))


def _normalize_policy_config(policy_config: str) -> str:
    aliases = {
        "pi0": "pi0_libero",
        "pi05": "pi05_libero",
        "pi0.5": "pi05_libero",
        "pi0fast": "pi0_fast_libero",
        "pi0_fast": "pi0_fast_libero",
    }
    return aliases.get(policy_config, policy_config)


def _default_checkpoint_for(policy_config: str) -> str | None:
    return _DEFAULT_LIBERO_CHECKPOINTS.get(policy_config)


def _validate_observation(observation: dict[str, Any]) -> None:
    if not isinstance(observation, dict):
        raise PolicyProtocolError(f"policy observation must be a dict, got {type(observation).__name__}")
    required = ("observation/image", "observation/wrist_image", "observation/state")
    missing = [key for key in required if key not in observation]
    if missing:
        raise PolicyProtocolError(f"policy observation missing keys: {missing}")
    state = np.asarray(observation["observation/state"], dtype=np.float32)
    if state.shape != (8,):
        raise PolicyProtocolError(f"`observation/state` must have shape [8], got {state.shape}")
    for key in ("observation/image", "observation/wrist_image"):
        image = np.asarray(observation[key])
        if image.ndim != 3 or (image.shape[-1] != 3 and image.shape[0] != 3):
            raise PolicyProtocolError(f"`{key}` must be HWC or CHW RGB, got {image.shape}")


def _health_check(connection, request):
    if getattr(request, "path", None) == "/healthz":
        return connection.respond(http.HTTPStatus.OK, "OK\n")
    return None


def _status(message: str) -> None:
    print(f"[openpi-native] {message}", flush=True)


def _msgpack_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _msgpack_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_msgpack_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value
    return str(value)


if __name__ == "__main__":
    main()
