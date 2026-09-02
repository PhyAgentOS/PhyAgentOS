from types import SimpleNamespace

from PhyAgentOS.agent.experience.analyzer import ModelExperienceAnalyzer
from PhyAgentOS.agent.experience.attribution import (
    assess_evolution_attribution,
    build_analyzer_attribution_context,
    validate_assessment_attribution,
)
from PhyAgentOS.agent.experience.contracts import (
    CapabilityOutcomeSummary,
    ExperienceAssessment,
    FailureObservationProposal,
    LessonEligibility,
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


def test_attribution_context_maps_owner_classes_without_authorizing_success():
    summary = CapabilityOutcomeSummary(
        status_counts={"failed": 1},
        failure_owner_counts={"planner": 1},
        evidence_availability_counts={"partial": 1},
    )
    context = build_analyzer_attribution_context(_episode(summary))
    assert context["requires_semantic_attribution_owners"] == ["planner"]
    assert context["required_lesson_reason"] is None
    assert context["task_success_authorized"] is False


def test_infrastructure_and_evidence_only_claims_must_use_bounded_lesson_reason():
    related = FailureObservationProposal(
        eligibility=LessonEligibility(
            decision="related",
            reason="workflow_related",
            confidence=0.9,
            rationale="workflow issue",
        ),
        workflow_key="pick-place",
        pattern_key="check-before-action",
        pattern_summary="check readiness before action",
        applies_when=["before action"],
        does_not_apply_when=["external outage"],
        recovery_principle="recheck state",
    )
    infrastructure = _episode(
        CapabilityOutcomeSummary(
            status_counts={"failed": 1},
            failure_owner_counts={"infrastructure": 1},
        )
    )
    assessment = ExperienceAssessment(
        outcome="failure",
        reusable=False,
        confidence=0.5,
        rationale="failure",
        failure_observations=[related],
    )
    decision = validate_assessment_attribution(infrastructure, assessment)
    assert decision.allowed is False
    assert decision.reason == "external_or_infrastructure_misattributed"

    evidence_only = _episode(
        CapabilityOutcomeSummary(
            status_counts={"failed": 1},
            evidence_availability_counts={"unknown": 1},
        )
    )
    decision = validate_assessment_attribution(evidence_only, assessment)
    assert decision.allowed is False
    assert decision.reason == "evidence_limit_misattributed"


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


async def test_analyzer_receives_attribution_context_as_untrusted_input():
    captured = {}

    class Provider:
        async def chat_with_retry(self, **kwargs):
            captured["messages"] = kwargs["messages"]
            return SimpleNamespace(
                finish_reason="stop",
                content=(
                    '{"version":"experience_assessment_v1","outcome":"ignored",'
                    '"reusable":false,"confidence":0.1,"rationale":"diagnostic",'
                    '"skill_candidate":null,"failure_observations":[],'
                    '"contradicted_lesson_ids":[],"conflicts":[]}'
                ),
            )

    summary = CapabilityOutcomeSummary(
        status_counts={"failed": 1},
        failure_owner_counts={"planner": 1},
    )
    await ModelExperienceAnalyzer(provider=Provider(), model="test").assess(
        _episode(summary), candidates=[], lessons=[], clusters=[], skill_catalog=[]
    )
    assert "capability_attribution_context" in captured["messages"][1]["content"]
    assert "task_success_authorized" in captured["messages"][1]["content"]
