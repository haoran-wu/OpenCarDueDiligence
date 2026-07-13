SHELL := /bin/sh
VENV ?= .venv
PYTHON := $(VENV)/bin/python
PIP := $(PYTHON) -m pip

.PHONY: bootstrap test test-python test-quickstart test-npm typecheck build smoke free-check audit dev-api dev-web \
	quickstart quickstart-prepare quickstart-status quickstart-stop quickstart-delete-data \
	docker-config docker-up docker-down docker-cloud-up docker-cloud-down

bootstrap:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e 'services/api[test,cloud]' -e 'services/worker[dev]' -e 'services/obd-bridge[dev]'
	npm ci

test: test-python test-npm

test-python:
	PYTHONPATH=services/api $(PYTHON) -m pytest -q services/api/tests services/worker/tests services/obd-bridge/tests
	python3 -m unittest discover -s scripts/tests -p 'test_*.py'

test-quickstart:
	python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v

test-npm:
	npm test

typecheck:
	npm run typecheck

build:
	npm run build

smoke:
	$(PYTHON) scripts/smoke_v1.py

free-check:
	python3 scripts/check_free_distribution.py

audit:
	$(VENV)/bin/pip-audit --progress-spinner off
	npm audit --omit=dev --audit-level=high

dev-api:
	OCDD_DATA_ROOT=$(CURDIR)/data $(PYTHON) -m uvicorn app.main:app --app-dir services/api --reload --port 8000

dev-web:
	npm run dev:web

quickstart:
	python3 scripts/quickstart.py

quickstart-prepare:
	python3 scripts/quickstart.py prepare

quickstart-status:
	python3 scripts/quickstart.py status

quickstart-stop:
	python3 scripts/quickstart.py stop

quickstart-delete-data:
	python3 scripts/quickstart.py stop --delete-data

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
