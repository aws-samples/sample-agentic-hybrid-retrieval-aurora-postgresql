SHELL := /bin/bash
PYTHON_VERSION := 3.13
VENV ?= .venv
VENV_PYTHON := $(VENV)/bin/python
BOOTSTRAP_PYTHON ?= python3.13
UV ?= uv
PYTHON ?= $(if $(wildcard $(VENV_PYTHON)),$(VENV_PYTHON),$(BOOTSTRAP_PYTHON))
MCP_VENV ?= mcp-server/.venv
MCP_PYTHON ?= $(MCP_VENV)/bin/python
# No default DSN. There is no local database (ARTIFACTS.md), so a localhost
# default could only ever fail — or, worse, succeed against an unintended
# cluster. Every db-* target requires DATABASE_URL to be set explicitly.
DATABASE_URL ?=
API_PORT ?= 8000
UI_PORT ?= 5173
# deploy/mosaic-bootstrap.sh is the source of truth; the workshop repository keeps
# a byte-identical copy because CloudFormation UserData reads it from S3 before any
# clone exists. See deploy/README.md.
BOOTSTRAP_SCRIPT ?= deploy/mosaic-bootstrap.sh
WORKSHOP_REPO ?= ../build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql
WORKSHOP_BOOTSTRAP ?= $(WORKSHOP_REPO)/assets/mosaic-bootstrap.sh
LAB_API_URL ?= http://127.0.0.1:$(API_PORT)
SCORE_EVAL_ARGS ?=

# The Mosaic data model is vendored under db/, rendered at 1024 dimensions.
SCHEMA_PACKAGE ?= db
VECTOR_DIM ?= 1024
EMBEDDING_CACHE_DIR ?= build/embedding-cache
EMBEDDING_CACHE_MANIFEST ?= $(EMBEDDING_CACHE_DIR)/manifest.json
EMBEDDING_CACHE_CONTRACT ?= db/config/embedding-cache.json
EMBEDDING_CACHE_URI ?=
BOOTSTRAP_TIMINGS_FILE ?= build/bootstrap-timings.tsv
MOSAIC_NORMALIZED_DIR ?= build/normalized
MOSAIC_PREMIUM_COHORT_CSV ?= $(MOSAIC_NORMALIZED_DIR)/premium_cohort_120.csv
MOSAIC_CATALOG_SHARDS := \
	data/full/products_consumer_electronics.csv.gz \
	data/full/products_running_fitness.csv.gz \
	data/full/products_home_office.csv.gz

.PHONY: setup doctor check-dsn check-python check-bootstrap-python check-mcp-python generate prepare media-map media-labels media-shot-list media-install-flagships media-import quality reviews validate validate-db lint test db-install db-install-labs db-upgrade-snapshot db-configure-retrieval validate-missions validate-evals score-evals validate-config validate-functions lab-01 lab-status reset-lab-1 validate-lab-1 solution-lab-1 reset-lab-2 validate-lab-2 solution-lab-2 reset-lab-3 validate-lab-3 solution-lab-3 restart-lab-api db-apply-search-functions db-render db-prepare-mosaic db-load-mosaic db-bootstrap-cached db-fetch-embeddings verify-embedding-cache db-verify-bootstrap db-smoke db-index-concurrent db-load-cohort db-load-evidence db-embed db-export-embeddings db-import-embeddings simulate db-seed-exact-neighbors check-exact-neighbors benchmark-hnsw benchmark-ask-mosaic api-serve ui-install ui-build ui-test ui-audit ui-dev mcp-install mcp-test mcp-serve sync-bootstrap check-bootstrap-sync

PYTHON_TARGETS := generate prepare media-map media-labels media-shot-list \
	media-install-flagships media-import quality reviews validate validate-db \
	validate-missions validate-evals score-evals validate-config validate-functions \
	test db-render db-prepare-mosaic \
	db-embed simulate db-export-embeddings db-import-embeddings \
	verify-embedding-cache db-configure-retrieval lab-status validate-lab-3 solution-lab-3 api-serve \
	mcp-install

$(PYTHON_TARGETS): check-python

