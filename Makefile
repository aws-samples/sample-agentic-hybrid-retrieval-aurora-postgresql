DATABASE_URL ?= postgresql://localhost:55432/retrieval?sslmode=disable
PGVECTOR_VERSION ?= v0.8.2
PGVECTOR_MIN_VERSION ?= 0.8.2
POSTGRES_MIN_VERSION ?= 18.4
PYTHON ?= .venv/bin/python
UVICORN ?= .venv/bin/uvicorn
SQL_FILES := sql/00_extensions.sql sql/01_schema.sql sql/02_indexes.sql sql/03_search_functions.sql sql/04_diagnostics.sql sql/05_evaluation.sql

export DATABASE_URL
export PGVECTOR_VERSION
export PGVECTOR_MIN_VERSION
export POSTGRES_MIN_VERSION

.PHONY: install install-pgvector local-db-start local-db-stop local-db-bootstrap schema sample load embed api frontend smoke clean

install:
	python -m venv .venv
	. .venv/bin/activate && pip install -r backend/requirements.txt

install-pgvector:
	scripts/install_pgvector.sh

local-db-start:
	scripts/local_postgres.sh start

local-db-stop:
	scripts/local_postgres.sh stop

local-db-bootstrap:
	scripts/local_postgres.sh bootstrap

schema:
	$(PYTHON) backend/scripts/check_postgres.py --min-version $(POSTGRES_MIN_VERSION)
	$(PYTHON) backend/scripts/check_pgvector.py --available --min-version $(PGVECTOR_MIN_VERSION)
	$(PYTHON) backend/scripts/run_sql.py --files $(SQL_FILES)
	$(PYTHON) backend/scripts/check_pgvector.py --min-version $(PGVECTOR_MIN_VERSION)

sample:
	$(PYTHON) backend/scripts/generate_workshop_operational_data.py --objects 2000 --out data/generated --seed 42

load:
	$(PYTHON) backend/scripts/load_jsonl_to_postgres.py --input data/generated/source_objects.jsonl --truncate

embed:
	$(PYTHON) backend/scripts/embed_chunks.py --provider hash --batch-size 500

api:
	$(UVICORN) backend.app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

smoke:
	$(PYTHON) backend/scripts/smoke_test.py

clean:
	rm -rf data/generated frontend/dist .pytest_cache
