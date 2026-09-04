"""Bounded worker for independent simulation-route evidence verification.

The worker receives a route request plus evidence produced by an external
planner/simulation probe.  It only validates and records a no-motion
projection; it never creates a RoboTwin task, steps a simulator, or starts an
Action/Gateway route.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from worker_protocol import serve

from robotwin20_adapter.route_evidence import (
    ROUTE_EVIDENCE_SCHEMA_VERSION,
    RouteEvidenceError,
    verify_route_evidence,
)


def _canonical_path(root: Path, candidate_ref: str) -> Path:
    token = candidate_ref.removeprefix("candidate://").replace("/", "-")
    if not token or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in token):
        raise RouteEvidenceError("route evidence candidate_ref is invalid")
    path = root / "route-evidence" / f"{token}.json"
    if path.parent.resolve() != root.resolve() / "route-evidence":
        raise RouteEvidenceError("route evidence canonical path is unsafe")
    return path


def _handle_factory(
    artifact_root: Path,
    worker_id: str,
    trusted_producer_id: str,
    trusted_profile_sha256: str,
):
    if not artifact_root.is_absolute() or artifact_root.is_symlink() or not artifact_root.is_dir():
        raise ValueError("artifact root must be an existing absolute directory")
    if not isinstance(worker_id, str) or not worker_id.strip():
        raise ValueError("worker_id must be non-empty")
    if not trusted_producer_id.strip() or len(trusted_profile_sha256) != 64:
        raise ValueError("trusted producer binding is invalid")
    trusted_producer = {
        "producer_id": trusted_producer_id,
        "profile_sha256": trusted_profile_sha256,
        "evidence_mode": "independent_simulation_probe",
    }

    def handle(request: Mapping[str, Any]) -> Mapping[str, Any]:
        if set(request) != {"request_id", "route_request", "external_evidence"}:
            raise RouteEvidenceError("route evidence worker request fields are invalid")
        route_request = request["route_request"]
        external = request["external_evidence"]
        if not isinstance(route_request, Mapping) or not isinstance(external, Mapping):
            raise RouteEvidenceError("route evidence worker payload must contain objects")
        if route_request.get("request_id") != request["request_id"] or external.get("request_id") != request["request_id"]:
            raise RouteEvidenceError("route evidence worker request identity mismatch")
        projection = verify_route_evidence(
            route_request,
            external,
            artifact_root,
            trusted_producer=trusted_producer,
        )
        candidate_ref = projection["candidate_ref"]
        path = _canonical_path(artifact_root, candidate_ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = (json.dumps(projection, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        if path.exists():
            if path.is_symlink() or path.read_bytes() != encoded:
                raise RouteEvidenceError("route evidence canonical artifact is immutable and divergent")
        else:
            with path.open("xb") as stream:
                stream.write(encoded)
            path.chmod(0o600)
        return {
            "request_id": request["request_id"],
            "schema_version": ROUTE_EVIDENCE_SCHEMA_VERSION,
            "status": "available",
            "provider_available": True,
            "worker_id": worker_id,
            "motion_authorized": False,
            "world_change_started": False,
            "route_evidence": projection,
            "verification_mode": "external_evidence_only",
        }

    return handle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--worker-id", required=True)
    parser.add_argument("--trusted-producer-id", required=True)
    parser.add_argument("--trusted-profile-sha256", required=True)
    args = parser.parse_args()
    return serve(
        "robotwin-route-evidence",
        lambda: None,
        _handle_factory(
            args.artifact_root.resolve(),
            args.worker_id,
            args.trusted_producer_id,
            args.trusted_profile_sha256,
        ),
        schema_version=ROUTE_EVIDENCE_SCHEMA_VERSION,
    )


if __name__ == "__main__":
    raise SystemExit(main())
