import subprocess
import sys
from pathlib import Path

from PhyAgentOS.skill_runtime.catalog import SkillCatalog
from PhyAgentOS.skill_runtime.installer import SkillInstaller
from PhyAgentOS.skill_runtime.integration import discover_active_runtime
from PhyAgentOS.skill_runtime.manager import RuntimeStatusReport
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
