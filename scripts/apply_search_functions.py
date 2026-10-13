#!/usr/bin/env python3
"""Install the search SQL, with the participant's Lab 1 and Lab 2 files, in Aurora."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lab_state import (
    FACILITATOR_ADVICE,
    assert_reset_database,
    is_environment_fault,
)
from service.catalog_runtime import active_dataset, search_schema
from service.lab_files import LAB1_SQL, LAB2_SQL
from service.lab_validation_receipt import participant_sql_digest
from service.participant_commands import APPLY_SQL, DIFF
from service.search_sql import (
    APPLIED_SQL_LABEL,
    FUSED_FUNCTION,
    SEARCH_SQL_FILES,
    search_sql,
    without_psql_lines,
)

#: A Lab 1 branch carries both a whole-number position and a real raw score; passing
#: the score as the position reaches Aurora as an undefined function, not a type error.
CONTRIBUTION_CALL = re.compile(r"reciprocal_rank_contribution\(\s*([a-z ]+?)\s*,")
POSITION_TYPES = frozenset({"bigint", "integer", "smallint"})


def explain_rejected_names(message: str) -> list[str]:
    """Translate the names in Aurora's error back to the participant's files.

    Args:
        message: Aurora's primary error message.

    Returns:
        Zero or more lines naming the rule broken and the nearest fix.
    """
    notes = []
    call = CONTRIBUTION_CALL.search(message)
    if call and call.group(1) not in POSITION_TYPES:
        notes.append(
            "Rule: reciprocal_rank_contribution takes a channel's position (bigint), "
            f"got {call.group(1)}. Pass the position column, such as trigram_rank, "
            "not the raw score, such as trigram_score."
        )
    return notes


def rendered_sql(source: str) -> str:
    """The statement apply sends to Aurora: the files as written, without psql lines."""
    return without_psql_lines(source)


def locate_error(
    statement: str, position: int, root: Path = ROOT
) -> tuple[Path, int, str] | None:
    """Find the file line Aurora's error position falls on, in the files apply read.

    Aurora counts characters into the statement apply sent. Apply drops psql
    lines but keeps every other line, so the line is found by its text, and a
    repeated line by its order.

    Returns:
        The file, its 1-based line number and the line, or None when unmatched.
    """
    if not 1 <= position <= len(statement):
        return None
    lines = statement.splitlines()
    index = statement[: position - 1].count("\n")
    if index >= len(lines) or not lines[index].strip():
        return None
    wanted = lines[index].strip()
    occurrence = sum(1 for line in lines[:index] if line.strip() == wanted)
    for path in SEARCH_SQL_FILES:
        text = (root / path).read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(text, start=1):
            if line.strip() == wanted:
                if occurrence == 0:
                    return path, number, line.strip()
                occurrence -= 1
    return None


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
            f"SELECT dataset_id FROM {search_schema()}.receipt WHERE singleton"
        ).fetchone()
        if row is None or row[0] != dataset:
            raise ValueError(
                f"Lab catalog rule: prepared dataset {row!r} differs from {dataset!r}; "
                "fix: select the prepared dataset used by the API before applying SQL."
            )
    statement = rendered_sql(source)
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


def describe_apply_failure(
    error, *, rolled_back: bool, statement: str | None = None, root: Path = ROOT
) -> str:
    """Say what Aurora rejected, where, and what state it was left in.

    Args:
        error: The `psycopg.Error` raised while applying or configuring.
        rolled_back: True when the apply transaction rolled back, so Aurora
            still runs its previous functions.
        statement: The statement apply sent, so Aurora's error position can be
            named as a line of the participant's own file.
        root: The checkout whose files the statement was built from.

    Returns:
        A multi-line message for the participant's terminal, with no traceback.
    """
    diagnostics = error.diag
    sqlstate = error.sqlstate or diagnostics.sqlstate or "none"
    message = (diagnostics.message_primary or str(error)).strip()
    lines = [f"Apply failed: SQLSTATE {sqlstate}: {message}"]
    lines.extend(explain_rejected_names(message))
    where = (
        locate_error(statement, int(diagnostics.statement_position), root)
        if statement and diagnostics.statement_position
        else None
    )
    if where:
        lines.append(f"Where: {where[0]} line {where[1]}: {where[2]}")
    if diagnostics.message_hint:
        lines.append(f"Hint from Aurora: {diagnostics.message_hint}")
    if rolled_back:
        lines.append(
            "Nothing was applied: the transaction rolled back, so Aurora still runs "
            "its previous functions."
        )
        if is_environment_fault(error):
            lines.append(FACILITATOR_ADVICE)
        else:
            lines.append(_apply_fix(where))
    return "\n".join(lines)


def _apply_fix(where: tuple[Path, int, str] | None) -> str:
    # Commands go on their own lines so a terminal never wraps them mid-word.
    indent = "      "
    if where and where[0] in (LAB1_SQL, LAB2_SQL):
        return "\n".join(
            [
                f"Fix: correct that line in {where[0]} and save it. Then run:",
                f"{indent}{APPLY_SQL}",
                "To see which lines of your file differ from the reference answer:",
                f"{indent}{DIFF}",
            ]
        )
    if where:
        return "\n".join(
            [
                (
                    f"Fix: {where[0]} is outside the marked blocks. If you changed it, "
                    "undo the change (git diff shows it) and run:"
                ),
                f"{indent}{APPLY_SQL}",
                "Otherwise give this message to your facilitator.",
            ]
        )
    return "\n".join(
        [
            (
                f"Fix: check the marked LAB1_EDIT and LAB2_EDIT blocks in {LAB1_SQL} "
                f"and {LAB2_SQL}. Then run:"
            ),
            f"{indent}{APPLY_SQL}",
        ]
    )


def main() -> None:
    import psycopg

    from scripts.configure_retrieval_database import (
        DatabaseConfigurationError,
        configure,
    )

    dsn = os.getenv("DATABASE_URL")
    source = search_sql(ROOT)
    try:
        assert_reset_database(dsn)
        with psycopg.connect(dsn, connect_timeout=15) as connection:
            apply(connection, source, participant_sql_digest(ROOT))
    except ValueError as error:
        raise SystemExit(
            f"{error}\nNothing was applied: Aurora still runs its previous functions."
        ) from error
    except psycopg.Error as error:
        raise SystemExit(
            describe_apply_failure(
                error, rolled_back=True, statement=rendered_sql(source)
            )
        ) from error
    print(f"Applied participant SQL to {search_schema()}; source lab state preserved.")
    # One participant command: the applied functions must also satisfy the
    # stored pg_trgm gates, which is what this re-proves.
    try:
        configure(dsn)
    except psycopg.Error as error:
        raise SystemExit(
            "The SQL was applied, but configuring the search gates failed.\n"
            + describe_apply_failure(error, rolled_back=False)
            + f"\nFix: run {APPLY_SQL} again once the error above is resolved."
        ) from error
    except DatabaseConfigurationError as error:
        raise SystemExit(
            "The SQL was applied, but configuring the search gates failed.\n"
            f"{error}\nFix: run {APPLY_SQL} again once the error above is resolved."
        ) from error


if __name__ == "__main__":
    main()
