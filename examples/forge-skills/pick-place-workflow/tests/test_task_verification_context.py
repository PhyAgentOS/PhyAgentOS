import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PhyAgentOS.config.schema import ForgeConfig
from PhyAgentOS.forge.binding import ForgeSkillBindingResolver
from PhyAgentOS.forge.evidence import ForgeEvidenceWriter
from PhyAgentOS.forge.observation import ObservationSnapshot
from PhyAgentOS.forge.task import AgentTaskCoordinator, AgentTaskStatus
from PhyAgentOS.forge.tool_client import ForgeToolClient
from PhyAgentOS.skill_runtime.integration import ActiveRuntimeRegistry, ActiveSkillRuntime
from PhyAgentOS.skill_runtime.manifest import load_manifest
from PhyAgentOS.verification.contracts import (
    CriterionVerdict,
    TaskVerificationContract,
    VerificationAttempt,
    VerificationVerdict,
)
from PhyAgentOS.verification.request_builder import VerificationRequestBuilder

from pick_place_workflow.fake_gateway import FakeGatewayTransport
from pick_place_workflow.fake_gateway import ObservationSnapshot as GatewaySnapshot
from pick_place_workflow.object_acquire import AcquireSnapshot

BUNDLE_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 2, tzinfo=timezone.utc)


class Provider:
    def observe(self, sensor_ref):
        if sensor_ref != "sensor/front":
            return None
        return GatewaySnapshot(
            captured_at=NOW,
            scene_revision="scene-7",
            frame_id="camera_front",
            calibration_ref="calibration://front/v3",
            artifacts=(),
        )

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


class Catalog:
    def __init__(self, manifest):
        self.manifest = manifest

    def get(self, name):
        return self.manifest


class ContextVerifier:
    """Build the real generic request, then return a deterministic verdict."""

    def __init__(self, workspace):
        self.workspace = Path(workspace)
        self.requests = []

    async def verify_agent_task(self, task, *, events, lessons, source, mode):
        request = VerificationRequestBuilder(self.workspace).build_agent_task(
            task, events=events, lessons=lessons
        )
        self.requests.append(request)
        return (
            VerificationVerdict(
                verdict="success",
                criteria=[
                    CriterionVerdict(
                        criterion="the bounded acquisition completed",
                        status="satisfied",
                    )
                ],
                reason="the generic verifier received the bound execution facts",
                lesson="none",
            ),
            request,
            VerificationAttempt(
                attempt_id="verification-context-1",
                source=source,
                mode=mode,
                verdict="success",
            ),
        )


def _write_empty_capture(coordinator, task_id, phase, *, before_ref=None):
    writer = ForgeEvidenceWriter(
        coordinator.workspace, task_id, "agent_task", artifact_namespace="agent_tasks"
    )
    reference = writer.write_snapshot(phase, ObservationSnapshot(captured_at=NOW))
    if phase == "before":
        coordinator.store.update(
            task_id,
            lambda task: setattr(task, "before_snapshot_ref", reference),
            event_type="test_before_capture",
        )
        return reference
    bundle, bundle_ref = writer.write_bundle(
        before_ref=before_ref,
        after_ref=reference,
        terminal_observed_at=NOW,
        required_sources=[],
        required_kinds=[],
        errors=[],
    )
    coordinator.store.update(
        task_id,
        lambda task: (
            setattr(task, "after_snapshot_ref", reference),
            setattr(task, "evidence_bundle_ref", bundle_ref),
        ),
        event_type="test_after_capture",
        payload={"bundle_id": bundle.bundle_id},
    )
    return bundle_ref


async def _setup(tmp_path, verifier):
    workspace_skill = tmp_path / "skills" / "pick-place-workflow"
    shutil.copytree(BUNDLE_ROOT, workspace_skill)
    manifest = load_manifest(workspace_skill / "skill.yaml")
    provider = Provider()
    transport = FakeGatewayTransport(
        provider,
        understanding_provider=provider,
        grasp_provider=provider,
        preparation_provider=provider,
        acquire_provider=provider,
        place_provider=provider,
        now=NOW,
    )
    client = ForgeToolClient("http://fake", transport=transport)
    runtime = ActiveSkillRuntime(
        skill_name="pick-place-workflow",
        skill_version=manifest.version,
        profile="fake",
        runtime_instance_id="runtime-verification-context",
        gateway_url="http://fake",
        gateway_identity="gateway-verification-context",
        client=client,
        invocation_ids=set(),
        session_ids=set(),
        task_binding_ids=set(),
    )
    registry = ActiveRuntimeRegistry(runtime)
    resolver = ForgeSkillBindingResolver(registry, catalog=Catalog(manifest))
    coordinator = AgentTaskCoordinator(
        workspace=tmp_path,
        config=ForgeConfig(),
        client=client,
        verifier=verifier,
        binding_resolver=resolver,
        activation_manager=None,
    )
    return client, transport, resolver, coordinator


