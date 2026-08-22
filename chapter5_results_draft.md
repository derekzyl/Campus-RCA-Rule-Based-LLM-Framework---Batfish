# Chapter 5 — Results (draft)

> Paste into the dissertation Results / Evaluation chapter.  
> **Topology:** dual-core / dual head-router / by-block distribution with **10** scenarios — see `docs/topology/README.md`.  
> **Before submission:** re-run Evaluate (live Batfish + Ollama if possible), then replace the numbers below. Older tables below may still reflect the previous 5-scenario offline run.

---

## 5.x Experimental setup (brief)

The prototype targets the Packet Tracer–aligned dual-core campus lab (see `docs/topology/README.md`) with **ten** injected faults and known ground truth:

| Scenario ID | Injected fault | Device |
|---|---|---|
| `student_acl_deny_mgt` | STUDENT-FILTER ACL deny | core_sw1 |
| `guest_wlan_acl_deny` | GUEST-WLAN-FILTER ACL deny | core_sw1 |
| `missing_ospf_students` | Student VLAN not in OSPF | dsw_b_student |
| `core1_uplink_shutdown` | Core uplink shut | core_sw1 |
| `wrong_default_route_r1` | Bad default next-hop | campus_r1 |
| `ospf_omit_academic` | Academic VLAN not in OSPF | dsw_a_acad |
| `dmz_to_lan_leak_attempt` | DMZ-IN ACL deny | fw1 |
| `fw1_inside_shutdown` | Firewall inside link shut | fw1 |
| `core2_student_uplink_down` | Redundant core uplink shut | core_sw2 |
| `missing_ospf_dns_services` | Services/DNS VLAN not in OSPF | dsw_d_dc |

Three diagnosis modes were compared:

- **rule_only** — Batfish evidence + deterministic rules (no LLM classification)
- **llm_only** — LLM classification from symptom/evidence without rule authority
- **hybrid** — rules decide fault class and device; LLM produces operator-facing explanation

Localisation was scored correct only when both **fault type** and **device** matched ground truth. Supporting metrics were keyword coverage (explanation content), hallucination rate, and evidence faithfulness.

> Offline `rule_only` smoke test on the 10-scenario lab reported **10/10** localisation correct. Replace aggregate tables below after a full Evaluate run (rule_only + llm_only + hybrid).

---

## 5.x Overall results

**Table 5.x — Aggregate mode comparison**

| Mode | Localisation accuracy | Avg. keyword coverage | Avg. hallucination rate | Avg. evidence faithfulness |
|---|---:|---:|---:|---:|
| rule_only | **1.00** (5/5) | 0.813 | 0.00 | 1.00 |
| llm_only | 0.80 (4/5) | 0.380 | 0.00 | 1.00 |
| hybrid | **1.00** (5/5) | 0.573 | 0.00 | 1.00 |

Rule-only and hybrid both localised every labelled fault. LLM-only missed one scenario, reducing accuracy to 80%. Keyword coverage was highest for rule-only (rationale text is tied tightly to evidence objects), while hybrid traded some keyword density for natural-language explanation. Hallucination rate remained zero under the automated checks used in this run; faithfulness scores were high across modes that cited Batfish-derived evidence keys.

---

## 5.x Per-scenario outcomes

**Table 5.x — Localisation outcomes by scenario and mode**

| Scenario | Truth | rule_only | llm_only | hybrid |
|---|---|---|---|---|
| acl_deny_http | acl_deny @ dist2 | OK | OK | OK |
| missing_ospf_network | missing_route @ dist1 | OK | OK | OK |
| interface_shutdown | interface_down @ core1 | OK | OK | OK |
| wrong_static_route | wrong_static_route @ core1 | OK | OK | OK |
| ospf_passive_misconfig | missing_route @ dist2 | OK | **MISS** → acl_deny @ dist2 | OK |

The single LLM-only failure is analytically important. For `ospf_passive_misconfig`, student-to-faculty unreachability coexists with campus ACL artefacts in the evidence. Without rule authority, the unguided LLM attributed the symptom to **policy (ACL)** on dist2 rather than the injected **missing OSPF advertisement**. Hybrid retained the correct rule classification (`missing_route` @ dist2) while still producing an explanation—showing that grounding classification in Batfish-validated rules reduces ambiguity between overlapping ACL and routing symptoms.

---

## 5.x Findings against research questions

### RQ1 — Does hybrid rule+LLM RCA improve localisation over unguided LLM?

Yes, on this labelled set. Hybrid matched rule-only at **5/5**, while llm_only achieved **4/5**. The gap is concentrated in the OSPF-vs-ACL ambiguity case, which is exactly the class of overlapping campus symptoms the hybrid design targets.

### RQ2 — Are hybrid explanations more trustworthy / evidence-faithful?

Automated faithfulness remained high (1.00 in this report) and hallucination rate was 0.00. Hybrid explanations are constrained to validated rule outputs and Batfish evidence rather than free invention of devices or routes. Keyword coverage for hybrid (0.573) was lower than rule-only (0.813) but higher than llm_only (0.380), consistent with explanations that are readable yet still anchored to labelled objects (device, ACL/route names).

### RQ3 — Is the approach practically usable for campus operators?

Rule-only produces immediate, auditable diagnoses suitable for automation and triage. Hybrid adds operator-readable remediation narrative without changing the authoritative fault class. In practice, operators can rely on rules for *what failed where*, and on the LLM layer for *how to explain and verify*—with remediation kept advisory (no automatic config apply).

---

## 5.x Discussion (short)

1. **Rules remain the reliability backbone.** Perfect localisation under rule_only confirms that Batfish evidence is sufficient for these fault classes when rules are specific (ACL deny, interface down, wrong static on routers, missing prefixes).
2. **LLM-only is brittle under ambiguity.** The OSPF passive miss shows that symptom language plus mixed evidence can push an unguided model toward a plausible but incorrect policy cause.
3. **Hybrid preserves accuracy while improving communication.** Classification follows rules; explanation follows the LLM. This separation is the core design claim of the framework.
4. **Scope limits.** Results are for five synthetic campus faults in a controlled lab topology. They support feasibility and comparative behaviour of the three modes; they do not yet generalise to production multi-vendor campuses or multi-fault incidents.

---

## 5.x Example write-up paragraph (ready to paste)

> Across five labelled campus scenarios, the rule-only and hybrid modes achieved 100% localisation accuracy (fault type and device), while llm_only achieved 80%. The llm_only miss occurred on `ospf_passive_misconfig`, where the model incorrectly predicted an ACL deny on dist2 instead of a missing OSPF route. Hybrid retained the correct rule diagnosis and used the LLM only for explanation, supporting the claim that rule-grounded classification improves RCA reliability under overlapping routing and policy symptoms. Keyword coverage was highest for rule_only (0.813), followed by hybrid (0.573) and llm_only (0.380). Automated hallucination rate was 0.0 and evidence faithfulness remained high across modes in this evaluation run.

---

## Notes for you (not for the dissertation)

- If your examiner expects **live Batfish + Ollama** numbers, re-run Evaluate (Offline unchecked), replace the table values, and keep screenshots of one Diagnose + the Evaluate summary.
- Mention model name (`llama3.2:3b` or whichever you finally use) and that temperature was fixed at 0 for reproducibility.
- Put the full `evaluation_report.md` / `.json` in an appendix.
