from __future__ import annotations

import hashlib
import io
import json
import sys
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parents[1]))

ROOT = Path(__file__).parents[1]

from PhyAgentOS.config.schema import (  # noqa: E402
    DEFAULT_RESOURCE_REGISTRY_URL,
    ResourceRegistryConfig,
)
from PhyAgentOS.skill_runtime import registry as registry_module  # noqa: E402
from PhyAgentOS.skill_runtime.archive import ArchiveError, ArchiveValidator  # noqa: E402
from PhyAgentOS.skill_runtime.catalog import SkillCatalog  # noqa: E402
from PhyAgentOS.skill_runtime.installer import (  # noqa: E402
    InstallerError,
    NodeInstaller,
    SkillInstaller,
)
from PhyAgentOS.skill_runtime.manifest import (  # noqa: E402
    ManifestError,
    NodeLock,
    load_manifest,
)
from PhyAgentOS.skill_runtime.registry import (  # noqa: E402
    DownloadCache,
    RegistryArtifact,
    RegistryClient,
    RegistryError,
    get_registry_base_url,
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


def test_move_arm_example_locks_single_file_github_assets() -> None:
    manifest = load_manifest(
        ROOT / "examples/forge-skills/move-arm-by-ee/skill.yaml"
    )
    locks = manifest.artifacts.nodes.values()

    assert all(lock.artifact_type == "executable_tar_gz" for lock in locks)
    assert all(len(lock.sha256) == 64 for lock in locks)
    assert {lock.entrypoint for lock in locks} == {
        path.as_posix()
        for path in manifest.profiles["mujoco"].required_binaries
    }


def test_move_arm_example_contains_closed_robot_asset_graph() -> None:
    bundle = ROOT / "examples/forge-skills/move-arm-by-ee"
    manifest = load_manifest(bundle / "skill.yaml")
    for relative in manifest.profiles["mujoco"].required_assets:
        assert manifest.resolve_bundle_path(relative).is_file()

    scene = ET.parse(bundle / "assets/piper_mujoco/scene.xml").getroot()
    model_file = scene.find("./asset/model").attrib["file"]
    model_path = bundle / "assets/piper_mujoco" / model_file
    assert model_path.is_file()

    model = ET.parse(model_path).getroot()
    mesh_dir = model.find("./compiler").attrib["meshdir"]
    for mesh in model.findall("./asset/mesh"):
        assert (model_path.parent / mesh_dir / mesh.attrib["file"]).is_file()

    urdf = ET.parse(bundle / "assets/piper_with_gripper.urdf").getroot()
    for mesh in urdf.findall(".//mesh"):
        assert (bundle / "assets" / mesh.attrib["filename"]).is_file()

    assert (bundle / "assets/LICENSE.piper_ros-noetic").is_file()
    assert (bundle / "assets/piper_mujoco/LICENSE").is_file()
    assert (bundle / "THIRD_PARTY_NOTICES.md").is_file()

    archive_manifest = json.loads(
        (bundle / "archive-manifest.json").read_text(encoding="utf-8")
    )
    listed = {item["path"]: item for item in archive_manifest["files"]}
    actual = {
        path.relative_to(bundle).as_posix(): path
        for path in bundle.rglob("*")
        if path.is_file() and path.name != "archive-manifest.json"
    }
    assert set(listed) == set(actual)
    for relative, path in actual.items():
        data = path.read_bytes()
        assert listed[relative]["size"] == len(data)
        assert listed[relative]["sha256"] == hashlib.sha256(data).hexdigest()


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


def test_registry_distinguishes_verified_skill_and_direct_node() -> None:
    digest = "a" * 64
    responses = {
        "/v1/skills/demo": {
            "download_url": "https://tos.example/demo.tar.gz",
            "sha256": digest,
            "size": 42,
            "mode": "verified",
        },
        "/v1/forge-nodes/gateway-one": {
            "download_url": "https://github.com/example/gateway.tar.gz",
            "artifact_id": "gateway-one",
            "mode": "direct",
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=responses[request.url.path])

    with RegistryClient(
        "https://registry.example",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    ) as registry:
        skill = registry.skill("demo")
        node = registry.node("gateway-one")

    assert skill.sha256 == digest
    assert skill.size == 42
    assert node.sha256 is None
    assert node.size is None


def test_resource_registry_has_public_default_and_environment_override(monkeypatch) -> None:
    monkeypatch.delenv("PAOS_RESOURCE_REGISTRY_URL", raising=False)
    monkeypatch.setattr(
        registry_module,
        "load_config",
        lambda: type(
            "Config",
            (),
            {"resource_registry": ResourceRegistryConfig(url="")},
        )(),
    )

    assert ResourceRegistryConfig().url == DEFAULT_RESOURCE_REGISTRY_URL
    assert get_registry_base_url() == DEFAULT_RESOURCE_REGISTRY_URL

    monkeypatch.setenv("PAOS_RESOURCE_REGISTRY_URL", "http://127.0.0.1:8080/")
    assert get_registry_base_url() == "http://127.0.0.1:8080"


def test_direct_download_cache_does_not_require_size_or_sha256(tmp_path: Path) -> None:
    payload = b"direct release asset"
    events: list[tuple[str, int, int | None]] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    cache = DownloadCache(
        tmp_path,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        progress=lambda event, _artifact, downloaded, total: events.append(
            (event, downloaded, total)
        ),
    )
    artifact = RegistryArtifact("https://example.test/release.tar.gz", mode="direct")

    result = cache.download(artifact)

    assert result.read_bytes() == payload
    assert cache.download(artifact) == result
    assert ("advance", len(payload), len(payload)) in events
    assert ("complete", len(payload), len(payload)) in events
    assert events[-1] == ("cached", len(payload), len(payload))


def test_verified_download_rejects_skill_sha256_mismatch(tmp_path: Path) -> None:
    payload = b"tampered Skill Bundle"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Length": str(len(payload))},
            content=payload,
        )

    cache = DownloadCache(
        tmp_path,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    artifact = RegistryArtifact(
        "https://tos.example/skill.tar.gz",
        "0" * 64,
        len(payload),
        mode="verified",
    )

    with pytest.raises(RegistryError, match="sha256 does not match"):
        cache.download(artifact)


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
    first = tmp_path / "gateway-one.tar.gz"
    second = tmp_path / "gateway-two.tar.gz"
    with tarfile.open(first, "w:gz") as archive:
        info = tarfile.TarInfo("gateway")
        info.size = 3
        archive.addfile(info, io.BytesIO(b"one"))
    with tarfile.open(second, "w:gz") as archive:
        info = tarfile.TarInfo("gateway")
        info.size = 3
        archive.addfile(info, io.BytesIO(b"two"))
    first_lock = NodeLock.from_dict(
        "gateway",
        {
            "artifact_id": "gateway-one",
            "version": "1.0.0",
            "platform": normalize_platform(),
            "arch": normalize_arch(),
            "artifact_type": "executable_tar_gz",
            "entrypoint": "gateway",
            "sha256": hashlib.sha256(first.read_bytes()).hexdigest(),
        },
    )
    second_lock = NodeLock.from_dict(
        "gateway",
        {
            "artifact_id": "gateway-two",
            "version": "2.0.0",
            "platform": normalize_platform(),
            "arch": normalize_arch(),
            "artifact_type": "executable_tar_gz",
            "entrypoint": "gateway",
            "sha256": hashlib.sha256(second.read_bytes()).hexdigest(),
        },
    )

    installer.install(first, first_lock)
    installer.install(second, second_lock)
    assert installer.load(first_lock).read_bytes() == b"one"
    assert installer.load(second_lock).read_bytes() == b"two"


def test_node_installer_rejects_archive_with_multiple_files(tmp_path: Path) -> None:
    archive_path = tmp_path / "gateway.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for name in ("gateway", "unexpected"):
            info = tarfile.TarInfo(name)
            info.size = 1
            archive.addfile(info, io.BytesIO(b"x"))
    lock = NodeLock.from_dict(
        "gateway",
        {
            "artifact_id": "gateway-one",
            "version": "1.0.0",
            "platform": normalize_platform(),
            "arch": normalize_arch(),
            "artifact_type": "executable_tar_gz",
            "entrypoint": "gateway",
            "sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        },
    )

    with pytest.raises(InstallerError, match="exactly one executable"):
        NodeInstaller(
            tmp_path / "runtime",
            state_store=RuntimeStateStore(tmp_path / "states"),
        ).install(archive_path, lock)


def test_node_lock_sha256_and_executable_metadata_are_required(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    skill = _manifest()
    skill["artifacts"] = {
        "resolver": "registry",
        "nodes": {
            "gateway": {
                "artifact_id": "gateway-1.0.2-linux-x86_64",
                "version": "1.0.2",
                "platform": normalize_platform(),
                "arch": normalize_arch(),
            }
        },
    }
    (bundle / "skill.yaml").write_text(yaml.safe_dump(skill))

    with pytest.raises(ManifestError, match="artifact_type must be a non-empty string"):
        load_manifest(bundle / "skill.yaml")


def test_node_lock_reserves_future_artifact_types_without_guessing() -> None:
    with pytest.raises(ManifestError, match="reserved for future installers"):
        NodeLock.from_dict(
            "gateway",
            {
                "artifact_id": "gateway-one",
                "version": "1.0.0",
                "platform": normalize_platform(),
                "arch": normalize_arch(),
                "artifact_type": "archive",
                "entrypoint": "gateway",
                "sha256": "0" * 64,
            },
        )


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
                "artifact_type": "executable_tar_gz",
                "entrypoint": "gateway",
                "sha256": "0" * 64,
                "unexpected": True,
            }
        }
    }
    (bundle / "skill.yaml").write_text(yaml.safe_dump(skill))

    with pytest.raises(ManifestError, match="unknown field"):
        load_manifest(bundle / "skill.yaml")
