#!/usr/bin/env bash
# Offline demo — no Docker / API keys required (mock LLM + synthetic evidence)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export LLM_BACKEND="${LLM_BACKEND:-mock}"
export USE_BATFISH=false

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

echo "==> uv sync"
uv sync

echo "==> List scenarios"
uv run campus-rca list-scenarios

echo "==> Hybrid diagnose: acl_deny_http"
uv run campus-rca diagnose acl_deny_http --mode hybrid --offline

echo "==> Run full evaluation (rule_only / llm_only / hybrid)"
uv run python evaluation/run_eval.py --offline --llm-backend mock --out results

echo "==> Done. See results/evaluation_report.md"
