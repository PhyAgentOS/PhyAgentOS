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

from PhyAgentOS.cli.commands import _install_skill_from_registry
from PhyAgentOS.skill_runtime import catalog as catalog_module
from PhyAgentOS.skill_runtime import installer as installer_module
from PhyAgentOS.skill_runtime import registry as registry_module
from PhyAgentOS.skill_runtime import state as state_module
from PhyAgentOS.skill_runtime.catalog import SkillCatalog
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


def _skill_bundle(path: Path, node_sha256: str, *, version: str = "1.0.0") -> str:
    manifest = {
        "manifest_version": 2,
        "name": "demo",
        "version": version,
        "description": "Registry install acceptance",
        "skill_document": "SKILL.md",
        "gateway_url": "http://127.0.0.1:19002",
        "required_tools": ["demo.run"],
        "profiles": {
            "local": {
                "dataflow": "profiles/local/dataflow.yaml",
                "required_binaries": ["gateway"],
            }
        },
        "artifacts": {
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
        },
    }
    return _archive(
        path,
        {
            "skill.yaml": yaml.safe_dump(manifest, sort_keys=False).encode(),
            "SKILL.md": b"# Demo\n",
            "profiles/local/dataflow.yaml": (
                b"nodes:\n  - id: gateway\n    path: ${FORGE_RUNTIME_BIN}/gateway\n"
            ),
        },
    )


def test_registry_install_skips_ready_nodes_and_prepares_environment(
    tmp_path: Path, monkeypatch
) -> None:
    skill_archive = tmp_path / "skill.tar.gz"
    node_archive = tmp_path / "gateway.tar.gz"
    node_sha256 = _node_archive(node_archive)
    skill_sha = _skill_bundle(skill_archive, node_sha256)
    current = {"archive": skill_archive, "sha256": skill_sha}
    skills = tmp_path / "home/skills"
    runtime = tmp_path / "home/forge_runtime"
    states = tmp_path / "home/run/skills"

    monkeypatch.setattr(installer_module, "get_skill_bundle_root", lambda: skills)
    monkeypatch.setattr(installer_module, "get_forge_runtime_root", lambda: runtime)
    monkeypatch.setattr(catalog_module, "get_skill_bundle_root", lambda: skills)
    monkeypatch.setattr(state_module, "get_skill_runtime_state_dir", lambda: states)
    monkeypatch.setattr(registry_module, "get_artifact_cache_root", lambda: tmp_path / "cache")

    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlparse(self.path).path
            requests.append(path)
            base = f"http://127.0.0.1:{self.server.server_port}"
            if path == "/v1/skills":
                self._json({"items": [{"name": "demo", "description": "acceptance"}]})
            elif path == "/v1/skills/demo":
                self._json(
                    {
                        "download_url": f"{base}/assets/skill.tar.gz",
                        "sha256": current["sha256"],
                        "size": current["archive"].stat().st_size,
                        "mode": "verified",
                    }
                )
            elif path == "/v1/forge-nodes/gateway-one":
                self._json(
                    {
                        "download_url": f"{base}/assets/gateway.tar.gz",
                        "artifact_id": "gateway-one",
                        "mode": "direct",
                    }
                )
            elif path == "/assets/skill.tar.gz":
                self._bytes(current["archive"].read_bytes())
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
    try:
        with registry_module.RegistryClient() as registry:
            assert registry.search_skills("demo")[0]["name"] == "demo"
        _install_skill_from_registry("demo")
        manifest = SkillCatalog(skills).get("demo")
        assert NodeInstaller(runtime).satisfies(manifest.artifacts.nodes["gateway"])
        environment = SkillEnvironmentBuilder(runtime).prepare(manifest, "local")
        assert (environment / "gateway").is_symlink()

        _install_skill_from_registry("demo")
        assert requests.count("/v1/forge-nodes/gateway-one") == 1
        assert SkillCatalog(skills).get("demo").version == "1.0.0"

        bad_skill = tmp_path / "skill-v2.tar.gz"
        current["sha256"] = _skill_bundle(bad_skill, "f" * 64, version="2.0.0")
        current["archive"] = bad_skill
        with pytest.raises(Exception, match="sha256 does not match Skill lock"):
            _install_skill_from_registry("demo")
        assert SkillCatalog(skills).get("demo").version == "1.0.0"

        good_skill_v2 = tmp_path / "skill-v2-good.tar.gz"
        current["sha256"] = _skill_bundle(good_skill_v2, node_sha256, version="2.0.0")
        current["archive"] = good_skill_v2
        _install_skill_from_registry("demo")
    finally:
        server.shutdown()
        thread.join()
        server.server_close()
    assert SkillCatalog(skills).get("demo").version == "2.0.0"
