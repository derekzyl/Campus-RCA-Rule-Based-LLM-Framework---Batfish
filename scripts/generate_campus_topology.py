#!/usr/bin/env python3
"""Generate dual-core / dual-edge / by-block distribution Batfish snapshots."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs" / "baseline"
SCEN = ROOT / "configs" / "scenarios"


def cfg(hostname: str, body: str) -> str:
    return f"!\nhostname {hostname}\n!\n{body.rstrip()}\n!\nend\n"


def write_cfg(directory: Path, hostname: str, body: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{hostname}.cfg").write_text(cfg(hostname, body), encoding="utf-8")


def write_host(directory: Path, hostname: str, iface: str, prefix: str, gateway: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    data = {
        "hostname": hostname,
        "hostInterfaces": {
            iface: {"name": iface, "prefix": prefix, "gateway": gateway}
        },
    }
    (directory / f"{hostname}.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def baseline_bodies() -> dict[str, str]:
    """Known-good IOS-style configs for the campus lab."""
    return {
        "campus_r1": """
interface Loopback0
 ip address 5.5.5.5 255.255.255.255
!
interface GigabitEthernet0/0
 description to-fw1
 ip address 100.100.50.1 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/1
 description to-isp1
 ip address 203.0.113.1 255.255.255.252
 no shutdown
!
router ospf 1
 router-id 5.5.5.5
 network 100.100.50.0 0.0.0.3 area 0
 network 5.5.5.5 0.0.0.0 area 0
 default-information originate metric 10 metric-type 1
!
ip route 0.0.0.0 0.0.0.0 203.0.113.2
""",
        "campus_r2": """
interface Loopback0
 ip address 6.6.6.6 255.255.255.255
!
interface GigabitEthernet0/0
 description to-fw2
 ip address 100.100.50.5 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/1
 description to-isp2
 ip address 203.0.113.5 255.255.255.252
 no shutdown
!
router ospf 1
 router-id 6.6.6.6
 network 100.100.50.4 0.0.0.3 area 0
 network 6.6.6.6 0.0.0.0 area 0
 default-information originate metric 100 metric-type 1
!
ip route 0.0.0.0 0.0.0.0 203.0.113.6
""",
        "fw1": """
interface Loopback0
 ip address 3.3.3.3 255.255.255.255
!
interface GigabitEthernet0/0
 description inside-to-core_sw1
 ip address 192.168.250.2 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/1
 description outside-to-campus_r1
 ip address 100.100.50.2 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/2
 description dmz
 ip address 12.20.20.1 255.255.255.192
 no shutdown
!
ip access-list extended DMZ-IN
 remark Allow DMZ DNS to internal DNS
 permit udp 12.20.20.0 0.0.0.63 host 192.168.80.12 eq 53
 permit tcp 12.20.20.0 0.0.0.63 host 192.168.80.12 eq 53
 remark Block DMZ to internal LAN / WLAN
 deny ip 12.20.20.0 0.0.0.63 192.168.0.0 0.0.255.255
 deny ip 12.20.20.0 0.0.0.63 11.10.0.0 0.0.255.255
 permit ip 12.20.20.0 0.0.0.63 any
!
interface GigabitEthernet0/2
 ip access-group DMZ-IN in
!
router ospf 1
 router-id 3.3.3.3
 network 192.168.250.0 0.0.0.3 area 0
 network 100.100.50.0 0.0.0.3 area 0
 network 12.20.20.0 0.0.0.63 area 0
 network 3.3.3.3 0.0.0.0 area 0
 passive-interface GigabitEthernet0/2
""",
        "fw2": """
interface Loopback0
 ip address 4.4.4.4 255.255.255.255
!
interface GigabitEthernet0/0
 description inside-to-core_sw2
 ip address 192.168.250.6 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/1
 description outside-to-campus_r2
 ip address 100.100.50.6 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/2
 description dmz-secondary
 ip address 12.20.20.2 255.255.255.192
 no shutdown
!
router ospf 1
 router-id 4.4.4.4
 network 192.168.250.4 0.0.0.3 area 0
 network 100.100.50.4 0.0.0.3 area 0
 network 4.4.4.4 0.0.0.0 area 0
""",
        "core_sw1": """
interface Loopback0
 ip address 1.1.1.1 255.255.255.255
