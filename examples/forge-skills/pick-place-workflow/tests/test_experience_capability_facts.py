from types import SimpleNamespace

from PhyAgentOS.agent.experience.contracts import TaskEpisode
from PhyAgentOS.agent.experience.source import AgentTaskOutcomeSource
from PhyAgentOS.forge.task import AgentTaskRecord, PlanRevision, ToolExecutionRecord
from PhyAgentOS.verification.contracts import TaskVerificationContract


def _summary(*, status="succeeded", phase="retreat", owner=None, code=None):
    return {
        "version": "capability_outcome_summary_v1",
        "capability_phase": phase,
        "status": status,
        "failure_owner": owner,
        "failure_code": code,
        "world_change_started": status != "failed",
        "outcome_known": status != "unknown",
        "evidence_availability": "partial",
        "artifact_refs": ["artifact://opaque/trajectory"],
        "bounded_metric_names": ["release_height"],
    }


def _response(summary):
    return {"ok": True, "data": {"result": {"capability_outcome_summary": summary}}}


def _task(records, *, verdict=None):
    revision = PlanRevision(
        revision_id="revision-1",
        number=1,
        reason="initial",
        execution_records=records,
        verdict=verdict,
    )
    return AgentTaskRecord(
        task_id="task-1",
        task_description="pick and place",
        verification=TaskVerificationContract(mode="off"),
        revisions=[revision],
        active_revision_id="revision-1",
        verdict=verdict,
    )


def _record(summary, *, record_id="record-1", status="succeeded"):
    return ToolExecutionRecord(
        record_id=record_id,
        revision_id="revision-1",
        tool_id="object.place",
        semantics="action",
        caller_id="paos:test",
        status=status,
        response=_response(summary),
        evidence_refs=[],
    )


def test_agent_task_outcome_contains_redacted_capability_fact_without_artifacts_or_codes():
    task = _task([_record(_summary())])
    outcome = AgentTaskOutcomeSource(SimpleNamespace(get_task=lambda _: task)).build("task-1")
    assert len(outcome.capability_outcomes) == 1
    fact = outcome.capability_outcomes[0]
    assert fact.capability == "object.place"
    assert fact.capability_phase == "retreat"
    assert fact.record_ref.startswith("evidence:")
    serialized = outcome.model_dump_json()
    assert "artifact://opaque/trajectory" not in serialized
    assert "failure_code" not in serialized
    assert outcome.final_verdict is None
    assert outcome.capability_outcome_summary.status_counts == {"succeeded": 1}
    assert outcome.capability_outcome_summary.world_change_started_count == 1


def test_unknown_and_failed_facts_preserve_execution_state_without_becoming_learning_authority():
    records = [
        _record(
            _summary(status="unknown", phase="release", owner="execution", code="timeout"),
            record_id="unknown-1",
            status="unknown",
        ),
        _record(
            _summary(status="failed", phase="transport", owner="planner", code="no_route"),
            record_id="failed-1",
            status="failed",
        ),
    ]
    outcome = AgentTaskOutcomeSource(SimpleNamespace(get_task=lambda _: _task(records))).build(
        "task-1"
    )
    assert [item.status for item in outcome.capability_outcomes] == ["unknown", "failed"]
    assert [item.failure_owner for item in outcome.capability_outcomes] == [
        "execution",
        "planner",
    ]
    assert not outcome.learnable
    assert outcome.capability_outcome_summary.status_counts == {
        "failed": 1,
        "unknown": 1,
    }
    assert outcome.capability_outcome_summary.failure_owner_counts == {
        "execution": 1,
        "planner": 1,
    }
    assert outcome.capability_outcome_summary.outcome_unknown_count == 1


def test_invalid_projection_is_diagnostic_and_does_not_create_fact():
    invalid = _summary()
    invalid["capability_phase"] = "ik"
    task = _task([_record(invalid)])
    outcome = AgentTaskOutcomeSource(SimpleNamespace(get_task=lambda _: task)).build("task-1")
    assert outcome.capability_outcomes == []
    assert [item.code for item in outcome.capability_outcome_errors] == [
        "invalid_capability_phase"
    ]
    assert outcome.capability_outcome_summary.projection_error_count == 1
    assert outcome.capability_outcome_summary.projection_error_codes == [
        "invalid_capability_phase"
    ]
    assert outcome.final_verdict is None


def test_provider_private_tool_id_is_not_persisted_in_capability_fact():
    task = _task([_record(_summary())])
    task.revisions[0].execution_records[0].tool_id = "robotwin_sapien_place"
    outcome = AgentTaskOutcomeSource(SimpleNamespace(get_task=lambda _: task)).build("task-1")
    assert outcome.capability_outcomes[0].capability == "bounded_action"
    assert "robotwin" not in outcome.capability_outcomes[0].model_dump_json().lower()


def test_task_episode_round_trip_preserves_capability_facts():
    outcome = AgentTaskOutcomeSource(
        SimpleNamespace(get_task=lambda _: _task([_record(_summary())]))
    ).build("task-1")
    episode = TaskEpisode(
        episode_id="episode-1",
        root_task_id="task-1",
        task_summary="pick and place",
        goal=outcome.goal,
        outcome=outcome,
    )
    restored = TaskEpisode.model_validate_json(episode.model_dump_json())
    assert restored.outcome.capability_outcomes[0].capability_phase == "retreat"
    assert restored.outcome.capability_outcome_summary.status_counts == {"succeeded": 1}
