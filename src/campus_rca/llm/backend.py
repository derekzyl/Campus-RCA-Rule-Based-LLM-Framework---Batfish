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

    # Reasoning models may wrap JSON in think tags
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"</?think>", "", text, flags=re.IGNORECASE).strip()

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
                if isinstance(data, dict) and (
                    data.get("fault_type") or data.get("device") or data.get("root_cause")
                ):
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
                if isinstance(data, dict) and (
                    data.get("fault_type") or data.get("device") or data.get("root_cause")
                ):
                    return data
            except json.JSONDecodeError as exc:
                last_err = exc

    salvaged = _salvage_partial_json(text)
    if salvaged.get("fault_type") or salvaged.get("device"):
        return salvaged

    if last_err:
        raise last_err
    raise json.JSONDecodeError("No JSON object found", text, 0)


_HOST_RE = re.compile(
    r"\b(campus_r1|campus_r2|fw1|fw2|core_sw1|core_sw2|"
    r"dsw_a_admin|dsw_a_acad|dsw_b_lib|dsw_b_student|dsw_c_lab|"
    r"dsw_d_dc|dsw_d_media|dsw_dmz)\b",
    re.I,
)


def _salvage_partial_json(text: str) -> dict[str, Any]:
    """Recover fault_type/device from truncated or prose-y model output."""
    out: dict[str, Any] = {}
    ft = re.search(r'"fault_type"\s*:\s*"([^"]+)"', text)
    if ft:
        out["fault_type"] = ft.group(1)
    dev = re.search(r'"device"\s*:\s*"([^"]+)"', text)
    if dev:
        out["device"] = dev.group(1)
    rc = re.search(r'"root_cause"\s*:\s*"(.*)', text)
    if rc:
        out["root_cause"] = rc.group(1).split('"')[0]
        out.setdefault("explanation", out["root_cause"])
    blob = text.lower()
    if not out.get("device"):
        host = _HOST_RE.search(text)
        if host:
            out["device"] = host.group(1).lower()
    if not out.get("fault_type"):
        if any(w in blob for w in ("acl", "filter", "deny")):
            out["fault_type"] = "acl_deny"
        elif "shutdown" in blob or ("interface" in blob and "down" in blob):
            out["fault_type"] = "interface_down"
        elif "next-hop" in blob or "nexthop" in blob or (
            "default" in blob and "static" in blob
        ):
            out["fault_type"] = "wrong_static_route"
        elif any(w in blob for w in ("advertis", "ospf", "missing", "no_route", "prefix")):
            out["fault_type"] = "missing_route"
    if out:
        out.setdefault("confidence", 0.6)
        out.setdefault("evidence_used", ["cues"])
        out.setdefault("remediation", [])
        out.setdefault("uncertainties", ["Salvaged from truncated LLM JSON"])
        out.setdefault("explanation", out.get("root_cause") or "")
    return out


