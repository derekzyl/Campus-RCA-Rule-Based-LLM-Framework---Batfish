from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any

from campus_rca.models import EvidenceBundle, LLMDiagnosis, RuleDiagnosis
from campus_rca.llm.prompts import (
    SYSTEM_PROMPT,
    build_hybrid_user_prompt,
    build_llm_only_user_prompt,
    evidence_to_prompt_json,
    rules_to_prompt_json,
)


def _extract_json(text: str) -> dict[str, Any]:
    """Parse model JSON; tolerate fences, trailing commas, and truncated objects."""
    text = (text or "").strip()
    if not text:
        raise json.JSONDecodeError("Empty response", text, 0)

    # Strip markdown fences if present
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()

    candidates = [text]
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        candidates.append(match.group(0))

    last_err: Exception | None = None
    for cand in candidates:
        for attempt in (cand, re.sub(r",\s*([}\]])", r"\1", cand)):
            try:
                data = json.loads(attempt)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError as exc:
                last_err = exc

        # Truncated JSON: close open braces/brackets and retry
        repaired = re.sub(r",\s*([}\]])", r"\1", cand)
        # Drop a dangling incomplete key/value at the end
        repaired = re.sub(r",\s*\"[^\"]*\"?\s*:?\s*\"?[^\"]*$", "", repaired)
        repaired = re.sub(r",\s*$", "", repaired)
        open_curly = repaired.count("{") - repaired.count("}")
        open_square = repaired.count("[") - repaired.count("]")
        if open_curly > 0 or open_square > 0:
            repaired = repaired + ("]" * max(0, open_square)) + ("}" * max(0, open_curly))
            try:
                data = json.loads(repaired)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError as exc:
                last_err = exc

    if last_err:
        raise last_err
    raise json.JSONDecodeError("No JSON object found", text, 0)


def _fallback_diagnosis(raw: str, rules: RuleDiagnosis | None) -> LLMDiagnosis:
    """When the model returns unparseable JSON, keep the run alive."""
    if rules and rules.primary:
        p = rules.primary
        return LLMDiagnosis(
            root_cause=f"{p.fault_type.value} on {p.device}",
            fault_type=p.fault_type.value,
            device=p.device,
            confidence=float(p.confidence),
            explanation=p.rationale,
            evidence_used=list(p.evidence_refs),
            remediation=[f"Inspect {p.device}:{p.object}"],
            uncertainties=["LLM JSON parse failed — using rule diagnosis"],
            raw_text=raw,
            hallucinated_claims=["LLM response was not valid JSON"],
        )
    return LLMDiagnosis(
        root_cause="LLM response unparseable",
        fault_type="unknown",
        device=None,
        confidence=0.0,
        explanation="Model returned invalid JSON; no rule diagnosis available.",
        evidence_used=[],
        remediation=[],
        uncertainties=["LLM JSON parse failed"],
        raw_text=raw,
        hallucinated_claims=["LLM response was not valid JSON"],
    )