@pytest.mark.asyncio
async def test_bound_execution_facts_reach_generic_verifier_without_authorizing_motion(tmp_path):
    verifier = ContextVerifier(tmp_path)
    client, transport, resolver, coordinator = await _setup(tmp_path, verifier)
    try:
        from PhyAgentOS.agent.experience.coordinator import ExperienceCoordinator

        experience = ExperienceCoordinator(
            workspace=tmp_path,
            analyzer=object(),
            binding_resolver=resolver,
            runtime_availability_provider=lambda name: name == "pick-place-workflow",
        )
        coordinator.set_experience(experience)
        coordinator.set_activation_manager(experience.activation)
        session = "verification-context-session"
        experience.begin_turn(session, "acquire one bounded object")
        activation, _content, _lessons = await experience.activation.activate(
            session_key=session, name="pick-place-workflow", role="primary"
        )
        task = await coordinator.create_task(
            task_description="acquire one bounded object",
            verification=TaskVerificationContract(
                mode="enforce",
                goal="complete the bounded acquisition",
                success_criteria=["the bounded acquisition completed"],
                evidence_policy={"required_kinds": []},
            ),
            activation_id=activation.activation_id,
            origin_session_key=session,
        )

        async def capture_before(task_id):
            return _write_empty_capture(coordinator, task_id, "before")

        async def capture_after(task_id):
            current = coordinator.get_task(task_id)
            return _write_empty_capture(
                coordinator,
                task_id,
                "after",
                before_ref=current.before_snapshot_ref,
            )

        coordinator._capture_before = capture_before
        coordinator._capture_after = capture_after
        await coordinator.invoke_query(
            task.task_id,
            "scene.observe",
            {"sensor_ref": "sensor/front", "max_age_ms": 1000},
        )
        admitted = await coordinator.start_action(
            task.task_id,
            "object.acquire",
            {
                "observation_ref": "observation://scene-7/camera_front",
                "scene_revision": "scene-7",
                "frame_id": "camera_front",
                "calibration_ref": "calibration://front/v3",
                "freshness_ms": 0,
                "max_age_ms": 1000,
                "candidate_set_ref": "candidate-set://scene-7/camera_front",
                "preparation_ref": "preparation://scene-7/camera_front",
                "candidate_ref": "candidate://bottle-1/1",
                "entity_ref": "entity://bottle-1",
            },
        )
        invocation_id = admitted["data"]["invocation_id"]
        terminal = await client.invocation_result(invocation_id)
        coordinator.observe_action(task.task_id, invocation_id, terminal)
        finalized = await coordinator.finalize_task(task.task_id)
        request = verifier.requests[0]
        context_text = request.content[0]["text"]
        context = json.loads(context_text.split("\n\n", 1)[1])
    finally:
        await client.close()

    assert finalized.status is AgentTaskStatus.SUCCEEDED
    assert context["tool_execution_records"][-1]["tool_id"] == "object.acquire"
    assert context["tool_execution_records"][-1]["skill_binding_id"]
    assert context["tool_execution_records"][-1]["revision_id"]
    assert context["tool_execution_records"][-1]["invocation_id"] == invocation_id
    projection = context["capability_outcome_projections"]
    assert len(projection) == 1
    assert projection[0]["authority"] == "execution_fact_only"
    assert projection[0]["task_success_authorized"] is False
    assert projection[0]["opaque_artifact_refs"] == ["artifact://acquire-7/settlement"]
    assert "artifact://acquire-7/settlement" in context_text
    assert "artifact://acquire-7/settlement" not in request.valid_evidence_refs
    assert "motion_authorized" not in json.dumps(context, sort_keys=True)
    assert all(
        path.startswith("/tools/") or path.startswith("/invocations/")
        for path in (request.url.path for request in transport.requests)
    )
