"""Strict, atomic Markdown state-file protocol.

State files are deliberately an input/projection surface.  This module never
creates AgentTasks, talks to a Gateway, or starts a scheduler.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import yaml

from PhyAgentOS.utils.atomic_file import atomic_write_text

PROTOCOL_VERSION = "paos.state-file.v1"
_FENCED_BLOCK_RE = re.compile(
    r"(?P<fence>`{3,}|~{3,})\s*(?P<lang>json|yaml|yml)\s*\n"
    r"(?P<body>.*?)(?:\n(?P=fence)\s*)",
    re.DOTALL | re.IGNORECASE,
)
_PATH_UNSAFE = re.compile(r"(?:^~|^/|^[A-Za-z]:[\\/]|(?:^|[\\/])\.\.(?:[\\/]|$))")
_REF_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)


class StateFileError(ValueError):
    """Raised when a state file violates the PAOS file protocol."""


class StateFileDriftError(StateFileError):
    """Raised when an atomic projection update observes unexpected content drift."""


@dataclass(frozen=True)
class ParsedStateFile:
    """Validated state-file envelope and its canonical data digest."""

    path: Path
    kind: str
    mode: str
    revision: str
    source: str
    generated_at: str | None
    data: dict[str, Any]
    data_sha256: str


@dataclass(frozen=True)
class ProjectionResult:
    """Result of an atomic projection write."""

    path: Path
    kind: str
    revision: str
    data_sha256: str
    changed: bool


def canonical_sha256(value: Any) -> str:
    """Hash JSON-compatible data deterministically."""

    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise StateFileError("state data must be finite JSON-compatible values") from exc
    return hashlib.sha256(encoded).hexdigest()


def _validate_scalar(value: Any, path: str) -> None:
    if value is None or isinstance(value, (str, bool, int, float)):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise StateFileError(f"{path} must be finite")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_scalar(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise StateFileError(f"{path} has an invalid object key")
            _validate_scalar(item, f"{path}.{key}")
        return
    raise StateFileError(f"{path} must contain only JSON-compatible values")


def _validate_text(value: Any, field: str, *, path_safe: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StateFileError(f"{field} must be a non-empty string")
    normalized = value.strip()
    if path_safe and _PATH_UNSAFE.search(normalized):
        raise StateFileError(f"{field} must not be a filesystem path")
    return normalized


def _extract_payload(text: str, path: Path) -> tuple[str, dict[str, Any]]:
    matches = list(_FENCED_BLOCK_RE.finditer(text))
    if len(matches) != 1:
        raise StateFileError(
            f"{path}: expected exactly one fenced JSON/YAML state block, found {len(matches)}"
        )
    match = matches[0]
    body = match.group("body")
    try:
        payload = json.loads(body) if match.group("lang").lower() == "json" else yaml.safe_load(body)
    except Exception as exc:
        raise StateFileError(f"{path}: structured state block is invalid") from exc
    if not isinstance(payload, dict):
        raise StateFileError(f"{path}: structured state block must be an object")
    unknown = sorted(set(payload) - {"paos", "data"})
    if unknown:
        raise StateFileError(f"{path}: unknown top-level field(s): {', '.join(unknown)}")
    if set(payload) != {"paos", "data"}:
        raise StateFileError(f"{path}: state block must contain exactly paos and data")
    if not isinstance(payload["paos"], dict):
        raise StateFileError(f"{path}: paos metadata must be an object")
    if not isinstance(payload["data"], dict):
        raise StateFileError(f"{path}: data must be an object")
    return match.group("lang").lower(), payload


def parse_state_file(path: str | Path, *, expected_kind: str | None = None) -> ParsedStateFile:
    """Parse and validate one PAOS Markdown state file without side effects."""

    resolved = Path(path).expanduser()
    try:
        text = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        raise StateFileError(f"{resolved}: cannot read UTF-8 state file") from exc
    _, payload = _extract_payload(text, resolved)
    metadata = payload["paos"]
    allowed = {"protocol", "kind", "mode", "revision", "source", "generated_at"}
    unknown = sorted(set(metadata) - allowed)
    if unknown:
        raise StateFileError(f"{resolved}: unknown paos field(s): {', '.join(unknown)}")
    if metadata.get("protocol") != PROTOCOL_VERSION:
        raise StateFileError(f"{resolved}: protocol must be {PROTOCOL_VERSION}")
    kind = _validate_text(metadata.get("kind"), "paos.kind", path_safe=True)
    if expected_kind is not None and kind != expected_kind:
        raise StateFileError(f"{resolved}: expected kind {expected_kind!r}, got {kind!r}")
    mode = _validate_text(metadata.get("mode"), "paos.mode", path_safe=True)
    if mode not in {"input", "projection"}:
        raise StateFileError(f"{resolved}: paos.mode must be input or projection")
    revision = _validate_text(metadata.get("revision"), "paos.revision", path_safe=True)
    source = _validate_text(metadata.get("source"), "paos.source", path_safe=True)
    if not _REF_SCHEME.match(source):
        raise StateFileError("paos.source must be an opaque URI reference")
    generated_at = metadata.get("generated_at")
    if generated_at is not None:
        generated_at = _validate_text(generated_at, "paos.generated_at")
        try:
            datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise StateFileError(f"{resolved}: paos.generated_at must be ISO-8601") from exc
    data = payload["data"]
    _validate_scalar(data, "data")
    return ParsedStateFile(
        path=resolved,
        kind=kind,
        mode=mode,
        revision=revision,
        source=source,
        generated_at=generated_at,
        data=data,
        data_sha256=canonical_sha256(data),
    )


def _render_document(*, kind: str, revision: str, source: str, data: Mapping[str, Any]) -> str:
    kind = _validate_text(kind, "kind", path_safe=True)
    revision = _validate_text(revision, "revision", path_safe=True)
    source = _validate_text(source, "source", path_safe=True)
    if not _REF_SCHEME.match(source):
        raise StateFileError("source must be an opaque URI reference")
    normalized = dict(data)
    _validate_scalar(normalized, "data")
    envelope = {
        "paos": {
            "generated_at": datetime.now(UTC).isoformat(),
            "kind": kind,
            "mode": "projection",
            "protocol": PROTOCOL_VERSION,
            "revision": revision,
            "source": source,
        },
        "data": normalized,
    }
    return "# PAOS state projection\n\n```json\n" + json.dumps(
        envelope, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
    ) + "\n```\n"


def write_projection(
    path: str | Path,
    *,
    kind: str,
    revision: str,
    source: str,
    data: Mapping[str, Any],
    expected_sha256: str | None = None,
) -> ProjectionResult:
    """Atomically write a projection, optionally refusing unexpected drift."""

    target = Path(path).expanduser()
    existing = None
    if target.exists():
        existing = parse_state_file(target, expected_kind=kind)
        if expected_sha256 is not None and existing.data_sha256 != expected_sha256:
            raise StateFileDriftError(
                f"{target}: projection drift (expected {expected_sha256}, got {existing.data_sha256})"
            )
    normalized = dict(data)
    rendered = _render_document(kind=kind, revision=revision, source=source, data=normalized)
    digest = canonical_sha256(normalized)
    changed = existing is None or existing.data_sha256 != digest or existing.revision != revision
    if changed:
        atomic_write_text(target, rendered)
    return ProjectionResult(target, kind, revision, digest, changed)
