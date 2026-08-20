"""Discovery of installed, local-only Skill bundles."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from PhyAgentOS.config.paths import get_skill_bundle_root
from PhyAgentOS.skill_runtime.manifest import ManifestError, SkillManifest, load_manifest


class ArtifactResolver(Protocol):
    """Boundary for resolving already-installed Skill artifacts."""

    def resolve(self, manifest: SkillManifest, relative_path: Path) -> Path:
        """Resolve one manifest path to an existing local path."""


class LocalArtifactResolver:
    """Resolve paths without downloading or mutating artifacts."""

    def resolve(self, manifest: SkillManifest, relative_path: Path) -> Path:
        return manifest.resolve_bundle_path(relative_path)


class SkillNotFoundError(LookupError):
    """Raised when an installed Skill cannot be found."""


class SkillCatalog:
    """Read Skill bundles from ``~/.PhyAgentOS/skills/<name>`` only."""

    def __init__(
        self,
        root: Path | None = None,
        resolver: ArtifactResolver | None = None,
    ) -> None:
        self.root = (root or get_skill_bundle_root()).expanduser()
        self.resolver = resolver or LocalArtifactResolver()

    def list(self) -> list[SkillManifest]:
        if not self.root.is_dir():
            return []
        manifests: list[SkillManifest] = []
        for bundle in sorted(self.root.iterdir(), key=lambda item: item.name):
            if not bundle.is_dir() or bundle.name.startswith("."):
                continue
            manifest_path = bundle / "skill.yaml"
            if not manifest_path.is_file():
                continue
            try:
                manifests.append(load_manifest(manifest_path))
            except ManifestError:
                continue
        return manifests

    def errors(self) -> dict[str, str]:
        """Return validation errors without hiding valid bundles."""
        if not self.root.is_dir():
            return {}
        errors: dict[str, str] = {}
        for bundle in sorted(self.root.iterdir(), key=lambda item: item.name):
            manifest_path = bundle / "skill.yaml"
            if not bundle.is_dir() or not manifest_path.is_file():
                continue
            try:
                load_manifest(manifest_path)
            except ManifestError as exc:
                errors[bundle.name] = str(exc)
        return errors

    def get(self, name: str) -> SkillManifest:
        if name in {"", ".", ".."} or "/" in name or "\\" in name:
            raise SkillNotFoundError(f"Skill {name!r} is not installed")
        manifest_path = self.root / name / "skill.yaml"
        if not manifest_path.is_file():
            raise SkillNotFoundError(f"Skill {name!r} is not installed")
        return load_manifest(manifest_path)
