#!/usr/bin/env bash
# Try to make Batfish available via Docker or rootless Podman.
# Exit 0 if Batfish ports respond; exit 1 for offline fallback.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

log()  { printf '    %s\n' "$*"; }
ok()   { printf '    [OK] %s\n' "$*"; }
warn() { printf '    [!!] %s\n' "$*"; }

bf_up() {
  # Batfish may return non-2xx on / — treat any TCP/HTTP response as up
  curl -s -o /dev/null --connect-timeout 2 http://127.0.0.1:9996/ >/dev/null 2>&1 \
    || curl -s -o /dev/null --connect-timeout 2 http://127.0.0.1:9997/ >/dev/null 2>&1 \
    || (echo >/dev/tcp/127.0.0.1/9997) 2>/dev/null
}

if bf_up; then
  ok "Batfish already reachable"
  exit 0
fi

# Prefer real Docker daemon; otherwise rootless Podman socket (Parrot/Fedora style)
ensure_runtime() {
  # Already usable?
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    ok "Container runtime ready (docker/podman)"
    return 0
  fi

  # Start user Podman API socket (common when `docker` is a Podman shim)
  if command -v podman >/dev/null 2>&1 && command -v systemctl >/dev/null 2>&1; then
    warn "Starting rootless Podman API socket…"
    systemctl --user enable --now podman.socket >/dev/null 2>&1 || true
    systemctl --user start podman.socket >/dev/null 2>&1 || true
    export DOCKER_HOST="unix:///run/user/$(id -u)/podman/podman.sock"
    # Give socket a moment
    for _ in $(seq 1 10); do
      if [[ -S "/run/user/$(id -u)/podman/podman.sock" ]]; then
        break
      fi
      sleep 0.5
    done
    if docker info >/dev/null 2>&1; then
      ok "Podman socket active (DOCKER_HOST=$DOCKER_HOST)"
      return 0
    fi
  fi

  # System Docker daemon
  if command -v systemctl >/dev/null 2>&1; then
    if systemctl is-active --quiet docker 2>/dev/null; then
      :
    else
      warn "Trying to start system docker.service (may need sudo)…"
      systemctl start docker >/dev/null 2>&1 || sudo -n systemctl start docker >/dev/null 2>&1 || true
    fi
    if docker info >/dev/null 2>&1; then
      ok "Docker daemon active"
      return 0
    fi
  fi

  return 1
}

if ! ensure_runtime; then
  warn "No working Docker/Podman daemon — offline Batfish evidence will be used"
  warn "To enable live Batfish later:"
  warn "  systemctl --user enable --now podman.socket"
  warn "  export DOCKER_HOST=unix:///run/user/\$(id -u)/podman/podman.sock"
  warn "  cd $ROOT && docker compose up -d"
  exit 1
fi

# Persist DOCKER_HOST for child processes when using podman
if [[ -S "/run/user/$(id -u)/podman/podman.sock" ]]; then
  export DOCKER_HOST="${DOCKER_HOST:-unix:///run/user/$(id -u)/podman/podman.sock}"
fi

warn "Starting Batfish container (first image pull can be large / slow)…"
# Reuse an existing named container if compose recreate fails on Podman
if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx 'campus-rca-batfish'; then
  warn "Found existing campus-rca-batfish — starting it"
  docker start campus-rca-batfish >/dev/null 2>&1 || true
else
  docker compose up -d || true
fi

# If still not created, try compose once more
if ! docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx 'campus-rca-batfish'; then
  if ! docker compose up -d; then
    warn "docker compose failed — using offline Batfish evidence"
    exit 1
  fi
fi

for i in $(seq 1 40); do
  if bf_up; then
    ok "Batfish is up"
    exit 0
  fi
  sleep 2
done
warn "Container present but Batfish ports not ready yet — using offline until it finishes warming up"
exit 1
