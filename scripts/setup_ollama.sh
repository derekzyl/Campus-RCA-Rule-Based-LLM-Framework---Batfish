#!/usr/bin/env bash
# Start Ollama (if needed) and ensure the Campus RCA model is available.
set -euo pipefail

MODEL="${OLLAMA_MODEL:-llama3.2:3b}"
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

if ! ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -qx "${MODEL}" \
  && ! ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -q "^${MODEL}:"; then
  echo "==> Pulling ${MODEL} (this can take several minutes)"
  ollama pull "${MODEL}"
else
  echo "==> Model ${MODEL} already present"
fi

echo "==> Smoke test JSON response"
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
echo "Ready. Set LLM_BACKEND=ollama OLLAMA_MODEL=${MODEL} then:"
echo "  campus-rca diagnose acl_deny_http --mode hybrid --offline"
