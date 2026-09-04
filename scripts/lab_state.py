#!/usr/bin/env python3
"""Reset, solve, and inspect the three independent DAT410 lab seams."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.retrieval_profile import explain

#: Slack for one reciprocal-rank contribution read back out of PostgreSQL by
#: calling `mosaic_search.reciprocal_rank_contribution` directly. Not a
#: retrieval tunable: it is the float comparison tolerance for a value the SQL
#: function already computed, and it is tighter than the tolerance
#: `service.lab_checks.CONTRIBUTION_TOLERANCE` applies to a contribution that
#: has been through JSON on the way out of a search response.
FUNCTION_CONTRIBUTION_TOLERANCE = 1e-12

LAB1_CTE = """, typo AS (
    SELECT * FROM mosaic_search.search_trigram(
        q, f, trigram_limit, trigram_threshold
    )
)"""

LAB1_CHANNEL = """    UNION ALL
    SELECT product_id, 'trigram', trigram_rank,
           trigram_score,
           mosaic_search.reciprocal_rank_contribution(trigram_rank, rrf_k)
    FROM typo"""

LAB2_FORMULA = """SELECT
    1.0::double precision
    / (
        rrf_k::double precision
        + source_rank::double precision
    )"""
LAB2_BROKEN_FORMULA = """SELECT
    1.0::double precision
    / (
        rrf_k::double precision
        + 1.0::double precision
    )"""

LAB3_EVIDENCE_STATE = """    for item in evidence:
        state["evidence"][item.evidence_id] = item
        product_evidence = state["evidence_by_product"].setdefault(product_id, [])
        if item.evidence_id not in product_evidence:
            product_evidence.append(item.evidence_id)"""

LAB3_BROKEN_STATE = (
    "    # Evidence is visible to the model but not attached to grounded synthesis."
)

LABS: dict[int, tuple[str, tuple[tuple[str, str, str, str], ...]]] = {
    1: (
        "db/sql/09_search_functions.sql",
        (
            (
                "-- LAB1_TRIGRAM_CTE_START",
                "-- LAB1_TRIGRAM_CTE_END",
                LAB1_CTE,
                "",
            ),
            (
                "-- LAB1_TRIGRAM_CHANNEL_START",
                "-- LAB1_TRIGRAM_CHANNEL_END",
                LAB1_CHANNEL,
                "",
            ),
        ),
    ),
    2: (
        "db/sql/09_search_functions.sql",
        (
            (
                "-- LAB2_RRF_FORMULA_START",
                "-- LAB2_RRF_FORMULA_END",
                LAB2_FORMULA,
                LAB2_BROKEN_FORMULA,
            ),
        ),
    ),
    3: (
        "service/agent_tools.py",
        (
            (
                "# LAB3_EVIDENCE_STATE_START",
                "# LAB3_EVIDENCE_STATE_END",
                LAB3_EVIDENCE_STATE,
                LAB3_BROKEN_STATE,
            ),
        ),
    ),
}


def _replace_block(
    source: str,
    start_marker: str,
    end_marker: str,
    replacement: str,
) -> str:
    if source.count(start_marker) != 1 or source.count(end_marker) != 1:
        raise ValueError(
            f"lab marker drift: expected one {start_marker!r} and {end_marker!r}"
        )
    start_marker_offset = source.index(start_marker)
    start_line_end = source.index("\n", start_marker_offset)
    end_marker_offset = source.index(end_marker, start_line_end)
    end_line_start = source.rfind("\n", 0, end_marker_offset) + 1
    return (
        source[: start_line_end + 1]
        + replacement.rstrip()
        + "\n"
        + source[end_line_start:]
    )


def set_lab_state(
    lab: int,
    *,
    solved: bool,
    repo: Path = REPO,
) -> Path:
    relative_path, blocks = LABS[lab]
    path = repo / relative_path
    source = path.read_text(encoding="utf-8")
    for start, end, fixed, broken in blocks:
        source = _replace_block(source, start, end, fixed if solved else broken)
    path.write_text(source, encoding="utf-8")
    return path


def set_isolated_lab_state(
    lab: int,
    *,
    repo: Path = REPO,
) -> list[Path]:
    """Make one lab broken while restoring every independent prerequisite."""
    changed: list[Path] = []
    for candidate in LABS:
        path = set_lab_state(candidate, solved=candidate != lab, repo=repo)
        if path not in changed:
            changed.append(path)
    return changed


def lab_is_solved(lab: int, *, repo: Path = REPO) -> bool:
    relative_path, blocks = LABS[lab]
    source = (repo / relative_path).read_text(encoding="utf-8")
    for start_marker, end_marker, fixed, _ in blocks:
        start = source.index(start_marker) + len(start_marker)
        end = source.index(end_marker, start)
        if source[start:end].strip() != fixed.strip():
            return False
    return True


@dataclass(frozen=True)
class LabDatabaseState:
    """What Aurora currently holds for one lab, and how to read that.

    `state` is `applied` when the function installed on the cluster carries the
    repair, `stale` when the source was edited but never re-applied, and
    `not_applicable` for Lab 3, whose seam lives in the API process rather than
    in SQL.
    """

    state: Literal["applied", "stale", "not_applicable"]
    detail: str


#: The two facts each SQL-backed lab is decided on, so the source edit and the
#: applied function can disagree out loud instead of silently.
LAB1_FUNCTION_SIGNATURE = """
    'mosaic_search.search_hybrid_rrf(
        text,vector,jsonb,integer,integer,integer,integer,integer,real
    )'::regprocedure
