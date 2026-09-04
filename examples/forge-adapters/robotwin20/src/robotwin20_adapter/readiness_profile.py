"""Profile wiring for the isolated readiness evidence replay worker."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .perception_profile import PerceptionProfileError, _absolute_path, _expand, _worker_config
from .process_worker import JsonlProcessWorkerClient
from .readiness import RoboTwinReadinessEvaluator

READINESS_PROFILE_SCHEMA_VERSION = "paos-robotwin20-readiness/v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ReadinessProfileError(ValueError):
    """A readiness replay profile is incomplete or unsafe."""


class ReadinessReplayClient:
    """Process client that validates worker identity before projecting evidence."""

    def __init__(self, client: JsonlProcessWorkerClient, *, worker_id: str) -> None:
        self.client = client
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("worker_id must be a non-empty string")
        self.worker_id = worker_id

    def evaluate(self, request: Mapping[str, Any]) -> Mapping[str, Any] | None:
        if not isinstance(request, Mapping):
            raise ReadinessProfileError("readiness request must be an object")
        payload = dict(request)
        payload["request_id"] = uuid4().hex
        response = self.client.request(payload)
        if response.get("request_id") != payload["request_id"]:
            raise ReadinessProfileError("readiness replay response identity mismatch")
        if response.get("status") != "available":
            return {"prepared_candidates": [], "provider_available": False}
        if response.get("schema_version") != "paos-robotwin20-readiness-replay/v1":
            raise ReadinessProfileError("readiness replay response schema mismatch")
        if response.get("worker_id") != self.worker_id:
            raise ReadinessProfileError("readiness replay worker identity mismatch")
        if response.get("motion_authorized") is not False:
            raise ReadinessProfileError("readiness replay worker is not no-motion")
        return {
            "prepared_candidates": response.get("prepared_candidates"),
            "provider_available": response.get("provider_available"),
        }

    def release(self) -> None:
        self.client.release()


def load_readiness_profile(path: str | os.PathLike[str]) -> dict[str, Any]:
    profile_path = Path(path)
    if not profile_path.is_absolute():
        raise ReadinessProfileError("readiness profile must be an absolute file")
    if not profile_path.is_file() or profile_path.is_symlink():
        raise ReadinessProfileError("readiness profile must be an existing regular file")
    try:
        import yaml
    except ImportError as exc:
        raise ReadinessProfileError("PyYAML is required only to load adapter profiles") from exc
    try:
        value = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ReadinessProfileError("readiness profile could not be loaded") from exc
    if not isinstance(value, dict):
        raise ReadinessProfileError("readiness profile must contain an object")
    return value


def build_readiness_evaluator(
    profile: Mapping[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
) -> RoboTwinReadinessEvaluator:
    required = {
        "schema_version", "fixture", "fixture_sha256", "evidence_manifest",
        "evidence_manifest_sha256", "worker", "worker_id",
    }
    if not isinstance(profile, Mapping) or set(profile) != required:
        raise ReadinessProfileError("readiness profile fields are invalid")
    if profile.get("schema_version") != READINESS_PROFILE_SCHEMA_VERSION:
        raise ReadinessProfileError("readiness profile schema_version is unsupported")
    variables = dict(os.environ if environ is None else environ)
    raw_fixture = profile.get("fixture")
    if not isinstance(raw_fixture, str) or not raw_fixture:
        raise ReadinessProfileError("fixture must be a path string")
    try:
        fixture_input = Path(_expand(raw_fixture, variables)).expanduser()
    except PerceptionProfileError as exc:
        raise ReadinessProfileError(str(exc)) from exc
    if not fixture_input.is_absolute() or not fixture_input.is_file() or fixture_input.is_symlink():
        raise ReadinessProfileError("fixture must be an existing regular file")
    try:
        fixture = _absolute_path(str(fixture_input), variables, "fixture", must_be_file=True)
        worker_config = _worker_config(profile.get("worker"), variables, "readiness_worker")
    except PerceptionProfileError as exc:
        raise ReadinessProfileError(str(exc)) from exc
    if "--fixture" in worker_config.command[2:]:
        raise ReadinessProfileError("readiness worker arguments must not contain --fixture")
    if "--evidence-manifest" in worker_config.command[2:]:
        raise ReadinessProfileError("readiness worker arguments must not contain --evidence-manifest")
    if not stat.S_ISREG(fixture.stat().st_mode):
        raise ReadinessProfileError("fixture must be a regular file")
    if fixture.stat().st_mode & 0o022:
        raise ReadinessProfileError("fixture must not be group/world writable")
    expected = profile.get("fixture_sha256")
    if not isinstance(expected, str) or _SHA256.fullmatch(expected) is None:
        raise ReadinessProfileError("fixture_sha256 must be a lowercase SHA-256 digest")
    digest = hashlib.sha256(fixture.read_bytes()).hexdigest()
    if digest != expected:
        raise ReadinessProfileError("fixture sha256 does not match profile")
    raw_manifest = profile.get("evidence_manifest")
    if not isinstance(raw_manifest, str) or not raw_manifest:
        raise ReadinessProfileError("evidence_manifest must be a path string")
    try:
        manifest_input = Path(_expand(raw_manifest, variables)).expanduser()
    except PerceptionProfileError as exc:
        raise ReadinessProfileError(str(exc)) from exc
    if not manifest_input.is_absolute() or not manifest_input.is_file() or manifest_input.is_symlink():
        raise ReadinessProfileError("evidence_manifest must be an existing regular file")
    try:
        manifest = _absolute_path(str(manifest_input), variables, "evidence_manifest", must_be_file=True)
    except PerceptionProfileError as exc:
        raise ReadinessProfileError(str(exc)) from exc
    if not stat.S_ISREG(manifest.stat().st_mode):
        raise ReadinessProfileError("evidence_manifest must be a regular file")
    if manifest.stat().st_mode & 0o022:
        raise ReadinessProfileError("evidence_manifest must not be group/world writable")
    expected_manifest = profile.get("evidence_manifest_sha256")
    if not isinstance(expected_manifest, str) or _SHA256.fullmatch(expected_manifest) is None:
        raise ReadinessProfileError("evidence_manifest_sha256 must be a lowercase SHA-256 digest")
    manifest_digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    if manifest_digest != expected_manifest:
        raise ReadinessProfileError("evidence_manifest sha256 does not match profile")
    worker_id = profile.get("worker_id")
    if not isinstance(worker_id, str) or not worker_id.strip():
        raise ReadinessProfileError("worker_id must be a non-empty string")
    config = replace(
        worker_config,
        command=(
            *worker_config.command,
            "--fixture", str(fixture),
            "--evidence-manifest", str(manifest),
        ),
    )
    return RoboTwinReadinessEvaluator(
        ReadinessReplayClient(JsonlProcessWorkerClient(config), worker_id=worker_id)
    )


__all__ = [
    "READINESS_PROFILE_SCHEMA_VERSION",
    "ReadinessProfileError",
    "ReadinessReplayClient",
    "build_readiness_evaluator",
    "load_readiness_profile",
]
