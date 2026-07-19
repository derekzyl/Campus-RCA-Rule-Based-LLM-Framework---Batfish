#!/usr/bin/env python3
"""Compare rule_only vs llm_only vs hybrid on labelled campus scenarios."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from campus_rca.config import Settings
from campus_rca.pipeline import RCAPipeline, load_scenarios
from evaluation.metrics import score_row, write_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Campus RCA modes")
    parser.add_argument(
        "--modes",
        nargs="+",
        default=["rule_only", "llm_only", "hybrid"],
        choices=["rule_only", "llm_only", "hybrid"],
    )
    parser.add_argument("--offline", action="store_true", help="Synthetic evidence (no Batfish)")
    parser.add_argument("--out", type=Path, default=ROOT / "results")
    parser.add_argument("--llm-backend", default=None, help="mock|openai|ollama")
    args = parser.parse_args()

    settings = Settings()
    if args.offline:
        settings.use_batfish = False
    if args.llm_backend:
        settings.llm_backend = args.llm_backend  # type: ignore[assignment]

    data = load_scenarios()
    pipe = RCAPipeline(settings)
    rows = []
    for scenario in data["scenarios"]:
        gt = scenario["ground_truth"]
        for mode in args.modes:
            result = pipe.run_scenario(scenario, mode=mode)
            rows.append(score_row(result, gt))
            status = "OK" if rows[-1]["localisation_correct"] else "MISS"
            print(f"[{status}] {mode:10} {scenario['id']:24} -> {result.final_fault_type}@{result.final_device}")

    path = write_report(rows, args.out)
    print(f"\nWrote {path}")
    print(f"Also wrote {args.out / 'evaluation_report.md'}")


if __name__ == "__main__":
    main()
