from __future__ import annotations

import argparse
import json
import os
import sys
import time


def emit(value):
    sys.stdout.write(json.dumps(value) + "\n")
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="normal")
    args = parser.parse_args()
    if args.mode == "unavailable":
        emit({"event": "worker_unavailable"})
        return 2
    emit({"event": "worker_ready"})
    for line in sys.stdin:
        request = json.loads(line)
        if request.get("command") == "shutdown":
            emit({"request_id": request["request_id"], "status": "shutdown"})
            return 0
        if args.mode == "timeout":
            time.sleep(2)
        elif args.mode == "invalid-json":
            sys.stdout.write("not-json\n")
            sys.stdout.flush()
            continue
        request_id = "wrong" if args.mode == "wrong-id" else request["request_id"]
        emit({"request_id": request_id, "status": "available", "pid": os.getpid()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
