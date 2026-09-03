from __future__ import annotations

import asyncio
import json

import pytest

from PhyAgentOS.state_io import (
    SessionCompileApproval,
    SessionCompileError,
    StateFileDriftError,
    StateFileError,
    compile_sessions_to_agent_tasks,
    parse_sessions_preview,
    parse_state_file,
    parse_targets_shadow,
    render_environment_projection,
)
from PhyAgentOS.state_io.protocol import write_projection


def _write_state(path, *, kind, mode, data, revision="r1", source="workspace://replay"):
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
    path.write_text(
        "# PAOS state\n\n```json\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
        + "\n```\n",
        encoding="utf-8",
    )


class _EmptyStore:
    def find_by_origin_dedup_key(self, origin_key):
        return []

    def active(self):
        return None


class _FailingCoordinator:
    def __init__(self):
        self.store = _EmptyStore()
        self.calls = 0

    def create_task(self, **kwargs):
        self.calls += 1
        raise RuntimeError("simulated store failure")


def _session(path, *, unknown=False):
    item = {
        "session_id": "replay-1",
        "intent": "replay a bounded declaration",
        "acceptance_criteria": ["declaration is accepted"],
        "retry_limit": 1,
    }
    if unknown:
        item["status"] = "pending"
    _write_state(path, kind="sessions", mode="input", data={"sessions": [item]})


def _targets(path):
    _write_state(
        path,
        kind="targets",
        mode="input",
        data={
            "profile_id": "replay-profile",
            "observation_modalities": ["rgb"],
            "action_space": ["object.acquire"],
            "limits": {"cartesian_speed_m_s": {"value": 0.1}},
        },
    )


def _environment():
    return {
        "schema_version": "paos.environment.v1",
        "scene_revision": "scene-replay-1",
        "snapshot_ref": "evidence://replay/after",
        "phase": "after",
        "captured_at": "2026-09-03T00:00:00+00:00",
        "source_id": "sensor://replay/camera",
        "frame": "world",
        "calibration_ref": "calibration://replay/v1",
        "scene_graph": {"nodes": [], "relations": []},
    }


def test_replay_is_deterministic_across_workspaces_without_lifecycle_side_effect(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    first_path = first / "SESSIONS.md"
    second_path = second / "SESSIONS.md"
    _session(first_path)
    second_path.write_bytes(first_path.read_bytes())

    first_preview = parse_sessions_preview(first_path)
    second_preview = parse_sessions_preview(second_path)
    assert first_preview.source.data_sha256 == second_preview.source.data_sha256
    assert first_preview.previews == second_preview.previews

    assert not (first / ".paos").exists()
    assert not (second / ".paos").exists()


def test_unknown_fields_fail_before_fake_store_or_gateway_can_be_touched(tmp_path):
    path = tmp_path / "SESSIONS.md"
    _session(path, unknown=True)
    coordinator = _FailingCoordinator()
    with pytest.raises(StateFileError, match="unknown field"):
        parse_sessions_preview(path)
    assert coordinator.calls == 0
    assert not (tmp_path / ".paos").exists()


def test_store_failure_is_wrapped_and_does_not_leave_partial_lifecycle_state(tmp_path):
    path = tmp_path / "SESSIONS.md"
    _session(path)
    source_digest = parse_sessions_preview(path).source.data_sha256
    approval = SessionCompileApproval(
        approval_id="replay-approval",
        source_sha256=source_digest,
        approved_by="operator",
        confirmed_at="2026-09-03T09:00:00+00:00",
    )
    coordinator = _FailingCoordinator()

    with pytest.raises(SessionCompileError, match="compilation failed"):
        asyncio.run(
            compile_sessions_to_agent_tasks(
                path,
                coordinator=coordinator,
                approval=approval,
            )
        )
    assert coordinator.calls == 1
    assert not (tmp_path / ".paos").exists()


def test_projection_drift_rejects_update_and_preserves_previous_bytes(tmp_path):
    path = tmp_path / "SKILLRUNTIME.md"
    write_projection(
        path,
        kind="skillruntime",
        data={"skill_name": "replay-skill", "status": "running"},
        revision="runtime-1",
        source="runtime://replay/state",
    )
    before = path.read_bytes()
    with pytest.raises(StateFileDriftError):
        write_projection(
            path,
            kind="skillruntime",
            revision="runtime-2",
            source="runtime://replay/state",
            data={"skill_name": "changed", "status": "stopped"},
            expected_sha256="0" * 64,
        )
    assert path.read_bytes() == before
    assert parse_state_file(path, expected_kind="skillruntime").data["status"] == "running"


def test_projection_replay_preserves_digest_and_adapters_remain_no_motion(tmp_path):
    first = tmp_path / "ENVIRONMENT.first.md"
    second = tmp_path / "ENVIRONMENT.second.md"
    render_environment_projection(
        first,
        _environment(),
        revision="scene-replay-1",
        source="snapshot://replay/after",
    )
    render_environment_projection(
        second,
        _environment(),
        revision="scene-replay-1",
        source="snapshot://replay/after",
    )
    assert parse_state_file(first, expected_kind="environment").data_sha256 == parse_state_file(
        second, expected_kind="environment"
    ).data_sha256

    target_path = tmp_path / "TARGETS.md"
    _targets(target_path)
    report = parse_targets_shadow(target_path)
    assert report.valid is True
    assert report.motion_authorized is False
    session_path = tmp_path / "SESSIONS.md"
    _session(session_path)
    assert parse_sessions_preview(session_path).previews[0]["motion_authorized"] is False
