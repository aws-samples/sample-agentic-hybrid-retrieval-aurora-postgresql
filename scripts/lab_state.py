#!/usr/bin/env python3
"""Reset, solve, and inspect the three independent DAT410 lab seams."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

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


def validate_database(lab: int, database_url: str) -> None:
    if lab not in {1, 2}:
        return
    import psycopg

    with psycopg.connect(database_url, connect_timeout=20) as connection:
        if lab == 1:
            definition = connection.execute(
                """
                SELECT pg_get_functiondef(
                    'mosaic_search.search_hybrid_rrf(
                        text,vector,jsonb,integer,integer,integer,integer,
                        integer,real
                    )'::regprocedure
                )
                """
            ).fetchone()[0]
            if "FROM typo" not in definition or "search_trigram" not in definition:
                raise RuntimeError(
                    "Lab 1 database state is not solved; run make solution-lab-1"
                )
        else:
            from scripts.retrieval_profile import load_profile

            rrf_k = load_profile().rrf_k
            first, second = connection.execute(
                """
                SELECT
                    mosaic_search.reciprocal_rank_contribution(1, %s),
                    mosaic_search.reciprocal_rank_contribution(2, %s)
                """,
                (rrf_k, rrf_k),
            ).fetchone()
            if abs(first - (1.0 / (rrf_k + 1))) > 1e-12 or not first > second:
                raise RuntimeError(
                    "Lab 2 database state is not reciprocal-rank fusion; "
                    "run make solution-lab-2"
                )


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
        validate_database(args.lab, args.database_url)
    elif args.lab in {1, 2}:
        raise SystemExit(
            f"Lab {args.lab}: source is solved but DATABASE_URL is required "
            "to validate the applied Aurora function"
        )
    print(f"Lab {args.lab}: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
