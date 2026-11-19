# Frontend only. Run from web/.
.PHONY: network up down dev test

network:
	@docker network inspect invoice-audit >/dev/null 2>&1 || docker network create invoice-audit

up: network
	docker compose up -d --build

down:
	docker compose down

# No Docker: needs a backend on API_URL (default http://127.0.0.1:8000)
dev:
	API_URL=$(or $(API_URL),http://127.0.0.1:8000) npm run dev

# Playwright; the backend must be running with AI_PROVIDER=fake FAKE_PROVIDER_DEMO=true
test:
	npx playwright test
