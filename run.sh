#!/usr/bin/env bash
# Start the AI engine (FastAPI, port 8000) and the UI dev server (Vite, port 5173).
# First run creates the Python virtualenv and installs the frontend dependencies.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "Creating Python virtualenv..."
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install -q -r "$ROOT/requirements-dev.txt"
fi
if [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "Installing frontend dependencies..."
  (cd "$ROOT/frontend" && npm install --no-audit --no-fund)
fi

trap 'kill 0' EXIT INT TERM
(cd "$ROOT/backend" && "$ROOT/.venv/bin/uvicorn" app.main:app --port 8000 --reload) &
(cd "$ROOT/frontend" && npm run dev -- --port 5173 --strictPort) &
echo "AI engine: http://localhost:8000   UI: http://localhost:5173"
wait
