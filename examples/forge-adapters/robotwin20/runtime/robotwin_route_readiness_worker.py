"""External route-readiness worker seam for RoboTwin simulation.

The worker validates the complete route/evidence contract and records an
explicit unavailable result until a real planner, attached-object collision
checker, contact probe, stop controller, and semantic verifier are injected.
It never calls ``play_once`` or steps the simulator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from worker_protocol import serve

from robotwin20_adapter.route_readiness import (
    ROUTE_CHECKS,
    SIMULATION_ROUTE_READINESS_SCHEMA_VERSION,
    project_route_evidence,
    validate_route_request,
)


def _artifact_path(root: Path, candidate_ref: str) -> tuple[Path, str]:
    token = hashlib.sha256(candidate_ref.encode("utf-8")).hexdigest()
    directory = root / "simulation-route-readiness"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{token}.json", f"artifact://simulation-route-readiness/{token}"


def _handle_factory(artifact_root: Path, worker_id: str):
    if not artifact_root.is_absolute() or artifact_root.is_symlink() or not artifact_root.is_dir():
        raise ValueError("artifact root must be an existing absolute directory")
    if not isinstance(worker_id, str) or not worker_id.strip():
        raise ValueError("worker_id must be non-empty")

    def handle(request: Mapping[str, Any]) -> Mapping[str, Any]:
        validate_route_request(request)
        evidence: list[dict[str, Any]] = []
        unavailable = {
            check: "unavailable"
            for check in ROUTE_CHECKS
        }
        for candidate in request["candidates"]:
            path, ref = _artifact_path(artifact_root, candidate["candidate_ref"])
            item = project_route_evidence(
                request,
                candidate,
                capability_status=unavailable,
                evidence_ref=ref,
            )
            encoded = (json.dumps(item, sort_keys=True) + "\n").encode("utf-8")
            if path.exists():
                if path.is_symlink() or path.read_bytes() != encoded:
                    raise ValueError("route evidence artifact is immutable and divergent")
            else:
                with path.open("xb") as stream:
                    stream.write(encoded)
                path.chmod(0o600)
            evidence.append(item)
        return {
            "request_id": request["request_id"],
            "schema_version": SIMULATION_ROUTE_READINESS_SCHEMA_VERSION,
            "status": "unavailable",
            "worker_id": worker_id,
            "motion_authorized": False,
            "provider_available": False,
            "route_evidence": evidence,
            "unavailable_reasons": [
                "attached_object_collision_worker_not_connected",
                "planner_route_worker_not_connected",
                "contact_dynamics_not_proven_without_stepping",
                "stop_controller_not_connected",
                "semantic_verifier_not_connected",
            ],
        }

    return handle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--worker-id", required=True)
    args = parser.parse_args()
    handle = _handle_factory(args.artifact_root.resolve(), args.worker_id)
    return serve(
        "robotwin-route-readiness",
        lambda: None,
        handle,
        schema_version=SIMULATION_ROUTE_READINESS_SCHEMA_VERSION,
    )


if __name__ == "__main__":
    raise SystemExit(main())
