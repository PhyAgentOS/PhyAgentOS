"""OpenVLA websocket policy server for PAOS LIBERO evaluation."""

from __future__ import annotations

import argparse
import asyncio
import http
import json
import logging
import os
from pathlib import Path
import time
import traceback
from typing import Any

import numpy as np

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_FLAX", "0")
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")

from PhyAgentOS.runtime.policy.msgpack_numpy import packb, unpackb
from PhyAgentOS.runtime.watchdog.errors import PolicyProtocolError


class OpenVLALiberoPolicy:
    """Serve OpenVLA LIBERO actions through the PAOS policy wire protocol."""

    def __init__(
        self,
        *,
        model_path: str,
        unnorm_key: str,
        device: str,
        torch_dtype: str,
        image_size: int,
        center_crop: bool,
        load_in_8bit: bool,
        load_in_4bit: bool,
        attn_implementation: str | None,
    ):
        self.model_path = model_path
        self.unnorm_key = unnorm_key
        self.device = device
        self.image_size = int(image_size)
        self.center_crop = bool(center_crop)

        try:
            import torch
            from transformers import AutoModelForVision2Seq, AutoProcessor
        except ModuleNotFoundError as exc:
            raise SystemExit(
                "Missing OpenVLA dependencies. Install the OpenVLA/Transformers "
                "environment before running this server."
            ) from exc

        _register_openvla_classes()
        dtype = _torch_dtype(torch, torch_dtype)
        load_kwargs: dict[str, Any] = {
            "trust_remote_code": True,
            "low_cpu_mem_usage": True,
            "torch_dtype": dtype,
            "load_in_8bit": bool(load_in_8bit),
            "load_in_4bit": bool(load_in_4bit),
        }
        if attn_implementation:
            load_kwargs["attn_implementation"] = attn_implementation
        _status(f"loading model from {model_path}")
        _status(
            "device=%s torch_dtype=%s load_in_8bit=%s load_in_4bit=%s attn_implementation=%s"
            % (device, str(dtype), bool(load_in_8bit), bool(load_in_4bit), attn_implementation or "<default>")
        )
        try:
            self.model = AutoModelForVision2Seq.from_pretrained(model_path, **load_kwargs)
        except Exception:
            if "attn_implementation" not in load_kwargs:
                raise
            _status("model load with requested attention implementation failed; retrying without it")
            load_kwargs.pop("attn_implementation", None)
            self.model = AutoModelForVision2Seq.from_pretrained(model_path, **load_kwargs)

        if not load_in_8bit and not load_in_4bit:
            _status(f"moving model to {device}")
            self.model = self.model.to(device)
        self.model.eval()
        _status("loading processor")
        self.processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)
        _status("loading dataset statistics")
        _load_dataset_statistics(self.model, model_path)
        self._torch = torch
        self._dtype = dtype
        self.metadata = _msgpack_safe(
            {
                "backend": "openvla",
                "model_path": model_path,
                "device": device,
                "torch_dtype": str(dtype),
                "unnorm_key": self.unnorm_key,
                "action_dim": 7,
                "image_size": self.image_size,
                "center_crop": self.center_crop,
                "recommended_control_mode": "relative",
                "wire_protocol": "openpi_msgpack_numpy",
            }
        )
        _status("OpenVLA policy object ready")

    def infer(self, observation: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        _validate_observation(observation, require_prompt=True)
        image = _image_to_pil(
            observation["observation/image"],
            image_size=self.image_size,
            center_crop=self.center_crop,
        )
        prompt = _openvla_prompt(str(observation.get("prompt") or observation.get("task")), self.model_path)
        inputs = self.processor(prompt, image).to(self.device, dtype=self._dtype)
        unnorm_key = _resolve_unnorm_key(self.model, self.unnorm_key)
        with self._torch.inference_mode():
            action = self.model.predict_action(**inputs, unnorm_key=unnorm_key, do_sample=False)
        actions = _actions_to_numpy(action)
        actions = _normalize_and_invert_libero_gripper(actions)
        return {
            "actions": np.ascontiguousarray(actions, dtype=np.float32),
            "policy_meta": {
                "backend": "openvla",
                "model_path": self.model_path,
                "unnorm_key": unnorm_key,
                "policy_latency_ms": (time.perf_counter() - started) * 1000,
                "chunk_size": int(actions.shape[0]),
                "action_dim": int(actions.shape[1]),
            },
        }


async def serve_policy(policy: OpenVLALiberoPolicy, *, host: str, port: int) -> None:
    try:
        import websockets
        import websockets.asyncio.server as websocket_server
    except ModuleNotFoundError as exc:
        raise SystemExit("Missing `websockets`; install runtime dependencies.") from exc

    async def handler(websocket):
        await websocket.send(packb(policy.metadata))
        while True:
            try:
                message = await websocket.recv()
                if isinstance(message, str):
                    raise PolicyProtocolError("expected binary msgpack policy request")
                await websocket.send(packb(policy.infer(unpackb(message))))
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
    ) as server:
        _status(f"listening on ws://{host}:{port}")
        _status(f"use policy endpoint openpi://{host}:{port} from PAOS")
        _status("health check path: /healthz")
        logging.info("OpenVLA LIBERO policy server listening on ws://%s:%d", host, port)
        await server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve OpenVLA for PAOS LIBERO evaluation")
    parser.add_argument("--model-path", "--model-dir", default="openvla/openvla-7b-finetuned-libero-spatial")
    parser.add_argument("--unnorm-key", default="libero_spatial")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--torch-dtype", default="bfloat16", choices=["bfloat16", "float16", "float32"])
    parser.add_argument("--image-size", type=int, default=224)
    parser.add_argument("--center-crop", action="store_true")
    parser.add_argument("--load-in-8bit", action="store_true")
    parser.add_argument("--load-in-4bit", action="store_true")
    parser.add_argument("--attn-implementation", default="flash_attention_2")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.INFO), force=True)
    _status("starting PAOS OpenVLA LIBERO policy server")
    _status(f"model_path={args.model_path}")
    _status(f"unnorm_key={args.unnorm_key}")
    _status(f"bind={args.host}:{args.port}")
    _status(f"image_size={args.image_size} center_crop={args.center_crop}")
    _status("loading checkpoint; first start may download from Hugging Face and take a while")
    policy = OpenVLALiberoPolicy(
        model_path=args.model_path,
        unnorm_key=args.unnorm_key,
        device=args.device,
        torch_dtype=args.torch_dtype,
        image_size=args.image_size,
        center_crop=args.center_crop,
        load_in_8bit=args.load_in_8bit,
        load_in_4bit=args.load_in_4bit,
        attn_implementation=args.attn_implementation,
    )
    _status("policy loaded; starting websocket server")
    logging.info("Loaded OpenVLA policy: %s", policy.metadata)
    asyncio.run(serve_policy(policy, host=args.host, port=args.port))


