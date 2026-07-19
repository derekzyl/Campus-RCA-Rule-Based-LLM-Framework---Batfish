#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Starting Batfish (docker compose)"
docker compose up -d
echo "==> Waiting for Batfish ports..."
sleep 8
docker compose ps
echo "Batfish should be reachable on localhost:9997 / coordinator :9996"
