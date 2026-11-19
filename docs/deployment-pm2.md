# Deploy Invoice-Audit with PM2

Run the **FastAPI API** and **Next.js** app on a Linux server under [PM2](https://pm2.keymetrics.io/). PostgreSQL and (optionally) Redis run on the same host or elsewhere.

All PM2 ports and the internal API URL live in **`ecosystem.config.json`** only (no `.env.pm2` file).

## Server prerequisites

- Ubuntu 22.04+ (or similar)
- **PostgreSQL 16** — create DB/user: `sudo -u postgres psql -f infra/postgres-init.sql`
- **Node.js 20+** and **Python 3.11+**
- **PM2:** `npm install -g pm2`
- **Nginx or Caddy** (recommended) — TLS and public port 443 → web `invoiceAudit.webPort`

Optional: **Redis** if `QUEUE_INLINE=false` (add an RQ worker entry under `apps` in `ecosystem.config.json`).

## 1. Clone on the server

```bash
cd /var/www   # or your path
git clone https://github.com/jordan-techtic/-Invoice-Audit.git
cd -Invoice-Audit
```

## 2. Configure API secrets

```bash
cp api/.env.production.example api/.env
nano api/.env
```

| Variable | Notes |
|----------|--------|
| `ENV` | `production` |
| `DATABASE_URL` | Postgres connection string |
| `OPENAI_API_KEY` | Required when `AI_PROVIDER=openai` |
| `JWT_SECRET`, `DATA_ENCRYPTION_KEY` | Strong random values |
| `PUBLIC_BASE_URL` | `https://your-domain.com` (no trailing slash) |
| `COOKIE_SECURE` | `true` behind HTTPS |
| `AUTH_DISABLED` | `false` for real login |
| `STORAGE_BACKEND` | `s3` for production uploads (or `postgres` for small POC) |

## 3. PM2 ports and API URL (`ecosystem.config.json`)

Edit the **`invoiceAudit`** block at the top of `ecosystem.config.json`:

```json
"invoiceAudit": {
  "apiHost": "127.0.0.1",
  "apiPort": 8010,
  "webHost": "0.0.0.0",
  "webPort": 3010,
  "apiUrl": "http://127.0.0.1:8010"
}
```

- **`apiUrl`** — where **Next** proxies `/api` (server-side only). Same machine: `http://127.0.0.1:<apiPort>`.
- **`./scripts/pm2-deploy.sh`** runs `scripts/pm2-sync-config.js` to copy these values into the `apps` entries, then builds the web with `apiUrl`.

## 4. Build and start PM2

```bash
chmod +x scripts/pm2-deploy.sh
./scripts/pm2-deploy.sh
```

After `git pull`, run `./scripts/pm2-deploy.sh` again.

```bash
pm2 save
pm2 startup   # run the command it prints as root
```

Manual start: `pm2 start ecosystem.config.json`

## 5. Reverse proxy (Nginx example)

Proxy to **`invoiceAudit.webPort`** (default `3010`), not the API port.

```nginx
server {
    listen 443 ssl http2;
    server_name audit.yourdomain.com;

    client_max_body_size 30M;

    location / {
        proxy_pass http://127.0.0.1:3010;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 900s;
    }
}
```

## 6. PM2 apps

| Name | Role |
|------|------|
| `invoice-audit-api` | Uvicorn on `apiHost:apiPort` |
| `invoice-audit-web` | Next on `webHost:webPort` |
| `invoice-audit-maintenance` | Retention cleanup loop |

## 7. API on another server

Set `apiUrl` to the internal URL of that API (e.g. `http://10.0.0.5:8010`), run `./scripts/pm2-deploy.sh` on the web server only.

## 8. Smoke test

```bash
curl -s http://127.0.0.1:8010/health    # apiPort
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3010/
```

Run `cd api && .venv/bin/python -m app.configcheck` before live client data.