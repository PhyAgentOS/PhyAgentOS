from __future__ import annotations

import asyncio
import json

import pytest

from PhyAgentOS.config.schema import ForgeConfig
from PhyAgentOS.forge.task import AgentTaskCoordinator, AgentTaskStatus
from PhyAgentOS.state_io import (
    SessionCompileApproval,
    SessionCompileError,
    StateFileDriftError,
    StateFileError,
    TargetProfileApproval,
    compile_sessions_to_agent_tasks,
    parse_sessions_preview,
    parse_state_file,
    parse_targets_shadow,
    promote_targets_candidate,
    render_environment_projection,
    render_lessons_projection,
    render_skillruntime_projection,
)
from PhyAgentOS.state_io.protocol import canonical_sha256


def write_state(path, *, kind, mode, data, revision="r1", source="workspace://test"):
    payload = {
        "paos": {
            "protocol": "paos.state-file.v1",
            "kind": kind,
            "mode": mode,
            "revision": revision,
            "source": source,
        },
        "data": data,
    }
    path.write_text("# state\n\n```json\n" + json.dumps(payload) + "\n```\n", encoding="utf-8")


def test_targets_shadow_validation_is_strict_and_no_motion(tmp_path):
    path = tmp_path / "TARGETS.md"
    data = {
        "profile_id": "panda-lab",
        "observation_modalities": ["rgb", "depth"],
        "action_space": ["object.acquire", "object.place"],
        "limits": {
            "joint_position_rad": {"min": [-1.0, -2.0], "max": [1.0, 2.0]},
            "cartesian_speed_m_s": {"value": 0.2},
        },
    }
    write_state(path, kind="targets", mode="input", data=data)
    report = parse_targets_shadow(path, baseline=data)
    assert report.valid is True
    assert report.differences == ()
    assert report.candidate_sha256
    assert report.motion_authorized is False


def test_targets_reject_invalid_limit_and_unknown_field(tmp_path):
    path = tmp_path / "TARGETS.md"
    write_state(
        path,
        kind="targets",
        mode="input",
        data={
            "profile_id": "panda-lab",
            "observation_modalities": ["rgb"],
            "action_space": ["object.place"],
            "limits": {"joint": {"min": [2], "max": [1]}},
            "status": "pending",
        },
    )
    report = parse_targets_shadow(path)
    assert report.valid is False
    assert any("unknown field" in error for error in report.errors)
    assert any("min exceeds max" in error for error in report.errors)
    assert report.motion_authorized is False


def test_targets_candidate_requires_source_and_baseline_bound_approval(tmp_path):
    path = tmp_path / "TARGETS.md"
    baseline = {
        "profile_id": "panda-lab",
        "observation_modalities": ["rgb"],
        "action_space": ["object.place"],
        "limits": {"cartesian_speed_m_s": {"value": 0.2}},
    }
    write_state(path, kind="targets", mode="input", data=baseline)
    source_digest = parse_targets_shadow(path, baseline=baseline).candidate_sha256
    approval = TargetProfileApproval(
        approval_id="targets-approval-1",
        source_sha256=source_digest,
        baseline_sha256=canonical_sha256(baseline),
        approved_by="operator",
        confirmed_at="2026-09-03T09:00:00+00:00",
    )
    candidate = promote_targets_candidate(path, baseline=baseline, approval=approval)
    assert candidate.profile_id == "panda-lab"
    assert candidate.differences == ()
    assert candidate.motion_authorized is False
    assert candidate.data == baseline


def test_targets_candidate_rejects_baseline_drift(tmp_path):
    path = tmp_path / "TARGETS.md"
    baseline = {
        "profile_id": "panda-lab",
        "observation_modalities": ["rgb"],
        "action_space": ["object.place"],
        "limits": {"cartesian_speed_m_s": {"value": 0.2}},
    }
    write_state(path, kind="targets", mode="input", data=baseline)
    source_digest = parse_targets_shadow(path, baseline=baseline).candidate_sha256
    approval = {
        "approval_id": "targets-approval-1",
        "source_sha256": source_digest,
        "baseline_sha256": "0" * 64,
        "approved_by": "operator",
        "confirmed_at": "2026-09-03T09:00:00+00:00",
    }
    with pytest.raises(StateFileError, match="baseline digest"):
        promote_targets_candidate(path, baseline=baseline, approval=approval)


