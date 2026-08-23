"""Campus dataplane policy taken from the Packet Tracer lab notes.

Source artefacts (docs/topology/):
  ACL CONFIGURATIONS.txt
  VLANS IP  ADDRESS AND GATEWAY.txt
  ROUTERS, FW, CORE-SW CONFIG.txt

Rules consume *documented DENY ACEs* for the probe 5-tuple. Batfish testFilters
also evaluates unrelated ACLs (implicit deny at the end of GUEST-WLAN-FILTER /
DMZ-IN), which must not be treated as the injected fault.
"""

from __future__ import annotations

from ipaddress import ip_address, ip_network
from typing import Any, Optional

from campus_rca.models import ProbeSpec

# Documented internal DNS host (ACL permit). DHCP helpers are .10/.11.
DNS_HOST = "192.168.80.13"

# Valid ISP default next-hops on campus_r1 / campus_r2 (ACL CONFIGURATIONS.txt).
ISP_NEXTHOPS = frozenset(
    {
        "20.20.20.2",
        "20.20.20.6",
        "30.30.30.2",
        "30.30.30.6",
    }
)

# VLAN → prefix (SVI / HSRP .1). Cores own SVIs; DSWs advertise in the RCA lab.
VLANS: dict[int, dict[str, str]] = {
    10: {"name": "MANAGEMENT", "prefix": "192.168.10.0/24", "owner": "core_sw1"},
    11: {"name": "ADMIN-HR", "prefix": "192.168.11.0/24", "owner": "dsw_a_admin"},
    12: {"name": "IT-STAFF", "prefix": "192.168.12.0/24", "owner": "dsw_a_acad"},
    20: {"name": "ACADEMIC-STAFF", "prefix": "192.168.20.0/24", "owner": "dsw_a_acad"},
    30: {"name": "STUDENTS", "prefix": "192.168.30.0/24", "owner": "dsw_b_student"},
    40: {"name": "COMPUTER-LAB", "prefix": "192.168.40.0/24", "owner": "dsw_c_lab"},
    50: {"name": "LIBRARY-SPORT", "prefix": "192.168.50.0/24", "owner": "dsw_b_lib"},
    55: {"name": "STAFF-WLAN", "prefix": "11.10.55.0/24", "owner": "dsw_b_student"},
    60: {"name": "STUDENT-WLAN", "prefix": "11.10.60.0/24", "owner": "dsw_b_student"},
    65: {"name": "GUEST-WLAN", "prefix": "11.10.65.0/24", "owner": "dsw_b_student"},
    70: {"name": "VOIP", "prefix": "192.168.70.0/24", "owner": "dsw_a_admin"},
    75: {"name": "PRINTER-IOT", "prefix": "192.168.75.0/24", "owner": "dsw_a_admin"},
    80: {"name": "NETWORK-SERVICES", "prefix": "192.168.80.0/24", "owner": "dsw_d_dc"},
    90: {"name": "INTERNAL-SERVERS", "prefix": "192.168.90.0/24", "owner": "dsw_d_dc"},
}

PREFIX_OWNER = {v["prefix"]: v["owner"] for v in VLANS.values()}
PREFIX_OWNER["12.20.20.0/26"] = "fw1"

# Named dataplane ACLs (not VTY ACL 1).
ACL_DEVICES = {
    "STUDENT-FILTER": ("core_sw1", "core_sw2"),
    "GUEST-WLAN-FILTER": ("core_sw1", "core_sw2"),
    "DMZ-IN": ("fw1",),
}


def in_net(ip: str, cidr: str) -> bool:
    try:
        return ip_address(ip) in ip_network(cidr, strict=False)
    except ValueError:
        return False


def prefix_for_ip(ip: str) -> str | None:
    try:
        addr = ip_address(ip)
    except ValueError:
        return None
    for meta in VLANS.values():
        if addr in ip_network(meta["prefix"], strict=False):
            return meta["prefix"]
    if addr in ip_network("12.20.20.0/26", strict=False):
        return "12.20.20.0/26"
    return None


def is_dns_probe(probe: ProbeSpec) -> bool:
    if probe.dst_port == 53:
        return True
    apps = [str(a).lower() for a in (probe.applications or [])]
    return "dns" in apps


