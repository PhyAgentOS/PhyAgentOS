from PhyAgentOS.agent.experience.attribution import assess_evolution_attribution
from PhyAgentOS.agent.experience.contracts import (
    CapabilityOutcomeSummary,
    ExperienceAssessment,
    TaskEpisode,
    TaskOutcomeEnvelope,
)
from PhyAgentOS.agent.experience.evolution import SkillEvolutionManager


def _episode(summary):
    return TaskEpisode(
        episode_id="episode-1",
        root_task_id="task-1",
        task_summary="pick and place",
        goal="complete task",
        outcome=TaskOutcomeEnvelope(
            task_id="task-1",
            root_task_id="task-1",
            goal="complete task",
            capability_outcome_summary=summary,
        ),
    )


def test_known_capability_outcomes_are_allowed():
    decision = assess_evolution_attribution(_episode(CapabilityOutcomeSummary()))
    assert decision.allowed is True
    assert decision.reason == "ready"


def test_unknown_and_unsettled_statuses_are_blocked_with_bounded_payload():
    summary = CapabilityOutcomeSummary(
        status_counts={"unknown": 1, "cancelled": 2},
        outcome_unknown_count=1,
    )
    decision = assess_evolution_attribution(_episode(summary))
    assert decision.allowed is False
    assert decision.reason == "capability_outcome_unsettled"
    assert decision.event_payload == {
        "reason": "capability_outcome_unsettled",
        "status_counts": {"cancelled": 2, "unknown": 1},
        "projection_error_count": 0,
        "projection_error_codes": [],
    }


def test_projection_errors_take_precedence_over_unsettled_status():
    summary = CapabilityOutcomeSummary(
        status_counts={"unknown": 1},
        projection_error_count=1,
        projection_error_codes=["invalid_summary_fields"],
    )
    decision = assess_evolution_attribution(_episode(summary))
    assert decision.allowed is False
    assert decision.reason == "capability_projection_error"


def test_evolution_manager_blocks_writes_and_records_event():
    events = []
    seen = set()

    class Store:
        def list_lessons(self, *, status):
            return []

        def record_event_once(self, event_type, subject_id, payload):
            key = (event_type, subject_id, repr(payload))
            if key in seen:
                return False
            seen.add(key)
            events.append((event_type, subject_id, payload))
            return True

    manager = SkillEvolutionManager(workspace=".", store=Store())
    episode = _episode(CapabilityOutcomeSummary(status_counts={"stopped": 1}))
    assessment = ExperienceAssessment(
        outcome="failure",
        reusable=False,
        confidence=0.5,
        rationale="unsettled",
    )
    assert manager.apply(episode, assessment) == set()
    assert manager.apply(episode, assessment) == set()
    assert len(events) == 1
    assert events[0][0] == "capability_attribution_blocked"
    assert events[0][2]["status_counts"] == {"stopped": 1}
