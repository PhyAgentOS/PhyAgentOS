#!/usr/bin/env python3
"""Run the versioned Verification Service semantic-quality evaluation."""

from __future__ import annotations

import argparse
from pathlib import Path

from PhyAgentOS.verification.evaluation import run_semantic_evaluation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("evals/verification/evaluation_config_v1.json"),
    )
    parser.add_argument("--provider-config", type=Path, required=True)
    parser.add_argument("--max-cases", type=int)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    summary = run_semantic_evaluation(
        config_path=args.config,
        provider_config_path=args.provider_config,
        repo_root=repo_root,
        max_cases=args.max_cases,
    )
    print(f"status={summary.status}")
    print(f"run_dir={summary.run_dir}")
    print(f"quality_gate_eligible={str(summary.quality_gate_eligible).lower()}")
    print(f"quality_gate_passed={str(summary.quality_gate_passed).lower()}")
    return summary.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
