SHELL := /bin/bash
PYTHON_VERSION := 3.13
VENV ?= .venv
VENV_PYTHON := $(VENV)/bin/python
BOOTSTRAP_PYTHON ?= python3.13
PYTHON ?= $(if $(wildcard $(VENV_PYTHON)),$(VENV_PYTHON),$(BOOTSTRAP_PYTHON))
MCP_VENV ?= mcp-server/.venv
MCP_PYTHON ?= $(MCP_VENV)/bin/python
# No default DSN. There is no local database (ARTIFACTS.md), so a localhost
# default could only ever fail — or, worse, succeed against an unintended
# cluster. Every db-* target requires DATABASE_URL to be set explicitly.
DATABASE_URL ?=
API_PORT ?= 8000
UI_PORT ?= 5173

# The Mosaic data model is vendored under db/, rendered at 1024 dimensions.
SCHEMA_PACKAGE ?= db
VECTOR_DIM ?= 1024
EMBEDDING_CACHE_DIR ?= build/embedding-cache
EMBEDDING_CACHE_MANIFEST ?= $(EMBEDDING_CACHE_DIR)/manifest.json
EMBEDDING_CACHE_URI ?=
MOSAIC_NORMALIZED_DIR ?= build/normalized
MOSAIC_PREMIUM_COHORT_CSV ?= $(MOSAIC_NORMALIZED_DIR)/premium_cohort_120.csv
MOSAIC_CATALOG_SHARDS := \
	data/full/products_consumer_electronics.csv.gz \
	data/full/products_running_fitness.csv.gz \
	data/full/products_home_office.csv.gz

.PHONY: setup doctor check-dsn check-python check-bootstrap-python check-mcp-python generate prepare media-map media-labels media-shot-list media-install-flagships media-import quality reviews validate validate-db test db-install db-install-labs validate-missions validate-config validate-functions lab-01 db-render db-prepare-mosaic db-load-mosaic db-bootstrap-cached db-fetch-embeddings db-smoke db-index-concurrent db-load-cohort db-embed db-export-embeddings db-import-embeddings simulate api-serve ui-install ui-build ui-test ui-audit ui-dev mcp-install mcp-test mcp-serve

PYTHON_TARGETS := generate prepare media-map media-labels media-shot-list \
	media-install-flagships media-import quality reviews validate validate-db \
	validate-missions validate-config validate-functions \
	test db-render db-prepare-mosaic \
	db-embed simulate db-export-embeddings db-import-embeddings api-serve \
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

DSN_TARGETS := db-install db-install-labs validate-missions validate-functions \
	lab-01 db-load-mosaic db-index-concurrent db-load-cohort db-smoke \
	db-bootstrap-cached db-embed db-export-embeddings db-import-embeddings \
	api-serve

$(DSN_TARGETS): check-dsn

setup: check-bootstrap-python
	$(BOOTSTRAP_PYTHON) -m venv "$(VENV)"
	"$(VENV_PYTHON)" -m pip install --upgrade pip
	"$(VENV_PYTHON)" -m pip install -r config/requirements.txt
	"$(VENV_PYTHON)" -m pip check

doctor: check-python
	"$(PYTHON)" -m pip check

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

# Premium-cohort photography. SCHEMA_PACKAGE must point at the checked-in
# mosaic-data-models-aurora-v1 package (override on the command line until it
# is vendored into the repository).
media-labels:
	$(PYTHON) scripts/build_asset_labels.py \
		--cohort "$(SCHEMA_PACKAGE)/data/premium_cohort_120.json"

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
	cd $(SCHEMA_PACKAGE)/sql && psql "$(DATABASE_URL)" -v ON_ERROR_STOP=1 -f install.sql

# Evaluation and benchmark schemas. Separate so the session's `\dt mosaic.*`
# shows the 12 tables the application reads, not 21.
db-install-labs:
	cd $(SCHEMA_PACKAGE)/sql && psql "$(DATABASE_URL)" -v ON_ERROR_STOP=1 -f install_labs.sql

# The mission contract gate. Shape checks always run; target checks need a DSN
# and call mosaic_search.matches_filters on the cluster rather than
# reimplementing filter logic. Set MISSION_GATE_REQUIRE_DB=1 in CI so a missing
# DSN is a loud failure instead of a silent skip.
validate-missions:
	DATABASE_URL="$(DATABASE_URL)" $(PYTHON) scripts/mission_contract.py

# db/config/retrieval.yaml is the single source for candidate limits, fusion k,
# weights, and the trigram threshold. This fails if any other file declares one,
# and asserts every exempted SQL default and index parameter equals its yaml
# value. No database needed.
validate-config:
	$(PYTHON) scripts/retrieval_profile.py --check
	$(PYTHON) scripts/config_tripwire.py

