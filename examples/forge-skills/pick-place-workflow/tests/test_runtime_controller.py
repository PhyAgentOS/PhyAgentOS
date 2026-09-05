from dataclasses import dataclass

import pytest
from PhyAgentOS.skill_runtime.integration import ActiveRuntimeRegistry, SkillRuntimeController
from PhyAgentOS.skill_runtime.manager import RuntimeStatusReport
from PhyAgentOS.skill_runtime.state import RuntimeState, RuntimeStateStore


@dataclass(frozen=True)
class Manifest:
    name: str
    version: str
    gateway_url: str


class Catalog:
    def __init__(self, *manifests):
        self.manifests = {item.name: item for item in manifests}

    def get(self, name):
        return self.manifests[name]


class Manager:
    def __init__(self, manifests, state_store, *, failing=()):
        self.manifests = manifests
        self.state_store = state_store
        self.failing = set(failing)
        self.started = []
        self.stopped = []

    def start(self, skill_name, profile):
        self.started.append((skill_name, profile))
        if skill_name in self.failing:
            raise RuntimeError(f"failed to start {skill_name}")
        manifest = self.manifests[skill_name]
        state = RuntimeState(
            skill_name=skill_name,
            profile=profile,
            status="running",
            flow_name=f"paos-{skill_name}-{profile}",
            gateway_url=manifest.gateway_url,
            gateway_identity=f"gateway-{skill_name}",
        )
        self.state_store.save(state)
        return state

    def status(self, skill_name):
        state = self.state_store.load(skill_name)
        return RuntimeStatusReport(
            state=state,
            flow_running=state is not None and state.status == "running",
            gateway_ready=state is not None and state.status == "running",
            tool_contexts={"tool": True} if state is not None and state.status == "running" else {},
        )

    def stop(self, skill_name, *, force=False):
        self.stopped.append((skill_name, force))
        state = self.state_store.load(skill_name)
        if state is not None:
            self.state_store.save(state.with_status("stopped"))
        return state


class ActiveTaskStore:
    def __init__(self, active):
        self._active = active

    def active(self):
        return self._active


def _setup(tmp_path, *, failing=()):
    shared_url = "http://127.0.0.1:19020"
    manifests = {
        "pick-place-workflow": Manifest("pick-place-workflow", "0.9.0", shared_url),
        "scene-alternate": Manifest("scene-alternate", "0.1.0", shared_url),
    }
    catalog = Catalog(*manifests.values())
    states = RuntimeStateStore(tmp_path / "run")
    manager = Manager(manifests, states, failing=failing)
    registry = ActiveRuntimeRegistry()
    controller = SkillRuntimeController(
        registry,
        manager=manager,
        catalog=catalog,
        state_store=states,
    )
    return controller, registry, manager


def test_switch_is_blocked_while_an_agent_task_is_nonterminal(tmp_path):
    controller, registry, manager = _setup(tmp_path)
    controller = SkillRuntimeController(
        registry,
        manager=manager,
        catalog=controller.catalog,
        state_store=controller.state_store,
        task_store=ActiveTaskStore(object()),
    )

    with pytest.raises(RuntimeError, match="AgentTask is non-terminal"):
        controller.switch("pick-place-workflow", "fake")
    assert registry.current() is None
    assert manager.started == []


def test_failed_target_restores_previous_runtime_and_keeps_registry(tmp_path):
    controller, registry, manager = _setup(tmp_path, failing={"scene-alternate"})
    selected = controller.switch("pick-place-workflow", "fake")

    with pytest.raises(RuntimeError, match="failed to start scene-alternate"):
        controller.switch("scene-alternate", "fake")

    restored = registry.current()
    assert restored is not None
    assert restored.skill_name == selected.skill_name == "pick-place-workflow"
    assert manager.started == [
        ("pick-place-workflow", "fake"),
        ("scene-alternate", "fake"),
        ("pick-place-workflow", "fake"),
    ]
    assert manager.stopped[0] == ("pick-place-workflow", False)


def test_healthy_target_replaces_active_registry_atomically(tmp_path):
    controller, registry, manager = _setup(tmp_path)
    first = controller.switch("pick-place-workflow", "fake")
    second = controller.switch("scene-alternate", "fake")

    assert second is registry.current()
    assert second.skill_name == "scene-alternate"
    assert first is not second
    assert manager.started == [
        ("pick-place-workflow", "fake"),
        ("scene-alternate", "fake"),
    ]
    assert manager.stopped[-1] == ("pick-place-workflow", False)
