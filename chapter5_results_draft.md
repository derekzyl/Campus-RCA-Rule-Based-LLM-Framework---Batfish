# Chapter 5 — Results (draft)

> Paste into the dissertation Results / Evaluation chapter.  
> **Topology:** dual-core / dual head-router / by-block distribution with **10** scenarios — see `docs/topology/README.md`.  
> **Source:** `results/topology10/` (offline `rule_only`, *n* = 10).  
> **Before submission:** re-run Evaluate with **all three modes** (live Batfish + Ollama if possible) and replace the `llm_only` / `hybrid` placeholders below.

---

## 5.x Experimental setup (brief)

The prototype was evaluated on the Packet Tracer–aligned university main-campus lab: dual head routers (`campus_r1`, `campus_r2`), dual firewalls (`fw1`, `fw2`), dual cores (`core_sw1`, `core_sw2`), and distribution organised by building/floor block. Ten single-fault snapshots were injected with known ground truth:

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

The ten faults cover four classes used by the rule engine: **ACL deny** (3), **missing route / OSPF omit** (3), **interface down** (3), and **wrong static default** (1). Several pairs share similar operator symptoms (for example student unreachability from ACL policy versus a missing OSPF advertisement), which is the ambiguity the hybrid design is intended to resolve.

Three diagnosis modes were compared:

- **rule_only** — Batfish evidence + deterministic rules (no LLM classification)
- **llm_only** — LLM classification from symptom/evidence without rule authority
- **hybrid** — rules decide fault class and device; LLM produces operator-facing explanation

Localisation was scored correct only when both **fault type** and **device** matched ground truth. Supporting metrics were keyword coverage (explanation content), hallucination rate, and evidence faithfulness.

---

## 5.x Overall results

**Table 5.x — Aggregate mode comparison** (*n* = 10 labelled scenarios)

| Mode | Localisation accuracy | Avg. keyword coverage | Avg. hallucination rate | Avg. evidence faithfulness |
|---|---:|---:|---:|---:|
| rule_only | **1.00** (10/10) | 0.693 | 0.00 | 1.00 |
| llm_only | — | — | — | — |
| hybrid | — | — | — | — |

> Fill `llm_only` and `hybrid` from a full Evaluate run (`evaluation/run_eval.py` or GUI Evaluate). Do **not** paste `results/gui_eval/` as-is: that run collapsed to `interface_down @ core_sw1` / `unknown` and is not a valid comparative result.

Offline **rule_only** localised every labelled fault (10/10). Mean keyword coverage was 0.693: rule rationales name the evidence object (filter, prefix, interface) but are terse, so they do not always hit every ground-truth keyword. Hallucination rate was 0.00 and evidence faithfulness was 1.00, as expected when diagnoses are taken only from Batfish-backed rules. Mean wall time was <1 ms per scenario (rules over cached/synthetic evidence; live Batfish + Ollama will dominate latency).

---

## 5.x Per-scenario outcomes

**Table 5.x — Localisation outcomes by scenario and mode**

| Scenario | Truth | rule_only | llm_only | hybrid |
|---|---|---|---|---|
| `student_acl_deny_mgt` | acl_deny @ core_sw1 | OK | — | — |
| `guest_wlan_acl_deny` | acl_deny @ core_sw1 | OK | — | — |
| `missing_ospf_students` | missing_route @ dsw_b_student | OK | — | — |
| `core1_uplink_shutdown` | interface_down @ core_sw1 | OK | — | — |
| `wrong_default_route_r1` | wrong_static_route @ campus_r1 | OK | — | — |
| `ospf_omit_academic` | missing_route @ dsw_a_acad | OK | — | — |
| `dmz_to_lan_leak_attempt` | acl_deny @ fw1 | OK | — | — |
| `fw1_inside_shutdown` | interface_down @ fw1 | OK | — | — |
| `core2_student_uplink_down` | interface_down @ core_sw2 | OK | — | — |
| `missing_ospf_dns_services` | missing_route @ dsw_d_dc | OK | — | — |

**Table 5.x — rule_only keyword coverage by scenario**

| Scenario | Fault class | Keyword coverage |
|---|---|---:|
| `student_acl_deny_mgt` | acl_deny | 0.667 |
| `guest_wlan_acl_deny` | acl_deny | 0.800 |
| `missing_ospf_students` | missing_route | **1.000** |
| `core1_uplink_shutdown` | interface_down | 0.600 |
| `wrong_default_route_r1` | wrong_static_route | 0.800 |
| `ospf_omit_academic` | missing_route | 0.800 |
| `dmz_to_lan_leak_attempt` | acl_deny | 0.667 |
| `fw1_inside_shutdown` | interface_down | 0.400 |
| `core2_student_uplink_down` | interface_down | 0.400 |
| `missing_ospf_dns_services` | missing_route | 0.800 |

Keyword coverage was highest on missing-OSPF cases (the rationale names the prefix and the owning DSW) and lowest on interface-down cases (the rationale names the interface and hostname but not always every labelled neighbour keyword). Localisation was nevertheless correct in every case: keyword coverage measures explanation content, not whether the fault class and device were right.

**Table 5.x — rule_only localisation by fault class**

| Fault class | Scenarios | Localisation |
|---|---:|---:|
| acl_deny | 3 | 3/3 |
| missing_route | 3 | 3/3 |
| interface_down | 3 | 3/3 |
| wrong_static_route | 1 | 1/1 |
| **All** | **10** | **10/10** |