!
interface GigabitEthernet0/0
 description to-core_sw2
 ip address 192.168.254.1 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/1
 description to-dsw_b_student
 ip address 10.1.30.1 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/2
 description to-dsw_a_acad
 ip address 10.1.20.1 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/3
 description to-dsw_a_admin
 ip address 10.1.11.1 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/4
 description to-dsw_d_dc
 ip address 10.1.80.1 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/5
 description to-fw1
 ip address 192.168.250.1 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/6
 description to-dsw_b_lib
 ip address 10.1.50.1 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/7
 description to-dsw_c_lab
 ip address 10.1.40.1 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/8
 description to-dsw_d_media
 ip address 10.1.51.1 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/9
 description to-dsw_dmz
 ip address 10.1.100.1 255.255.255.252
 no shutdown
!
interface Vlan30
 description students-svl
 ip address 192.168.30.2 255.255.255.0
 no shutdown
!
interface Vlan65
 description guest-wlan-svl
 ip address 11.10.65.2 255.255.255.0
 no shutdown
!
ip access-list extended STUDENT-FILTER
 remark BLOCK MANAGEMENT NETWORK
 deny ip 192.168.30.0 0.0.0.255 192.168.10.0 0.0.0.255
 remark ALLOW DNS ONLY INTO SERVICES
 permit udp 192.168.30.0 0.0.0.255 host 192.168.80.12 eq 53
 permit tcp 192.168.30.0 0.0.0.255 host 192.168.80.12 eq 53
 deny ip 192.168.30.0 0.0.0.255 192.168.80.0 0.0.0.255
 permit ip 192.168.30.0 0.0.0.255 any
!
ip access-list extended GUEST-WLAN-FILTER
 remark BLOCK GUEST TO WIRED CAMPUS LAN
 deny ip 11.10.65.0 0.0.0.255 192.168.0.0 0.0.255.255
 remark BLOCK GUEST TO STAFF WLAN
 deny ip 11.10.65.0 0.0.0.255 11.10.55.0 0.0.0.255
 remark BLOCK GUEST TO STUDENT WLAN
 deny ip 11.10.65.0 0.0.0.255 11.10.60.0 0.0.0.255
 permit ip 11.10.65.0 0.0.0.255 any
!
interface Vlan30
 ip access-group STUDENT-FILTER in
!
interface Vlan65
 ip access-group GUEST-WLAN-FILTER in
!
router ospf 1
 router-id 1.1.1.1
 network 192.168.254.0 0.0.0.3 area 0
 network 192.168.250.0 0.0.0.3 area 0
 network 10.1.30.0 0.0.0.3 area 0
 network 10.1.20.0 0.0.0.3 area 0
 network 10.1.11.0 0.0.0.3 area 0
 network 10.1.80.0 0.0.0.3 area 0
 network 10.1.50.0 0.0.0.3 area 0
 network 10.1.40.0 0.0.0.3 area 0
 network 10.1.51.0 0.0.0.3 area 0
 network 10.1.100.0 0.0.0.3 area 0
 network 192.168.30.0 0.0.0.255 area 0
 network 11.10.65.0 0.0.0.255 area 0
 network 1.1.1.1 0.0.0.0 area 0
""",
        "core_sw2": """
interface Loopback0
 ip address 2.2.2.2 255.255.255.255
!
interface GigabitEthernet0/0
 description to-core_sw1
 ip address 192.168.254.2 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/1
 description to-dsw_a_acad
 ip address 10.1.20.5 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/2
 description to-dsw_b_student
 ip address 10.1.30.5 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/3
 description to-dsw_d_dc
 ip address 10.1.80.5 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/4
 description to-fw2
 ip address 192.168.250.5 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/5
 description to-dsw_a_admin
 ip address 10.1.11.5 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/6
 description to-dsw_c_lab
 ip address 10.1.40.5 255.255.255.252
 no shutdown
!
ip access-list extended STUDENT-FILTER
 deny ip 192.168.30.0 0.0.0.255 192.168.10.0 0.0.0.255
 permit udp 192.168.30.0 0.0.0.255 host 192.168.80.12 eq 53
 permit tcp 192.168.30.0 0.0.0.255 host 192.168.80.12 eq 53
 deny ip 192.168.30.0 0.0.0.255 192.168.80.0 0.0.0.255
 permit ip 192.168.30.0 0.0.0.255 any
