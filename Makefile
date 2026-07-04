# Katbook VIP — developer & ops shortcuts.
# All targets are CPU-only except `verify-gpu` and the docker GPU services.
PY ?= python
COMPOSE ?= docker compose

.PHONY: help install-dev lint format typecheck test smoke migrate up down logs verify-gpu clean

help:
	@echo "Targets:"
	@echo "  install-dev  install dev + api deps (CPU) into the current env"
	@echo "  lint         ruff check"
	@echo "  format       ruff format"
	@echo "  typecheck    mypy api/"
	@echo "  test         pytest (CPU, models mocked)"
	@echo "  smoke        full pipeline on a generated 10s clip (CPU, no GPU, no DB)"
	@echo "  migrate      alembic upgrade head (needs DATABASE_URL)"
	@echo "  up / down    docker compose up -d / down"
	@echo "  verify-gpu   run scripts/verify_gpu.py (run on the 5090 box FIRST)"

install-dev:
	$(PY) -m pip install -e ".[dev]"
	$(PY) -m spacy download en_core_web_sm

lint:
	$(PY) -m ruff check .

format:
	$(PY) -m ruff format .

typecheck:
	$(PY) -m mypy

test:
	$(PY) -m pytest

smoke:
	$(PY) scripts/smoke.py

migrate:
	$(PY) -m alembic upgrade head

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=100

verify-gpu:
	$(PY) scripts/verify_gpu.py

clean:
	rm -rf .pytest_cache .ruff_cache **/__pycache__ build dist *.egg-info
