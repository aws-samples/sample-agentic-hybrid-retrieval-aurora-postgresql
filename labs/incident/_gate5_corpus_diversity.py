#!/usr/bin/env python3
"""Gate 5: check near-duplicate rate across a realistic sample corpus before
freezing the 180-250 document count target. Throwaway prototype."""
from __future__ import annotations

import json
import sys
from itertools import combinations
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import psycopg

from backend.app.config import get_settings


def main() -> int:
    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        name = conn.execute("SELECT current_database()").fetchone()[0]
        if not name.endswith("_test"):
            raise RuntimeError(f"SAFETY ABORT: {name}")
        print(f"safety check passed: {name}")

        documents = json.loads(Path("/tmp/gate5_sample_documents.json").read_text())
        print(f"documents loaded: {len(documents)}")

        conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

        # One round trip: load documents into a temp table, self-join with
        # similarity() computed server-side, instead of one query per pair
        # (148 docs = 10,878 pairs -- far too many individual round trips).
        conn.execute("DROP TABLE IF EXISTS gate5_docs")
        conn.execute("CREATE TEMP TABLE gate5_docs (key text PRIMARY KEY, body text)")
        with conn.cursor().copy("COPY gate5_docs (key, body) FROM STDIN") as copy:
            for key, body in documents:
                copy.write_row((key, body))

        rows = conn.execute(
            """
            SELECT a.key, b.key, similarity(a.body, b.body) AS sim
            FROM gate5_docs a
            JOIN gate5_docs b ON a.key < b.key
            WHERE similarity(a.body, b.body) > 0.6
            ORDER BY sim DESC
            """
        ).fetchall()
        near_dupes = [(row[0], row[1], row[2]) for row in rows]
        total_pairs = len(list(combinations(documents, 2)))

    print(f"total pairs checked: {total_pairs}")
    print(f"near-duplicate pairs (trigram similarity > 0.6): {len(near_dupes)}")
    for key_a, key_b, sim in sorted(near_dupes, key=lambda x: -x[2])[:20]:
        print(f"  {key_a} <-> {key_b}: {sim:.3f}")

    # Also check per-category rate, since a category-specific problem is more
    # actionable than one aggregate number.
    from collections import defaultdict
    dupes_by_prefix: dict[str, int] = defaultdict(int)
    pairs_by_prefix: dict[str, int] = defaultdict(int)
    for (key_a, _), (key_b, _) in combinations(documents, 2):
        prefix_a = key_a.rsplit("-", 1)[0]
        prefix_b = key_b.rsplit("-", 1)[0]
        if prefix_a == prefix_b:
            pairs_by_prefix[prefix_a] += 1
    for key_a, key_b, _ in near_dupes:
        prefix_a = key_a.rsplit("-", 1)[0]
        prefix_b = key_b.rsplit("-", 1)[0]
        if prefix_a == prefix_b:
            dupes_by_prefix[prefix_a] += 1

    print()
    print("per-category near-dupe rate (within-category pairs only):")
    for prefix in sorted(pairs_by_prefix):
        rate = dupes_by_prefix[prefix] / pairs_by_prefix[prefix]
        print(f"  {prefix}: {dupes_by_prefix[prefix]}/{pairs_by_prefix[prefix]} ({rate:.1%})")

    dupe_rate = len(near_dupes) / max(1, total_pairs)
    gate_passed = dupe_rate < 0.15
    print()
    print(f"overall near-dupe rate: {dupe_rate:.2%}")
    print(f"GATE 5 {'PASSED' if gate_passed else 'FAILED'} (threshold: <15%)")
    return 0 if gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
