"""RoboTwin 2.0 runtime-only sensor backend.

This file is intentionally outside the installable ``robotwin20_adapter``
package. It is executed in the separately provisioned RoboTwin20 conda
environment and is injected into the dependency-free PAOS adapter. The
backend exposes only rendered RGB/depth and robot state artifacts. It never
serializes actors, segmentation, simulator poses, task evaluators, or action
results.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from contextlib import contextmanager, redirect_stdout
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

try:  # Runtime-only dependencies; PAOS test/install environments may not have them.
    import cv2
    import numpy as np
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised by PAOS boundary tests
    cv2 = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    yaml = None  # type: ignore[assignment]

from robotwin20_adapter import SensorArtifact, SensorCapture


class RoboTwinRuntimeError(RuntimeError):
    """The external RoboTwin runtime cannot provide a safe observation."""


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_CAMERA_REFS = {
    "camera/head": "head_camera",
    "camera/front": "front_camera",
    "camera/left_wrist": "left_camera",
    "camera/right_wrist": "right_camera",
}


EmbodimentSpec = str | tuple[str, str, float]
RUNTIME_PROFILE_SCHEMA_VERSION = "paos-robotwin20-runtime-profile/v1"


def _normalize_embodiment(value: EmbodimentSpec | list[Any]) -> EmbodimentSpec:
    """Normalize RoboTwin's single- or two-single-arm embodiment syntax."""
    if isinstance(value, str):
        return value
    if isinstance(value, (tuple, list)) and len(value) == 3:
        left, right, interval = value
        if (
            isinstance(left, str)
            and isinstance(right, str)
            and isinstance(interval, (int, float))
            and not isinstance(interval, bool)
            and math.isfinite(float(interval))
            and interval > 0
        ):
            return (left, right, float(interval))
    raise RoboTwinRuntimeError(
        "embodiment must be a name or [left_name, right_name, positive_interval]"
    )