# An unset DSN must fail by name, not by handing psql an empty string and letting
# it try to reach a local socket that does not exist.
check-dsn:
	@test -n "$(DATABASE_URL)" || { \
		echo "DATABASE_URL is not set. There is no local database; point it at"; \
		echo "the Aurora cluster. See ARTIFACTS.md for the connection notes,"; \
		echo "including sslnegotiation=direct on a corporate network."; \
		exit 2; \
	}

DSN_TARGETS := test db-install db-install-labs db-upgrade-snapshot \
	validate-missions validate-evals score-evals validate-functions \
	lab-01 db-load-mosaic db-index-concurrent db-load-cohort db-load-evidence db-smoke \
	db-bootstrap-cached db-verify-bootstrap db-embed db-export-embeddings db-import-embeddings \
	db-configure-retrieval db-apply-search-functions reset-lab-1 validate-lab-1 solution-lab-1 \
	reset-lab-2 validate-lab-2 solution-lab-2 reset-lab-3 api-serve

$(DSN_TARGETS): check-dsn

setup: check-bootstrap-python
	$(UV) sync --frozen
	$(UV) pip check

doctor: check-python
	$(UV) pip check

check-python:
	@"$(PYTHON)" -c 'import sys; expected = (3, 13); actual = sys.version_info[:2]; print(f"Python {sys.version.split()[0]} ({sys.executable})"); raise SystemExit(0 if actual == expected else "Mosaic requires Python 3.13")'

check-bootstrap-python:
	@"$(BOOTSTRAP_PYTHON)" -c 'import sys; expected = (3, 13); actual = sys.version_info[:2]; print(f"Python {sys.version.split()[0]} ({sys.executable})"); raise SystemExit(0 if actual == expected else "Mosaic requires Python 3.13")'

check-mcp-python:
	@test -x "$(MCP_PYTHON)" || { echo "MCP environment is missing. Run 'make mcp-install'."; exit 1; }
	@"$(MCP_PYTHON)" -c 'import sys; expected = (3, 13); actual = sys.version_info[:2]; print(f"MCP Python {sys.version.split()[0]} ({sys.executable})"); raise SystemExit(0 if actual == expected else "Mosaic MCP requires Python 3.13")'

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

# Product-bound photography: the fixed premium 120 plus the focused 80.
media-labels:
	$(PYTHON) scripts/build_asset_labels.py

media-shot-list: media-labels
	$(PYTHON) scripts/build_shot_list.py

media-install-flagships:
	$(PYTHON) scripts/install_cohort_assets.py

# SOURCE=~/Downloads/batch make media-import
media-import:
	$(PYTHON) scripts/import_generated_images.py --source "$(SOURCE)"

# --- Mosaic data model (db/) ----------------------------------------------
# Installs schemas, tables, functions, and non-concurrent indexes. HNSW indexes
# are deliberately excluded: CREATE INDEX CONCURRENTLY cannot run inside a
# transaction block, and they are pointless before embeddings exist.
db-install:
	@cd $(SCHEMA_PACKAGE)/sql && psql "$(DATABASE_URL)" -v ON_ERROR_STOP=1 -f install.sql
	@$(MAKE) db-configure-retrieval DATABASE_URL="$(DATABASE_URL)"

# Evaluation and benchmark schemas. Separate so the session's `\dt mosaic.*`
# shows the 12 tables the application reads, not 21.
db-install-labs:
	@cd $(SCHEMA_PACKAGE)/sql && psql "$(DATABASE_URL)" -v ON_ERROR_STOP=1 -f install_labs.sql

# Operator-only compatibility path for historical snapshot restores. Workshop
# Studio provisions fresh Aurora through db-bootstrap-cached.
db-upgrade-snapshot:
	@cd $(SCHEMA_PACKAGE)/sql && psql "$(DATABASE_URL)" -v ON_ERROR_STOP=1 -f upgrade_snapshot.sql
	@$(MAKE) db-configure-retrieval DATABASE_URL="$(DATABASE_URL)"

db-configure-retrieval:
	@DATABASE_URL="$(DATABASE_URL)" $(PYTHON) scripts/configure_retrieval_database.py

# The mission contract gate. Shape checks always run; target checks need a DSN
# and call mosaic_search.matches_filters on the cluster rather than
# reimplementing filter logic. Set MISSION_GATE_REQUIRE_DB=1 in CI so a missing
# DSN is a loud failure instead of a silent skip.
validate-missions:
	@DATABASE_URL="$(DATABASE_URL)" $(PYTHON) scripts/mission_contract.py

