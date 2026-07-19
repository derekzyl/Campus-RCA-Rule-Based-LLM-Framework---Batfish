from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from campus_rca.models import RCAResult


def localisation_correct(result: RCAResult, ground_truth: dict[str, Any]) -> bool:
    gt_type = ground_truth["fault_type"]
    gt_device = (ground_truth.get("device") or "").lower()
    pred_type = (result.final_fault_type or "").lower()
    pred_device = (result.final_device or "").lower()
    type_ok = pred_type == gt_type
    device_ok = (not gt_device) or (pred_device == gt_device)
    return type_ok and device_ok


def keyword_coverage(result: RCAResult, ground_truth: dict[str, Any]) -> float:
    keywords = [k.lower() for k in ground_truth.get("keywords", [])]
    if not keywords:
        return 1.0
    text = f"{result.final_explanation} {result.final_device} {result.final_fault_type}".lower()
    hits = sum(1 for k in keywords if k.lower() in text)
    return hits / len(keywords)


def hallucination_rate(result: RCAResult) -> float:
    if result.llm_diagnosis is None:
        return 0.0
    claims = result.llm_diagnosis.hallucinated_claims
    # Normalize loosely: each claim counts; cap at 1.0
    return min(1.0, len(claims) / 3.0)


def evidence_faithfulness(result: RCAResult) -> float:
    """Fraction of LLM-cited evidence refs that exist in the evidence bundle."""
    if result.llm_diagnosis is None:
        return 1.0 if result.rule_diagnosis and result.rule_diagnosis.primary else 0.0
    used = result.llm_diagnosis.evidence_used
    if not used:
        return 0.5
    keys = set(result.evidence.model_dump().keys())
    ok = 0
    for ref in used:
        r = ref.lower()
        if r in keys or r in {"rule_primary", "symptom", "reachability", "routes", "acl_trace", "traceroute", "interfaces"}:
            ok += 1
        elif r in result.evidence.model_dump_json().lower():
            ok += 1
    return ok / len(used)


def score_row(result: RCAResult, ground_truth: dict[str, Any]) -> dict[str, Any]:
    return {
        "scenario_id": result.scenario_id,
        "mode": result.mode,
        "predicted_fault": result.final_fault_type,
        "predicted_device": result.final_device,
        "truth_fault": ground_truth["fault_type"],
        "truth_device": ground_truth.get("device"),
        "localisation_correct": localisation_correct(result, ground_truth),
        "keyword_coverage": round(keyword_coverage(result, ground_truth), 3),
        "hallucination_rate": round(hallucination_rate(result), 3),
        "evidence_faithfulness": round(evidence_faithfulness(result), 3),
        "elapsed_ms": round(result.elapsed_ms, 1),
        "explanation": result.final_explanation,
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_mode: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_mode.setdefault(r["mode"], []).append(r)

    summary = {}
    for mode, items in by_mode.items():
        n = len(items)
        summary[mode] = {
            "n": n,
            "accuracy": round(sum(1 for i in items if i["localisation_correct"]) / n, 3),
            "avg_keyword_coverage": round(sum(i["keyword_coverage"] for i in items) / n, 3),
            "avg_hallucination_rate": round(sum(i["hallucination_rate"] for i in items) / n, 3),
            "avg_evidence_faithfulness": round(sum(i["evidence_faithfulness"] for i in items) / n, 3),
            "avg_elapsed_ms": round(sum(i["elapsed_ms"] for i in items) / n, 1),
        }
    return summary


def write_report(rows: list[dict[str, Any]], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize(rows)
    report = {"summary": summary, "rows": rows}
    path = out_dir / "evaluation_report.json"
    path.write_text(json.dumps(report, indent=2))

    md = ["# Campus RCA Evaluation Report", "", "## Summary", ""]
    md.append("| Mode | Accuracy | Keyword cov. | Hallucination | Faithfulness | Avg ms |")
    md.append("|---|---:|---:|---:|---:|---:|")
    for mode, s in summary.items():
        md.append(
            f"| {mode} | {s['accuracy']} | {s['avg_keyword_coverage']} | "
            f"{s['avg_hallucination_rate']} | {s['avg_evidence_faithfulness']} | {s['avg_elapsed_ms']} |"
        )
    md.append("")
    md.append("## Per-scenario")
    md.append("")
    for r in rows:
        mark = "OK" if r["localisation_correct"] else "MISS"
        md.append(
            f"- `{r['mode']}` / `{r['scenario_id']}` [{mark}] "
            f"pred=`{r['predicted_fault']}`@{r['predicted_device']} "
            f"truth=`{r['truth_fault']}`@{r['truth_device']}"
        )
    (out_dir / "evaluation_report.md").write_text("\n".join(md))
    return path