!
router ospf 1
 router-id 2.2.2.2
 network 192.168.254.0 0.0.0.3 area 0
 network 192.168.250.4 0.0.0.3 area 0
 network 10.1.20.4 0.0.0.3 area 0
 network 10.1.30.4 0.0.0.3 area 0
 network 10.1.80.4 0.0.0.3 area 0
 network 10.1.11.4 0.0.0.3 area 0
 network 10.1.40.4 0.0.0.3 area 0
 network 2.2.2.2 0.0.0.0 area 0
""",
        "dsw_a_admin": """
interface Loopback0
 ip address 11.11.11.11 255.255.255.255
!
interface GigabitEthernet0/0
 description to-core_sw1
 ip address 10.1.11.2 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/1
 description to-core_sw2
 ip address 10.1.11.6 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/2
 description admin-hr-vlan11
 ip address 192.168.11.1 255.255.255.0
 no shutdown
!
router ospf 1
 router-id 11.11.11.11
 network 10.1.11.0 0.0.0.3 area 0
 network 10.1.11.4 0.0.0.3 area 0
 network 192.168.11.0 0.0.0.255 area 0
 network 11.11.11.11 0.0.0.0 area 0
""",
        "dsw_a_acad": """
interface Loopback0
 ip address 20.20.20.20 255.255.255.255
!
interface GigabitEthernet0/0
 description to-core_sw1
 ip address 10.1.20.2 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/1
 description to-core_sw2
 ip address 10.1.20.6 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/2
 description academic-vlan20
 ip address 192.168.20.1 255.255.255.0
 no shutdown
!
interface GigabitEthernet0/3
 description it-staff-vlan12
 ip address 192.168.12.1 255.255.255.0
 no shutdown
!
router ospf 1
 router-id 20.20.20.20
 network 10.1.20.0 0.0.0.3 area 0
 network 10.1.20.4 0.0.0.3 area 0
 network 192.168.20.0 0.0.0.255 area 0
 network 192.168.12.0 0.0.0.255 area 0
 network 20.20.20.20 0.0.0.0 area 0
""",
        "dsw_b_lib": """
interface Loopback0
 ip address 50.50.50.50 255.255.255.255
!
interface GigabitEthernet0/0
 description to-core_sw1
 ip address 10.1.50.2 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/1
 description library-vlan50
 ip address 192.168.50.1 255.255.255.0
 no shutdown
!
router ospf 1
 router-id 50.50.50.50
 network 10.1.50.0 0.0.0.3 area 0
 network 192.168.50.0 0.0.0.255 area 0
 network 50.50.50.50 0.0.0.0 area 0
""",
        "dsw_b_student": """
interface Loopback0
 ip address 30.30.30.30 255.255.255.255
!
interface GigabitEthernet0/0
 description to-core_sw1
 ip address 10.1.30.2 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/1
 description to-core_sw2
 ip address 10.1.30.6 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/2
 description students-vlan30
 ip address 192.168.30.1 255.255.255.0
 no shutdown
!
interface GigabitEthernet0/3
 description guest-wlan-vlan65
 ip address 11.10.65.1 255.255.255.0
 no shutdown
!
router ospf 1
 router-id 30.30.30.30
 network 10.1.30.0 0.0.0.3 area 0
 network 10.1.30.4 0.0.0.3 area 0
 network 192.168.30.0 0.0.0.255 area 0
 network 11.10.65.0 0.0.0.255 area 0
 network 30.30.30.30 0.0.0.0 area 0
""",
        "dsw_c_lab": """
interface Loopback0
 ip address 40.40.40.40 255.255.255.255
!
interface GigabitEthernet0/0
 description to-core_sw1
 ip address 10.1.40.2 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/1
 description to-core_sw2
 ip address 10.1.40.6 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/2
 description lab-vlan40
 ip address 192.168.40.1 255.255.255.0
 no shutdown
!
router ospf 1
 router-id 40.40.40.40
 network 10.1.40.0 0.0.0.3 area 0
 network 10.1.40.4 0.0.0.3 area 0
 network 192.168.40.0 0.0.0.255 area 0
 network 40.40.40.40 0.0.0.0 area 0
""",
        "dsw_d_dc": """
interface Loopback0
 ip address 80.80.80.80 255.255.255.255