# The 720-case filter-contract corpus and the 20-query canonical scorecard both
# call matches_filters on Aurora before an eval can spend model calls or
# publish metrics.
validate-evals:
	@DATABASE_URL="$(DATABASE_URL)" $(PYTHON) scripts/run_eval.py --validate-only
	@DATABASE_URL="$(DATABASE_URL)" $(PYTHON) scripts/run_eval.py \
		--queries data/evals/canonical_queries.jsonl --validate-only

# Release-only quality gate. It runs the 19 product-retrieval cases from the
# curated 20-query set through served FTS + pg_trgm + HNSW + unweighted RRF +
# managed reranking, then rejects provenance or metric regressions.
score-evals:
	@DATABASE_URL="$(DATABASE_URL)" $(PYTHON) scripts/score_evals.py $(SCORE_EVAL_ARGS)

# db/config/retrieval.yaml is the single source for candidate limits, fusion k,
# weights, and the trigram threshold. This fails if any other file declares one,
# and asserts every exempted SQL default and index parameter equals its yaml
# value. No database needed.
validate-config:
	$(PYTHON) scripts/retrieval_profile.py --check
	$(PYTHON) scripts/config_tripwire.py
	$(PYTHON) scripts/tool_contracts.py --check

# Exactly one live signature per retrieval function. CREATE OR REPLACE cannot
# change a signature, so a parameter change leaves the old body callable by any
# caller passing the old argument count. Needs a DSN; set
# FUNCTION_CENSUS_REQUIRE_DB=1 in CI so a missing DSN is a loud failure.
validate-functions:
	@DATABASE_URL="$(DATABASE_URL)" $(PYTHON) scripts/function_census.py

# Lab 1: lexical precision and typo tolerance, against the mosaic_search tree
# the API reads. Read-only; safe to re-run.
lab-01:
	@psql "$(DATABASE_URL)" -v ON_ERROR_STOP=1 -f $(SCHEMA_PACKAGE)/sql/lab_01_typo_tolerance.sql

lab-status:
	@$(PYTHON) scripts/lab_state.py status

db-apply-search-functions:
	@cd $(SCHEMA_PACKAGE)/sql && psql "$(DATABASE_URL)" -v ON_ERROR_STOP=1 \
		-f 09_search_functions.sql
	@$(MAKE) db-configure-retrieval DATABASE_URL="$(DATABASE_URL)"

reset-lab-1:
	@$(PYTHON) scripts/lab_state.py reset --lab 1
	@$(MAKE) db-apply-search-functions DATABASE_URL="$(DATABASE_URL)"

validate-lab-1:
	@$(PYTHON) scripts/lab_state.py validate --lab 1 --database-url "$(DATABASE_URL)"
	@$(PYTHON) scripts/validate_lab.py --lab 1 --api-url "$(LAB_API_URL)"

solution-lab-1:
	@$(PYTHON) scripts/lab_state.py solution --lab 1
	@$(MAKE) db-apply-search-functions DATABASE_URL="$(DATABASE_URL)"

reset-lab-2:
	@$(PYTHON) scripts/lab_state.py reset --lab 2
	@$(MAKE) db-apply-search-functions DATABASE_URL="$(DATABASE_URL)"

validate-lab-2:
	@$(PYTHON) scripts/lab_state.py validate --lab 2 --database-url "$(DATABASE_URL)"
	@$(PYTHON) scripts/validate_lab.py --lab 2 --api-url "$(LAB_API_URL)"

solution-lab-2:
	@$(PYTHON) scripts/lab_state.py solution --lab 2
	@$(MAKE) db-apply-search-functions DATABASE_URL="$(DATABASE_URL)"

reset-lab-3:
	@$(PYTHON) scripts/lab_state.py reset --lab 3
	@$(MAKE) db-apply-search-functions DATABASE_URL="$(DATABASE_URL)"
	@$(MAKE) restart-lab-api

validate-lab-3:
	@$(PYTHON) scripts/lab_state.py validate --lab 3
	@$(PYTHON) scripts/validate_lab.py --lab 3 --api-url "$(LAB_API_URL)"

