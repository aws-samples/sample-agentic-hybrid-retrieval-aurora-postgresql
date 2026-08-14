#!/usr/bin/env python3
"""Apply or verify database-level retrieval settings on Aurora PostgreSQL.

pg_trgm registers its GUCs when its shared library first loads in a backend.
Aurora rejects a function-local ``SET pg_trgm.*`` clause in a fresh session
before that registration occurs. Mosaic therefore loads pg_trgm explicitly,
stores both index-gate thresholds as database defaults, and keeps the search
function free of hidden session state.

The values come only from ``db/config/retrieval.yaml``. This command must run
after ``CREATE EXTENSION pg_trgm`` and is idempotent.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.retrieval_profile import load_profile


class DatabaseConfigurationError(RuntimeError):
    """Aurora cannot satisfy the deterministic retrieval-setting contract."""


SETTING_FIELDS = (
    ("pg_trgm.similarity_threshold", "trigram_similarity_gate"),
    ("pg_trgm.word_similarity_threshold", "trigram_word_similarity_gate"),
)

TRIGRAM_IDENTITY_ARGUMENTS = (
    "q text, f jsonb, candidate_limit integer, minimum_similarity real"
)


def _expected_settings() -> dict[str, float]:
    profile = load_profile()
    return {
        setting: float(getattr(profile, field)) for setting, field in SETTING_FIELDS
    }


def _load_pg_trgm(connection) -> None:
    extension = connection.execute(
        "SELECT extversion FROM pg_extension WHERE extname = 'pg_trgm'"
    ).fetchone()
    if extension is None:
        raise DatabaseConfigurationError(
            "D1 pg_trgm extension is absent; found no pg_extension row; "
            "fix: run make db-install before db-configure-retrieval"
        )
    connection.execute("SELECT similarity('mosaic', 'mosaic')").fetchone()


def _stored_database_settings(connection) -> dict[str, str]:
    row = connection.execute(
        """
        SELECT s.setconfig
        FROM pg_db_role_setting s
        JOIN pg_database d ON d.oid = s.setdatabase
        WHERE d.datname = current_database()
          AND s.setrole = 0
        """
    ).fetchone()
    values: dict[str, str] = {}
    for item in (row[0] if row else []) or []:
        key, separator, value = item.partition("=")
        if separator:
            values[key] = value
    return values


def configure(dsn: str) -> None:
    """Persist the YAML-sourced pg_trgm gates on the target Aurora database."""
    import psycopg
    from psycopg import sql

    expected = _expected_settings()
    with psycopg.connect(dsn, autocommit=True, connect_timeout=20) as connection:
        _load_pg_trgm(connection)
        database, user, owner = connection.execute(
            """
            SELECT current_database(), current_user, pg_get_userbyid(d.datdba)
            FROM pg_database d
            WHERE d.datname = current_database()
            """
        ).fetchone()
        if user != owner:
            raise DatabaseConfigurationError(
                f"D2 database owner mismatch; found user={user!r}, owner={owner!r}; "
                "fix: run db-configure-retrieval with the Aurora database owner"
            )
        for setting, value in expected.items():
            statement = sql.SQL("ALTER DATABASE {} SET {} TO {}").format(
                sql.Identifier(database),
                sql.SQL(setting),
                sql.Literal(format(value, ".15g")),
            )
            connection.execute(statement)

    verify(dsn)


def verify(dsn: str) -> None:
    """Prove stored defaults, new-session values, and function state agree."""
    import psycopg

    expected = _expected_settings()
    with psycopg.connect(dsn, connect_timeout=20) as connection:
        connection.read_only = True
        _load_pg_trgm(connection)
        stored = _stored_database_settings(connection)
        actual = {
            setting: float(
                connection.execute("SELECT current_setting(%s)", (setting,)).fetchone()[
                    0
                ]
            )
            for setting in expected
        }
        function_row = connection.execute(
            """
            SELECT p.proconfig
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'mosaic_search'
              AND p.proname = 'search_trigram'
              AND pg_get_function_identity_arguments(p.oid) = %s
            """,
            (TRIGRAM_IDENTITY_ARGUMENTS,),
        ).fetchone()

    failures: list[str] = []
    for setting, expected_value in expected.items():
        stored_value = stored.get(setting)
        if stored_value is None or not math.isclose(
            float(stored_value), expected_value, rel_tol=0, abs_tol=1e-9
        ):
            failures.append(
                f"stored {setting}={stored_value!r}, expected {expected_value:g}"
            )
        if not math.isclose(actual[setting], expected_value, rel_tol=0, abs_tol=1e-9):
            failures.append(
                f"new-session {setting}={actual[setting]:g}, "
                f"expected {expected_value:g}"
            )
    if function_row is None:
        failures.append(
            "mosaic_search.search_trigram(text,jsonb,integer,real) is absent"
        )
    elif function_row[0] is not None:
        failures.append(
            f"search_trigram proconfig={function_row[0]!r}, expected no "
            "function-local settings"
        )
    if failures:
        joined = "; ".join(failures)
        raise DatabaseConfigurationError(
            f"D3 deterministic pg_trgm contract failed; found {joined}; "
            "fix: run make db-apply-search-functions"
        )

    rendered = ", ".join(f"{setting}={value:g}" for setting, value in expected.items())
    print(f"Aurora retrieval settings verified: {rendered}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify without changing database settings",
    )
    args = parser.parse_args()
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print(
            "FAIL D0 DATABASE_URL is unset; found no Aurora target; "
            "fix: source .env or pass DATABASE_URL",
            file=sys.stderr,
        )
        return 2
    try:
        if args.check:
            verify(dsn)
        else:
            configure(dsn)
    except (DatabaseConfigurationError, OSError, ValueError) as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
