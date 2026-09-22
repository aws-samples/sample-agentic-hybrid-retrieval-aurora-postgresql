#!/usr/bin/env python3
"""Install participant SQL edits in the catalog selected by the Mosaic API."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lab_state import assert_reset_database
from scripts.prepare_live_catalog import live_search_functions
from service.catalog_runtime import active_dataset, search_schema


def apply(connection, source: str) -> None:
    """Preserve the marked lab state while targeting the verified active dataset."""
    dataset = active_dataset()
    if dataset:
        row = connection.execute(
            "SELECT dataset_id FROM mosaic_live_search.receipt WHERE singleton"
        ).fetchone()
        if row is None or row[0] != dataset:
            raise ValueError(
                f"Lab catalog rule: prepared dataset {row!r} differs from {dataset!r}; "
                "fix: select the prepared dataset used by the API before applying SQL."
            )
        statement = live_search_functions(source, repair_labs=False)
    else:
        statement = "\n".join(
            line for line in source.splitlines() if not line.startswith("\\")
        )
    connection.execute("SET LOCAL statement_timeout='60s'")
    connection.execute(statement, prepare=False)


def main() -> None:
    import psycopg

    dsn = os.getenv("DATABASE_URL")
    assert_reset_database(dsn)
    with psycopg.connect(dsn, connect_timeout=15) as connection:
        apply(connection, (ROOT / "db/sql/09_search_functions.sql").read_text())
    print(f"Applied participant SQL to {search_schema()}; source lab state preserved.")


if __name__ == "__main__":
    main()
