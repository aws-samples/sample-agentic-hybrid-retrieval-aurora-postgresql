from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))
from app.config import get_settings
from app.db import get_dict_conn
from app.embeddings import embed_texts, to_pgvector


def _source_predicate(source_name: str | None, source_system: str | None) -> tuple[str, dict]:
    clauses = []
    params = {}
    if source_name:
        clauses.append("s.source_name = %(source_name)s")
        params["source_name"] = source_name
    if source_system:
        clauses.append("s.source_system = %(source_system)s")
        params["source_system"] = source_system
    return (" AND " + " AND ".join(clauses)) if clauses else "", params


def _mark_completed_sources(source_name: str | None, source_system: str | None) -> None:
    predicate, params = _source_predicate(source_name, source_system)
    with get_dict_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT s.source_id
                FROM ops.source_connectors s
                WHERE s.status = 'indexing'
                  {predicate}
                  AND NOT EXISTS (
                    SELECT 1
                    FROM ops.source_objects o
                    JOIN ops.object_chunks c ON c.object_id = o.object_id
                    WHERE o.source_id = s.source_id
                      AND o.is_active
                      AND c.embedding IS NULL
                  )
            """, params)
            source_ids = [row["source_id"] for row in cur.fetchall()]
            if not source_ids:
                return
            cur.execute("""
                UPDATE ops.source_connectors
                SET status = 'ready'
                WHERE source_id = ANY(%s)
            """, (source_ids,))
            cur.execute("""
                UPDATE ops.ingest_jobs
                SET status = 'ready',
                    finished_at = now(),
                    embedding_count = coalesce((metadata->>'embeddings_pending')::int, 0)
                WHERE source_id = ANY(%s)
                  AND status = 'indexing'
                RETURNING job_id, embedding_count
            """, (source_ids,))
            for row in cur.fetchall():
                cur.execute("""
                    INSERT INTO ops.ingest_job_events(job_id, step_name, status, message, metadata)
                    VALUES (%s, 'embed_chunks', 'complete',
                            'All pending chunks for this connector are embedded',
                            %s::jsonb)
                """, (
                    row["job_id"],
                    json.dumps({"embedded": row["embedding_count"]}),
                ))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["hash", "bedrock"], default=None)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument(
        "--model-batch-size",
        type=int,
        default=16,
        help="documents per Cohere Embed invocation; ignored by the hash provider",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--source-name")
    parser.add_argument("--source-system")
    args = parser.parse_args()
    settings = get_settings()
    provider = args.provider or settings.embed_provider
    total = 0
    predicate, source_params = _source_predicate(args.source_name, args.source_system)
    with get_dict_conn() as conn:
        with conn.cursor() as cur:
            while True:
                cur.execute(f"""
                    SELECT c.chunk_id, coalesce(c.section_title,'') || E'\n' || c.chunk_text AS text
                    FROM ops.object_chunks c
                    JOIN ops.source_objects o ON o.object_id = c.object_id
                    LEFT JOIN ops.source_connectors s ON s.source_id = o.source_id
                    WHERE c.embedding IS NULL
                      AND o.is_active
                      {predicate}
                    ORDER BY c.chunk_id
                    LIMIT %(batch_size)s
                """, {**source_params, "batch_size": args.batch_size})
                rows = cur.fetchall()
                if not rows:
                    break
                for start in range(0, len(rows), args.model_batch_size):
                    batch = rows[start:start + args.model_batch_size]
                    if args.limit:
                        batch = batch[:max(0, args.limit - total)]
                    if not batch:
                        print(f"Embedded {total} chunks")
                        return
                    vectors = embed_texts(
                        [row["text"] for row in batch],
                        provider=provider,
                        dim=settings.embed_dim,
                    )
                    for row, embedding in zip(batch, vectors, strict=True):
                        cur.execute(
                            "UPDATE ops.object_chunks SET embedding = %s::vector WHERE chunk_id = %s",
                            (to_pgvector(embedding), row["chunk_id"]),
                        )
                        total += 1
                    if args.limit and total >= args.limit:
                        print(f"Embedded {total} chunks")
                        return
                print(f"Embedded {total} chunks")
    _mark_completed_sources(args.source_name, args.source_system)
    print(f"Done: embedded {total} chunks")

if __name__ == "__main__":
    main()
