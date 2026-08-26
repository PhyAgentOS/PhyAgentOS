#!/usr/bin/env python3
"""第 7 步结果完整性校验（规划 §8 第 7 步 I-5 + eval_protocol §5 事前判据）。

校验项：
  I-5-1  completed_episodes == total_episodes
  I-5-2  success + failed + timed_out == completed
  I-5-3  valid + invalid == completed
  I-5-4  status != succeeded 时必须有批次级错误信息（本次预期 succeeded，仅告警）
  I-5-5  episode_id 唯一且覆盖 t0-9 × i0-49 × r0（500 个）
  协议§5  success_rate >= 95% 且 timed_out/500 < 20%（事前判据，只报数不修改）

用法：
  python3 scripts/verify_result.py <result.json>
"""
from __future__ import annotations

import json
import sys
from collections import Counter


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: python3 scripts/verify_result.py <result.json>")
        return 2
    r = load(sys.argv[1])

    failures: list[str] = []
    warns: list[str] = []

    def check(cond: bool, tag: str, detail: str) -> None:
        print(f"[{'PASS' if cond else 'FAIL'}] {tag}: {detail}")
        if not cond:
            failures.append(tag)

    # —— 基础字段 ——
    check(r.get("schema_version") == "benchmark_execution_result_v1",
          "schema", f"schema_version={r.get('schema_version')}")
    check(r.get("suite") == "libero_spatial", "suite", r.get("suite"))
    check(r.get("control_mode") == "relative", "control_mode", r.get("control_mode"))
    check(r.get("max_steps") == 220, "max_steps", f"max_steps={r.get('max_steps')}")
    check(r.get("layout_mode") == "per_episode", "layout_mode", r.get("layout_mode"))
    check(r.get("seed") == 0, "seed", f"seed={r.get('seed')}")

    episodes = r.get("episodes", [])
    total = r.get("total_episodes")
    completed = r.get("completed_episodes")

    # —— I-5-1 ——
    check(total == 500, "I-5-1a", f"total_episodes={total}（期望 500）")
    check(completed == len(episodes), "I-5-1b", f"completed_episodes={completed} == len(episodes)={len(episodes)}")
    check(completed == total, "I-5-1c", f"completed==total=={completed}")

    # —— 分类统计 ——
    succ = sum(1 for e in episodes if e.get("success"))
    n_timed_out = sum(1 for e in episodes if e.get("termination") == "timed_out")
    n_failed = sum(1 for e in episodes if e.get("termination") == "failed")
    n_invalid = sum(1 for e in episodes if e.get("error_code") is not None)

    # —— I-5-2 ——
    check(succ + n_failed + n_timed_out == completed,
          "I-5-2", f"success({succ}) + failed({n_failed}) + timed_out({n_timed_out}) == completed({completed})")

    # —— I-5-3 ——
    check(r.get("valid_episodes") == completed - n_invalid,
          "I-5-3", f"valid_episodes={r.get('valid_episodes')} == completed-invalid={completed - n_invalid}")

    # —— 终止态与 success 一致性 ——
    bad_term = [e["episode_id"] for e in episodes
                if e.get("termination") not in ("success", "failed", "timed_out")]
    check(not bad_term, "termination-域", f"非法 termination: {bad_term[:5] or '无'}")
    inconsistent = [e["episode_id"] for e in episodes
                    if (e.get("success") is True) != (e.get("termination") == "success")]
    check(not inconsistent, "success-一致性",
          f"success 与 termination 不一致: {inconsistent[:5] or '无'}")

    # —— 步数边界 ——
    over = [e["episode_id"] for e in episodes if e.get("num_steps", 0) > r.get("max_steps", 220)]
    check(not over, "num_steps<=max_steps", f"超界: {over[:5] or '无'}")
    to_over = [e["episode_id"] for e in episodes
               if e.get("termination") == "timed_out" and e.get("num_steps", 0) != r.get("max_steps", 220)]
    if to_over:
        warns.append(f"timed_out 但 num_steps != max_steps: {to_over[:5]}")

    # —— I-5-5 episode 覆盖 ——
    ids = [e.get("episode_id") for e in episodes]
    dup = [k for k, v in Counter(ids).items() if v > 1]
    check(not dup, "I-5-5a", f"重复 episode_id: {dup[:5] or '无'}")
    expected = {f"libero_spatial_t{t}_i{i}_r{rn}" for t in range(10) for i in range(50) for rn in range(1)}
    missing = expected - set(ids)
    extra = set(ids) - expected
    check(not missing and not extra, "I-5-5b",
          f"缺失 {len(missing)} 个 / 多余 {len(extra)} 个（期望恰好 500 全集）")

    # —— I-5-4 批次级错误 ——
    status = r.get("status")
    if status == "succeeded":
        check(True, "I-5-4", "status=succeeded（无需批次级错误信息）")
    else:
        warns.append(f"status={status}：需在归档记录中写明批次级 error_code/error_message 与原因")
        check(False, "I-5-4", f"status={status} != succeeded")

    # —— 分数 ——
    rate = r.get("success_rate")
    calc_rate = succ / total if total else 0.0
    check(abs((rate or 0.0) - calc_rate) < 1e-9, "success_rate-自洽",
          f"字段={rate}，重算={calc_rate:.6f}")

    # —— 协议 §5 事前判据（只报数，判据定死不可改） ——
    print("-" * 62)
    print(f"success_rate        : {rate:.4f}（判据 ≥0.95）")
    print(f"timed_out/500       : {n_timed_out}/500（判据 <20%）")
    print(f"completed_episodes  : {completed}")
    print(f"mean_policy_latency : {r.get('mean_policy_latency_ms')} ms")
    print(f"elapsed_s           : {r.get('elapsed_s')} s")
    per_task = Counter((e.get("task_id"), e.get("success")) for e in episodes)
    print("-" * 62)
    print("per-task success rate（对照官方发布表）:")
    for t in range(10):
        s = per_task.get((t, True), 0)
        n = s + per_task.get((t, False), 0)
        print(f"  task {t:2d}: {s:3d}/{n:3d} = {s / n * 100:.1f}%" if n else f"  task {t:2d}: 无数据")
    print("-" * 62)

    for w in warns:
        print(f"[WARN] {w}")
    verdict = "VERIFY_OK" if not failures else "VERIFY_FAIL"
    print(verdict)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
