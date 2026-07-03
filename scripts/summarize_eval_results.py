#!/usr/bin/env python
"""Summarize LIBERO evaluation success rates."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import yaml


def read_sessions(workspace: Path) -> list[dict]:
    sessions_md = workspace / "SESSIONS.md"
    text = sessions_md.read_text()
    try:
        block = text.split("```yaml", 1)[1].split("```", 1)[0]
    except IndexError as exc:
        raise ValueError(f"{sessions_md} does not contain a fenced yaml block") from exc
    doc = yaml.safe_load(block)
    return list(doc.get("sessions") or [])


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


def summarize_workspace(workspace: Path) -> tuple[int, int]:
    sessions = read_sessions(workspace)
    counts = Counter(session.get("status", "unknown") for session in sessions)
    benchmark_success = 0
    benchmark_total = 0
    for session in sessions:
        result = session.get("result") or {}
        metadata = result.get("metadata") or {}
        benchmark = metadata.get("benchmark_result") or {}
        if not isinstance(benchmark, dict):
            continue
        if benchmark.get("total_episodes") is None:
            continue
        benchmark_success += int(benchmark.get("successes") or 0)
        benchmark_total += int(benchmark.get("total_episodes") or 0)
    if benchmark_total:
        success = benchmark_success
        total = benchmark_total
    else:
        success = sum(session.get("status") == "succeeded" for session in sessions)
        total = len(sessions)
    rate = success / total if total else 0.0
    print(f"{workspace.name}: {success}/{total} = {rate:.3%} statuses={dict(counts)}")
    return success, total


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
    args = parser.parse_args()

    paths = (args.run_root or []) + (args.workspace or [])
    if not paths:
        parser.error("pass at least one --run-root or --workspace")

    total_success = 0
    total_episodes = 0
    for workspace in iter_workspaces(paths):
        success, total = summarize_workspace(workspace)
        total_success += success
        total_episodes += total

    rate = total_success / total_episodes if total_episodes else 0.0
    print(f"overall: {total_success}/{total_episodes} = {rate:.3%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