!
interface GigabitEthernet0/0
 description to-core_sw1
 ip address 10.1.80.2 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/1
 description to-core_sw2
 ip address 10.1.80.6 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/2
 description network-services-vlan80
 ip address 192.168.80.1 255.255.255.0
 no shutdown
!
interface GigabitEthernet0/3
 description internal-servers-vlan90
 ip address 192.168.90.1 255.255.255.0
 no shutdown
!
router ospf 1
 router-id 80.80.80.80
 network 10.1.80.0 0.0.0.3 area 0
 network 10.1.80.4 0.0.0.3 area 0
 network 192.168.80.0 0.0.0.255 area 0
 network 192.168.90.0 0.0.0.255 area 0
 network 80.80.80.80 0.0.0.0 area 0
""",
        "dsw_d_media": """
interface Loopback0
 ip address 51.51.51.51 255.255.255.255
!
interface GigabitEthernet0/0
 description to-core_sw1
 ip address 10.1.51.2 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/1
 description media-endpoints
 ip address 192.168.51.1 255.255.255.0
 no shutdown
!
router ospf 1
 router-id 51.51.51.51
 network 10.1.51.0 0.0.0.3 area 0
 network 192.168.51.0 0.0.0.255 area 0
 network 51.51.51.51 0.0.0.0 area 0
""",
        "dsw_dmz": """
interface Loopback0
 ip address 100.100.100.100 255.255.255.255
!
interface GigabitEthernet0/0
 description to-core_sw1
 ip address 10.1.100.2 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/1
 description dmz-servers
 ip address 12.20.20.10 255.255.255.192
 no shutdown
!
router ospf 1
 router-id 100.100.100.100
 network 10.1.100.0 0.0.0.3 area 0
 network 12.20.20.0 0.0.0.63 area 0
 network 100.100.100.100 0.0.0.0 area 0
