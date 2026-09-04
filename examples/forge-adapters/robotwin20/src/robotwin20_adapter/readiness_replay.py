"""Immutable, adapter-local readiness replay artifacts.

These artifacts record the output of an independently validated readiness
worker.  They are an audit/replay protocol for the adapter only; they are not
PAOS ``EvidenceBundle`` objects and never authorize an Action.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .readiness import (
    _ARTIFACT_REF,
    _CANDIDATE_REF,
    _CHECK_KEYS,
    _CHECK_STATUSES,
    _ENTITY_REF,
    _validate_request,
)

READINESS_REPLAY_ARTIFACT_SCHEMA_VERSION = (
    "paos-robotwin20-readiness-replay-artifact/v1"
)
_ARTIFACT_KEYS = frozenset(
    {
        "schema_version",
        "artifact_id",
        "worker_id",
        "fixture_sha256",
        "evidence_manifest_sha256",
        "motion_authorized",
        "request",
        "result",
        "generated_at",
    }
)
_RESULT_KEYS = frozenset({"prepared_candidates", "provider_available"})
_SHA256_CHARS = frozenset("0123456789abcdef")


class ReadinessReplayArtifactError(ValueError):
    """The replay artifact is malformed, unsafe, or does not match its ID."""


def _canonical(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReadinessReplayArtifactError("replay artifact is not canonical JSON") from exc


def readiness_replay_artifact_id(artifact: Mapping[str, Any]) -> str:
    payload = {key: artifact[key] for key in _ARTIFACT_KEYS if key != "artifact_id"}
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _check_sha256(value: Any, field: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in _SHA256_CHARS for char in value)
    ):
        raise ReadinessReplayArtifactError(f"{field} must be a lowercase SHA-256 digest")


def _validate_timestamp(value: Any) -> None:
    if not isinstance(value, str):
        raise ReadinessReplayArtifactError("generated_at must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ReadinessReplayArtifactError("generated_at must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReadinessReplayArtifactError("generated_at must include a timezone")


def _validate_result(result: Any) -> None:
    if not isinstance(result, Mapping) or set(result) != _RESULT_KEYS:
        raise ReadinessReplayArtifactError("replay result fields are invalid")
    if not isinstance(result["provider_available"], bool):
        raise ReadinessReplayArtifactError("provider_available must be boolean")
    prepared = result["prepared_candidates"]
    if not isinstance(prepared, list):
        raise ReadinessReplayArtifactError("prepared_candidates must be an array")
    seen: set[str] = set()
    for item in prepared:
        if not isinstance(item, Mapping) or set(item) != {
            "candidate_ref", "entity_ref", "checks", "evidence", "qualification"
        }:
            raise ReadinessReplayArtifactError("prepared candidate fields are invalid")
        candidate_ref = item["candidate_ref"]
        entity_ref = item["entity_ref"]
        if (
            not isinstance(candidate_ref, str)
            or _CANDIDATE_REF.fullmatch(candidate_ref) is None
            or candidate_ref in seen
            or not isinstance(entity_ref, str)
            or _ENTITY_REF.fullmatch(entity_ref) is None
        ):
            raise ReadinessReplayArtifactError("prepared candidate identity is invalid")
        seen.add(candidate_ref)
        checks = item["checks"]
        if (
            not isinstance(checks, Mapping)
            or set(checks) != _CHECK_KEYS
            or any(checks[key] not in _CHECK_STATUSES for key in _CHECK_KEYS)
            or any(checks[key] != "pass" for key in _CHECK_KEYS)
        ):
            raise ReadinessReplayArtifactError("prepared candidate checks are not passing")
        evidence = item["evidence"]
        if not isinstance(evidence, list) or not evidence or any(
            not isinstance(ref, str) or _ARTIFACT_REF.fullmatch(ref) is None
            for ref in evidence
        ):
            raise ReadinessReplayArtifactError("prepared candidate evidence is invalid")
        if item["qualification"] != "prepared":
            raise ReadinessReplayArtifactError("prepared candidate qualification is invalid")


def validate_readiness_replay_artifact(artifact: Mapping[str, Any]) -> None:
    """Validate schema, no-motion boundary, bindings, and content digest."""
    if not isinstance(artifact, Mapping) or set(artifact) != _ARTIFACT_KEYS:
        raise ReadinessReplayArtifactError("replay artifact fields are invalid")
    if artifact["schema_version"] != READINESS_REPLAY_ARTIFACT_SCHEMA_VERSION:
        raise ReadinessReplayArtifactError("replay artifact schema_version is unsupported")
    for field in ("worker_id",):
        if not isinstance(artifact[field], str) or not artifact[field].strip():
            raise ReadinessReplayArtifactError(f"{field} must be a non-empty string")
    _check_sha256(artifact["fixture_sha256"], "fixture_sha256")
    _check_sha256(artifact["evidence_manifest_sha256"], "evidence_manifest_sha256")
    if artifact["motion_authorized"] is not False:
        raise ReadinessReplayArtifactError("replay artifact must be no-motion")
    try:
        _validate_request(artifact["request"])
    except Exception as exc:
        raise ReadinessReplayArtifactError("replay request is invalid") from exc
    _validate_result(artifact["result"])
    request_candidates = {
        item["candidate_ref"]: item["entity_ref"] for item in artifact["request"]["candidates"]
    }
    for item in artifact["result"]["prepared_candidates"]:
        if (
            item["candidate_ref"] not in request_candidates
            or request_candidates[item["candidate_ref"]] != item["entity_ref"]
        ):
            raise ReadinessReplayArtifactError("replay result is not bound to request candidates")
    _validate_timestamp(artifact["generated_at"])
    artifact_id = artifact["artifact_id"]
    if (
        not isinstance(artifact_id, str)
        or len(artifact_id) != 64
        or any(char not in _SHA256_CHARS for char in artifact_id)
        or artifact_id != readiness_replay_artifact_id(artifact)
    ):
        raise ReadinessReplayArtifactError("replay artifact digest mismatch")


def write_readiness_replay_artifact(
    path: str | os.PathLike[str], artifact: Mapping[str, Any]
) -> dict[str, Any]:
    """Write one immutable canonical artifact, refusing divergent overwrites."""
    validate_readiness_replay_artifact(artifact)
    target = Path(path)
    if not target.is_absolute():
        raise ReadinessReplayArtifactError("replay artifact path must be absolute")
    if not target.parent.is_dir():
        raise ReadinessReplayArtifactError("replay artifact parent must exist")
    if target.is_symlink():
        raise ReadinessReplayArtifactError("replay artifact path must not be a symlink")
    encoded = _canonical(artifact) + b"\n"
    if target.exists():
        if not target.is_file() or target.is_symlink():
            raise ReadinessReplayArtifactError("replay artifact must be a regular file")
        if target.stat().st_mode & 0o022:
            raise ReadinessReplayArtifactError("replay artifact must not be group/world writable")
        if target.read_bytes() != encoded:
            raise ReadinessReplayArtifactError("refusing to overwrite immutable replay artifact")
        return dict(artifact)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except OSError as exc:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise ReadinessReplayArtifactError("replay artifact could not be written") from exc
    return dict(artifact)


def load_readiness_replay_artifact(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Load and revalidate an immutable replay artifact from an absolute path."""
    target = Path(path)
    if not target.is_absolute() or not target.is_file() or target.is_symlink():
        raise ReadinessReplayArtifactError("replay artifact must be an existing regular file")
    if target.stat().st_mode & 0o022:
        raise ReadinessReplayArtifactError("replay artifact must not be group/world writable")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReadinessReplayArtifactError("replay artifact is not valid JSON") from exc
    validate_readiness_replay_artifact(value)
    if _canonical(value) + b"\n" != target.read_bytes():
        raise ReadinessReplayArtifactError("replay artifact is not canonical JSON")
    return dict(value)


__all__ = [
    "READINESS_REPLAY_ARTIFACT_SCHEMA_VERSION",
    "ReadinessReplayArtifactError",
    "load_readiness_replay_artifact",
    "readiness_replay_artifact_id",
    "validate_readiness_replay_artifact",
    "write_readiness_replay_artifact",
]
