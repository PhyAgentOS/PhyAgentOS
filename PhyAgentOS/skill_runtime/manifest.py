"""Strict, relocatable manifest format for installed Skill bundles."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

MANIFEST_VERSION = 2
_MANIFEST_FIELDS = {
    "manifest_version",
    "name",
    "version",
    "description",
    "skill_document",
    "gateway_url",
    "required_tools",
    "profiles",
    "artifacts",
}
_PROFILE_FIELDS = {
    "dataflow",
    "required_binaries",
    "required_assets",
    "required_environment",
    "environment",
}
_ARTIFACT_FIELDS = {"resolver", "nodes"}
_NODE_LOCK_FIELDS = {
    "artifact_id",
    "version",
    "platform",
    "arch",
    "digest",
}


class ManifestError(ValueError):
    """Raised when a Skill manifest is invalid or unsafe."""


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{label} must be a mapping")
    if not all(isinstance(key, str) for key in value):
        raise ManifestError(f"{label} keys must be strings")
    return value


def _unknown(data: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ManifestError(f"{label} has unknown field(s): {', '.join(unknown)}")


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{label} must be a non-empty string")
    return value.strip()


def _relative_path(value: Any, label: str) -> Path:
    raw = _string(value, label)
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ManifestError(f"{label} must be a safe relative path")
    return path


def _string_tuple(value: Any, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ManifestError(f"{label} must be a list")
    items = tuple(_string(item, f"{label} item") for item in value)
    if len(items) != len(set(items)):
        raise ManifestError(f"{label} must not contain duplicates")
    return items


def _path_tuple(value: Any, label: str) -> tuple[Path, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ManifestError(f"{label} must be a list")
    return tuple(_relative_path(item, f"{label} item") for item in value)


@dataclass(frozen=True)
class RuntimeProfile:
    """One launchable Dora profile in a Skill manifest."""

    dataflow: Path
    required_binaries: tuple[Path, ...] = ()
    required_assets: tuple[Path, ...] = ()
    required_environment: tuple[str, ...] = ()
    environment: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Any, label: str) -> RuntimeProfile:
        data = _mapping(value, label)
        _unknown(data, _PROFILE_FIELDS, label)
        environment = _mapping(data.get("environment", {}), f"{label}.environment")
        parsed_environment = {
            _string(key, f"{label}.environment key"): _string(
                item, f"{label}.environment.{key}"
            )
            for key, item in environment.items()
        }
        return cls(
            dataflow=_relative_path(data.get("dataflow"), f"{label}.dataflow"),
            required_binaries=_path_tuple(
                data.get("required_binaries"), f"{label}.required_binaries"
            ),
            required_assets=_path_tuple(
                data.get("required_assets"), f"{label}.required_assets"
            ),
            required_environment=_string_tuple(
                data.get("required_environment"), f"{label}.required_environment"
            ),
            environment=parsed_environment,
        )


@dataclass(frozen=True)
class NodeLock:
    """Immutable reference to one independently installed Forge node."""

    node_id: str
    artifact_id: str
    version: str
    platform: str
    arch: str
    digest: str | None = None

    @classmethod
    def from_dict(cls, node_id: str, value: Any) -> NodeLock:
        safe_node_id = _string(node_id, "artifacts.nodes key")
        if safe_node_id in {".", ".."} or "/" in safe_node_id or "\\" in safe_node_id:
            raise ManifestError("artifacts.nodes key must be directory-safe")
        label = f"artifacts.nodes.{safe_node_id}"
        data = _mapping(value, label)
        _unknown(data, _NODE_LOCK_FIELDS, label)
        artifact_id = _string(data.get("artifact_id"), f"{label}.artifact_id")
        if artifact_id in {".", ".."} or "/" in artifact_id or "\\" in artifact_id:
            raise ManifestError(f"{label}.artifact_id must be directory-safe")
        raw_digest = data.get("digest")
        digest = None
        if raw_digest is not None:
            digest = _string(raw_digest, f"{label}.digest").lower()
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ManifestError(f"{label}.digest must be a sha256 digest")
        return cls(
            node_id=safe_node_id,
            artifact_id=artifact_id,
            version=_string(data.get("version"), f"{label}.version"),
            platform=_string(data.get("platform"), f"{label}.platform").lower(),
            arch=_string(data.get("arch"), f"{label}.arch").lower(),
            digest=digest,
        )


@dataclass(frozen=True)
class ArtifactConfig:
    """Strict node artifact resolver configuration."""

    resolver: str = "local"
    nodes: dict[str, NodeLock] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Any) -> ArtifactConfig:
        data = _mapping(value, "artifacts")
        _unknown(data, _ARTIFACT_FIELDS, "artifacts")
        resolver = _string(data.get("resolver", "local"), "artifacts.resolver")
        if resolver not in {"local", "registry"}:
            raise ManifestError("artifacts.resolver must be 'local' or 'registry'")
        raw_nodes = _mapping(data.get("nodes", {}), "artifacts.nodes")
        nodes = {
            node_id: NodeLock.from_dict(node_id, item)
            for node_id, item in raw_nodes.items()
        }
        if resolver == "registry" and not nodes:
            raise ManifestError("artifacts.nodes is required for registry resolver")
        return cls(resolver=resolver, nodes=nodes)


@dataclass(frozen=True)
class SkillManifest:
    """Validated contents of ``skill.yaml``."""

    name: str
    version: str
    description: str
    skill_document: Path
    gateway_url: str
    required_tools: tuple[str, ...]
    profiles: dict[str, RuntimeProfile]
    artifacts: ArtifactConfig = field(default_factory=ArtifactConfig)
    manifest_version: int = MANIFEST_VERSION
    bundle_root: Path = field(default=Path("."), compare=False, repr=False)

    @classmethod
    def from_dict(cls, value: Any, *, bundle_root: Path) -> SkillManifest:
        data = _mapping(value, "skill manifest")
        _unknown(data, _MANIFEST_FIELDS, "skill manifest")
        if data.get("manifest_version") != MANIFEST_VERSION:
            raise ManifestError(f"manifest_version must be {MANIFEST_VERSION}")

        name = _string(data.get("name"), "name")
        if name in {".", ".."} or "/" in name or "\\" in name:
            raise ManifestError("name must be a directory-safe Skill name")
        gateway_url = _string(data.get("gateway_url"), "gateway_url").rstrip("/")
        parsed_url = urlparse(gateway_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ManifestError("gateway_url must be an HTTP(S) URL")

        profiles_data = _mapping(data.get("profiles"), "profiles")
        if not profiles_data:
            raise ManifestError("profiles must not be empty")
        profiles = {
            _string(profile_name, "profile name"): RuntimeProfile.from_dict(
                profile, f"profiles.{profile_name}"
            )
            for profile_name, profile in profiles_data.items()
        }
        required_tools = _string_tuple(data.get("required_tools"), "required_tools")
        if not required_tools:
            raise ManifestError("required_tools must not be empty")
        artifacts = ArtifactConfig.from_dict(data.get("artifacts", {}))

        version = _string(data.get("version"), "version")
        if "/" in version or "\\" in version or version in {".", ".."}:
            raise ManifestError("version must be directory-safe")
        manifest = cls(
            name=name,
            version=version,
            description=_string(data.get("description"), "description"),
            skill_document=_relative_path(data.get("skill_document"), "skill_document"),
            gateway_url=gateway_url,
            required_tools=required_tools,
            profiles=profiles,
            artifacts=artifacts,
            bundle_root=bundle_root.resolve(),
        )
        document = manifest.resolve_bundle_path(manifest.skill_document)
        if not document.is_file():
            raise ManifestError("skill_document does not exist in the Skill bundle")
        return manifest

    def resolve_bundle_path(self, relative: Path) -> Path:
        """Resolve and contain a path within this bundle."""
        candidate = (self.bundle_root / relative).resolve()
        if not candidate.is_relative_to(self.bundle_root):
            raise ManifestError("manifest path escapes the Skill bundle")
        return candidate


def load_manifest(path: Path) -> SkillManifest:
    """Load a strict Skill manifest from disk."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ManifestError("cannot read Skill manifest") from exc
    except yaml.YAMLError as exc:
        raise ManifestError(f"invalid Skill manifest YAML: {exc}") from exc
    manifest = SkillManifest.from_dict(raw, bundle_root=path.parent)
    if path.parent.name != manifest.name:
        raise ManifestError("manifest name must match its bundle directory")
    return manifest
