import shutil
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PhyAgentOS.agent.experience.coordinator import ExperienceCoordinator
from PhyAgentOS.config.schema import ForgeConfig
from PhyAgentOS.forge.binding import ForgeSkillBindingResolver
from PhyAgentOS.forge.task import AgentTaskCoordinator
from PhyAgentOS.forge.tool_client import ForgeToolClient
from PhyAgentOS.skill_runtime.integration import ActiveRuntimeRegistry, ActiveSkillRuntime
from PhyAgentOS.skill_runtime.manifest import load_manifest
from PhyAgentOS.verification.contracts import TaskVerificationContract

from pick_place_workflow.fake_gateway import FakeGatewayTransport, ObservationSnapshot
from pick_place_workflow.object_acquire import AcquireSnapshot
from pick_place_workflow.object_place import PlaceSnapshot

BUNDLE_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


class Provider:
    def observe(self, sensor_ref):
        return ObservationSnapshot(
            captured_at=NOW - timedelta(milliseconds=100),
            scene_revision="scene-7",
            frame_id="camera_front",
            calibration_ref="calibration://front/v3",
            artifacts=({"ref": "artifact://obs-7/rgb", "kind": "rgb", "media_type": "image/jpeg"},),
        ) if sensor_ref == "sensor/front" else None

    def acquire(self, request):
        return AcquireSnapshot(
            capability_phase="hold",
            status="succeeded",
            world_change_started=True,
            outcome_known=True,
            evidence_availability="partial",
            artifact_refs=("artifact://acquire-7/settlement",),
            bounded_metric_names=("lift_height",),
        )

    def place(self, request):
        return PlaceSnapshot(status="succeeded", world_change_started=True)


class Analyzer:
    async def assess(self, episode, **kwargs):
        raise AssertionError("reflection is outside this execution-record fixture")


class Catalog:
    def __init__(self, manifest):
        self.manifest = manifest

    def get(self, name):
        return self.manifest


async def _setup(tmp_path):
    workspace_skill = tmp_path / "skills" / "pick-place-workflow"
    shutil.copytree(BUNDLE_ROOT, workspace_skill)
    manifest = replace(load_manifest(BUNDLE_ROOT / "skill.yaml"), gateway_url="http://fake")
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
        skill_version=manifest.version,
        profile="fake",
        runtime_instance_id="runtime-records",
        gateway_url="http://fake",
        gateway_identity="gateway-records",
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
        config=ForgeConfig(),
        client=client,
        experience=experience,
        binding_resolver=resolver,
        activation_manager=experience.activation,
    )

    async def no_capture(task_id):
        return None

    coordinator._capture_before = no_capture
    return client, transport, experience, coordinator


@pytest.mark.asyncio
async def test_bound_query_and_action_records_retain_binding_and_revision_identity(tmp_path):
    client, transport, experience, coordinator = await _setup(tmp_path)
    try:
        session = "session-records"
        experience.begin_turn(session, "capture and acquire an object")
        activation, _content, _lessons = await experience.activation.activate(
            session_key=session, name="pick-place-workflow", role="primary"
        )
        task = await coordinator.create_task(
            task_description="capture and acquire an object",
            verification=TaskVerificationContract(mode="off"),
            activation_id=activation.activation_id,
            origin_session_key=session,
        )
        await coordinator.invoke_query(
            task.task_id,
            "scene.observe",
            {"sensor_ref": "sensor/front", "max_age_ms": 1000},
        )
        action = await coordinator.start_action(
            task.task_id,
            "object.acquire",
            {
                "observation_ref": "observation://scene-7/camera_front",
                "scene_revision": "scene-7",
                "frame_id": "camera_front",
                "calibration_ref": "calibration://front/v3",
                "freshness_ms": 25,
                "max_age_ms": 1000,
                "candidate_set_ref": "candidate-set://scene-7/camera_front",
                "preparation_ref": "preparation://scene-7/camera_front",
                "candidate_ref": "candidate://bottle-1/1",
                "entity_ref": "entity://bottle-1",
                "capability_snapshot_ref": "artifact://capabilities/scene-7/snapshot",
                "assignment_ref": "artifact://assignments/task-1/revision-1/acquire",
            },
        )
        invocation_id = action["data"]["invocation_id"]
        result = await client.invocation_result(invocation_id)
        while result["data"].get("phase") == "running":
            result = await client.invocation_result(invocation_id)
        coordinator.observe_action(task.task_id, invocation_id, result)
        bound = task.primary_skill_binding
        assert bound is not None
        records = coordinator.get_task(task.task_id).execution_records
    finally:
        await client.close()

    assert [item.tool_id for item in records] == ["scene.observe", "object.acquire"]
    assert all(item.status == "succeeded" for item in records)
    assert all(item.skill_binding_id == bound.binding_id for item in records)
    assert all(item.revision_id == task.active_revision_id for item in records)
    for item in records:
        spec = bound.tool(item.tool_id)
        assert spec is not None
        assert item.tool_spec_sha256 == spec.spec_sha256
    action_record = records[-1]
    assert action_record.invocation_id == invocation_id
    assert action_record.attempt_id is not None
    assert action_record.response["data"]["result"]["capability_outcome_summary"]["status"] == "succeeded"
    assert all(path.startswith("/tools/") or path.startswith("/invocations/") for path in [request.url.path for request in transport.requests])
