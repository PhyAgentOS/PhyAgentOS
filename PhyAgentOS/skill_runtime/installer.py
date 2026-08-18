"""Transactional installers for Skill bundles and Forge Runtime artifact sets."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import yaml

from PhyAgentOS.config.paths import get_forge_runtime_root, get_skill_bundle_root
from PhyAgentOS.skill_runtime.archive import ArchiveValidator
from PhyAgentOS.skill_runtime.manifest import SkillManifest, load_manifest
from PhyAgentOS.skill_runtime.node_manifest import (
    NodeManifest,
    NodeManifestError,
    load_node_manifest,
)
from PhyAgentOS.skill_runtime.state import RuntimeStateStore


class InstallerError(RuntimeError):
    """Raised when an installation cannot be safely committed."""


def _payload_root(extracted: Path, required: str) -> Path:
    if (extracted / required).is_file():
        return extracted
    raise InstallerError(f"archive root must contain {required}")


def _active_skills(store: RuntimeStateStore) -> list[str]:
    if not store.root.is_dir():
        return []
    active = []
    for path in store.root.glob("*.json"):
        try:
            state = store.load(path.stem)
        except Exception:
            active.append(path.stem)
            continue
        if state is not None and (
            state.status in {"starting", "running", "stopping"} or state.active_invocations
        ):
            active.append(state.skill_name)
    return sorted(active)


class SkillInstaller:
    """Install or remove a Skill without exposing a partially validated bundle."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        validator: ArchiveValidator | None = None,
        state_store: RuntimeStateStore | None = None,
    ) -> None:
        self.root = (root or get_skill_bundle_root()).expanduser()
        self.validator = validator or ArchiveValidator()
        self.state_store = state_store or RuntimeStateStore()

    def install(self, archive: Path, *, expected_sha256: str | None = None) -> SkillManifest:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".skill-install-", dir=self.root))
        extracted = temporary / "extracted"
        target: Path | None = None
        backup: Path | None = None
        committed = False
        try:
            self.validator.extract(archive, extracted, expected_sha256=expected_sha256)
            payload = _payload_root(extracted, "skill.yaml")
            if not (payload / "SKILL.md").is_file():
                raise InstallerError("Skill archive root must contain SKILL.md")
            # ``load_manifest`` requires the directory name to equal the Skill name.
            try:
                data = yaml.safe_load((payload / "skill.yaml").read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError) as exc:
                raise InstallerError("cannot parse Skill manifest") from exc
            if not isinstance(data, dict) or not isinstance(data.get("name"), str):
                raise InstallerError("Skill manifest does not contain a valid name")
            normalized = temporary / data["name"]
            if normalized.exists():
                raise InstallerError("Skill archive has an ambiguous root")
            os.replace(payload, normalized)
            manifest = load_manifest(normalized / "skill.yaml")
            if manifest.skill_document != Path("SKILL.md"):
                raise InstallerError("installed Skill skill_document must be SKILL.md")
            target = self.root / manifest.name
            if target.exists():
                if manifest.name in _active_skills(self.state_store):
                    raise InstallerError(f"Skill {manifest.name!r} is currently running")
                try:
                    old_version = load_manifest(target / "skill.yaml").version
                except Exception:
                    try:
                        legacy = yaml.safe_load(
                            (target / "skill.yaml").read_text(encoding="utf-8")
                        )
                        old_version = str(legacy.get("version", "legacy"))
                    except Exception:
                        old_version = "legacy"
                stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
                backup = self.root / ".backups" / manifest.name / f"{old_version}-{stamp}"
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, backup)
            try:
                os.replace(normalized, target)
                installed = load_manifest(target / "skill.yaml")
            except Exception:
                if target is not None and target.exists():
                    failed = temporary / ".failed-install"
                    os.replace(target, failed)
                if backup is not None and target is not None:
                    os.replace(backup, target)
                raise
            committed = True
            return installed
        except InstallerError:
            raise
        except Exception as exc:
            raise InstallerError(f"Skill installation failed: {exc}") from exc
        finally:
            if not committed and backup is not None and target is not None and not target.exists():
                os.replace(backup, target)
            shutil.rmtree(temporary, ignore_errors=True)

    def remove(self, name: str) -> None:
        target = self.root / name
        if name in {"", ".", ".."} or "/" in name or "\\" in name or not target.is_dir():
            raise InstallerError(f"Skill {name!r} is not installed")
        if name in _active_skills(self.state_store):
            raise InstallerError(f"Skill {name!r} is currently running")
        temporary = self.root / f".remove-{name}-{os.getpid()}"
        os.replace(target, temporary)
        try:
            shutil.rmtree(temporary)
        except Exception:
            if not target.exists():
                os.replace(temporary, target)
            raise