def test_parser_rejects_missing_or_malformed_structured_block(tmp_path):
    path = tmp_path / "ENVIRONMENT.md"
    path.write_text("# no structured state\n", encoding="utf-8")
    with pytest.raises(StateFileError, match="exactly one fenced"):
        parse_state_file(path, expected_kind="environment")


def test_projection_renderers_are_atomic_and_drift_checked(tmp_path):
    path = tmp_path / "SKILLRUNTIME.md"
    result = render_skillruntime_projection(
        path, {"skill_name": "pick-place", "status": "stopped"}, revision="runtime-1", source="runtime://state"
    )
    assert result.changed is True
    parsed = parse_state_file(path, expected_kind="skillruntime")
    assert parsed.mode == "projection"
    assert parsed.data_sha256 == result.data_sha256
    second = render_environment_projection(
        tmp_path / "ENVIRONMENT.md", {"revision": "scene-1", "entities": []}, revision="scene-1", source="snapshot://1"
    )
    assert second.changed is True
    with pytest.raises(StateFileDriftError):
        from PhyAgentOS.state_io.protocol import write_projection

        write_projection(
            path,
            kind="skillruntime",
            revision="runtime-2",
            source="runtime://state",
            data={"skill_name": "other"},
            expected_sha256="0" * 64,
        )


def test_lessons_projection_uses_projection_mode(tmp_path):
    path = tmp_path / "LESSONS.md"
    result = render_lessons_projection(
        path,
        {"skill_name": "pick-place", "lessons": [{"lesson_id": "l1", "status": "active"}]},
        revision="exp-1",
        source="experience://ledger",
    )
    parsed = parse_state_file(path, expected_kind="lessons")
    assert parsed.mode == "projection"
    assert parsed.data_sha256 == result.data_sha256


def test_sessions_preview_is_deterministic_and_does_not_create_task_store(tmp_path):
    path = tmp_path / "SESSIONS.md"
    write_state(
        path,
        kind="sessions",
        mode="input",
        data={
            "sessions": [
                {
                    "session_id": "pick-001",
                    "intent": "Pick the red cup",
                    "acceptance_criteria": ["cup is in gripper"],
                    "retry_limit": 2,
                }
            ]
        },
    )
    first = parse_sessions_preview(path)
    second = parse_sessions_preview(path)
    assert first.previews == second.previews
    preview = first.previews[0]
    assert preview["preview_status"] == "dry_run"
    assert preview["agent_task_write"] is False
    assert preview["watchdog_dispatch"] is False
    assert preview["motion_authorized"] is False
    assert not (tmp_path / ".paos").exists()


def test_sessions_rejects_status_field_as_second_state_machine(tmp_path):
    path = tmp_path / "SESSIONS.md"
    write_state(
        path,
        kind="sessions",
        mode="input",
        data={
            "sessions": [
                {
                    "session_id": "pick-001",
                    "intent": "Pick",
                    "acceptance_criteria": ["done"],
                    "retry_limit": 1,
                    "status": "pending",
                }
            ]
        },
    )
    with pytest.raises(StateFileError, match="unknown field"):
        parse_sessions_preview(path)


def test_sessions_rejects_duplicate_or_unsafe_parent_identity(tmp_path):
    path = tmp_path / "SESSIONS.md"
    write_state(
        path,
        kind="sessions",
        mode="input",
        data={
            "sessions": [
                {
                    "session_id": "pick-001",
                    "intent": "Pick",
                    "acceptance_criteria": ["done"],
                    "retry_limit": 1,
                    "parent_task_id": "../task",
                }
            ]
        },
    )
    with pytest.raises(StateFileError, match="parent_task_id"):
        parse_sessions_preview(path)


def test_projection_source_must_be_an_opaque_reference(tmp_path):
    with pytest.raises(StateFileError, match="filesystem path|opaque URI"):
        render_environment_projection(
            tmp_path / "ENVIRONMENT.md",
            {"revision": "scene-1"},
            revision="scene-1",
            source="/tmp/environment.json",
        )