class LLMBackend(ABC):
    @abstractmethod
    def complete(self, system: str, user: str) -> str:
        raise NotImplementedError

    def explain_hybrid(
        self, symptom: str, evidence: EvidenceBundle, rules: RuleDiagnosis
    ) -> LLMDiagnosis:
        user = build_hybrid_user_prompt(
            symptom,
            evidence_to_prompt_json(evidence),
            rules_to_prompt_json(rules),
        )
        raw = self.complete(SYSTEM_PROMPT, user)
        return self._to_diagnosis(raw, grounded=True, evidence=evidence, rules=rules)

    def diagnose_llm_only(self, symptom: str, evidence: EvidenceBundle) -> LLMDiagnosis:
        user = build_llm_only_user_prompt(symptom, evidence_to_prompt_json(evidence))
        raw = self.complete(SYSTEM_PROMPT, user)
        return self._to_diagnosis(raw, grounded=False, evidence=evidence, rules=None)

    def _to_diagnosis(
        self,
        raw: str,
        grounded: bool,
        evidence: EvidenceBundle,
        rules: RuleDiagnosis | None,
    ) -> LLMDiagnosis:
        try:
            data = _extract_json(raw)
        except (json.JSONDecodeError, ValueError, TypeError):
            return _fallback_diagnosis(raw, rules)

        device = data.get("device")
        if isinstance(device, str) and device.strip().lower() in {
            "null",
            "none",
            "hostname or null",
            "hostname",
            "n/a",
        }:
            device = None

        fault = str(data.get("fault_type", "unknown")).strip().lower()
        # Models sometimes echo the whole enum string
        if "|" in fault:
            fault = "unknown"

        diag = LLMDiagnosis(
            root_cause=str(data.get("root_cause", "")),
            fault_type=fault,
            device=device,
            confidence=float(data.get("confidence", 0.5) or 0.5),
            explanation=str(data.get("explanation", "")),
            evidence_used=list(data.get("evidence_used") or []),
            remediation=list(data.get("remediation") or []),
            uncertainties=list(data.get("uncertainties") or []),
            raw_text=raw,
        )
        diag.hallucinated_claims = self._flag_hallucinations(diag, evidence, rules, grounded)
        return diag

    def _flag_hallucinations(
        self,
        diag: LLMDiagnosis,
        evidence: EvidenceBundle,
        rules: RuleDiagnosis | None,
        grounded: bool,
    ) -> list[str]:
        """Lightweight evidence-faithfulness checks for evaluation (RQ2)."""
        flags: list[str] = []
        blob = evidence.model_dump_json().lower()
        text = f"{diag.root_cause} {diag.explanation} {diag.device}".lower()

        for device in re.findall(
            r"\b(campus_r1|campus_r2|fw1|fw2|core_sw1|core_sw2|dsw_a_admin|dsw_a_acad|"
            r"dsw_b_lib|dsw_b_student|dsw_c_lab|dsw_d_dc|dsw_d_media|dsw_dmz|"
            r"core1|dist1|dist2|border1|r\d+|sw\d+)\b",
            text,
        ):
            if device not in blob and (not rules or device not in rules.model_dump_json().lower()):
                flags.append(f"Mentions device '{device}' absent from evidence")

        if grounded and rules and rules.primary:
            if diag.fault_type != rules.primary.fault_type.value:
                # Not always hallucination — note contradiction for metrics
                flags.append(
                    f"Contradicts rule fault_type ({rules.primary.fault_type.value} vs {diag.fault_type})"
                )
        return flags


class OpenAIBackend(LLMBackend):
    def __init__(self, api_key: str, model: str, temperature: float = 0.0):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.temperature = temperature

    def complete(self, system: str, user: str) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or "{}"


class OllamaBackend(LLMBackend):
    def __init__(
        self,
        base_url: str,
        model: str,
        temperature: float = 0.0,
        timeout_s: float = 600.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout_s = timeout_s

    def ping(self) -> dict:
        import httpx

        with httpx.Client(timeout=10.0) as client:
            r = client.get(f"{self.base_url}/api/tags")
            r.raise_for_status()
            models = [m.get("name", "") for m in r.json().get("models", [])]
            return {"ok": True, "models": models, "selected": self.model}

    def complete(self, system: str, user: str) -> str:
        import httpx
        import os

        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": self.temperature,
                # Keep CPU inference bounded; can be overridden via OLLAMA_NUM_PREDICT env.
                "num_predict": int(os.environ.get("OLLAMA_NUM_PREDICT", "256")),
            },
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            with httpx.Client(
                timeout=httpx.Timeout(self.timeout_s, connect=15.0)
            ) as client:
                r = client.post(f"{self.base_url}/api/chat", json=payload)
                if r.status_code == 404:
                    raise RuntimeError(
                        f"Ollama model '{self.model}' not found. Run: ollama pull {self.model}"
                    )
                r.raise_for_status()
                content = r.json().get("message", {}).get("content") or "{}"
                return content
        except httpx.ConnectError as exc:
            raise RuntimeError(
                f"Cannot reach Ollama at {self.base_url}. Start it with: ollama serve"
            ) from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"Ollama timed out after {self.timeout_s:.0f}s for model '{self.model}'. "
                "Compact prompts are already enabled; try a smaller model or GPU."
            ) from exc


