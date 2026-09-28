#!/usr/bin/env python3
"""Install the search SQL, with the participant's Lab 1 and Lab 2 files, in Aurora."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lab_state import assert_reset_database
from scripts.prepare_live_catalog import live_search_functions
from service.catalog_runtime import active_dataset, search_schema
from service.lab_validation_receipt import participant_sql_digest
from service.search_sql import search_sql

#: The fused search function carries the record of which participant SQL Aurora
#: runs. Its applier already owns it, so the record needs no new privilege and
#: no new table, and it changes in the same transaction as the functions do.
FUSED_FUNCTION = (
    "search_hybrid_rrf(text,vector,jsonb,integer,integer,integer,integer,integer,real)"
)
APPLIED_SQL_LABEL = "Participant SQL sha256 "


def applied_sql_digest(connection) -> str | None:
    """The participant SQL digest Aurora recorded when it was last applied."""
    row = connection.execute(
        f"SELECT obj_description('{search_schema()}.{FUSED_FUNCTION}'::regprocedure,"
        " 'pg_proc') AS note"
    ).fetchone()
    note = (row["note"] if isinstance(row, dict) else row[0]) if row else None
    if not note or not note.startswith(APPLIED_SQL_LABEL):
        return None
    return note.removeprefix(APPLIED_SQL_LABEL)


def apply(connection, source: str, source_sha256: str | None = None) -> None:
    """Preserve the marked lab state while targeting the verified active dataset.

    Args:
        connection: An open connection whose transaction the caller commits.
        source: The participant SQL file's text.
        source_sha256: The file's digest, recorded on the fused function so a
            later check can tell whether Aurora runs the workspace's SQL.
    """
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
        statement = live_search_functions(source)
    else:
        statement = "\n".join(
            line for line in source.splitlines() if not line.startswith("\\")
        )
    connection.execute("SET LOCAL statement_timeout='60s'")
    connection.execute(statement, prepare=False)
    if source_sha256 is not None:
        from psycopg import sql

        connection.execute(
            sql.SQL("COMMENT ON FUNCTION {} IS {}").format(
                sql.SQL(f"{search_schema()}.{FUSED_FUNCTION}"),
                sql.Literal(APPLIED_SQL_LABEL + source_sha256),
            )
        )


def main() -> None:
    import psycopg

    dsn = os.getenv("DATABASE_URL")
    assert_reset_database(dsn)
    with psycopg.connect(dsn, connect_timeout=15) as connection:
        apply(
            connection,
            search_sql(ROOT),
            participant_sql_digest(ROOT),
        )
    print(f"Applied participant SQL to {search_schema()}; source lab state preserved.")
    # One participant command: the applied functions must also satisfy the
    # stored pg_trgm gates, which is what this re-proves.
    from scripts.configure_retrieval_database import configure

    configure(dsn)


if __name__ == "__main__":
    main()
