# Campus RCA — Rule-Based LLM Framework (Batfish)

Prototype for the dissertation *Design and Evaluation of a Rule-Based LLM Framework for Root Cause Analysis in Campus Network Using Batfish*.

Campus lab topology (Packet Tracer aligned): **dual cores**, **dual head routers**, **distribution-by-block**, and **10 labelled scenarios** — see [`docs/topology/README.md`](docs/topology/README.md).
Hybrid pipeline:

1. **Batfish** — deterministic reachability, routes, interfaces, ACL/filter evidence  
2. **Python rules** — transparent mapping of evidence → fault classes  
3. **LLM** — evidence-grounded explanation + remediation (advisory only)

Evaluation modes: `rule_only` | `llm_only` | `hybrid` (matches RQ1–RQ3).

## Campus lab topology

```

```

Injected faults (ground truth in `ground_truth/scenarios.yaml`):

| Scenario | Fault class | Device |
|---|---|---|


## Quick start (novice — one click)

```bash
cd /path/to/sal
chmod +x run.sh
./run.sh
```

This script will:

1. Detect OS / CPU architecture  
2. Check Python 3.10+ and Tkinter  
3. Install **uv** if needed and run `uv sync`  
4. Ensure **Ollama** is running and the model is pulled (real LLM — not mock)  
5. Try to start **Batfish** via rootless Podman or Docker; if unavailable, use offline evidence  
6. Open the **Tkinter GUI**

Skip containers entirely:

```bash
./run.sh --skip-batfish
```

On Parrot/Fedora (docker → podman shim), Batfish setup runs:

```bash
systemctl --user enable --now podman.socket
./scripts/ensure_batfish.sh
```

Or: `make run`

### GUI tabs

| Tab | What it does |
|---|---|
| Setup | System checks, uv sync, start Ollama, pull model |
| Diagnose | Pick scenario + mode (hybrid / rule_only / llm_only), run RCA, view explanation |
| Evaluate | Full labelled comparison report (all scenarios × modes) |
| Results | Browse reports; **Generate figures** (CSV/LaTeX/PNG); open charts |

Manual GUI only (after setup): `uv run campus-rca-gui`

Requires [uv](https://docs.astral.sh/uv/) and Ollama. On Debian/Parrot/Ubuntu, Tkinter may need:

```bash
sudo apt install python3-tk
```

## Quick start (CLI)

```bash
uv sync
cp -n .env.example .env
export LLM_BACKEND=ollama USE_BATFISH=false
uv run campus-rca list-scenarios
uv run campus-rca diagnose acl_deny_http --mode hybrid --offline
uv run python evaluation/run_eval.py --offline --llm-backend ollama
```

Reports land in `results/evaluation_report.md` and `results/evaluation_report.json`.

Generate dissertation tables/charts from a report:

```bash
make figures
# or:
uv run python evaluation/plot_results.py --report results/evaluation_report.json
```

Outputs:
- `results/evaluation_summary.csv` / `evaluation_rows.csv` — Excel/Sheets
- `results/evaluation_tables.tex` — LaTeX tables for Chapter 5
- `results/figures/*.png` — accuracy, metrics, localisation matrix, latency

Dependencies are managed via `pyproject.toml` + `uv.lock` (no `requirements.txt`).

## Full stack with Batfish

```bash
# 1) Start Batfish
./scripts/start_batfish.sh
# or: docker compose up -d

# 2) Configure
cp -n .env.example .env
# set USE_BATFISH=true

# 3) Diagnose using live Batfish snapshots under configs/scenarios/*
uv run campus-rca diagnose missing_ospf_network --mode hybrid

# 4) Comparative evaluation
uv run python evaluation/run_eval.py --out results
```

## LLM backends

Set in `.env` or environment:

| `LLM_BACKEND` | Notes |
|---|---|
| `mock` | Deterministic offline stand-in (default for demos/CI) |
| `openai` | Requires `OPENAI_API_KEY` (temperature 0.0) |
| `ollama` | Local `OLLAMA_BASE_URL` + `OLLAMA_MODEL` (recommended for dissertation ethics) |

### Ollama setup

```bash
# Install from https://ollama.com/download if needed, then:
./scripts/setup_ollama.sh          # starts server + lets you pick a LOCAL model
# or: make ollama

uv run campus-rca check-llm
uv run campus-rca diagnose acl_deny_http --mode hybrid --offline
uv run python evaluation/run_eval.py --offline --llm-backend ollama --out results/ollama
```

**Local models are reused** — if Ollama already has a model downloaded, the launcher/GUI lists it and will not re-download. You are asked which local model to use, or you can type a different name (download only if missing).

In the GUI: **Choose Ollama model…** on the Setup tab (also prompted at startup when locals exist).

Notes:
- Evidence sent to the LLM is **compacted** (routes/ACL/traceroute slices) so local CPU models stay usable.
- Default timeout is `OLLAMA_TIMEOUT_S=600` (CPU cold starts can take several minutes).
- Prefer Ollama over OpenAI when prompts include campus configs (§1.6 ethics).

Hybrid prompts force JSON answers and instruct the model **not** to contradict Batfish/rule evidence.

## HTTP API

```bash
uv run campus-rca serve --host 127.0.0.1 --port 8080
# or: make serve
# GET  /health
# GET  /scenarios
# POST /diagnose {"scenario_id":"acl_deny_http","mode":"hybrid","offline":true}
```
## Project layout

```
run.sh                        # ONE-CLICK: arch check → setup → Tkinter UI
configs/baseline|scenarios/   # Batfish snapshots (configs/ + hosts/)
ground_truth/scenarios.yaml   # labelled faults for scoring
src/campus_rca/
  batfish_client.py           # evidence collection (+ synthetic fallback)
  rules/engine.py             # deterministic rules R1–R5
  llm/backend.py              # openai | ollama
  pipeline.py                 # rule_only / llm_only / hybrid
  gui.py                      # Tkinter UI
  setup_checks.py             # system / dep readiness
  cli.py  api.py
evaluation/                   # accuracy, faithfulness, hallucination metrics
docker-compose.yml            # batfish/allinone
```

## Safety / ethics (aligned with dissertation §1.6)

- Diagnostics are **read-only**; remediation is advisory (`ALLOW_REMEDIATION_APPLY=false`).
- Prefer local Ollama for sensitive configs; sanitise untrusted log text before prompting.
- Synthetic campus topology — no live institutional traffic.

## Dissertation mapping

| Objective | Artifact |
|---|---|
| Rule-based verification layer | `rules/engine.py` + Batfish evidence |
| LLM reasoning on validated evidence | `pipeline.py` hybrid mode + `llm/` |
| Scenario evaluation | `evaluation/run_eval.py` + ground truth |
| Compare rule / LLM / hybrid | three modes + `results/` report |