# Exactly one live signature per retrieval function. CREATE OR REPLACE cannot
# change a signature, so a parameter change leaves the old body callable by any
# caller passing the old argument count. Needs a DSN; set
# FUNCTION_CENSUS_REQUIRE_DB=1 in CI so a missing DSN is a loud failure.
validate-functions:
	DATABASE_URL="$(DATABASE_URL)" $(PYTHON) scripts/function_census.py

# Lab 1: lexical precision and typo tolerance, against the mosaic_search tree
# the API reads. Read-only; safe to re-run.
lab-01:
	psql "$(DATABASE_URL)" -v ON_ERROR_STOP=1 -f $(SCHEMA_PACKAGE)/sql/lab_01_typo_tolerance.sql

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
	psql "$(DATABASE_URL)" -v ON_ERROR_STOP=1 \
		-v brands_path="$(MOSAIC_NORMALIZED_DIR)/brands.csv.gz" \
		-v categories_path="$(MOSAIC_NORMALIZED_DIR)/categories.csv.gz" \
		-v products_path="$(MOSAIC_NORMALIZED_DIR)/products.csv.gz" \
		-v offers_path="$(MOSAIC_NORMALIZED_DIR)/offers.csv.gz" \
		-f $(SCHEMA_PACKAGE)/sql/17_load_normalized_catalog.sql

# Run after embeddings are populated.
db-index-concurrent:
	psql "$(DATABASE_URL)" -v ON_ERROR_STOP=1 -f $(SCHEMA_PACKAGE)/sql/08_indexes_concurrent.sql

db-load-cohort:
	psql "$(DATABASE_URL)" -v ON_ERROR_STOP=1 \
		-v premium_cohort_path="$(MOSAIC_PREMIUM_COHORT_CSV)" \
		-f $(SCHEMA_PACKAGE)/sql/15_load_premium_cohort.sql

db-smoke:
	psql "$(DATABASE_URL)" -v ON_ERROR_STOP=1 -f $(SCHEMA_PACKAGE)/sql/99_smoke_test.sql

db-fetch-embeddings:
	@test -n "$(EMBEDDING_CACHE_URI)" || { \
		echo "EMBEDDING_CACHE_URI must be an s3:// prefix"; exit 2; \
	}
	aws s3 sync "$(EMBEDDING_CACHE_URI)" "$(EMBEDDING_CACHE_DIR)" \
		--only-show-errors

db-bootstrap-cached:
	@test -f "$(EMBEDDING_CACHE_MANIFEST)" || { \
		echo "Embedding cache manifest not found: $(EMBEDDING_CACHE_MANIFEST)"; \
		exit 2; \
	}
	$(MAKE) db-install DATABASE_URL="$(DATABASE_URL)"
	$(MAKE) db-prepare-mosaic
	$(MAKE) db-load-mosaic DATABASE_URL="$(DATABASE_URL)"
	$(MAKE) db-import-embeddings DATABASE_URL="$(DATABASE_URL)"
	$(MAKE) db-index-concurrent DATABASE_URL="$(DATABASE_URL)"
	$(MAKE) db-load-cohort DATABASE_URL="$(DATABASE_URL)"
	$(MAKE) db-smoke DATABASE_URL="$(DATABASE_URL)"

validate-db:
	"$(PYTHON)" "$(SCHEMA_PACKAGE)/scripts/validate_package.py"

quality:
	$(PYTHON) scripts/catalog_quality.py

reviews:
	$(PYTHON) scripts/generate_reviews.py

validate:
	$(PYTHON) scripts/validate_package.py

test:
	$(PYTHON) -m pytest

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
	DATABASE_URL="$(DATABASE_URL)" $(PYTHON) scripts/embed_catalog.py

db-export-embeddings:
	DATABASE_URL="$(DATABASE_URL)" $(PYTHON) scripts/embedding_cache.py \
		export --output "$(EMBEDDING_CACHE_DIR)"

db-import-embeddings:
	DATABASE_URL="$(DATABASE_URL)" $(PYTHON) scripts/embedding_cache.py \
		import "$(EMBEDDING_CACHE_MANIFEST)"

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
	"$(PYTHON)" -m venv "$(MCP_VENV)"
	"$(MCP_PYTHON)" -m pip install --upgrade pip
	"$(MCP_PYTHON)" -m pip install -e "./mcp-server[dev]"
	"$(MCP_PYTHON)" -m pip check

mcp-test: check-mcp-python
	"$(MCP_PYTHON)" -m pytest -c mcp-server/pyproject.toml mcp-server/mcp_tests

mcp-serve: check-mcp-python
	"$(MCP_VENV)/bin/mosaic-retrieval-mcp"
