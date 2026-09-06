#!/usr/bin/env python3
"""Materialize a no-motion RoboTwin provider capability document."""

from __future__ import annotations

import argparse
from pathlib import Path

from robotwin20_adapter.motion_capabilities import (
    canonical_motion_capability,
    derive_robotwin_motion_capability,
    motion_capability_digest,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--robotwin-root", type=Path, required=True)
    parser.add_argument("--runtime-python", type=Path, required=True)
    parser.add_argument("--embodiment", required=True)
    parser.add_argument("--arm", choices=("left", "right"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.output.is_absolute() or args.output.exists() or args.output.is_symlink():
        parser.error("--output must be a new absolute path")
    document = derive_robotwin_motion_capability(
        args.robotwin_root,
        embodiment_id=args.embodiment,
        arm_id=args.arm,
        runtime_python=args.runtime_python,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_motion_capability(document))
    print(f"status=materialized\nsha256={motion_capability_digest(document)}\npath={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
