"""Build the isolated grasp provider from an adapter-owned deployment profile."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from .grasp_proposal import FilesystemPointCloudArtifactResolver, GraspGenProposalProvider
from .perception_profile import PerceptionProfileError, _absolute_path, _worker_config
from .process_worker import JsonlProcessWorkerClient

GRASP_PROFILE_SCHEMA_VERSION = "paos-robotwin20-grasp/v1"


class GraspProfileError(ValueError):
    """A grasp provider profile is incomplete or unsafe."""


def load_grasp_profile(path: str | os.PathLike[str]) -> dict[str, Any]:
    profile_path = Path(path)
    if not profile_path.is_absolute() or not profile_path.is_file():
        raise GraspProfileError("grasp profile must be an existing absolute file")
    try:
        import yaml

        value = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError, ImportError) as exc:
        raise GraspProfileError("grasp profile could not be loaded") from exc
    if not isinstance(value, dict):
        raise GraspProfileError("grasp profile must contain an object")
    return value


def build_grasp_provider(
    profile: Mapping[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
) -> GraspGenProposalProvider:
    required = {
        "schema_version", "artifact_root", "max_candidates", "score_threshold", "apply_nms",
        "nms_position_threshold_m", "nms_approach_angle_deg", "nms_closing_angle_deg",
        "apply_model_collision", "worker",
    }
    if not isinstance(profile, Mapping) or set(profile) != required:
        raise GraspProfileError("grasp profile fields are invalid")
    if profile.get("schema_version") != GRASP_PROFILE_SCHEMA_VERSION:
        raise GraspProfileError("grasp profile schema_version is unsupported")
    variables = dict(os.environ if environ is None else environ)
    try:
        artifact_root = _absolute_path(
            profile.get("artifact_root"), variables, "artifact_root", must_be_directory=True
        )
        worker_config = _worker_config(profile.get("worker"), variables, "grasp_worker")
    except PerceptionProfileError as exc:
        raise GraspProfileError(str(exc)) from exc
    client = JsonlProcessWorkerClient(worker_config)
    try:
        return GraspGenProposalProvider(
            client,
            artifact_store=FilesystemPointCloudArtifactResolver(artifact_root),
            max_candidates=profile["max_candidates"],
            score_threshold=profile["score_threshold"],
            apply_nms=profile["apply_nms"],
            nms_position_threshold_m=profile["nms_position_threshold_m"],
            nms_approach_angle_deg=profile["nms_approach_angle_deg"],
            nms_closing_angle_deg=profile["nms_closing_angle_deg"],
            apply_model_collision=profile["apply_model_collision"],
        )
    except (TypeError, ValueError) as exc:
        raise GraspProfileError("grasp profile values are invalid") from exc


__all__ = ["GRASP_PROFILE_SCHEMA_VERSION", "GraspProfileError", "build_grasp_provider", "load_grasp_profile"]
