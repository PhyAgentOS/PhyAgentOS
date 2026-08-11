"""X-VLA websocket policy server for PAOS LIBERO evaluation."""

from __future__ import annotations

import argparse
import asyncio
import http
import logging
import os
import time
import traceback
from typing import Any

import numpy as np

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_FLAX", "0")
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")

from PhyAgentOS.runtime.errors import PolicyProtocolError
from PhyAgentOS.runtime.policy.msgpack_numpy import packb, unpackb


class XVLALiberoPolicy:
    """Serve Hugging Face LeRobot X-VLA checkpoints through PAOS."""

    def __init__(self, *, model_id: str, device: str, image_size: int, empty_camera_size: int):
        self.model_id = model_id
        self.device = device
        self.image_size = int(image_size)
        self.empty_camera_size = int(empty_camera_size)
        try:
            import torch
            from lerobot.policies.factory import make_pre_post_processors
            from lerobot.policies.xvla.modeling_xvla import XVLAPolicy
            from lerobot.policies.xvla.processor_xvla import make_xvla_libero_pre_post_processors
            from lerobot.utils.constants import ACTION
        except ModuleNotFoundError as exc:
            raise SystemExit(
                "Missing X-VLA/LeRobot dependencies. Install `lerobot[xvla]` "
                "in the policy environment before running this server."
            ) from exc

        self._torch = torch
        self._action_key = ACTION
        _status(f"loading X-VLA model from {model_id}")
        _status(f"device={device} image_size={self.image_size} empty_camera_size={self.empty_camera_size}")
        self.policy = XVLAPolicy.from_pretrained(model_id).to(device).eval()
        self._last_session_id: str | None = None
        _status("loading LeRobot pre/post processors")
        self.preprocess, self.postprocess = make_pre_post_processors(
            self.policy.config,
            model_id,
            preprocessor_overrides={"device_processor": {"device": device}},
        )
        _, self.env_postprocess = make_xvla_libero_pre_post_processors()
        self.metadata = _msgpack_safe(
            {
                "backend": "xvla_lerobot",
                "model_id": model_id,
                "device": device,
                "action_dim": 7,
                "policy_state_dim": 20,
                "chunk_size": getattr(self.policy.config, "chunk_size", None),
                "n_action_steps": getattr(self.policy.config, "n_action_steps", None),
                "image_size": self.image_size,
                "image_normalization": "imagenet",
                "recommended_control_mode": "absolute",
                "wire_protocol": "openpi_msgpack_numpy",
            }
        )
        _status("X-VLA policy object ready")

    def infer(self, observation: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        session_id = observation.get("session_id")
        if session_id is not None and session_id != self._last_session_id:
            self.policy.reset()
            self._last_session_id = str(session_id)
        frame = _libero_observation_to_lerobot_frame(
            observation,
            image_size=self.image_size,
            empty_camera_size=self.empty_camera_size,
        )
        batch = self.preprocess(frame)
        with self._torch.inference_mode():
            action = self.policy.select_action(batch)
            action = self.postprocess(action)
            action = self.env_postprocess({self._action_key: action})[self._action_key]
        actions = _action_to_numpy(action)
        return {
            "actions": np.ascontiguousarray(actions, dtype=np.float32),
            "policy_meta": {
                "backend": "xvla_lerobot",
                "model_id": self.model_id,
                "policy_latency_ms": (time.perf_counter() - started) * 1000,
                "chunk_size": int(actions.shape[0]),
                "action_dim": int(actions.shape[1]),
            },
        }


async def serve_policy(policy: XVLALiberoPolicy, *, host: str, port: int) -> None:
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
        logging.info("X-VLA LIBERO policy server listening on ws://%s:%d", host, port)
        await server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve X-VLA for PAOS LIBERO evaluation")
    parser.add_argument("--model-id", "--model-dir", default="lerobot/xvla-libero")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--image-size", type=int, default=256)
    parser.add_argument("--empty-camera-size", type=int, default=224)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.INFO), force=True)
    _status("starting PAOS X-VLA LIBERO policy server")
    _status(f"model_id={args.model_id}")
    _status(f"bind={args.host}:{args.port}")
    _status(f"device={args.device} image_size={args.image_size} empty_camera_size={args.empty_camera_size}")
    _status("loading checkpoint; first start may download from Hugging Face and take a while")
    policy = XVLALiberoPolicy(
        model_id=args.model_id,
        device=args.device,
        image_size=args.image_size,
        empty_camera_size=args.empty_camera_size,
    )
    _status("policy loaded; starting websocket server")
    logging.info("Loaded X-VLA policy: %s", policy.metadata)
    asyncio.run(serve_policy(policy, host=args.host, port=args.port))


