from __future__ import annotations

import re
from typing import Any

from campus_rca.models import EvidenceBundle, FaultType, RuleDiagnosis, RuleHit


# Infrastructure / distribution nodes (exclude Batfish host endpoints).
ROUTER_NODES = frozenset(
    {
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
        # legacy names kept for older caches
        "core1",
        "dist1",
        "dist2",
        "border1",
    }
)

# Prefix ownership for missing-route localisation
PREFIX_OWNER = {
    "192.168.30.0/24": "dsw_b_student",
    "192.168.20.0/24": "dsw_a_acad",
    "192.168.11.0/24": "dsw_a_admin",
    "192.168.12.0/24": "dsw_a_acad",
    "192.168.40.0/24": "dsw_c_lab",
    "192.168.50.0/24": "dsw_b_lib",
    "192.168.80.0/24": "dsw_d_dc",
    "192.168.90.0/24": "dsw_d_dc",
    "11.10.65.0/24": "dsw_b_student",
    "12.20.20.0/26": "fw1",
}

DEVICE_RE = (
    r"\b(campus_r1|campus_r2|fw1|fw2|core_sw1|core_sw2|"
    r"dsw_a_admin|dsw_a_acad|dsw_b_lib|dsw_b_student|dsw_c_lab|"
    r"dsw_d_dc|dsw_d_media|dsw_dmz|core1|dist1|dist2|border1)\b"
)


def _s(obj: Any) -> str:
    return str(obj).lower() if obj is not None else ""


def _blob(evidence: EvidenceBundle) -> str:
    return evidence.model_dump_json().lower()


def _is_router(node: Any) -> bool:
    return _s(node) in ROUTER_NODES


def _prefix_for_ip(ip: str) -> str | None:
    if ip.startswith("192.168.30."):
        return "192.168.30.0/24"
    if ip.startswith("192.168.20."):
        return "192.168.20.0/24"
    if ip.startswith("192.168.11."):
        return "192.168.11.0/24"
    if ip.startswith("192.168.12."):
        return "192.168.12.0/24"
    if ip.startswith("192.168.40."):
        return "192.168.40.0/24"
    if ip.startswith("192.168.50."):
        return "192.168.50.0/24"
    if ip.startswith("192.168.80."):
        return "192.168.80.0/24"
    if ip.startswith("192.168.90."):
        return "192.168.90.0/24"
    if ip.startswith("11.10.65."):
        return "11.10.65.0/24"
    if ip.startswith("12.20.20."):
        return "12.20.20.0/26"
    if ip.startswith("10.10.10."):
        return "10.10.10.0/24"
    if ip.startswith("10.20.20."):
        return "10.20.20.0/24"
    return None


