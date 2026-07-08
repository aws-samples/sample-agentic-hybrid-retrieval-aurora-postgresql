from __future__ import annotations
import argparse
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))
from app.config import get_settings
from app.db import get_conn
from app.embeddings import embed_text, to_pgvector


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["hash", "bedrock"], default=None)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    settings = get_settings()
    provider = args.provider or settings.embed_provider
    total = 0
    with get_conn() as conn:
        with conn.cursor() as cur:
            while True:
                cur.execute("""
                    SELECT chunk_id, coalesce(section_title,'') || E'\n' || chunk_text
                    FROM ops.object_chunks
                    WHERE embedding IS NULL
                    ORDER BY chunk_id
                    LIMIT %s
                """, (args.batch_size,))
                rows = cur.fetchall()
                if not rows:
                    break
                for chunk_id, text in rows:
                    emb = embed_text(text, provider=provider, dim=settings.embed_dim)
                    cur.execute("UPDATE ops.object_chunks SET embedding = %s::vector WHERE chunk_id = %s", (to_pgvector(emb), chunk_id))
                    total += 1
                    if args.limit and total >= args.limit:
                        print(f"Embedded {total} chunks")
                        return
                print(f"Embedded {total} chunks")
    print(f"Done: embedded {total} chunks")

if __name__ == "__main__":
    main()
