import asyncio
from datetime import datetime, timezone

import pytest
from PhyAgentOS.agent.experience.contracts import ExperienceAssessment
from PhyAgentOS.agent.experience.coordinator import ExperienceCoordinator
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

from scene_observe.fake_gateway import FakeGatewayTransport, ObservationSnapshot


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

    async def verify_agent_task(self, task, **kwargs):
        self.calls += 1
        if self.calls == 1:
            verdict = VerificationVerdict(
                verdict="replan_required",
                criteria=[CriterionVerdict(criterion="fresh observation", status="unknown")],
                reason="re-observe",
                lesson="refresh the observation",
                recovery_context=RecoveryContext(
                    unmet_criteria=["fresh observation"],
                    preserved_constraints=["same task"],
                    guidance="take another observation",
                ),
            )
        else:
            verdict = VerificationVerdict(
                verdict="success",
                criteria=[CriterionVerdict(criterion="fresh observation", status="satisfied")],
                reason="verified",
                lesson="none",
            )
        return verdict, {"fixture": True}, VerificationAttempt(
            attempt_id=f"verify-{self.calls}",
            verdict=verdict.verdict,
        )


class Analyzer:
    def __init__(self):
        self.episodes = []

    async def assess(self, episode, **kwargs):
        self.episodes.append(episode)
        assert episode.outcome.has_failed_attempt
        assert len(episode.outcome.lineage) == 2
        assert [item.semantic_verdict for item in episode.outcome.lineage] == [
            "replan_required",
            "success",
        ]
        return ExperienceAssessment(
            outcome="mixed",
            reusable=False,
            confidence=1.0,
            rationale="recovery lineage was preserved",
        )


@pytest.mark.asyncio
async def test_recovery_completion_persists_one_mixed_episode_for_analyzer(tmp_path):
    transport = FakeGatewayTransport(Provider(), now=datetime(2026, 9, 1, tzinfo=timezone.utc))
    verifier = Verifier()
    analyzer = Analyzer()
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
        experience = ExperienceCoordinator(
            workspace=tmp_path,
            analyzer=analyzer,
            task_coordinator=coordinator,
        )
        coordinator.set_experience(experience)
        task = coordinator.create_task(
            task_description="recover a scene observation",
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
        coordinator.begin_revision(task.task_id, reason="refresh observation")
        await coordinator.invoke_query(
            task.task_id,
            "scene.observe",
            {"sensor_ref": "sensor/front", "max_age_ms": 1000},
        )
        completed = await coordinator.finalize_task(task.task_id)
        await asyncio.sleep(0.05)

        episode = experience.store.get_episode_by_root(task.task_id)

    assert completed.status is AgentTaskStatus.SUCCEEDED
    assert verifier.calls == 2
    assert episode.outcome.final_verdict == "success"
    assert episode.outcome.has_failed_attempt
    assert len(episode.outcome.lineage) == 2
    assert len(analyzer.episodes) == 1
    assert episode.processing_status == "processed"
    assert experience.store.list_candidates(active_only=False) == []
    assert experience.store.list_clusters() == []