""",
    }


def write_baseline_hosts(hosts_dir: Path) -> None:
    hosts = [
        ("student_pc", "eth0", "192.168.30.21/24", "192.168.30.1"),
        ("acad_pc", "eth0", "192.168.20.21/24", "192.168.20.1"),
        ("admin_pc", "eth0", "192.168.11.21/24", "192.168.11.1"),
        ("dns_srv", "eth0", "192.168.80.12/24", "192.168.80.1"),
        ("web_dmz", "eth0", "12.20.20.20/26", "12.20.20.1"),
        ("guest_wifi", "eth0", "11.10.65.21/24", "11.10.65.1"),
        ("mgt_pc", "eth0", "192.168.10.51/24", "192.168.10.1"),
        ("lab_pc", "eth0", "192.168.40.21/24", "192.168.40.1"),
        ("inet_host", "eth0", "203.0.113.50/24", "203.0.113.1"),
    ]
    # management SVI is on cores in PT; give mgt_pc a gateway on core SVL via static host route through admin for simplicity
    for h, iface, prefix, gw in hosts:
        write_host(hosts_dir, h, iface, prefix, gw)
    # dedicated management network host attached via dsw_a_admin secondary for reachability tests
    # Use admin block gateway already; override mgt to sit on 192.168.10 via a small stub on dsw_a_admin? Keep as-is for ACL tests from student.


def clone_baseline(scenario_id: str) -> Path:
    dest = SCEN / scenario_id
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(BASE, dest)
    return dest


def mutate_file(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Mutation miss in {path}: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def build_scenarios() -> None:
    # 1 student ACL deny to management (policy already present — strengthen by denying all student→mgt TCP probes)
    d = clone_baseline("student_acl_deny_mgt")
    # baseline already has STUDENT-FILTER deny to 192.168.10.0/24 — fault is intentional policy causing symptom

    # 2 guest WLAN ACL
    clone_baseline("guest_wlan_acl_deny")

    # 3 missing OSPF students on dsw_b_student
    d = clone_baseline("missing_ospf_students")
    mutate_file(
        d / "configs" / "dsw_b_student.cfg",
        " network 192.168.30.0 0.0.0.255 area 0\n",
        " ! FAULT: student VLAN omitted from OSPF\n",
    )

    # 4 core1 uplink to student DSW shut
    d = clone_baseline("core1_uplink_shutdown")
    mutate_file(
        d / "configs" / "core_sw1.cfg",
        "interface GigabitEthernet0/1\n description to-dsw_b_student\n ip address 10.1.30.1 255.255.255.252\n no shutdown\n",
        "interface GigabitEthernet0/1\n description to-dsw_b_student\n ip address 10.1.30.1 255.255.255.252\n shutdown\n",
    )

    # 5 wrong default on campus_r1
    d = clone_baseline("wrong_default_route_r1")
    mutate_file(
        d / "configs" / "campus_r1.cfg",
        "ip route 0.0.0.0 0.0.0.0 203.0.113.2\n",
        "ip route 0.0.0.0 0.0.0.0 192.168.30.1\n",
    )

    # 6 omit academic OSPF
    d = clone_baseline("ospf_omit_academic")
    mutate_file(
        d / "configs" / "dsw_a_acad.cfg",
        " network 192.168.20.0 0.0.0.255 area 0\n",
        " ! FAULT: academic VLAN omitted from OSPF\n",
    )

    # 7 DMZ ACL: remove deny to LAN so traffic incorrectly permitted (policy regression) —
    # For RCA of "DMZ cannot reach LAN" the deny is correct; inject extra deny to DNS to create fault symptom
    d = clone_baseline("dmz_to_lan_leak_attempt")
    mutate_file(
        d / "configs" / "fw1.cfg",
        " permit udp 12.20.20.0 0.0.0.63 host 192.168.80.12 eq 53\n permit tcp 12.20.20.0 0.0.0.63 host 192.168.80.12 eq 53\n",
        " deny udp 12.20.20.0 0.0.0.63 host 192.168.80.12 eq 53\n deny tcp 12.20.20.0 0.0.0.63 host 192.168.80.12 eq 53\n",
    )

    # 8 fw1 inside interface shut
    d = clone_baseline("fw1_inside_shutdown")
    mutate_file(
        d / "configs" / "fw1.cfg",
        "interface GigabitEthernet0/0\n description inside-to-core_sw1\n ip address 192.168.250.2 255.255.255.252\n no shutdown\n",
        "interface GigabitEthernet0/0\n description inside-to-core_sw1\n ip address 192.168.250.2 255.255.255.252\n shutdown\n",
    )

    # 9 core2 student uplink down (redundant path fault)
    d = clone_baseline("core2_student_uplink_down")
    mutate_file(
        d / "configs" / "core_sw2.cfg",
        "interface GigabitEthernet0/2\n description to-dsw_b_student\n ip address 10.1.30.5 255.255.255.252\n no shutdown\n",
        "interface GigabitEthernet0/2\n description to-dsw_b_student\n ip address 10.1.30.5 255.255.255.252\n shutdown\n",
    )

    # 10 missing OSPF for DNS services VLAN
    d = clone_baseline("missing_ospf_dns_services")
    mutate_file(
        d / "configs" / "dsw_d_dc.cfg",
        " network 192.168.80.0 0.0.0.255 area 0\n",
        " ! FAULT: services VLAN omitted from OSPF\n",
    )


def main() -> None:
    # Replace old small topology baseline
    if BASE.exists():
        shutil.rmtree(BASE)
    cfg_dir = BASE / "configs"
    hosts_dir = BASE / "hosts"
    for name, body in baseline_bodies().items():
        write_cfg(cfg_dir, name, body)
    # management SVI on core_sw1 for STUDENT-FILTER destination realism
    core1 = cfg_dir / "core_sw1.cfg"
    text = core1.read_text(encoding="utf-8")
    if "interface Vlan10" not in text:
        text = text.replace(
            "interface Vlan30\n",
            "interface Vlan10\n description management\n ip address 192.168.10.2 255.255.255.0\n no shutdown\n!\ninterface Vlan30\n",
            1,
        )
        text = text.replace(
            " network 192.168.30.0 0.0.0.255 area 0\n",
            " network 192.168.10.0 0.0.0.255 area 0\n network 192.168.30.0 0.0.0.255 area 0\n",
            1,
        )
        core1.write_text(text, encoding="utf-8")
    write_baseline_hosts(hosts_dir)

    # Remove obsolete scenario dirs from old 5-scenario lab
    if SCEN.exists():
        for child in list(SCEN.iterdir()):
            if child.is_dir():
                shutil.rmtree(child)
    build_scenarios()
    print(f"Wrote baseline devices: {len(list(cfg_dir.glob('*.cfg')))}")
    print(f"Wrote scenarios: {sorted(p.name for p in SCEN.iterdir() if p.is_dir())}")


if __name__ == "__main__":
    main()
