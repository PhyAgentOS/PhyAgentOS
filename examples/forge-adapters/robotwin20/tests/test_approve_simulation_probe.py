from __future__ import annotations

import hashlib
import importlib.util
import json
from argparse import Namespace
from pathlib import Path

import pytest
from robotwin_simulation_probe_worker import _artifact_record
from test_route_readiness import _request

SCRIPT = Path(__file__).parents[1] / "scripts" / "approve_simulation_probe.py"
SPEC = importlib.util.spec_from_file_location("approve_simulation_probe", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
APPROVAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(APPROVAL)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _setup(tmp_path: Path) -> tuple[Namespace, dict[str, object], Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    request = _request(tmp_path)
    route_path = tmp_path / "route-request.json"
    route_path.write_text(
        json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    runtime_path = tmp_path / "runtime.yaml"
    runtime_path.write_text(
        "task_name: blocks_ranking_rgb\n"
        "robot_identity: franka-panda\n"
        "gripper_identity: panda-gripper\n"
        "embodiment_topology: two-single-arm\n"
        "planner_profile: curobo\n",
        encoding="utf-8",
    )
    simulation_profile = tmp_path / "simulation-probe.yaml"
    simulation_profile.write_text("profile: probe-v1\n", encoding="utf-8")
    simulation_worker = tmp_path / "simulation-probe-worker.py"
    simulation_worker.write_text("# immutable worker\n", encoding="utf-8")
    candidate = request["candidates"][0]
    artifact_values = {
        request["calibration_ref"]: b"calibration\n",
        request["joint_limits_ref"]: b"joint-limits\n",
        request["stop_policy_ref"]: b"stop-policy\n",
        candidate["attached_object"]["transform_provenance_ref"]: b"transform\n",
        candidate["placement_target"]["provenance_ref"]: b"placement\n",
        request["controller_qualification"]["artifact_ref"]: b"qualification\n",
        "artifact://blocks/source-manifest": b"manifest\n",
    }
    digests = {
        ref: _artifact_record(tmp_path, ref, payload)["sha256"]
        for ref, payload in artifact_values.items()
    }
    request["controller_qualification"]["sha256"] = digests[
        request["controller_qualification"]["artifact_ref"]
    ]
    route_path.write_text(
        json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    route_digest = APPROVAL.route_geometry_digest(request)
    route_sha = hashlib.sha256(route_path.read_bytes()).hexdigest()
    review = {
        "schema_version": "paos-robotwin20-simulation-probe-review-request/v3",
        "decision": "pending_human_review",
        "motion_authorized": False,
        "request_id": request["request_id"],
        "candidate_ref": candidate["candidate_ref"],
        "entity_ref": candidate["entity_ref"],
        "scene_revision": request["scene_revision"],
        "route_geometry_digest": route_digest,
        "route_request_sha256": route_sha,
        "source_manifest_ref": "artifact://blocks/source-manifest",
        "source_manifest_sha256": digests["artifact://blocks/source-manifest"],
        "producer_profile_sha256": _sha(simulation_profile),
        "runtime_profile_sha256": _sha(runtime_path),
        "object_robot_target_transform_sha256": digests[
            candidate["attached_object"]["transform_provenance_ref"]
        ],
        "placement_target_sha256": digests[candidate["placement_target"]["provenance_ref"]],
        "calibration_sha256": digests[request["calibration_ref"]],
        "joint_limits_sha256": digests[request["joint_limits_ref"]],
        "stop_policy_sha256": digests[request["stop_policy_ref"]],
        "controller_qualification_ref": request["controller_qualification"]["artifact_ref"],
        "controller_qualification_sha256": digests[
            request["controller_qualification"]["artifact_ref"]
        ],
        "simulation_probe_worker_sha256": _sha(simulation_worker),
        "required_decision": "approved_independent_simulation_probe",
        "required_reviewer": "human",
        "simulation_only": True,
    }
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(review, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    args = Namespace(
        artifact_root=tmp_path,
        route_request=route_path,
        review_request=review_path,
        runtime_profile=runtime_path,
        simulation_probe_profile=simulation_profile,
        simulation_probe_worker=simulation_worker,
        reviewer_id="human-reviewer-1",
        confirm_route_digest=route_digest,
        confirm_source_manifest_digest=review["source_manifest_sha256"],
        approve_simulation_only="I_REVIEWED_AND_APPROVE_SIMULATION_ONLY",
    )
    return args, review, route_path


def test_approval_script_writes_digest_bound_record(tmp_path: Path):
    args, review, _ = _setup(tmp_path)
    destination = APPROVAL.approve(args)
    value = json.loads(destination.read_text(encoding="utf-8"))
    assert value["decision"] == "approved_independent_simulation_probe"
    assert value["motion_authorized"] is True
    assert value["route_geometry_digest"] == review["route_geometry_digest"]
    assert destination.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda args, review: setattr(args, "approve_simulation_only", "yes"), "phrase"),
        (lambda args, review: setattr(args, "confirm_route_digest", "0" * 64), "route digest"),
        (lambda args, review: setattr(args, "confirm_source_manifest_digest", "0" * 64), "source manifest digest"),
        (lambda args, review: review.update(required_reviewer="agent"), "approvable"),
    ],
)
def test_approval_script_rejects_unreviewable_inputs(tmp_path: Path, mutate, message: str):
    args, review, _ = _setup(tmp_path)
    mutate(args, review)
    args.review_request.write_text(
        json.dumps(review, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(APPROVAL.ApprovalError, match=message):
        APPROVAL.approve(args)


def test_approval_script_rejects_changed_profile_and_route_input(tmp_path: Path):
    args, _, route_path = _setup(tmp_path)
    args.simulation_probe_profile.write_text("profile: changed\n", encoding="utf-8")
    with pytest.raises(APPROVAL.ApprovalError, match="profile changed"):
        APPROVAL.approve(args)

    args, _, _ = _setup(tmp_path / "runtime-change")
    args.runtime_profile.write_text("task_name: changed\n", encoding="utf-8")
    with pytest.raises(APPROVAL.ApprovalError, match="runtime profile changed|runtime profile task"):
        APPROVAL.approve(args)

    args, _, route_path = _setup(tmp_path / "route-change")
    route = json.loads(route_path.read_text(encoding="utf-8"))
    route["scene_revision"] = "changed-scene"
    route_path.write_text(json.dumps(route) + "\n", encoding="utf-8")
    with pytest.raises(Exception, match="observation identity|route digest"):
        APPROVAL.approve(args)


def test_approval_script_never_overwrites_existing_record(tmp_path: Path):
    args, _, _ = _setup(tmp_path)
    APPROVAL.approve(args)
    with pytest.raises(APPROVAL.ApprovalError, match="already exists"):
        APPROVAL.approve(args)


def test_approval_script_rejects_duplicate_runtime_profile_keys(tmp_path: Path):
    args, review, _ = _setup(tmp_path)
    args.runtime_profile.write_text(
        args.runtime_profile.read_text(encoding="utf-8") + "task_name: overwritten\n",
        encoding="utf-8",
    )
    review["runtime_profile_sha256"] = _sha(args.runtime_profile)
    args.review_request.write_text(
        json.dumps(review, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(APPROVAL.ApprovalError, match="duplicate YAML keys"):
        APPROVAL.approve(args)
