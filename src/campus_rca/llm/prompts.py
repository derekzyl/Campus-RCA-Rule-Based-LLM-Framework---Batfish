from __future__ import annotations

import json
from typing import Any

from campus_rca.campus_policy import (
    PREFIX_OWNER,
    filter_acl_trace_for_probe,
    is_bad_default_nexthop,
    match_campus_acl,
    policy_cheatsheet,
    prefix_for_ip,
)
from campus_rca.models import EvidenceBundle, RuleDiagnosis
from campus_rca.rules.engine import ROUTER_NODES, iface_parts, is_spurious_inactive, is_virtual_iface

SYSTEM_PROMPT = """You are a campus network RCA assistant. Reply with JSON only (no markdown).
Put fault_type and device FIRST so a truncated reply is still usable:
{"fault_type":"acl_deny","device":"core_sw1","root_cause":"short","confidence":0.9,"explanation":"one sentence","evidence_used":["cues"],"remediation":["step"],"uncertainties":[]}
fault_type must be exactly one of: acl_deny, missing_route, interface_down, wrong_static_route, ospf_neighbor, unknown.
device must be a hostname (core_sw1, core_sw2, dsw_b_student, dsw_a_acad, dsw_d_dc, campus_r1, fw1, …) or JSON null."""


def classification_cues(evidence: EvidenceBundle) -> dict[str, Any]:
    """Batfish-derived facts for llm_only (not the rule engine's primary verdict)."""
    hit = match_campus_acl(evidence.probe)
    downs: list[dict[str, str]] = []
    for row in evidence.interfaces:
        hostname, iname = iface_parts(row)
        if not hostname or str(hostname).lower() not in ROUTER_NODES:
            continue
        if is_spurious_inactive(row):
            continue
        if row.get("Admin_Up") is False and not is_virtual_iface(iname):
            downs.append({"device": str(hostname), "iface": iname})
        if len(downs) >= 4:
            break

    bad_defaults: list[dict[str, str]] = []
    for row in evidence.routes:
        node = str(row.get("Node") or "")
        if str(node).lower() not in {"campus_r1", "campus_r2"}:
            continue
        net = str(row.get("Network") or "")
        proto = str(row.get("Protocol") or "").lower()
        nh = str(row.get("Next_Hop_IP") or row.get("Next_Hop") or "")
        if isinstance(row.get("Next_Hop"), dict):
            nh = str(row["Next_Hop"].get("ip") or nh)
        if net in {"0.0.0.0/0", "default"} and "static" in proto and is_bad_default_nexthop(nh):
            bad_defaults.append({"device": node, "next_hop": nh})

    prefix = prefix_for_ip(evidence.probe.dst_ip)
    owner = PREFIX_OWNER.get(prefix or "", None)
    at_core = False
    if prefix:
        at_core = any(
            prefix in str(r.get("Network"))
            and str(r.get("Node") or "").lower() in {"core_sw1", "core_sw2"}
            for r in evidence.routes
        )

    dispositions = []
    for row in (evidence.reachability or [])[:3]:
        d = row.get("Disposition") or row.get("Result")
        if d:
            dispositions.append(str(d))
    for row in (evidence.traceroute or [])[:2]:
        for tr in row.get("Traces") or []:
            if isinstance(tr, dict) and tr.get("disposition"):
                dispositions.append(str(tr["disposition"]))
                break

    return {
        "probe": f"{evidence.probe.src_ip}->{evidence.probe.dst_ip}:{evidence.probe.dst_port or '*'}/{evidence.probe.ip_protocol}",
        "policy_acl_hit": hit,
        "physical_admin_down": downs,
        "bad_default_nexthop": bad_defaults,
        "dst_prefix": prefix,
        "dst_prefix_owner": owner,
        "dst_prefix_at_core": at_core,
        "dispositions": dispositions[:4],
    }


def _slim_trace(row: dict[str, Any]) -> dict[str, Any]:
    traces = row.get("Traces") or []
    hops: list[str] = []
    disp = None
    for t in traces[:1]:
        if not isinstance(t, dict):
            continue
        disp = t.get("disposition")
        for h in (t.get("hops") or [])[:6]:
            if isinstance(h, dict) and h.get("node"):
                hops.append(str(h["node"]))
    flow = row.get("Flow") if isinstance(row.get("Flow"), dict) else {}
    return {
        "src": flow.get("srcIp"),
        "dst": flow.get("dstIp"),
        "disposition": disp,
        "hops": hops,
    }


