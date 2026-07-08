.PHONY: install schema sample load embed api frontend smoke clean

install:
	python -m venv .venv
	. .venv/bin/activate && pip install -r backend/requirements.txt

schema:
	python backend/scripts/run_sql.py --files sql/00_extensions.sql sql/01_schema.sql sql/02_indexes.sql sql/03_search_functions.sql sql/04_diagnostics.sql sql/05_evaluation.sql

sample:
	python backend/scripts/generate_synthetic_operational_data.py --objects 2000 --out data/generated --seed 42

load:
	python backend/scripts/load_jsonl_to_aurora.py --input data/generated/source_objects.jsonl --truncate

embed:
	python backend/scripts/embed_chunks.py --provider hash --batch-size 500

api:
	uvicorn backend.app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

smoke:
	python backend/scripts/smoke_test.py

clean:
	rm -rf data/generated frontend/dist .pytest_cache
