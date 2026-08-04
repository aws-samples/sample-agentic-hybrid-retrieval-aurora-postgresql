#!/usr/bin/env python3
"""Gate 3: confirm existing current documents are not incorrectly demoted when
the search index is rebuilt again over the SAME evidence. Runs the real
rebuild_search_index code path against real, already-admitted evidence --
not a synthetic row insert. Throwaway prototype, real _test DB only.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import psycopg

from backend.app import db as app_db
from backend.app.config import get_settings
from backend.app.search_index import rebuild_search_index


def main() -> int:
    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        name = conn.execute("SELECT current_database()").fetchone()[0]
        if not name.endswith("_test"):
            raise RuntimeError(f"SAFETY ABORT: {name}")
        print(f"safety check passed: {name}")

    with app_db.get_owner_conn() as conn:
        before = conn.execute(
            "SELECT evidence_id, document_version_id, search_document_hash "
            "FROM retrieval.documents WHERE is_current = true ORDER BY evidence_id"
        ).fetchall()
        if not before:
            print("SKIP: no current documents -- admit a live run first")
            return 2
        before_by_evidence = {row[0]: row for row in before}
        print(f"current documents before: {len(before_by_evidence)}")

    # Verify the source-code invariant directly, not just behaviorally: every
    # is_current demotion in search_index.py must be scoped by SOME identity key
    # (evidence_id, document_version_id, or a source_systems filter applied
    # uniformly across a full rebuild) -- manually inspected all 8 sites found
    # here on 2026-08-04: 2 use "previous.evidence_id" (join-scoped), 2 use a
    # bound %s evidence_id/document_version_id parameter, 2 use
    # "ON CONFLICT (document_version_id)" (inherently single-row), 2 use
    # "NOT EXISTS (...document_version_id...)" (chunk scoped to its own
    # document). None can touch an unrelated evidence item's row. This check
    # only asserts the COUNT stays stable at 8 -- if a future edit adds or
    # removes a demotion site, this forces a human to re-verify scoping by
    # hand rather than silently trusting a stale count.
    search_index_source = (REPO_ROOT / "backend/app/search_index.py").read_text()
    demotion_blocks = [
        block for block in search_index_source.split("cursor.execute(")
        if "SET is_current = false" in block
    ]
    known_good_count = 8
    count_stable = len(demotion_blocks) == known_good_count
    print(f"is_current demotion queries found: {len(demotion_blocks)} "
          f"(expected {known_good_count}, manually verified scoped on 2026-08-04)")

    # Actually run the real rebuild path -- no content changed, so every
    # document's hash should be identical and nothing should need a new version,
    # but this exercises the real demotion/promotion SQL, not just a static read.
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "gate3-cache.jsonl"
        with app_db.get_owner_conn() as conn:
            result = rebuild_search_index(
                conn,
                model_id="us.cohere.embed-v4:0",
                cache_path=cache_path,
                embed_missing=True,
                batch_size=48,
            )
    print(f"rebuild completed, raw result keys: {sorted(result.keys())}")

    with app_db.get_owner_conn() as conn:
        after = conn.execute(
            "SELECT evidence_id, document_version_id, search_document_hash "
            "FROM retrieval.documents WHERE is_current = true ORDER BY evidence_id"
        ).fetchall()
        after_by_evidence = {row[0]: row for row in after}
        print(f"current documents after: {len(after_by_evidence)}")

    same_evidence_ids = set(before_by_evidence) == set(after_by_evidence)
    same_hashes = all(
        before_by_evidence[eid][2] == after_by_evidence[eid][2]
        for eid in before_by_evidence
        if eid in after_by_evidence
    )
    no_evidence_lost = set(before_by_evidence) <= set(after_by_evidence)

    gate_passed = (
        count_stable
        and no_evidence_lost
        and same_evidence_ids
        and same_hashes
    )

    print()
    print(f"same set of current evidence_ids: {same_evidence_ids}")
    print(f"content hashes unchanged (no unnecessary version bump): {same_hashes}")
    print(f"no existing evidence lost is_current status: {no_evidence_lost}")
    print(f"GATE 3 {'PASSED' if gate_passed else 'FAILED'}")
    app_db.close_pool()
    return 0 if gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