solution-lab-3:
	@$(PYTHON) scripts/lab_state.py solution --lab 3
	@$(MAKE) restart-lab-api

restart-lab-api:
	@if command -v systemctl >/dev/null 2>&1 \
		&& systemctl cat mosaic-api.service >/dev/null 2>&1; then \
		if command -v sudo >/dev/null 2>&1; then \
			sudo systemctl restart mosaic-api.service; \
		else \
			systemctl restart mosaic-api.service; \
		fi; \
		systemctl is-active --quiet mosaic-api.service \
			|| { echo "mosaic-api failed to restart; run systemctl status mosaic-api.service"; exit 1; }; \
		echo "mosaic-api restarted"; \
	else \
		echo "mosaic-api is not systemd-managed in this environment; no restart required"; \
	fi

# Re-render the vendored SQL at a different embedding width.
db-render:
	$(PYTHON) $(SCHEMA_PACKAGE)/scripts/render_dimension.py \
		--dimension $(VECTOR_DIM) --output $(SCHEMA_PACKAGE)/sql

db-prepare-mosaic:
	$(PYTHON) $(SCHEMA_PACKAGE)/scripts/transform_legacy_catalog.py \
		$(MOSAIC_CATALOG_SHARDS) "$(MOSAIC_NORMALIZED_DIR)"
	$(PYTHON) scripts/export_premium_cohort.py \
		--output "$(MOSAIC_PREMIUM_COHORT_CSV)"

db-load-mosaic:
	@psql "$(DATABASE_URL)" -v ON_ERROR_STOP=1 \
		-v brands_path="$(MOSAIC_NORMALIZED_DIR)/brands.csv.gz" \
		-v categories_path="$(MOSAIC_NORMALIZED_DIR)/categories.csv.gz" \
		-v products_path="$(MOSAIC_NORMALIZED_DIR)/products.csv.gz" \
		-v offers_path="$(MOSAIC_NORMALIZED_DIR)/offers.csv.gz" \
		-f $(SCHEMA_PACKAGE)/sql/17_load_normalized_catalog.sql

# Run after embeddings are populated.
db-index-concurrent:
	@psql "$(DATABASE_URL)" -v ON_ERROR_STOP=1 -f $(SCHEMA_PACKAGE)/sql/08_indexes_concurrent.sql

db-load-cohort:
	@psql "$(DATABASE_URL)" -v ON_ERROR_STOP=1 \
		-v premium_cohort_path="$(MOSAIC_PREMIUM_COHORT_CSV)" \
		-f $(SCHEMA_PACKAGE)/sql/15_load_premium_cohort.sql

db-load-evidence:
	@psql "$(DATABASE_URL)" -v ON_ERROR_STOP=1 \
		-v review_evidence_path='data/sample/reviews_15000.csv.gz' \
		-f $(SCHEMA_PACKAGE)/sql/18_load_evidence.sql

db-smoke:
	@psql "$(DATABASE_URL)" -v ON_ERROR_STOP=1 -f $(SCHEMA_PACKAGE)/sql/99_smoke_test.sql

verify-embedding-cache:
	@$(PYTHON) scripts/embedding_cache.py verify \
		"$(EMBEDDING_CACHE_MANIFEST)" \
		--contract "$(EMBEDDING_CACHE_CONTRACT)"

db-fetch-embeddings:
	@test -n "$(EMBEDDING_CACHE_URI)" || { \
		echo "EMBEDDING_CACHE_URI must be an s3:// prefix"; exit 2; \
	}
	aws s3 sync "$(EMBEDDING_CACHE_URI)" "$(EMBEDDING_CACHE_DIR)" \
		--only-show-errors
	@$(MAKE) verify-embedding-cache

define bootstrap-phase
	@set -e; database_url="$(DATABASE_URL)"; \
	started=$$(date +%s); \
	printf 'MOSAIC_BOOTSTRAP_PHASE_START phase=%s epoch=%s\n' \
		"$(1)" "$$started"; \
	$(MAKE) $(2) DATABASE_URL="$$database_url"; \
	finished=$$(date +%s); \
	elapsed=$$((finished - started)); \
	printf '%s\t%s\n' "$(1)" "$$elapsed" >>"$(BOOTSTRAP_TIMINGS_FILE)"; \
	printf 'MOSAIC_BOOTSTRAP_PHASE_END phase=%s epoch=%s elapsed_seconds=%s\n' \
		"$(1)" "$$finished" "$$elapsed"
