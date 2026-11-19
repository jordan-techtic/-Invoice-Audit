# Frontend only, on the host (no Docker). Run from web/. Needs a backend on API_URL (default http://127.0.0.1:8000).
.PHONY: install dev build start test

API_URL ?= http://127.0.0.1:8000
export API_URL

node_modules:
	npm install

install: node_modules

dev: node_modules
	npm run dev

# Production build. The /api proxy target (API_URL) is fixed at build time.
build: node_modules
	npm run build

start:
	npm run start

# Playwright; the backend must be running with AI_PROVIDER=fake FAKE_PROVIDER_DEMO=true
test: node_modules
	npx playwright test
