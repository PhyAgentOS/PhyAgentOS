from __future__ import annotations

import hashlib
import io
import json
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pytest
import yaml
from typer.testing import CliRunner

from PhyAgentOS.cli.commands import (
    _install_skill_from_local_bundle,
    _resolve_local_bundle_path,
    _resolve_skill_install_source,
    app,
)
from PhyAgentOS.skill_runtime import catalog as catalog_module
from PhyAgentOS.skill_runtime import installer as installer_module
from PhyAgentOS.skill_runtime import registry as registry_module
from PhyAgentOS.skill_runtime import state as state_module
from PhyAgentOS.skill_runtime.catalog import SkillCatalog, SkillNotFoundError
from PhyAgentOS.skill_runtime.installer import NodeInstaller, SkillEnvironmentBuilder
from PhyAgentOS.skill_runtime.runtime_manifest import normalize_arch, normalize_platform


def _archive(path: Path, files: dict[str, bytes], *, executable: set[str] | None = None) -> str:
    manifest = {
        "files": [
            {"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in files.items()
        ]
    }
    with tarfile.open(path, "w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755 if name in (executable or set()) else 0o644
            tar.addfile(info, io.BytesIO(data))
        encoded = json.dumps(manifest).encode()
        info = tarfile.TarInfo("archive-manifest.json")
        info.size = len(encoded)
        tar.addfile(info, io.BytesIO(encoded))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _node_archive(path: Path) -> str:
    binary = b"#!/bin/sh\nexit 0\n"
    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo("gateway")
        info.size = len(binary)
        info.mode = 0o755
        archive.addfile(info, io.BytesIO(binary))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(node_sha256: str | None, *, version: str) -> dict:
    manifest = {
        "manifest_version": 2,
        "name": "demo",
        "version": version,
        "description": "Local install acceptance",
        "skill_document": "SKILL.md",
        "gateway_url": "http://127.0.0.1:19002",
        "required_tools": ["demo.run"],
        "profiles": {
            "local": {
                "dataflow": "profiles/local/dataflow.yaml",
                "required_binaries": ["gateway"] if node_sha256 else [],
            }
        },
    }
    if node_sha256:
        manifest["artifacts"] = {
            "resolver": "registry",
            "nodes": {
                "gateway": {
                    "artifact_id": "gateway-one",
                    "version": "1.0.0",
                    "platform": normalize_platform(),
                    "arch": normalize_arch(),
                    "artifact_type": "executable_tar_gz",
                    "entrypoint": "gateway",
                    "sha256": node_sha256,
                }
            },
        }
    return manifest


def _skill_bundle(path: Path, node_sha256: str | None, *, version: str = "1.0.0") -> str:
    return _archive(
        path,
        {
            "skill.yaml": yaml.safe_dump(
                _manifest(node_sha256, version=version), sort_keys=False
            ).encode(),
            "SKILL.md": b"# Demo\n",
            "profiles/local/dataflow.yaml": b"nodes: []\n",
        },
    )


def _tampered_bundle(path: Path, original: Path) -> None:
    """Copy the original manifest but change SKILL.md bytes."""
    with tarfile.open(original, "r:gz") as tar:
        handle = tar.extractfile("archive-manifest.json")
        assert handle is not None
        original_manifest = handle.read()
    with tarfile.open(path, "w:gz") as tar:
        for name, data in (
            ("skill.yaml", yaml.safe_dump(_manifest(None, version="1.0.0"), sort_keys=False).encode()),
            ("SKILL.md", b"# demo\n"),
            ("profiles/local/dataflow.yaml", b"nodes: []\n"),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
        info = tarfile.TarInfo("archive-manifest.json")
        info.size = len(original_manifest)
        tar.addfile(info, io.BytesIO(original_manifest))


def _isolate(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    """Redirect every runtime root into a per-test home."""
    skills = tmp_path / "home/skills"
    runtime = tmp_path / "home/forge_runtime"
    states = tmp_path / "home/run/skills"
    monkeypatch.setattr(installer_module, "get_skill_bundle_root", lambda: skills)
    monkeypatch.setattr(installer_module, "get_forge_runtime_root", lambda: runtime)
    monkeypatch.setattr(catalog_module, "get_skill_bundle_root", lambda: skills)
    monkeypatch.setattr(state_module, "get_skill_runtime_state_dir", lambda: states)
    monkeypatch.setattr(registry_module, "get_artifact_cache_root", lambda: tmp_path / "cache")
    return skills, runtime


def _node_registry(monkeypatch, node_archive: Path) -> tuple[list[str], ThreadingHTTPServer]:
    """Serve only the node endpoints and record every request path."""
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlparse(self.path).path
            requests.append(path)
            if path == "/v1/forge-nodes/gateway-one":
                base = f"http://127.0.0.1:{self.server.server_port}"
                self._json(
                    {
                        "download_url": f"{base}/assets/gateway.tar.gz",
                        "artifact_id": "gateway-one",
                        "mode": "direct",
                    }
                )
            elif path == "/assets/gateway.tar.gz":
                self._bytes(node_archive.read_bytes())
            else:
                self.send_error(404)

        def _json(self, value: dict) -> None:
            self._bytes(json.dumps(value).encode(), "application/json")

        def _bytes(self, value: bytes, content_type: str = "application/gzip") -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(value)))
            self.end_headers()
            self.wfile.write(value)

        def log_message(self, _format: str, *_args) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv(
        "PAOS_RESOURCE_REGISTRY_URL",
        f"http://127.0.0.1:{server.server_port}",
    )
    return requests, server


def _stop_server(server: ThreadingHTTPServer) -> None:
    server.shutdown()
    server.server_close()


def test_local_bundle_install_resolves_nodes_from_registry(tmp_path: Path, monkeypatch) -> None:
    skill_archive = tmp_path / "skill.tar.gz"
    node_archive = tmp_path / "gateway.tar.gz"
    node_sha256 = _node_archive(node_archive)
    _skill_bundle(skill_archive, node_sha256)
    skills, runtime = _isolate(tmp_path, monkeypatch)
    requests, server = _node_registry(monkeypatch, node_archive)
    try:
        _install_skill_from_local_bundle(skill_archive)
        manifest = SkillCatalog(skills).get("demo")
        assert manifest.version == "1.0.0"
        assert NodeInstaller(runtime).satisfies(manifest.artifacts.nodes["gateway"])
        environment = SkillEnvironmentBuilder(runtime).prepare(manifest, "local")
        assert (environment / "gateway").is_symlink()
        assert "/v1/skills" not in requests
        assert "/v1/skills/demo" not in requests
        assert "/v1/forge-nodes/gateway-one" in requests
        assert "/assets/gateway.tar.gz" in requests
    finally:
        _stop_server(server)


def test_environment_digest_includes_profile_files(tmp_path: Path, monkeypatch) -> None:
    """同版本 profile 文件变化必须触发环境重渲染（渲染副本不得滞留旧内容）。"""
    skill_archive = tmp_path / "skill.tar.gz"
    node_archive = tmp_path / "gateway.tar.gz"
    node_sha256 = _node_archive(node_archive)
    _skill_bundle(skill_archive, node_sha256)
    skills, runtime = _isolate(tmp_path, monkeypatch)
    requests, server = _node_registry(monkeypatch, node_archive)
    try:
        _install_skill_from_local_bundle(skill_archive)
        manifest = SkillCatalog(skills).get("demo")
        builder = SkillEnvironmentBuilder(runtime)

        first_bin = builder.prepare(manifest, "local")
        first_rendered = first_bin.parent / "launch" / "profiles/local/dataflow.yaml"
        assert first_rendered.read_text() == "nodes: []\n"

        # 模拟同版本重装：bundle 内 dataflow 内容变化
        (manifest.bundle_root / "profiles/local/dataflow.yaml").write_text(
            "nodes: []\npath: ${PAOS_SKILL_NAME}-${PAOS_SKILL_VERSION}\n",
            encoding="utf-8",
        )

        second_bin = builder.prepare(manifest, "local")
        second_rendered = second_bin.parent / "launch" / "profiles/local/dataflow.yaml"
        assert second_bin.parent != first_bin.parent  # digest 变化 → 新环境目录
        assert "path: demo-1.0.0" in second_rendered.read_text()
    finally:
        _stop_server(server)


def test_local_bundle_install_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    skill_archive = tmp_path / "skill.tar.gz"
    node_archive = tmp_path / "gateway.tar.gz"
    _skill_bundle(skill_archive, _node_archive(node_archive))
    skills, _runtime = _isolate(tmp_path, monkeypatch)
    requests, server = _node_registry(monkeypatch, node_archive)
    try:
        _install_skill_from_local_bundle(skill_archive)
        before = len(requests)
        _install_skill_from_local_bundle(skill_archive)
        assert len(requests) == before
        assert requests.count("/v1/forge-nodes/gateway-one") == 1
        assert SkillCatalog(skills).get("demo").version == "1.0.0"
    finally:
        _stop_server(server)


def test_local_bundle_install_without_nodes_needs_no_registry(
    tmp_path: Path, monkeypatch
) -> None:
    skill_archive = tmp_path / "skill.tar.gz"
    _skill_bundle(skill_archive, None)
    skills, _runtime = _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("PAOS_RESOURCE_REGISTRY_URL", "http://127.0.0.1:1")
    _install_skill_from_local_bundle(skill_archive)
    assert SkillCatalog(skills).get("demo").version == "1.0.0"


def test_local_bundle_install_rejects_tampered_bundle_preserving_installed_version(
    tmp_path: Path, monkeypatch
) -> None:
    skill_archive = tmp_path / "skill.tar.gz"
    _skill_bundle(skill_archive, None)
    skills, _runtime = _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("PAOS_RESOURCE_REGISTRY_URL", "http://127.0.0.1:1")
    _install_skill_from_local_bundle(skill_archive)
    assert SkillCatalog(skills).get("demo").version == "1.0.0"

    tampered = tmp_path / "tampered.tar.gz"
    _tampered_bundle(tampered, skill_archive)
    with pytest.raises(Exception, match="file sha256 mismatch"):
        _install_skill_from_local_bundle(tampered)
    assert SkillCatalog(skills).get("demo").version == "1.0.0"


def test_local_bundle_install_rejects_garbage_archive(tmp_path: Path, monkeypatch) -> None:
    garbage = tmp_path / "garbage.tar.gz"
    garbage.write_bytes(b"not a tar archive")
    skills, _runtime = _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("PAOS_RESOURCE_REGISTRY_URL", "http://127.0.0.1:1")
    with pytest.raises(Exception):
        _install_skill_from_local_bundle(garbage)
    with pytest.raises(SkillNotFoundError):
        SkillCatalog(skills).get("demo")


def test_resolve_skill_install_source_classification(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    bundle = tmp_path / "demo.tar.gz"
    bundle.write_bytes(b"x")
    notes = tmp_path / "notes.txt"
    notes.write_text("notes", encoding="utf-8")
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)

    assert _resolve_skill_install_source("demo") == "demo"
    assert _resolve_skill_install_source("~/demo.tar.gz") == bundle
    assert _resolve_skill_install_source(str(bundle)) == bundle
    with pytest.raises(RuntimeError, match="file not found"):
        _resolve_skill_install_source("demo.tar.gz")
    with pytest.raises(RuntimeError, match="file not found"):
        _resolve_skill_install_source("sub/dir/x.tar.gz")
    with pytest.raises(RuntimeError, match="is not a file"):
        _resolve_skill_install_source(str(tmp_path))
    with pytest.raises(RuntimeError, match="must be a .tar.gz"):
        _resolve_skill_install_source(str(notes))


def test_resolve_local_bundle_path_explicit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    bundle = tmp_path / "demo.tar.gz"
    bundle.write_bytes(b"x")
    notes = tmp_path / "notes.txt"
    notes.write_text("notes", encoding="utf-8")
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)

    assert _resolve_local_bundle_path(str(bundle)) == bundle
    assert _resolve_local_bundle_path("~/demo.tar.gz") == bundle
    with pytest.raises(RuntimeError, match="file not found"):
        _resolve_local_bundle_path("missing.tar.gz")
    with pytest.raises(RuntimeError, match="is not a file"):
        _resolve_local_bundle_path(str(empty))
    with pytest.raises(RuntimeError, match="must be a .tar.gz"):
        _resolve_local_bundle_path(str(notes))


def test_skill_install_cli_accepts_local_bundle(tmp_path: Path, monkeypatch) -> None:
    skill_archive = tmp_path / "skill.tar.gz"
    node_archive = tmp_path / "gateway.tar.gz"
    _skill_bundle(skill_archive, _node_archive(node_archive))
    skills, _runtime = _isolate(tmp_path, monkeypatch)
    _requests, server = _node_registry(monkeypatch, node_archive)
    try:
        result = CliRunner().invoke(app, ["skill", "install", str(skill_archive), "--yes"])
        assert result.exit_code == 0
        assert "Installed Skill" in result.stdout
        assert SkillCatalog(skills).get("demo").version == "1.0.0"
    finally:
        _stop_server(server)


def test_skill_install_cli_local_flag(tmp_path: Path, monkeypatch) -> None:
    skill_archive = tmp_path / "skill.tar.gz"
    node_archive = tmp_path / "gateway.tar.gz"
    _skill_bundle(skill_archive, _node_archive(node_archive))
    skills, _runtime = _isolate(tmp_path, monkeypatch)
    _requests, server = _node_registry(monkeypatch, node_archive)
    try:
        result = CliRunner().invoke(
            app, ["skill", "install", "--local", str(skill_archive), "--yes"]
        )
        assert result.exit_code == 0
        assert "Installed Skill" in result.stdout
        assert SkillCatalog(skills).get("demo").version == "1.0.0"

        missing = CliRunner().invoke(app, ["skill", "install", "--local", "nope.tar.gz"])
        assert missing.exit_code == 1
        assert "file not found" in missing.stdout
    finally:
        _stop_server(server)


def test_skill_install_cli_help_documents_local_bundle() -> None:
    result = CliRunner().invoke(app, ["skill", "install", "--help"])
    assert result.exit_code == 0
    assert ".tar.gz" in result.stdout
    assert "Registry" in result.stdout
    assert "--local" in result.stdout
