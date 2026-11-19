#!/usr/bin/env bash
# Run Invoice-Audit API + web without Docker.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ ! -f "$ROOT/api/.env" ]]; then
  echo "Missing api/.env — copy api/.env.example to api/.env and adjust DATABASE_URL if needed."
  exit 1
fi

if [[ ! -d "$ROOT/api/.venv" ]]; then
  python3 -m venv "$ROOT/api/.venv"
  "$ROOT/api/.venv/bin/pip" install -r "$ROOT/api/requirements.txt"
fi

export PATH="$ROOT/api/.venv/bin:$PATH"
cd "$ROOT/api"
alembic upgrade head
python -m app.seed

echo "API:  http://127.0.0.1:8000  (docs at /docs)"
echo "Web:  run in another terminal: cd web && npm install && npm run dev"
echo "Logins (after seed): admin@audit-demo.com / admin-password-123"
exec uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload