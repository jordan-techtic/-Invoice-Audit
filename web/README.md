# Invoice audit: frontend

Next.js app for analysts (upload, review, flags, reports). It holds no business logic and no secrets. The browser only
talks to this app; the app proxies `/api/*` to the backend (`API_URL`, see `next.config.ts`). It can be developed, built and
run without the rest of the repo as long as a backend answers at `API_URL`.

## Run

| | Command |
|---|---|
| Dev | `make dev` (or `npm install && API_URL=http://127.0.0.1:8000 npm run dev`). Opens on http://localhost:3000 |
| Production build | `API_URL=http://host:8000 make build && make start` (the URL is fixed at build time) |
| Backend somewhere else | `API_URL=http://host:8000 make dev` |

Demo logins (backend seeds them): `admin@audit-demo.com` / `admin-password-123`, `analyst@audit-demo.com` / `analyst-password-123`.

## Contract with the backend
- Everything goes through `src/lib/api.ts` (relative `/api/...` URLs). There is no other coupling to the backend code.
- Uploads up to 25 MB; the proxy allows 30 MB (`proxyClientMaxBodySize`).
- Auth is a cookie set by the backend on sign-in.

## Test
`make test` (Playwright). The backend must run with `AI_PROVIDER=fake FAKE_PROVIDER_DEMO=true`.
Notes on the UI and design decisions: `NOTES.md`, `AGENTS.md`.
