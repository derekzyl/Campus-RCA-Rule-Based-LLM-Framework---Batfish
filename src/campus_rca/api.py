from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from campus_rca.config import get_settings
from campus_rca.models import ProbeSpec
from campus_rca.pipeline import RCAPipeline, load_scenarios

app = FastAPI(
    title="Campus RCA Hybrid Framework",
    description="Rule-based LLM root cause analysis for campus networks using Batfish",
    version="0.1.0",
)


class DiagnoseRequest(BaseModel):
    scenario_id: str
    mode: str = Field("hybrid", pattern="^(rule_only|llm_only|hybrid)$")
    offline: bool = False


class AdhocRequest(BaseModel):
    symptom: str
    snapshot_dir: str
    mode: str = "hybrid"
    src_ip: str
    dst_ip: str
    dst_port: Optional[int] = None
    ip_protocol: str = "TCP"
    applications: list[str] = Field(default_factory=list)
    offline: bool = False


@app.get("/health")
def health() -> dict[str, Any]:
    s = get_settings()
    payload: dict[str, Any] = {
        "status": "ok",
        "llm_backend": s.llm_backend,
        "use_batfish": s.use_batfish,
    }
    if s.llm_backend == "ollama":
        payload["ollama_model"] = s.ollama_model
        payload["ollama_base_url"] = s.ollama_base_url
        try:
            from campus_rca.llm.backend import OllamaBackend

            payload["ollama"] = OllamaBackend(
                s.ollama_base_url, s.ollama_model, s.llm_temperature
            ).ping()
        except Exception as exc:  # noqa: BLE001
            payload["ollama"] = {"ok": False, "error": str(exc)}
            payload["status"] = "degraded"
    return payload


@app.get("/scenarios")
def scenarios() -> dict[str, Any]:
    return load_scenarios()


@app.post("/diagnose")
def diagnose(req: DiagnoseRequest) -> dict[str, Any]:
    base = get_settings()
    settings = base.model_copy(update={"use_batfish": False} if req.offline else {})
    data = load_scenarios()
    matching = next((s for s in data["scenarios"] if s["id"] == req.scenario_id), None)
    if not matching:
        raise HTTPException(404, f"Unknown scenario {req.scenario_id}")
    pipe = RCAPipeline(settings)
    return pipe.run_scenario(matching, mode=req.mode).model_dump()


@app.post("/diagnose/adhoc")
def diagnose_adhoc(req: AdhocRequest) -> dict[str, Any]:
    base = get_settings()
    settings = base.model_copy(update={"use_batfish": False} if req.offline else {})
    probe = ProbeSpec(
        src_ip=req.src_ip,
        dst_ip=req.dst_ip,
        dst_port=req.dst_port,
        ip_protocol=req.ip_protocol,
        applications=req.applications,
    )
    pipe = RCAPipeline(settings)
    return pipe.run(
        mode=req.mode,
        scenario_id="adhoc",
        symptom=req.symptom,
        snapshot_dir=req.snapshot_dir,
        probe=probe,
    ).model_dump()
