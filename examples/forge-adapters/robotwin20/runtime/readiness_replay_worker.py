"""No-motion readiness evidence replay worker.

This worker replays an externally materialized, hash-pinned evidence fixture.
It never imports PAOS/RoboTwin/Hephaestus and never invokes a planner or
actuator.  The fixture is a conformance input, not proof of physical readiness.
"""

from __future__ import annotations

import argparse
import json
import stat
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from worker_protocol import serve

SCHEMA_VERSION = "paos-robotwin20-readiness-replay/v1"
EVIDENCE_SCHEMA_VERSION = "paos-robotwin20-readiness-evidence/v1"
_BINDING_KEYS = {
    "robot_identity", "gripper_identity", "embodiment_topology",
    "planner_profile", "profile_digest",
}
_SHA256 = set("0123456789abcdef")


class ReplayFixtureError(ValueError):
    """The replay fixture is malformed or does not match a request."""


def _validate_binding(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != _BINDING_KEYS:
        raise ReplayFixtureError(f"{label} fields are invalid")
    result = dict(value)
    if any(not isinstance(item, str) or not item.strip() for item in result.values()):
        raise ReplayFixtureError(f"{label} values are invalid")
    digest = result["profile_digest"]
    if len(digest) != 64 or any(char not in _SHA256 for char in digest):
        raise ReplayFixtureError(f"{label}.profile_digest is invalid")
    return result


def _load_fixture(path: Path) -> tuple[str, dict[str, str], tuple[dict[str, Any], ...]]:
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise ReplayFixtureError("readiness replay fixture must be an absolute regular file")
    if not stat.S_ISREG(path.stat().st_mode) or path.stat().st_mode & 0o022:
        raise ReplayFixtureError("readiness replay fixture must not be writable")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReplayFixtureError("readiness replay fixture could not be loaded") from exc
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version", "worker_id", "motion_authorized", "embodiment_binding", "cases"
    }:
        raise ReplayFixtureError("readiness replay fixture fields are invalid")
    if value["schema_version"] != SCHEMA_VERSION:
        raise ReplayFixtureError("readiness replay fixture schema_version is unsupported")
    worker_id = value["worker_id"]
    if not isinstance(worker_id, str) or not worker_id.strip():
        raise ReplayFixtureError("readiness replay fixture worker_id is invalid")
    if value["motion_authorized"] is not False:
        raise ReplayFixtureError("readiness replay fixture must be no-motion")
    embodiment_binding = _validate_binding(value["embodiment_binding"], "readiness replay fixture embodiment_binding")
    cases = value["cases"]
    if not isinstance(cases, list) or not cases:
        raise ReplayFixtureError("readiness replay fixture cases must be non-empty")
    normalized: list[dict[str, Any]] = []
    seen_keys: set[tuple[Any, ...]] = set()
    for case in cases:
        if not isinstance(case, Mapping) or set(case) != {
            "observation_ref", "scene_revision", "frame_id", "calibration_ref", "candidate_set_ref",
            "candidate_refs", "prepared_candidates",
        }:
            raise ReplayFixtureError("readiness replay case fields are invalid")
        if (
            case["observation_ref"] != f"observation://{case['scene_revision']}/{case['frame_id']}"
            or case["candidate_set_ref"] != f"candidate-set://{case['scene_revision']}/{case['frame_id']}"
            or not isinstance(case["calibration_ref"], str)
            or not case["calibration_ref"].strip()
        ):
            raise ReplayFixtureError("readiness replay case identity is invalid")
        candidate_refs = case["candidate_refs"]
        if (
            not isinstance(candidate_refs, list)
            or any(
                not isinstance(item, list)
                or len(item) != 2
                or not all(isinstance(value, str) for value in item)
                for item in candidate_refs
            )
        ):
            raise ReplayFixtureError("readiness replay candidate_refs are invalid")
        prepared = case["prepared_candidates"]
        if not isinstance(prepared, list) or any(not isinstance(item, Mapping) for item in prepared):
            raise ReplayFixtureError("readiness replay prepared_candidates are invalid")
        for item in prepared:
            if set(item) != {"candidate_ref", "entity_ref", "checks", "evidence", "qualification"}:
                raise ReplayFixtureError("readiness replay prepared candidate fields are invalid")
            if (
                not isinstance(item["evidence"], list)
                or not item["evidence"]
                or any(not isinstance(ref, str) for ref in item["evidence"])
            ):
                raise ReplayFixtureError("readiness replay prepared candidate evidence is invalid")
        case_value = dict(case)
        case_key = (
            case_value["observation_ref"],
            case_value["scene_revision"],
            case_value["frame_id"],
            case_value["calibration_ref"],
            case_value["candidate_set_ref"],
            tuple(tuple(item) for item in case_value["candidate_refs"]),
        )
        if case_key in seen_keys:
            raise ReplayFixtureError("readiness replay fixture contains duplicate case identity")
        seen_keys.add(case_key)
        normalized.append(case_value)
    return worker_id, embodiment_binding, tuple(normalized)


