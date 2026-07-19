from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))
from app.ingest import create_job, upsert_objects
from app.models import SourceObject
from app.db import get_conn


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--source-name", default="workshop-source-bundle")
    parser.add_argument("--source-system", default="source_bundle")
    parser.add_argument("--truncate", action="store_true")
    args = parser.parse_args()

    # Parse the whole input BEFORE any TRUNCATE. --truncate wipes the corpus, so a
    # missing file or malformed line must abort while the existing data is intact;
    # otherwise `make load` with no data/generated bundle would empty the database
    # and then fail, leaving nothing to fall back to.
    input_path = Path(args.input)
    if not input_path.is_file():
        raise SystemExit(
            f"Input file not found: {input_path}. Run `make sample` to generate "
            "data/generated/source_objects.jsonl before `make load`."
        )
    objects = []
    with input_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                objects.append(SourceObject(**json.loads(line)))
    if not objects:
        raise SystemExit(f"Input file is empty: {input_path}. Nothing to load; skipping TRUNCATE.")

    if args.truncate:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE ops.retrieval_candidates, ops.retrieval_runs, ops.citations, ops.object_links, ops.object_chunks, ops.source_objects, ops.ingest_job_events, ops.ingest_jobs, ops.source_connectors RESTART IDENTITY CASCADE;")

    source_id, job_id = create_job(args.source_system, args.source_name, len(objects))
    result = upsert_objects(source_id, job_id, objects)
    print(json.dumps(result, indent=2, default=str))

if __name__ == "__main__":
    main()
