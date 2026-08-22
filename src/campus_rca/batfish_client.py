from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from campus_rca.config import Settings, get_settings
from campus_rca.models import EvidenceBundle, ProbeSpec

logger = logging.getLogger(__name__)


def _df_records(df) -> list[dict[str, Any]]:
    if df is None:
        return []
    try:
        return json.loads(df.to_json(orient="records"))
    except Exception:
        return df.to_dict(orient="records")


class BatfishClient:
    """Thin wrapper around pybatfish for campus RCA evidence collection."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._ready = False
        self._bf = None

    def connect(self) -> None:
        from pybatfish.client.session import Session

        self._bf = Session(host=self.settings.batfish_host)
        # Some deployments expose coordinator on 9996; Session uses host default.
        self._bf.set_network(self.settings.batfish_network)
        self._ready = True
        logger.info(
            "Connected to Batfish at %s (network=%s)",
            self.settings.batfish_host,
            self.settings.batfish_network,
        )

    @property
    def bf(self):
        if not self._ready or self._bf is None:
            self.connect()
        return self._bf

    def init_snapshot(self, snapshot_dir: Path | str, name: str, overwrite: bool = True) -> str:
        path = Path(snapshot_dir)
        if not path.is_absolute():
            path = self.settings.project_root / path
        # Batfish expects configs under configs/ and optional hosts under hosts/
        snap = self.bf.init_snapshot(str(path), name=name, overwrite=overwrite)
        return snap

    def collect_evidence(
        self,
        scenario_id: str,
        snapshot_dir: Path | str,
        probe: ProbeSpec,
        symptom: str = "",
        baseline_dir: Path | str | None = None,
        cache_dir: Path | str | None = None,
    ) -> EvidenceBundle:
        cache_path = None
        if cache_dir:
            cache_path = Path(cache_dir)
            if not cache_path.is_absolute():
                cache_path = self.settings.project_root / cache_path
            cache_path.mkdir(parents=True, exist_ok=True)
            cached = cache_path / f"{scenario_id}.json"
            if cached.exists() and not self.settings.use_batfish:
                return EvidenceBundle.model_validate_json(cached.read_text())

        if not self.settings.use_batfish:
            synthetic = self._synthetic_fallback(scenario_id, probe, symptom)
            if cache_path:
                (cache_path / f"{scenario_id}.json").write_text(synthetic.model_dump_json(indent=2))
            return synthetic

        snap_name = f"snap_{scenario_id}"
        self.init_snapshot(snapshot_dir, name=snap_name)

        issues = _df_records(self.bf.q.initIssues().answer().frame())
        interfaces = _df_records(self.bf.q.interfaceProperties().answer().frame())
        routes = _df_records(self.bf.q.routes().answer().frame())

        hc = self._header_constraints(probe)
        start = self._start_location(probe)
        tr = _df_records(
            self.bf.q.traceroute(startLocation=start, headers=hc).answer().frame()
        )
        reach = _df_records(self.bf.q.reachability(headers=hc).answer().frame())

        acl = []
        try:
            acl = _df_records(
                self.bf.q.testFilters(
                    headers=hc, nodes="/core_sw.*|fw.*|dsw_.*/"
                ).answer().frame()
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("testFilters unavailable: %s", exc)

        differential: dict[str, Any] = {}
        if baseline_dir:
            try:
                self.init_snapshot(baseline_dir, name="snap_baseline")
                differential = {
                    "note": "Baseline snapshot loaded for comparison",
                    "baseline_snapshot": "snap_baseline",
                    "fault_snapshot": snap_name,
                }
                # Re-load fault snapshot as active
                self.init_snapshot(snapshot_dir, name=snap_name)
            except Exception as exc:  # noqa: BLE001
                differential = {"error": str(exc)}

        bundle = EvidenceBundle(
            scenario_id=scenario_id,
            snapshot=snap_name,
            symptom=symptom,
            probe=probe,
            init_issues=issues,
            routes=self._simplify_routes(routes),
            interfaces=self._simplify_interfaces(interfaces),
            traceroute=tr,
            reachability=reach,
            acl_trace=acl,
            differential=differential,
            source="batfish",
        )

        if cache_path:
            (cache_path / f"{scenario_id}.json").write_text(bundle.model_dump_json(indent=2))
        return bundle

    def _header_constraints(self, probe: ProbeSpec):
        from pybatfish.datamodel.flow import HeaderConstraints

        kwargs: dict[str, Any] = {
            "srcIps": probe.src_ip,
            "dstIps": probe.dst_ip,
        }
        if probe.applications:
            kwargs["applications"] = probe.applications
        else:
            kwargs["ipProtocols"] = [probe.ip_protocol]
            if probe.dst_port is not None:
                kwargs["dstPorts"] = str(probe.dst_port)
        return HeaderConstraints(**kwargs)

    @staticmethod
    def _start_location(probe: ProbeSpec) -> str:
        # Map campus lab addressing to Batfish host names
        mapping = (
            ("192.168.30.", "student_pc"),
            ("192.168.20.", "acad_pc"),
            ("192.168.11.", "admin_pc"),
            ("192.168.80.", "dns_srv"),
            ("192.168.10.", "mgt_pc"),
            ("192.168.40.", "lab_pc"),
            ("11.10.65.", "guest_wifi"),
            ("12.20.20.", "web_dmz"),
            ("203.0.113.", "inet_host"),
            ("10.10.10.", "hostA"),
            ("10.20.20.", "hostB"),
        )
        for prefix, host in mapping:
            if probe.src_ip.startswith(prefix):
                return host
        return f"@enter(/.*{probe.src_ip}/)"

    @staticmethod
    def _simplify_routes(routes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        keep = ("Node", "Network", "Protocol", "Next_Hop", "Next_Hop_IP", "Admin_Distance", "Metric")
        out = []
        for r in routes:
            out.append({k: r.get(k) for k in keep if k in r})
        return out[:500]

    @staticmethod
    def _simplify_interfaces(ifaces: list[dict[str, Any]]) -> list[dict[str, Any]]:
        keep = (
            "Interface",
            "VRF",
            "Primary_Address",
            "Active",
            "Admin_Up",
            "Line_Up",
            "Description",
            "Incoming_Filter_Name",
            "Outgoing_Filter_Name",
        )
        out = []
        for r in ifaces:
            out.append({k: r.get(k) for k in keep if k in r})
        return out

    def _synthetic_fallback(
        self, scenario_id: str, probe: ProbeSpec, symptom: str
    ) -> EvidenceBundle:
        """Offline evidence when Batfish is unavailable — aligned to ground-truth scenarios."""
        factory = {
            "student_acl_deny_mgt": self._syn_student_acl,
            "guest_wlan_acl_deny": self._syn_guest_acl,
            "missing_ospf_students": self._syn_missing_students,
            "core1_uplink_shutdown": self._syn_core1_uplink,
            "wrong_default_route_r1": self._syn_bad_default,
            "ospf_omit_academic": self._syn_omit_academic,
            "dmz_to_lan_leak_attempt": self._syn_dmz_acl,
            "fw1_inside_shutdown": self._syn_fw1_down,
            "core2_student_uplink_down": self._syn_core2_uplink,
            "missing_ospf_dns_services": self._syn_missing_dns,
            # legacy ids
            "acl_deny_http": self._syn_student_acl,
            "missing_ospf_network": self._syn_missing_students,
            "interface_shutdown": self._syn_core1_uplink,
            "wrong_static_route": self._syn_bad_default,
            "ospf_passive_misconfig": self._syn_omit_academic,
        }
        builder = factory.get(scenario_id, self._syn_generic)
        return builder(probe, symptom)

    def _syn_student_acl(self, probe: ProbeSpec, symptom: str) -> EvidenceBundle:
        return EvidenceBundle(
            scenario_id="student_acl_deny_mgt",
            snapshot="synthetic",
            symptom=symptom,
            probe=probe,
            routes=[{"Node": "core_sw1", "Network": "192.168.10.0/24", "Protocol": "connected"}],
            interfaces=[
                {
                    "Interface": {"hostname": "core_sw1", "interface": "Vlan30"},
                    "Active": True,
                    "Incoming_Filter_Name": "STUDENT-FILTER",
                }
            ],
            traceroute=[{"Traces": [{"disposition": "DENIED_IN", "hop": "core_sw1"}]}],
            reachability=[{"Result": "UNREACHABLE", "Disposition": "DENIED_IN"}],
            acl_trace=[
                {
                    "Node": "core_sw1",
                    "Filter_Name": "STUDENT-FILTER",
                    "Flow": f"{probe.src_ip}->{probe.dst_ip}",
                    "Action": "DENY",
                }
            ],
            source="synthetic",
        )

    def _syn_guest_acl(self, probe: ProbeSpec, symptom: str) -> EvidenceBundle:
        return EvidenceBundle(
            scenario_id="guest_wlan_acl_deny",
            snapshot="synthetic",
            symptom=symptom,
            probe=probe,
            interfaces=[
                {
                    "Interface": {"hostname": "core_sw1", "interface": "Vlan65"},
                    "Active": True,
                    "Incoming_Filter_Name": "GUEST-WLAN-FILTER",
                }
            ],
            traceroute=[{"Traces": [{"disposition": "DENIED_IN", "hop": "core_sw1"}]}],
            reachability=[{"Result": "UNREACHABLE", "Disposition": "DENIED_IN"}],
            acl_trace=[
                {
                    "Node": "core_sw1",
                    "Filter_Name": "GUEST-WLAN-FILTER",
                    "Action": "DENY",
                }
            ],
            source="synthetic",
        )

    def _syn_missing_students(self, probe: ProbeSpec, symptom: str) -> EvidenceBundle:
        return EvidenceBundle(
            scenario_id="missing_ospf_students",
            snapshot="synthetic",
            symptom=symptom,
            probe=probe,
            routes=[
                {"Node": "dsw_b_student", "Network": "192.168.30.0/24", "Protocol": "connected"},
                {"Node": "core_sw1", "Network": "192.168.20.0/24", "Protocol": "ospf"},
            ],
            interfaces=[
                {
                    "Interface": {"hostname": "dsw_b_student", "interface": "GigabitEthernet0/2"},
                    "Primary_Address": "192.168.30.1/24",
                    "Active": True,
                }
            ],
            traceroute=[{"Traces": [{"disposition": "NO_ROUTE", "hop": "core_sw1"}]}],
            reachability=[{"Result": "UNREACHABLE", "Disposition": "NO_ROUTE"}],
            source="synthetic",
        )

    def _syn_core1_uplink(self, probe: ProbeSpec, symptom: str) -> EvidenceBundle:
        return EvidenceBundle(
            scenario_id="core1_uplink_shutdown",
            snapshot="synthetic",
            symptom=symptom,
            probe=probe,
            interfaces=[
                {
                    "Interface": {"hostname": "core_sw1", "interface": "GigabitEthernet0/1"},
                    "Description": "to-dsw_b_student",
                    "Active": False,
                    "Admin_Up": False,
                }
            ],
            traceroute=[{"Traces": [{"disposition": "NO_ROUTE"}]}],
            reachability=[{"Result": "UNREACHABLE"}],
            source="synthetic",
        )

    def _syn_bad_default(self, probe: ProbeSpec, symptom: str) -> EvidenceBundle:
        return EvidenceBundle(
            scenario_id="wrong_default_route_r1",
            snapshot="synthetic",
            symptom=symptom,
            probe=probe,
            routes=[
                {
                    "Node": "campus_r1",
                    "Network": "0.0.0.0/0",
                    "Protocol": "static",
                    "Next_Hop_IP": "192.168.30.1",
                }
            ],
            traceroute=[{"Traces": [{"disposition": "NEIGHBOR_UNREACHABLE_OR_NO_ROUTE"}]}],
            reachability=[{"Result": "UNREACHABLE"}],
            source="synthetic",
        )

    def _syn_omit_academic(self, probe: ProbeSpec, symptom: str) -> EvidenceBundle:
        return EvidenceBundle(
            scenario_id="ospf_omit_academic",
            snapshot="synthetic",
            symptom=symptom,
            probe=probe,
            routes=[
                {"Node": "dsw_a_acad", "Network": "192.168.20.0/24", "Protocol": "connected"},
            ],
            interfaces=[
                {
                    "Interface": {"hostname": "dsw_a_acad", "interface": "GigabitEthernet0/2"},
                    "Primary_Address": "192.168.20.1/24",
                    "Active": True,
                }
            ],
            traceroute=[{"Traces": [{"disposition": "NO_ROUTE", "hop": "core_sw1"}]}],
            reachability=[{"Result": "UNREACHABLE", "Disposition": "NO_ROUTE"}],
            source="synthetic",
        )

    def _syn_dmz_acl(self, probe: ProbeSpec, symptom: str) -> EvidenceBundle:
        return EvidenceBundle(
            scenario_id="dmz_to_lan_leak_attempt",
            snapshot="synthetic",
            symptom=symptom,
            probe=probe,
            interfaces=[
                {
                    "Interface": {"hostname": "fw1", "interface": "GigabitEthernet0/2"},
                    "Incoming_Filter_Name": "DMZ-IN",
                    "Active": True,
                }
            ],
            acl_trace=[{"Node": "fw1", "Filter_Name": "DMZ-IN", "Action": "DENY"}],
            traceroute=[{"Traces": [{"disposition": "DENIED_IN", "hop": "fw1"}]}],
            reachability=[{"Result": "UNREACHABLE", "Disposition": "DENIED_IN"}],
            source="synthetic",
        )

    def _syn_fw1_down(self, probe: ProbeSpec, symptom: str) -> EvidenceBundle:
        return EvidenceBundle(
            scenario_id="fw1_inside_shutdown",
            snapshot="synthetic",
            symptom=symptom,
            probe=probe,
            interfaces=[
                {
                    "Interface": {"hostname": "fw1", "interface": "GigabitEthernet0/0"},
                    "Description": "inside-to-core_sw1",
                    "Active": False,
                    "Admin_Up": False,
                }
            ],
            reachability=[{"Result": "UNREACHABLE"}],
            source="synthetic",
        )

    def _syn_core2_uplink(self, probe: ProbeSpec, symptom: str) -> EvidenceBundle:
        return EvidenceBundle(
            scenario_id="core2_student_uplink_down",
            snapshot="synthetic",
            symptom=symptom,
            probe=probe,
            interfaces=[
                {
                    "Interface": {"hostname": "core_sw2", "interface": "GigabitEthernet0/2"},
                    "Description": "to-dsw_b_student",
                    "Active": False,
                    "Admin_Up": False,
                }
            ],
            reachability=[{"Result": "UNREACHABLE"}],
            source="synthetic",
        )

    def _syn_missing_dns(self, probe: ProbeSpec, symptom: str) -> EvidenceBundle:
        return EvidenceBundle(
            scenario_id="missing_ospf_dns_services",
            snapshot="synthetic",
            symptom=symptom,
            probe=probe,
            routes=[
                {"Node": "dsw_d_dc", "Network": "192.168.80.0/24", "Protocol": "connected"},
            ],
            interfaces=[
                {
                    "Interface": {"hostname": "dsw_d_dc", "interface": "GigabitEthernet0/2"},
                    "Primary_Address": "192.168.80.1/24",
                    "Active": True,
                }
            ],
            traceroute=[{"Traces": [{"disposition": "NO_ROUTE", "hop": "core_sw1"}]}],
            reachability=[{"Result": "UNREACHABLE", "Disposition": "NO_ROUTE"}],
            source="synthetic",
        )

    def _syn_generic(self, probe: ProbeSpec, symptom: str) -> EvidenceBundle:
        return EvidenceBundle(
            scenario_id="unknown",
            snapshot="synthetic",
            symptom=symptom,
            probe=probe,
            reachability=[{"Result": "UNREACHABLE"}],
            source="synthetic",
        )
