"""Independent verifier for externally produced simulation-route evidence.

The verifier is deliberately not a planner or an executor.  It consumes
immutable artifacts produced by an external planner/simulation probe and
projects them into the provider-neutral route-readiness contract.  Missing,
stale, divergent, or partially bound evidence is rejected; a successful
verification still never grants motion authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

from .perception_profile import PerceptionProfileError, _absolute_path, _expand, _worker_config
from .process_worker import JsonlProcessWorkerClient
from .route_readiness import (
    ROUTE_CHECKS,
    project_route_evidence,
    route_geometry_digest,
    validate_route_request,
)

ROUTE_EVIDENCE_SCHEMA_VERSION = "paos-robotwin20-simulation-route-evidence/v1"
ROUTE_EVIDENCE_PROFILE_SCHEMA_VERSION = "paos-robotwin20-route-evidence/v1"


class RouteEvidenceError(ValueError):
    """External route evidence is malformed, unavailable, or unbound."""


def _artifact_path(root: Path, ref: Any) -> Path:
    if not isinstance(ref, str) or not ref.startswith("artifact://"):
        raise RouteEvidenceError("route evidence artifact_ref is invalid")
    parts = ref.removeprefix("artifact://").split("/")
    if len(parts) < 2 or any(not part or part in {".", ".."} for part in parts):
        raise RouteEvidenceError("route evidence artifact_ref is invalid")
    candidate = root.joinpath(*parts)
    if not candidate.suffix:
        candidate = candidate.with_suffix(".json")
    if candidate.is_symlink():
        raise RouteEvidenceError("route evidence artifact path is unsafe")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise RouteEvidenceError("route evidence artifact is unavailable") from exc
    root_resolved = root.resolve()
    if resolved.is_symlink() or not resolved.is_file() or root_resolved not in resolved.parents:
        raise RouteEvidenceError("route evidence artifact path is unsafe")
    return resolved


def _digest(path: Path, expected: Any) -> None:
    if not isinstance(expected, str) or len(expected) != 64 or any(
        char not in "0123456789abcdef" for char in expected
    ):
        raise RouteEvidenceError("route evidence artifact sha256 is invalid")
    try:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise RouteEvidenceError("route evidence artifact cannot be read") from exc
    if actual != expected:
        raise RouteEvidenceError("route evidence artifact digest mismatch")


def _artifact(root: Path, ref: Any, digest: Any) -> None:
    path = _artifact_path(root, ref)
    _digest(path, digest)


def _identity(request: Mapping[str, Any], item: Mapping[str, Any]) -> None:
    fields = (
        "request_id",
        "observation_ref",
        "scene_revision",
        "frame_id",
        "calibration_ref",
        "candidate_set_ref",
    )
    if any(item.get(field) != request[field] for field in fields):
        raise RouteEvidenceError("route evidence identity binding is invalid")


def _require_artifact_record(root: Path, value: Any, label: str) -> str:
    if not isinstance(value, Mapping) or set(value) != {"artifact_ref", "sha256"}:
        raise RouteEvidenceError(f"{label} artifact record is invalid")
    _artifact(root, value["artifact_ref"], value["sha256"])
    return str(value["artifact_ref"])


def _snapshot(
    root: Path,
    value: Any,
    request: Mapping[str, Any],
    candidate: Mapping[str, Any],
    label: str,
) -> tuple[str, str, Mapping[str, Any]]:
    ref = _require_artifact_record(root, value, label)
    path = _artifact_path(root, ref)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RouteEvidenceError(f"{label} snapshot is not valid JSON") from exc
    if not isinstance(payload, Mapping) or set(payload) != {
        "scene_revision", "observation_ref", "frame_id", "candidate_set_ref", "captured_at",
        "state_digest", "target_entity_ref", "target_actor", "target_pose", "robot_grippers",
    }:
        raise RouteEvidenceError(f"{label} snapshot fields are invalid")
    if any(payload[key] != request[key] for key in ("scene_revision", "observation_ref", "frame_id", "candidate_set_ref")):
        raise RouteEvidenceError(f"{label} snapshot identity is invalid")
    if not isinstance(payload["captured_at"], str) or not payload["captured_at"].strip():
        raise RouteEvidenceError(f"{label} snapshot timestamp is invalid")
    if payload["target_entity_ref"] != candidate["entity_ref"]:
        raise RouteEvidenceError(f"{label} snapshot target identity is invalid")
    if not isinstance(payload["target_actor"], str) or not payload["target_actor"].strip():
        raise RouteEvidenceError(f"{label} snapshot target actor is invalid")
    target_pose = payload["target_pose"]
    if not isinstance(target_pose, Mapping) or set(target_pose) != {"position_m", "orientation_wxyz"}:
        raise RouteEvidenceError(f"{label} snapshot target pose is invalid")
    for key, length in (("position_m", 3), ("orientation_wxyz", 4)):
        vector = target_pose[key]
        if (
            not isinstance(vector, list)
            or len(vector) != length
            or any(
                isinstance(item, bool)
                or not isinstance(item, (int, float))
                or not math.isfinite(float(item))
                for item in vector
            )
        ):
            raise RouteEvidenceError(f"{label} snapshot target pose is invalid")
    grippers = payload["robot_grippers"]
    if (
        not isinstance(grippers, Mapping)
        or set(grippers) != {"left", "right"}
        or any(
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not math.isfinite(float(item))
            for item in grippers.values()
        )
    ):
        raise RouteEvidenceError(f"{label} snapshot gripper state is invalid")
    state_digest = payload["state_digest"]
    if not isinstance(state_digest, str) or len(state_digest) != 64 or any(
        char not in "0123456789abcdef" for char in state_digest
    ):
        raise RouteEvidenceError(f"{label} snapshot state_digest is invalid")
    return ref, state_digest, payload


def _verify_external_evidence(
    request: Mapping[str, Any],
    external: Mapping[str, Any],
    artifact_root: Path,
    trusted_producer: Mapping[str, str],
) -> dict[str, Any]:
    validate_route_request(request)
    if not isinstance(external, Mapping) or set(external) != {
        "schema_version",
        "request_id",
        "candidate_ref",
        "entity_ref",
        "observation_ref",
        "scene_revision",
        "frame_id",
        "calibration_ref",
        "candidate_set_ref",
        "route_geometry_digest",
        "planner",
        "scopes",
        "before_snapshot",
        "after_snapshot",
        "semantic_verdict",
        "producer_binding",
        "probe_execution",
    }:
        raise RouteEvidenceError("route evidence fields are invalid")
    if external["schema_version"] != ROUTE_EVIDENCE_SCHEMA_VERSION:
        raise RouteEvidenceError("route evidence schema_version is unsupported")
    if external["producer_binding"] != dict(trusted_producer):
        raise RouteEvidenceError("route evidence producer binding is untrusted")
    _identity(request, external)
    candidates = {item["candidate_ref"]: item["entity_ref"] for item in request["candidates"]}
    candidate_ref = external["candidate_ref"]
    if candidate_ref not in candidates or external["entity_ref"] != candidates[candidate_ref]:
        raise RouteEvidenceError("route evidence candidate binding is invalid")
    selected_candidate = next(item for item in request["candidates"] if item["candidate_ref"] == candidate_ref)
    attached = selected_candidate["attached_object"]
    _artifact(artifact_root, attached["geometry_ref"], attached["geometry_sha256"])
    if external["route_geometry_digest"] != route_geometry_digest(request):
        raise RouteEvidenceError("route evidence route geometry digest mismatch")
    probe = external["probe_execution"]
    if not isinstance(probe, Mapping) or set(probe) != {
        "simulation_only", "motion_authorized", "world_change_started", "world_change_completed", "authorization"
    }:
        raise RouteEvidenceError("route evidence probe execution is invalid")
    if (
        probe["simulation_only"] is not True
        or probe["motion_authorized"] is not True
        or probe["world_change_started"] is not True
        or probe["world_change_completed"] is not True
    ):
        raise RouteEvidenceError("route evidence probe execution is incomplete or unauthorized")
    authorization_ref = _require_artifact_record(artifact_root, probe["authorization"], "probe.authorization")

    planner = external["planner"]
    if not isinstance(planner, Mapping) or set(planner) != {
        "status", "planner_id", "trajectory", "joint_limits", "route_phase_order"
    }:
        raise RouteEvidenceError("route evidence planner record is invalid")
    if planner["status"] != "pass" or not isinstance(planner["planner_id"], str) or not planner["planner_id"].strip():
        raise RouteEvidenceError("route evidence planner status is not pass")
    _require_artifact_record(artifact_root, planner["trajectory"], "planner.trajectory")
    _require_artifact_record(artifact_root, planner["joint_limits"], "planner.joint_limits")
    if planner["route_phase_order"] != [item["phase"] for item in selected_candidate["route"]]:
        raise RouteEvidenceError("route evidence planner route phase order is invalid")

    scopes = external["scopes"]
    if not isinstance(scopes, Mapping) or set(scopes) != set(ROUTE_CHECKS):
        raise RouteEvidenceError("route evidence scopes are incomplete")
    for scope in ROUTE_CHECKS:
        record = scopes[scope]
        if not isinstance(record, Mapping) or set(record) != {"status", "evidence", "method"}:
            raise RouteEvidenceError(f"route evidence scope is invalid: {scope}")
        if record["status"] != "pass" or not isinstance(record["method"], str) or not record["method"].strip():
            raise RouteEvidenceError(f"route evidence scope is not pass: {scope}")
        _require_artifact_record(artifact_root, record["evidence"], f"scope.{scope}")

    before = external["before_snapshot"]
    after = external["after_snapshot"]
    before_ref, before_state_digest, before_payload = _snapshot(
        artifact_root, before, request, selected_candidate, "before_snapshot"
    )
    after_ref, after_state_digest, after_payload = _snapshot(
        artifact_root, after, request, selected_candidate, "after_snapshot"
    )
    if before_ref == after_ref or before_state_digest == after_state_digest:
        raise RouteEvidenceError("before/after snapshots do not show a state transition")
    semantic = external["semantic_verdict"]
    if not isinstance(semantic, Mapping) or set(semantic) != {
        "status", "verifier_id", "criteria_scope", "criteria", "after_snapshot_ref",
        "target_displacement_m", "selected_arm", "selected_gripper_value",
    }:
        raise RouteEvidenceError("route evidence semantic verdict is invalid")
    if semantic["status"] != "pass" or not isinstance(semantic["verifier_id"], str) or not semantic["verifier_id"].strip():
        raise RouteEvidenceError("route evidence semantic verdict is not pass")
    if not isinstance(semantic["criteria"], list) or not semantic["criteria"] or any(
        not isinstance(item, str) or not item.strip() for item in semantic["criteria"]
    ):
        raise RouteEvidenceError("route evidence semantic criteria are invalid")
    if semantic["after_snapshot_ref"] != after_ref:
        raise RouteEvidenceError("route evidence semantic snapshot binding is invalid")
    if semantic["criteria_scope"] != "single_object_route_only":
        raise RouteEvidenceError("route evidence semantic criteria scope is invalid")
    expected_criteria = {
        "single_object_target_actor_state_changed",
        "selected_gripper_released",
    }
    if set(semantic["criteria"]) != expected_criteria:
        raise RouteEvidenceError("route evidence semantic criteria are invalid")
    selected_arm = semantic["selected_arm"]
    if selected_arm not in {"left", "right"}:
        raise RouteEvidenceError("route evidence semantic selected arm is invalid")
    before_position = before_payload["target_pose"]["position_m"]
    after_position = after_payload["target_pose"]["position_m"]
    displacement = math.sqrt(
        sum((float(after_value) - float(before_value)) ** 2 for before_value, after_value in zip(before_position, after_position))
    )
    if (
        isinstance(semantic["target_displacement_m"], bool)
        or not isinstance(semantic["target_displacement_m"], (int, float))
        or not math.isclose(float(semantic["target_displacement_m"]), displacement, rel_tol=1e-6, abs_tol=1e-8)
        or displacement < 1e-4
    ):
        raise RouteEvidenceError("route evidence semantic target displacement is invalid")
    selected_gripper = float(after_payload["robot_grippers"][selected_arm])
    if (
        isinstance(semantic["selected_gripper_value"], bool)
        or not isinstance(semantic["selected_gripper_value"], (int, float))
        or not math.isclose(float(semantic["selected_gripper_value"]), selected_gripper, abs_tol=1e-6)
        or selected_gripper < 0.8
    ):
        raise RouteEvidenceError("route evidence semantic gripper release is invalid")

    evidence_ref = f"artifact://route-evidence/{candidate_ref.removeprefix('candidate://').replace('/', '-')}.json"
    # The caller writes the canonical projection; return only the verified refs.
    return project_route_evidence(
        request,
        next(item for item in request["candidates"] if item["candidate_ref"] == candidate_ref),
        capability_status={scope: "pass" for scope in ROUTE_CHECKS},
        evidence_ref=evidence_ref,
    ) | {
        "evidence": [
            attached["geometry_ref"],
            authorization_ref,
            planner["trajectory"]["artifact_ref"],
            planner["joint_limits"]["artifact_ref"],
            *(scopes[scope]["evidence"]["artifact_ref"] for scope in ROUTE_CHECKS),
            before_ref,
            after_ref,
        ],
        "semantic_verifier_id": semantic["verifier_id"],
        "semantic_criteria": list(semantic["criteria"]),
        "source_probe_world_changed": True,
        "source_probe_authorization_ref": authorization_ref,
        "source_producer_binding": dict(trusted_producer),
    }


class RouteEvidenceClient:
    """Profile-owned client for an independent evidence verifier worker."""

    def __init__(
        self,
        client: JsonlProcessWorkerClient,
        *,
        worker_id: str,
        artifact_root: Path,
        trusted_producer: Mapping[str, str],
    ) -> None:
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise RouteEvidenceError("route evidence worker_id must be non-empty")
        self.client = client
        self.worker_id = worker_id
        self.artifact_root = artifact_root
        self.trusted_producer = dict(trusted_producer)

    def verify(self, request: Mapping[str, Any], external_evidence: Mapping[str, Any]) -> Mapping[str, Any]:
        validate_route_request(request)
        response = self.client.request({
            "request_id": request["request_id"],
            "route_request": dict(request),
            "external_evidence": dict(external_evidence),
        })
        if response.get("request_id") != request["request_id"]:
            raise RouteEvidenceError("route evidence response identity mismatch")
        if response.get("schema_version") != ROUTE_EVIDENCE_SCHEMA_VERSION:
            raise RouteEvidenceError("route evidence response schema mismatch")
        if response.get("worker_id") != self.worker_id:
            raise RouteEvidenceError("route evidence worker identity mismatch")
        if response.get("status") != "available" or response.get("provider_available") is not True:
            raise RouteEvidenceError("route evidence verifier is unavailable")
        if response.get("motion_authorized") is not False or response.get("world_change_started") is not False:
            raise RouteEvidenceError("route evidence response must remain no-motion")
        evidence = response.get("route_evidence")
        if (
            not isinstance(evidence, Mapping)
            or evidence.get("request_id") != request["request_id"]
            or evidence.get("candidate_set_ref") != request["candidate_set_ref"]
            or evidence.get("route_geometry_digest") != route_geometry_digest(request)
            or evidence.get("motion_authorized") is not False
            or evidence.get("world_change_started") is not False
            or set(evidence.get("checks", {})) != set(ROUTE_CHECKS)
            or any(evidence["checks"].get(scope) != "pass" for scope in ROUTE_CHECKS)
        ):
            raise RouteEvidenceError("route evidence response is not no-motion")
        return dict(response)

    def release(self) -> None:
        self.client.release()


def build_route_evidence_client(
    profile: Mapping[str, Any], *, environ: Mapping[str, str] | None = None
) -> RouteEvidenceClient:
    required = {"schema_version", "worker_id", "artifact_root", "trusted_producer", "worker"}
    if not isinstance(profile, Mapping) or set(profile) != required:
        raise RouteEvidenceError("route evidence profile fields are invalid")
    if profile["schema_version"] != ROUTE_EVIDENCE_PROFILE_SCHEMA_VERSION:
        raise RouteEvidenceError("route evidence profile schema_version is unsupported")
    variables = dict(os.environ if environ is None else environ)
    worker_id = profile["worker_id"]
    if not isinstance(worker_id, str) or not worker_id.strip():
        raise RouteEvidenceError("route evidence worker_id is invalid")
    trusted = profile["trusted_producer"]
    if not isinstance(trusted, Mapping) or set(trusted) != {"producer_id", "profile_sha256", "evidence_mode"}:
        raise RouteEvidenceError("route evidence trusted_producer fields are invalid")
    try:
        trusted = {
            "producer_id": _expand(trusted["producer_id"], variables),
            "profile_sha256": _expand(trusted["profile_sha256"], variables),
            "evidence_mode": trusted["evidence_mode"],
        }
    except (KeyError, TypeError, PerceptionProfileError) as exc:
        raise RouteEvidenceError("route evidence trusted_producer is invalid") from exc
    if (
        not trusted["producer_id"].strip()
        or len(trusted["profile_sha256"]) != 64
        or any(char not in "0123456789abcdef" for char in trusted["profile_sha256"])
        or trusted["evidence_mode"] != "independent_simulation_probe"
    ):
        raise RouteEvidenceError("route evidence trusted_producer is invalid")
    try:
        artifact_root = _absolute_path(profile["artifact_root"], variables, "route evidence artifact_root", must_be_directory=True)
        worker_config = _worker_config(profile["worker"], variables, "route evidence worker")
    except PerceptionProfileError as exc:
        raise RouteEvidenceError(str(exc)) from exc
    args = worker_config.command
    if "--artifact-root" not in args or str(artifact_root) not in args:
        raise RouteEvidenceError("route evidence worker must bind artifact_root")
    if "--worker-id" not in args or worker_id not in args:
        raise RouteEvidenceError("route evidence worker must bind worker_id")
    for flag, value in (
        ("--trusted-producer-id", trusted["producer_id"]),
        ("--trusted-profile-sha256", trusted["profile_sha256"]),
    ):
        if flag not in args or value not in args:
            raise RouteEvidenceError("route evidence worker must bind trusted producer")
    return RouteEvidenceClient(
        JsonlProcessWorkerClient(worker_config),
        worker_id=worker_id,
        artifact_root=artifact_root,
        trusted_producer=trusted,
    )


def verify_route_evidence(
    request: Mapping[str, Any],
    external_evidence: Mapping[str, Any],
    artifact_root: str | os.PathLike[str],
    *,
    trusted_producer: Mapping[str, str],
) -> dict[str, Any]:
    """Verify one externally produced evidence record without executing motion."""
    root_input = Path(artifact_root).expanduser()
    if not root_input.is_absolute() or root_input.is_symlink() or not root_input.is_dir():
        raise RouteEvidenceError("route evidence artifact_root must be an existing directory")
    root = root_input.resolve()
    return _verify_external_evidence(request, external_evidence, root, trusted_producer)


__all__ = [
    "ROUTE_EVIDENCE_PROFILE_SCHEMA_VERSION",
    "ROUTE_EVIDENCE_SCHEMA_VERSION",
    "RouteEvidenceClient",
    "RouteEvidenceError",
    "build_route_evidence_client",
    "verify_route_evidence",
]