def _load_evidence_manifest(path: Path) -> tuple[str, dict[str, str], dict[str, dict[str, Any]]]:
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise ReplayFixtureError("readiness evidence manifest must be an absolute regular file")
    if not stat.S_ISREG(path.stat().st_mode) or path.stat().st_mode & 0o022:
        raise ReplayFixtureError("readiness evidence manifest must not be writable")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReplayFixtureError("readiness evidence manifest could not be loaded") from exc
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version", "worker_id", "motion_authorized", "embodiment_binding", "artifacts"
    }:
        raise ReplayFixtureError("readiness evidence manifest fields are invalid")
    if value["schema_version"] != EVIDENCE_SCHEMA_VERSION:
        raise ReplayFixtureError("readiness evidence manifest schema_version is unsupported")
    worker_id = value["worker_id"]
    if not isinstance(worker_id, str) or not worker_id.strip():
        raise ReplayFixtureError("readiness evidence manifest worker_id is invalid")
    if value["motion_authorized"] is not False:
        raise ReplayFixtureError("readiness evidence manifest must be no-motion")
    embodiment_binding = _validate_binding(value["embodiment_binding"], "readiness evidence manifest embodiment_binding")
    artifacts = value["artifacts"]
    if not isinstance(artifacts, list):
        raise ReplayFixtureError("readiness evidence manifest artifacts must be an array")
    indexed: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        if not isinstance(artifact, Mapping) or set(artifact) != {
            "artifact_ref", "observation_ref", "scene_revision", "frame_id",
            "candidate_set_ref", "calibration_ref", "source", "captured_at",
        }:
            raise ReplayFixtureError("readiness evidence manifest artifact fields are invalid")
        artifact_ref = artifact["artifact_ref"]
        if not isinstance(artifact_ref, str) or not artifact_ref.startswith("artifact://"):
            raise ReplayFixtureError("readiness evidence manifest artifact_ref is invalid")
        if artifact_ref in indexed:
            raise ReplayFixtureError("readiness evidence manifest contains duplicate artifact_ref")
        observation_ref = artifact["observation_ref"]
        revision = artifact["scene_revision"]
        frame_id = artifact["frame_id"]
        if (
            not isinstance(observation_ref, str)
            or not isinstance(revision, str)
            or not isinstance(frame_id, str)
            or observation_ref != f"observation://{revision}/{frame_id}"
            or artifact["candidate_set_ref"] != f"candidate-set://{revision}/{frame_id}"
        ):
            raise ReplayFixtureError("readiness evidence manifest observation identity is invalid")
        if not isinstance(artifact["calibration_ref"], str) or not artifact["calibration_ref"].strip():
            raise ReplayFixtureError("readiness evidence manifest calibration_ref is invalid")
        if not isinstance(artifact["source"], str) or not artifact["source"].strip():
            raise ReplayFixtureError("readiness evidence manifest source is invalid")
        captured_at = artifact["captured_at"]
        if not isinstance(captured_at, str):
            raise ReplayFixtureError("readiness evidence manifest captured_at is invalid")
        try:
            timestamp = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ReplayFixtureError("readiness evidence manifest captured_at is invalid") from exc
        if timestamp.tzinfo is None:
            raise ReplayFixtureError("readiness evidence manifest captured_at requires timezone")
        indexed[artifact_ref] = dict(artifact)
    return worker_id, embodiment_binding, indexed


