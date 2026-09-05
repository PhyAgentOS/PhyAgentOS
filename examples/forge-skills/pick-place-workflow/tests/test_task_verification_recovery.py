from datetime import datetime, timezone

import pytest
from PhyAgentOS.agent.experience.source import AgentTaskOutcomeSource
from PhyAgentOS.config.schema import ForgeConfig
from PhyAgentOS.forge.task import AgentTaskCoordinator, AgentTaskStatus
from PhyAgentOS.forge.tool_client import ForgeToolClient
from PhyAgentOS.verification.contracts import (
    CriterionVerdict,
    RecoveryContext,
    TaskVerificationContract,
    VerificationAttempt,
    VerificationVerdict,
)

from pick_place_workflow.fake_gateway import FakeGatewayTransport, ObservationSnapshot


class Provider:
    def observe(self, sensor_ref):
        return ObservationSnapshot(
            captured_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            scene_revision="scene-7",
            frame_id="camera_front",
            calibration_ref="calibration://front/v3",
            artifacts=({"ref": "artifact://obs-7/rgb", "kind": "rgb", "media_type": "image/jpeg"},),
        )


class Verifier:
    def __init__(self):
        self.calls = 0
        self.retention_calls = []

    async def verify_agent_task(self, task, *, events, lessons, source, mode):
        self.calls += 1
        if self.calls == 1:
            verdict = VerificationVerdict(
                verdict="replan_required",
                criteria=[CriterionVerdict(criterion="fresh observation", status="unknown")],
                evidence_refs=[],
                reason="the first observation requires a fresh planning revision",
                lesson="re-observe before continuing",
                recovery_context=RecoveryContext(
                    unmet_criteria=["fresh observation"],
                    preserved_constraints=["keep the same task identity"],
                    guidance="obtain a new observation",
                ),
            )
        else:
            verdict = VerificationVerdict(
                verdict="success",
                criteria=[CriterionVerdict(criterion="fresh observation", status="satisfied")],
                evidence_refs=[],
                reason="the revised observation satisfies the criterion",
                lesson="none",
            )
        return verdict, {"request": "fixture"}, VerificationAttempt(
            attempt_id=f"verification-{self.calls}",
            source="auto",
            mode="apply",
            verdict=verdict.verdict,
        )

    def apply_retention(self, request, *, final_status):
        self.retention_calls.append((request, final_status))
        return {"status": "retained", "errors": []}


@pytest.mark.asyncio
async def test_recovery_appends_revision_and_preserves_failure_success_lineage(tmp_path):
    transport = FakeGatewayTransport(Provider(), now=datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc))
    verifier = Verifier()
    async with ForgeToolClient("http://fake", transport=transport) as client:
        coordinator = AgentTaskCoordinator(
            workspace=tmp_path,
            config=ForgeConfig(),
            client=client,
            verifier=verifier,
            max_replans=1,
        )
        async def no_capture(task_id):
            return None

        coordinator._capture_before = no_capture
        coordinator._capture_after = no_capture
        task = coordinator.create_task(
            task_description="observe and recover",
            verification=TaskVerificationContract(
                mode="recovery",
                goal="obtain a verified observation",
                success_criteria=["fresh observation"],
            ),
        )
        await coordinator.invoke_query(
            task.task_id,
            "scene.observe",
            {"sensor_ref": "sensor/front", "max_age_ms": 1000},
        )
        awaiting = await coordinator.finalize_task(task.task_id)
        assert awaiting.status is AgentTaskStatus.AWAITING_REPLAN
        assert verifier.retention_calls == []
        revised = coordinator.begin_revision(task.task_id, reason="refresh observation")
        assert revised.task_id == task.task_id
        assert len(revised.revisions) == 2
        assert revised.revisions[0].verdict.verdict == "replan_required"
        await coordinator.invoke_query(
            task.task_id,
            "scene.observe",
            {"sensor_ref": "sensor/front", "max_age_ms": 1000},
        )
        completed = await coordinator.finalize_task(task.task_id)
        outcome = AgentTaskOutcomeSource(coordinator).build(task.task_id)

    assert completed.status is AgentTaskStatus.SUCCEEDED
    assert verifier.calls == 2
    assert verifier.retention_calls == [({"request": "fixture"}, "succeeded")]
    assert len(completed.revisions) == 2
    assert len(completed.execution_records) == 2
    assert [item.revision_id for item in completed.execution_records] == [
        completed.revisions[0].revision_id,
        completed.revisions[1].revision_id,
    ]
    assert [item.semantic_verdict for item in outcome.lineage] == ["replan_required", "success"]
    assert outcome.has_failed_attempt
