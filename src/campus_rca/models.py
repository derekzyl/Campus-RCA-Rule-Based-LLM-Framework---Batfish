from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class FaultType(str, Enum):
    ACL_DENY = "acl_deny"
    MISSING_ROUTE = "missing_route"
    INTERFACE_DOWN = "interface_down"
    WRONG_STATIC_ROUTE = "wrong_static_route"
    OSPF_NEIGHBOR = "ospf_neighbor"
    REACHABILITY_OK = "reachability_ok"
    UNKNOWN = "unknown"


class ProbeSpec(BaseModel):
    src_ip: str
    dst_ip: str
    dst_port: Optional[int] = None
    ip_protocol: str = "TCP"
    applications: list[str] = Field(default_factory=list)


class EvidenceBundle(BaseModel):
    """Deterministic evidence produced by Batfish (or offline cache)."""

    scenario_id: str
    snapshot: str
    symptom: str = ""
    probe: ProbeSpec
    init_issues: list[dict[str, Any]] = Field(default_factory=list)
    routes: list[dict[str, Any]] = Field(default_factory=list)
    interfaces: list[dict[str, Any]] = Field(default_factory=list)
    traceroute: list[dict[str, Any]] = Field(default_factory=list)
    reachability: list[dict[str, Any]] = Field(default_factory=list)
    acl_trace: list[dict[str, Any]] = Field(default_factory=list)
    differential: dict[str, Any] = Field(default_factory=dict)
    source: str = "batfish"  # batfish | cache | synthetic


class RuleHit(BaseModel):
    rule_id: str
    fault_type: FaultType
    confidence: float
    device: Optional[str] = None
    object: Optional[str] = None
    layer: str
    rationale: str
    evidence_refs: list[str] = Field(default_factory=list)


class RuleDiagnosis(BaseModel):
    primary: Optional[RuleHit] = None
    candidates: list[RuleHit] = Field(default_factory=list)
    unmatched_evidence: list[str] = Field(default_factory=list)


class LLMDiagnosis(BaseModel):
    root_cause: str
    fault_type: str
    device: Optional[str] = None
    confidence: float = 0.0
    explanation: str
    evidence_used: list[str] = Field(default_factory=list)
    remediation: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    raw_text: str = ""
    hallucinated_claims: list[str] = Field(default_factory=list)


class RCAResult(BaseModel):
    mode: str  # rule_only | llm_only | hybrid
    scenario_id: str
    symptom: str
    evidence: EvidenceBundle
    rule_diagnosis: Optional[RuleDiagnosis] = None
    llm_diagnosis: Optional[LLMDiagnosis] = None
    final_fault_type: str
    final_device: Optional[str] = None
    final_explanation: str
    remediation: list[str] = Field(default_factory=list)
    elapsed_ms: float = 0.0
    notes: list[str] = Field(default_factory=list)
