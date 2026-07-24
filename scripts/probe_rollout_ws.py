#!/usr/bin/env python
"""Probe external rollout WebSocket (health / reset / optional control step)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
ext_root = str(ROOT / "external")
if ext_root not in sys.path:
    sys.path.insert(0, ext_root)

from isaac_env.protocol import decode_message, encode_message

try:
    from websockets.sync.client import connect
except ImportError as exc:
    raise SystemExit("websockets>=16 required") from exc


def _request(ws, req_type: str, payload: dict | None = None) -> dict:
    envelope = {"type": req_type, "seq": 1, "payload": dict(payload or {})}
    ws.send(encode_message(envelope))
    return decode_message(ws.recv())


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe rollout WebSocket server")
    parser.add_argument("--url", default="ws://127.0.0.1:8765")
    parser.add_argument("--reset", action="store_true", help="Send reset (starts sim if not up)")
    parser.add_argument("--step-control", action="store_true", help="Send one empty control step after reset")
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args()

    print(f"connecting {args.url} (timeout={args.timeout}s) ...", flush=True)
    with connect(
        args.url,
        open_timeout=min(args.timeout, 60.0),
        close_timeout=args.timeout,
        max_size=None,
        proxy=None,
    ) as ws:
        health = _request(ws, "health")
        print("health:", "ok" if health.get("ok") else health)
        if not health.get("ok"):
            return 1

        if args.reset or args.step_control:
            print("reset: waiting (first Isaac boot can take 3–10 min) ...", flush=True)
            reset = _request(ws, "reset")
            print("reset:", "ok" if reset.get("ok") else reset.get("error", reset))
            if not reset.get("ok"):
                return 1
            obs = (reset.get("payload") or {}).get("obs") or {}
            print("  obs keys:", sorted(obs.keys()) if isinstance(obs, dict) else type(obs))

        if args.step_control:
            hold_action = {"arm_joint_controller": [[0.0] * 8]}
            step = _request(ws, "step", {"mode": "control", "action": hold_action})
            print("step:", "ok" if step.get("ok") else step.get("error", step))
            return 0 if step.get("ok") else 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