def _register_openvla_classes() -> None:
    try:
        from prismatic.extern.hf.configuration_prismatic import OpenVLAConfig
        from prismatic.extern.hf.modeling_prismatic import OpenVLAForActionPrediction
        from transformers import AutoConfig, AutoModelForVision2Seq
    except Exception:
        return
    try:
        AutoConfig.register("openvla", OpenVLAConfig)
    except ValueError:
        pass
    try:
        AutoModelForVision2Seq.register(OpenVLAConfig, OpenVLAForActionPrediction)
    except ValueError:
        pass


def _torch_dtype(torch, dtype: str):
    return {
        "bfloat16": torch.bfloat16,
        "float16": torch.float16,
        "float32": torch.float32,
    }[dtype]


def _validate_observation(observation: dict[str, Any], *, require_prompt: bool) -> None:
    if not isinstance(observation, dict):
        raise PolicyProtocolError(f"policy observation must be a dict, got {type(observation).__name__}")
    if "observation/image" not in observation:
        raise PolicyProtocolError("policy observation missing `observation/image`")
    if require_prompt and observation.get("prompt", observation.get("task")) is None:
        raise PolicyProtocolError("policy observation missing `prompt` or `task`")


def _image_to_pil(image: Any, *, image_size: int, center_crop: bool):
    try:
        from PIL import Image
    except ModuleNotFoundError as exc:
        raise SystemExit("Missing Pillow; install PIL/Pillow in the policy environment.") from exc
    array = np.asarray(image)
    if array.ndim != 3:
        raise PolicyProtocolError(f"`observation/image` must have rank 3, got {array.shape}")
    if array.shape[0] == 3:
        array = np.transpose(array, (1, 2, 0))
    if array.shape[-1] != 3:
        raise PolicyProtocolError(f"`observation/image` must be RGB, got {array.shape}")
    if np.issubdtype(array.dtype, np.floating):
        array = (np.clip(array, 0.0, 1.0) * 255.0).astype(np.uint8)
    else:
        array = array.astype(np.uint8, copy=False)
    pil = Image.fromarray(np.ascontiguousarray(array))
    if center_crop:
        crop_scale = 0.9
        width, height = pil.size
        crop_w, crop_h = int(width * crop_scale), int(height * crop_scale)
        left = max(0, (width - crop_w) // 2)
        top = max(0, (height - crop_h) // 2)
        pil = pil.crop((left, top, left + crop_w, top + crop_h))
    if pil.size != (image_size, image_size):
        pil = pil.resize((image_size, image_size), Image.Resampling.LANCZOS)
    return pil


def _openvla_prompt(task: str, model_path: str) -> str:
    task = task.strip()
    if "openvla-v01" in model_path.lower():
        return f"{task.lower()}"
    return f"In: What action should the robot take to {task.lower()}?\nOut:"


def _load_dataset_statistics(model, model_path: str) -> None:
    if getattr(model, "norm_stats", None):
        return
    stats = None
    local_path = Path(model_path).expanduser()
    if local_path.exists():
        stats_path = local_path / "dataset_statistics.json"
        if stats_path.exists():
            stats = json.loads(stats_path.read_text(encoding="utf-8"))
    if stats is None and "/" in model_path and not local_path.exists():
        try:
            from huggingface_hub import hf_hub_download

            stats_path = hf_hub_download(repo_id=model_path, filename="dataset_statistics.json")
            stats = json.loads(Path(stats_path).read_text(encoding="utf-8"))
        except Exception:
            stats = None
    if stats is not None:
        model.norm_stats = stats


def _resolve_unnorm_key(model, requested: str) -> str:
    stats = getattr(model, "norm_stats", {}) or {}
    if requested in stats:
        return requested
    no_noops = f"{requested}_no_noops"
    if no_noops in stats:
        return no_noops
    return requested


def _actions_to_numpy(action: Any) -> np.ndarray:
    torch = None
    try:
        import torch as _torch

        torch = _torch
    except Exception:
        pass
    if torch is not None and isinstance(action, torch.Tensor):
        action = action.detach().cpu().numpy()
    actions = np.asarray(action, dtype=np.float32)
    if actions.ndim == 1:
        actions = actions[None, :]
    if actions.ndim != 2:
        raise PolicyProtocolError(f"OpenVLA action must have shape [A] or [T,A], got {actions.shape}")
    if actions.shape[1] < 7:
        raise PolicyProtocolError(f"OpenVLA action must have at least 7 dims, got {actions.shape}")
    return actions[:, :7]


def _normalize_and_invert_libero_gripper(actions: np.ndarray) -> np.ndarray:
    updated = np.array(actions, dtype=np.float32, copy=True)
    gripper = updated[:, -1]
    if np.nanmin(gripper) >= 0.0 and np.nanmax(gripper) <= 1.0:
        gripper = 2.0 * gripper - 1.0
    gripper = np.where(gripper >= 0.0, 1.0, -1.0)
    updated[:, -1] = -gripper
    return updated


def _health_check(connection, request):
    if getattr(request, "path", None) == "/healthz":
        return connection.respond(http.HTTPStatus.OK, "OK\n")
    return None


def _status(message: str) -> None:
    print(f"[openvla] {message}", flush=True)


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