class RuleEngine:
    """Deterministic diagnostic rules over Batfish campus evidence."""

    def diagnose(self, evidence: EvidenceBundle) -> RuleDiagnosis:
        hits: list[RuleHit] = []
        blob = _blob(evidence)

        hits.extend(self._rule_acl_deny(evidence, blob))
        hits.extend(self._rule_interface_down(evidence, blob))
        hits.extend(self._rule_wrong_static(evidence, blob))
        hits.extend(self._rule_missing_route(evidence, blob))
        hits.extend(self._rule_ospf_neighbor(evidence, blob))
        hits.extend(self._rule_reachability_ok(evidence, blob))

        hits.sort(key=lambda h: h.confidence, reverse=True)
        primary = hits[0] if hits else None
        unmatched = []
        if not hits:
            unmatched.append("No rule matched the collected evidence")
        return RuleDiagnosis(primary=primary, candidates=hits, unmatched_evidence=unmatched)

    def _rule_acl_deny(self, evidence: EvidenceBundle, blob: str) -> list[RuleHit]:
        hits = []
        denied = any(
            "denied" in _s(r) or "deny" in _s(r.get("Action") if isinstance(r, dict) else r)
            for r in (evidence.acl_trace + evidence.reachability + evidence.traceroute)
        )
        filter_name = None
        device = None
        for row in evidence.acl_trace:
            if "deny" in _s(row.get("Action")):
                filter_name = row.get("Filter_Name") or row.get("Filter")
                device = row.get("Node")
                break
        if not device:
            for row in evidence.interfaces:
                filt = row.get("Incoming_Filter_Name") or row.get("Outgoing_Filter_Name")
                if filt:
                    iface = row.get("Interface")
                    if isinstance(iface, dict):
                        device = iface.get("hostname")
                    filter_name = filt
                    break
        if denied or ("denied_in" in blob or "denied_out" in blob):
            hits.append(
                RuleHit(
                    rule_id="R1_ACL_DENY",
                    fault_type=FaultType.ACL_DENY,
                    confidence=0.92 if denied else 0.75,
                    device=device
                    or self._guess_device(
                        blob, ["core_sw1", "fw1", "dsw_b_student", "core_sw2", "dist2"]
                    ),
                    object=str(filter_name) if filter_name else "ACL",
                    layer="policy",
                    rationale=(
                        "Reachability/traceroute disposition indicates ACL drop "
                        f"(filter={filter_name}). Routing evidence may still show a path."
                    ),
                    evidence_refs=["acl_trace", "reachability", "traceroute"],
                )
            )
        return hits

    def _rule_interface_down(self, evidence: EvidenceBundle, blob: str) -> list[RuleHit]:
        hits = []
        for row in evidence.interfaces:
            active = row.get("Active")
            admin = row.get("Admin_Up")
            iface = row.get("Interface")
            hostname = iface.get("hostname") if isinstance(iface, dict) else None
            iname = iface.get("interface") if isinstance(iface, dict) else str(iface)
            down = active is False or admin is False or "shutdown" in _s(row.get("Description"))
            if down and (hostname is None or _is_router(hostname)):
                hits.append(
                    RuleHit(
                        rule_id="R2_INTERFACE_DOWN",
                        fault_type=FaultType.INTERFACE_DOWN,
                        confidence=0.95,
                        device=hostname,
                        object=iname,
                        layer="interface",
                        rationale=f"Interface {iname} on {hostname} is administratively/operationally down.",
                        evidence_refs=["interfaces"],
                    )
                )
        return hits

    def _rule_wrong_static(self, evidence: EvidenceBundle, blob: str) -> list[RuleHit]:
        hits = []
        for row in evidence.routes:
            node = row.get("Node")
            if not _is_router(node):
                continue
            net = _s(row.get("Network"))
            proto = _s(row.get("Protocol"))
            nh = _s(row.get("Next_Hop_IP") or row.get("Next_Hop"))
            if net in {"0.0.0.0/0", "default"} and "static" in proto:
                # Wrong if next-hop is inside campus LAN / WLAN ranges
                bad = (
                    nh.startswith("192.168.")
                    or nh.startswith("10.10.")
                    or nh.startswith("10.20.")
                    or nh.startswith("11.10.")
                )
                if bad:
                    hits.append(
                        RuleHit(
                            rule_id="R3_WRONG_STATIC",
                            fault_type=FaultType.WRONG_STATIC_ROUTE,
                            confidence=0.93,
                            device=str(node),
                            object=str(row.get("Network")),
                            layer="routing",
                            rationale=(
                                f"Default static route next-hop {nh} points into a campus LAN "
                                "instead of the ISP / edge handoff."
                            ),
                            evidence_refs=["routes", "reachability"],
                        )
                    )
        return hits

    def _rule_missing_route(self, evidence: EvidenceBundle, blob: str) -> list[RuleHit]:
        hits = []
        no_route = "no_route" in blob or any(
            "no_route" in _s(r) for r in evidence.traceroute + evidence.reachability
        )
        dst = evidence.probe.dst_ip
        target_prefix = _prefix_for_ip(dst)
        owner = PREFIX_OWNER.get(target_prefix or "", None)

        if target_prefix and no_route:
            appears_on_cores = any(
                target_prefix in str(r.get("Network"))
                and str(r.get("Node")).lower() in {"core_sw1", "core_sw2", "core1"}
                for r in evidence.routes
            )
            locally_present = any(
                target_prefix in str(r.get("Network"))
                and str(r.get("Node")).lower() == (owner or "").lower()
                for r in evidence.routes
            ) or any(
                target_prefix.split("/")[0].rsplit(".", 1)[0]
                in _s(i.get("Primary_Address"))
                for i in evidence.interfaces
            )
            if not appears_on_cores:
                hits.append(
                    RuleHit(
                        rule_id="R4_MISSING_ROUTE",
                        fault_type=FaultType.MISSING_ROUTE,
                        confidence=0.9 if locally_present or owner else 0.7,
                        device=owner,
                        object=target_prefix,
                        layer="routing",
                        rationale=(
                            f"No OSPF route to {target_prefix} at core; likely missing network "
                            f"statement / advertisement on {owner or 'distribution block'}."
                        ),
                        evidence_refs=["routes", "traceroute", "interfaces"],
                    )
                )

        if no_route and not hits:
            hits.append(
                RuleHit(
                    rule_id="R4_MISSING_ROUTE_GENERIC",
                    fault_type=FaultType.MISSING_ROUTE,
                    confidence=0.6,
                    device=owner,
                    object=target_prefix or evidence.probe.dst_ip,
                    layer="routing",
                    rationale="Traceroute/reachability shows NO_ROUTE without ACL deny evidence.",
                    evidence_refs=["traceroute", "reachability"],
                )
            )
        return hits

    def _rule_ospf_neighbor(self, evidence: EvidenceBundle, blob: str) -> list[RuleHit]:
        hits = []
        for issue in evidence.init_issues:
            text = _s(issue)
            if "ospf" in text and ("neighbor" in text or "adjacency" in text):
                hits.append(
                    RuleHit(
                        rule_id="R5_OSPF_NEIGHBOR",
                        fault_type=FaultType.OSPF_NEIGHBOR,
                        confidence=0.8,
                        device=self._extract_node(text),
                        object="OSPF adjacency",
                        layer="routing",
                        rationale=f"Batfish init/OSPF issue detected: {issue}",
                        evidence_refs=["init_issues"],
                    )
                )
        return hits

    def _rule_reachability_ok(self, evidence: EvidenceBundle, blob: str) -> list[RuleHit]:
        if any(_s(r.get("Action")) in {"deny", "denied"} for r in evidence.acl_trace):
            return []
        if any(
            tok in blob
            for tok in ("denied_in", "denied_out", "unreachable", "no_route", "null_routed")
        ):
            return []
        if any(
            "accepted" in _s(r) or _s(r.get("Result")) == "reachable"
            for r in evidence.reachability
        ):
            return [
                RuleHit(
                    rule_id="R0_OK",
                    fault_type=FaultType.REACHABILITY_OK,
                    confidence=0.85,
                    device=None,
                    object=None,
                    layer="dataplane",
                    rationale="Probe flow is reachable under current snapshot.",
                    evidence_refs=["reachability"],
                )
            ]
        return []

    @staticmethod
    def _guess_device(blob: str, candidates: list[str]) -> str | None:
        for c in candidates:
            if c.lower() in blob:
                return c
        return None

    @staticmethod
    def _extract_node(text: str) -> str | None:
        m = re.search(DEVICE_RE, text, flags=re.IGNORECASE)
        return m.group(1).lower() if m else None