def _slim_route(row: dict[str, Any]) -> dict[str, Any]:
    nh = row.get("Next_Hop_IP")
    if isinstance(row.get("Next_Hop"), dict):
        nh = row["Next_Hop"].get("ip") or nh
    return {
        "Node": row.get("Node"),
        "Network": row.get("Network"),
        "Protocol": row.get("Protocol"),
        "Next_Hop_IP": nh,
    }


def _slim_iface(row: dict[str, Any]) -> dict[str, Any]:
    hostname, iname = iface_parts(row)
    return {
        "hostname": hostname,
        "interface": iname,
        "Admin_Up": row.get("Admin_Up"),
        "Active": row.get("Active"),
        "Incoming_Filter_Name": row.get("Incoming_Filter_Name"),
    }


def compact_evidence(evidence: EvidenceBundle, max_routes: int = 4) -> dict[str, Any]:
    """Aggressively shrink Batfish evidence for LLMs (esp. local CPU models)."""
    interesting = [
        _slim_iface(i)
        for i in evidence.interfaces
        if (
            isinstance(i.get("Interface"), dict)
            and str(i["Interface"].get("hostname") or "").lower() in ROUTER_NODES
        )
        and not is_spurious_inactive(i)
        and (
            i.get("Active") is False
            or i.get("Admin_Up") is False
            or i.get("Incoming_Filter_Name")
            or i.get("Outgoing_Filter_Name")
        )
    ][:4]
    router_routes = [
        _slim_route(r)
        for r in evidence.routes
        if str(r.get("Node", "")).lower() in ROUTER_NODES
    ]
    acl_rows = filter_acl_trace_for_probe(evidence.acl_trace, evidence.probe)
    return {
        "cues": classification_cues(evidence),
        "symptom": evidence.symptom,
        "reachability_disp": [
            str(r.get("Disposition") or r.get("Result") or "")
            for r in evidence.reachability[:3]
        ],
        "traceroute": [_slim_trace(r) for r in evidence.traceroute[:1]],
        "acl_trace": [
            {k: v for k, v in r.items() if k in ("Node", "Filter_Name", "Action")}
            for r in acl_rows[:3]
        ],
        "routes": (router_routes or [_slim_route(r) for r in evidence.routes])[:max_routes],
        "interfaces": interesting,
    }


def compact_rules(rules: RuleDiagnosis) -> dict[str, Any]:
    return {
        "primary": rules.primary.model_dump() if rules.primary else None,
        "candidates": [c.model_dump() for c in rules.candidates[:3]],
    }


def build_hybrid_user_prompt(symptom: str, evidence_json: str, rule_json: str) -> str:
    return f"""{policy_cheatsheet()}
Symptom: {symptom}
Validated rule diagnosis (authoritative for fault_type and device): {rule_json}
Evidence: {evidence_json}
Explain that diagnosis briefly. JSON only. Do not contradict the rule fault_type/device.
Put fault_type and device first."""


def build_llm_only_user_prompt(symptom: str, evidence: EvidenceBundle | str) -> str:
    if isinstance(evidence, str):
        cues_block = evidence
    else:
        cues_block = json.dumps(classification_cues(evidence), indent=2)
    return f"""{policy_cheatsheet()}
Symptom: {symptom}

Cues (Batfish + campus ACL notes — classify from these, not from guesswork):
{cues_block}

Decision order (stop at the first match):
1. If policy_acl_hit is not null → fault_type=acl_deny, device=policy_acl_hit.device
2. Else if physical_admin_down is not empty → fault_type=interface_down, device=that hostname
3. Else if bad_default_nexthop is not empty → fault_type=wrong_static_route, device=that router
4. Else if dst_prefix_at_core is false → fault_type=missing_route, device=dst_prefix_owner

JSON only. First keys MUST be "fault_type" then "device"."""


def evidence_to_prompt_json(evidence: EvidenceBundle) -> str:
    return json.dumps(compact_evidence(evidence), indent=2)


def rules_to_prompt_json(rules: RuleDiagnosis) -> str:
    return json.dumps(compact_rules(rules), indent=2)
