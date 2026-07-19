from __future__ import annotations

import json
from typing import Any

from campus_rca.models import EvidenceBundle, RuleDiagnosis

SYSTEM_PROMPT = """You are a campus network root-cause analysis assistant.
You MUST ground every claim in the provided evidence.
You MUST NOT invent devices, ACLs, routes, or traceroute hops that are absent from the evidence.
If evidence is incomplete, state uncertainty explicitly.
Temperature is fixed at 0 for reproducibility.
Respond ONLY with valid JSON matching this schema:
{
  "root_cause": "one sentence",
  "fault_type": "acl_deny|missing_route|interface_down|wrong_static_route|ospf_neighbor|unknown",
  "device": "hostname or null",
  "confidence": 0.0-1.0,
  "explanation": "operator-readable explanation tied to evidence",
  "evidence_used": ["short refs"],
  "remediation": ["read-only recommended checks/fixes — do not claim changes were applied"],
  "uncertainties": ["optional"]
}
"""


def compact_evidence(evidence: EvidenceBundle, max_routes: int = 12) -> dict[str, Any]:
    """Shrink Batfish evidence for local LLM context windows / CPU latency."""
    interesting = [
        i
        for i in evidence.interfaces
        if i.get("Active") is False
        or i.get("Admin_Up") is False
        or i.get("Incoming_Filter_Name")
        or i.get("Outgoing_Filter_Name")
    ][:8]
    return {
        "scenario_id": evidence.scenario_id,
        "source": evidence.source,
        "symptom": evidence.symptom,
        "probe": evidence.probe.model_dump(),
        "reachability": evidence.reachability[:5],
        "traceroute": evidence.traceroute[:5],
        "acl_trace": evidence.acl_trace[:8],
        "routes": evidence.routes[:max_routes],
        "interfaces": interesting or evidence.interfaces[:6],
        "init_issues": evidence.init_issues[:5],
    }


def compact_rules(rules: RuleDiagnosis) -> dict[str, Any]:
    return {
        "primary": rules.primary.model_dump() if rules.primary else None,
        "candidates": [c.model_dump() for c in rules.candidates[:3]],
    }


def build_hybrid_user_prompt(symptom: str, evidence_json: str, rule_json: str) -> str:
    return f"""Incident symptom:
{symptom}

Validated rule-based diagnosis (authoritative for fault classification):
{rule_json}

Batfish-derived evidence (authoritative facts; do not contradict):
{evidence_json}

Task:
1) Explain the rule diagnosis in clear operator language.
2) Rank likely causes if multiple rule candidates exist, but do not invent new root causes outside the evidence.
3) Provide practical remediation steps that a human administrator must approve.
Return JSON only.
"""


def build_llm_only_user_prompt(symptom: str, evidence_json: str) -> str:
    return f"""Incident symptom:
{symptom}

Optional raw evidence (may be incomplete or noisy):
{evidence_json}

Task: Infer the most likely root cause for this campus routing/ACL failure.
Return JSON only. Prefer concrete device/object names when present in evidence.
"""


def evidence_to_prompt_json(evidence: EvidenceBundle) -> str:
    return json.dumps(compact_evidence(evidence), indent=2)


def rules_to_prompt_json(rules: RuleDiagnosis) -> str:
    return json.dumps(compact_rules(rules), indent=2)
