#!/usr/bin/env bash
# Reproducible local verification (WSL / Linux).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export EARTHSIM_DATA_MODE="${EARTHSIM_DATA_MODE:-fixture}"
cd "$ROOT/backend"
python -m earthsim.cli doctor
python -m earthsim.cli fixtures install
python -m earthsim.cli fixtures verify
python -m pytest -q
cd "$ROOT/apps/web"
npm run build
npm test -- --run
cd "$ROOT"
python scripts/bench_api.py
echo "VERIFY_OK"
