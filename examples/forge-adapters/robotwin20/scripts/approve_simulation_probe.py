#!/usr/bin/env python3
"""Create one human-confirmed, digest-bound simulation-only probe approval."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

from robotwin20_adapter.route_readiness import route_geometry_digest, validate_route_request

APPROVAL_SCHEMA_VERSION = "paos-robotwin20-simulation-probe-approval/v3"


class ApprovalError(RuntimeError):
    pass


def _load(path: Path, label: str) -> Mapping[str, Any]:
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise ApprovalError(f"{label} must be an absolute regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ApprovalError(f"{label} is invalid JSON") from exc
    if not isinstance(value, Mapping):
        raise ApprovalError(f"{label} must contain an object")
    return value


def _artifact_path(root: Path, ref: str) -> Path:
    if not isinstance(ref, str) or not ref.startswith("artifact://"):
        raise ApprovalError("artifact reference is invalid")
    parts = ref.removeprefix("artifact://").split("/")
    if len(parts) < 2 or any(not part or part in {".", ".."} for part in parts):
        raise ApprovalError("artifact reference is invalid")
    path = root.joinpath(*parts)
    if not path.suffix:
        path = path.with_suffix(".json")
    resolved = path.resolve()
    if root.resolve() not in resolved.parents or not resolved.is_file() or resolved.is_symlink():
        raise ApprovalError("artifact reference is unavailable or unsafe")
    return resolved


def _sha(path: Path) -> str:
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise ApprovalError("digest input must be an absolute regular file")
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ApprovalError("digest input cannot be read") from exc


def approve(args: argparse.Namespace) -> Path:
    root = args.artifact_root
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise ApprovalError("artifact root must be an absolute directory")
    if args.approve_simulation_only != "I_REVIEWED_AND_APPROVE_SIMULATION_ONLY":
        raise ApprovalError("explicit simulation-only approval phrase is required")
    request = _load(args.route_request, "route request")
    validate_route_request(request)
    route_digest = route_geometry_digest(request)
    if args.confirm_route_digest != route_digest:
        raise ApprovalError("confirmed route digest does not match request")
    review = _load(args.review_request, "review request")
    required_review_fields = {
        "schema_version", "decision", "motion_authorized", "request_id",
        "candidate_ref", "entity_ref", "scene_revision", "route_geometry_digest",
        "route_request_sha256", "source_manifest_ref", "source_manifest_sha256",
        "producer_profile_sha256", "runtime_profile_sha256",
        "object_robot_target_transform_sha256",
        "placement_target_sha256", "calibration_sha256", "joint_limits_sha256",
        "stop_policy_sha256", "required_decision", "required_reviewer",
        "simulation_only",
    }
    if (
        set(review) != required_review_fields
        or review.get("schema_version")
        != "paos-robotwin20-simulation-probe-review-request/v2"
        or review.get("decision") != "pending_human_review"
        or review.get("motion_authorized") is not False
        or review.get("simulation_only") is not True
        or review.get("required_decision") != "approved_independent_simulation_probe"
        or review.get("required_reviewer") != "human"
        or review.get("route_geometry_digest") != route_digest
        or review.get("request_id") != request["request_id"]
        or review.get("scene_revision") != request["scene_revision"]
    ):
        raise ApprovalError("review request is not an approvable simulation-only request")
    route_request_sha256 = hashlib.sha256(
        (json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()
    if review["route_request_sha256"] != route_request_sha256:
        raise ApprovalError("review route request digest does not match request")
    if args.confirm_source_manifest_digest != review["source_manifest_sha256"]:
        raise ApprovalError("confirmed source manifest digest does not match review request")
    source_manifest_ref = review["source_manifest_ref"]
    manifest_path = _artifact_path(root, source_manifest_ref)
    if _sha(manifest_path) != review["source_manifest_sha256"]:
        raise ApprovalError("source manifest digest is invalid")
    candidate = next(
        (item for item in request["candidates"] if item["candidate_ref"] == review["candidate_ref"]),
        None,
    )
    if candidate is None:
        raise ApprovalError("review candidate is not in route request")
    if (
        not args.runtime_profile.is_absolute()
        or not args.runtime_profile.is_file()
        or args.runtime_profile.is_symlink()
    ):
        raise ApprovalError("runtime profile must be an absolute regular file")
    class _UniqueKeyLoader(yaml.SafeLoader):
        pass

    def construct_mapping(loader, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in result:
                raise ApprovalError("runtime profile contains duplicate YAML keys")
            result[key] = loader.construct_object(value_node, deep=deep)
        return result

    _UniqueKeyLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping
    )
    try:
        runtime = yaml.load(
            args.runtime_profile.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader
        )
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ApprovalError("runtime profile is invalid") from exc
    if not isinstance(runtime, Mapping) or runtime.get("task_name") != "blocks_ranking_rgb":
        raise ApprovalError("runtime profile task is invalid")
    runtime_profile_digest = _sha(args.runtime_profile)
    if runtime_profile_digest != review["runtime_profile_sha256"]:
        raise ApprovalError("runtime profile changed after review materialization")
    profile_digest = _sha(args.simulation_probe_profile)
    if profile_digest != review["producer_profile_sha256"]:
        raise ApprovalError("simulation probe profile changed after review materialization")
    bindings = {
        "calibration_sha256": _sha(_artifact_path(root, request["calibration_ref"])),
        "joint_limits_sha256": _sha(_artifact_path(root, request["joint_limits_ref"])),
        "stop_policy_sha256": _sha(_artifact_path(root, request["stop_policy_ref"])),
        "object_robot_target_transform_sha256": _sha(
            _artifact_path(root, candidate["attached_object"]["transform_provenance_ref"])
        ),
        "placement_target_sha256": _sha(
            _artifact_path(root, candidate["placement_target"]["provenance_ref"])
        ),
    }
    if any(review.get(field) != digest for field, digest in bindings.items()):
        raise ApprovalError("reviewed route input artifact changed before approval")
    if not isinstance(args.reviewer_id, str) or not args.reviewer_id.strip():
        raise ApprovalError("reviewer_id is required")
    value = {
        "schema_version": APPROVAL_SCHEMA_VERSION,
        "decision": "approved_independent_simulation_probe",
        "motion_authorized": True,
        "producer_id": "robotwin20-independent-probe/v1",
        "producer_profile_sha256": profile_digest,
        "task_name": runtime["task_name"],
        "scene_revision": request["scene_revision"],
        "embodiment_binding": {
            key: runtime[key]
            for key in ("robot_identity", "gripper_identity", "embodiment_topology", "planner_profile")
        },
        "request_id": request["request_id"],
        "candidate_ref": candidate["candidate_ref"],
        "route_geometry_digest": route_digest,
        "reviewer_id": args.reviewer_id.strip(),
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "route_request_sha256": route_request_sha256,
        "source_manifest_ref": source_manifest_ref,
        "source_manifest_sha256": review["source_manifest_sha256"],
        "runtime_profile_sha256": runtime_profile_digest,
        **bindings,
    }
    destination = root / "probe" / "approval.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise ApprovalError("approval record already exists")
    payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    with destination.open("xb") as stream:
        stream.write(payload)
    destination.chmod(0o600)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--route-request", type=Path, required=True)
    parser.add_argument("--review-request", type=Path, required=True)
    parser.add_argument("--runtime-profile", type=Path, required=True)
    parser.add_argument("--simulation-probe-profile", type=Path, required=True)
    parser.add_argument("--reviewer-id", required=True)
    parser.add_argument("--confirm-route-digest", required=True)
    parser.add_argument("--confirm-source-manifest-digest", required=True)
    parser.add_argument("--approve-simulation-only", required=True)
    args = parser.parse_args()
    path = approve(args)
    print(json.dumps({"status": "approved", "approval": str(path), "sha256": _sha(path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
