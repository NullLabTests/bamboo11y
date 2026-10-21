#!/usr/bin/env bash
# Full local gate. CI calls the same script so "works on my machine" means "works in CI".
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

PYTHON="${PYTHON:-.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  echo "error: $PYTHON not found. Run 'make setup' first." >&2
  exit 1
fi

if [[ ! -d frontend/node_modules ]]; then
  echo "== frontend dependencies =="
  (cd frontend && npm ci)
fi

echo "== backend lint =="
"$PYTHON" -m ruff check backend scripts
"$PYTHON" -m ruff format --check backend scripts

echo "== backend tests =="
PYTHONPATH=backend "$PYTHON" -m pytest backend/tests -q

echo "== frontend lint =="
(cd frontend && npm run lint)

echo "== frontend typecheck =="
(cd frontend && npm run typecheck)

echo "== frontend tests =="
(cd frontend && npm run test)

echo "== frontend build =="
(cd frontend && npm run build)

echo "== configuration validation =="
PYTHONPATH=backend "$PYTHON" scripts/validate_config.py

echo
echo "All checks passed."
