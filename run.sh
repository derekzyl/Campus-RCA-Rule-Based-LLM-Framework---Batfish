#!/usr/bin/env bash
# Campus RCA — one-click setup + Tkinter UI for novices
# Usage:  ./run.sh
#         ./run.sh --setup-only
#         ./run.sh --cli
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

MODE="gui"
SETUP_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --setup-only) SETUP_ONLY=1 ;;
    --cli) MODE="cli" ;;
    --gui) MODE="gui" ;;
    -h|--help)
      cat <<'EOF'
Campus RCA launcher (masters prototype)

  ./run.sh              Detect arch, install deps, ensure Ollama, open Tkinter UI
  ./run.sh --setup-only Setup only (no UI)
  ./run.sh --cli        Setup then interactive CLI diagnose hint

Requires: Python 3.10+, network for first uv sync / Ollama model pull.
EOF
      exit 0
      ;;
  esac
done

log()  { printf '\n==> %s\n' "$*"; }
ok()   { printf '    [OK] %s\n' "$*"; }
warn() { printf '    [!!] %s\n' "$*"; }
fail() { printf '    [XX] %s\n' "$*"; exit 1; }

# ---------------------------------------------------------------------------
# 1) Architecture / platform
# ---------------------------------------------------------------------------
log "Detecting system"
OS="$(uname -s 2>/dev/null || echo unknown)"
ARCH="$(uname -m 2>/dev/null || echo unknown)"
case "$ARCH" in
  x86_64|amd64) ARCH_NORM="x86_64" ;;
  aarch64|arm64) ARCH_NORM="arm64" ;;
  armv7l) ARCH_NORM="armv7" ;;
  *) ARCH_NORM="$ARCH" ;;
esac
ok "OS=$OS  arch=$ARCH ($ARCH_NORM)"

case "$OS" in
  Linux|Darwin) ;;
  MINGW*|MSYS*|CYGWIN*)
    warn "Windows detected via Git Bash/MSYS. Prefer WSL2 for Batfish/Docker."
    ;;
  *)
    warn "Unusual OS '$OS' — continuing anyway"
    ;;
esac

# ---------------------------------------------------------------------------
# 2) Python
# ---------------------------------------------------------------------------
log "Checking Python"
if ! command -v python3 >/dev/null 2>&1; then
  fail "python3 not found. Install Python 3.10+ and re-run."
fi
PY_VER="$(python3 -c 'import sys; print("%d.%d"%sys.version_info[:2])')"
PY_OK="$(python3 -c 'import sys; print(int(sys.version_info[:2] >= (3,10)))')"
ok "python3 $PY_VER"
[[ "$PY_OK" == "1" ]] || fail "Need Python >= 3.10 (found $PY_VER)"

# Tkinter (required for GUI)
if [[ "$MODE" == "gui" ]]; then
  if ! python3 -c 'import tkinter' 2>/dev/null; then
    warn "Tkinter missing."
    if [[ "$OS" == "Linux" ]]; then
      warn "Install with:  sudo apt install python3-tk   (Debian/Ubuntu/Parrot)"
      warn "           or:  sudo dnf install python3-tkinter"
    elif [[ "$OS" == "Darwin" ]]; then
      warn "Install/use python.org Python or: brew install python-tk"
    fi
    fail "Tkinter is required for the GUI. Install it, then re-run ./run.sh"
  fi
  ok "Tkinter available"
fi

# ---------------------------------------------------------------------------
# 3) uv
# ---------------------------------------------------------------------------
log "Checking uv package manager"
if ! command -v uv >/dev/null 2>&1; then
  warn "uv not found — installing to ~/.local/bin"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
command -v uv >/dev/null 2>&1 || fail "uv install failed. See https://docs.astral.sh/uv/"
ok "uv $(uv --version | head -1)"

# ---------------------------------------------------------------------------
# 4) Project env
# ---------------------------------------------------------------------------
log "Installing project dependencies (uv sync)"
uv sync --python "$(command -v python3)"
ok "Virtual environment ready (.venv)"

if [[ ! -f .env ]]; then
  cp .env.example .env
  ok "Created .env from .env.example"
else
  ok ".env already present"
fi

# Masters default: real LLM (Ollama), not mock
if grep -q '^LLM_BACKEND=mock' .env 2>/dev/null; then
  warn "Switching LLM_BACKEND from mock → ollama (masters / real inference)"
  if [[ "$OS" == "Darwin" ]]; then
    sed -i '' 's/^LLM_BACKEND=mock/LLM_BACKEND=ollama/' .env
  else
    sed -i 's/^LLM_BACKEND=mock/LLM_BACKEND=ollama/' .env
  fi
