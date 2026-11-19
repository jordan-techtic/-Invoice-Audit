# Backend only. Run from api/.
.PHONY: network up down logs test config-check eval-flags

network:
	@docker network inspect invoice-audit >/dev/null 2>&1 || docker network create invoice-audit

up: network
	docker compose up -d --build
	@for i in $$(seq 60); do curl -fs localhost:8000/health >/dev/null && break; sleep 2; done

down:
	docker compose down

logs:
	docker compose logs -f api worker

test:
	docker compose run --rm api python -m pytest -q

config-check:
	docker compose run --rm api python -m app.configcheck

# Rule evaluation on synthetic_dataset_v1. Needs DATABASE_URL pointing at a *_test database (see eval/run_flag_eval_v1.py).
# Usage: make eval-flags DATASET=/path/to/synthetic_dataset_v1
eval-flags:
	python -m eval.run_flag_eval_v1 --dataset $(DATASET) --config aligned