def _fallback_diagnosis(raw: str, rules: RuleDiagnosis | None) -> LLMDiagnosis:
    """When the model fails or returns unparseable JSON, keep the run alive."""
    api_fail = (raw or "").startswith("LLM error:")
    if api_fail:
        uncertainty = "LLM backend failed — using rule diagnosis"
        claim = (raw or "")[:240]
        unknown_expl = (raw or "LLM backend failed.")[:300]
    else:
        uncertainty = "LLM JSON parse failed — using rule diagnosis"
        claim = "LLM response was not valid JSON"
        unknown_expl = "Model returned invalid JSON; no rule diagnosis available."
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
            uncertainties=[uncertainty],
            raw_text=raw,
            hallucinated_claims=[claim],
        )
    return LLMDiagnosis(
        root_cause="LLM unavailable" if api_fail else "LLM response unparseable",
        fault_type="unknown",
        device=None,
        confidence=0.0,
        explanation=unknown_expl,
        evidence_used=[],
        remediation=[],
        uncertainties=[uncertainty.replace(" — using rule diagnosis", "")],
        raw_text=raw,
        hallucinated_claims=[claim],
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
        try:
            raw = self.complete(SYSTEM_PROMPT, user)
        except Exception as exc:  # noqa: BLE001
            return _fallback_diagnosis(f"LLM error: {exc}", rules)
        return self._to_diagnosis(raw, grounded=True, evidence=evidence, rules=rules)

    def diagnose_llm_only(self, symptom: str, evidence: EvidenceBundle) -> LLMDiagnosis:
        user = build_llm_only_user_prompt(symptom, evidence)
        try:
            raw = self.complete(SYSTEM_PROMPT, user)
        except Exception as exc:  # noqa: BLE001
            return _fallback_diagnosis(f"LLM error: {exc}", None)
        diag = self._to_diagnosis(raw, grounded=False, evidence=evidence, rules=None)
        if diag.fault_type != "unknown":
            return diag
        try:
            raw2 = self.complete(
                SYSTEM_PROMPT,
                build_llm_only_user_prompt(symptom, evidence)
                + "\nPrevious reply was invalid JSON. Output one JSON object now.",
            )
        except Exception:  # noqa: BLE001
            return diag
        return self._to_diagnosis(raw2, grounded=False, evidence=evidence, rules=None)

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

        if not data.get("fault_type") and not data.get("device"):
            return _fallback_diagnosis(raw or "Empty LLM JSON", rules)

        fault = _normalize_fault(_as_str(data.get("fault_type", "unknown")))

        try:
            diag = LLMDiagnosis(
                root_cause=_as_str(data.get("root_cause")),
                fault_type=fault,
                device=_as_device(data.get("device")),
                confidence=_as_float(data.get("confidence"), 0.5),
                explanation=_as_str(data.get("explanation")),
                evidence_used=_as_str_list(data.get("evidence_used")),
                remediation=_as_str_list(data.get("remediation")),
                uncertainties=_as_str_list(data.get("uncertainties")),
                raw_text=raw,
            )
        except Exception:  # noqa: BLE001
            return _fallback_diagnosis(raw, rules)
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


_FAULT_TYPES = (
    "wrong_static_route",
    "interface_down",
    "missing_route",
    "ospf_neighbor",
    "acl_deny",
    "unknown",
)


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("rule_id", "rationale", "filter", "explanation", "root_cause"):
            if value.get(key):
                return str(value[key])
        return json.dumps(value, default=str)[:240]
    if isinstance(value, list):
        return "; ".join(_as_str(v) for v in value if v is not None)
    return str(value)


def _as_device(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("device") or value.get("hostname") or value.get("Node")
    text = _as_str(value).strip()
    if not text or text.lower() in {"null", "none", "hostname or null", "hostname", "n/a"}:
        return None
    return text


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, list):
        text = _as_str(value)
        return [text] if text else []
    out: list[str] = []
    for item in value:
        text = _as_str(item).strip()
        if text:
            out.append(text)
    return out


def _normalize_fault(raw: str) -> str:
    s = (raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if s in _FAULT_TYPES:
        return s
    for token in re.split(r"[|,/;]+", s):
        t = token.strip().strip("\"'")
        if t in _FAULT_TYPES:
            return t
    for name in _FAULT_TYPES:
        if name in s:
            return name
    return "unknown"


_SUGGESTED_GEMINI = re.compile(r"models/([a-zA-Z0-9._-]+)")


class GeminiBackend(LLMBackend):
    """Google Gemini generateContent API (online)."""

    # 2.0 / 2.5 Flash are retired for new AI Studio keys (404 → use 3.x).
    FALLBACK_MODELS = (
        "gemini-3.6-flash",
        "gemini-3.7-flash",
        "gemini-3.5-flash",
        "gemini-flash-latest",
        "gemini-3.1-flash-lite",
    )

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.6-flash",
        temperature: float = 0.0,
        timeout_s: float = 120.0,
    ):
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout_s = timeout_s
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    def _headers(self) -> dict[str, str]:
        # Header auth so a 503/404 never logs ?key= in the URL
        return {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}

    def ping(self) -> dict:
        import httpx

        last_err: str | None = None
        for model in self._models_to_try():
            url = f"{self.base_url}/models/{model}"
            with httpx.Client(timeout=15.0) as client:
                r = client.get(url, headers=self._headers())
            if r.status_code == 200:
                self.model = model
                return {"ok": True, "model": model, "backend": "gemini"}
            last_err = f"HTTP {r.status_code}"
        raise RuntimeError(
            f"Gemini model '{self.model}' is unavailable ({last_err}). "
            "Set GEMINI_MODEL to gemini-3.6-flash or gemini-flash-latest."
        )

    def _models_to_try(self) -> list[str]:
        seen: list[str] = []
        for name in (self.model, *self.FALLBACK_MODELS):
            if name and name not in seen:
                seen.append(name)
        return seen

    def complete(self, system: str, user: str) -> str:
        import time

        import httpx

        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": self.temperature,
                "responseMimeType": "application/json",
                "maxOutputTokens": 8192,
            },
        }
        last_status = 0
        tried: list[str] = []
        try:
            with httpx.Client(timeout=httpx.Timeout(self.timeout_s, connect=15.0)) as client:
                models = self._models_to_try()
                idx = 0
                while idx < len(models):
                    model = models[idx]
                    idx += 1
                    if model in tried:
                        continue
                    tried.append(model)
                    url = f"{self.base_url}/models/{model}:generateContent"
                    empty = False
                    for attempt in range(1, 4):
                        r = client.post(url, headers=self._headers(), json=payload)
                        last_status = r.status_code
                        if r.status_code == 404:
                            for suggested in _SUGGESTED_GEMINI.findall(r.text or ""):
                                if suggested not in tried and suggested not in models:
                                    models.append(suggested)
                            break
                        if r.status_code in {429, 503} and attempt < 3:
                            time.sleep(2 * attempt)
                            continue
                        if r.status_code == 503:
                            break
                        if r.status_code == 400:
                            raise RuntimeError(
                                f"Gemini rejected the request for '{model}' (HTTP 400)."
                            )
                        if r.status_code in {401, 403}:
                            raise RuntimeError(
                                "Gemini API key rejected. Check GEMINI_API_KEY "
                                "(https://aistudio.google.com/apikey)."
                            )
                        if r.status_code >= 400:
                            raise RuntimeError(
                                f"Gemini HTTP {r.status_code} for model '{model}'."
                            )
                        data = r.json()
                        text = self._candidate_text(data)
                        if not text:
                            empty = True
                            break
                        self.model = model
                        return text
                    if empty:
                        continue
        except httpx.ConnectError as exc:
            raise RuntimeError("Cannot reach Gemini API.") from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"Gemini timed out after {self.timeout_s:.0f}s for model '{self.model}'."
            ) from exc

        raise RuntimeError(
            f"Gemini model '{self.model}' unavailable (HTTP {last_status}). "
            "Set GEMINI_MODEL=gemini-3.6-flash and retry."
        )

    @staticmethod
    def _candidate_text(data: dict) -> str:
        cands = data.get("candidates") or []
        if not cands:
            return ""
        parts = (cands[0].get("content") or {}).get("parts") or []
        visible = "".join(p.get("text") or "" for p in parts if not p.get("thought"))
        text = (visible or "".join(p.get("text") or "" for p in parts)).strip()
        if text in {"", "{}", "null"}:
            return ""
        return text


