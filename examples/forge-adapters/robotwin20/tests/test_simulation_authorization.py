from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
import yaml

from robotwin20_adapter import (
    SIMULATION_AUTHORIZATION_PROFILE_SCHEMA_VERSION,
    SIMULATION_EVIDENCE_MANIFEST_SCHEMA_VERSION,
    SimulationAuthorizationError,
    load_simulation_motion_profile,
)
from robotwin20_adapter.simulation_authorization import _profile_identity_digest

WORKER = Path(__file__).parents[1] / "runtime" / "readiness_replay_worker.py"
BINDING = {
    "robot_identity": "franka-panda",
    "gripper_identity": "panda-gripper",
    "embodiment_topology": "two-single-arm",
    "planner_profile": "curobo",
    "profile_digest": "a" * 64,
}
SCOPES = [
    "attached_object_collision",
    "complete_transport_descent_retreat",
    "contact_dynamics",
    "stop_control",
    "workspace_and_joint_limits",
]


def _base(tmp_path: Path, *, state: str = "disabled") -> dict:
    runtime = tmp_path / "runtime.yaml"
    runtime.write_text("runtime: franka\n", encoding="utf-8")
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    return {
        "schema_version": SIMULATION_AUTHORIZATION_PROFILE_SCHEMA_VERSION,
        "profile_id": "sim-profile-v1",
        "runtime": {
            "profile": str(runtime),
            "profile_sha256": hashlib.sha256(runtime.read_bytes()).hexdigest(),
        },
        "scope": {
            "task_name": "blocks_ranking_rgb",
            "seed": 0,
            "scene_revision": "blocks_ranking_rgb-0-1",
            "embodiment_binding": BINDING,
        },
        "authorization": {
            "state": state,
            "motion_authorized": state == "approved",
            "approval_record": None,
            "approval_record_sha256": None,
            "evidence_manifest": None,
            "evidence_manifest_sha256": None,
            "required_evidence_scopes": SCOPES,
        },
        "execution": {
            "worker": None,
            "max_duration_s": 300,
        },
        "stop": {
            "cancel_timeout_s": 5,
            "hard_stop_timeout_s": 15,
            "unknown_policy": "halt_and_reconcile",
        },
        "snapshot": {
            "artifact_root": str(artifact_root),
            "before_required": True,
            "after_required": True,
            "task_verifier_handoff_required": True,
        },
    }


def _write(path: Path, value: dict) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def test_disabled_profile_loads_without_worker_or_motion(tmp_path: Path):
    path = tmp_path / "profile.yaml"
    _write(path, _base(tmp_path))
    profile = load_simulation_motion_profile(path)
    assert profile.authorization_state == "disabled"
    assert profile.motion_authorized is False
    assert profile.worker_config is None
    assert profile.before_snapshot_required and profile.after_snapshot_required


def test_profile_rejects_duplicate_yaml_keys(tmp_path: Path):
    path = tmp_path / "profile.yaml"
    path.write_text("schema_version: paos-robotwin20-simulation-motion/v2\nschema_version: duplicate\n", encoding="utf-8")
    with pytest.raises(SimulationAuthorizationError, match="duplicate"):
        load_simulation_motion_profile(path)


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda p: p.update(extra=True), "fields are invalid"),
        (lambda p: p["authorization"].update(motion_authorized=True), "disagree"),
        (lambda p: p["authorization"].update(required_evidence_scopes=SCOPES[:2]), "scopes"),
        (lambda p: p["snapshot"].update(after_required=False), "mandatory"),
        (lambda p: p["stop"].update(hard_stop_timeout_s=1), "hard_stop"),
    ],
)
def test_profile_rejects_unsafe_or_incomplete_configuration(tmp_path: Path, mutate, message: str):
    value = _base(tmp_path)
    mutate(value)
    path = tmp_path / "profile.yaml"
    _write(path, value)
    with pytest.raises(SimulationAuthorizationError, match=message):
        load_simulation_motion_profile(path)


def test_profile_expands_environment_and_checks_runtime_digest(tmp_path: Path, monkeypatch):
    value = _base(tmp_path)
    runtime = Path(value["runtime"]["profile"])
    artifact_root = Path(value["snapshot"]["artifact_root"])
    value["runtime"]["profile"] = "${SIM_RUNTIME}"
    value["snapshot"]["artifact_root"] = "${SIM_ARTIFACTS}"
    path = tmp_path / "profile.yaml"
    _write(path, value)
    monkeypatch.setenv("SIM_RUNTIME", str(runtime))
    monkeypatch.setenv("SIM_ARTIFACTS", str(artifact_root))
    profile = load_simulation_motion_profile(path)
    assert profile.runtime_profile == runtime.resolve()
    assert profile.snapshot_artifact_root == artifact_root.resolve()


