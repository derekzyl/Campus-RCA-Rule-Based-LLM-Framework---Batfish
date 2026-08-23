from __future__ import annotations

import re
from typing import Any

from campus_rca.campus_policy import (
    PREFIX_OWNER,
    is_bad_default_nexthop,
    match_campus_acl,
    prefix_for_ip,
)
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

DEVICE_RE = (
    r"\b(campus_r1|campus_r2|fw1|fw2|core_sw1|core_sw2|"
    r"dsw_a_admin|dsw_a_acad|dsw_b_lib|dsw_b_student|dsw_c_lab|"
    r"dsw_d_dc|dsw_d_media|dsw_dmz|core1|dist1|dist2|border1)\b"
)


def iface_parts(row: dict[str, Any]) -> tuple[Any, str]:
    iface = row.get("Interface")
    if isinstance(iface, dict):
        return iface.get("hostname"), str(iface.get("interface") or "")
    return None, str(iface or "")


def is_virtual_iface(name: str) -> bool:
    n = (name or "").lower().replace(" ", "")
    return n.startswith(("vlan", "loopback", "null"))


def is_spurious_inactive(row: dict[str, Any]) -> bool:
    """Batfish often marks SVIs (and unused ports) Active=false without a shutdown."""
    admin = row.get("Admin_Up")
    active = row.get("Active")
    looks_down = active is False or admin is False
    if not looks_down:
        return False
    _, iname = iface_parts(row)
    if is_virtual_iface(iname):
        return admin is not False
    if active is False and admin is not False:
        has_addr = bool(row.get("Primary_Address"))
        desc = str(row.get("Description") or "").strip()
        return not (has_addr or desc)
    return False


def _s(obj: Any) -> str:
    return str(obj).lower() if obj is not None else ""


def _blob(evidence: EvidenceBundle) -> str:
    return evidence.model_dump_json().lower()


def _is_router(node: Any) -> bool:
    return _s(node) in ROUTER_NODES


def _prefix_for_ip(ip: str) -> str | None:
    return prefix_for_ip(ip)


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
        """R1 — only documented DENY ACEs for this probe (not implicit deny on other ACLs)."""
        hit = match_campus_acl(evidence.probe)
        if not hit:
            return []
        return [
            RuleHit(
                rule_id="R1_ACL_DENY",
                fault_type=FaultType.ACL_DENY,
                confidence=0.94,
                device=hit["device"],
                object=hit["filter"],
                layer="policy",
                rationale=hit["rationale"],
                evidence_refs=["acl_trace", "reachability", "campus_policy"],
            )
        ]

    def _rule_interface_down(self, evidence: EvidenceBundle, blob: str) -> list[RuleHit]:
        hits = []
        for row in evidence.interfaces:
            hostname, iname = iface_parts(row)
            if hostname is not None and not _is_router(hostname):
                continue
            admin_down = row.get("Admin_Up") is False
            oper_down = row.get("Active") is False
            shutdown_in_desc = "shutdown" in _s(row.get("Description"))
            if is_spurious_inactive(row) and not shutdown_in_desc:
                continue
            if not (admin_down or oper_down or shutdown_in_desc):
                continue
            if admin_down and not is_virtual_iface(iname):
                confidence = 0.96
            elif admin_down:
                confidence = 0.86
            else:
                confidence = 0.88
            hits.append(
                RuleHit(
                    rule_id="R2_INTERFACE_DOWN",
                    fault_type=FaultType.INTERFACE_DOWN,
                    confidence=confidence,
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
                if is_bad_default_nexthop(nh):
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
        if match_campus_acl(evidence.probe):
            return []
        no_route = "no_route" in blob or any(
            "no_route" in _s(r) for r in evidence.traceroute + evidence.reachability
        )
        unreachable = no_route or any(
            "unreachable" in _s(r) or "no_route" in _s(r) for r in evidence.reachability
        )
        dst = evidence.probe.dst_ip
        target_prefix = _prefix_for_ip(dst)
        owner = PREFIX_OWNER.get(target_prefix or "", None)

        if target_prefix:
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

        if (no_route or unreachable) and not hits:
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
        if match_campus_acl(evidence.probe):
            return []
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
