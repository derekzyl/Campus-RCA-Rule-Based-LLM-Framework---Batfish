# Campus RCA — Rule-Based LLM Framework (Batfish)

Prototype for the dissertation *Design and Evaluation of a Rule-Based LLM Framework for Root Cause Analysis in Campus Network Using Batfish*.

Campus lab topology (Packet Tracer aligned): **dual cores**, **dual head routers**, **distribution-by-block**, and **10 labelled scenarios** — see [`docs/topology/README.md`](docs/topology/README.md).

Hybrid pipeline:

1. **Batfish** — deterministic reachability, routes, interfaces, ACL/filter evidence  
2. **Python rules** — transparent mapping of evidence → fault classes  
3. **LLM (Ollama)** — evidence-grounded explanation + remediation (advisory only)

Evaluation modes: `rule_only` | `llm_only` | `hybrid` (RQ1–RQ3).

---

## Quick start (novice — one click)

```bash
cd /path/to/sal
chmod +x run.sh
./run.sh
```

`run.sh` will:

1. Detect OS / CPU architecture  
2. Check Python 3.10+ and Tkinter  
3. Install **uv** if needed and run `uv sync`  
4. Ensure **Ollama** is running and let you choose a **local** model (no re-download if present)  
5. Try to start **Batfish** via Podman/Docker; if unavailable, fall back to offline evidence  
6. Open the **Tkinter GUI**

```bash
./run.sh --skip-batfish    # no containers
./run.sh --setup-only      # bootstrap only
make run                   # same as ./run.sh
```

On Parrot/Fedora (docker → podman shim):

```bash
systemctl --user enable --now podman.socket
./scripts/ensure_batfish.sh
```

