#!/usr/bin/env python3
"""Run one approved simulation probe and persist its validated response."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from robotwin20_adapter import build_simulation_probe_client, load_simulation_probe_profile
from robotwin20_adapter.route_readiness import validate_route_request


class ProbeRunError(RuntimeError):
    pass


def _load_request(path: Path) -> Mapping[str, Any]:
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise ProbeRunError("route request must be an absolute regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProbeRunError("route request is invalid JSON") from exc
    if not isinstance(value, Mapping):
        raise ProbeRunError("route request must contain an object")
    validate_route_request(value)
    return value


def _write_response(path: Path, value: Mapping[str, Any]) -> None:
    if not path.is_absolute() or path.exists() or path.is_symlink():
        raise ProbeRunError("output must be a new absolute file")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(payload)
    path.chmod(0o600)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--route-request", type=Path, required=True)
    parser.add_argument("--candidate-ref", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    request = _load_request(args.route_request)
    client = build_simulation_probe_client(load_simulation_probe_profile(args.profile))
    try:
        response = client.probe(request, candidate_ref=args.candidate_ref)
    finally:
        client.release()
    _write_response(args.output, response)
    print(
        json.dumps(
            {
                "status": response["status"],
                "output": str(args.output),
                "world_change_started": response["world_change_started"],
                "world_change_completed": response["world_change_completed"],
            },
            sort_keys=True,
        )
    )
    return 0 if response["status"] == "available" else 2


if __name__ == "__main__":
    raise SystemExit(main())
