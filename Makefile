SHELL := /bin/bash
PYTHON ?= python3
DATABASE_URL ?= postgresql://postgres:postgres@localhost:5432/catalog_workshop
API_PORT ?= 8000
UI_PORT ?= 5173

.PHONY: generate prepare media-map quality reviews validate test render-sql db-init db-load db-load-catalog db-load-media db-embed db-index simulate api-serve ui-install ui-build ui-test ui-audit ui-dev mcp-install mcp-test mcp-serve

generate:
	$(PYTHON) scripts/generate_catalog.py
	$(PYTHON) scripts/prepare_catalog.py
	$(PYTHON) scripts/materialize_image_urls.py
	$(PYTHON) scripts/catalog_quality.py

prepare:
	$(PYTHON) scripts/prepare_catalog.py
	$(PYTHON) scripts/materialize_image_urls.py
	$(PYTHON) scripts/catalog_quality.py

media-map:
	$(PYTHON) scripts/materialize_image_urls.py

quality:
	$(PYTHON) scripts/catalog_quality.py

reviews:
	$(PYTHON) scripts/generate_reviews.py

validate:
	$(PYTHON) scripts/validate_package.py

test:
	$(PYTHON) -m pytest

render-sql:
	$(PYTHON) scripts/render_sql.py --vector-dim $${VECTOR_DIM:-1024}

db-init:
	psql "$(DATABASE_URL)" -f sql/00_extensions.sql -f sql/01_schema.sql

db-load: db-load-catalog db-load-media

db-load-catalog:
	DATABASE_URL="$(DATABASE_URL)" $(PYTHON) scripts/load_catalog.py

db-load-media:
	DATABASE_URL="$(DATABASE_URL)" $(PYTHON) scripts/load_media.py

db-embed:
	DATABASE_URL="$(DATABASE_URL)" $(PYTHON) scripts/embed_catalog.py

db-index:
	psql "$(DATABASE_URL)" -f sql/03_indexes.sql

simulate:
	$(PYTHON) scripts/simulate_scale.py

api-serve:
	DATABASE_URL="$(DATABASE_URL)" $(PYTHON) -m uvicorn service.main:app --host 127.0.0.1 --port $(API_PORT)

ui-install:
	cd ui && npm ci

ui-build:
	cd ui && npm run build

ui-test:
	cd ui && npm test

ui-audit:
	cd ui && npm audit --audit-level=moderate

ui-dev:
	cd ui && CATALOG_API_PROXY="$${CATALOG_API_PROXY:-http://127.0.0.1:$(API_PORT)}" npm run dev -- --host 127.0.0.1 --port $(UI_PORT)

mcp-install:
	$(PYTHON) -m venv mcp-server/.venv
	mcp-server/.venv/bin/python -m pip install -e "./mcp-server[dev]"

mcp-test:
	mcp-server/.venv/bin/python -m pytest -c mcp-server/pyproject.toml mcp-server/mcp_tests

mcp-serve:
	mcp-server/.venv/bin/catalog-studio-mcp