def _validate_case_evidence(
    cases: tuple[dict[str, Any], ...],
    evidence: Mapping[str, Mapping[str, Any]],
) -> None:
    case_keys = {
        (
            case["observation_ref"], case["scene_revision"], case["frame_id"],
            case["calibration_ref"], case["candidate_set_ref"],
        )
        for case in cases
    }
    referenced: set[str] = set()
    for case in cases:
        identity = (
            case["observation_ref"], case["scene_revision"], case["frame_id"],
            case["calibration_ref"], case["candidate_set_ref"],
        )
        for prepared in case["prepared_candidates"]:
            for artifact_ref in prepared["evidence"]:
                if not isinstance(artifact_ref, str) or artifact_ref in referenced:
                    raise ReplayFixtureError("readiness replay evidence references are invalid")
                artifact = evidence.get(artifact_ref)
                if artifact is None:
                    raise ReplayFixtureError("readiness replay evidence reference is missing")
                artifact_identity = (
                    artifact["observation_ref"], artifact["scene_revision"],
                    artifact["frame_id"], artifact["calibration_ref"], artifact["candidate_set_ref"],
                )
                if artifact_identity != identity:
                    raise ReplayFixtureError("readiness replay evidence identity is unbound")
                referenced.add(artifact_ref)
    for artifact in evidence.values():
        if (
            artifact["observation_ref"], artifact["scene_revision"], artifact["frame_id"],
            artifact["calibration_ref"], artifact["candidate_set_ref"],
        ) not in case_keys:
            raise ReplayFixtureError("readiness evidence manifest contains an unknown case")


def _case_key(request: Mapping[str, Any]) -> tuple[Any, ...]:
    candidates = request.get("candidates")
    if not isinstance(candidates, list):
        raise ReplayFixtureError("readiness request candidates are invalid")
    refs = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ReplayFixtureError("readiness request candidate is invalid")
        refs.append((candidate.get("candidate_ref"), candidate.get("entity_ref")))
    return (
        request.get("observation_ref"),
        request.get("scene_revision"),
        request.get("frame_id"),
        request.get("calibration_ref"),
        request.get("candidate_set_ref"),
        tuple(refs),
    )


def _handle_factory(worker_id: str, embodiment_binding: Mapping[str, str], cases: tuple[dict[str, Any], ...]):
    indexed = {
        (
            case["observation_ref"],
            case["scene_revision"],
            case["frame_id"],
            case["calibration_ref"],
            case["candidate_set_ref"],
            tuple(tuple(item) for item in case["candidate_refs"]),
        ): case
        for case in cases
    }

    def handle(request: Mapping[str, Any]) -> Mapping[str, Any]:
        key = _case_key(request)
        case = indexed.get(key)
        if case is None:
            raise ReplayFixtureError("readiness replay request does not match a fixture case")
        return {
            "request_id": request["request_id"],
            "schema_version": SCHEMA_VERSION,
            "status": "available",
            "worker_id": worker_id,
            "embodiment_binding": dict(embodiment_binding),
            "motion_authorized": False,
            "prepared_candidates": case["prepared_candidates"],
            "provider_available": True,
        }

    return handle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--evidence-manifest", type=Path, required=True)
    args = parser.parse_args()
    worker_id, embodiment_binding, cases = _load_fixture(args.fixture.expanduser())
    evidence_worker_id, evidence_binding, evidence = _load_evidence_manifest(args.evidence_manifest.expanduser())
    if evidence_worker_id != worker_id:
        raise ReplayFixtureError("readiness evidence manifest worker identity mismatch")
    if evidence_binding != embodiment_binding:
        raise ReplayFixtureError("readiness evidence manifest embodiment binding mismatch")
    _validate_case_evidence(cases, evidence)
    return serve(
        "robotwin20-readiness-replay",
        lambda: None,
        _handle_factory(worker_id, embodiment_binding, cases),
        schema_version=SCHEMA_VERSION,
    )


if __name__ == "__main__":
    raise SystemExit(main())
