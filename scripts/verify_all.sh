#!/usr/bin/env bash
# Reproducible local verification (WSL / Linux).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
python -m earthsim.cli doctor
python -m pytest -q
cd "$ROOT/apps/web"
npm run build
npm test -- --run
echo "VERIFY_OK"
