#!/usr/bin/env python3
"""Generate dissertation-ready tables and charts from evaluation_report.json."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MODE_ORDER = ["rule_only", "llm_only", "hybrid"]


def load_report(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "summary" not in data or "rows" not in data:
        raise ValueError(f"{path} must contain 'summary' and 'rows'")
    return data


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    fields = [
        "scenario_id",
        "mode",
        "truth_fault",
        "truth_device",
        "predicted_fault",
        "predicted_device",
        "localisation_correct",
        "keyword_coverage",
        "hallucination_rate",
        "evidence_faithfulness",
        "elapsed_ms",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_summary_csv(summary: dict[str, Any], path: Path) -> None:
    fields = [
        "mode",
        "n",
        "accuracy",
        "avg_keyword_coverage",
        "avg_hallucination_rate",
        "avg_evidence_faithfulness",
        "avg_elapsed_ms",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for mode in MODE_ORDER:
            if mode not in summary:
                continue
            row = {"mode": mode, **summary[mode]}
            w.writerow(row)


def write_latex_tables(summary: dict[str, Any], rows: list[dict[str, Any]], path: Path) -> None:
    lines = [
        "% Auto-generated from evaluation_report.json — paste into Chapter 5",
        "",
        "% --- Aggregate metrics ---",
        r"\begin{table}[ht]",
        r"\centering",
        r"\caption{Aggregate localisation and explanation metrics by mode}",
        r"\label{tab:rca-aggregate}",
        r"\begin{tabular}{lrrrrr}",
        r"\toprule",
        r"Mode & Accuracy & Keyword cov. & Hallucination & Faithfulness & Avg.\ ms \\",
        r"\midrule",
    ]
    for mode in MODE_ORDER:
        if mode not in summary:
            continue
        s = summary[mode]
        lines.append(
            f"{mode.replace('_', r'\_')} & {s['accuracy']:.2f} & "
            f"{s['avg_keyword_coverage']:.3f} & {s['avg_hallucination_rate']:.2f} & "
            f"{s['avg_evidence_faithfulness']:.2f} & {s['avg_elapsed_ms']:.1f} \\\\"
        )
    lines.extend(
        [
            r"\bottomrule",
            r"\end{tabular}",
            r"\end{table}",
            "",
            "% --- Per-scenario localisation matrix ---",
            r"\begin{table}[ht]",
            r"\centering",
            r"\caption{Per-scenario localisation outcomes (OK/MISS)}",
            r"\label{tab:rca-per-scenario}",
            r"\begin{tabular}{l" + "c" * len([m for m in MODE_ORDER if m in {r['mode'] for r in rows}]) + "}",
            r"\toprule",
        ]
    )
    modes_present = [m for m in MODE_ORDER if any(r["mode"] == m for r in rows)]
    lines.append("Scenario & " + " & ".join(m.replace("_", r"\_") for m in modes_present) + r" \\")
    lines.append(r"\midrule")

    scenarios: list[str] = []
    for r in rows:
        if r["scenario_id"] not in scenarios:
            scenarios.append(r["scenario_id"])
    lookup = {(r["scenario_id"], r["mode"]): r for r in rows}
    for sid in scenarios:
        cells = []
        for mode in modes_present:
            r = lookup.get((sid, mode))
            if not r:
                cells.append("--")
            else:
                cells.append("OK" if r["localisation_correct"] else "MISS")
        lines.append(sid.replace("_", r"\_") + " & " + " & ".join(cells) + r" \\")
    lines.extend(
        [
            r"\bottomrule",
            r"\end{tabular}",
            r"\end{table}",
            "",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _mode_labels(modes: list[str]) -> list[str]:
    return [m.replace("_", "\n") for m in modes]


def plot_charts(summary: dict[str, Any], rows: list[dict[str, Any]], out_dir: Path) -> list[Path]:
    import matplotlib.pyplot as plt
    import numpy as np

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    modes = [m for m in MODE_ORDER if m in summary]
    if not modes:
        return written

    # 1) Accuracy bar chart
    fig, ax = plt.subplots(figsize=(7, 4.2))
    acc = [summary[m]["accuracy"] for m in modes]
    colors = ["#2F6F4E", "#B85C38", "#1F4E79"]
    bars = ax.bar(_mode_labels(modes), acc, color=colors[: len(modes)], width=0.55)
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("Localisation accuracy")
    ax.set_title("Localisation accuracy by diagnosis mode")
    ax.axhline(1.0, color="#888888", linestyle="--", linewidth=0.8)
    for bar, v in zip(bars, acc):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 0.03, f"{v:.0%}", ha="center", fontsize=10)
    fig.tight_layout()
    p = out_dir / "fig_accuracy_by_mode.png"
    fig.savefig(p, dpi=160)
    plt.close(fig)
    written.append(p)

    # 2) Grouped metrics
    fig, ax = plt.subplots(figsize=(8, 4.5))
    metrics = [
        ("accuracy", "Accuracy"),
        ("avg_keyword_coverage", "Keyword cov."),
        ("avg_evidence_faithfulness", "Faithfulness"),
        ("avg_hallucination_rate", "Hallucination"),
    ]
    x = np.arange(len(metrics))
    width = 0.25
    for i, mode in enumerate(modes):
        vals = [summary[mode][k] for k, _ in metrics]
        ax.bar(x + (i - 1) * width, vals, width, label=mode, color=colors[i])
    ax.set_xticks(x)
    ax.set_xticklabels([lab for _, lab in metrics])
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("Score (0–1)")
    ax.set_title("Explanation-quality metrics by mode")
    ax.legend(frameon=False)
    fig.tight_layout()
    p = out_dir / "fig_metrics_by_mode.png"
    fig.savefig(p, dpi=160)
    plt.close(fig)
    written.append(p)

    # 3) Per-scenario OK/MISS matrix
    scenarios: list[str] = []
    for r in rows:
        if r["scenario_id"] not in scenarios:
            scenarios.append(r["scenario_id"])
    lookup = {(r["scenario_id"], r["mode"]): r for r in rows}
    matrix = np.full((len(scenarios), len(modes)), np.nan)
    for i, sid in enumerate(scenarios):
        for j, mode in enumerate(modes):
            r = lookup.get((sid, mode))
            if r is not None:
                matrix[i, j] = 1.0 if r["localisation_correct"] else 0.0

    fig, ax = plt.subplots(figsize=(8, 4.8))
    im = ax.imshow(matrix, cmap="RdYlGn", vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(modes)))
    ax.set_xticklabels(modes, rotation=20, ha="right")
    ax.set_yticks(range(len(scenarios)))
    ax.set_yticklabels(scenarios)
    ax.set_title("Per-scenario localisation (green=OK, red=MISS)")
    for i in range(len(scenarios)):
        for j in range(len(modes)):
            if not np.isnan(matrix[i, j]):
                ax.text(j, i, "OK" if matrix[i, j] == 1 else "MISS", ha="center", va="center", fontsize=9)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    p = out_dir / "fig_localisation_matrix.png"
    fig.savefig(p, dpi=160)
    plt.close(fig)
    written.append(p)

    # 4) Latency comparison
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ms = [summary[m]["avg_elapsed_ms"] for m in modes]
    ax.bar(_mode_labels(modes), ms, color=colors[: len(modes)], width=0.55)
    ax.set_ylabel("Average elapsed time (ms)")
    ax.set_title("Average diagnosis latency by mode")
    for i, v in enumerate(ms):
        ax.text(i, v, f"{v:.0f}", ha="center", va="bottom", fontsize=9)
    fig.tight_layout()
    p = out_dir / "fig_latency_by_mode.png"
    fig.savefig(p, dpi=160)
    plt.close(fig)
    written.append(p)

    return written


def export_all(report_path: Path, out_dir: Path | None = None) -> dict[str, Any]:
    data = load_report(report_path)
    out_dir = out_dir or report_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = data["summary"]
    rows = data["rows"]

    artifacts = {
        "csv_rows": out_dir / "evaluation_rows.csv",
        "csv_summary": out_dir / "evaluation_summary.csv",
        "latex": out_dir / "evaluation_tables.tex",
    }
    write_csv(rows, artifacts["csv_rows"])
    write_summary_csv(summary, artifacts["csv_summary"])
    write_latex_tables(summary, rows, artifacts["latex"])

    figures = plot_charts(summary, rows, out_dir / "figures")
    return {"tables": artifacts, "figures": figures, "out_dir": out_dir}


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot tables/charts from RCA evaluation JSON")
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "results" / "evaluation_report.json",
        help="Path to evaluation_report.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory (default: same folder as report)",
    )
    args = parser.parse_args()
    if not args.report.exists():
        raise SystemExit(
            f"Missing {args.report}. Run evaluation first:\n"
            "  uv run python evaluation/run_eval.py --out results"
        )
    result = export_all(args.report, args.out)
    print(f"Wrote tables to {result['out_dir']}")
    for p in result["tables"].values():
        print(f"  - {p}")
    print("Figures:")
    for p in result["figures"]:
        print(f"  - {p}")


if __name__ == "__main__":
    main()