"""

_LAB3_DETAIL = (
    "Lab 3 edits service/agent_tools.py, which the API process imports once "
    "when it starts, so an edited file only reaches a run after "
    "make restart-lab-api; no Aurora object carries its repair"
)


def _lab_1_database_state(connection: Any) -> LabDatabaseState:
    row = connection.execute(
        f"SELECT pg_get_functiondef({LAB1_FUNCTION_SIGNATURE}) AS definition"
    ).fetchone()
    definition = row["definition"]
    applied = "FROM typo" in definition and "search_trigram" in definition
    return LabDatabaseState(
        state="applied" if applied else "stale",
        detail=(
            "mosaic_search.search_hybrid_rrf reads the trigram CTE"
            if applied
            else explain(
                "the installed mosaic_search.search_hybrid_rrf body has no "
                "trigram CTE and no search_trigram call",
                "run make solution-lab-1, or re-apply the edited file with "
                "make db-apply-search-functions",
            )
        ),
    )


def _lab_2_database_state(connection: Any) -> LabDatabaseState:
    from scripts.retrieval_profile import load_profile

    rrf_k = load_profile().rrf_k
    row = connection.execute(
        """
        SELECT
            mosaic_search.reciprocal_rank_contribution(1, %s)
                AS first_contribution,
            mosaic_search.reciprocal_rank_contribution(2, %s)
                AS second_contribution
        """,
        (rrf_k, rrf_k),
    ).fetchone()
    first = row["first_contribution"]
    second = row["second_contribution"]
    applied = abs(first - (1.0 / (rrf_k + 1))) <= FUNCTION_CONTRIBUTION_TOLERANCE and (
        first > second
    )
    return LabDatabaseState(
        state="applied" if applied else "stale",
        detail=(
            "mosaic_search.reciprocal_rank_contribution decays with rank"
            if applied
            else explain(
                f"reciprocal_rank_contribution(1) = {first} and "
                f"reciprocal_rank_contribution(2) = {second} at k={rrf_k}",
                "run make solution-lab-2, or re-apply the edited file with "
                "make db-apply-search-functions",
            )
        ),
    )


def validate_database(lab: int, connection: Any) -> LabDatabaseState:
    """Report whether Aurora holds the repair this lab's source declares.

    Takes an open connection rather than a DSN so the service reuses its pool
    and the CLI opens exactly one short-lived session. Rows are read by column
    name, because the pooled connections use `dict_row` and a positional read
    would work in one caller and raise in the other.

    Args:
        lab: The lab number, 1 to 3.
        connection: An open connection to the workshop cluster, with a
            dictionary row factory.

    Returns:
        The applied/stale/not-applicable verdict and a readable reason.
    """
    if lab not in {1, 2}:
        return LabDatabaseState(state="not_applicable", detail=_LAB3_DETAIL)
    if lab == 1:
        return _lab_1_database_state(connection)
    return _lab_2_database_state(connection)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("reset", "solution", "validate", "status"))
    parser.add_argument("--lab", type=int, choices=LABS)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.action != "status" and args.lab is None:
        raise SystemExit("--lab is required")
    if args.action == "status":
        for lab in LABS:
            state = "SOLVED" if lab_is_solved(lab) else "BROKEN"
            print(f"Lab {lab}: {state}")
        return 0
    if args.action == "reset":
        paths = set_isolated_lab_state(args.lab)
        rendered = ", ".join(str(path.relative_to(REPO)) for path in paths)
        print(f"Lab {args.lab}: RESET ISOLATED ({rendered})")
        return 0
    if args.action == "solution":
        path = set_lab_state(args.lab, solved=True)
        print(f"Lab {args.lab}: SOLUTION ({path.relative_to(REPO)})")
        return 0
    if not lab_is_solved(args.lab):
        raise SystemExit(f"Lab {args.lab}: BROKEN; run make solution-lab-{args.lab}")
    if args.database_url:
        _validate_applied_state(args.lab, args.database_url)
    elif args.lab in {1, 2}:
        raise SystemExit(
            f"Lab {args.lab}: source is solved but DATABASE_URL is required "
            "to validate the applied Aurora function"
        )
    print(f"Lab {args.lab}: PASS")
    return 0


def _validate_applied_state(lab: int, database_url: str) -> None:
    """Open one short-lived session and refuse a stale Aurora function."""
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(
        database_url, connect_timeout=20, row_factory=dict_row
    ) as connection:
        applied = validate_database(lab, connection)
    if applied.state == "stale":
        raise SystemExit(f"Lab {lab}: STALE; {applied.detail}")


if __name__ == "__main__":
    raise SystemExit(main())
