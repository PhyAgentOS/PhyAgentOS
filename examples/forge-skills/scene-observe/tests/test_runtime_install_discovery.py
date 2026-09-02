import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PhyAgentOS.skill_runtime.catalog import SkillCatalog
from PhyAgentOS.skill_runtime.installer import SkillInstaller
from PhyAgentOS.skill_runtime.integration import discover_active_runtime
from PhyAgentOS.skill_runtime.manager import RuntimeManager, RuntimeStatusReport
from PhyAgentOS.skill_runtime.state import RuntimeState, RuntimeStateStore

BUNDLE_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TOOLS = {
    "scene.observe",
    "scene.understand",
    "grasp.propose",
    "manipulation.prepare",
    "object.acquire",
    "object.place",
}


def _package_bundle(tmp_path: Path) -> Path:
    output = tmp_path / "dist"
    command = [
        sys.executable,
        str(Path(__file__).resolve().parents[4] / "scripts" / "package_skill.py"),
        str(BUNDLE_ROOT),
        "--output-dir",
        str(output),
        "--force",
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    archive = output / "scene-observe-0.7.0.tar.gz"
    assert archive.is_file(), completed.stdout
    return archive


def test_manifest_v2_bundle_installs_and_catalog_reloads_required_tools(tmp_path):
    archive = _package_bundle(tmp_path)
    state_store = RuntimeStateStore(tmp_path / "run")
    installer = SkillInstaller(tmp_path / "skills", state_store=state_store)

    manifest = installer.install(archive)
    reloaded = SkillCatalog(tmp_path / "skills").get("scene-observe")

    assert manifest == reloaded
    assert manifest.name == "scene-observe"
    assert manifest.manifest_version == 2
    assert set(manifest.required_tools) == EXPECTED_TOOLS
    assert manifest.profiles["fake"].dataflow.as_posix() == "profiles/fake/dataflow.yaml"
    assert (tmp_path / "skills" / "scene-observe" / "SKILL.md").is_file()


class HealthyRuntimeManager:
    def __init__(self, state, manifest):
        self.state = state
        self.manifest = manifest
        self.calls = []

    def status(self, skill_name):
        self.calls.append(skill_name)
        return RuntimeStatusReport(
            state=self.state if skill_name == self.manifest.name else None,
            flow_running=True,
            gateway_ready=True,
            tool_contexts={tool_id: True for tool_id in self.manifest.required_tools},
        )


def test_discovery_publishes_only_one_healthy_installed_runtime(tmp_path):
    archive = _package_bundle(tmp_path)
    state_store = RuntimeStateStore(tmp_path / "run")
    SkillInstaller(tmp_path / "skills", state_store=state_store).install(archive)
    catalog = SkillCatalog(tmp_path / "skills")
    manifest = catalog.get("scene-observe")
    state = RuntimeState(
        skill_name=manifest.name,
        profile="fake",
        status="running",
        flow_name="paos-scene-observe-fake",
        gateway_url=manifest.gateway_url,
        gateway_identity="gateway_fake_fixture",
    )
    state_store.save(state)
    manager = HealthyRuntimeManager(state, manifest)

    active = discover_active_runtime(
        catalog=catalog,
        state_store=state_store,
        manager=manager,
    )

    assert active is not None
    assert active.skill_name == "scene-observe"
    assert active.skill_version == "0.7.0"
    assert active.profile == "fake"
    assert active.gateway_identity == "gateway_fake_fixture"
    assert manager.calls == ["scene-observe"]


def test_discovery_fail_closed_for_non_ready_runtime(tmp_path):
    archive = _package_bundle(tmp_path)
    state_store = RuntimeStateStore(tmp_path / "run")
    SkillInstaller(tmp_path / "skills", state_store=state_store).install(archive)
    catalog = SkillCatalog(tmp_path / "skills")
    manifest = catalog.get("scene-observe")
    state = RuntimeState(
        skill_name=manifest.name,
        profile="fake",
        status="starting",
        flow_name="paos-scene-observe-fake",
        gateway_url=manifest.gateway_url,
    )
    state_store.save(state)

    class NotReadyManager:
        def status(self, skill_name):
            return RuntimeStatusReport(
                state=state,
                flow_running=False,
                gateway_ready=False,
                tool_contexts={tool_id: False for tool_id in manifest.required_tools},
            )

    assert discover_active_runtime(
        catalog=catalog,
        state_store=state_store,
        manager=NotReadyManager(),
    ) is None


def test_runtime_manager_status_reads_http_health_and_fails_closed_on_missing_context(tmp_path):
    requests = []
    missing_tool = "object.place"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            requests.append(self.path)
            if self.path == "/tools":
                payload = {"ok": True, "data": {"gateway_identity": "gateway-http"}}
            elif self.path.endswith("/context"):
                tool_id = self.path[len("/tools/") : -len("/context")]
                payload = {
                    "ok": True,
                    "data": {
                        "ready": tool_id != missing_tool,
                        "binding_error": None if tool_id != missing_tool else "provider unavailable",
                    },
                }
            else:
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):  # noqa: A002
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        archive = _package_bundle(tmp_path)
        state_store = RuntimeStateStore(tmp_path / "run")
        SkillInstaller(tmp_path / "skills", state_store=state_store).install(archive)
        catalog = SkillCatalog(tmp_path / "skills")
        manifest = catalog.get("scene-observe")
        object.__setattr__(manifest, "gateway_url", f"http://127.0.0.1:{server.server_port}")

        class LocalCatalog:
            def get(self, skill_name):
                assert skill_name == manifest.name
                return manifest

        state = RuntimeState(
            skill_name=manifest.name,
            profile="fake",
            status="running",
            flow_name="paos-scene-observe-fake",
            gateway_url=manifest.gateway_url,
        )
        state_store.save(state)
        manager = RuntimeManager(
            catalog=LocalCatalog(), state_store=state_store, poll_interval_s=0.01
        )
        manager._flow_running = lambda flow_name: True

        report = manager.status(manifest.name)
        assert report.gateway_ready is True
        assert report.tool_contexts[missing_tool] is False
        assert report.state is not None
        assert report.state.status == "failed"
        assert "Tool context is not ready" in (report.state.last_error or "")
        assert f"/tools/{missing_tool}/context" in requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
