from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
import robotwin_simulation_probe_worker as probe_worker
import yaml
from robotwin_simulation_probe_worker import (
    APPROVAL_SCHEMA_VERSION,
    SimulationProbeError,
    _artifact_record,
    _handle_factory,
    _joint_limits,
    _label_probe_actors,
    _recover_candidate_failure,
    _validate_approval,
    _validate_request_policies,
)
from test_route_readiness import _request as _route_request

from robotwin20_adapter import (
    SIMULATION_PROBE_PROFILE_SCHEMA_VERSION,
    SimulationProbeClient,
    SimulationProbeProfileError,
    build_simulation_probe_client,
    load_simulation_probe_profile,
)


def _profile() -> dict[str, object]:
    return {
        "task_name": "blocks_ranking_rgb",
        "scene_revision": "blocks_ranking_rgb-0-1",
        "embodiment_binding": {
            "robot_identity": "franka-panda",
            "gripper_identity": "panda-gripper",
            "embodiment_topology": "two-single-arm",
            "planner_profile": "curobo",
        },
    }


def _approval(root: Path, request: dict[str, object]) -> str:
    from robotwin20_adapter.route_readiness import route_geometry_digest

    inputs = {
        request["calibration_ref"]: b"{}\n",
        request["joint_limits_ref"]: b'{"policy":"joint-limits"}\n',
        request["stop_policy_ref"]: b'{"policy":"stop"}\n',
    }
    digests = {
        ref: _artifact_record(root, ref, payload)["sha256"]
        for ref, payload in inputs.items()
    }
    value = {
        "schema_version": APPROVAL_SCHEMA_VERSION,
        "decision": "approved_independent_simulation_probe",
        "motion_authorized": True,
        "producer_id": "robotwin20-independent-probe/v1",
        "producer_profile_sha256": "a" * 64,
        "task_name": "blocks_ranking_rgb",
        "scene_revision": "blocks_ranking_rgb-0-1",
        "request_id": request["request_id"],
        "candidate_ref": request["candidates"][0]["candidate_ref"],
        "route_geometry_digest": route_geometry_digest(request),
        "calibration_sha256": digests[request["calibration_ref"]],
        "joint_limits_sha256": digests[request["joint_limits_ref"]],
        "stop_policy_sha256": digests[request["stop_policy_ref"]],
        "embodiment_binding": _profile()["embodiment_binding"],
        "reviewer_id": "reviewer-1",
        "reviewed_at": "2026-09-05T00:00:00+00:00",
    }
    record = _artifact_record(
        root,
        "artifact://probe/approval.json",
        (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    )
    return record["artifact_ref"]


def test_approval_record_is_strictly_bound(tmp_path: Path):
    request = _route_request(tmp_path)
    ref = _approval(tmp_path, request)
    result = _validate_approval(
        tmp_path,
        ref,
        producer_id="robotwin20-independent-probe/v1",
        producer_profile_sha256="a" * 64,
        request=request,
        candidate_ref=request["candidates"][0]["candidate_ref"],
        profile=_profile(),
    )
    assert result["motion_authorized"] is True


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda value: value.update(motion_authorized=False), "does not authorize"),
        (lambda value: value.update(producer_id="other"), "producer binding"),
        (lambda value: value.update(scene_revision="other-scene"), "scene binding"),
        (lambda value: value.update(calibration_sha256="0" * 64), "calibration_ref digest"),
        (lambda value: value.update(reviewed_at="2026-09-05T00:00:00"), "timezone"),
    ],
)
def test_approval_mutation_fails_closed(tmp_path: Path, mutate, message: str):
    request = _route_request(tmp_path)
    ref = _approval(tmp_path, request)
    path = tmp_path / "probe" / "approval.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    with pytest.raises(SimulationProbeError, match=message):
        _validate_approval(
            tmp_path,
            ref,
            producer_id="robotwin20-independent-probe/v1",
            producer_profile_sha256="a" * 64,
            request=request,
            candidate_ref=request["candidates"][0]["candidate_ref"],
            profile=_profile(),
        )


def test_artifact_writer_is_immutable(tmp_path: Path):
    payload = b"immutable\n"
    first = _artifact_record(tmp_path, "artifact://probe/result", payload)
    assert first["sha256"] == hashlib.sha256(payload).hexdigest()
    assert _artifact_record(tmp_path, "artifact://probe/result", payload) == first
    with pytest.raises(SimulationProbeError, match="immutable"):
        _artifact_record(tmp_path, "artifact://probe/result", b"different\n")


