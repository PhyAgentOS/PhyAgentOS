import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from PhyAgentOS.agent.experience.contracts import ExperienceAssessment
from PhyAgentOS.agent.experience.coordinator import ExperienceCoordinator
from PhyAgentOS.agent.experience.source import AgentTaskOutcomeSource
from PhyAgentOS.config.schema import ForgeConfig
from PhyAgentOS.forge.task import AgentTaskCoordinator, AgentTaskError, AgentTaskStatus
from PhyAgentOS.forge.tool_client import ForgeToolClient
from PhyAgentOS.verification.contracts import TaskVerificationContract

from pick_place_workflow.fake_gateway import FakeGatewayTransport, ObservationSnapshot
from pick_place_workflow.grasp_proposal import GraspProposalSnapshot
from pick_place_workflow.manipulation_prepare import PreparationSnapshot
from pick_place_workflow.object_acquire import AcquireSnapshot
from pick_place_workflow.object_place import PlaceSnapshot
from pick_place_workflow.understanding import UnderstandingSnapshot

NOW = datetime(2026, 9, 1, 0, 0, 0, 500000, tzinfo=timezone.utc)
OBSERVATION_REF = "observation://scene-7/camera_front"
SCENE_REVISION = "scene-7"
FRAME_ID = "camera_front"
CALIBRATION_REF = "calibration://front/v3"
ARTIFACT_REF = "artifact://obs-7/rgb"
CANDIDATE_SET_REF = "candidate-set://scene-7/camera_front"
PREPARATION_REF = "preparation://scene-7/camera_front"
CANDIDATE_REF = "candidate://bottle-1/1"
ENTITY_REF = "entity://bottle-1"


class ObservationProvider:
    def observe(self, sensor_ref):
        if sensor_ref != "sensor/front":
            return None
        return ObservationSnapshot(
            captured_at=NOW - timedelta(milliseconds=500),
            scene_revision=SCENE_REVISION,
            frame_id=FRAME_ID,
            calibration_ref=CALIBRATION_REF,
            artifacts=(
                {"ref": ARTIFACT_REF, "kind": "rgb", "media_type": "image/jpeg"},
            ),
        )


class UnderstandingProvider:
    def understand(self, request):
        return UnderstandingSnapshot(
            entities=(
                {
                    "entity_ref": ENTITY_REF,
                    "category": "container",
                    "confidence": 0.92,
                    "provenance": [ARTIFACT_REF],
                },
            ),
            spatial_envelopes=(
                {
                    "entity_ref": ENTITY_REF,
                    "frame_id": FRAME_ID,
                    "unit": "m",
                    "min_xyz_m": [0.1, -0.2, 0.0],
                    "max_xyz_m": [0.2, -0.1, 0.3],
                    "confidence": 0.8,
                    "provenance": [ARTIFACT_REF],
                },
            ),
        )


class GraspProvider:
    def propose(self, request):
        candidate = {
            "candidate_ref": CANDIDATE_REF,
            "entity_ref": ENTITY_REF,
            "grasp_frame": {
                "frame_id": FRAME_ID,
                "unit": "m",
                "position_m": [0.15, -0.15, 0.12],
                "orientation_xyzw": [0.0, 0.0, 0.0, 1.0],
            },
            "approach_direction": {
                "frame_id": FRAME_ID,
                "unit": "unitless",
                "vector": [0.0, 0.0, -1.0],
            },
            "score": 0.81,
            "confidence": 0.77,
            "provenance": [ARTIFACT_REF],
            "qualification": "proposed",
        }
        return GraspProposalSnapshot(
            candidates=(candidate,),
            funnel={"decoded": 1, "canonicalized": 1, "deduplicated": 1, "retained": 1},
        )


class PreparationProvider:
    def prepare(self, request):
        return PreparationSnapshot(
            prepared_candidates=(
                {
                    "candidate_ref": CANDIDATE_REF,
                    "entity_ref": ENTITY_REF,
                    "checks": {"kinematic": "pass", "collision": "pass", "workspace": "pass"},
                    "evidence": ["artifact://prep-7/readiness"],
                    "qualification": "prepared",
                },
            )
        )


class StaticAnalyzer:
    def __init__(self):
        self.episodes = []

    async def assess(self, episode, **kwargs):
        self.episodes.append(episode)
        return ExperienceAssessment(
            outcome="success" if episode.outcome.successful else "failure",
            reusable=False,
            confidence=1.0,
            rationale="deterministic integration assessment",
        )

    async def synthesize_lesson(self, cluster, observations):
        raise AssertionError("lesson synthesis is outside this success-path fixture")

    async def validate_lesson_abstraction(self, cluster, observations, draft):
        raise AssertionError("lesson validation is outside this success-path fixture")


def _acquire_provider(status="succeeded"):
    return type(
        "AcquireProvider",
        (),
        {"acquire": lambda self, request: AcquireSnapshot(
            status=status,
            capability_phase="hold" if status == "succeeded" else "none",
            world_change_started=status == "succeeded",
            outcome_known=status != "unknown",
            failure_owner=None if status == "succeeded" else "execution",
            failure_code=None if status == "succeeded" else "remote_unknown",
            evidence_availability="partial",
            artifact_refs=("artifact://acquire-7/settlement",),
            bounded_metric_names=("lift_height",),
        )},
    )()