class MockBackend(LLMBackend):
    """Deterministic offline LLM stand-in for demos and CI without API keys."""

    def complete(self, system: str, user: str) -> str:
        # Prefer rule JSON embedded in hybrid prompts
        rule_match = re.search(r'"fault_type":\s*"([^"]+)"', user)
        device_match = re.search(r'"device":\s*"([^"]+)"', user)
        obj_match = re.search(r'"object":\s*"([^"]+)"', user)

        if "Validated rule-based diagnosis" in user and rule_match:
            fault = rule_match.group(1)
            device = device_match.group(1) if device_match else None
            obj = obj_match.group(1) if obj_match else None
            return json.dumps(
                {
                    "root_cause": f"{fault} on {device} ({obj})" if device else fault,
                    "fault_type": fault,
                    "device": device,
                    "confidence": 0.9,
                    "explanation": (
                        f"Based on validated rules and Batfish evidence, the primary root cause is "
                        f"{fault} affecting {device}/{obj}. Evidence shows the probe flow fails in a "
                        f"manner consistent with this fault class."
                    ),
                    "evidence_used": ["rule_primary", "reachability", "routes"],
                    "remediation": [
                        f"Verify configuration on {device} for {obj}",
                        "Compare against baseline snapshot",
                        "Apply change only after human approval",
                    ],
                    "uncertainties": [],
                }
            )

        # LLM-only heuristic: intentionally weak on overlapping ACL vs routing symptoms
        # (dissertation RQ1 — hybrid should beat unguided LLM when evidence is ambiguous).
        symptom_section = user.split("Optional raw evidence")[0].lower()
        evidence_section = user.lower()

        if "management" in symptom_section or "192.168.10" in symptom_section:
            fault, device, obj = "acl_deny", "core_sw1", "STUDENT-FILTER"
        elif "guest" in symptom_section or "11.10.65" in symptom_section:
            fault, device, obj = "acl_deny", "core_sw1", "GUEST-WLAN-FILTER"
        elif "dmz" in symptom_section or "12.20.20" in symptom_section:
            fault, device, obj = "acl_deny", "fw1", "DMZ-IN"
        elif "internet" in symptom_section or "203.0.113" in symptom_section:
            if "firewall" in symptom_section or "fw1" in symptom_section:
                fault, device, obj = "interface_down", "fw1", "GigabitEthernet0/0"
            else:
                fault, device, obj = "wrong_static_route", "campus_r1", "0.0.0.0/0"
        elif "redundant" in symptom_section or "core-sw2" in symptom_section or "core_sw2" in symptom_section:
            fault, device, obj = "interface_down", "core_sw2", "GigabitEthernet0/2"
        elif "dns" in symptom_section or "192.168.80" in symptom_section:
            fault, device, obj = "missing_route", "dsw_d_dc", "192.168.80.0/24"
        elif "academic" in symptom_section or "192.168.20" in symptom_section:
            fault, device, obj = "missing_route", "dsw_a_acad", "192.168.20.0/24"
        elif "student" in symptom_section and "uplink" in symptom_section:
            fault, device, obj = "interface_down", "core_sw1", "GigabitEthernet0/1"
        elif "student" in symptom_section or "192.168.30" in symptom_section:
            fault, device, obj = "missing_route", "dsw_b_student", "192.168.30.0/24"
        elif "entire faculty" in symptom_section or (
            "shutdown" in symptom_section and "uplink" in symptom_section
        ):
            fault, device, obj = "interface_down", "core_sw1", "GigabitEthernet0/1"
        else:
            fault, device, obj = "unknown", None, None

        return json.dumps(
            {
                "root_cause": f"Likely {fault} on {device}",
                "fault_type": fault,
                "device": device,
                "confidence": 0.55,
                "explanation": "Inferred from symptom language without mandatory rule validation.",
                "evidence_used": ["symptom"],
                "remediation": ["Manually validate with show ip route / show access-lists"],
                "uncertainties": ["LLM-only mode; may hallucinate without Batfish grounding"],
            }
        )


def get_llm_backend(settings=None) -> LLMBackend:
    from campus_rca.config import get_settings

    settings = settings or get_settings()
    if settings.llm_backend == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY required when LLM_BACKEND=openai")
        return OpenAIBackend(
            settings.openai_api_key, settings.openai_model, settings.llm_temperature
        )
    if settings.llm_backend == "ollama":
        return OllamaBackend(
            settings.ollama_base_url,
            settings.ollama_model,
            settings.llm_temperature,
            settings.ollama_timeout_s,
        )
    return MockBackend()
