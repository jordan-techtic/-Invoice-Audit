#!/usr/bin/env bash
# Install deps, migrate DB, build Next.js, (re)load PM2. Run from repo root on the server.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ECOSYSTEM=ecosystem.config.json

if [[ ! -f "$ECOSYSTEM" ]]; then
  echo "Missing $ECOSYSTEM"
  exit 1
fi

node scripts/pm2-sync-config.js

API_URL="$(node -p "require('./ecosystem.config.json').invoiceAudit.apiUrl")"
export API_URL

if [[ ! -f api/.env ]]; then
  echo "Create api/.env from api/.env.production.example and set production secrets first."
  exit 1
fi

echo "==> API: venv + dependencies"
if [[ ! -d api/.venv ]]; then
  python3 -m venv api/.venv
fi
api/.venv/bin/pip install -q -r api/requirements.txt

echo "==> Database migrations"
cd api
.venv/bin/alembic upgrade head
.venv/bin/python -m app.seed
cd "$ROOT"

echo "==> Web: install + production build (API_URL=$API_URL)"
cd web
npm ci
API_URL="$API_URL" npm run build
cd "$ROOT"

if command -v pm2 >/dev/null 2>&1; then
  if pm2 describe invoice-audit-api >/dev/null 2>&1; then
    pm2 reload "$ECOSYSTEM" --update-env
  else
    pm2 start "$ECOSYSTEM"
  fi
  pm2 save
  echo "PM2 apps running. Run 'pm2 logs' to tail output."
else
  echo "pm2 not found. Install: npm i -g pm2"
  echo "Then: pm2 start $ECOSYSTEM && pm2 save && pm2 startup"
fi