class PlaceProvider:
    def place(self, request):
        return PlaceSnapshot(
            capability_phase="retreat",
            status="succeeded",
            world_change_started=True,
            outcome_known=True,
            evidence_availability="partial",
            artifact_refs=("artifact://place-7/trajectory",),
            post_release_evidence_availability="complete",
            post_release_evidence_refs=("artifact://place-7/post-release",),
            bounded_metric_names=("release_height",),
        )


def _understanding_args():
    return {
        "observation_ref": OBSERVATION_REF,
        "scene_revision": SCENE_REVISION,
        "frame_id": FRAME_ID,
        "calibration_ref": CALIBRATION_REF,
        "freshness_ms": 25,
        "max_age_ms": 1000,
        "artifacts": [ARTIFACT_REF],
    }


def _proposal_args():
    return {
        "observation_ref": OBSERVATION_REF,
        "scene_revision": SCENE_REVISION,
        "frame_id": FRAME_ID,
        "calibration_ref": CALIBRATION_REF,
        "freshness_ms": 25,
        "max_age_ms": 1000,
        "targets": [
            {
                "entity_ref": ENTITY_REF,
                "category": "container",
                "confidence": 0.92,
                "spatial_envelope": {
                    "frame_id": FRAME_ID,
                    "unit": "m",
                    "min_xyz_m": [0.1, -0.2, 0.0],
                    "max_xyz_m": [0.2, -0.1, 0.3],
                    "confidence": 0.8,
                    "provenance": [ARTIFACT_REF],
                },
            }
        ],
    }


def _candidate_args():
    return {
        "observation_ref": OBSERVATION_REF,
        "scene_revision": SCENE_REVISION,
        "frame_id": FRAME_ID,
        "calibration_ref": CALIBRATION_REF,
        "freshness_ms": 25,
        "max_age_ms": 1000,
        "candidate_set_ref": CANDIDATE_SET_REF,
        "candidates": [
            {
                "candidate_ref": CANDIDATE_REF,
                "entity_ref": ENTITY_REF,
                "grasp_frame": {
                    "frame_id": FRAME_ID,
                    "unit": "m",
                    "position_m": [0.15, -0.15, 0.12],
                    "orientation_xyzw": [0.0, 0.0, 0.0, 1.0],
                },
                "approach_direction": {
                    "frame_id": FRAME_ID,
                    "unit": "unitless",
                    "vector": [0.0, 0.0, -1.0],
                },
                "score": 0.81,
                "confidence": 0.77,
                "provenance": [ARTIFACT_REF],
                "qualification": "proposed",
            }
        ],
    }


def _prepare_args():
    args = _candidate_args()
    args["candidates"][0]["qualification"] = "proposed"
    return args


def _action_args(acquire_ref=None):
    value = {
        "observation_ref": OBSERVATION_REF,
        "scene_revision": SCENE_REVISION,
        "frame_id": FRAME_ID,
        "calibration_ref": CALIBRATION_REF,
        "freshness_ms": 25,
        "max_age_ms": 1000,
        "candidate_set_ref": CANDIDATE_SET_REF,
        "preparation_ref": PREPARATION_REF,
        "candidate_ref": CANDIDATE_REF,
        "entity_ref": ENTITY_REF,
        "capability_snapshot_ref": "artifact://capabilities/scene-7/snapshot",
        "assignment_ref": "artifact://assignments/task-1/revision-1/acquire",
    }
    if acquire_ref is not None:
        value.update({"acquire_invocation_ref": acquire_ref, "destination_ref": "destination://bin/primary"})
    return value


async def _terminal_action(coordinator, task_id, client, tool_id, arguments):
    admitted = await coordinator.start_action(task_id, tool_id, arguments)
    invocation_id = admitted["data"]["invocation_id"]
    result = await client.invocation_result(invocation_id)
    while result["data"].get("phase") == "running":
        result = await client.invocation_result(invocation_id)
    coordinator.observe_action(task_id, invocation_id, result)
    return result


def _coordinator(tmp_path, client, experience=None):
    return AgentTaskCoordinator(
        workspace=tmp_path,
        config=ForgeConfig(
            evidence={
                "capture_timeout_s": 0.1,
                "post_capture_timeout_s": 0.1,
                "connection_timeout_s": 0.1,
            }
        ),
        client=client,
        experience=experience,
    )


