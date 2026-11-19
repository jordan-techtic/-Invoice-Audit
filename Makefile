# One-command demo. Uses the real AI when OPENAI_API_KEY is set; otherwise an offline oracle (clearly labelled).
SHELL := /bin/bash
AI_PROVIDER ?= $(if $(OPENAI_API_KEY),openai,fake)
export AI_PROVIDER

.PHONY: demo demo-clean up down test scan config-check

synthetic/out/answer_key.json:
	cd synthetic && ([ -d .venv ] || python3 -m venv .venv) && .venv/bin/pip install -q -r requirements.txt && .venv/bin/python generate.py --out out --count 200 --seed 7

up:
	docker compose up -d --build db redis minio api worker maintenance web
	@for i in $$(seq 60); do curl -fs localhost:8000/health >/dev/null && break; sleep 2; done

demo: synthetic/out/answer_key.json up
	mkdir -p demo
	docker compose run --rm -v $(PWD)/synthetic:/synthetic:ro -v $(PWD)/demo:/demo api python -m app.demo

# same, but first wipes all local volumes (database, object storage) so it starts from nothing
demo-clean:
	docker compose down -v
	$(MAKE) demo

down:
	docker compose down

test:
	docker compose run --rm api python -m pytest -q

scan:  # confirms no API key is committed anywhere in the repo
	@! grep -rEn --exclude-dir={node_modules,.next,.git,.venv,eval_out} "sk-(proj-)?[A-Za-z0-9_-]{30,}|sk-ant-[A-Za-z0-9_-]{20,}" . && echo "scan clean: no API keys found"

config-check:
	docker compose run --rm api python -m app.configcheck