class NodeInstaller:
    """Install and verify independently versioned Forge node bundles."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        validator: ArchiveValidator | None = None,
        state_store: RuntimeStateStore | None = None,
    ) -> None:
        runtime_root = (root or get_forge_runtime_root()).expanduser()
        self.root = runtime_root / "nodes"
        self.validator = validator or ArchiveValidator()
        self.state_store = state_store or RuntimeStateStore()

    def install(
        self,
        archive: Path,
        *,
        expected_sha256: str,
        expected_digest: str | None = None,
    ) -> NodeManifest:
        active = _active_skills(self.state_store)
        if active:
            raise InstallerError(
                f"cannot install Forge nodes while Skills are running: {', '.join(active)}"
            )
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".node-install-", dir=self.root))
        extracted = temporary / "extracted"
        committed: Path | None = None
        try:
            self.validator.extract(archive, extracted, expected_sha256=expected_sha256)
            payload = _payload_root(extracted, "node-manifest.json")
            try:
                value = json.loads((payload / "node-manifest.json").read_text(encoding="utf-8"))
                manifest = NodeManifest.from_dict(value, root=payload)
                manifest.verify_host()
                manifest.verify_files()
            except (OSError, json.JSONDecodeError, NodeManifestError) as exc:
                raise InstallerError(f"invalid node-manifest.json: {exc}") from exc
            if expected_digest is not None and manifest.digest != expected_digest.lower():
                raise InstallerError("node manifest digest does not match registry metadata")
            versions = self.root / manifest.node_id / "versions"
            versions.mkdir(parents=True, exist_ok=True)
            target = versions / manifest.artifact_id
            if target.exists():
                installed = load_node_manifest(target / "node-manifest.json", verify_files=True)
                if installed.digest != manifest.digest:
                    raise InstallerError("installed node artifact ID has different contents")
            else:
                os.replace(payload, target)
                committed = target
            return load_node_manifest(target / "node-manifest.json", verify_files=True)
        except InstallerError:
            raise
        except Exception as exc:
            if committed is not None:
                shutil.rmtree(committed, ignore_errors=True)
            raise InstallerError(f"Forge node installation failed: {exc}") from exc
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    def load(self, node_id: str, artifact_id: str) -> NodeManifest:
        path = self.root / node_id / "versions" / artifact_id / "node-manifest.json"
        try:
            manifest = load_node_manifest(path, verify_files=True)
            manifest.verify_host()
        except NodeManifestError as exc:
            raise InstallerError(f"installed Forge node is invalid: {exc}") from exc
        if manifest.node_id != node_id:
            raise InstallerError("installed Forge node ID does not match its directory")
        return manifest


class SkillEnvironmentBuilder:
    """Create immutable per-Skill executable views from exact node locks."""

    def __init__(self, root: Path | None = None) -> None:
        self.runtime_root = (root or get_forge_runtime_root()).expanduser()
        self.environments = self.runtime_root / "environments"
        self.nodes = NodeInstaller(self.runtime_root)

    def prepare(self, skill: SkillManifest, profile_name: str) -> Path:
        profile = skill.profiles.get(profile_name)
        if profile is None:
            raise InstallerError(f"unknown Skill profile: {profile_name}")
        manifests: list[NodeManifest] = []
        for node_id, lock in sorted(skill.artifacts.nodes.items()):
            manifest = self.nodes.load(node_id, lock.artifact_id)
            actual = {
                "version": manifest.version,
                "platform": manifest.platform,
                "arch": manifest.arch,
                "digest": manifest.digest,
            }
            expected = {
                "version": lock.version,
                "platform": lock.platform,
                "arch": lock.arch,
                "digest": lock.digest,
            }
            mismatches = [
                f"{name}={actual[name]!r} (expected {value!r})"
                for name, value in expected.items()
                if actual[name] != value
            ]
            if mismatches:
                raise InstallerError(
                    f"Forge node {node_id!r} does not satisfy Skill lock: "
                    + "; ".join(mismatches)
                )
            manifests.append(manifest)

        providers: dict[str, tuple[NodeManifest, Path]] = {}
        for manifest in manifests:
            for name, relative in manifest.entrypoints.items():
                if name in providers:
                    raise InstallerError(f"duplicate Forge node entrypoint: {name}")
                providers[name] = (manifest, relative)
        required = {path.as_posix() for path in profile.required_binaries}
        missing = sorted(required - providers.keys())
        if missing:
            raise InstallerError(
                f"Skill profile requires unavailable binaries: {', '.join(missing)}"
            )

        lock_value = {
            "manifest_version": 1,
            "skill": skill.name,
            "skill_version": skill.version,
            "profile": profile_name,
            "nodes": {
                manifest.node_id: {
                    "artifact_id": manifest.artifact_id,
                    "digest": manifest.digest,
                }
                for manifest in manifests
            },
            "entrypoints": sorted(required),
        }
        encoded = json.dumps(
            lock_value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode()
        lock_digest = hashlib.sha256(encoded).hexdigest()
        profile_root = self.environments / skill.name / profile_name
        target = profile_root / lock_digest
        rendered_dataflow = target / "launch" / profile.dataflow
        if target.exists() and not rendered_dataflow.is_file():
            shutil.rmtree(target)
        if not target.exists():
            profile_root.mkdir(parents=True, exist_ok=True)
            temporary = Path(tempfile.mkdtemp(prefix=".environment-", dir=profile_root))
            try:
                bin_dir = temporary / "bin"
                bin_dir.mkdir()
                for name in sorted(required):
                    manifest, relative = providers[name]
                    source = manifest.root / relative
                    os.symlink(os.path.relpath(source, bin_dir), bin_dir / name)
                (temporary / "runtime-lock.json").write_bytes(encoded)
                launch_root = temporary / "launch"
                launch_profile = launch_root / profile.dataflow.parent
                launch_profile.mkdir(parents=True)
                source_profile = skill.bundle_root / profile.dataflow.parent
                for source in source_profile.iterdir():
                    if not source.is_file() or source.name == profile.dataflow.name:
                        continue
                    os.symlink(
                        os.path.relpath(source, launch_profile),
                        launch_profile / source.name,
                    )
                assets = skill.bundle_root / "assets"
                if assets.is_dir():
                    os.symlink(os.path.relpath(assets, launch_root), launch_root / "assets")
                source_dataflow = skill.resolve_bundle_path(profile.dataflow)
                rendered = source_dataflow.read_text(encoding="utf-8").replace(
                    "${FORGE_RUNTIME_BIN}", str((target / "bin").resolve())
                ).replace("${PAOS_SKILL_ROOT}", str(skill.bundle_root))
                (launch_profile / profile.dataflow.name).write_text(
                    rendered, encoding="utf-8"
                )
                os.replace(temporary, target)
            finally:
                shutil.rmtree(temporary, ignore_errors=True)
        self._replace_symlink(profile_root / "current", target)
        return target / "bin"

    @staticmethod
    def _replace_symlink(link: Path, target: Path) -> None:
        temporary = link.parent / f".{link.name}.{os.getpid()}.tmp"
        temporary.unlink(missing_ok=True)
        os.symlink(os.path.relpath(target, link.parent), temporary)
        os.replace(temporary, link)
