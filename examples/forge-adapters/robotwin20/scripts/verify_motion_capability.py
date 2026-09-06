#!/usr/bin/env python3
"""Independently revalidate a RoboTwin motion-capability source projection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from robotwin20_adapter.motion_capabilities import (
    MotionCapabilityDocument,
    validate_robotwin_motion_capability,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capability", type=Path, required=True)
    parser.add_argument("--robotwin-root", type=Path, required=True)
    parser.add_argument("--runtime-python", type=Path, required=True)
    parser.add_argument("--verifier-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--controller-source", type=Path)
    parser.add_argument(
        "--controller-id",
        choices=("robotwin-sapien-drive-target", "paos-robotwin-capability-bounded-drive-target"),
        default="robotwin-sapien-drive-target",
    )
    args = parser.parse_args()
    if not args.capability.is_absolute() or not args.capability.is_file() or args.capability.is_symlink():
        parser.error("--capability must be an absolute regular file")
    if not args.output.is_absolute() or args.output.exists() or args.output.is_symlink():
        parser.error("--output must be a new absolute path")
    try:
        document = MotionCapabilityDocument.model_validate_json(args.capability.read_bytes())
    except (OSError, ValueError) as exc:
        parser.error(f"invalid capability document: {exc}")
    validation = validate_robotwin_motion_capability(
        document,
        args.robotwin_root,
        runtime_python=args.runtime_python,
        verifier_id=args.verifier_id,
        controller_source_path=args.controller_source,
        controller_id=args.controller_id,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(validation.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    print(f"status={validation.status}\npath={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
