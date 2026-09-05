import shutil
from pathlib import Path

import pytest
from PhyAgentOS.agent.experience.coordinator import ExperienceCoordinator
from PhyAgentOS.forge.binding import ForgeSkillBindingResolver
from PhyAgentOS.forge.task import AgentTaskCoordinator, AgentTaskError
from PhyAgentOS.forge.tool_client import ForgeToolClient
from PhyAgentOS.skill_runtime.integration import ActiveRuntimeRegistry, ActiveSkillRuntime
from PhyAgentOS.skill_runtime.manifest import load_manifest
from PhyAgentOS.verification.contracts import TaskVerificationContract

from pick_place_workflow.fake_gateway import FakeGatewayTransport

BUNDLE_ROOT = Path(__file__).resolve().parents[1]


class Provider:
    def observe(self, sensor_ref):
        return None

    def understand(self, request):
        return None

    def propose(self, request):
        return None

    def prepare(self, request):
        return None

    def acquire(self, request):
        return None

    def place(self, request):
        return None


class Catalog:
    def __init__(self, manifest):
        self.manifest = manifest

    def get(self, name):
        assert name == "pick-place-workflow"
        return self.manifest


class Analyzer:
    async def assess(self, episode, **kwargs):
        raise AssertionError("reflection is outside task binding setup")


def _setup(tmp_path):
    workspace_skill = tmp_path / "skills" / "pick-place-workflow"
    shutil.copytree(BUNDLE_ROOT, workspace_skill)
    manifest = load_manifest(BUNDLE_ROOT / "skill.yaml")
    manifest = manifest.__class__(
        **{**manifest.__dict__, "gateway_url": "http://fake"}
    )
    provider = Provider()
    transport = FakeGatewayTransport(
        provider,
        understanding_provider=provider,
        grasp_provider=provider,
        preparation_provider=provider,
        acquire_provider=provider,
        place_provider=provider,
    )
    client = ForgeToolClient("http://fake", transport=transport)
    runtime = ActiveSkillRuntime(
        skill_name="pick-place-workflow",
        skill_version="0.10.1",
        profile="fake",
        runtime_instance_id="runtime-binding",
        gateway_url="http://fake",
        gateway_identity="gateway-binding",
        client=client,
        invocation_ids=set(),
        session_ids=set(),
        task_binding_ids=set(),
    )
    registry = ActiveRuntimeRegistry(runtime)
    resolver = ForgeSkillBindingResolver(registry, catalog=Catalog(manifest))
    experience = ExperienceCoordinator(
        workspace=tmp_path,
        analyzer=Analyzer(),
        binding_resolver=resolver,
        runtime_availability_provider=lambda name: name == "pick-place-workflow",
    )
    coordinator = AgentTaskCoordinator(
        workspace=tmp_path,
        config=__import__("PhyAgentOS.config.schema", fromlist=["ForgeConfig"]).ForgeConfig(),
        client=client,
        experience=experience,
        binding_resolver=resolver,
        activation_manager=experience.activation,
    )
    return client, registry, experience, coordinator


@pytest.mark.asyncio
async def test_activation_freeze_and_task_creation_share_one_immutable_binding(tmp_path):
    client, _registry, experience, coordinator = _setup(tmp_path)
    try:
        session_key = "session-binding"
        experience.begin_turn(session_key, "run the scene observation workflow")
        activation, content, _lessons = await experience.activation.activate(
            session_key=session_key,
            name="pick-place-workflow",
            role="primary",
        )
        task = await coordinator.create_task(
            task_description="run the scene observation workflow",
            verification=TaskVerificationContract(mode="off"),
            activation_id=activation.activation_id,
            origin_session_key=session_key,
        )
    finally:
        await client.close()

    assert activation.binding_candidate_id
    assert activation.content_sha256 == __import__("hashlib").sha256(content.encode()).hexdigest()
    assert task.primary_skill_binding is not None
    binding = task.primary_skill_binding
    assert task.active_revision.skill_binding_id == binding.binding_id
    assert task.runtime_snapshot_ref == "runtime:runtime-binding"
    assert binding.skill_name == "pick-place-workflow"
    assert binding.skill_document_sha256 == activation.content_sha256
    assert experience.store.get_binding(task.task_id)["forge_skill_binding"]["binding_id"] == binding.binding_id


@pytest.mark.asyncio
async def test_task_query_is_blocked_before_gateway_when_runtime_binding_drifts(tmp_path):
    client, registry, experience, coordinator = _setup(tmp_path)
    try:
        session_key = "session-drift"
        experience.begin_turn(session_key, "observe a scene")
        activation, _content, _lessons = await experience.activation.activate(
            session_key=session_key,
            name="pick-place-workflow",
            role="primary",
        )
        task = await coordinator.create_task(
            task_description="observe a scene",
            verification=TaskVerificationContract(mode="off"),
            activation_id=activation.activation_id,
            origin_session_key=session_key,
        )
        registry.replace(
            ActiveSkillRuntime(
                skill_name="pick-place-workflow",
                skill_version="0.10.1",
                profile="fake",
                runtime_instance_id="runtime-drifted",
                gateway_url="http://fake",
                gateway_identity="gateway-drifted",
                client=client,
                invocation_ids=set(),
                session_ids=set(),
                task_binding_ids=set(),
            )
        )
        with pytest.raises(AgentTaskError, match="binding is no longer active"):
            await coordinator.invoke_query(
                task.task_id,
                "scene.observe",
                {"sensor_ref": "sensor/front", "max_age_ms": 1000},
            )
    finally:
        await client.close()
