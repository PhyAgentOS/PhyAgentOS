"""Strict parser and verifier for installed Forge Runtime manifests."""

from __future__ import annotations

import hashlib
import json
import platform as host_platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PhyAgentOS.skill_runtime.archive import sha256_file


class RuntimeManifestError(ValueError):
    """Raised when a runtime manifest or installed artifact set is invalid."""


_FIELDS = {
    "manifest_version",
    "artifact_set_id",
    "version",
    "platform",
    "arch",
    "mode",
    "digest",
    "files",
}


def normalize_platform(value: str | None = None) -> str:
    raw = (value or host_platform.system()).strip().lower()
    return {"darwin": "macos", "win32": "windows"}.get(raw, raw)


def normalize_arch(value: str | None = None) -> str:
    raw = (value or host_platform.machine()).strip().lower()
    return {"amd64": "x86_64", "x64": "x86_64", "arm64": "aarch64"}.get(raw, raw)


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeManifestError(f"{label} must be a non-empty string")
    return value.strip()


def _digest(value: Any, label: str) -> str:
    digest = _string(value, label).lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise RuntimeManifestError(f"{label} must be a sha256 digest")
    return digest


def _path(value: Any, label: str) -> Path:
    raw = _string(value, label)
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeManifestError(f"{label} must be a safe relative path")
    return path


@dataclass(frozen=True)
class RuntimeFile:
    path: Path
    sha256: str
    size: int | None = None


@dataclass(frozen=True)
class RuntimeManifest:
    artifact_set_id: str
    version: str
    platform: str
    arch: str
    mode: str
    digest: str
    files: tuple[RuntimeFile, ...]
    manifest_version: int = 1
    root: Path = Path(".")

    @classmethod
    def from_dict(cls, value: Any, *, root: Path) -> RuntimeManifest:
        if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
            raise RuntimeManifestError("runtime manifest must be a JSON object")
        unknown = sorted(set(value) - _FIELDS)
        if unknown:
            raise RuntimeManifestError(
                f"runtime manifest has unknown field(s): {', '.join(unknown)}"
            )
        if value.get("manifest_version") != 1:
            raise RuntimeManifestError("runtime manifest_version must be 1")
        raw_files = value.get("files")
        if not isinstance(raw_files, list):
            raise RuntimeManifestError("runtime manifest files must be a list")
        files: list[RuntimeFile] = []
        seen: set[Path] = set()
        for index, item in enumerate(raw_files):
            if not isinstance(item, dict) or set(item) - {"path", "sha256", "size"}:
                raise RuntimeManifestError(f"runtime manifest files[{index}] has invalid fields")
            path = _path(item.get("path"), f"files[{index}].path")
            if path in seen or path == Path("runtime-manifest.json"):
                raise RuntimeManifestError(f"duplicate or reserved runtime file path: {path}")
            seen.add(path)
            size = item.get("size")
            if size is not None and (
                not isinstance(size, int) or isinstance(size, bool) or size < 0
            ):
                raise RuntimeManifestError(f"files[{index}].size must be a non-negative integer")
            files.append(
                RuntimeFile(
                    path=path,
                    sha256=_digest(item.get("sha256"), f"files[{index}].sha256"),
                    size=size,
                )
            )
        artifact_set_id = _string(value.get("artifact_set_id"), "artifact_set_id")
        if artifact_set_id in {".", ".."} or "/" in artifact_set_id or "\\" in artifact_set_id:
            raise RuntimeManifestError("artifact_set_id must be directory-safe")
        declared_digest = _digest(value.get("digest"), "digest")
        canonical = dict(value)
        canonical.pop("digest", None)
        computed_digest = hashlib.sha256(
            json.dumps(
                canonical,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        if declared_digest != computed_digest:
            raise RuntimeManifestError("runtime manifest digest does not match its contents")
        return cls(
            artifact_set_id=artifact_set_id,
            version=_string(value.get("version"), "version"),
            platform=normalize_platform(_string(value.get("platform"), "platform")),
            arch=normalize_arch(_string(value.get("arch"), "arch")),
            mode=_string(value.get("mode"), "mode"),
            digest=declared_digest,
            files=tuple(files),
            root=root.resolve(),
        )

    def verify_files(self) -> None:
        expected = {item.path for item in self.files}
        actual = {
            path.relative_to(self.root)
            for path in self.root.rglob("*")
            if path.is_file() and path.name != "runtime-manifest.json"
        }
        if actual != expected:
            raise RuntimeManifestError(
                f"runtime file set mismatch; missing={sorted(map(str, expected - actual))}, "
                f"extra={sorted(map(str, actual - expected))}"
            )
        for item in self.files:
            target = (self.root / item.path).resolve()
            if not target.is_relative_to(self.root) or not target.is_file():
                raise RuntimeManifestError(f"runtime file is missing: {item.path.as_posix()}")
            if item.size is not None and target.stat().st_size != item.size:
                raise RuntimeManifestError(f"runtime file size mismatch: {item.path.as_posix()}")
            if sha256_file(target) != item.sha256:
                raise RuntimeManifestError(f"runtime file sha256 mismatch: {item.path.as_posix()}")

    def verify_host(self) -> None:
        if self.platform != normalize_platform():
            raise RuntimeManifestError(
                f"runtime platform {self.platform!r} does not match host {normalize_platform()!r}"
            )
        if self.arch != normalize_arch():
            raise RuntimeManifestError(
                f"runtime arch {self.arch!r} does not match host {normalize_arch()!r}"
            )


def load_runtime_manifest(path: Path, *, verify_files: bool = False) -> RuntimeManifest:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeManifestError("cannot read runtime-manifest.json") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeManifestError("runtime-manifest.json is not valid JSON") from exc
    manifest = RuntimeManifest.from_dict(value, root=path.parent)
    if path.parent.name != manifest.artifact_set_id:
        raise RuntimeManifestError(
            "runtime artifact_set_id must match its installation directory"
        )
    if verify_files:
        manifest.verify_files()
    return manifest
