#!/usr/bin/env python
"""Run LIBERO evaluation workspaces until all sessions are terminal."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import yaml

TERMINAL_STATUSES = {"succeeded", "failed", "timed_out", "cancelled", "rejected"}


def find_repo_root() -> Path:
    for path in Path(__file__).resolve().parents:
        if (path / "scripts" / "run_runtime_watchdog.py").is_file():
            return path
    raise RuntimeError("could not find repository root containing scripts/run_runtime_watchdog.py")


def read_sessions(workspace: Path) -> list[dict]:
    sessions_md = workspace / "SESSIONS.md"
    text = sessions_md.read_text()
    try:
        block = text.split("```yaml", 1)[1].split("```", 1)[0]
    except IndexError as exc:
        raise ValueError(f"{sessions_md} does not contain a fenced yaml block") from exc
    doc = yaml.safe_load(block)
    return list(doc.get("sessions") or [])


def session_counts(workspace: Path) -> Counter:
    return Counter(session.get("status", "unknown") for session in read_sessions(workspace))


def all_terminal(workspace: Path) -> bool:
    sessions = read_sessions(workspace)
    return bool(sessions) and all(session.get("status") in TERMINAL_STATUSES for session in sessions)


def print_workspace_status(workspace: Path, *, verbose_sessions: bool = False) -> None:
    counts = session_counts(workspace)
    print(f"[xvla-eval] {workspace}: counts {dict(counts)}", flush=True)
    if not verbose_sessions:
        return
    for session in read_sessions(workspace):
        status = session.get("status")
        if status not in TERMINAL_STATUSES:
            continue
        result = session.get("result") or {}
        benchmark = session.get("benchmark") or {}
        print(
            "[xvla-eval] "
            f"t{benchmark.get('task_index')} "
            f"i{benchmark.get('instance_id')}: {status} "
            f"success={result.get('success')} "
            f"steps={result.get('num_steps')} "
            f"return={result.get('return_value')}",
            flush=True,
        )


def iter_workspaces(paths: list[Path]) -> list[Path]:
    workspaces: list[Path] = []
    for path in paths:
        path = path.expanduser().resolve()
        if (path / "SESSIONS.md").is_file():
            workspaces.append(path)
            continue
        for child in sorted(path.iterdir()):
            if child.is_dir() and (child / "SESSIONS.md").is_file():
                workspaces.append(child)
    if not workspaces:
        joined = ", ".join(str(path) for path in paths)
        raise ValueError(f"no workspaces containing SESSIONS.md found under: {joined}")
    return workspaces


def run_watchdog_once(repo_root: Path, workspace: Path, conda_env: str) -> int:
    watchdog = str(repo_root / "scripts" / "run_runtime_watchdog.py")
    if os.environ.get("CONDA_DEFAULT_ENV") == conda_env:
        cmd = [sys.executable, watchdog, "--workspace", str(workspace), "--once"]
    else:
        cmd = [
            "conda",
            "run",
            "--no-capture-output",
            "-n",
            conda_env,
            "python",
            watchdog,
            "--workspace",
            str(workspace),
            "--once",
        ]
    return subprocess.run(cmd, cwd=repo_root).returncode


def run_workspace(
    repo_root: Path,
    workspace: Path,
    conda_env: str,
    sleep_s: float,
    *,
    verbose_sessions: bool = False,
) -> None:
    print(f"[xvla-eval] running {workspace}", flush=True)
    while not all_terminal(workspace):
        rc = run_watchdog_once(repo_root, workspace, conda_env)
        print_workspace_status(workspace, verbose_sessions=verbose_sessions)
        if rc != 0 and not all_terminal(workspace):
            raise RuntimeError(f"watchdog exited with code {rc} before all sessions reached terminal status")
        if not all_terminal(workspace):
            time.sleep(sleep_s)
    print(f"[xvla-eval] completed {workspace}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-root",
        action="append",
        type=Path,
        help="Directory containing suite workspaces, e.g. tests/xvla/libero_4suite_...",
    )
    parser.add_argument(
        "--workspace",
        action="append",
        type=Path,
        help="Single workspace containing SESSIONS.md. Can be passed multiple times.",
    )
    parser.add_argument("--conda-env", default="paos", help="Conda environment used to run the PAOS watchdog")
    parser.add_argument("--sleep-s", type=float, default=1.0, help="Seconds to sleep between watchdog passes")
    parser.add_argument(
        "--verbose-sessions",
        action="store_true",
        help="Print one line for each terminal session after every watchdog pass.",
    )
    args = parser.parse_args()

    paths = (args.run_root or []) + (args.workspace or [])
    if not paths:
        parser.error("pass at least one --run-root or --workspace")

    repo_root = find_repo_root()
    for workspace in iter_workspaces(paths):
        run_workspace(repo_root, workspace, args.conda_env, args.sleep_s, verbose_sessions=args.verbose_sessions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