def _write_session_file(path, sessions):
    write_state(path, kind="sessions", mode="input", data={"sessions": sessions})
    return parse_sessions_preview(path).source.data_sha256


def _coordinator(tmp_path):
    return AgentTaskCoordinator(
        workspace=tmp_path,
        config=ForgeConfig(),
        client=object(),
    )


def _approval(source_sha256):
    return SessionCompileApproval(
        approval_id="approval-1",
        source_sha256=source_sha256,
        approved_by="operator",
        confirmed_at="2026-09-03T09:00:00+00:00",
    )


def test_sessions_compile_requires_digest_bound_human_approval(tmp_path):
    path = tmp_path / "SESSIONS.md"
    digest = _write_session_file(
        path,
        [{"session_id": "pick-001", "intent": "Pick", "acceptance_criteria": ["done"], "retry_limit": 1}],
    )
    coordinator = _coordinator(tmp_path)
    with pytest.raises(SessionCompileError, match="different SESSIONS.md"):
        asyncio.run(
            compile_sessions_to_agent_tasks(
                path,
                coordinator=coordinator,
                approval=_approval("0" * 64),
            )
        )
    assert coordinator.store.active() is None
    assert digest


def test_sessions_compile_is_idempotent_and_uses_coordinator(tmp_path):
    path = tmp_path / "SESSIONS.md"
    digest = _write_session_file(
        path,
        [{
            "session_id": "pick-001",
            "intent": "Pick the red cup",
            "acceptance_criteria": ["cup is in gripper"],
            "retry_limit": 2,
        }],
    )
    coordinator = _coordinator(tmp_path)
    first = asyncio.run(
        compile_sessions_to_agent_tasks(path, coordinator=coordinator, approval=_approval(digest))
    )
    second = asyncio.run(
        compile_sessions_to_agent_tasks(path, coordinator=coordinator, approval=_approval(digest))
    )
    assert len(first.compiled) == 1
    assert second.compiled == ()
    assert len(second.reused) == 1
    task = second.reused[0]
    assert task.origin_session_key == f"statefile+sessions://{digest}/pick-001"
    assert task.retry_limit == 2
    assert task.verification.success_criteria == ["cup is in gripper"]
    assert task.status == AgentTaskStatus.EXECUTING
    assert second.motion_authorized is False


def test_sessions_compile_rejects_active_task_and_multi_session_batch(tmp_path):
    path = tmp_path / "SESSIONS.md"
    digest = _write_session_file(
        path,
        [
            {"session_id": "pick-001", "intent": "Pick", "acceptance_criteria": ["done"], "retry_limit": 0},
            {"session_id": "place-001", "intent": "Place", "acceptance_criteria": ["done"], "retry_limit": 0},
        ],
    )
    coordinator = _coordinator(tmp_path)
    with pytest.raises(SessionCompileError, match="exactly one session"):
        asyncio.run(
            compile_sessions_to_agent_tasks(path, coordinator=coordinator, approval=_approval(digest))
        )
    one_path = tmp_path / "ONE.md"
    one_digest = _write_session_file(
        one_path,
        [{"session_id": "single", "intent": "Single", "acceptance_criteria": ["done"], "retry_limit": 0}],
    )
    asyncio.run(
        compile_sessions_to_agent_tasks(one_path, coordinator=coordinator, approval=_approval(one_digest))
    )
    with pytest.raises(SessionCompileError, match="non-terminal"):
        asyncio.run(
            compile_sessions_to_agent_tasks(path, session_id="place-001", coordinator=coordinator, approval=_approval(digest))
        )


def test_sessions_compile_rejects_unknown_parent_before_creation(tmp_path):
    path = tmp_path / "SESSIONS.md"
    digest = _write_session_file(
        path,
        [{
            "session_id": "child",
            "intent": "Place",
            "acceptance_criteria": ["placed"],
            "retry_limit": 0,
            "parent_task_id": "missing-parent",
        }],
    )
    coordinator = _coordinator(tmp_path)
    with pytest.raises(SessionCompileError, match="parent AgentTask not found"):
        asyncio.run(
            compile_sessions_to_agent_tasks(path, coordinator=coordinator, approval=_approval(digest))
        )
    assert coordinator.store.active() is None