Requires [uv](https://docs.astral.sh/uv/) and Ollama. Tkinter on Debian/Ubuntu/Parrot:

```bash
sudo apt install python3-tk
```

### GUI tabs

| Tab | What it does |
|---|---|
| **1. Setup** | Readiness checks, uv sync, start Ollama, choose local model, start Batfish |
| **2. Diagnose** | Pick one of 10 scenarios + mode (`rule_only` / `llm_only` / `hybrid`), run RCA |
| **3. Evaluate** | All scenarios × 3 modes → scored report |
| **4. Results** | Browse JSON/MD/CSV/TeX/PNG; **Generate figures**; open charts folder |

Manual GUI: `uv run campus-rca-gui`

---

## CLI

```bash
uv sync
cp -n .env.example .env

# List the 10 scenarios
uv run campus-rca list-scenarios

# Fast deterministic path (recommended on CPU)
uv run campus-rca diagnose student_acl_deny_mgt --mode rule_only --offline

# Hybrid (rules classify + Ollama explains)
uv run campus-rca diagnose missing_ospf_students --mode hybrid --offline

# Full evaluation (10 × 3 modes)
uv run python evaluation/run_eval.py --offline --llm-backend ollama --out results
# or mock LLM for CI/demo:
uv run python evaluation/run_eval.py --offline --llm-backend mock --modes rule_only --out results
```

### Tables & charts (Chapter 5)

```bash
make figures
# or:
uv run python evaluation/plot_results.py --report results/evaluation_report.json
# GUI Evaluate also writes under results/gui_eval/ and can Generate figures
```

Outputs:

| File | Use |
|---|---|
| `evaluation_report.md` / `.json` | Summary + per-scenario scores |
| `evaluation_summary.csv` / `evaluation_rows.csv` | Excel / Sheets |
| `evaluation_tables.tex` | LaTeX Chapter 5 |
| `figures/fig_*.png` | Accuracy, metrics, OK/MISS matrix, latency |

On **WSL** (especially projects under `/mnt/c/...`), figure export uses a Pillow fallback if matplotlib/FreeType hits raster overflow.

---

## Full stack with live Batfish

```bash
./scripts/start_batfish.sh   # or: docker compose up -d / ./scripts/ensure_batfish.sh
cp -n .env.example .env      # USE_BATFISH=true, LLM_BACKEND=ollama

uv run campus-rca diagnose guest_wlan_acl_deny --mode hybrid
uv run python evaluation/run_eval.py --out results
```

---

## LLM backends

| `LLM_BACKEND` | Notes |
|---|---|
| `ollama` | **Default for this project** — local model, ethics-friendly |
| `openai` | Needs `OPENAI_API_KEY`, temperature 0.0 |
| `gemini` | Needs `GEMINI_API_KEY` (Google AI Studio), `GEMINI_MODEL=gemini-3.6-flash` |
| `mock` | Deterministic stand-in for CI / offline demos |

```bash
./scripts/setup_ollama.sh
uv run campus-rca check-llm
```

Notes:

- Local models are **listed and reused** (GUI/launcher ask which to use).  
- Prompts are **compacted** for CPU.  
- Tunables: `OLLAMA_MODEL`, `OLLAMA_TIMEOUT_S`, `OLLAMA_NUM_PREDICT` (use ≥512 so local models can finish JSON). 
- Hybrid: **rules decide fault/device**; LLM explains only.

---

## HTTP API

```bash
uv run campus-rca serve --host 127.0.0.1 --port 8080
# GET  /health
# GET  /scenarios
# POST /diagnose {"scenario_id":"student_acl_deny_mgt","mode":"hybrid","offline":true}
```

---

## Project layout

```text
run.sh                         # one-click: checks → Ollama → Batfish → GUI
docs/
  topology/                    # Packet Tracer diagram + topology + justification
  data_generation.md           # under-the-hood data flow
configs/baseline/              # dual-core dual-edge by-block snapshots
configs/scenarios/<id>/        # 10 faulted snapshots
ground_truth/scenarios.yaml    # labels for scoring
scripts/
  generate_campus_topology.py  # rebuild baseline + scenarios
  ensure_batfish.sh            # Podman/Docker Batfish
  select_ollama_model.sh       # pick local Ollama model
src/campus_rca/
  batfish_client.py            # evidence (+ synthetic offline fallback)
  rules/engine.py              # R0–R5 using docs/topology campus ACL/VLAN policy
  campus_policy.py             # STUDENT-FILTER / GUEST-WLAN-FILTER / DMZ-IN ACE matchers
  llm/                         # prompts + ollama/openai/gemini/mock
  pipeline.py                  # rule_only / llm_only / hybrid
  gui.py                       # Tkinter UI
evaluation/
  run_eval.py                  # comparative evaluation
  metrics.py                   # accuracy, keywords, faithfulness
  plot_results.py              # CSV / LaTeX / PNG export
results/                       # reports, tables, figures
```

---

## Documentation index

| Doc | Contents |
|---|---|
| [`docs/topology/README.md`](docs/topology/README.md) | Packet Tracer topology, devices, 10 scenarios, image justification |
| [`docs/data_generation.md`](docs/data_generation.md) | How evidence → rules → LLM → scores → charts works |
| [`chapter5_results_draft.md`](chapter5_results_draft.md) | Draft Chapter 5 results text (re-run eval after topology update) |

---

## Safety / ethics

- Diagnostics are **read-only**; remediation is advisory (`ALLOW_REMEDIATION_APPLY=false`).
- Prefer local Ollama when prompts include campus configs.
- Lab topology is synthetic — no live institutional traffic.

---

## Dissertation mapping

| Objective | Artifact |
|---|---|
| Campus design case study | Packet Tracer figure + `docs/topology/` |
| Rule-based verification | `rules/engine.py` + Batfish evidence |
| LLM on validated evidence | hybrid mode in `pipeline.py` + `llm/` |
| Scenario evaluation (n=10) | `evaluation/run_eval.py` + `ground_truth/scenarios.yaml` |
| Compare rule / LLM / hybrid | three modes + `results/` + figures |
