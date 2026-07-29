#!/usr/bin/env bash
# Start Ollama (if needed) and let the user pick a local model (no re-download).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE="${OLLAMA_BASE_URL:-http://localhost:11434}"

if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama is not installed. See https://ollama.com/download"
  exit 1
fi

if ! curl -sf "${BASE}/api/tags" >/dev/null 2>&1; then
  echo "==> Starting ollama serve"
  nohup ollama serve >/tmp/ollama-serve.log 2>&1 &
  for i in $(seq 1 40); do
    if curl -sf "${BASE}/api/tags" >/dev/null 2>&1; then
      echo "Ollama is up"
      break
    fi
    sleep 1
  done
fi

if ! curl -sf "${BASE}/api/tags" >/dev/null 2>&1; then
  echo "Failed to reach Ollama at ${BASE}"
  exit 1
fi

# shellcheck disable=SC1091
source "$ROOT/scripts/select_ollama_model.sh"
MODEL="${SELECTED_OLLAMA_MODEL}"

echo "==> Smoke test JSON response (${MODEL})"
curl -sf "${BASE}/api/chat" -d "$(cat <<EOF
{
  "model": "${MODEL}",
  "stream": false,
  "format": "json",
  "options": {"temperature": 0},
  "messages": [
    {"role": "system", "content": "Reply with JSON only: {\\"ok\\": true}"},
    {"role": "user", "content": "ping"}
  ]
}
EOF
)" | python3 -c "import sys,json; print(json.load(sys.stdin)['message']['content'][:200])"

echo
echo "Ready. LLM_BACKEND=ollama OLLAMA_MODEL=${MODEL}"
echo "  uv run campus-rca diagnose acl_deny_http --mode hybrid --offline"