class OllamaBackend(LLMBackend):
    def __init__(
        self,
        base_url: str,
        model: str,
        temperature: float = 0.0,
        timeout_s: float = 600.0,
        num_predict: int = 512,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout_s = timeout_s
        self.num_predict = num_predict

    def ping(self) -> dict:
        import httpx

        with httpx.Client(timeout=10.0) as client:
            r = client.get(f"{self.base_url}/api/tags")
            r.raise_for_status()
            models = [m.get("name", "") for m in r.json().get("models", [])]
            return {"ok": True, "models": models, "selected": self.model}

    def complete(self, system: str, user: str) -> str:
        import httpx

        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "think": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.num_predict,
            },
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            return self._chat(payload)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 400 and "think" in payload:
                payload.pop("think", None)
                return self._chat(payload)
            raise

    def _chat(self, payload: dict[str, Any]) -> str:
        import httpx

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

        if "Validated rule diagnosis" in user and rule_match:
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
    if settings.llm_backend == "gemini":
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY required when LLM_BACKEND=gemini")
        return GeminiBackend(
            settings.gemini_api_key,
            settings.gemini_model,
            settings.llm_temperature,
        )
    if settings.llm_backend == "ollama":
        return OllamaBackend(
            settings.ollama_base_url,
            settings.ollama_model,
            settings.llm_temperature,
            settings.ollama_timeout_s,
            settings.ollama_num_predict,
        )
    return MockBackend()
