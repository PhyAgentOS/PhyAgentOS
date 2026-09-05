"""Profile wiring for isolated proposal and segmentation worker environments."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Mapping

from .process_worker import JsonlProcessWorkerClient, ProcessWorkerConfig
from .single_view_perception import (
    FilesystemPerceptionArtifactStore,
    NumpyMetricLocalizationProvider,
    SingleViewPerceptionInference,
    WorkerProposalProvider,
    WorkerSegmentationProvider,
)

PROFILE_SCHEMA_VERSION = "paos-robotwin20-perception/v1"
_ENV = re.compile(r"\$\{([A-Z][A-Z0-9_]*)\}")


class PerceptionProfileError(ValueError):
    """A deployment profile cannot construct the isolated perception route."""


def _read_unique_yaml(
    path: Path,
    *,
    error_type: type[ValueError],
    label: str,
) -> dict[str, Any]:
    """Read a strict YAML mapping and reject duplicate keys at every depth."""

    try:
        import yaml
    except ImportError as exc:
        raise error_type("PyYAML is required to load adapter profiles") from exc

    class _UniqueKeyLoader(yaml.SafeLoader):
        pass

    def mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False):
        result: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in result:
                raise error_type(f"{label} contains duplicate YAML keys")
            result[key] = loader.construct_object(value_node, deep=deep)
        return result

    _UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    try:
        value = yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except error_type:
        raise
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise error_type(f"{label} could not be loaded") from exc
    if not isinstance(value, dict):
        raise error_type(f"{label} must contain an object")
    return value


def load_perception_profile(path: str | os.PathLike[str]) -> dict[str, Any]:
    profile_path = Path(path)
    if not profile_path.is_absolute() or not profile_path.is_file():
        raise PerceptionProfileError("perception profile must be an existing absolute file")
    return _read_unique_yaml(
        profile_path,
        error_type=PerceptionProfileError,
        label="perception profile",
    )


def build_single_view_perception(
    semantic_inference: Any,
    profile: Mapping[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
) -> SingleViewPerceptionInference:
    if not isinstance(profile, Mapping) or set(profile) != {
        "schema_version", "artifact_root", "worker_artifact_root", "depth_scale_to_m",
        "max_points", "proposal_worker", "segmentation_worker",
    }:
        raise PerceptionProfileError("perception profile fields are invalid")
    if profile.get("schema_version") != PROFILE_SCHEMA_VERSION:
        raise PerceptionProfileError("perception profile schema_version is unsupported")
    variables = dict(os.environ if environ is None else environ)
    artifact_root = _absolute_path(profile.get("artifact_root"), variables, "artifact_root")
    worker_artifact_root = _absolute_path(
        profile.get("worker_artifact_root"), variables, "worker_artifact_root"
    )
    proposal_client = JsonlProcessWorkerClient(
        _worker_config(profile.get("proposal_worker"), variables, "proposal_worker")
    )
    segmentation_client = JsonlProcessWorkerClient(
        _worker_config(profile.get("segmentation_worker"), variables, "segmentation_worker")
    )
    depth_scale = profile.get("depth_scale_to_m")
    max_points = profile.get("max_points")
    if isinstance(depth_scale, bool) or not isinstance(depth_scale, (int, float)):
        raise PerceptionProfileError("depth_scale_to_m must be numeric")
    if isinstance(max_points, bool) or not isinstance(max_points, int):
        raise PerceptionProfileError("max_points must be an integer")
    return SingleViewPerceptionInference(
        semantic_inference,
        proposal_provider=WorkerProposalProvider(proposal_client),
        segmentation_provider=WorkerSegmentationProvider(
            segmentation_client,
            worker_artifact_root=worker_artifact_root,
        ),
        localization_provider=NumpyMetricLocalizationProvider(
            depth_scale_to_m=float(depth_scale),
            max_points=max_points,
        ),
        artifact_store=FilesystemPerceptionArtifactStore(artifact_root),
    )


def _worker_config(value: Any, environ: Mapping[str, str], label: str) -> ProcessWorkerConfig:
    required = {
        "python", "script", "arguments", "cwd", "environment",
        "startup_timeout_s", "request_timeout_s", "shutdown_timeout_s",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise PerceptionProfileError(f"{label} fields are invalid")
    python = _absolute_path(value.get("python"), environ, f"{label}.python", must_be_file=True)
    script = _absolute_path(value.get("script"), environ, f"{label}.script", must_be_file=True)
    cwd = _absolute_path(value.get("cwd"), environ, f"{label}.cwd", must_be_directory=True)
    arguments = value.get("arguments")
    if not isinstance(arguments, list) or any(not isinstance(item, str) or not item for item in arguments):
        raise PerceptionProfileError(f"{label}.arguments must be an array of strings")
    environment = value.get("environment")
    if not isinstance(environment, Mapping) or any(
        not isinstance(key, str) or not isinstance(item, str) for key, item in environment.items()
    ):
        raise PerceptionProfileError(f"{label}.environment must be a string mapping")
    try:
        return ProcessWorkerConfig(
            command=(str(python), str(script), *(_expand(item, environ) for item in arguments)),
            cwd=cwd,
            environment={key: _expand(item, environ) for key, item in environment.items()},
            startup_timeout_s=float(value["startup_timeout_s"]),
            request_timeout_s=float(value["request_timeout_s"]),
            shutdown_timeout_s=float(value["shutdown_timeout_s"]),
        )
    except (TypeError, ValueError) as exc:
        raise PerceptionProfileError(f"{label} process configuration is invalid") from exc


def _absolute_path(
    value: Any,
    environ: Mapping[str, str],
    label: str,
    *,
    must_be_file: bool = False,
    must_be_directory: bool = False,
) -> Path:
    if not isinstance(value, str) or not value:
        raise PerceptionProfileError(f"{label} must be a path string")
    path = Path(_expand(value, environ)).expanduser()
    if not path.is_absolute():
        raise PerceptionProfileError(f"{label} must be absolute")
    path = path.resolve()
    if must_be_file and not path.is_file():
        raise PerceptionProfileError(f"{label} file is unavailable")
    if must_be_directory and not path.is_dir():
        raise PerceptionProfileError(f"{label} directory is unavailable")
    return path


def _expand(value: str, environ: Mapping[str, str]) -> str:
    missing = sorted({name for name in _ENV.findall(value) if not environ.get(name)})
    if missing:
        raise PerceptionProfileError(f"profile environment variable is unavailable: {missing[0]}")
    return _ENV.sub(lambda match: environ[match.group(1)], value)


__all__ = [
    "PROFILE_SCHEMA_VERSION",
    "PerceptionProfileError",
    "build_single_view_perception",
    "load_perception_profile",
]
