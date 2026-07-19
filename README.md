# Campus RCA — Rule-Based LLM Framework (Batfish)

Prototype for the dissertation *Design and Evaluation of a Rule-Based LLM Framework for Root Cause Analysis in Campus Network Using Batfish*.

Hybrid pipeline:

1. **Batfish** — deterministic reachability, routes, interfaces, ACL/filter evidence  
2. **Python rules** — transparent mapping of evidence → fault classes  
3. **LLM** — evidence-grounded explanation + remediation (advisory only)

Evaluation modes: `rule_only` | `llm_only` | `hybrid` (matches RQ1–RQ3).

## Campus lab topology

```
                 [border1]---- Internet 203.0.113.0/24
                     |
                  [core1]
                  /    \
             [dist1]  [dist2]--+ CAMPUS_EDGE ACL
                |        |
          VLAN10      VLAN20
        10.10.10.0   10.20.20.0
          hostA        hostB (portal .50), hostC (.100)
```

Injected faults (ground truth in `ground_truth/scenarios.yaml`):

| Scenario | Fault class | Device |
|---|---|---|
| `acl_deny_http` | ACL deny (HTTP permit removed) | dist2 |
| `missing_ospf_network` | Student prefix not in OSPF | dist1 |
| `interface_shutdown` | Core uplink shut | core1 |
| `wrong_static_route` | Bad default next-hop | core1 |
| `ospf_passive_misconfig` | Faculty prefix not advertised | dist2 |

## Quick start (offline demo — no Docker/API key)

Requires [uv](https://docs.astral.sh/uv/):

```bash
cd /path/to/sal
uv sync
cp -n .env.example .env
chmod +x scripts/*.sh
uv run ./scripts/demo.sh
# or: make sync && make demo
```

Step by step:

```bash
uv sync
export LLM_BACKEND=mock USE_BATFISH=false
uv run campus-rca list-scenarios
uv run campus-rca diagnose acl_deny_http --mode hybrid --offline
uv run python evaluation/run_eval.py --offline --llm-backend mock
```

Reports land in `results/evaluation_report.md`.

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
./scripts/setup_ollama.sh          # starts server + pulls OLLAMA_MODEL
# or: make ollama

uv run campus-rca check-llm
uv run campus-rca diagnose acl_deny_http --mode hybrid --offline
uv run python evaluation/run_eval.py --offline --llm-backend ollama --out results/ollama
```

Current `.env` uses `LLM_BACKEND=ollama` with `OLLAMA_MODEL=llama3.2:3b` (fast interim).  
For dissertation runs after the larger model finishes downloading:

```bash
ollama pull llama3.1
# then set OLLAMA_MODEL=llama3.1 in .env
```

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
configs/baseline|scenarios/   # Batfish snapshots (configs/ + hosts/)
ground_truth/scenarios.yaml   # labelled faults for scoring
src/campus_rca/
  batfish_client.py           # evidence collection (+ synthetic fallback)
  rules/engine.py             # deterministic rules R1–R5
  llm/backend.py              # openai | ollama | mock
  pipeline.py                 # rule_only / llm_only / hybrid
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
