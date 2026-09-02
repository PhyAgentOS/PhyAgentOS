from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest
from PhyAgentOS.forge.binding import (
    ForgeSkillBindingError,
    ForgeSkillBindingResolver,
    canonical_sha256,
)
from PhyAgentOS.skill_runtime.integration import ActiveRuntimeRegistry, ActiveSkillRuntime
from PhyAgentOS.skill_runtime.manifest import load_manifest

from scene_observe.fake_gateway import FakeGatewayTransport

BUNDLE_ROOT = Path(__file__).resolve().parents[1]
SKILL_NAME = "scene-observe"
TOOL_IDS = (
    "scene.observe",
    "scene.understand",
    "grasp.propose",
    "manipulation.prepare",
    "object.acquire",
    "object.place",
)


class DummyProvider:
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
        assert name == SKILL_NAME
        return self.manifest


def _runtime(client, *, instance="runtime_fixture", identity="gateway_fixture"):
    return ActiveSkillRuntime(
        skill_name=SKILL_NAME,
        skill_version="0.7.0",
        profile="fake",
        runtime_instance_id=instance,
        gateway_url="http://fake",
        gateway_identity=identity,
        client=client,
        invocation_ids=set(),
        session_ids=set(),
        task_binding_ids=set(),
    )


def _fixture(tmp_path):
    manifest = load_manifest(BUNDLE_ROOT / "skill.yaml")
    manifest = replace(manifest, gateway_url="http://fake")
    dummy = DummyProvider()
    transport = FakeGatewayTransport(
        dummy,
        understanding_provider=dummy,
        grasp_provider=dummy,
        preparation_provider=dummy,
        acquire_provider=dummy,
        place_provider=dummy,
    )
    from PhyAgentOS.forge.tool_client import ForgeToolClient

    client = ForgeToolClient("http://fake", transport=transport)
    runtime = _runtime(client)
    registry = ActiveRuntimeRegistry(runtime)
    resolver = ForgeSkillBindingResolver(registry, catalog=Catalog(manifest))
    return manifest, transport, client, registry, resolver


@pytest.mark.asyncio
async def test_preview_and_freeze_capture_immutable_runtime_and_tool_hashes(tmp_path):
    manifest, transport, client, _registry, resolver = _fixture(tmp_path)
    try:
        candidate = await resolver.preview(SKILL_NAME)
        binding = await resolver.freeze(candidate.candidate_id, task_id="task_fixture")

        assert candidate.skill_name == binding.skill_name == SKILL_NAME
        assert candidate.skill_version == binding.skill_version == "0.7.0"
        assert candidate.runtime_profile == binding.runtime_profile == "fake"
        assert candidate.runtime_instance_id == binding.runtime_instance_id == "runtime_fixture"
        assert candidate.gateway_identity == binding.gateway_identity == "gateway_fixture"
        assert candidate.manifest_sha256 == sha256(
            (BUNDLE_ROOT / "skill.yaml").read_bytes()
        ).hexdigest()
        assert candidate.skill_document_sha256 == sha256(
            (BUNDLE_ROOT / "SKILL.md").read_bytes()
        ).hexdigest()
        assert tuple(item.tool_id for item in binding.required_tools) == tuple(sorted(TOOL_IDS))
        assert all(item.ready_at_binding is True for item in binding.required_tools)
        assert all(len(item.spec_sha256) == 64 for item in binding.required_tools)
        assert len(transport.requests) >= len(TOOL_IDS) * 2
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_validate_tool_rejects_runtime_identity_change_after_freeze(tmp_path):
    _manifest, _transport, client, registry, resolver = _fixture(tmp_path)
    try:
        candidate = await resolver.preview(SKILL_NAME)
        binding = await resolver.freeze(candidate.candidate_id, task_id="task_fixture")
        registry.replace(_runtime(client, instance="runtime_replaced", identity="gateway_replaced"))

        with pytest.raises(ForgeSkillBindingError, match="binding is no longer active"):
            await resolver.validate_tool(binding, "scene.observe", "query")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_freeze_rejects_changed_tool_spec_after_preview(tmp_path):
    _manifest, _transport, client, _registry, resolver = _fixture(tmp_path)
    try:
        candidate = await resolver.preview(SKILL_NAME)
        candidate = candidate.model_copy(
            update={
                "required_tools": tuple(
                    item.model_copy(
                        update={"spec_sha256": canonical_sha256({"changed": item.tool_id})}
                    )
                    for item in candidate.required_tools
                )
            }
        )
        resolver._candidates[candidate.candidate_id] = candidate

        with pytest.raises(ForgeSkillBindingError, match="Runtime or ToolSpec changed"):
            await resolver.freeze(candidate.candidate_id, task_id="task_fixture")
    finally:
        await client.close()