endef

db-bootstrap-cached:
	@test -f "$(EMBEDDING_CACHE_MANIFEST)" || { \
		echo "Embedding cache manifest not found: $(EMBEDDING_CACHE_MANIFEST)"; \
		exit 2; \
	}
	@$(MAKE) verify-embedding-cache
	@mkdir -p "$(dir $(BOOTSTRAP_TIMINGS_FILE))"
	@: >"$(BOOTSTRAP_TIMINGS_FILE)"
	$(call bootstrap-phase,schema_install,db-install)
	$(call bootstrap-phase,lab_schema_install,db-install-labs)
	$(call bootstrap-phase,catalog_prepare,db-prepare-mosaic)
	$(call bootstrap-phase,catalog_load,db-load-mosaic)
	$(call bootstrap-phase,embedding_import,db-import-embeddings)
	$(call bootstrap-phase,index_creation,db-index-concurrent)
	$(call bootstrap-phase,premium_cohort_load,db-load-cohort)
	$(call bootstrap-phase,evidence_load,db-load-evidence)
	$(call bootstrap-phase,smoke_test,db-smoke)
	$(call bootstrap-phase,bootstrap_acceptance,db-verify-bootstrap)
	@awk -F '\t' \
		'BEGIN { total = 0 } { total += $$2 } END { print "total\t" total }' \
		"$(BOOTSTRAP_TIMINGS_FILE)" >>"$(BOOTSTRAP_TIMINGS_FILE)"
	@cat "$(BOOTSTRAP_TIMINGS_FILE)"

db-verify-bootstrap:
	@psql "$(DATABASE_URL)" -v ON_ERROR_STOP=1 \
		-f $(SCHEMA_PACKAGE)/sql/98_bootstrap_acceptance.sql
	@DATABASE_URL="$(DATABASE_URL)" $(PYTHON) \
		scripts/configure_retrieval_database.py --check

validate-db:
	"$(PYTHON)" "$(SCHEMA_PACKAGE)/scripts/validate_package.py"

quality:
	$(PYTHON) scripts/catalog_quality.py

reviews:
	$(PYTHON) scripts/generate_reviews.py

validate:
	$(PYTHON) scripts/validate_package.py

# The workshop repository's copy is a delivery artifact, not a second source. Edit
# deploy/mosaic-bootstrap.sh, run this, and commit both.
sync-bootstrap:
	@test -f "$(WORKSHOP_BOOTSTRAP)" || { \
		echo "No workshop copy at $(WORKSHOP_BOOTSTRAP)."; \
		echo "Set WORKSHOP_REPO to the workshop checkout."; exit 1; }
	@cp "$(BOOTSTRAP_SCRIPT)" "$(WORKSHOP_BOOTSTRAP)"
	@echo "Synced $(BOOTSTRAP_SCRIPT) -> $(WORKSHOP_BOOTSTRAP)"
	@echo "BootstrapScriptSha256: $$(shasum -a 256 "$(BOOTSTRAP_SCRIPT)" | cut -d" " -f1)"

# Skips rather than fails when the workshop repository is not checked out beside
# this one, so a plain clone of this repository still passes.
check-bootstrap-sync:
	@if [ ! -f "$(WORKSHOP_BOOTSTRAP)" ]; then \
		echo "check-bootstrap-sync: skipped, no workshop checkout at $(WORKSHOP_REPO)"; \
	elif cmp -s "$(BOOTSTRAP_SCRIPT)" "$(WORKSHOP_BOOTSTRAP)"; then \
		echo "check-bootstrap-sync: identical"; \
	else \
		echo "check-bootstrap-sync: FAILED, the two copies differ"; \
		diff -u "$(WORKSHOP_BOOTSTRAP)" "$(BOOTSTRAP_SCRIPT)" | head -40; \
		echo "Run: make sync-bootstrap"; exit 1; \
	fi

lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	@$(MAKE) --no-print-directory check-bootstrap-sync

test:
	@DATABASE_URL="$(DATABASE_URL)" $(PYTHON) -m pytest

