# Invoice audit: backend

FastAPI service plus an RQ worker and a maintenance loop. PostgreSQL holds the data and, locally, the uploaded files; Redis holds the queue. Production keeps files in AWS S3 (`STORAGE_BACKEND=s3`). It serves JSON only; the frontend lives in `../web` and needs nothing from here except the HTTP API.

## Run

| | Command |
|---|---|
| Docker (whole backend: db, redis, api, worker, maintenance) | `make up`, API on http://localhost:8000 (`/health`, `/docs`) |
| No Docker | `cp .env.example .env`, create the `audit` database (see `../infra/postgres-init.sql`), then `alembic upgrade head && python -m app.seed && uvicorn app.main:app --reload` |

With `QUEUE_INLINE=true` (the `.env.example` default) no Redis or worker is needed. For an offline run without an AI key
set `AI_PROVIDER=fake`. The API refuses to start with `AI_PROVIDER=openai` and no key, by design.

`docker compose` here reads `api/.env` for the `${...}` values in `docker-compose.yml` (keys, `AI_PROVIDER`, secrets). The
`DATABASE_URL` in that file is for non-Docker runs; the compose file sets its own.

## Test and evaluate
- `make test`: unit and API tests (they use a separate `audit_test` database).
- `python -m eval.run_eval` (extraction), `python -m eval.run_flag_eval` (rules, old synthetic set),
  `python -m eval.run_flag_eval_v1 --dataset <synthetic_dataset_v1>` (rules, 992-invoice set; refuses non-`*_test` databases).
- `make config-check` lists what is not set for production.

## Layout
`app/` code (`routers/`, `services/`, `flags/` rules engine, `reports/`), `alembic/` migrations, `eval/` measurements,
`tests/`. Prompts are in `app/prompts/`. Architecture and data policy: `../docs/`.

## Frontend
Run it from `../web` (`make up` or `make dev`). It reaches this API through its own `/api` proxy, so no CORS settings are needed.