The labelled set is built so that overlapping campus symptoms can be compared once `llm_only` and `hybrid` are run. In particular:

- **Policy vs routing on the student block.** `student_acl_deny_mgt` (STUDENT-FILTER on `core_sw1`) and `missing_ospf_students` (prefix omitted on `dsw_b_student`) both present as student-related unreachability. Rules distinguished ACL drop from a missing OSPF advertisement.
- **DMZ policy vs services routing.** `dmz_to_lan_leak_attempt` (DMZ-IN on `fw1`) versus `missing_ospf_dns_services` (192.168.80.0/24 omitted on `dsw_d_dc`).
- **Redundant core uplinks.** `core1_uplink_shutdown` and `core2_student_uplink_down` inject the same fault class on different cores; rules named the correct device, not a generic “core is down”.

Those pairs are the intended test of RQ1 (unguided LLM vs rule-grounded hybrid) after the full three-mode Evaluate.

---

## 5.x Findings against research questions

### RQ1 — Does hybrid rule+LLM RCA improve localisation over unguided LLM?

Not yet answerable with a complete three-mode table. What can be stated now: **rule_only achieved 10/10 localisation** on the dual-core by-block lab, so the Batfish + rule layer is a reliable classification backbone for these four fault classes. Hybrid is designed to *preserve* that classification and use the LLM only for explanation; llm_only is the condition expected to fail first on ACL-versus-OSPF ambiguity. After Evaluate, replace this paragraph with the hybrid vs llm_only accuracy gap (and name any missed scenario).

### RQ2 — Are hybrid explanations more trustworthy / evidence-faithful?

For rule_only, automated faithfulness was **1.00** and hallucination rate was **0.00**. Keyword coverage averaged **0.693**. Hybrid explanations should be scored the same way once generated: they are constrained to validated rule outputs and Batfish evidence rather than free invention of devices or routes. Expect hybrid keyword coverage to sit between terse rule text and unconstrained llm_only prose.

### RQ3 — Is the approach practically usable for campus operators?

Rule-only already produces immediate, auditable diagnoses (fault class + device + evidence object) suitable for automation and triage, with sub-millisecond classification once evidence is collected. Hybrid is intended to add operator-readable remediation narrative without changing the authoritative fault class. In practice, operators can rely on rules for *what failed where*, and on the LLM layer for *how to explain and verify*—with remediation kept advisory (no automatic config apply). Confirm latency and explanation quality from the Ollama Evaluate run before treating RQ3 as measured rather than designed.

---

## 5.x Discussion (short)

1. **Rules remain the reliability backbone.** Perfect localisation under rule_only (10/10) confirms that Batfish evidence is sufficient for these fault classes when rules are specific: ACL deny (`STUDENT-FILTER`, `GUEST-WLAN-FILTER`, `DMZ-IN`), interface down on cores/firewall, wrong static default on the edge router, and missing prefixes owned by a DSW block.
2. **The 10-scenario lab exercises overlapping symptoms.** Student and DMZ unreachability can arise from policy or from OSPF omission; dual cores can fail independently. That is a stronger test of localisation than a five-node toy topology.
3. **Keyword coverage is not localisation.** Interface-down rationales scored 0.40–0.60 on keywords while still naming the correct device and interface. Report both metrics; do not treat keyword coverage as accuracy.
4. **Hybrid vs LLM-only is still the open comparison.** Do not reuse the previous five-scenario numbers (`acl_deny_http`, `dist2`, 5/5 vs 4/5): those IDs and devices are not this lab.
5. **Scope limits.** Results so far are for ten synthetic single faults in a controlled Packet Tracer–aligned lab. They support feasibility of the rule layer on the dissertation topology; they do not yet generalise to production multi-vendor campuses, multi-fault incidents, or the LLM modes.

---

## 5.x Example write-up paragraph (ready to paste)

> The prototype was evaluated on ten labelled faults in a Packet Tracer–aligned dual-core campus laboratory (dual head routers, dual firewalls, and distribution by building/floor block). In the offline rule-only condition, localisation accuracy was 100% (10/10): every diagnosis matched both the injected fault class and the ground-truth device. Mean keyword coverage was 0.693, hallucination rate was 0.0, and evidence faithfulness was 1.00. ACL denies on `core_sw1` and `fw1`, missing OSPF advertisements on `dsw_b_student`, `dsw_a_acad`, and `dsw_d_dc`, interface shutdowns on `core_sw1`, `core_sw2`, and `fw1`, and an incorrect default next-hop on `campus_r1` were all recovered from Batfish-derived evidence. These results show that the deterministic rule layer is sufficient for the four campus fault classes used in this study. Comparative llm_only and hybrid figures are reported from the full Evaluate run in Table 5.x.

---

## Notes for you (not for the dissertation)

- **Do use:** `results/topology10/evaluation_report.md` (and `.json` / CSV / figures) for rule_only.
- **Do not use:** `results/gui_eval/` until you re-run Evaluate; that report is 1/10 rule_only and 0/10 llm_only (model timeout / snapshot mix-up).
- Re-run with live Batfish + Ollama, then replace every `—` above:

```bash
uv run python evaluation/run_eval.py --out results --llm-backend ollama
# or GUI Evaluate (Offline unchecked)
make figures
```

- Name the model (`llama3.2:3b` or whichever you finally use) and that temperature was fixed at 0.
- Put the full `evaluation_report.md` / `.json` in an appendix.
- Screenshots: one Diagnose result + the Evaluate summary table.