def test_approved_profile_requires_bound_approval_and_worker(tmp_path: Path):
    value = _base(tmp_path, state="approved")
    value["execution"]["worker"] = {
        "python": sys.executable,
        "script": str(WORKER),
        "arguments": [],
        "cwd": str(WORKER.parent),
        "environment": {"PYTHONUNBUFFERED": "1"},
        "startup_timeout_s": 2,
        "request_timeout_s": 2,
        "shutdown_timeout_s": 2,
    }
    approval = tmp_path / "approval.json"
    evidence_manifest = tmp_path / "evidence-manifest.json"
    evidence_manifest_value = {
        "schema_version": SIMULATION_EVIDENCE_MANIFEST_SCHEMA_VERSION,
        "profile_id": value["profile_id"],
        "task_name": value["scope"]["task_name"],
        "scene_revision": value["scope"]["scene_revision"],
        "embodiment_binding": BINDING,
        "motion_authorized": False,
        "scope_status": {scope: "pass" for scope in SCOPES},
        "artifacts": [
            {"artifact_ref": f"artifact://simulation/{scope}", "sha256": "b" * 64, "scope": scope}
            for scope in SCOPES
        ],
    }
    evidence_manifest.write_text(json.dumps(evidence_manifest_value, sort_keys=True), encoding="utf-8")
    evidence_manifest.chmod(0o600)
    value["authorization"]["evidence_manifest"] = str(evidence_manifest)
    value["authorization"]["evidence_manifest_sha256"] = hashlib.sha256(evidence_manifest.read_bytes()).hexdigest()
    value["authorization"]["approval_record"] = str(approval)
    value["authorization"]["approval_record_sha256"] = "0" * 64
    profile_path = tmp_path / "profile.yaml"
    _write(profile_path, value)
    profile_digest = _profile_identity_digest(value)
    approval_value = {
        "schema_version": "paos-robotwin20-simulation-motion-approval/v2",
        "decision": "approved_simulation_motion",
        "motion_authorized": True,
        "profile_id": value["profile_id"],
        "profile_sha256": profile_digest,
        "task_name": value["scope"]["task_name"],
        "scene_revision": value["scope"]["scene_revision"],
        "embodiment_binding": BINDING,
        "evidence_scopes": SCOPES,
        "evidence_manifest_sha256": value["authorization"]["evidence_manifest_sha256"],
        "reviewer_id": "reviewer-1",
        "reviewed_at": "2026-09-05T02:00:00+00:00",
    }
    approval.write_text(json.dumps(approval_value, sort_keys=True), encoding="utf-8")
    approval.chmod(0o600)
    approval_digest = hashlib.sha256(approval.read_bytes()).hexdigest()
    value["authorization"]["approval_record_sha256"] = approval_digest
    _write(profile_path, value)
    profile = load_simulation_motion_profile(profile_path)
    assert profile.authorization_state == "approved"
    assert profile.motion_authorized is True
    assert profile.worker_config is not None


def test_approved_profile_rejects_tampered_approval(tmp_path: Path):
    value = _base(tmp_path, state="approved")
    value["execution"]["worker"] = {
        "python": sys.executable,
        "script": str(WORKER),
        "arguments": [],
        "cwd": str(WORKER.parent),
        "environment": {},
        "startup_timeout_s": 2,
        "request_timeout_s": 2,
        "shutdown_timeout_s": 2,
    }
    approval = tmp_path / "approval.json"
    approval.write_text("{}", encoding="utf-8")
    approval.chmod(0o600)
    evidence_manifest = tmp_path / "evidence-manifest.json"
    evidence_manifest.write_text(
        json.dumps(
            {
                "schema_version": SIMULATION_EVIDENCE_MANIFEST_SCHEMA_VERSION,
                "profile_id": value["profile_id"],
                "task_name": value["scope"]["task_name"],
                "scene_revision": value["scope"]["scene_revision"],
                "embodiment_binding": BINDING,
                "motion_authorized": False,
                "scope_status": {scope: "pass" for scope in SCOPES},
                "artifacts": [
                    {"artifact_ref": f"artifact://simulation/{scope}", "sha256": "b" * 64, "scope": scope}
                    for scope in SCOPES
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    evidence_manifest.chmod(0o600)
    value["authorization"]["evidence_manifest"] = str(evidence_manifest)
    value["authorization"]["evidence_manifest_sha256"] = hashlib.sha256(evidence_manifest.read_bytes()).hexdigest()
    value["authorization"].update({"approval_record": str(approval), "approval_record_sha256": "1" * 64})
    profile_path = tmp_path / "profile.yaml"
    _write(profile_path, value)
    with pytest.raises(SimulationAuthorizationError, match="digest"):
        load_simulation_motion_profile(profile_path)