# Five targets were DELETED in Phase 2 Unit E. They installed and loaded the
# `catalog.*` tree, which no longer exists, against whatever DSN they were handed
# — including the live Aurora cluster. Their replacements target `mosaic_*`:
#
#   old target       new target             SQL
#   ---------------- ---------------------- ----------------------------------
#   db-init          db-install             db/sql/install.sql
#   db-load-catalog  db-load-mosaic         db/sql/17_load_normalized_catalog.sql
#   db-load-media    db-load-cohort         db/sql/15_load_premium_cohort.sql
#   db-index         db-index-concurrent    db/sql/08_indexes_concurrent.sql
#   db-load          db-bootstrap-cached    the whole sequence, in order
#
# See ARTIFACTS.md for the Aurora-only policy and docs/rewrite-losses.md
# SUBSTRATE-1 for why the predecessors cannot be run at all.

db-embed:
	@DATABASE_URL="$(DATABASE_URL)" $(PYTHON) scripts/embed_catalog.py

db-export-embeddings:
	@DATABASE_URL="$(DATABASE_URL)" $(PYTHON) scripts/embedding_cache.py \
		export --output "$(EMBEDDING_CACHE_DIR)"

db-import-embeddings:
	@DATABASE_URL="$(DATABASE_URL)" $(PYTHON) scripts/embedding_cache.py \
		import "$(EMBEDDING_CACHE_MANIFEST)"

simulate:
	$(PYTHON) scripts/simulate_scale.py

# Precomputes exact top-k neighbours for the 30 retrieval anchors across the six
# filter presets. Roughly 7 minutes: each exact query is a sequential scan, measured
# at 2.4s. Run once per corpus; the HNSW instrument computes recall against these
# rows rather than re-running the scan per interaction.
db-seed-exact-neighbors:
	@DATABASE_URL="$(DATABASE_URL)" $(PYTHON) scripts/seed_exact_neighbors.py --k 10

# Which models this account may actually invoke. An ACTIVE inference profile is
# not entitlement: a fresh Workshop Studio account answered "anthropic.claude-
# sonnet-5 is not available for this account" for the pinned agent model, and the
# Claude Code preflight failed three times as a result. The model ids come from
# service.config so this cannot drift from what the application asks for.
check-model-access:
	@$(PYTHON) scripts/check_model_access.py \
	  --chat "$$($(PYTHON) -c 'from service.config import get_settings as g; print(g().agent_model_id)')" \
	  --embed "$$($(PYTHON) -c 'from service.config import get_settings as g; print(g().embedding_model_id)')" \
	  --rerank "$$($(PYTHON) -c 'from service.config import get_settings as g; print(g().rerank_model_id)')"

check-exact-neighbors:
	@DATABASE_URL="$(DATABASE_URL)" $(PYTHON) scripts/seed_exact_neighbors.py --check

# Captures data/benchmarks/hnsw_measured.json, the artifact the HNSW instrument
# replays. Read-only against the catalog; writes measured rows to mosaic_bench.
benchmark-hnsw:
	@DATABASE_URL="$(DATABASE_URL)" AURORA_INSTANCE_CLASS="$(AURORA_INSTANCE_CLASS)" \
		$(PYTHON) scripts/benchmark_hnsw.py --queries 25 --k 10 \
		--ef-search 10 20 40 80 100 200 400 --filter-preset-matrix

benchmark-ask-mosaic:
	@DATABASE_URL="$(DATABASE_URL)" $(PYTHON) scripts/benchmark_ask_mosaic.py

api-serve:
	@DATABASE_URL="$(DATABASE_URL)" $(PYTHON) -m uvicorn service.main:app --host 127.0.0.1 --port $(API_PORT)

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
	"$(PYTHON)" -m venv "$(MCP_VENV)"
	"$(MCP_PYTHON)" -m pip install --upgrade pip
	"$(MCP_PYTHON)" -m pip install -e "./mcp-server[dev]"
	"$(MCP_PYTHON)" -m pip check

mcp-test: check-mcp-python
	"$(MCP_PYTHON)" -m pytest -c mcp-server/pyproject.toml mcp-server/mcp_tests

mcp-serve: check-mcp-python
	"$(MCP_VENV)/bin/mosaic-retrieval-mcp"
