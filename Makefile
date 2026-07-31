.PHONY: help sync run dev test lint format typecheck check agent \
	up down build logs ps db clean

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
	@echo "  agent      - run the exfiltrate-pii red-team scenario"
	@echo "  up         - docker compose up --build gateway"
	@echo "  down       - docker compose down"
	@echo "  build      - docker compose build"
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

agent:
	uv run python -m app.agents --scenario exfiltrate-pii

up:
	docker compose up --build gateway

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f

ps:
	docker compose ps

db:
	docker compose up -d postgres

clean:
	rm -rf .pytest_cache .ruff_cache
	find . -type d -name "__pycache__" -exec rm -rf {} +
