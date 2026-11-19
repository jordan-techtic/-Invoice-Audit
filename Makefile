# Runs on the host (no Docker). Needs PostgreSQL, Python 3.11+ and Node.js; see README.md "Run locally".
# Uses the real AI when OPENAI_API_KEY is set (here or in api/.env); otherwise an offline oracle (clearly labelled).
SHELL := /bin/bash
-include .env          # optional; .env is git-ignored
export


.PHONY: setup api web demo test scan config-check

api/.venv:
	python3 -m venv api/.venv && api/.venv/bin/pip install -q -r api/requirements.txt

web/node_modules:
	cd web && npm install

setup: api/.venv web/node_modules   # first run: also create the databases (infra/postgres-init.sql) and api/.env

api: api/.venv          # migrate, seed and serve the API on :8000 (Ctrl+C to stop)
	./scripts/dev-local.sh

web: web/node_modules   # Next dev server on :3000, proxying /api to the API above
	cd web && API_URL=$(or $(API_URL),http://127.0.0.1:8000) npm run dev

synthetic/out/answer_key.json:
	cd synthetic && ([ -d .venv ] || python3 -m venv .venv) && .venv/bin/pip install -q -r requirements.txt && .venv/bin/python generate.py --out out --count 200 --seed 7

# The demo data is synthetic, so it may run before zero data retention is confirmed (real client data may not).
demo: synthetic/out/answer_key.json api/.venv
	mkdir -p demo
	cd api && AI_ZERO_RETENTION_REQUIRED=false .venv/bin/python -m app.demo --synthetic ../synthetic/out --out ../demo

test: api/.venv         # backend suite; uses the separate audit_test database
	cd api && SYNTHETIC_DIR=../synthetic/out .venv/bin/python -m pytest -q

scan:  # confirms no API key is committed anywhere in the repo
	@! grep -rEn --exclude-dir={node_modules,.next,.git,.venv,eval_out} --exclude=test_security.py "sk-(proj-)?[A-Za-z0-9_-]{30,}|sk-ant-[A-Za-z0-9_-]{20,}" . && echo "scan clean: no API keys found"

config-check: api/.venv
	cd api && .venv/bin/python -m app.configcheck
