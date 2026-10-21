#!/usr/bin/env bash
# Run the API with reload and the Vite dev server together. Ctrl-C stops both.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
PYTHON="${PYTHON:-.venv/bin/python}"

if [[ ! -x "$PYTHON" ]]; then
  echo "error: $PYTHON not found. Run 'make setup' first." >&2
  exit 1
fi

mkdir -p data
api_pid=""

cleanup() {
  if [[ -n "$api_pid" ]] && kill -0 "$api_pid" 2>/dev/null; then
    kill "$api_pid" 2>/dev/null || true
    wait "$api_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

PYTHONPATH=backend "$PYTHON" -m uvicorn app.main:create_app --factory \
  --reload --host "$HOST" --port "$PORT" &
api_pid=$!

for _ in $(seq 1 60); do
  if "$PYTHON" -c "import urllib.request; urllib.request.urlopen('http://$HOST:$PORT/healthz', timeout=1)" 2>/dev/null; then
    break
  fi
  if ! kill -0 "$api_pid" 2>/dev/null; then
    echo "error: the API process exited before becoming healthy." >&2
    exit 1
  fi
  sleep 0.25
done

echo "API:       http://$HOST:$PORT"
echo "Dashboard: http://127.0.0.1:5173"
(cd frontend && npm run dev)
