# Load ignored local overrides, such as DATABASE_URL for a deployed Aurora cluster.
-include .env

DATABASE_URL ?= postgresql://localhost:55432/retrieval?sslmode=disable
PGVECTOR_VERSION ?= v0.8.2
PGVECTOR_MIN_VERSION ?= 0.8.1
POSTGRES_MIN_VERSION ?= 18.3
PYTHON ?= .venv/bin/python
UVICORN ?= .venv/bin/uvicorn
SQL_FILES := sql/00_extensions.sql sql/01_schema.sql sql/02_indexes.sql sql/03_search_functions.sql sql/04_diagnostics.sql sql/05_evaluation.sql

export DATABASE_URL
export PGVECTOR_VERSION
export PGVECTOR_MIN_VERSION
export POSTGRES_MIN_VERSION

.PHONY: install install-pgvector local-db-start local-db-stop local-db-bootstrap aurora-local-env schema aurora-verify sample load embed api frontend smoke clean seed-generate seed-jsonl seed-load agentcore-provision

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

aurora-local-env:
	scripts/configure_local_aurora.sh

schema:
	$(PYTHON) backend/scripts/check_postgres.py --min-version $(POSTGRES_MIN_VERSION)
	$(PYTHON) backend/scripts/check_pgvector.py --available --min-version $(PGVECTOR_MIN_VERSION)
	$(PYTHON) backend/scripts/run_sql.py --files $(SQL_FILES)
	$(PYTHON) backend/scripts/check_pgvector.py --min-version $(PGVECTOR_MIN_VERSION)

aurora-verify: schema
	$(PYTHON) backend/scripts/check_postgres.py --min-version 18.3
	$(PYTHON) backend/scripts/check_pgvector.py --min-version 0.8.1

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

# --- Workshop seed (canonical Orion corpus) ---------------------------------
# seed-jsonl:    write JSONL + manifest only (no DB needed) — quick sanity check
# seed-generate: full rebuild — populate DB + write the -Fc dump (needs DATABASE_URL)
# seed-load:     idempotent pg_restore of the dump + rebuild indexes (needs DATABASE_URL)
seed-jsonl:
	$(PYTHON) seed/generate.py --jsonl-only

seed-generate:
	$(PYTHON) seed/generate.py

seed-load:
	seed/load.sh

# --- Optional AgentCore Gateway + Runtime -----------------------------------
# Wires the CDK-managed Gateway Lambda into AgentCore and provisions the Gateway
# + BYO Runtime via the @aws/agentcore CLI. See agentcore/README.md.
agentcore-provision:
	agentcore/provision.sh

clean:
	rm -rf data/generated frontend/dist .pytest_cache agentcore/.build
