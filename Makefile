.PHONY: help sync run dev test lint format typecheck check policy-schema agent \
	ui-install ui-dev ui-build up down build rebuild logs ps db clean

help:
	@echo "Targets:"
	@echo "  sync       - install/sync dependencies (uv sync --all-groups)"
	@echo "  run        - run the gateway with uvicorn (no reload)"
	@echo "  dev        - run the gateway with uvicorn --reload"
	@echo "  test       - run the test suite"
	@echo "  lint       - run ruff check"
	@echo "  format     - run ruff format"
	@echo "  typecheck  - run pyright"
	@echo "  check      - lint + typecheck + test"
	@echo "  policy-schema - generate policy JSON Schema"
	@echo "  agent      - run the exfiltrate-pii red-team scenario"
	@echo "  ui-install - install frontend dependencies"
	@echo "  ui-dev     - run frontend dev server"
	@echo "  ui-build   - build frontend into frontend/dist"
	@echo "  up         - docker compose up --build gateway"
	@echo "  down       - docker compose down"
	@echo "  build      - docker compose build"
	@echo "  rebuild    - down --remove-orphans, build --no-cache, up -d --force-recreate"
	@echo "  logs       - docker compose logs -f"
	@echo "  ps         - docker compose ps"
	@echo "  db         - docker compose up -d postgres"
	@echo "  clean      - remove caches and build artifacts"

sync:
	uv sync --all-groups

run:
	uv run uvicorn app.main:create_app --factory

dev:
	uv run uvicorn app.main:create_app --factory --reload

test:
	uv run pytest

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run pyright

check: lint typecheck test

policy-schema:
	uv run python scripts/generate_policy_schema.py

agent:
	uv run python -m app.agents --scenario exfiltrate-pii

ui-install:
	npm --prefix frontend install

ui-dev:
	npm --prefix frontend run dev

ui-build:
	npm --prefix frontend run build

up:
	docker compose up 

down:
	docker compose down

build:
	docker compose build

rebuild:
	docker compose down --remove-orphans
	docker compose build 
	docker compose up -d --force-recreate --remove-orphans

logs:
	docker compose logs -f

ps:
	docker compose ps

db:
	docker compose up -d postgres

clean:
	rm -rf .pytest_cache .ruff_cache
	find . -type d -name "__pycache__" -exec rm -rf {} +
