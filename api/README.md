# Invoice audit: backend

FastAPI service plus an RQ worker and a maintenance loop. PostgreSQL holds the data and, locally, the uploaded files; Redis holds the queue. Production keeps files in AWS S3 (`STORAGE_BACKEND=s3`). It serves JSON only; the frontend lives in `../web` and needs nothing from here except the HTTP API.

## Run

1. Create the role and databases once: `sudo -u postgres psql -f ../infra/postgres-init.sql`.
2. `cp .env.example .env` and fill in the key (or set `AI_PROVIDER=fake`).
3. `make dev`: creates `.venv`, migrates, seeds the demo accounts and serves http://127.0.0.1:8000 (`/health`, `/docs`).

| | Command |
|---|---|
| API with auto-reload | `make dev` |
| Queue worker (only with `QUEUE_INLINE=false`, needs Redis at `REDIS_URL`) | `make worker` |
| Raw-file retention loop (keep running on a long-lived install) | `make maintenance` |

With `QUEUE_INLINE=true` (the `.env.example` default) no Redis or worker is needed. For an offline run without an AI key
set `AI_PROVIDER=fake`. The API refuses to start with `AI_PROVIDER=openai` and no key, by design.

All settings come from `api/.env`.

## Test and evaluate
- `make test`: unit and API tests (they use a separate `audit_test` database; synthetic-data cases read `SYNTHETIC_DIR`,
  default `../synthetic/out`, and are skipped if it is missing).
- `python -m eval.run_eval` (extraction), `python -m eval.run_flag_eval` (rules, old synthetic set),
  `python -m eval.run_flag_eval_v1 --dataset <synthetic_dataset_v1>` (rules, 992-invoice set; refuses non-`*_test` databases).
- `make config-check` lists what is not set for production.

## Layout
`app/` code (`routers/`, `services/`, `flags/` rules engine, `reports/`), `alembic/` migrations, `eval/` measurements,
`tests/`. Prompts are in `app/prompts/`. Architecture and data policy: `../docs/`.

## Frontend
Run it from `../web` (`make dev`). It reaches this API through its own `/api` proxy, so no CORS settings are needed.
