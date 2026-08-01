# Load ignored local defaults, while preserving an explicit process override.
PROCESS_DATABASE_URL := $(DATABASE_URL)
-include .env
ifneq ($(strip $(PROCESS_DATABASE_URL)),)
DATABASE_URL := $(PROCESS_DATABASE_URL)
endif

DATABASE_URL ?= postgresql://localhost:55432/retrieval?sslmode=disable
PGVECTOR_VERSION ?= v0.8.2
PGVECTOR_MIN_VERSION ?= 0.8.1
POSTGRES_MIN_VERSION ?= 18.3
PYTHON ?= .venv/bin/python
UVICORN ?= .venv/bin/uvicorn
BACKGROUND_DOCUMENTS ?= 15000
LOCAL_BACKGROUND_DOCUMENTS ?= 200
CAPTURE_BUNDLE ?=
SEED_ARTIFACT ?=
SOURCE_ARCHIVE ?=
CORE_SQL_FILES := \
	sql/00_extensions.sql \
	sql/01_schema.sql \
	sql/02_indexes.sql \
	sql/03_search_functions.sql \
	sql/04_diagnostics.sql \
	sql/05_evaluation.sql \
	sql/06_receipts.sql \
	sql/07_search_index_verification.sql \
	sql/08_query_runtime.sql \
	sql/09_traverse_evidence.sql \
	sql/10_admission.sql

SECURITY_SQL_FILES := \
	sql/11_roles_rls.sql \
	sql/12_masking.sql

export DATABASE_URL
export PGVECTOR_VERSION
export PGVECTOR_MIN_VERSION
export POSTGRES_MIN_VERSION

.PHONY: install aurora-local-env schema security-schema security-checks aurora-verify doctor test api frontend smoke clean seed-casework seed-project seed-local seed-dump seed-restore source-archive

install:
	python -m venv .venv
	. .venv/bin/activate && pip install -r backend/requirements.txt

aurora-local-env:
	scripts/configure_local_aurora.sh

schema:
	$(PYTHON) backend/scripts/check_postgres.py --min-version $(POSTGRES_MIN_VERSION)
	$(PYTHON) backend/scripts/check_pgvector.py --available --min-version $(PGVECTOR_MIN_VERSION)
	$(PYTHON) backend/scripts/run_sql.py --files $(CORE_SQL_FILES)
	$(PYTHON) backend/scripts/check_pgvector.py --min-version $(PGVECTOR_MIN_VERSION)

security-schema:
	$(PYTHON) backend/scripts/check_postgres.py --min-version $(POSTGRES_MIN_VERSION)
	$(PYTHON) backend/scripts/check_pgvector.py --available --min-version $(PGVECTOR_MIN_VERSION)
	$(PYTHON) backend/scripts/run_sql.py --files $(CORE_SQL_FILES) $(SECURITY_SQL_FILES)
	$(PYTHON) backend/scripts/check_pgvector.py --min-version $(PGVECTOR_MIN_VERSION)

security-checks:
	WORKBENCH_SECURITY_ENABLED=1 FAIL_ON_BLOCKED=1 gates/checks.sh G-27 G-29 G-30 G-31

aurora-verify: schema
	$(PYTHON) backend/scripts/check_postgres.py --min-version 18.3
	$(PYTHON) backend/scripts/check_pgvector.py --min-version 0.8.1

doctor:
	$(PYTHON) backend/scripts/doctor.py

test:
	@if [ -n "$$TEST_DATABASE_URL" ] && [ "$$ALLOW_TEST_DATABASE_RESET" = "1" ]; then \
		DATABASE_URL="$$TEST_DATABASE_URL" $(PYTHON) -m unittest discover -s backend/tests -v; \
	else \
		$(PYTHON) -m unittest discover -s backend/tests -v; \
	fi

seed-casework:
	@test -n "$(CAPTURE_BUNDLE)" || (echo "CAPTURE_BUNDLE is required for release seeding" >&2; exit 2)
	$(PYTHON) backend/scripts/build_search_index.py \
		--load-casework \
		--capture-bundle $(CAPTURE_BUNDLE) \
		--require-release-capture \
		--verify-cache \
		--background-documents $(BACKGROUND_DOCUMENTS)

seed-project:
	$(PYTHON) backend/scripts/build_search_index.py

seed-local:
	$(PYTHON) backend/scripts/build_search_index.py \
		--load-casework \
		--offline-capture \
		--provider hash \
		--background-documents $(LOCAL_BACKGROUND_DOCUMENTS)

# Produce the packaged restore artifact the Workshop Studio stack provisions
# from. Run against a disposable database that has been through `make schema`
# and `make seed-casework`, never the live workshop cluster.
seed-dump:
	seed/dump.sh $(SEED_ARTIFACT)

# Restore that artifact. This is what the CFN SeedDatabase step runs.
seed-restore:
	seed/load.sh $(SEED_ARTIFACT)

# Package the committed tree plus the seed artifact into the Workshop Studio
# source archive. Run `make seed-dump` from this revision first. This is the
# only supported producer: the published archive drifted five schema
# generations while it was assembled by hand.
source-archive:
	scripts/build_source_archive.sh $(SOURCE_ARCHIVE)

api:
	$(UVICORN) backend.app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

smoke:
	$(PYTHON) backend/scripts/smoke_test.py

clean:
	rm -rf data/generated frontend/dist .pytest_cache
