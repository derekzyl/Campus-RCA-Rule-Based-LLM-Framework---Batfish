from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

import yaml

from campus_rca.batfish_client import BatfishClient
from campus_rca.config import Settings, get_settings
from campus_rca.llm import get_llm_backend
from campus_rca.models import EvidenceBundle, ProbeSpec, RCAResult, RuleDiagnosis
from campus_rca.rules import RuleEngine


def load_scenarios(path: Path | str | None = None) -> dict[str, Any]:
    settings = get_settings()
    path = Path(path) if path else settings.project_root / "ground_truth" / "scenarios.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


class RCAPipeline:
    """Runs rule_only, llm_only, or hybrid diagnosis for a scenario."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.batfish = BatfishClient(self.settings)
        self.rules = RuleEngine()
        self.llm = get_llm_backend(self.settings)

    def collect(
        self,
        scenario_id: str,
        snapshot_dir: Path | str,
        probe: ProbeSpec,
        symptom: str = "",
    ) -> EvidenceBundle:
        baseline = self.settings.project_root / "configs" / "baseline"
        cache = self.settings.project_root / "data" / "evidence_cache"
        return self.batfish.collect_evidence(
            scenario_id=scenario_id,
            snapshot_dir=snapshot_dir,
            probe=probe,
            symptom=symptom,
            baseline_dir=baseline,
            cache_dir=cache,
        )

    def run(
        self,
        mode: str,
        scenario_id: str,
        symptom: str,
        snapshot_dir: Path | str,
        probe: ProbeSpec,
        evidence: EvidenceBundle | None = None,
    ) -> RCAResult:
        t0 = time.perf_counter()
        evidence = evidence or self.collect(scenario_id, snapshot_dir, probe, symptom)

        rule_diag: RuleDiagnosis | None = None
        llm_diag = None
        notes: list[str] = []

        if mode in {"rule_only", "hybrid"}:
            rule_diag = self.rules.diagnose(evidence)

        if mode == "rule_only":
            primary = rule_diag.primary if rule_diag else None
            result = RCAResult(
                mode=mode,
                scenario_id=scenario_id,
                symptom=symptom,
                evidence=evidence,
                rule_diagnosis=rule_diag,
                final_fault_type=(primary.fault_type.value if primary else "unknown"),
                final_device=primary.device if primary else None,
                final_explanation=(primary.rationale if primary else "No rule matched"),
                remediation=(
                    [
                        f"Inspect {primary.device}:{primary.object}",
                        "Validate against baseline snapshot",
                    ]
                    if primary
                    else []
                ),
            )
        elif mode == "llm_only":
            llm_diag = self.llm.diagnose_llm_only(symptom, evidence)
            result = RCAResult(
                mode=mode,
                scenario_id=scenario_id,
                symptom=symptom,
                evidence=evidence,
                llm_diagnosis=llm_diag,
                final_fault_type=llm_diag.fault_type,
                final_device=llm_diag.device,
                final_explanation=llm_diag.explanation,
                remediation=llm_diag.remediation,
                notes=["LLM-only: not constrained by rule validation layer"],
            )
        elif mode == "hybrid":
            if rule_diag is None:
                rule_diag = self.rules.diagnose(evidence)
            llm_diag = self.llm.explain_hybrid(symptom, evidence, rule_diag)
            primary = rule_diag.primary
            # Rules are authoritative for classification; LLM for explanation
            result = RCAResult(
                mode=mode,
                scenario_id=scenario_id,
                symptom=symptom,
                evidence=evidence,
                rule_diagnosis=rule_diag,
                llm_diagnosis=llm_diag,
                final_fault_type=(primary.fault_type.value if primary else llm_diag.fault_type),
                final_device=(primary.device if primary else llm_diag.device),
                final_explanation=llm_diag.explanation or (primary.rationale if primary else ""),
                remediation=llm_diag.remediation,
                notes=[
                    "Hybrid: rules decide fault class; LLM explains using validated evidence only",
                    f"evidence_source={evidence.source}",
                ],
            )
            if llm_diag.hallucinated_claims:
                notes.extend(llm_diag.hallucinated_claims)
                result.notes.extend(notes)
        else:
            raise ValueError(f"Unknown mode: {mode}")

        result.elapsed_ms = (time.perf_counter() - t0) * 1000
        return result

    def run_scenario(self, scenario: dict[str, Any], mode: str) -> RCAResult:
        probe = ProbeSpec(**scenario["probe"])
        return self.run(
            mode=mode,
            scenario_id=scenario["id"],
            symptom=scenario["symptom"],
            snapshot_dir=scenario["snapshot_dir"],
            probe=probe,
        )
