# Bamboo11y — local development and verification
#
# `make setup` then `make run` is the shortest path. `make check` is the full gate.
# Docker targets are provided for completeness; see docs/operations.md.

PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip
HOST ?= 127.0.0.1
PORT ?= 8000
BASE_URL ?= http://$(HOST):$(PORT)
COMPOSE ?= docker compose

.DEFAULT_GOAL := help
.PHONY: help setup venv install-backend install-frontend run dev demo demo-reset \
	test test-backend test-frontend lint format typecheck build check validate \
	hooks clean docker-build docker-up docker-down docker-logs

help: ## Show available targets
	@echo "Bamboo11y"
	@echo ""
	@echo "  make setup       Create .venv, install Python and Node dependencies, install hooks"
	@echo "  make run         Build the dashboard and serve everything on $(BASE_URL)"
	@echo "  make dev         Run API (reload) and Vite dev server together"
	@echo "  make demo        Run the deterministic demo against a running API"
	@echo "  make demo-reset  Remove demo-partition data only"
	@echo "  make test        Backend and frontend tests"
	@echo "  make lint        Ruff, ESLint, and TypeScript checks"
	@echo "  make check       Full local gate (lint, tests, build, config validation)"
	@echo "  make validate    Validate the service catalog, settings, Compose, and CI files"
	@echo "  make docker-up   Build and run with Docker Compose (requires Docker)"
	@echo "  make clean       Remove caches and build output (keeps data/)"
	@echo ""
	@echo "Variables: PORT=$(PORT) BASE_URL=$(BASE_URL)"

venv:
	@test -x $(PYTHON) || python3 -m venv .venv

install-backend: venv
	$(PIP) install --upgrade pip
	$(PIP) install -r backend/requirements-dev.txt

install-frontend:
	cd frontend && npm ci

setup: install-backend install-frontend hooks
	@echo "Setup complete. Run 'make run' or 'make dev'."

run: build
	PYTHONPATH=backend $(PYTHON) -m uvicorn app.main:create_app --factory \
		--host $(HOST) --port $(PORT)

dev:
	HOST=$(HOST) PORT=$(PORT) ./scripts/dev.sh

demo:
	$(PYTHON) scripts/simulate.py demo --base-url $(BASE_URL)

demo-reset:
	$(PYTHON) scripts/simulate.py reset --base-url $(BASE_URL)

test: test-backend test-frontend

test-backend:
	PYTHONPATH=backend $(PYTHON) -m pytest backend/tests -q

test-frontend:
	cd frontend && npm run test

lint:
	$(PYTHON) -m ruff check backend scripts
	$(PYTHON) -m ruff format --check backend scripts
	cd frontend && npm run lint && npm run typecheck

format:
	$(PYTHON) -m ruff check --fix backend scripts
	$(PYTHON) -m ruff format backend scripts
	cd frontend && npm run lint -- --fix

typecheck:
	cd frontend && npm run typecheck

build:
	cd frontend && npm run build

check:
	./scripts/check.sh

validate:
	PYTHONPATH=backend $(PYTHON) scripts/validate_config.py

hooks:
	git config core.hooksPath .githooks
	chmod +x .githooks/pre-commit
	@echo "Git hooks enabled from .githooks/"

docker-build:
	$(COMPOSE) build

docker-up:
	$(COMPOSE) up --build -d
	@echo "Bamboo11y: http://127.0.0.1:8000"
	@echo "Observability profile: $(COMPOSE) --profile observability up -d"

docker-down:
	$(COMPOSE) down

docker-logs:
	$(COMPOSE) logs -f bamboo11y

clean:
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov
	find backend scripts -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf frontend/dist frontend/coverage frontend/.vite
	@echo "Caches and build output removed; data/ was left untouched."
