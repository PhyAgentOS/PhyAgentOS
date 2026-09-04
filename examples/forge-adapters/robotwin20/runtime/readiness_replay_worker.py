"""No-motion readiness evidence replay worker.

This worker replays an externally materialized, hash-pinned evidence fixture.
It never imports PAOS/RoboTwin/Hephaestus and never invokes a planner or
actuator.  The fixture is a conformance input, not proof of physical readiness.
"""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any, Mapping

from worker_protocol import serve

SCHEMA_VERSION = "paos-robotwin20-readiness-replay/v1"


class ReplayFixtureError(ValueError):
    """The replay fixture is malformed or does not match a request."""


def _load_fixture(path: Path) -> tuple[str, tuple[dict[str, Any], ...]]:
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise ReplayFixtureError("readiness replay fixture must be an absolute regular file")
    if not stat.S_ISREG(path.stat().st_mode) or path.stat().st_mode & 0o022:
        raise ReplayFixtureError("readiness replay fixture must not be writable")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReplayFixtureError("readiness replay fixture could not be loaded") from exc
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version", "worker_id", "motion_authorized", "cases"
    }:
        raise ReplayFixtureError("readiness replay fixture fields are invalid")
    if value["schema_version"] != SCHEMA_VERSION:
        raise ReplayFixtureError("readiness replay fixture schema_version is unsupported")
    worker_id = value["worker_id"]
    if not isinstance(worker_id, str) or not worker_id.strip():
        raise ReplayFixtureError("readiness replay fixture worker_id is invalid")
    if value["motion_authorized"] is not False:
        raise ReplayFixtureError("readiness replay fixture must be no-motion")
    cases = value["cases"]
    if not isinstance(cases, list) or not cases:
        raise ReplayFixtureError("readiness replay fixture cases must be non-empty")
    normalized: list[dict[str, Any]] = []
    seen_keys: set[tuple[Any, ...]] = set()
    for case in cases:
        if not isinstance(case, Mapping) or set(case) != {
            "observation_ref", "scene_revision", "frame_id", "candidate_set_ref",
            "candidate_refs", "prepared_candidates",
        }:
            raise ReplayFixtureError("readiness replay case fields are invalid")
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
        case_value = dict(case)
        case_key = (
            case_value["observation_ref"],
            case_value["scene_revision"],
            case_value["frame_id"],
            case_value["candidate_set_ref"],
            tuple(tuple(item) for item in case_value["candidate_refs"]),
        )
        if case_key in seen_keys:
            raise ReplayFixtureError("readiness replay fixture contains duplicate case identity")
        seen_keys.add(case_key)
        normalized.append(case_value)
    return worker_id, tuple(normalized)


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
        request.get("candidate_set_ref"),
        tuple(refs),
    )


def _handle_factory(worker_id: str, cases: tuple[dict[str, Any], ...]):
    indexed = {
        (
            case["observation_ref"],
            case["scene_revision"],
            case["frame_id"],
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
            "motion_authorized": False,
            "prepared_candidates": case["prepared_candidates"],
            "provider_available": True,
        }

    return handle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    args = parser.parse_args()
    worker_id, cases = _load_fixture(args.fixture.expanduser())
    return serve(
        "robotwin20-readiness-replay",
        lambda: None,
        _handle_factory(worker_id, cases),
        schema_version=SCHEMA_VERSION,
    )


if __name__ == "__main__":
    raise SystemExit(main())
