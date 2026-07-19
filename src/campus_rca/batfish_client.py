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
                self.bf.q.testFilters(headers=hc, nodes="/dist.*/").answer().frame()
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
        # Map host interfaces from campus lab addressing
        if probe.src_ip.startswith("10.10.10."):
            return "hostA"
        if probe.src_ip.startswith("10.20.20."):
            return "hostC" if probe.src_ip.endswith(".100") else "hostB"
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
            "acl_deny_http": self._syn_acl,
            "missing_ospf_network": self._syn_missing_student,
            "interface_shutdown": self._syn_iface_down,
            "wrong_static_route": self._syn_static,
            "ospf_passive_misconfig": self._syn_missing_faculty,
        }
        builder = factory.get(scenario_id, self._syn_generic)
        return builder(probe, symptom)

    def _syn_acl(self, probe: ProbeSpec, symptom: str) -> EvidenceBundle:
        return EvidenceBundle(
            scenario_id="acl_deny_http",
            snapshot="synthetic",
            symptom=symptom,
            probe=probe,
            routes=[
                {"Node": "dist1", "Network": "10.20.20.0/24", "Protocol": "ospf", "Next_Hop": "core1"},
                {"Node": "core1", "Network": "10.20.20.0/24", "Protocol": "ospf", "Next_Hop": "dist2"},
            ],
            interfaces=[
                {
                    "Interface": {"hostname": "dist2", "interface": "GigabitEthernet0/1"},
                    "Active": True,
                    "Incoming_Filter_Name": "CAMPUS_EDGE",
                }
            ],
            traceroute=[
                {
                    "Flow": f"{probe.src_ip} -> {probe.dst_ip}:{probe.dst_port}",
                    "Traces": [{"disposition": "DENIED_IN", "hop": "dist2", "filter": "CAMPUS_EDGE"}],
                }
            ],
            reachability=[{"Flow": "HTTP", "Result": "UNREACHABLE", "Disposition": "DENIED_IN"}],
            acl_trace=[
                {
                    "Node": "dist2",
                    "Filter_Name": "CAMPUS_EDGE",
                    "Flow": f"TCP {probe.src_ip} -> {probe.dst_ip}:80",
                    "Action": "DENY",
                }
            ],
            source="synthetic",
        )

    def _syn_missing_student(self, probe: ProbeSpec, symptom: str) -> EvidenceBundle:
        return EvidenceBundle(
            scenario_id="missing_ospf_network",
            snapshot="synthetic",
            symptom=symptom,
            probe=probe,
            routes=[
                {"Node": "dist2", "Network": "10.20.20.0/24", "Protocol": "connected"},
                {"Node": "core1", "Network": "10.20.20.0/24", "Protocol": "ospf"},
                # 10.10.10.0/24 missing on core1/dist2
            ],
            interfaces=[
                {
                    "Interface": {"hostname": "dist1", "interface": "GigabitEthernet0/1"},
                    "Primary_Address": "10.10.10.1/24",
                    "Active": True,
                }
            ],
            traceroute=[{"Flow": str(probe), "Traces": [{"disposition": "NO_ROUTE", "hop": "core1"}]}],
            reachability=[{"Result": "UNREACHABLE", "Disposition": "NO_ROUTE"}],
            source="synthetic",
        )

    def _syn_iface_down(self, probe: ProbeSpec, symptom: str) -> EvidenceBundle:
        return EvidenceBundle(
            scenario_id="interface_shutdown",
            snapshot="synthetic",
            symptom=symptom,
            probe=probe,
            routes=[{"Node": "core1", "Network": "10.20.20.0/24", "Protocol": None}],
            interfaces=[
                {
                    "Interface": {"hostname": "core1", "interface": "GigabitEthernet0/1"},
                    "Description": "to-dist2",
                    "Active": False,
                    "Admin_Up": False,
                }
            ],
            traceroute=[{"Traces": [{"disposition": "NO_ROUTE"}]}],
            reachability=[{"Result": "UNREACHABLE"}],
            source="synthetic",
        )

    def _syn_static(self, probe: ProbeSpec, symptom: str) -> EvidenceBundle:
        return EvidenceBundle(
            scenario_id="wrong_static_route",
            snapshot="synthetic",
            symptom=symptom,
            probe=probe,
            routes=[
                {
                    "Node": "core1",
                    "Network": "0.0.0.0/0",
                    "Protocol": "static",
                    "Next_Hop_IP": "10.10.10.1",
                }
            ],
            interfaces=[{"Interface": {"hostname": "core1", "interface": "GigabitEthernet0/2"}, "Active": True}],
            traceroute=[{"Traces": [{"disposition": "NEIGHBOR_UNREACHABLE_OR_NO_ROUTE"}]}],
            reachability=[{"Result": "UNREACHABLE", "Destination": "203.0.113.50"}],
            source="synthetic",
        )

    def _syn_missing_faculty(self, probe: ProbeSpec, symptom: str) -> EvidenceBundle:
        return EvidenceBundle(
            scenario_id="ospf_passive_misconfig",
            snapshot="synthetic",
            symptom=symptom,
            probe=probe,
            routes=[
                {"Node": "dist2", "Network": "10.20.20.0/24", "Protocol": "connected"},
                # missing on core1 / dist1
            ],
            interfaces=[
                {
                    "Interface": {"hostname": "dist2", "interface": "GigabitEthernet0/1"},
                    "Primary_Address": "10.20.20.1/24",
                    "Active": True,
                    "Incoming_Filter_Name": "CAMPUS_EDGE",
                }
            ],
            traceroute=[{"Traces": [{"disposition": "NO_ROUTE", "hop": "core1"}]}],
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