def match_campus_acl(probe: ProbeSpec) -> Optional[dict[str, str]]:
    """If the probe hits a *documented deny ACE*, return filter/device/rationale.

    Implicit deny on an unrelated ACL (e.g. GUEST-WLAN-FILTER vs a student flow)
    is ignored.
    """
    src, dst = probe.src_ip, probe.dst_ip

    # STUDENT-FILTER in on VLAN 30, both cores (eval localises to core_sw1).
    if in_net(src, "192.168.30.0/24"):
        if in_net(dst, "192.168.10.0/24"):
            return {
                "filter": "STUDENT-FILTER",
                "device": "core_sw1",
                "rationale": (
                    "STUDENT-FILTER (VLAN 30 in, both cores) denies student "
                    "192.168.30.0/24 to management 192.168.10.0/24."
                ),
            }
        if in_net(dst, "192.168.80.0/24"):
            dns_ok = dst == DNS_HOST and is_dns_probe(probe)
            if not dns_ok:
                return {
                    "filter": "STUDENT-FILTER",
                    "device": "core_sw1",
                    "rationale": (
                        "STUDENT-FILTER denies student traffic to network services "
                        f"192.168.80.0/24 except DNS to {DNS_HOST}."
                    ),
                }

    # GUEST-WLAN-FILTER in on VLAN 65, both cores.
    if in_net(src, "11.10.65.0/24"):
        if (
            in_net(dst, "192.168.0.0/16")
            or in_net(dst, "11.10.55.0/24")
            or in_net(dst, "11.10.60.0/24")
        ):
            return {
                "filter": "GUEST-WLAN-FILTER",
                "device": "core_sw1",
                "rationale": (
                    "GUEST-WLAN-FILTER (VLAN 65 in, both cores) denies guest "
                    "11.10.65.0/24 to wired campus LAN / staff WLAN / student WLAN."
                ),
            }

    # DMZ-IN on FIREWALL-1 DMZ interface.
    if in_net(src, "12.20.20.0/26"):
        dns_ok = dst == DNS_HOST and is_dns_probe(probe)
        if dns_ok:
            return None
        if in_net(dst, "192.168.0.0/16") or in_net(dst, "11.10.0.0/16"):
            return {
                "filter": "DMZ-IN",
                "device": "fw1",
                "rationale": (
                    "DMZ-IN on fw1 denies DMZ 12.20.20.0/26 to internal LAN/WLAN; "
                    f"only DNS to {DNS_HOST} is permitted."
                ),
            }
    return None


def is_bad_default_nexthop(next_hop: str) -> bool:
    """True if a static default points into campus, not ISP-A/ISP-B."""
    nh = (next_hop or "").split("/")[0].strip()
    if not nh or nh.lower() in {"none", "null", "auto"}:
        return False
    if nh in ISP_NEXTHOPS:
        return False
    return (
        in_net(nh, "192.168.0.0/16")
        or in_net(nh, "11.10.0.0/16")
        or in_net(nh, "10.0.0.0/8")
    )


def policy_cheatsheet() -> str:
    return (
        "Campus policy (authoritative lab notes):\n"
        f"- DNS host {DNS_HOST} (VLAN 80 NETWORK-SERVICES).\n"
        "- STUDENT-FILTER on VLAN 30 (core_sw1/core_sw2): deny 192.168.30.0/24 -> "
        "192.168.10.0/24 (management); deny students -> 192.168.80.0/24 except DNS "
        f"to {DNS_HOST}; permit other student traffic.\n"
        "- GUEST-WLAN-FILTER on VLAN 65 (core_sw1/core_sw2): deny 11.10.65.0/24 -> "
        "192.168.0.0/16, 11.10.55.0/24, 11.10.60.0/24; permit remaining guest traffic.\n"
        "- DMZ-IN on fw1: permit DMZ 12.20.20.0/26 DNS to "
        f"{DNS_HOST}; deny DMZ -> 192.168.0.0/16 and 11.10.0.0/16; permit rest.\n"
        "- VTY ACL 1 is management-plane only; ignore for dataplane RCA.\n"
        "- OSPF area 0 on cores/firewalls/head routers. Missing advertisement of a "
        "VLAN prefix is owned by the distribution block (students dsw_b_student, "
        "academic dsw_a_acad, services dsw_d_dc).\n"
        "- Head-router default must next-hop ISP-A 20.20.20.x or ISP-B 30.30.30.x, "
        "not a campus LAN address.\n"
        "- Do not treat implicit deny on an ACL whose source ACE does not match the probe."
    )


def filter_acl_trace_for_probe(rows: list[dict[str, Any]], probe: ProbeSpec) -> list[dict[str, Any]]:
    hit = match_campus_acl(probe)
    if not hit:
        return []
    name = hit["filter"].lower()
    keep = [
        r
        for r in rows
        if name in _s(r.get("Filter_Name") or r.get("Filter"))
        and "deny" in _s(r.get("Action"))
    ]
    return keep or [
        {
            "Node": hit["device"],
            "Filter_Name": hit["filter"],
            "Action": "DENY",
            "Flow": f"{probe.src_ip}->{probe.dst_ip}",
        }
    ]


def _s(obj: Any) -> str:
    return str(obj).lower() if obj is not None else ""
