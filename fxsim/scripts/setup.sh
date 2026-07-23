#!/usr/bin/env bash
# Idempotent environment setup for the FX simulator.
# Used by the SessionStart hook and for manual setup.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  echo "[setup] creating virtualenv ..."
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
. .venv/bin/activate
echo "[setup] installing python deps ..."
pip install --quiet --disable-pip-version-check -r requirements.txt

# vendor chart.js for the dashboard if missing
if [ ! -f app/static/chart.umd.js ]; then
  echo "[setup] vendoring chart.js ..."
  npm install chart.js@4 >/dev/null 2>&1 || true
  cp node_modules/chart.js/dist/chart.umd.js app/static/chart.umd.js 2>/dev/null || true
fi

echo "[setup] done. Run:  . fxsim/.venv/bin/activate && python -m pytest fxsim/tests -q"
