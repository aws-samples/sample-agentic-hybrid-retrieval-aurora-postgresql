#!/usr/bin/env python3
"""Move a cluster prepared with the earlier search schemas onto the one search schema.

Until then the listings table lived in `mosaic_catalog_search`, the view and the
functions Aurora ran in `mosaic_live_search`, and `mosaic_search`, the schema the
lab files name, held an empty table and copies of the functions that nothing
ran. Afterwards everything search reads or runs is in `mosaic_search`: the
`product_listing` table and its indexes, `product_listing_view`, and the
functions exactly as the files define them.

Every step renames or moves catalog metadata, in one transaction: no listing is
rewritten and no index is rebuilt. The functions are re-applied from the saved
lab files, so a lab's current state, broken or repaired, carries over.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from service.catalog_runtime import (
    LISTING_TABLE,
    LISTING_VIEW,
    LIVE_INDEXES,
    SEARCH_SCHEMA,
)
from service.search_sql import search_sql, without_psql_lines

OLD_TABLE_SCHEMA = "mosaic_catalog_search"
OLD_VIEW_SCHEMA = "mosaic_live_search"
OLD_TABLE = "product_document"
#: Tables that move from the old view schema unchanged.
MOVED_TABLES = ("source_price", "corpus_lexeme", "corpus_surface_lexeme", "receipt")
#: The index names used until 13 October 2026, when `real_` marked the real
#: catalog built beside a synthetic one since retired.
LEGACY_INDEX_NAMES = {
    "real_search_" + name.removeprefix("product_search_"): name
    for name in LIVE_INDEXES.values()
}


def _exists(connection, relation: str) -> bool:
    return connection.execute(
        "SELECT to_regclass(%s) IS NOT NULL", (relation,)
    ).fetchone()[0]


def _identifier(connection, name: str) -> str:
    return connection.execute("SELECT quote_ident(%s)", (name,)).fetchone()[0]


def rename_legacy_indexes(connection) -> list[str]:
    """Rename `real_search_*` indexes on the listings table to `product_search_*`."""
    renamed = []
    for legacy, current in LEGACY_INDEX_NAMES.items():
        if _exists(connection, f"{SEARCH_SCHEMA}.{legacy}") and not _exists(
            connection, f"{SEARCH_SCHEMA}.{current}"
        ):
            connection.execute(
                f"ALTER INDEX {SEARCH_SCHEMA}.{legacy} RENAME TO {current}"
            )
            renamed.append(f"index {legacy} -> {current}")
    return renamed


def _rename_constraints(connection, relation: str, old: str, new: str) -> list[str]:
    """Rename a table's `old_*` constraints, and the indexes behind them, to `new_*`.

    Done before the table changes schema, so a moved `receipt_pkey` cannot collide
    with the one already in the target schema.
    """
    rows = connection.execute(
        """SELECT conname FROM pg_constraint
        WHERE conrelid = %s::regclass AND conname LIKE %s ORDER BY conname""",
        (relation, f"{old}\\_%"),
    ).fetchall()
    renamed = []
    for (name,) in rows:
        renamed_to = new + name.removeprefix(old)
        connection.execute(
            f"ALTER TABLE {relation} "
            f"RENAME CONSTRAINT {_identifier(connection, name)} "
            f"TO {_identifier(connection, renamed_to)}"
        )
        renamed.append(f"constraint {name} -> {renamed_to}")
    return renamed


def _grantees(connection) -> list[str]:
    """Roles other than the owner that could read the old schemas."""
    rows = connection.execute(
        """SELECT DISTINCT a.grantee::regrole::text
        FROM pg_namespace n, aclexplode(n.nspacl) a
        WHERE n.nspname IN (%s, %s) AND a.grantee <> 0 AND a.grantee <> n.nspowner
        ORDER BY 1""",
        (OLD_TABLE_SCHEMA, OLD_VIEW_SCHEMA),
    ).fetchall()
    return [row[0] for row in rows]


def _drop_routines(connection, schemas: tuple[str, ...]) -> list[str]:
    rows = connection.execute(
        """SELECT p.oid::regprocedure::text FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = ANY(%s) ORDER BY 1""",
        (list(schemas),),
    ).fetchall()
    for (signature,) in rows:
        connection.execute(f"DROP ROUTINE {signature}")
    return [f"dropped {len(rows)} routines in {', '.join(schemas)}"]


def _drop_unused_search_tables(connection) -> list[str]:
    """Drop the empty synthetic projection and vocabularies that the moved ones replace."""
    dropped = []
    if _exists(connection, f"{SEARCH_SCHEMA}.{OLD_TABLE}"):
        kind, rows = connection.execute(
            f"""SELECT c.relkind, (SELECT count(*) FROM {SEARCH_SCHEMA}.{OLD_TABLE})
            FROM pg_class c WHERE c.oid = %s::regclass""",
            (f"{SEARCH_SCHEMA}.{OLD_TABLE}",),
        ).fetchone()
        if kind != "r" or rows:
            raise ValueError(
                f"Search schema migration rule: {SEARCH_SCHEMA}.{OLD_TABLE} is "
                f"relkind {kind!r} with {rows} rows, not the empty synthetic table; "
                "fix: inspect it before migrating, nothing was changed."
            )
        connection.execute(f"DROP TABLE {SEARCH_SCHEMA}.{OLD_TABLE}")
        dropped.append(f"dropped empty {SEARCH_SCHEMA}.{OLD_TABLE}")
    for table in ("corpus_lexeme", "corpus_surface_lexeme"):
        if _exists(connection, f"{SEARCH_SCHEMA}.{table}"):
            connection.execute(f"DROP TABLE {SEARCH_SCHEMA}.{table}")
            dropped.append(
                f"dropped {SEARCH_SCHEMA}.{table}, replaced by the moved one"
            )
    return dropped


def _move_tables(connection) -> list[str]:
    moves = (
        (OLD_TABLE_SCHEMA, OLD_TABLE, LISTING_TABLE),
        (OLD_TABLE_SCHEMA, "receipt", "product_listing_receipt"),
        *((OLD_VIEW_SCHEMA, table, table) for table in MOVED_TABLES),
    )
    moved = []
    for schema, table, name in moves:
        if name != table:
            connection.execute(f"ALTER TABLE {schema}.{table} RENAME TO {name}")
            moved += _rename_constraints(connection, f"{schema}.{name}", table, name)
        connection.execute(f"ALTER TABLE {schema}.{name} SET SCHEMA {SEARCH_SCHEMA}")
        moved.append(f"{schema}.{table} -> {SEARCH_SCHEMA}.{name}")
    return moved


def _apply_search_sql(connection, root: Path) -> list[str]:
    from scripts.apply_search_functions import apply
    from service.lab_validation_receipt import participant_sql_digest

    projection = root / "db/sql/06_retrieval_projection.sql"
    connection.execute(without_psql_lines(projection.read_text(encoding="utf-8")))
    apply(connection, search_sql(root), participant_sql_digest(root))
    coverage = root / "db/sql/11_query_coverage.sql"
    connection.execute(without_psql_lines(coverage.read_text(encoding="utf-8")))
    return [
        f"created {SEARCH_SCHEMA}.{LISTING_VIEW}",
        "applied the search SQL with the saved Lab 1 and Lab 2 files",
    ]


def _grant(connection, roles: list[str]) -> list[str]:
    for role in roles:
        quoted = _identifier(connection, role)
        connection.execute(f"GRANT USAGE ON SCHEMA {SEARCH_SCHEMA} TO {quoted}")
        connection.execute(
            f"GRANT SELECT ON ALL TABLES IN SCHEMA {SEARCH_SCHEMA} TO {quoted}"
        )
        connection.execute(
            f"GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA {SEARCH_SCHEMA} TO {quoted}"
        )
    return [f"granted read and execute on {SEARCH_SCHEMA} to {role}" for role in roles]


def _refresh_receipts(connection, root: Path) -> list[str]:
    from scripts.catalog.prepare_live_catalog import preparation_sha256
    from scripts.catalog.prepare_staged_catalog_search import (
        projection_sha256,
        reference_functions_sha256,
    )

    connection.execute(
        f"""UPDATE {SEARCH_SCHEMA}.product_listing_receipt
        SET projection_sha256 = %s, functions_sha256 = %s WHERE singleton""",
        (projection_sha256(), reference_functions_sha256(root)),
    )
    connection.execute(
        f"UPDATE {SEARCH_SCHEMA}.receipt SET preparation_sha256 = %s WHERE singleton",
        (preparation_sha256(root),),
    )
    return ["recorded the projection and preparation SQL under their new names"]


def migrate(connection, root: Path = ROOT) -> list[str]:
    """Move an old cluster onto the one search schema, or report that it already is.

    Args:
        connection: An Aurora connection whose transaction the caller commits.
        root: The checkout whose lab files and SQL are applied.

    Returns:
        One line per change, empty when the cluster needed none.
    """
    connection.execute("SET LOCAL lock_timeout = '10s'")
    if not _exists(connection, f"{OLD_TABLE_SCHEMA}.{OLD_TABLE}"):
        return rename_legacy_indexes(connection)
    roles = _grantees(connection)
    steps = _drop_routines(
        connection, (SEARCH_SCHEMA, OLD_VIEW_SCHEMA, OLD_TABLE_SCHEMA)
    )
    connection.execute(f"DROP VIEW {OLD_VIEW_SCHEMA}.{OLD_TABLE}")
    steps += _drop_unused_search_tables(connection)
    steps += _move_tables(connection)
    steps += rename_legacy_indexes(connection)
    connection.execute(f"DROP SCHEMA {OLD_VIEW_SCHEMA}")
    connection.execute(f"DROP SCHEMA {OLD_TABLE_SCHEMA}")
    steps.append(f"dropped the empty schemas {OLD_VIEW_SCHEMA} and {OLD_TABLE_SCHEMA}")
    steps += _apply_search_sql(connection, root)
    steps += _grant(connection, roles)
    steps += _refresh_receipts(connection, root)
    return steps


def require_migrated(connection) -> None:
    """Refuse to prepare or rebuild on a cluster still using the old schemas."""
    if _exists(connection, f"{OLD_TABLE_SCHEMA}.{OLD_TABLE}"):
        raise ValueError(
            f"Search schema rule: the listings are still in "
            f"{OLD_TABLE_SCHEMA}.{OLD_TABLE}; fix: run "
            "uv run python scripts/catalog/migrate_search_schema.py first."
        )


def main() -> None:
    import psycopg
    from dotenv import load_dotenv

    argparse.ArgumentParser(description=__doc__).parse_args()
    load_dotenv(ROOT / ".env", override=False)
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        raise SystemExit("Search schema migration needs DATABASE_URL; load .env first.")
    with psycopg.connect(dsn, connect_timeout=15) as connection:
        steps = migrate(connection)
        connection.commit()
    print(json.dumps({"migrated": bool(steps), "steps": steps}, indent=2))


if __name__ == "__main__":
    main()