def test_request_policies_are_materialized_and_strict(tmp_path: Path):
    request = _route_request(tmp_path)
    joint_ref = request["joint_limits_ref"]
    stop_ref = request["stop_policy_ref"]
    _artifact_record(
        tmp_path,
        joint_ref,
        (json.dumps({
            "schema_version": "paos-robotwin20-joint-limit-policy/v1",
            "planner_profile": "curobo",
            "joint_count": 7,
            "require_runtime_position_limits": True,
            "max_joint_speed_radps": 1.0,
        }, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    )
    _artifact_record(
        tmp_path,
        stop_ref,
        (json.dumps({
            "schema_version": "paos-robotwin20-stop-policy/v1",
            "max_duration_s": 12,
            "stop_file_required": True,
            "poll_each_step": True,
            "failure_recovery": "reset_simulation",
        }, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    )
    policies = _validate_request_policies(tmp_path, request, max_duration_s=12)
    assert policies["max_joint_speed_radps"] == 1.0
    assert policies["joint_limit_policy"]["artifact_ref"] == joint_ref

    request["candidates"][0]["route"][0]["waypoints"][0]["max_joint_speed_radps"] = 1.1
    with pytest.raises(SimulationProbeError, match="joint-limit policy"):
        _validate_request_policies(tmp_path, request, max_duration_s=12)

    request = _route_request(tmp_path)
    request["candidates"][0]["grasp_frame"]["max_joint_speed_radps"] = 1.1
    with pytest.raises(SimulationProbeError, match="joint-limit policy"):
        _validate_request_policies(tmp_path, request, max_duration_s=12)


def test_post_step_failure_is_snapshotted_and_reset(tmp_path: Path, monkeypatch):
    class MotionGen:
        def __init__(self):
            self.detached = False

        def detach_object_from_robot(self):
            self.detached = True

    class Planner:
        motion_gen = MotionGen()

    class Backend:
        def __init__(self):
            self.reset_count = 0

        def reset(self, *, seed):
            assert seed == 0
            self.reset_count += 1

    backend = Backend()
    request = _route_request(tmp_path)
    candidate = request["candidates"][0]
    before_ref = {"artifact_ref": "artifact://probe/before", "sha256": "a" * 64}
    monkeypatch.setattr(
        probe_worker,
        "_snapshot",
        lambda task, route_request, route_candidate: {
            "scene_revision": route_request["scene_revision"],
            "candidate_ref": route_candidate["candidate_ref"],
            "state_digest": "b" * 64,
        },
    )
    execution_state = {
        "_planner": Planner(),
        "planner_object_attached": True,
        "world_change_started": True,
        "phase": "finalizing",
        "simulator_steps": 9,
        "contact_trace": [],
    }
    response = _recover_candidate_failure(
        backend=backend,
        task=object(),
        runtime_seed=0,
        artifact_root=tmp_path,
        prefix="artifact://probe/request/candidate",
        profile={"worker_id": "probe-test/v1"},
        producer_binding={
            "producer_id": "producer-test/v1",
            "profile_sha256": "c" * 64,
            "evidence_mode": "independent_simulation_probe",
        },
        request=request,
        candidate=candidate,
        before_ref=before_ref,
        execution_state=execution_state,
        error=RuntimeError("final evidence write failed"),
    )
    assert response["status"] == "unavailable"
    assert response["reconciliation_required"] is False
    assert response["failure_evidence"]["artifact_ref"].endswith("/failure")
    assert backend.reset_count == 1
    assert execution_state["planner_object_attached"] is False
    failure = json.loads((tmp_path / "probe/request/candidate/failure.json").read_text())
    assert failure["failed_phase"] == "finalizing"
    assert failure["simulation_reset_status"] == "completed"

    no_step_state = {
        "planner_object_attached": False,
        "world_change_started": False,
        "phase": "preflight",
        "simulator_steps": 0,
        "arm_selection_attempts": [
            {"arm": "left", "status": "fail", "detail": "joint-speed limit"}
        ],
    }
    no_step_response = _recover_candidate_failure(
        backend=backend,
        task=object(),
        runtime_seed=0,
        artifact_root=tmp_path,
        prefix="artifact://probe/request/no-step-candidate",
        profile={"worker_id": "probe-test/v1"},
        producer_binding={
            "producer_id": "producer-test/v1",
            "profile_sha256": "c" * 64,
            "evidence_mode": "independent_simulation_probe",
        },
        request=request,
        candidate=candidate,
        before_ref=before_ref,
        execution_state=no_step_state,
        error=SimulationProbeError("no arm can plan candidate route"),
    )
    assert no_step_response["world_change_started"] is False
    assert no_step_response["failure_evidence"]["artifact_ref"].endswith("/failure")
    assert backend.reset_count == 1
    no_step_failure = json.loads(
        (tmp_path / "probe/request/no-step-candidate/failure.json").read_text()
    )
    assert no_step_failure["simulation_reset_status"] == "not_required"
    assert no_step_failure["arm_selection_attempts"][0]["arm"] == "left"


def test_probe_actor_labels_are_unique_and_fail_closed():
    class Actor:
        def __init__(self):
            self.name = "box"

        def set_name(self, name):
            self.name = name

    class Task:
        block1 = Actor()
        block2 = Actor()
        block3 = Actor()

    task = Task()
    _label_probe_actors(task)
    assert [task.block1.name, task.block2.name, task.block3.name] == [
        "block-red-1", "block-green-1", "block-blue-1"
    ]

    class BrokenTask:
        block1 = object()
        block2 = Actor()
        block3 = Actor()

    with pytest.raises(SimulationProbeError, match="identity"):
        _label_probe_actors(BrokenTask())


@pytest.mark.parametrize(
    "values",
    [
        [[float("nan")] * 7, [1.0] * 7],
        [[-1.0, -1.0, -1.0, -1.0, -1.0, -1.0, 2.0], [1.0] * 7],
    ],
)
def test_planner_joint_limits_reject_non_finite_or_inverted_values(values):
    class Tensor:
        def detach(self):
            return self

        def cpu(self):
            return self

        def tolist(self):
            return values

    class Limits:
        position = Tensor()

    class Kinematics:
        joint_limits = Limits()

    class RobotConfig:
        kinematics = Kinematics()

    class MotionGen:
        robot_cfg = RobotConfig()

    class Planner:
        motion_gen = MotionGen()

    with pytest.raises(SimulationProbeError, match="joint limits are invalid"):
        _joint_limits(Planner())


def test_worker_factory_does_not_advance_scene_revision_before_request(
    tmp_path: Path, monkeypatch
):
    import types

    class RuntimeProfile:
        def __init__(self, **values):
            self.values = values

    class Backend:
        def __init__(self, profile):
            self.profile = profile
            self.reset_count = 0
            self._task = None

        def reset(self, *, seed):
            self.reset_count += 1

    module = types.SimpleNamespace(
        RoboTwinRuntimeProfile=RuntimeProfile,
        RoboTwinSensorBackend=Backend,
        load_runtime_profile=lambda path: {
            "task_name": "blocks_ranking_rgb",
            "task_config": "demo_clean",
            "embodiment": ("franka-panda", "franka-panda", 0.8),
            "seed": 0,
        },
    )
    monkeypatch.setitem(sys.modules, "robotwin_backend", module)
    profile = _profile()
    profile.update(
        worker_id="probe-test/v1",
        runtime_root=str(tmp_path),
        runtime_profile=str(tmp_path / "runtime.yaml"),
    )
    backend, _ = _handle_factory(
        profile,
        tmp_path,
        producer_id="producer-test/v1",
        producer_profile_sha256="a" * 64,
        approval_ref="artifact://probe/approval.json",
        max_duration_s=1,
        stop_file=tmp_path / "control" / "stop",
    )
    assert backend.reset_count == 0
    assert backend._task is None


def test_worker_is_single_use_after_an_authorized_attempt(tmp_path: Path, monkeypatch):
    import types

    class RuntimeProfile:
        def __init__(self, **values):
            self.values = values

    class Task:
        robot = object()

    class Backend:
        def __init__(self, profile):
            self.profile = profile
            self.reset_count = 0
            self._task = None

        def reset(self, *, seed):
            assert seed == 0
            self.reset_count += 1
            self._task = Task()

        def snapshot(self):
            return {"scene_revision": "blocks_ranking_rgb-0-1"}

    module = types.SimpleNamespace(
        RoboTwinRuntimeProfile=RuntimeProfile,
        RoboTwinSensorBackend=Backend,
        load_runtime_profile=lambda path: {
            "task_name": "blocks_ranking_rgb",
            "task_config": "demo_clean",
            "embodiment": ("franka-panda", "franka-panda", 0.8),
            "seed": 0,
        },
    )
    monkeypatch.setitem(sys.modules, "robotwin_backend", module)
    monkeypatch.setattr(probe_worker, "_validate_approval", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        probe_worker,
        "_validate_request_policies",
        lambda *args, **kwargs: {
            "joint_limit_policy": {},
            "stop_policy": {},
            "max_joint_speed_radps": 1.0,
        },
    )
    monkeypatch.setattr(probe_worker, "_load_json_artifact", lambda *args: {})
    monkeypatch.setattr(probe_worker, "_label_probe_actors", lambda task: None)
    monkeypatch.setattr(
        probe_worker,
        "_snapshot",
        lambda task, request, candidate: {
            "scene_revision": request["scene_revision"],
            "state_digest": "d" * 64,
        },
    )

    def reject_candidate(*args, **kwargs):
        raise SimulationProbeError("planned rejection")

    monkeypatch.setattr(probe_worker, "_run_candidate", reject_candidate)
    request = _route_request(tmp_path)
    geometry = _artifact_record(
        tmp_path,
        request["candidates"][0]["attached_object"]["geometry_ref"],
        b"geometry\n",
    )
    request["candidates"][0]["attached_object"]["geometry_sha256"] = geometry["sha256"]
    profile = _profile()
    profile.update(
        worker_id="probe-test/v1",
        runtime_root=str(tmp_path),
        runtime_profile=str(tmp_path / "runtime.yaml"),
    )
    backend, handle = _handle_factory(
        profile,
        tmp_path,
        producer_id="producer-test/v1",
        producer_profile_sha256="a" * 64,
        approval_ref="artifact://probe/approval.json",
        max_duration_s=1,
        stop_file=tmp_path / "control" / "stop",
    )
    (tmp_path / "control").mkdir()
    message = {
        "request_id": request["request_id"],
        "route_request": request,
        "candidate_ref": request["candidates"][0]["candidate_ref"],
        "calibration_ref": request["calibration_ref"],
    }
    first = handle(message)
    assert first["status"] == "unavailable"
    assert first["world_change_started"] is True
    assert backend.reset_count == 2
    second = handle(message)
    assert second["motion_authorized"] is False
    assert second["error_detail"] == "simulation probe worker is single-use"
    assert backend.reset_count == 2


def test_profile_loader_and_builder_bind_every_worker_argument(tmp_path: Path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    runtime_profile = runtime_root / "profile.yaml"
    runtime_profile.write_text("task_name: blocks_ranking_rgb\n", encoding="utf-8")
    stop_file = artifact_root / "control" / "stop"
    stop_file.parent.mkdir()
    profile_path = tmp_path / "simulation-probe.yaml"
    script = Path(__file__).parents[1] / "runtime" / "robotwin_simulation_probe_worker.py"
    profile = {
        "schema_version": SIMULATION_PROBE_PROFILE_SCHEMA_VERSION,
        "worker_id": "probe-test/v1",
        "producer_id": "producer-test/v1",
        "producer_profile_sha256": "${PROBE_PROFILE_SHA256}",
        "runtime_root": str(runtime_root),
        "runtime_profile": str(runtime_profile),
        "artifact_root": str(artifact_root),
        "approval_ref": "artifact://probe/approval.json",
        "max_duration_s": 12,
        "stop_file": str(stop_file),
        "worker": {
            "python": "/usr/bin/python3",
            "script": str(script),
            "cwd": str(script.parent),
            "startup_timeout_s": 2,
            "request_timeout_s": 2,
            "shutdown_timeout_s": 2,
            "environment": {"PYTHONUNBUFFERED": "1"},
            "arguments": [
                "--runtime-root", str(runtime_root), "--runtime-profile", str(runtime_profile),
                "--artifact-root", str(artifact_root), "--worker-id", "probe-test/v1",
                "--producer-id", "producer-test/v1", "--producer-profile-sha256", "${PROBE_PROFILE_SHA256}",
                "--approval-ref", "artifact://probe/approval.json", "--max-duration-s", "12",
                "--stop-file", str(stop_file),
            ],
        },
    }
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    monkeypatch.setenv("PROBE_PROFILE_SHA256", hashlib.sha256(profile_path.read_bytes()).hexdigest())
    loaded = load_simulation_probe_profile(profile_path)
    client = build_simulation_probe_client(loaded)
    assert isinstance(client, SimulationProbeClient)
    client.release()


def test_profile_builder_rejects_incomplete_profile(tmp_path: Path):
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(SimulationProbeProfileError, match="fields are invalid"):
        build_simulation_probe_client(load_simulation_probe_profile(profile_path))


def test_profile_loader_rejects_duplicate_yaml_keys(tmp_path: Path):
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        "schema_version: paos-robotwin20-simulation-probe-profile/v1\n"
        "schema_version: duplicate\n",
        encoding="utf-8",
    )
    with pytest.raises(SimulationProbeProfileError, match="duplicate"):
        load_simulation_probe_profile(profile_path)


class _ResponseClient:
    def __init__(self, response: dict[str, object]):
        self.response = response

    def request(self, payload):
        return self.response

    def release(self):
        return None


def _client_response(request: dict[str, object], *, started: bool = False) -> dict[str, object]:
    return {
        "request_id": request["request_id"],
        "schema_version": "paos-robotwin20-simulation-probe/v1",
        "status": "unavailable",
        "provider_available": True,
        "worker_id": "probe-test/v1",
        "producer_binding": {
            "producer_id": "producer-test/v1",
            "profile_sha256": "a" * 64,
            "evidence_mode": "independent_simulation_probe",
        },
        "motion_authorized": True,
        "world_change_started": started,
        "world_change_completed": False,
        # A completed simulator reset clears reconciliation even after a
        # world-changing attempt; the worker reports that state explicitly.
        "reconciliation_required": False,
        "failure_evidence": {"artifact_ref": "artifact://probe/failure", "sha256": "b" * 64} if started else None,
    }


def test_client_accepts_bounded_unavailable_stop_before_world_change(tmp_path: Path):
    request = _route_request(tmp_path)
    client = SimulationProbeClient(
        _ResponseClient(_client_response(request)),
        worker_id="probe-test/v1",
        producer_binding={
            "producer_id": "producer-test/v1",
            "profile_sha256": "a" * 64,
            "evidence_mode": "independent_simulation_probe",
        },
    )
    response = client.probe(request, candidate_ref=request["candidates"][0]["candidate_ref"])
    assert response["status"] == "unavailable"
    assert response["world_change_started"] is False


def test_client_accepts_unauthorized_preflight_failure(tmp_path: Path):
    request = _route_request(tmp_path)
    response = _client_response(request)
    response["motion_authorized"] = False
    client = SimulationProbeClient(
        _ResponseClient(response),
        worker_id="probe-test/v1",
        producer_binding={
            "producer_id": "producer-test/v1",
            "profile_sha256": "a" * 64,
            "evidence_mode": "independent_simulation_probe",
        },
    )
    assert client.probe(
        request, candidate_ref=request["candidates"][0]["candidate_ref"]
    )["status"] == "unavailable"


def test_client_rejects_non_boolean_failure_reconciliation(tmp_path: Path):
    request = _route_request(tmp_path)
    response = _client_response(request, started=True)
    response["reconciliation_required"] = "false"
    client = SimulationProbeClient(
        _ResponseClient(response),
        worker_id="probe-test/v1",
        producer_binding={
            "producer_id": "producer-test/v1",
            "profile_sha256": "a" * 64,
            "evidence_mode": "independent_simulation_probe",
        },
    )
    with pytest.raises(SimulationProbeProfileError, match="reconciliation"):
        client.probe(request, candidate_ref=request["candidates"][0]["candidate_ref"])


def test_client_rejects_reconciliation_without_world_change(tmp_path: Path):
    request = _route_request(tmp_path)
    response = _client_response(request, started=False)
    response["reconciliation_required"] = True
    client = SimulationProbeClient(
        _ResponseClient(response),
        worker_id="probe-test/v1",
        producer_binding={
            "producer_id": "producer-test/v1",
            "profile_sha256": "a" * 64,
            "evidence_mode": "independent_simulation_probe",
        },
    )
    with pytest.raises(SimulationProbeProfileError, match="reconciliation"):
        client.probe(request, candidate_ref=request["candidates"][0]["candidate_ref"])