fi

# ---------------------------------------------------------------------------
# 5) Ollama (required for real RCA explanations)
# ---------------------------------------------------------------------------
log "Checking Ollama (local LLM — required for masters demo)"
OLLAMA_MODEL="$(grep -E '^OLLAMA_MODEL=' .env 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'" || true)"
OLLAMA_MODEL="${OLLAMA_MODEL:-llama3.2:3b}"

if ! command -v ollama >/dev/null 2>&1; then
  warn "Ollama CLI not found."
  case "$OS-$ARCH_NORM" in
    Linux-x86_64|Linux-arm64)
      warn "Install: curl -fsSL https://ollama.com/install.sh | sh"
      ;;
    Darwin-*)
      warn "Install: https://ollama.com/download (macOS app) or brew install ollama"
      ;;
    *)
      warn "Install from https://ollama.com/download for $OS/$ARCH_NORM"
      ;;
  esac
  fail "Install Ollama, then re-run ./run.sh"
fi
ok "ollama $(ollama --version 2>/dev/null | head -1 || echo present)"

if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
  warn "Starting ollama serve in background"
  nohup ollama serve >/tmp/campus-rca-ollama.log 2>&1 &
  for i in $(seq 1 40); do
    curl -sf http://localhost:11434/api/tags >/dev/null 2>&1 && break
    sleep 1
  done
fi
curl -sf http://localhost:11434/api/tags >/dev/null 2>&1 || fail "Cannot reach Ollama at http://localhost:11434"

if ! ollama list 2>/dev/null | awk 'NR>1 {print $1}' | grep -Eq "^${OLLAMA_MODEL}$|^${OLLAMA_MODEL}:"; then
  log "Pulling model ${OLLAMA_MODEL} (first time can take a while)"
  ollama pull "${OLLAMA_MODEL}"
fi
ok "Model ready: ${OLLAMA_MODEL}"

# ---------------------------------------------------------------------------
# 6) Optional Batfish via Docker
# ---------------------------------------------------------------------------
log "Checking Batfish (optional Docker)"
USE_BF=0
if command -v docker >/dev/null 2>&1; then
  if docker info >/dev/null 2>&1; then
    ok "Docker available"
    if ! curl -sf http://localhost:9996/ >/dev/null 2>&1; then
      warn "Starting Batfish (docker compose) — first pull may be large"
      if docker compose up -d; then
        sleep 8
        USE_BF=1
      else
        warn "Could not start Batfish; GUI can still use offline evidence cache"
      fi
    else
      ok "Batfish already reachable"
      USE_BF=1
    fi
  else
    warn "Docker installed but daemon not running — offline evidence mode"
  fi
else
  warn "Docker not found — offline/synthetic Batfish evidence will be used"
fi

if [[ "$USE_BF" == "1" ]]; then
  if [[ "$OS" == "Darwin" ]]; then
    sed -i '' 's/^USE_BATFISH=.*/USE_BATFISH=true/' .env || true
  else
    sed -i 's/^USE_BATFISH=.*/USE_BATFISH=true/' .env || true
  fi
else
  if [[ "$OS" == "Darwin" ]]; then
    sed -i '' 's/^USE_BATFISH=.*/USE_BATFISH=false/' .env || true
  else
    sed -i 's/^USE_BATFISH=.*/USE_BATFISH=false/' .env || true
  fi
fi

# ---------------------------------------------------------------------------
# 7) Launch
# ---------------------------------------------------------------------------
log "Setup complete"
ok "Project: $ROOT"
ok "LLM:    ollama / ${OLLAMA_MODEL}"
ok "Batfish evidence live: $([[ $USE_BF == 1 ]] && echo yes || echo no — offline/cache)"

if [[ "$SETUP_ONLY" == "1" ]]; then
  ok "Setup-only requested — exiting"
  exit 0
fi

if [[ "$MODE" == "cli" ]]; then
  log "CLI examples"
  cat <<EOF
  uv run campus-rca list-scenarios
  uv run campus-rca diagnose acl_deny_http --mode hybrid
  uv run python evaluation/run_eval.py --llm-backend ollama --out results
EOF
  exit 0
fi

log "Launching Campus RCA Tkinter UI"
exec uv run campus-rca-gui
