# Backend only, on the host (no Docker). Run from api/. Settings come from api/.env (copy .env.example).
.PHONY: install dev worker maintenance test config-check eval-flags

PY := .venv/bin/python

.venv:
	python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt

install: .venv

# migrate, seed and serve on :8000 with auto-reload
dev: .venv
	.venv/bin/alembic upgrade head && $(PY) -m app.seed && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Only when QUEUE_INLINE=false: needs Redis at REDIS_URL.
worker: .venv
	.venv/bin/rq worker --url $${REDIS_URL:-redis://127.0.0.1:6379/0} extraction flags reports maintenance

# Deletes raw files after the retention period; keep it running on any long-lived install.
maintenance: .venv
	$(PY) -m app.maintenance --loop

test: .venv
	SYNTHETIC_DIR=$${SYNTHETIC_DIR:-../synthetic/out} $(PY) -m pytest -q

config-check: .venv
	$(PY) -m app.configcheck

# Rule evaluation on synthetic_dataset_v1. Needs DATABASE_URL pointing at a *_test database (see eval/run_flag_eval_v1.py).
# Usage: make eval-flags DATASET=/path/to/synthetic_dataset_v1
eval-flags: .venv
	$(PY) -m eval.run_flag_eval_v1 --dataset $(DATASET) --config aligned
