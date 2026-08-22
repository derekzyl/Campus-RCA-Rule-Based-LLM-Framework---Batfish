from __future__ import annotations

import json
from typing import Any

from campus_rca.models import EvidenceBundle, RuleDiagnosis
from campus_rca.rules.engine import is_spurious_inactive

SYSTEM_PROMPT = """Reply with JSON only (no markdown, no extra keys):
{"root_cause":"short","fault_type":"acl_deny","device":"core_sw1","confidence":0.9,"explanation":"one sentence","evidence_used":["acl_trace"],"remediation":["step"],"uncertainties":[]}
fault_type must be one of: acl_deny, missing_route, interface_down, wrong_static_route, ospf_neighbor, unknown.
device must be a hostname from evidence (core_sw1, dsw_b_student, campus_r1, fw1, …) or JSON null.
Fill every field. Ground claims in evidence only."""


def compact_evidence(evidence: EvidenceBundle, max_routes: int = 6) -> dict[str, Any]:
    """Aggressively shrink Batfish evidence for CPU-bound local LLMs."""
    routers = {
        "campus_r1",
        "campus_r2",
        "fw1",
        "fw2",
        "core_sw1",
        "core_sw2",
        "dsw_a_admin",
        "dsw_a_acad",
        "dsw_b_lib",
        "dsw_b_student",
        "dsw_c_lab",
        "dsw_d_dc",
        "dsw_d_media",
        "dsw_dmz",
    }
    interesting = [
        i
        for i in evidence.interfaces
        if (
            isinstance(i.get("Interface"), dict)
            and i["Interface"].get("hostname") in routers
        )
        and not is_spurious_inactive(i)
        and (
            i.get("Active") is False
            or i.get("Admin_Up") is False
            or i.get("Incoming_Filter_Name")
            or i.get("Outgoing_Filter_Name")
        )
    ][:4]
    # Prefer router routes; skip host default-gateway noise
    router_routes = [r for r in evidence.routes if str(r.get("Node", "")).lower() in routers]
    routes = (router_routes or evidence.routes)[:max_routes]
    return {
        "symptom": evidence.symptom,
        "probe": f"{evidence.probe.src_ip}->{evidence.probe.dst_ip}:{evidence.probe.dst_port or '*'}/{evidence.probe.ip_protocol}",
        "reachability": [
            {k: v for k, v in r.items() if k in ("Result", "Disposition", "Flow")}
            for r in evidence.reachability[:3]
        ],
        "traceroute": [
            {k: v for k, v in r.items() if k in ("Flow", "Traces")}
            for r in evidence.traceroute[:2]
        ],
        "acl_trace": [
            {k: v for k, v in r.items() if k in ("Node", "Filter_Name", "Action", "Flow")}
            for r in evidence.acl_trace[:4]
        ],
        "routes": routes,
        "interfaces": interesting or [
            i
            for i in evidence.interfaces
            if isinstance(i.get("Interface"), dict)
            and i["Interface"].get("hostname") in routers
            and not is_spurious_inactive(i)
        ][:3],
    }


def compact_rules(rules: RuleDiagnosis) -> dict[str, Any]:
    return {
        "primary": rules.primary.model_dump() if rules.primary else None,
        "candidates": [c.model_dump() for c in rules.candidates[:3]],
    }


def build_hybrid_user_prompt(symptom: str, evidence_json: str, rule_json: str) -> str:
    return f"""Symptom: {symptom}
Rule diagnosis: {rule_json}
Evidence: {evidence_json}
Explain the diagnosis briefly. JSON only."""


def build_llm_only_user_prompt(symptom: str, evidence_json: str) -> str:
    return f"""Symptom: {symptom}
Evidence: {evidence_json}
Identify root cause. JSON only."""


def evidence_to_prompt_json(evidence: EvidenceBundle) -> str:
    return json.dumps(compact_evidence(evidence), indent=2)


def rules_to_prompt_json(rules: RuleDiagnosis) -> str:
    return json.dumps(compact_rules(rules), indent=2)
