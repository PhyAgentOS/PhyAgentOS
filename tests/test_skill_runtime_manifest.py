from __future__ import annotations

import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path

import httpx
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parents[1]))

from PhyAgentOS.skill_runtime.archive import ArchiveError, ArchiveValidator  # noqa: E402
from PhyAgentOS.skill_runtime.catalog import SkillCatalog  # noqa: E402
from PhyAgentOS.skill_runtime.installer import (  # noqa: E402
    InstallerError,
    NodeInstaller,
    SkillInstaller,
)
from PhyAgentOS.skill_runtime.manifest import ManifestError, load_manifest  # noqa: E402
from PhyAgentOS.skill_runtime.registry import (  # noqa: E402
    DownloadCache,
    RegistryArtifact,
    RegistryError,
)
from PhyAgentOS.skill_runtime.runtime_manifest import (  # noqa: E402
    normalize_arch,
    normalize_platform,
)
from PhyAgentOS.skill_runtime.state import RuntimeState, RuntimeStateStore  # noqa: E402


def _manifest() -> dict:
    return {
        "manifest_version": 2,
        "name": "move-arm-by-ee",
        "version": "1.0.0",
        "description": "Move an arm through Forge Tool APIs.",
        "skill_document": "SKILL.md",
        "gateway_url": "http://127.0.0.1:19002",
        "required_tools": ["motion.resolve_relative_pose", "motion.move_pose"],
        "profiles": {
            "mujoco": {
                "dataflow": "profiles/mujoco/dataflow.yaml",
                "required_binaries": ["gateway", "mujoco_sim"],
                "required_assets": [
                    "assets/piper_mujoco/scene.xml"
                ],
            }
        },
    }


def _bundle(root: Path, data: dict | None = None) -> Path:
    bundle = root / "move-arm-by-ee"
    bundle.mkdir(parents=True)
    (bundle / "SKILL.md").write_text("# Move arm\n", encoding="utf-8")
    (bundle / "skill.yaml").write_text(
        yaml.safe_dump(data or _manifest(), sort_keys=False),
        encoding="utf-8",
    )
    return bundle


def test_manifest_and_catalog_load_only_installed_bundle(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)

    manifest = SkillCatalog(tmp_path).get("move-arm-by-ee")

    assert manifest.bundle_root == bundle.resolve()
    assert manifest.profiles["mujoco"].dataflow == Path(
        "profiles/mujoco/dataflow.yaml"
    )
    assert [item.name for item in SkillCatalog(tmp_path).list()] == ["move-arm-by-ee"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("skill_document", "../SKILL.md"),
        ("skill_document", str(Path("/") / "SKILL.md")),
    ],
)
def test_manifest_rejects_unsafe_paths(tmp_path: Path, field: str, value: str) -> None:
    data = _manifest()
    data[field] = value
    bundle = _bundle(tmp_path, data)

    with pytest.raises(ManifestError, match="safe relative path"):
        load_manifest(bundle / "skill.yaml")


def test_manifest_rejects_unknown_fields(tmp_path: Path) -> None:
    data = _manifest()
    data["source_checkout"] = "forbidden"
    bundle = _bundle(tmp_path, data)

    with pytest.raises(ManifestError, match="unknown field"):
        load_manifest(bundle / "skill.yaml")


def test_runtime_state_store_replaces_json_atomically(tmp_path: Path) -> None:
    store = RuntimeStateStore(tmp_path)
    starting = RuntimeState(
        skill_name="move-arm-by-ee",
        profile="mujoco",
        status="starting",
        flow_name="paos-move-arm-by-ee-mujoco",
        gateway_url="http://127.0.0.1:19002",
    )
    store.save(starting)
    store.save(starting.with_status("running"))

    loaded = store.load("move-arm-by-ee")
    assert loaded is not None
    assert loaded.status == "running"
    assert json.loads((tmp_path / "move-arm-by-ee.json").read_text())["state_version"] == 1
    assert not list(tmp_path.glob(".move-arm-by-ee.json.*"))


