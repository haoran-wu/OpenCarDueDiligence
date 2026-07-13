SHELL := /bin/sh
VENV ?= .venv
PYTHON := $(VENV)/bin/python
PIP := $(PYTHON) -m pip

.PHONY: bootstrap test test-python test-npm typecheck build smoke audit dev-api dev-web \
	docker-config docker-up docker-down docker-cloud-up docker-cloud-down

bootstrap:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e 'services/api[test,cloud]' -e 'services/worker[dev]' -e 'services/obd-bridge[dev]'
	npm ci

test: test-python test-npm

test-python:
	PYTHONPATH=services/api $(PYTHON) -m pytest -q services/api/tests services/worker/tests services/obd-bridge/tests

test-npm:
	npm test

typecheck:
	npm run typecheck

build:
	npm run build

smoke:
	$(PYTHON) scripts/smoke_v1.py

audit:
	$(VENV)/bin/pip-audit --progress-spinner off
	npm audit --omit=dev --audit-level=high

dev-api:
	OCDD_DATA_ROOT=$(CURDIR)/data $(PYTHON) -m uvicorn app.main:app --app-dir services/api --reload --port 8000

dev-web:
	npm run dev:web

docker-config:
	docker compose config --quiet
	docker compose -f docker-compose.cloud.yml config --quiet

docker-up:
	docker compose up --build

docker-down:
	docker compose down

docker-cloud-up:
	docker compose -f docker-compose.cloud.yml up --build

docker-cloud-down:
	docker compose -f docker-compose.cloud.yml down
