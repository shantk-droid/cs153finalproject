#!/usr/bin/env bash
# Run web (next dev) and api (uvicorn) concurrently for local development.
# Both stop together on Ctrl-C.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ ! -d "$REPO_ROOT/node_modules" ]]; then
  echo "node_modules missing — run \`npm install\` from the repo root first."
  exit 1
fi

if ! python -c "import fastapi" &> /dev/null; then
  echo "FastAPI not installed in current Python env."
  echo "Run: source .venv/bin/activate && pip install -e \"apps/api[dev]\""
  exit 1
fi

cd "$REPO_ROOT"

cleanup() {
  echo
  echo "Shutting down..."
  jobs -p | xargs -r kill 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "→ FastAPI on http://localhost:8000  (docs: /docs)"
PYTHONPATH="$REPO_ROOT" uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload &

echo "→ Next.js on http://localhost:3000"
npm run -w @inventory-optimizer/web dev &

wait
