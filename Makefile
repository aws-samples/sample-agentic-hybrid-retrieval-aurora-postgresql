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

# The optional security module. Applied only by `make security-schema`, and only
# after the core files, because both depend on the casework and retrieval tables
# they gate. Re-run sql/01_schema.sql first if evidence ACLs changed: the ACL
# reconciliation there is what these policies read.
SECURITY_SQL_FILES := \
	sql/11_roles_rls.sql \
	sql/12_masking.sql

export DATABASE_URL
export PGVECTOR_VERSION
export PGVECTOR_MIN_VERSION
export POSTGRES_MIN_VERSION

.PHONY: install aurora-local-env schema prepare-workload security-schema security-checks agentcore-generate agentcore-invoke aurora-verify doctor test live-workshop api frontend smoke clean source-archive

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

prepare-workload:
	$(PYTHON) labs/incident/prepare_workload.py

# Optional module: enforce evidence access with PostgreSQL RLS and column
# masking. Applies the core files first so the policies land on the current
# schema, then sql/11 and sql/12. Run this against the database that already
# holds a completed `make live-workshop` run: both files read real captured
# evidence to decide what is restricted.
security-schema:
	$(PYTHON) backend/scripts/check_postgres.py --min-version $(POSTGRES_MIN_VERSION)
	$(PYTHON) backend/scripts/check_pgvector.py --available --min-version $(PGVECTOR_MIN_VERSION)
	$(PYTHON) backend/scripts/run_sql.py --files $(CORE_SQL_FILES) $(SECURITY_SQL_FILES)
	$(PYTHON) backend/scripts/check_pgvector.py --min-version $(PGVECTOR_MIN_VERSION)

# Prove the module on the participant's own data. FAIL_ON_BLOCKED=1 because a
# BLOCKED security gate here means the policies were never applied, which must
# not read as a pass.
security-checks:
	WORKBENCH_SECURITY_ENABLED=1 FAIL_ON_BLOCKED=1 gates/checks.sh G-27 G-29 G-30 G-31

# Optional module: publish the retrieval tools through a managed AgentCore
# Gateway. The adapters are generated from agent/registry.py, so regenerate and
# let G-17 prove the committed files still match byte for byte.
agentcore-generate:
	$(PYTHON) -m agent.generate_mcp_server
	$(PYTHON) -m agent.generate_gateway_dispatch
	FAIL_ON_BLOCKED=1 gates/checks.sh G-17

# Call the deployed Gateway with the current AWS identity and require the
# receipt-derived unsafe change to rank first, so a green run proves Aurora
# ranking survived the managed boundary rather than proving connectivity alone.
agentcore-invoke:
	$(PYTHON) scripts/invoke_agentcore_gateway.py --assert-incident

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

live-workshop:
	$(PYTHON) labs/incident/run_live_workshop.py

source-archive:
	scripts/build_live_source_archive.sh $(SOURCE_ARCHIVE)

api:
	$(UVICORN) backend.app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

smoke:
	$(PYTHON) backend/scripts/smoke_test.py

clean:
	rm -rf data/generated frontend/dist .pytest_cache