@pytest.mark.asyncio
async def test_full_workflow_uses_one_agent_task_and_creates_episode(tmp_path):
    analyzer = StaticAnalyzer()
    transport = FakeGatewayTransport(
        ObservationProvider(),
        understanding_provider=UnderstandingProvider(),
        grasp_provider=GraspProvider(),
        preparation_provider=PreparationProvider(),
        acquire_provider=_acquire_provider(),
        place_provider=PlaceProvider(),
        now=NOW,
    )
    async with ForgeToolClient("http://fake", transport=transport) as client:
        experience = ExperienceCoordinator(workspace=tmp_path, analyzer=analyzer)
        coordinator = _coordinator(tmp_path, client, experience)
        # The coordinator owns the task store; bind the documented outcome source
        # explicitly after both objects exist to avoid a second execution path.
        experience.outcome_source = AgentTaskOutcomeSource(coordinator)
        task = coordinator.create_task(
            task_description="pick and place one container",
            verification=TaskVerificationContract(
                mode="off",
                goal="complete the bounded pick and place workflow",
                success_criteria=["the object is placed"],
            ),
        )
        observed = await coordinator.invoke_query(
            task.task_id, "scene.observe", {"sensor_ref": "sensor/front", "max_age_ms": 1000}
        )
        await coordinator.invoke_query(task.task_id, "scene.understand", _understanding_args())
        await coordinator.invoke_query(task.task_id, "grasp.propose", _proposal_args())
        await coordinator.invoke_query(task.task_id, "manipulation.prepare", _prepare_args())
        acquire = await _terminal_action(
            coordinator, task.task_id, client, "object.acquire", _action_args()
        )
        acquire_ref = acquire["data"]["invocation_id"]
        await _terminal_action(
            coordinator, task.task_id, client, "object.place", _action_args(acquire_ref)
        )
        finalized = await coordinator.finalize_task(task.task_id)
        await asyncio.sleep(0.05)

    assert observed["data"]["observation_ref"] == OBSERVATION_REF
    assert finalized.status is AgentTaskStatus.SUCCEEDED
    records = finalized.execution_records
    assert len(records) == 6
    assert {item.revision_id for item in records} == {finalized.active_revision_id}
    assert [item.tool_id for item in records] == [
        "scene.observe",
        "scene.understand",
        "grasp.propose",
        "manipulation.prepare",
        "object.acquire",
        "object.place",
    ]
    assert all(item.status == "succeeded" for item in records)
    assert all(item.invocation_id for item in records if item.semantics == "action")
    episode = experience.store.get_episode_by_root(task.task_id)
    assert episode is not None
    assert episode.outcome.successful
    assert episode.outcome.capability_outcome_summary.status_counts == {"succeeded": 2}
    assert len(analyzer.episodes) == 1
    assert transport.invocations
    assert all(record["tool_id"] in {"object.acquire", "object.place"} for record in transport.invocations.values())


@pytest.mark.asyncio
async def test_task_lifecycle_rejects_nonterminal_finalize_and_unknown_retry(tmp_path):
    transport = FakeGatewayTransport(
        ObservationProvider(),
        acquire_provider=_acquire_provider(status="unknown"),
        now=NOW,
    )
    async with ForgeToolClient("http://fake", transport=transport) as client:
        coordinator = _coordinator(tmp_path, client)
        task = coordinator.create_task(
            task_description="reconcile one bounded action",
            verification=TaskVerificationContract(mode="off"),
        )
        admitted = await coordinator.start_action(task.task_id, "object.acquire", _action_args())
        with pytest.raises(AgentTaskError, match="cannot finalize"):
            await coordinator.finalize_task(task.task_id)
        invocation_id = admitted["data"]["invocation_id"]
        result = await client.invocation_result(invocation_id)
        coordinator.observe_action(task.task_id, invocation_id, result)
        with pytest.raises(AgentTaskError, match="unknown remote state"):
            await coordinator.start_action(task.task_id, "object.acquire", _action_args())
        finalized = await coordinator.finalize_task(task.task_id)

    assert finalized.status is AgentTaskStatus.FAILED
    assert finalized.execution_records[-1].status == "unknown"
    assert finalized.before_snapshot_ref is not None


@pytest.mark.asyncio
async def test_cancelled_action_requires_observation_before_task_terminal(tmp_path):
    pending = AcquireSnapshot(
        status="succeeded",
        capability_phase="hold",
        world_change_started=True,
        evidence_availability="partial",
        artifact_refs=("artifact://acquire-7/settlement",),
        pending_polls=2,
    )
    transport = FakeGatewayTransport(
        ObservationProvider(),
        acquire_provider=type("Provider", (), {"acquire": lambda self, request: pending})(),
        now=NOW,
    )
    async with ForgeToolClient("http://fake", transport=transport) as client:
        coordinator = _coordinator(tmp_path, client)
        task = coordinator.create_task(
            task_description="cancel a bounded action",
            verification=TaskVerificationContract(mode="off"),
        )
        admitted = await coordinator.start_action(task.task_id, "object.acquire", _action_args())
        cancelling = await coordinator.cancel_task(task.task_id, reason="operator stop")
        assert cancelling.status is AgentTaskStatus.CANCELLING
        invocation_id = admitted["data"]["invocation_id"]
        terminal = await client.invocation_result(invocation_id)
        coordinator.observe_action(task.task_id, invocation_id, terminal)
        finalized = await coordinator.finalize_task(task.task_id)

    assert finalized.status is AgentTaskStatus.CANCELLED
    assert finalized.execution_records[-1].status == "cancelled"
