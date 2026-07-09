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

    if args.truncate:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE ops.retrieval_candidates, ops.retrieval_runs, ops.citations, ops.object_links, ops.object_chunks, ops.source_objects, ops.ingest_job_events, ops.ingest_jobs, ops.source_connectors RESTART IDENTITY CASCADE;")

    objects = []
    with Path(args.input).open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                objects.append(SourceObject(**json.loads(line)))

    source_id, job_id = create_job(args.source_system, args.source_name, len(objects))
    result = upsert_objects(source_id, job_id, objects)
    print(json.dumps(result, indent=2, default=str))

if __name__ == "__main__":
    main()