def _libero_observation_to_lerobot_frame(
    observation: dict[str, Any],
    *,
    image_size: int,
    empty_camera_size: int,
) -> dict[str, Any]:
    if not isinstance(observation, dict):
        raise PolicyProtocolError(f"policy observation must be a dict, got {type(observation).__name__}")
    task = observation.get("task", observation.get("prompt"))
    if task is None:
        raise PolicyProtocolError("policy observation missing `prompt` or `task`")
    try:
        image = observation["observation/image"]
        wrist_image = observation["observation/wrist_image"]
        state = observation["observation/state"]
    except KeyError as exc:
        raise PolicyProtocolError(f"policy observation missing `{exc.args[0]}`") from exc
    eef_mat = observation.get("observation/eef_mat")

    state_array = np.asarray(state, dtype=np.float32)
    if state_array.shape != (8,):
        raise PolicyProtocolError(f"`observation/state` must have shape [8], got {state_array.shape}")

    torch = _torch()
    return {
        "observation.images.image": _imagenet_normalize_chw(_image_to_chw_tensor(image, image_size)),
        # The PAOS LIBERO target returns both cameras flipped 180 degrees. LeRobot's
        # X-VLA LIBERO processor flips only the front camera, so undo the target-side
        # wrist flip here to match the official evaluation path.
        "observation.images.image2": _imagenet_normalize_chw(
            _image_to_chw_tensor(_flip_hwc_or_chw_180(wrist_image), image_size)
        ),
        "observation.state": torch.as_tensor(_libero_state_to_ee6d(state_array, eef_mat), dtype=torch.float32),
        "task": str(task),
    }


def _image_to_chw_tensor(image: Any, size: int):
    torch = _torch()
    array = np.asarray(image)
    if array.size == 0:
        raise PolicyProtocolError("image observation is empty")
    if array.ndim != 3:
        raise PolicyProtocolError(f"image observation must have rank 3, got {array.shape}")
    if array.shape[0] == 3:
        chw = array
    elif array.shape[-1] == 3:
        chw = np.transpose(array, (2, 0, 1))
    else:
        raise PolicyProtocolError(f"image observation must be CHW or HWC RGB, got {array.shape}")
    tensor = torch.as_tensor(np.ascontiguousarray(chw), dtype=torch.float32)
    if np.issubdtype(array.dtype, np.integer):
        tensor = tensor / 255.0
    if tensor.shape[-2:] != (size, size):
        tensor = torch.nn.functional.interpolate(
            tensor[None],
            size=(size, size),
            mode="bilinear",
            align_corners=False,
        )[0]
    return tensor


def _imagenet_normalize_chw(tensor):
    torch = _torch()
    mean = torch.tensor([0.485, 0.456, 0.406], dtype=tensor.dtype, device=tensor.device)[:, None, None]
    std = torch.tensor([0.229, 0.224, 0.225], dtype=tensor.dtype, device=tensor.device)[:, None, None]
    return (tensor - mean) / std


def _flip_hwc_or_chw_180(image: Any) -> np.ndarray:
    array = np.asarray(image)
    if array.ndim != 3:
        raise PolicyProtocolError(f"image observation must have rank 3, got {array.shape}")
    if array.shape[0] == 3:
        return np.ascontiguousarray(array[:, ::-1, ::-1])
    if array.shape[-1] == 3:
        return np.ascontiguousarray(array[::-1, ::-1])
    raise PolicyProtocolError(f"image observation must be CHW or HWC RGB, got {array.shape}")


def _libero_state_to_ee6d(state: np.ndarray, eef_mat: Any | None) -> np.ndarray:
    # Official LeRobot X-VLA LIBERO preprocessing maps robot_state to a 20D
    # ee6d proprio vector: [eef_pos(3), rot6d(6), extra(1), zeros(10)].
    eef_pos = state[:3]
    rot6d = _mat_to_rot6d(eef_mat) if eef_mat is not None else _axis_angle_to_rot6d(state[3:6])
    proprio = np.concatenate([eef_pos, rot6d, np.zeros(1, dtype=np.float32)], axis=0)
    return np.ascontiguousarray(np.concatenate([proprio, np.zeros_like(proprio)], axis=0), dtype=np.float32)


def _axisangle_state_to_ee6d(state: np.ndarray) -> np.ndarray:
    return _libero_state_to_ee6d(state, None)


def _mat_to_rot6d(eef_mat: Any) -> np.ndarray:
    mat = np.asarray(eef_mat, dtype=np.float32)
    if mat.shape != (3, 3):
        raise PolicyProtocolError(f"`observation/eef_mat` must have shape [3,3], got {mat.shape}")
    return np.concatenate([mat[:3, 0], mat[:3, 1]], axis=0).astype(np.float32)


def _axis_angle_to_rot6d(axis_angle: np.ndarray) -> np.ndarray:
    mat = _axis_angle_to_mat(axis_angle)
    return np.concatenate([mat[:3, 0], mat[:3, 1]], axis=0).astype(np.float32)


