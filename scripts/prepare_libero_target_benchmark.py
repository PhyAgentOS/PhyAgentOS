#!/usr/bin/env python
"""Prepare one PAOS session that runs a target-native LIBERO suite benchmark."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PhyAgentOS.runtime.state_io.markdown_yaml import read_yaml_block, write_yaml_block

from scripts.init_runtime_workspace import init_runtime_workspace
from scripts.prepare_libero_suite_benchmark import DEFAULT_MAX_STEPS, _ensure_libero_contract


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--suite", required=True, choices=["libero_spatial", "libero_object", "libero_goal", "libero_10"])
    parser.add_argument("--policy-id", default="xvla")
    parser.add_argument("--target-id", default="libero_real_remote")
    parser.add_argument("--skillruntime-id", default=None)
    parser.add_argument("--target-endpoint", default="targetws://127.0.0.1:9002")
    parser.add_argument("--policy-endpoint", default="openpi://127.0.0.1:8000")
    parser.add_argument("--task-ids", default="0-9")
    parser.add_argument("--init-state-ids", default="0-49")
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--control-mode", default="absolute", choices=["relative", "absolute"])
    parser.add_argument("--execute-timeout-s", type=float, default=172800)
    parser.add_argument("--policy-timeout-s", type=float, default=180)
    parser.add_argument("--force-init", action="store_true")
    args = parser.parse_args()

    workspace = Path(args.workspace).expanduser()
    init_runtime_workspace(workspace, force=args.force_init)
    write_yaml_block(workspace / "SESSIONS.md", "Runtime Sessions", {"version": "runtime_sessions_v1", "sessions": []})
    _ensure_libero_contract(workspace)

    skillruntime_id = args.skillruntime_id or f"{args.policy_id}_libero_target_benchmark"
    max_steps = args.max_steps or DEFAULT_MAX_STEPS.get(args.suite, 300)
    run_id = f"{args.policy_id}_{args.suite}_target_benchmark_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    _write_target(workspace, args, skillruntime_id, max_steps)
    _write_skillruntime(workspace, skillruntime_id)
    _write_session(workspace, args, skillruntime_id, max_steps, run_id)

    print(f"workspace: {workspace}")
    print(f"run_id: {run_id}")
    print("sessions_added: 1")
    print("next:")
    print(f"  PYTHONPATH={ROOT} conda run -n paos python scripts/run_runtime_watchdog.py --workspace {workspace} --once")
    return 0


def _write_target(workspace: Path, args: argparse.Namespace, skillruntime_id: str, max_steps: int) -> None:
    path = workspace / "TARGETS.md"
    doc = read_yaml_block(path)
    doc["targets"] = [
        target
        for target in doc.get("targets", [])
        if target.get("id") != args.target_id
    ]
    doc.setdefault("targets", []).append(
        {
            "id": args.target_id,
            "target_class": "remote",
            "target_kind": "simulation",
            "enabled": True,
            "workspace": "workspaces/libero_real",
            "supported_skillruntimes": [skillruntime_id],
            "runtime": {
                "target_runtime": "LiberoRemoteTargetProxy",
                "target_endpoint": args.target_endpoint,
                "target_adapter": "target_adapter://libero_adapter",
                "runtime_contract_ref": "configs/runtime/contracts/libero_real.runtime.yaml",
            },
            "observation": {"observation_type": "multimodal", "empty_observation_allowed": False},
            "perception": {"enabled": False, "strict_preflight": True},
            "config": {
                "benchmark_name": args.suite,
                "task_id": 0,
                "init_state_id": 0,
                "camera_height": 256,
                "camera_width": 256,
                "action_dim": 7,
                "max_chunk_size": 50,
                "max_steps": max_steps,
                "num_steps_wait": 10,
                "control_mode": args.control_mode,
                "target_ws_timeout_s": args.execute_timeout_s + 300,
                "action": {"action_dim": 7, "max_chunk_size": 50},
            },
        }
    )
    write_yaml_block(path, "Runtime Targets", doc)


def _write_skillruntime(workspace: Path, skillruntime_id: str) -> None:
    path = workspace / "SKILLRUNTIME.md"
    doc = read_yaml_block(path)
    doc["skillruntimes"] = [
        skill
        for skill in doc.get("skillruntimes", [])
        if skill.get("id") != skillruntime_id
    ]
    doc.setdefault("skillruntimes", []).append(
        {
            "id": skillruntime_id,
            "runtime": "LiberoBenchmarkSkillRuntime",
            "runtime_kind": "builtin",
            "loop_mode": "target_native_benchmark",
            "agent_exposure": "none",
            "supported_target_kinds": ["simulation"],
            "observation_contract": {"observation_type": "multimodal", "empty_observation_allowed": False},
            "supports_chunk": False,
            "default_replan_every": 1,
            "requires": {"sensors": [], "environment_outputs": [], "strict_environment_contract": True},
            "adapter_requirements": {"allowed_bridges": [], "forbidden": []},
        }
    )
    write_yaml_block(path, "Runtime Skill Runtimes", doc)


def _write_session(
    workspace: Path,
    args: argparse.Namespace,
    skillruntime_id: str,
    max_steps: int,
    run_id: str,
) -> None:
    path = workspace / "SESSIONS.md"
    doc = read_yaml_block(path)
    session_id = run_id
    doc["sessions"] = [
        {
            "session_id": session_id,
            "target_ref": f"target://{args.target_id}",
            "skillruntime_ref": f"skillruntime://{skillruntime_id}",
            "task_description": f"Run target-native LIBERO benchmark for {args.suite}",
            "status": "pending",
            "priority": "normal",
            "timeouts": {
                "queue_timeout_s": 30,
                "preflight_timeout_s": 20,
                "execute_timeout_s": args.execute_timeout_s,
                "policy_timeout_s": args.policy_timeout_s,
            },
            "retry": {"max_retries": 0, "attempted": 0},
            "depends_on": [],
            "routing": {
                "target_endpoint": args.target_endpoint,
                "policy_endpoint": args.policy_endpoint,
                "adapter_resolution": "strict_auto",
            },
            "execution": {
                "max_steps": max_steps,
                "replan_every_steps": 1,
                "action_chunk_mode": "chunk_buffer",
                "chunk_switch_mode": "hard_switch",
            },
            "runtime_hints": {
                "perception_queries": [
                    {"task_ids": _parse_ids(args.task_ids)},
                    {"init_state_ids": _parse_ids(args.init_state_ids)},
                ],
                "force_environment_refresh": False,
                "preferred_replan_every_steps": 1,
            },
            "safety_profile": {
                "profile": "default_simulation",
                "workspace_bounds": "default",
                "stop_on_policy_timeout": True,
            },
            "benchmark": {
                "benchmark_id": "LIBERO",
                "suite_id": args.suite,
                "policy_id": args.policy_id,
                "run_id": run_id,
            },
            "result": {},
        }
    ]
    write_yaml_block(path, "Runtime Sessions", doc)


def _parse_ids(spec: str) -> list[int]:
    ids: list[int] = []
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            ids.extend(range(int(start), int(end) + 1))
        else:
            ids.append(int(part))
    return sorted(dict.fromkeys(ids))


if __name__ == "__main__":
    raise SystemExit(main())
