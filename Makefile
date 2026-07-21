# Load ignored local overrides, such as DATABASE_URL for a deployed Aurora cluster.
-include .env

DATABASE_URL ?= postgresql://localhost:55432/retrieval?sslmode=disable
PGVECTOR_VERSION ?= v0.8.2
PGVECTOR_MIN_VERSION ?= 0.8.1
POSTGRES_MIN_VERSION ?= 18.3
PYTHON ?= .venv/bin/python
UVICORN ?= .venv/bin/uvicorn
GITHUB_REPO_PATH ?= .
GITHUB_REPOSITORY_URL ?=
GITHUB_TRANSPORT ?= local
GITHUB_REF ?= main
GITHUB_SOURCE_NAME ?= verity-source-repository
GITHUB_PROJECT_KEY ?= VERITY
GITHUB_EXPORT ?= data/live/github/repository_source_objects.jsonl
GITHUB_CURSOR ?= data/live/github/repository_manifest.json
SQL_FILES := sql/00_extensions.sql sql/01_schema.sql sql/12_search_tsv.sql sql/14_connector_sync.sql sql/02_indexes.sql sql/03_search_functions.sql sql/04_diagnostics.sql sql/05_evaluation.sql sql/06_agent_answers.sql sql/08_pgvector_08.sql sql/09_evaluation_metrics.sql sql/10_query_plan.sql sql/11_traverse_links.sql sql/13_acl_seed.sql

export DATABASE_URL
export PGVECTOR_VERSION
export PGVECTOR_MIN_VERSION
export POSTGRES_MIN_VERSION
export GITHUB_TOKEN

.PHONY: install aurora-local-env schema aurora-verify doctor sample load embed api frontend smoke clean seed-generate seed-jsonl seed-load github-export github-sync

install:
	python -m venv .venv
	. .venv/bin/activate && pip install -r backend/requirements.txt

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

doctor:
	$(PYTHON) backend/scripts/doctor.py

sample:
	$(PYTHON) backend/scripts/generate_workshop_operational_data.py --objects 2000 --out data/generated --seed 42

load:
	$(PYTHON) backend/scripts/load_jsonl_to_postgres.py --input data/generated/source_objects.jsonl --truncate

embed:
	$(PYTHON) backend/scripts/embed_chunks.py --batch-size 500

github-export:
	$(PYTHON) connectors/github_repository.py \
		--repo "$(GITHUB_REPO_PATH)" \
		--repository-url "$(GITHUB_REPOSITORY_URL)" \
		--transport "$(GITHUB_TRANSPORT)" \
		--github-ref "$(GITHUB_REF)" \
		--project-key "$(GITHUB_PROJECT_KEY)" \
		--output "$(GITHUB_EXPORT)" \
		--manifest "$(GITHUB_CURSOR)"

github-sync: github-export
	$(PYTHON) backend/scripts/load_jsonl_to_postgres.py \
		--input "$(GITHUB_EXPORT)" \
		--source-name "$(GITHUB_SOURCE_NAME)" \
		--source-system github \
		--sync-mode full \
		--sync-cursor-file "$(GITHUB_CURSOR)"
	$(PYTHON) backend/scripts/embed_chunks.py \
		--batch-size 100 \
		--source-name "$(GITHUB_SOURCE_NAME)" \
		--source-system github

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

clean:
	rm -rf data/generated frontend/dist .pytest_cache