def _axis_angle_to_mat(axis_angle: np.ndarray) -> np.ndarray:
    vec = np.asarray(axis_angle, dtype=np.float32).reshape(3)
    theta = float(np.linalg.norm(vec))
    if theta < 1e-8:
        return np.eye(3, dtype=np.float32)
    axis = vec / theta
    x, y, z = axis
    c = np.cos(theta)
    s = np.sin(theta)
    one_c = 1.0 - c
    return np.array(
        [
            [c + x * x * one_c, x * y * one_c - z * s, x * z * one_c + y * s],
            [y * x * one_c + z * s, c + y * y * one_c, y * z * one_c - x * s],
            [z * x * one_c - y * s, z * y * one_c + x * s, c + z * z * one_c],
        ],
        dtype=np.float32,
    )


def _action_to_numpy(action: Any) -> np.ndarray:
    torch = _torch(optional=True)
    if torch is not None and isinstance(action, torch.Tensor):
        action = action.detach().cpu().numpy()
    elif isinstance(action, dict):
        for key in ("actions", "action"):
            if key in action:
                return _action_to_numpy(action[key])
    actions = np.asarray(action, dtype=np.float32)
    if actions.ndim == 3 and actions.shape[0] == 1:
        actions = actions[0]
    if actions.ndim == 1:
        actions = actions[None, :]
    if actions.ndim != 2:
        raise PolicyProtocolError(f"policy action must have shape [A] or [T,A], got {actions.shape}")
    if actions.shape[1] == 7:
        return actions
    if actions.shape[1] >= 10:
        return _ee6d_action_to_libero(actions)
    raise PolicyProtocolError(f"policy action must have 7 dims or ee6d dims >=10, got {actions.shape}")


def _ee6d_action_to_libero(actions: np.ndarray) -> np.ndarray:
    # LeRobot X-VLA LIBERO checkpoints emit ee6d actions:
    # [eef_xyz(3), rot6d(6), gripper(1), ...]. LIBERO expects
    # [eef_xyz(3), axis_angle(3), gripper(1)].
    target_eef = actions[:, :3]
    target_axis = _rotate6d_to_axis_angle(actions[:, 3:9])
    gripper = np.where(actions[:, 9:10] > 0.5, 1.0, -1.0)
    return np.ascontiguousarray(np.concatenate([target_eef, target_axis, gripper], axis=-1), dtype=np.float32)


def _rotate6d_to_axis_angle(rotation_6d: np.ndarray) -> np.ndarray:
    a1 = rotation_6d[:, 0:3]
    a2 = rotation_6d[:, 3:6]
    b1 = a1 / (np.linalg.norm(a1, axis=-1, keepdims=True) + 1e-6)
    dot_prod = np.sum(b1 * a2, axis=-1, keepdims=True)
    b2_orth = a2 - dot_prod * b1
    b2 = b2_orth / (np.linalg.norm(b2_orth, axis=-1, keepdims=True) + 1e-6)
    b3 = np.cross(b1, b2, axis=-1)
    rotation_matrix = np.stack([b1, b2, b3], axis=-1)
    return np.stack([_quat_to_axis_angle(_mat_to_quat(mat)) for mat in rotation_matrix], axis=0).astype(np.float32)


def _mat_to_quat(mat: np.ndarray) -> np.ndarray:
    mat = np.asarray(mat, dtype=np.float32)[:3, :3]
    m00, m01, m02 = mat[0]
    m10, m11, m12 = mat[1]
    m20, m21, m22 = mat[2]
    k = np.array(
        [
            [m00 - m11 - m22, 0.0, 0.0, 0.0],
            [m01 + m10, m11 - m00 - m22, 0.0, 0.0],
            [m02 + m20, m12 + m21, m22 - m00 - m11, 0.0],
            [m21 - m12, m02 - m20, m10 - m01, m00 + m11 + m22],
        ],
        dtype=np.float32,
    )
    k /= 3.0
    values, vectors = np.linalg.eigh(k)
    quat = vectors[[3, 0, 1, 2], np.argmax(values)]
    if quat[0] < 0.0:
        quat = -quat
    return quat[[1, 2, 3, 0]].astype(np.float32)


def _quat_to_axis_angle(quat: np.ndarray) -> np.ndarray:
    quat = np.asarray(quat, dtype=np.float32).copy()
    quat[3] = np.clip(quat[3], -1.0, 1.0)
    den = np.sqrt(max(0.0, 1.0 - float(quat[3] * quat[3])))
    if den < 1e-8:
        return np.zeros(3, dtype=np.float32)
    return (quat[:3] * (2.0 * np.arccos(quat[3]) / den)).astype(np.float32)


def _torch(optional: bool = False):
    try:
        import torch
    except ModuleNotFoundError:
        if optional:
            return None
        raise
    return torch


def _health_check(connection, request):
    if getattr(request, "path", None) == "/healthz":
        return connection.respond(http.HTTPStatus.OK, "OK\n")
    return None


def _status(message: str) -> None:
    print(f"[xvla] {message}", flush=True)


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
