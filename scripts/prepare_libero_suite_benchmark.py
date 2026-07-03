#!/usr/bin/env python
"""Prepare a PAOS runtime workspace for a full LIBERO suite benchmark."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PhyAgentOS.runtime.communication.target_ws_client import TargetWSClient
from PhyAgentOS.runtime.state_io.markdown_yaml import read_yaml_block, write_yaml_block

from scripts.init_runtime_workspace import init_runtime_workspace


DEFAULT_MAX_STEPS = {
    "libero_spatial": 220,
    "libero_object": 280,
    "libero_goal": 300,
    "libero_10": 520,
    "libero_90": 400,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Create pending sessions for one full LIBERO suite")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--suite", default="libero_spatial")
    parser.add_argument("--policy-id", default="pi05", help="Used in session ids/report metadata")
    parser.add_argument("--skillruntime-id", default=None)
    parser.add_argument("--target-id", default="libero_real_remote")
    parser.add_argument("--target-endpoint", default="targetws://127.0.0.1:9002")
    parser.add_argument("--policy-endpoint", default="openpi://127.0.0.1:8000")
    parser.add_argument("--task-ids", default="all", help="all, comma list, or range like 0-9")
    parser.add_argument("--init-state-ids", default="0", help="comma list or range like 0-9")
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--replan-every-steps", type=int, default=10)
    parser.add_argument(
        "--control-mode",
        default="auto",
        choices=["auto", "relative", "absolute"],
        help="LIBERO OSC control mode. auto uses absolute for xvla and relative otherwise.",
    )
    parser.add_argument("--execute-timeout-s", type=float, default=900)
    parser.add_argument("--policy-timeout-s", type=float, default=180)
    parser.add_argument("--force-init", action="store_true", help="Overwrite existing runtime template files")
    parser.add_argument("--allow-duplicate-session-ids", action="store_true")
    parser.add_argument("--no-live-discovery", action="store_true")
    args = parser.parse_args()

    workspace = Path(args.workspace).expanduser()
    init_result = init_runtime_workspace(workspace, force=args.force_init)
    if "SESSIONS.md" in init_result.get("created", []) or "SESSIONS.md" in init_result.get("overwritten", []):
        write_yaml_block(workspace / "SESSIONS.md", "Runtime Sessions", {"version": "runtime_sessions_v1", "sessions": []})
    _ensure_libero_contract(workspace)

    skillruntime_id = args.skillruntime_id or f"{args.policy_id}_libero_remote"
    max_steps = args.max_steps or DEFAULT_MAX_STEPS.get(args.suite, 300)
    control_mode = _resolve_control_mode(args.policy_id, args.control_mode)
    run_id = f"{args.policy_id}_{args.suite}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    task_list = _discover_tasks(args.target_endpoint, args.target_id, args.suite) if not args.no_live_discovery else []
    task_ids = _parse_ids(args.task_ids, max_id=len(task_list) - 1 if task_list else None)
    if args.task_ids == "all" and not task_ids:
        raise SystemExit("Live task discovery failed; pass --task-ids explicitly or start the LIBERO TargetWS server.")
    init_ids = _parse_ids(args.init_state_ids)

    _upsert_target(workspace, args, skillruntime_id, max_steps, control_mode)
    _upsert_skillruntime(workspace, skillruntime_id, args.policy_id, control_mode)
    created = _append_sessions(
        workspace,
        args=args,
        task_list=task_list,
        task_ids=task_ids,
        init_ids=init_ids,
        skillruntime_id=skillruntime_id,
        max_steps=max_steps,
        run_id=run_id,
    )
    print(f"workspace: {workspace}")
    print(f"run_id: {run_id}")
    print(f"control_mode: {control_mode}")
    print(f"sessions_added: {created}")
    print("next:")
    print(f"  PYTHONPATH={ROOT} conda run -n paos python scripts/run_runtime_watchdog.py --workspace {workspace}")
    return 0


def _discover_tasks(endpoint: str, target_id: str, suite: str) -> list[dict[str, Any]]:
    client = TargetWSClient(endpoint, target_id=target_id, timeout_s=300)
    try:
        client.call(
            "target.configure_session",
            {"libero": {"benchmark_name": suite, "task_id": 0, "init_state_id": 0}},
        )
        desc = client.call("target.describe", {})
    finally:
        client.close()
    tasks = desc.get("task_list") or []
    return [task for task in tasks if isinstance(task, dict)]


def _parse_ids(spec: str, *, max_id: int | None = None) -> list[int]:
    spec = str(spec).strip()
    if spec == "all":
        if max_id is None:
            return []
        return list(range(max_id + 1))
    ids: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            ids.extend(range(int(start), int(end) + 1))
        else:
            ids.append(int(part))
    return sorted(dict.fromkeys(ids))


def _resolve_control_mode(policy_id: str, requested: str) -> str:
    if requested != "auto":
        return requested
    return "absolute" if policy_id.lower() == "xvla" else "relative"


def _ensure_libero_contract(workspace: Path) -> None:
    path = workspace / "configs/runtime/contracts/libero_real.runtime.yaml"
    if not path.exists():
        return
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    action = payload.setdefault("action_contract", {})
    accepted = list(action.setdefault("accepted_representations", []))
    changed = False
    for representation in ("delta_eef_pose_gripper", "absolute_eef_pose_gripper"):
        if representation not in accepted:
            accepted.append(representation)
            changed = True
    if changed:
        action["accepted_representations"] = accepted
        path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _upsert_target(workspace: Path, args, skillruntime_id: str, max_steps: int, control_mode: str) -> None:
    path = workspace / "TARGETS.md"
    doc = read_yaml_block(path)
    targets = doc.setdefault("targets", [])
    target = next((item for item in targets if item.get("id") == args.target_id), None)
    if target is None:
        target = {
            "id": args.target_id,
            "target_class": "remote",
            "target_kind": "simulation",
            "enabled": True,
            "workspace": "workspaces/libero_real",
            "supported_skillruntimes": [],
            "runtime": {
                "target_runtime": "LiberoRemoteTargetProxy",
                "target_endpoint": args.target_endpoint,
                "target_adapter": "target_adapter://libero_adapter",
                "runtime_contract_ref": "configs/runtime/contracts/libero_real.runtime.yaml",
            },
            "observation": {"observation_type": "multimodal", "empty_observation_allowed": False},
            "perception": {"enabled": False, "strict_preflight": True},
            "config": {},
        }
        targets.append(target)

    target["enabled"] = True
    target["target_class"] = "remote"
    target["target_kind"] = "simulation"
    target.setdefault("runtime", {})
    target["runtime"].update(
        {
            "target_runtime": "LiberoRemoteTargetProxy",
            "target_endpoint": args.target_endpoint,
            "target_adapter": "target_adapter://libero_adapter",
            "runtime_contract_ref": "configs/runtime/contracts/libero_real.runtime.yaml",
        }
    )
    supported = list(target.setdefault("supported_skillruntimes", []))
    if skillruntime_id not in supported:
        supported.append(skillruntime_id)
    target["supported_skillruntimes"] = supported
    target.setdefault("observation", {"observation_type": "multimodal", "empty_observation_allowed": False})
    target.setdefault("perception", {"enabled": False, "strict_preflight": True})
    target["config"] = {
        **dict(target.get("config") or {}),
        "benchmark_name": args.suite,
        "task_id": 0,
        "init_state_id": 0,
        "camera_height": 256,
        "camera_width": 256,
        "action_dim": 7,
        "max_chunk_size": 50,
        "max_steps": max_steps,
        "num_steps_wait": 10,
        "control_mode": control_mode,
        "action": {"action_dim": 7, "max_chunk_size": 50},
    }
    write_yaml_block(path, "Runtime Targets", doc)


def _upsert_skillruntime(workspace: Path, skillruntime_id: str, policy_id: str, control_mode: str) -> None:
    path = workspace / "SKILLRUNTIME.md"
    doc = read_yaml_block(path)
    skills = doc.setdefault("skillruntimes", [])
    skill = next((item for item in skills if item.get("id") == skillruntime_id), None)
    representation = "absolute_eef_pose_gripper" if control_mode == "absolute" else "delta_eef_pose_gripper"
    action_control_mode = "cartesian_absolute_position" if control_mode == "absolute" else "policy_delta"
    action_space_token = "absolute" if control_mode == "absolute" else "delta"
    payload = {
        "id": skillruntime_id,
        "runtime": "OpenPISkillRuntime",
        "runtime_kind": "policy",
        "loop_mode": "policy_closed_loop",
        "agent_exposure": "none",
        "supported_target_kinds": ["simulation"],
        "policy": {"policy_client": "openpi", "policy_adapter": "policy_adapter://openpi_pi05_adapter", "supports_chunk": True},
        "observation_contract": {"observation_type": "multimodal", "empty_observation_allowed": False},
        "supports_chunk": True,
        "default_replan_every": 10,
        "requires": {"sensors": [], "environment_outputs": [], "strict_environment_contract": True},
        "output_contract": {
            "action": {
                "action_space_id": f"libero_{policy_id}_{action_space_token}_eef_gripper_v1",
                "tensor_key": "actions",
                "shape": ["T", 7],
                "dtype": "float32",
                "normalized": False,
                "representation": representation,
                "frame": "base",
                "control_mode": action_control_mode,
                "chunk": {"variable_T": True, "default_T": 50, "policy_hz": 20},
            }
        },
        "adapter_requirements": {"allowed_bridges": ["bridge://safety_clamp"], "forbidden": []},
    }
    if skill is None:
        skills.append(payload)
    else:
        skill.update(payload)
    write_yaml_block(path, "Runtime Skill Runtimes", doc)


def _append_sessions(
    workspace: Path,
    *,
    args,
    task_list: list[dict[str, Any]],
    task_ids: list[int],
    init_ids: list[int],
    skillruntime_id: str,
    max_steps: int,
    run_id: str,
) -> int:
    path = workspace / "SESSIONS.md"
    doc = read_yaml_block(path)
    sessions = doc.setdefault("sessions", [])
    existing_ids = {session.get("session_id") for session in sessions if isinstance(session, dict)}
    created = 0
    task_by_id = {int(task.get("task_id")): task for task in task_list if task.get("task_id") is not None}
    for task_id in task_ids:
        task = task_by_id.get(task_id, {})
        language = str(task.get("language") or task.get("task_name") or f"{args.suite} task {task_id}")
        for init_id in init_ids:
            session_id = f"{run_id}_t{task_id}_i{init_id}"
            if session_id in existing_ids and not args.allow_duplicate_session_ids:
                continue
            sessions.append(
                {
                    "session_id": session_id,
                    "target_ref": f"target://{args.target_id}",
                    "skillruntime_ref": f"skillruntime://{skillruntime_id}",
                    "task_description": language,
                    "status": "pending",
                    "priority": "normal",
                    "timeouts": {
                        "queue_timeout_s": 30,
                        "preflight_timeout_s": 20,
                        "execute_timeout_s": args.execute_timeout_s,
                        "policy_timeout_s": args.policy_timeout_s,
                    },
                    "retry": {"max_retries": 0, "attempted": 0},
                    "routing": {
                        "target_endpoint": args.target_endpoint,
                        "policy_endpoint": args.policy_endpoint,
                        "adapter_resolution": "strict_auto",
                        "adapter_overrides": None,
                    },
                    "execution": {
                        "max_steps": max_steps,
                        "replan_every_steps": args.replan_every_steps,
                        "action_chunk_mode": "chunk_buffer",
                        "chunk_switch_mode": "hard_switch",
                    },
                    "runtime_hints": {
                        "perception_queries": [],
                        "force_environment_refresh": False,
                        "preferred_replan_every_steps": args.replan_every_steps,
                    },
                    "safety_profile": {
                        "profile": "default_simulation",
                        "workspace_bounds": "default",
                        "stop_on_policy_timeout": True,
                    },
                    "benchmark": {
                        "benchmark_id": "LIBERO",
                        "suite_id": args.suite,
                        "task_name": language,
                        "task_index": task_id,
                        "instance_id": init_id,
                        "policy_id": args.policy_id,
                        "run_id": run_id,
                    },
                    "result": {},
                }
            )
            created += 1
    write_yaml_block(path, "Runtime Sessions", doc)
    return created


if __name__ == "__main__":
    raise SystemExit(main())
