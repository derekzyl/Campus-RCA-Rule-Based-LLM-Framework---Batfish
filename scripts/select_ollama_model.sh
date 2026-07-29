#!/usr/bin/env bash
# Select / reuse a local Ollama model (never re-downloads if already present).
# Interactive when stdin is a TTY; otherwise keeps preferred local model or first local.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT}/.env"
PREFERRED="${OLLAMA_MODEL:-}"
if [[ -z "$PREFERRED" && -f "$ENV_FILE" ]]; then
  PREFERRED="$(grep -E '^OLLAMA_MODEL=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'" || true)"
fi
PREFERRED="${PREFERRED:-llama3.2:3b}"

list_models() {
  ollama list 2>/dev/null | awk 'NR>1 {print $1}'
}

model_local() {
  local want="$1"
  local m
  while read -r m; do
    [[ -z "$m" ]] && continue
    if [[ "$m" == "$want" ]]; then
      echo "$m"
      return 0
    fi
    if [[ "$m" == "$want":* ]]; then
      echo "$m"
      return 0
    fi
    if [[ "$want" != *:* && "$m" == "$want":* ]]; then
      echo "$m"
      return 0
    fi
  done < <(list_models)
  return 1
}

write_env_model() {
  local model="$1"
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "OLLAMA_MODEL=${model}" >"$ENV_FILE"
    return
  fi
  if grep -q '^OLLAMA_MODEL=' "$ENV_FILE"; then
    if [[ "$(uname -s)" == "Darwin" ]]; then
      sed -i '' "s/^OLLAMA_MODEL=.*/OLLAMA_MODEL=${model}/" "$ENV_FILE"
    else
      sed -i "s/^OLLAMA_MODEL=.*/OLLAMA_MODEL=${model}/" "$ENV_FILE"
    fi
  else
    echo "OLLAMA_MODEL=${model}" >>"$ENV_FILE"
  fi
}

mapfile -t MODELS < <(list_models || true)
# Drop empty first element if no models
if [[ "${#MODELS[@]}" -eq 1 && -z "${MODELS[0]:-}" ]]; then
  MODELS=()
fi

if [[ "${#MODELS[@]}" -eq 0 ]]; then
  echo "No local Ollama models found."
  if [[ "${AUTO_PULL_IF_EMPTY:-1}" == "1" ]]; then
    echo "Pulling preferred model: ${PREFERRED}"
    ollama pull "${PREFERRED}"
    SELECTED_OLLAMA_MODEL="${PREFERRED}"
    write_env_model "$SELECTED_OLLAMA_MODEL"
    echo "Selected: ${SELECTED_OLLAMA_MODEL}"
    export SELECTED_OLLAMA_MODEL OLLAMA_MODEL="$SELECTED_OLLAMA_MODEL"
    return 0 2>/dev/null || exit 0
  fi
  echo "Install a model with: ollama pull ${PREFERRED}"
  return 1 2>/dev/null || exit 1
fi

echo
echo "Local Ollama models (already downloaded — will NOT re-download if chosen):"
i=1
for m in "${MODELS[@]}"; do
  mark=""
  hit="$(model_local "$PREFERRED" || true)"
  if [[ -n "$hit" && "$m" == "$hit" ]]; then
    mark="  ← current preference (${PREFERRED})"
  fi
  printf "  [%d] %s%s\n" "$i" "$m" "$mark"
  i=$((i + 1))
done
echo "  Or type a different model name (downloads only if not already local)"
echo

pick_noninteractive() {
  if [[ -n "${OLLAMA_MODEL_CHOICE:-}" ]]; then
    SELECTED_OLLAMA_MODEL="$OLLAMA_MODEL_CHOICE"
    hit="$(model_local "$SELECTED_OLLAMA_MODEL" || true)"
    if [[ -n "$hit" ]]; then
      SELECTED_OLLAMA_MODEL="$hit"
      echo "Already local — skipped download: ${SELECTED_OLLAMA_MODEL}"
    else
      echo "Not local yet — pulling '${SELECTED_OLLAMA_MODEL}'…"
      ollama pull "${SELECTED_OLLAMA_MODEL}"
    fi
    return
  fi
  hit="$(model_local "$PREFERRED" || true)"
  if [[ -n "$hit" ]]; then
    SELECTED_OLLAMA_MODEL="$hit"
    echo "Non-interactive: using already-local model ${SELECTED_OLLAMA_MODEL}"
  else
    SELECTED_OLLAMA_MODEL="${MODELS[0]}"
    echo "Non-interactive: preferred '${PREFERRED}' not local; using ${SELECTED_OLLAMA_MODEL}"
  fi
}

if [[ ! -t 0 ]]; then
  pick_noninteractive
else
  read -r -p "Enter number [1-${#MODELS[@]}] or a model name [default=1]: " choice
  choice="${choice:-1}"
  if [[ "$choice" =~ ^[0-9]+$ ]]; then
    idx=$((choice - 1))
    if (( idx < 0 || idx >= ${#MODELS[@]} )); then
      echo "Invalid number — using [1]."
      SELECTED_OLLAMA_MODEL="${MODELS[0]}"
    else
      SELECTED_OLLAMA_MODEL="${MODELS[$idx]}"
    fi
    echo "Using already-local model (no download): ${SELECTED_OLLAMA_MODEL}"
  else
    SELECTED_OLLAMA_MODEL="$choice"
    hit="$(model_local "$SELECTED_OLLAMA_MODEL" || true)"
    if [[ -n "$hit" ]]; then
      SELECTED_OLLAMA_MODEL="$hit"
      echo "Already local — skipped download: ${SELECTED_OLLAMA_MODEL}"
    else
      echo "Not local yet — pulling '${SELECTED_OLLAMA_MODEL}'…"
      ollama pull "${SELECTED_OLLAMA_MODEL}"
    fi
  fi
fi

write_env_model "$SELECTED_OLLAMA_MODEL"
echo "Selected: ${SELECTED_OLLAMA_MODEL}"
export SELECTED_OLLAMA_MODEL
export OLLAMA_MODEL="$SELECTED_OLLAMA_MODEL"
