"""Strict manifests for independently versioned Forge node bundles."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PhyAgentOS.skill_runtime.archive import sha256_file
from PhyAgentOS.skill_runtime.runtime_manifest import normalize_arch, normalize_platform


class NodeManifestError(ValueError):
    """Raised when a node manifest or installed payload is invalid."""


_FIELDS = {
    "manifest_version",
    "node_id",
    "artifact_id",
    "version",
    "platform",
    "arch",
    "digest",
    "entrypoints",
    "files",
}


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NodeManifestError(f"{label} must be a non-empty string")
    return value.strip()


def _identifier(value: Any, label: str) -> str:
    result = _string(value, label)
    if result in {".", ".."} or "/" in result or "\\" in result:
        raise NodeManifestError(f"{label} must be directory-safe")
    return result


def _digest(value: Any, label: str) -> str:
    result = _string(value, label).lower()
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
        raise NodeManifestError(f"{label} must be a sha256 digest")
    return result


def _path(value: Any, label: str) -> Path:
    path = Path(_string(value, label))
    if path.is_absolute() or ".." in path.parts:
        raise NodeManifestError(f"{label} must be a safe relative path")
    return path


@dataclass(frozen=True)
class NodeFile:
    path: Path
    sha256: str
    size: int


@dataclass(frozen=True)
class NodeManifest:
    node_id: str
    artifact_id: str
    version: str
    platform: str
    arch: str
    digest: str
    entrypoints: dict[str, Path]
    files: tuple[NodeFile, ...]
    root: Path
    manifest_version: int = 1

    @classmethod
    def from_dict(cls, value: Any, *, root: Path) -> NodeManifest:
        if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
            raise NodeManifestError("node manifest must be a JSON object")
        unknown = sorted(set(value) - _FIELDS)
        if unknown:
            raise NodeManifestError(f"node manifest has unknown field(s): {', '.join(unknown)}")
        if value.get("manifest_version") != 1:
            raise NodeManifestError("node manifest_version must be 1")

        raw_files = value.get("files")
        if not isinstance(raw_files, list):
            raise NodeManifestError("node manifest files must be a list")
        files: list[NodeFile] = []
        seen: set[Path] = set()
        for index, item in enumerate(raw_files):
            if not isinstance(item, dict) or set(item) != {"path", "sha256", "size"}:
                raise NodeManifestError(f"files[{index}] has invalid fields")
            path = _path(item["path"], f"files[{index}].path")
            if path in seen or path == Path("node-manifest.json"):
                raise NodeManifestError(f"duplicate or reserved node file path: {path}")
            size = item["size"]
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise NodeManifestError(f"files[{index}].size must be a non-negative integer")
            seen.add(path)
            files.append(NodeFile(path, _digest(item["sha256"], "file sha256"), size))

        raw_entrypoints = value.get("entrypoints")
        if not isinstance(raw_entrypoints, dict) or not raw_entrypoints:
            raise NodeManifestError("entrypoints must be a non-empty object")
        entrypoints: dict[str, Path] = {}
        for name, raw_path in raw_entrypoints.items():
            safe_name = _identifier(name, "entrypoint name")
            path = _path(raw_path, f"entrypoints.{safe_name}")
            if path not in seen:
                raise NodeManifestError(f"entrypoint is not inventoried: {path}")
            entrypoints[safe_name] = path

        declared_digest = _digest(value.get("digest"), "digest")
        canonical = dict(value)
        canonical.pop("digest", None)
        computed = hashlib.sha256(
            json.dumps(
                canonical,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        if declared_digest != computed:
            raise NodeManifestError("node manifest digest does not match its contents")
        return cls(
            node_id=_identifier(value.get("node_id"), "node_id"),
            artifact_id=_identifier(value.get("artifact_id"), "artifact_id"),
            version=_string(value.get("version"), "version"),
            platform=normalize_platform(_string(value.get("platform"), "platform")),
            arch=normalize_arch(_string(value.get("arch"), "arch")),
            digest=declared_digest,
            entrypoints=entrypoints,
            files=tuple(files),
            root=root.resolve(),
        )

    def verify_host(self) -> None:
        if self.platform != normalize_platform() or self.arch != normalize_arch():
            raise NodeManifestError(
                f"node platform/arch {self.platform}/{self.arch} does not match host "
                f"{normalize_platform()}/{normalize_arch()}"
            )

    def verify_files(self) -> None:
        expected = {item.path for item in self.files}
        actual = {
            path.relative_to(self.root)
            for path in self.root.rglob("*")
            if path.is_file() and path.name != "node-manifest.json"
        }
        if actual != expected:
            raise NodeManifestError(
                f"node file set mismatch; missing={sorted(map(str, expected - actual))}, "
                f"extra={sorted(map(str, actual - expected))}"
            )
        for item in self.files:
            target = (self.root / item.path).resolve()
            if not target.is_relative_to(self.root) or not target.is_file():
                raise NodeManifestError(f"node file is missing: {item.path}")
            if target.stat().st_size != item.size:
                raise NodeManifestError(f"node file size mismatch: {item.path}")
            if sha256_file(target) != item.sha256:
                raise NodeManifestError(f"node file sha256 mismatch: {item.path}")
        for name, path in self.entrypoints.items():
            target = self.root / path
            if not target.is_file() or target.stat().st_mode & 0o111 == 0:
                raise NodeManifestError(f"node entrypoint is not executable: {name}")


def load_node_manifest(path: Path, *, verify_files: bool = False) -> NodeManifest:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NodeManifestError("cannot parse node-manifest.json") from exc
    manifest = NodeManifest.from_dict(value, root=path.parent)
    if path.parent.name != manifest.artifact_id:
        raise NodeManifestError("artifact_id must match its installation directory")
    if verify_files:
        manifest.verify_files()
    return manifest