def load_runtime_profile(path: Path) -> dict[str, Any]:
    """Load one adapter-owned task/embodiment profile without importing PAOS."""
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise RoboTwinRuntimeError("runtime profile must be an absolute regular file")
    profile_yaml = yaml
    if profile_yaml is None:
        try:
            import yaml as profile_yaml
        except ModuleNotFoundError as exc:
            raise RoboTwinRuntimeError("PyYAML is required to load a runtime profile") from exc
    class _UniqueKeyLoader(profile_yaml.SafeLoader):
        pass

    def construct_mapping(loader, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in result:
                raise RoboTwinRuntimeError("runtime profile contains duplicate YAML keys")
            result[key] = loader.construct_object(value_node, deep=deep)
        return result

    _UniqueKeyLoader.add_constructor(
        profile_yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping
    )
    try:
        value = profile_yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except (OSError, UnicodeError, profile_yaml.YAMLError) as exc:
        raise RoboTwinRuntimeError("runtime profile could not be loaded") from exc
    required = {
        "schema_version", "task_name", "task_config", "embodiment", "sensor_ref", "seed",
        "robot_identity", "gripper_identity", "embodiment_topology", "planner_profile",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise RoboTwinRuntimeError("runtime profile fields are invalid")
    if value["schema_version"] != RUNTIME_PROFILE_SCHEMA_VERSION:
        raise RoboTwinRuntimeError("runtime profile schema_version is unsupported")
    try:
        embodiment = _normalize_embodiment(value["embodiment"])
    except RoboTwinRuntimeError:
        raise
    if (
        not isinstance(value["task_name"], str)
        or not _IDENTIFIER.fullmatch(value["task_name"])
        or not isinstance(value["task_config"], str)
        or not _IDENTIFIER.fullmatch(value["task_config"])
        or not isinstance(value["sensor_ref"], str)
        or value["sensor_ref"] not in _CAMERA_REFS
        or not isinstance(value["seed"], int)
        or isinstance(value["seed"], bool)
    ):
        raise RoboTwinRuntimeError("runtime profile task or sensor fields are invalid")
    for field in ("robot_identity", "gripper_identity", "embodiment_topology", "planner_profile"):
        if not isinstance(value[field], str) or not value[field].strip():
            raise RoboTwinRuntimeError(f"runtime profile {field} is invalid")
    expected_topology = "native-dual-arm" if isinstance(embodiment, str) else "two-single-arm"
    if value["embodiment_topology"] != expected_topology:
        raise RoboTwinRuntimeError("runtime profile embodiment_topology does not match embodiment")
    return {**value, "embodiment": embodiment}


@dataclass(frozen=True)
class RoboTwinObservationSnapshot:
    """Provider-neutral ``scene.observe`` value projected from a sensor capture."""

    captured_at: datetime
    scene_revision: str
    frame_id: str
    calibration_ref: str | None
    artifacts: tuple[dict[str, str], ...]
    sensor_available: bool = True
    observation_ref: str | None = None


class RoboTwinObservationProvider:
    """Expose the runtime backend through the generic observation-provider port."""

    def __init__(self, backend: Any) -> None:
        if not callable(getattr(backend, "capture_sensors", None)) and not callable(
            getattr(backend, "capture", None)
        ):
            raise RoboTwinRuntimeError(
                "observation provider backend must expose capture_sensors or capture"
            )
        self.backend = backend

    def reset(self, *, seed: int | None = None) -> None:
        reset = getattr(self.backend, "reset", None)
        if not callable(reset):
            raise RoboTwinRuntimeError("observation provider backend must expose reset")
        reset(seed=seed)

    def observe(self, sensor_ref: str) -> RoboTwinObservationSnapshot | None:
        capture_sensors = getattr(self.backend, "capture_sensors", None)
        capture = (
            capture_sensors(sensor_ref)
            if callable(capture_sensors)
            else self.backend.capture(sensor_ref)
        )
        if capture is None:
            return None
        if not isinstance(capture, SensorCapture):
            raise RoboTwinRuntimeError("RoboTwin backend returned an invalid sensor capture")
        return RoboTwinObservationSnapshot(
            captured_at=capture.captured_at,
            scene_revision=capture.scene_revision,
            frame_id=capture.frame_id,
            calibration_ref=capture.calibration_ref,
            artifacts=tuple(
                {"ref": item.ref, "kind": item.kind, "media_type": item.media_type}
                for item in capture.artifacts
            ),
            sensor_available=capture.sensor_available,
            observation_ref=(
                f"observation://{capture.scene_revision}/{capture.frame_id}"
            ),
        )


@dataclass(frozen=True)
class RoboTwinRuntimeProfile:
    runtime_root: Path
    artifact_root: Path
    task_name: str = "beat_block_hammer"
    task_config: str = "demo_clean"
    embodiment: EmbodimentSpec = "aloha-agilex"
    forbidden_roots: tuple[Path, ...] = ()

    def validate(self) -> None:
        for value, label in ((self.task_name, "task_name"), (self.task_config, "task_config")):
            if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
                raise RoboTwinRuntimeError(f"{label} must be a safe identifier")
        spec = _normalize_embodiment(self.embodiment)
        names = (spec,) if isinstance(spec, str) else spec[:2]
        for name in names:
            if _IDENTIFIER.fullmatch(name) is None:
                raise RoboTwinRuntimeError("embodiment names must be safe identifiers")
        if not self.runtime_root.is_absolute() or not self.runtime_root.is_dir():
            raise RoboTwinRuntimeError("runtime_root must be an existing absolute directory")
        if not self.artifact_root.is_absolute():
            raise RoboTwinRuntimeError("artifact_root must be an absolute directory")
        runtime_root = self.runtime_root.resolve()
        artifact_root = self.artifact_root.resolve()
        if artifact_root == runtime_root or runtime_root in artifact_root.parents:
            raise RoboTwinRuntimeError("artifact_root must be outside runtime_root")
        for forbidden_root in self.forbidden_roots:
            if not forbidden_root.is_absolute():
                raise RoboTwinRuntimeError("forbidden_roots must be absolute")
            forbidden_root = forbidden_root.resolve()
            if artifact_root == forbidden_root or forbidden_root in artifact_root.parents:
                raise RoboTwinRuntimeError("artifact_root is inside a forbidden root")

    def normalized_embodiment(self) -> EmbodimentSpec:
        return _normalize_embodiment(self.embodiment)


class RoboTwinSensorBackend:
    """Adapt one official RoboTwin task to the provider-neutral sensor seam."""

    def __init__(self, profile: RoboTwinRuntimeProfile) -> None:
        profile.validate()
        self.profile = profile
        self._task: Any | None = None
        self._seed: int | None = None
        self._generation = 0
        self._capture_index = 0
        self._scene_revision: str | None = None
        self._import_runtime()

    @contextmanager
    def _runtime_cwd(self):
        """Run official RoboTwin code with its checkout as the working directory.

        RoboTwin's import-time registries and task implementations resolve some
        asset paths relative to ``.``.  The adapter may be launched from PAOS,
        so the external runtime root must be an explicit, temporary boundary.
        """
        previous = Path.cwd()
        os.chdir(self.profile.runtime_root)
        try:
            yield
        finally:
            os.chdir(previous)

    def _import_runtime(self) -> None:
        global cv2, np, yaml
        if cv2 is None or np is None or yaml is None:
            try:
                import cv2 as cv2_module
                import numpy as np_module
                import yaml as yaml_module
            except ModuleNotFoundError as exc:
                raise RoboTwinRuntimeError(
                    "RoboTwin runtime dependencies are unavailable; use the RoboTwin20 environment"
                ) from exc
            cv2, np, yaml = cv2_module, np_module, yaml_module
        root = str(self.profile.runtime_root)
        if root not in sys.path:
            sys.path.insert(0, root)
        try:
            with self._runtime_cwd():
                from scripts.collect_data import class_decorator
        except Exception as exc:  # pragma: no cover - exercised by runtime preflight
            raise RoboTwinRuntimeError("RoboTwin task runtime import failed") from exc
        self._class_decorator = class_decorator

    def reset(self, *, seed: int | None = None) -> None:
        if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool)):
            raise RoboTwinRuntimeError("seed must be an integer or null")
        self.close()
        root = self.profile.runtime_root
        config_path = root / "env_cfg" / "task_config" / f"{self.profile.task_config}.yml"
        embodiment_path = root / "env_cfg" / "task_config" / "_embodiment_config.yml"
        try:
            task_config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            embodiment_config = yaml.safe_load(embodiment_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise RoboTwinRuntimeError("RoboTwin task configuration could not be read") from exc
        if not isinstance(task_config, dict) or not isinstance(embodiment_config, dict):
            raise RoboTwinRuntimeError("RoboTwin task configuration must be mappings")
        spec = self.profile.normalized_embodiment()
        names = (spec,) if isinstance(spec, str) else spec[:2]
        entries: list[Mapping[str, Any]] = []
        for name in names:
            entry = embodiment_config.get(name)
            if not isinstance(entry, Mapping) or not entry.get("file_path"):
                raise RoboTwinRuntimeError(f"RoboTwin embodiment configuration is unavailable: {name}")
            entries.append(entry)

        args = dict(task_config)
        args.update(
            {
                "task_name": self.profile.task_name,
                "task_config": self.profile.task_config,
                "render_freq": 0,
                "save_data": False,
                "collect_data": False,
                "eval_mode": False,
                "need_plan": False,
                "save_path": str(self.profile.artifact_root),
                "data_type": {
                    "rgb": True,
                    "depth": True,
                    "qpos": True,
                    "endpose": True,
                    "third_view": False,
                    "pointcloud": False,
                    "mesh_segmentation": False,
                    "actor_segmentation": False,
                },
            }
        )
        configs: list[dict[str, Any]] = []
        robot_files: list[str] = []
        for entry in entries:
            robot_file = str(entry["file_path"])
            robot_path = (root / robot_file).resolve()
            if root not in robot_path.parents or not robot_path.is_dir():
                raise RoboTwinRuntimeError("RoboTwin embodiment path escapes runtime_root")
            robot_files.append(robot_file)
            configs.append(self._read_embodiment(robot_path))
        if isinstance(spec, str):
            if configs[0].get("dual_arm") is not True:
                raise RoboTwinRuntimeError(
                    "single embodiment requires a native dual-arm config"
                )
            args["embodiment"] = [spec]
            args["left_robot_file"] = robot_files[0]
            args["right_robot_file"] = robot_files[0]
            args["left_embodiment_config"] = configs[0]
            args["right_embodiment_config"] = configs[0]
            args["dual_arm_embodied"] = True
        else:
            left_name, right_name, interval = spec
            if any(config.get("dual_arm") is not False for config in configs):
                raise RoboTwinRuntimeError(
                    "pair embodiment requires two single-arm configs"
                )
            args["embodiment"] = [left_name, right_name, interval]
            args["left_robot_file"] = robot_files[0]
            args["right_robot_file"] = robot_files[1]
            args["left_embodiment_config"] = configs[0]
            args["right_embodiment_config"] = configs[1]
            args["embodiment_dis"] = interval
            args["dual_arm_embodied"] = False
        args["now_ep_num"] = 0
        args["seed"] = 0 if seed is None else seed
        try:
            with self._runtime_cwd():
                task = self._class_decorator(self.profile.task_name)
                # setup_demo initializes the simulated sensor scene only. This
                # backend deliberately never calls play_once/check_success/move.
                task.setup_demo(**args)
        except Exception as exc:
            raise RoboTwinRuntimeError("RoboTwin task sensor scene setup failed") from exc
        self._task = task
        self._seed = args["seed"]
        self._generation += 1
        self._capture_index = 0
        self._scene_revision = f"{self.profile.task_name}-{self._seed}-{self._generation}"

    @staticmethod
    def _read_embodiment(path: Path) -> dict[str, Any]:
        try:
            value = yaml.safe_load((path / "config.yml").read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise RoboTwinRuntimeError("RoboTwin embodiment config could not be read") from exc
        if not isinstance(value, dict):
            raise RoboTwinRuntimeError("RoboTwin embodiment config must be a mapping")
        return value

    def close(self) -> None:
        task, self._task = self._task, None
        self._scene_revision = None
        if task is not None:
            close = getattr(task, "close_env", None)
            if callable(close):
                with self._runtime_cwd():
                    close(clear_cache=False)

    def snapshot(self) -> Mapping[str, Any]:
        if self._task is None or self._scene_revision is None:
            raise RoboTwinRuntimeError("RoboTwin runtime has not been reset")
        return {"scene_revision": self._scene_revision}

    def capture_sensors(self, sensor_ref: str) -> SensorCapture:
        if self._task is None or self._scene_revision is None:
            raise RoboTwinRuntimeError("RoboTwin runtime has not been reset")
        camera_name = _CAMERA_REFS.get(sensor_ref)
        if camera_name is None:
            raise RoboTwinRuntimeError(f"unsupported sensor_ref: {sensor_ref}")
        try:
            with self._runtime_cwd():
                observation = self._task.get_obs()
        except Exception as exc:
            raise RoboTwinRuntimeError("RoboTwin sensor capture failed") from exc
        camera = observation.get("observation", {}).get(camera_name)
        if not isinstance(camera, Mapping):
            raise RoboTwinRuntimeError(f"RoboTwin observation lacks {camera_name}")
        rgb = camera.get("rgb")
        depth = camera.get("depth")
        if not isinstance(rgb, np.ndarray) or not isinstance(depth, np.ndarray):
            raise RoboTwinRuntimeError("RoboTwin RGB/depth capture has invalid arrays")
        state = self._state_artifact(observation)
        calibration = self._calibration_artifact(camera, camera_name)
        capture_id = f"{self._scene_revision}-{self._capture_index:06d}"
        self._capture_index += 1
        capture_dir = self.profile.artifact_root / self._scene_revision / capture_id
        capture_dir.mkdir(parents=True, exist_ok=True)
        rgb_path = capture_dir / "rgb.png"
        depth_path = capture_dir / "depth.npy"
        state_path = capture_dir / "state.json"
        calibration_path = capture_dir / "calibration.json"
        if not cv2.imwrite(str(rgb_path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)):
            raise RoboTwinRuntimeError("failed to persist RGB artifact")
        np.save(depth_path, depth.astype(np.float32, copy=False), allow_pickle=False)
        state_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
        calibration_path.write_text(json.dumps(calibration, sort_keys=True), encoding="utf-8")
        return SensorCapture(
            captured_at=datetime.now(timezone.utc),
            scene_revision=self._scene_revision,
            frame_id=camera_name,
            calibration_ref=f"artifact://{self._scene_revision}/{capture_id}/calibration",
            artifacts=(
                SensorArtifact(f"artifact://{self._scene_revision}/{capture_id}/rgb", "rgb", "image/png"),
                SensorArtifact(f"artifact://{self._scene_revision}/{capture_id}/depth", "depth", "application/numpy"),
                SensorArtifact(f"artifact://{self._scene_revision}/{capture_id}/state", "state", "application/json"),
            ),
        )

    @staticmethod
    def _calibration_artifact(camera: Mapping[str, Any], camera_name: str) -> dict[str, Any]:
        result: dict[str, Any] = {"camera_name": camera_name}
        for key in ("intrinsic_cv", "extrinsic_cv", "cam2world_gl"):
            value = camera.get(key)
            if not isinstance(value, np.ndarray):
                raise RoboTwinRuntimeError(f"RoboTwin calibration lacks {key}")
            result[key] = value.tolist()
        return result

    @staticmethod
    def _state_artifact(observation: Mapping[str, Any]) -> dict[str, Any]:
        state: dict[str, Any] = {}
        for key in ("joint_action", "endpose"):
            value = observation.get(key)
            if not isinstance(value, Mapping):
                raise RoboTwinRuntimeError(f"RoboTwin state lacks {key}")
            state[key] = _jsonable(value)
        return state


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if np is not None and isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if np is not None and isinstance(value, (np.integer, np.floating)):
        return value.item()
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture one no-motion RoboTwin observation")
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--task-name")
    parser.add_argument("--task-config")
    parser.add_argument(
        "--embodiment",
        nargs="+",
        default=None,
        help="name or: left_name right_name interval",
    )
    parser.add_argument(
        "--forbidden-root",
        action="append",
        type=Path,
        default=[],
        help="Absolute root that must not receive runtime artifacts; repeatable.",
    )
    parser.add_argument("--sensor-ref")
    parser.add_argument("--seed", type=int)
    parser.add_argument(
        "--format",
        choices=("capture", "scene_observe"),
        default="capture",
        help="Emit the raw capture metadata or the provider-neutral scene.observe snapshot.",
    )
    args = parser.parse_args()
    # Third-party simulator/rendering libraries may write warnings to stdout.
    # Keep the machine-readable provider payload on stdout by redirecting all
    # runtime noise to stderr until the final JSON print below.
    profile = load_runtime_profile(args.profile.resolve()) if args.profile else None
    task_name = args.task_name or (profile["task_name"] if profile else "beat_block_hammer")
    task_config = args.task_config or (profile["task_config"] if profile else "demo_clean")
    sensor_ref = args.sensor_ref or (profile["sensor_ref"] if profile else "camera/head")
    seed = args.seed if args.seed is not None else (profile["seed"] if profile else 0)
    raw_embodiment = args.embodiment
    if raw_embodiment is None and profile is not None:
        normalized_profile_embodiment = profile["embodiment"]
        raw_embodiment = (
            [normalized_profile_embodiment]
            if isinstance(normalized_profile_embodiment, str)
            else list(normalized_profile_embodiment)
        )
    if raw_embodiment is None:
        raw_embodiment = ["aloha-agilex"]
    try:
        if len(raw_embodiment) == 1:
            embodiment: EmbodimentSpec = raw_embodiment[0]
        elif len(raw_embodiment) == 3:
            embodiment = (raw_embodiment[0], raw_embodiment[1], float(raw_embodiment[2]))
        else:
            parser.error("--embodiment expects NAME or LEFT RIGHT INTERVAL")
    except ValueError as exc:
        parser.error(f"invalid embodiment interval: {exc}")
    with redirect_stdout(sys.stderr):
        backend = RoboTwinSensorBackend(
            RoboTwinRuntimeProfile(
                runtime_root=args.runtime_root.resolve(),
                artifact_root=args.artifact_root.resolve(),
                task_name=task_name,
                task_config=task_config,
                embodiment=embodiment,
                forbidden_roots=tuple(path.resolve() for path in args.forbidden_root),
            )
        )
        try:
            backend.reset(seed=seed)
            if args.format == "scene_observe":
                snapshot = RoboTwinObservationProvider(backend).observe(sensor_ref)
                if snapshot is None:
                    raise RoboTwinRuntimeError("requested RoboTwin sensor is unavailable")
                output = _jsonable(asdict(snapshot))
            else:
                output = _jsonable(backend.capture_sensors(sensor_ref).__dict__)
        finally:
            backend.close()
    print(json.dumps(output, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