def _distribution_archive(
    path: Path, files: dict[str, bytes], *, symlink: str | None = None
) -> str:
    embedded = {
        "files": [
            {"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in files.items()
        ]
    }
    with tarfile.open(path, "w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755 if name.endswith("gateway") else 0o644
            tar.addfile(info, io.BytesIO(data))
        encoded = json.dumps(embedded).encode()
        info = tarfile.TarInfo("archive-manifest.json")
        info.size = len(encoded)
        tar.addfile(info, io.BytesIO(encoded))
        if symlink:
            info = tarfile.TarInfo(symlink)
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tar.addfile(info)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _installable_skill_files(version: str = "1.0.0", *, valid: bool = True) -> dict[str, bytes]:
    manifest = {
        "manifest_version": 2,
        "name": "demo",
        "version": version,
        "description": "Demo Skill",
        "skill_document": "SKILL.md",
        "gateway_url": "http://127.0.0.1:9001",
        "required_tools": ["demo.run"],
        "profiles": {"local": {"dataflow": "flow.yaml"}},
    }
    if not valid:
        manifest["unknown"] = True
    return {
        "skill.yaml": yaml.safe_dump(manifest).encode(),
        "SKILL.md": b"# Demo\n",
    }


def _node_artifact_files(node_id: str, artifact_id: str, marker: bytes) -> dict[str, bytes]:
    file_digest = hashlib.sha256(marker).hexdigest()
    manifest = {
        "manifest_version": 1,
        "node_id": node_id,
        "artifact_id": artifact_id,
        "version": "1.0.0",
        "platform": normalize_platform(),
        "arch": normalize_arch(),
        "entrypoints": {node_id: node_id},
        "files": [{"path": "gateway", "size": len(marker), "sha256": file_digest}],
    }
    manifest["digest"] = hashlib.sha256(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    return {"node-manifest.json": json.dumps(manifest).encode(), "gateway": marker}


def test_archive_validator_rejects_links_and_duplicate_paths(tmp_path: Path) -> None:
    linked = tmp_path / "linked.tar.gz"
    _distribution_archive(linked, {"safe": b"ok"}, symlink="escape")
    with pytest.raises(ArchiveError, match="links are forbidden"):
        ArchiveValidator().extract(linked, tmp_path / "linked-out")
    assert not (tmp_path / "linked-out").exists()

    duplicate = tmp_path / "duplicate.tar.gz"
    with tarfile.open(duplicate, "w:gz") as tar:
        for name in ("file", "./file"):
            info = tarfile.TarInfo(name)
            info.size = 1
            tar.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(ArchiveError, match="duplicate archive path"):
        ArchiveValidator().extract(duplicate, tmp_path / "duplicate-out")

    collision = tmp_path / "collision.tar.gz"
    with tarfile.open(collision, "w:gz") as tar:
        for name in ("Config.yaml", "config.yaml"):
            info = tarfile.TarInfo(name)
            info.size = 1
            tar.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(ArchiveError, match="collide after normalization"):
        ArchiveValidator().extract(collision, tmp_path / "collision-out")


def test_download_cache_resumes_and_reuses_verified_archive(tmp_path: Path) -> None:
    payload = b"0123456789abcdef"
    digest = hashlib.sha256(payload).hexdigest()
    calls: list[str | None] = []

    class InterruptedStream(httpx.SyncByteStream):
        def __iter__(self):
            yield payload[:6]
            raise httpx.ReadError("connection lost")

    def handler(request: httpx.Request) -> httpx.Response:
        range_header = request.headers.get("Range")
        calls.append(range_header)
        if range_header is None:
            return httpx.Response(
                200,
                headers={"Content-Length": str(len(payload))},
                stream=InterruptedStream(),
            )
        offset = int(range_header.removeprefix("bytes=").removesuffix("-"))
        remainder = payload[offset:]
        return httpx.Response(
            206,
            headers={
                "Content-Length": str(len(remainder)),
                "Content-Range": f"bytes {offset}-{len(payload) - 1}/{len(payload)}",
            },
            content=remainder,
        )

    cache = DownloadCache(
        tmp_path, client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    artifact = RegistryArtifact("https://registry.test/archive", digest, len(payload))
    with pytest.raises(RegistryError, match="partial download was retained"):
        cache.download(artifact)
    result = cache.download(artifact)
    assert cache.download(artifact) == result
    assert result.read_bytes() == payload
    assert calls == [None, "bytes=6-"]


def test_skill_installer_failure_preserves_current_version(tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    installer = SkillInstaller(
        skills, state_store=RuntimeStateStore(tmp_path / "states")
    )
    good = tmp_path / "good.tar.gz"
    bad = tmp_path / "bad.tar.gz"
    good_digest = _distribution_archive(good, _installable_skill_files())
    bad_digest = _distribution_archive(
        bad, _installable_skill_files("2.0.0", valid=False)
    )
    installer.install(good, expected_sha256=good_digest)

    with pytest.raises(InstallerError):
        installer.install(bad, expected_sha256=bad_digest)

    assert SkillCatalog(skills).get("demo").version == "1.0.0"


def test_node_installer_versions_artifacts_independently(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    installer = NodeInstaller(
        root, state_store=RuntimeStateStore(tmp_path / "states")
    )
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"
    first_sha = _distribution_archive(
        first, _node_artifact_files("gateway", "gateway-one", b"one")
    )
    second_sha = _distribution_archive(
        second, _node_artifact_files("gateway", "gateway-two", b"two")
    )

    installer.install(first, expected_sha256=first_sha)
    installer.install(second, expected_sha256=second_sha)
    assert installer.load("gateway", "gateway-one").artifact_id == "gateway-one"
    assert installer.load("gateway", "gateway-two").artifact_id == "gateway-two"


def test_node_lock_schema_is_strict(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    skill = _manifest()
    skill["artifacts"] = {
        "resolver": "registry",
        "nodes": {
            "gateway": {
                "artifact_id": "gateway-one",
                "version": "1.0.0",
                "platform": normalize_platform(),
                "arch": normalize_arch(),
                "digest": "0" * 64,
                "unexpected": True,
            }
        }
    }
    (bundle / "skill.yaml").write_text(yaml.safe_dump(skill))

    with pytest.raises(ManifestError, match="unknown field"):
        load_manifest(bundle / "skill.yaml")
