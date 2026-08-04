#!/usr/bin/env python3
"""Gate 2: prove a retrieval run's replayed candidates are unaffected by a later
admission touching the same evidence. Throwaway prototype against a real _test DB.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import psycopg

from backend.app import db as app_db
from backend.app.agent import explain_ranking_impl, search_evidence_impl
from backend.app.config import get_settings


def safety_check() -> str:
    settings = get_settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        name = conn.execute("SELECT current_database()").fetchone()[0]
        if not name.endswith("_test"):
            raise RuntimeError(f"SAFETY ABORT: {name}")
        return name


def main() -> int:
    name = safety_check()
    print(f"safety check passed: {name}")

    with app_db.get_owner_conn() as conn:
        count = conn.execute("SELECT count(*) FROM casework.evidence_items").fetchone()[0]
        if count == 0:
            print("SKIP: no evidence admitted yet -- run the live orchestrator against "
                  "this test database first, then re-run this gate")
            return 2
        print(f"evidence_items present: {count}")

    role = "app_engineer"
    search_result = search_evidence_impl(query="INC-", limit=5, role=role)
    run_id = search_result["run_id"]
    print(f"run_id: {run_id}")

    before = explain_ranking_impl(run_id, role=role)
    before_candidates = json.dumps(before["candidates"], sort_keys=True, default=str)
    print(f"candidates before: {len(before['candidates'])}")

    with app_db.get_owner_conn() as conn:
        conn.execute(
            "UPDATE casework.evidence_items SET source_revision = source_revision "
            "WHERE evidence_id = (SELECT evidence_id FROM casework.evidence_items LIMIT 1)"
        )
    print("performed a later write against casework.evidence_items")

    after = explain_ranking_impl(run_id, role=role)
    after_candidates = json.dumps(after["candidates"], sort_keys=True, default=str)
    print(f"candidates after: {len(after['candidates'])}")

    identical = before_candidates == after_candidates
    print()
    print(f"GATE 2 {'PASSED' if identical else 'FAILED'}: replayed candidates "
          f"{'unchanged' if identical else 'CHANGED'} after a later write")
    app_db.close_pool()
    return 0 if identical else 1


if __name__ == "__main__":
    raise SystemExit(main())
