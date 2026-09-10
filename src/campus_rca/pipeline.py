from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

import yaml

from campus_rca.batfish_client import BatfishClient
from campus_rca.config import Settings, get_settings
from campus_rca.llm import get_llm_backend
from campus_rca.models import EvidenceBundle, ProbeSpec, RCAResult, RuleDiagnosis, RuleHit
from campus_rca.rules import RuleEngine


def load_scenarios(path: Path | str | None = None) -> dict[str, Any]:
    settings = get_settings()
    path = Path(path) if path else settings.project_root / "ground_truth" / "scenarios.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def default_remediation(
    *,
    fault_type: str | None,
    device: str | None,
    obj: str | None = None,
) -> list[str]:
    """Advisory steps shown to the operator; never applied automatically."""
    loc = f"{device}:{obj}" if device and obj else (device or "the implicated device")
    ft = (fault_type or "unknown").lower()
    if ft == "acl_deny":
        return [
            f"Review ACL {obj or 'filter'} inbound on {device or 'the core/firewall'} (do not apply changes without approval).",
            "Confirm the deny ACE matches the probe 5-tuple, then verify with show access-lists / testFilters.",
            "Compare against the baseline snapshot before any policy edit.",
        ]
    if ft == "interface_down":
        return [
            f"Check interface {obj or 'status'} on {device or loc} (show ip interface brief).",
            "If administratively down, restore with no shutdown only after human approval.",
            "Validate against the baseline snapshot.",
        ]
    if ft == "wrong_static_route":
        return [
            f"Inspect the default static route on {device or 'the head router'} (show ip route 0.0.0.0).",
            "Next-hop must be the ISP handoff (20.20.20.x / 30.30.30.x), not a campus LAN address.",
            "Correct ip route 0.0.0.0 0.0.0.0 <ISP-NEXT-HOP> only after human approval.",
        ]
    if ft in {"missing_route", "ospf_neighbor"}:
        return [
            f"On {device or loc}, confirm the VLAN prefix is in router ospf 1 network statements.",
            "Check OSPF adjacency (show ip ospf neighbor) toward the cores.",
            "Compare against the baseline snapshot before adding a network statement.",
        ]
    return [
        f"Inspect {loc}",
        "Validate against baseline snapshot",
    ]


def _from_rule(primary: RuleHit | None) -> list[str]:
    if not primary:
        return []
    return default_remediation(
        fault_type=primary.fault_type.value,
        device=primary.device,
        obj=primary.object,
    )


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
                remediation=_from_rule(primary),
            )
        elif mode == "llm_only":
            llm_diag = self.llm.diagnose_llm_only(symptom, evidence)
            if not llm_diag.remediation:
                llm_diag.remediation = default_remediation(
                    fault_type=llm_diag.fault_type,
                    device=llm_diag.device,
                )
            result = RCAResult(
                mode=mode,
                scenario_id=scenario_id,
                symptom=symptom,
                evidence=evidence,
                llm_diagnosis=llm_diag,
                final_fault_type=llm_diag.fault_type,
                final_device=llm_diag.device,
                final_explanation=llm_diag.explanation,
                remediation=list(llm_diag.remediation),
                notes=["LLM-only: not constrained by rule validation layer"],
            )
        elif mode == "hybrid":
            if rule_diag is None:
                rule_diag = self.rules.diagnose(evidence)
            llm_diag = self.llm.explain_hybrid(symptom, evidence, rule_diag)
            primary = rule_diag.primary
            if not llm_diag.remediation:
                llm_diag.remediation = _from_rule(primary)
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
                remediation=list(llm_diag.remediation),
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
