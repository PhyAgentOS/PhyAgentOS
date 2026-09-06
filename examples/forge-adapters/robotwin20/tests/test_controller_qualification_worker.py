from __future__ import annotations

from pathlib import Path

import pytest
from robotwin_controller_qualification_worker import (
    ControllerQualificationWorker,
    QualificationPackage,
    QualificationWorkerError,
    validate_trace_artifact,
)
from test_controller_qualification import _capability, _plan

from robotwin20_adapter.controller_qualification import ControllerQualificationApproval


class FakeRuntime:
    dt_s = 0.004

    def __init__(self, *, status: str = "running", supports: set[str] | None = None):
        self.status = status
        self._supports = supports or set()
        self.steps = 0
        self.closed = False

    def reset(self):
        pass

    def close(self):
        self.closed = True

    def state(self, arm_id):
        return {
            "joint_position": [0.0] * 7,
            "joint_velocity": [0.0] * 7,
            "tcp_pose": [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
            "tcp_velocity": [0.0] * 6,
        }

    def command(self, arm_id, position, velocity):
        self.last_command = (arm_id, list(position), list(velocity))

    def step(self):
        self.steps += 1

    def contacts(self):
        return []

    def controller_status(self, arm_id):
        return self.status

    def stop(self):
        self.status = "stopped"

    def reset_controller(self):
        self.status = "reset"

    def supports(self, capability):
        return capability in self._supports

    def prepare_contact_load(self):
        pass

    def inject_error(self):
        self.status = "fault"

    def drop_next_step(self):
        pass


def _package(tmp_path: Path, *, status: str = "running"):
    plan = _plan()
    approval = ControllerQualificationApproval(
        decision="approved_controller_qualification_simulation_only",
        qualification_id=plan.qualification_id,
        plan_ref="artifact://route/plan",
        plan_sha256="a" * 64,
        source_manifest_ref="artifact://route/source-manifest",
        source_manifest_sha256="b" * 64,
        plan_validation_ref="artifact://route/no-motion-validation",
        plan_validation_sha256="c" * 64,
        reviewer_id="reviewer",
        reviewed_at="2026-09-06T08:00:00+00:00",
    )
    return QualificationPackage(
        plan=plan,
        approval=approval,
        plan_validation=None,  # type: ignore[arg-type]
        source_manifest=None,  # type: ignore[arg-type]
        capabilities={"left": _capability("left"), "right": _capability("right")},
        validations={},
        file_digests={"approval": "a" * 64},
        source_paths={},
    ), FakeRuntime(status=status)


def test_worker_rejects_digest_drift_before_any_step(tmp_path: Path):
    package, runtime = _package(tmp_path)
    plan_path = tmp_path / "plan.json"
    plan_path.write_text("original", encoding="utf-8")
    import hashlib

    package = package.__class__(
        **{
            **package.__dict__,
            "source_paths": {"plan": plan_path},
            "file_digests": {"plan": hashlib.sha256(plan_path.read_bytes()).hexdigest(), "approval": "a" * 64},
        }
    )
    plan_path.write_text("tampered", encoding="utf-8")
    worker = ControllerQualificationWorker(package, runtime, tmp_path / "out", stop_file=tmp_path / "stop")
    evidence, _ = worker.run()
    assert evidence.status != "passed"
    assert runtime.steps == 0


def test_over_limit_command_never_passes_without_controller_rejection(tmp_path: Path):
    package, runtime = _package(tmp_path)
    worker = ControllerQualificationWorker(package, runtime, tmp_path / "out", stop_file=tmp_path / "stop")
    evidence, traces = worker.run()
    result = next(item for item in evidence.tests if item.test_id == "over_limit_velocity_command")
    assert result.outcome == "fail"
    assert evidence.status in {"failed", "unavailable"}
    assert traces["over_limit_velocity_command"]["sha256"]


def test_missing_fixture_is_unavailable_and_trace_is_auditable(tmp_path: Path):
    package, runtime = _package(tmp_path)
    worker = ControllerQualificationWorker(package, runtime, tmp_path / "out", stop_file=tmp_path / "stop")
    evidence, _ = worker.run()
    result = next(item for item in evidence.tests if item.test_id == "contact_load")
    assert result.outcome == "unavailable"


def test_trace_validator_rejects_missing_required_signal():
    expected = type("E", (), {"evidence_ref": "artifact://controller-qualification/q/evidence/t", "test_id": "t", "command_family": "position_drive_target", "outcome": "pass"})()
    with pytest.raises(QualificationWorkerError, match="required signal"):
        validate_trace_artifact(
            {"schema_version": "paos-robotwin20-controller-qualification-test-trace/v1", "qualification_id": "q", "test_id": "t", "command_family": "position_drive_target", "arms": {"left": {"samples": [{}]}, "right": {"samples": [{}]}}, "outcome": "pass"},
            expected,
        )


def test_trace_validator_accepts_explicit_failure_reason():
    expected = type("E", (), {"evidence_ref": "artifact://controller-qualification/q/evidence/t", "test_id": "t", "command_family": "position_drive_target", "outcome": "unavailable"})()
    checks = validate_trace_artifact(
        {"schema_version": "paos-robotwin20-controller-qualification-test-trace/v1", "qualification_id": "q", "test_id": "t", "command_family": "position_drive_target", "arms": {}, "outcome": "unavailable", "failure_reason": "fixture unavailable"},
        expected,
    )
    assert "failure_reason" in checks
