#!/usr/bin/env python3
"""Reset, solve, and inspect the three independent DAT410 lab seams."""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.retrieval_profile import explain
from service.catalog_runtime import search_schema

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

LAB3_AGENT = """    return Agent(
        model=model,
        tools=tools,
        system_prompt=instructions,
        hooks=hooks,
        callback_handler=None,
    )"""
LAB3_STARTER = '    raise NotImplementedError("Build your Strands agent here, then run make deploy-agent.")'

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
        "labs/lab3/agent.py",
        (
            (
                "# LAB3_AGENT_START",
                "# LAB3_AGENT_END",
                LAB3_AGENT,
                LAB3_STARTER,
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
    """Make one lab broken while restoring every independent prerequisite.

    A prerequisite the participant already repaired keeps their code: the lab
    guides promise that later labs preserve earlier repairs, and Lab 3's proof
    reads the participant's own fusion back from the agent's searches. Only a
    prerequisite that fails its contract is rewritten to the reference.
    """
    changed: list[Path] = []
    for candidate in LABS:
        if candidate != lab and lab_is_solved(candidate, repo=repo):
            continue
        path = set_lab_state(candidate, solved=candidate != lab, repo=repo)
        if path not in changed:
            changed.append(path)
    return changed


def _sql_tokens(source: str) -> list[str]:
    pattern = (
        r"--[^\n]*|/\*.*?\*/|'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|"
        r"[A-Za-z_]\w*|\d+(?:\.\d+)?|::|<>|!=|<=|>=|\S"
    )
    return [
        token if token.startswith(("'", '"')) else token.lower()
        for token in re.findall(pattern, source, re.DOTALL)
        if not token.startswith(("--", "/*"))
    ]


def _lab2_matches_contract(source: str) -> bool:
    """Recognize floating reciprocal rank without requiring reference casts.

    The bounded formula permits either addition order and lossless numeric
    casts. Integer division must remain a failure even if the enclosing SQL
    function converts its truncated result to double precision.
    """
    start, end, _, _ = LABS[2][1][0]
    if source.count(start) != 1 or source.count(end) != 1:
        return False
    body = source.split(start, 1)[1].split(end, 1)[0]
    cast = r" :: (?:double precision|float8|numeric|decimal)"
    match = re.fullmatch(
        rf"select (?P<numerator>1(?:\.0+)?)(?P<numerator_cast>{cast})?"
        rf" / \( (?P<left>rrf_k|source_rank)(?P<left_cast>{cast})?"
        rf" \+ (?P<right>rrf_k|source_rank)(?P<right_cast>{cast})? \)(?: ;)?",
        " ".join(_sql_tokens(body)),
    )
    if match is None:
        return False
    return {match["left"], match["right"]} == {"rrf_k", "source_rank"} and (
        "." in match["numerator"]
        or any(match[name] for name in ("numerator_cast", "left_cast", "right_cast"))
    )


def _projection(tokens: list[str]) -> list[tuple[list[str], str | None]]:
    expressions: list[list[str]] = [[]]
    depth = 0
    for token in tokens:
        depth += (token == "(") - (token == ")")
        if depth < 0:
            return []
        if token == "," and depth == 0:
            expressions.append([])
        else:
            expressions[-1].append(token)
    if depth or any(not expression for expression in expressions):
        return []
    result = []
    for expression in expressions:
        if len(expression) >= 3 and expression[-2] == "as":
            if not re.fullmatch(r"[a-z_]\w*", expression[-1]):
                return []
            result.append((expression[:-2], expression[-1]))
        else:
            result.append((expression, None))
    return result


def _lab1_matches_contract(source: str, *, schema: str = "mosaic_search") -> bool:
    """Check the two bounded SQL blocks by their data flow, not local names.

    The CTE must forward the four production parameters and expose the three
    result columns; its UNION ALL branch must preserve rank, score, channel and
    unweighted contribution. Aliases and explicit projections do not change that
    contract. Production retrieval validation separately proves the behavior.
    """
    blocks = []
    for start, end, _, _ in LABS[1][1]:
        if source.count(start) != 1 or source.count(end) != 1:
            return False
        body = source.split(start, 1)[1]
        if end not in body:
            return False
        blocks.append(_sql_tokens(body.split(end, 1)[0]))
    cte, channel = blocks
    if len(cte) < 7 or cte[0] != "," or cte[2:5] != ["as", "(", "select"]:
        return False
    name = cte[1]
    if not re.fullmatch(r"[a-z_]\w*", name) or "from" not in cte[5:]:
        return False
    boundary = cte.index("from", 5)
    expected_call = _sql_tokens(
        f"{schema}.search_trigram(q, f, trigram_limit, trigram_threshold)"
    )
    if cte[boundary + 1 :] != [*expected_call, ")"]:
        return False
    columns = cte[5:boundary]
    if columns != ["*"]:
        projected = _projection(columns)
        required = {"product_id", "trigram_rank", "trigram_score"}
        if len(projected) != len(required) or {
            tuple(expression) for expression, _ in projected
        } != {(column,) for column in required}:
            return False
        if any(alias not in {None, expression[0]} for expression, alias in projected):
            return False
    if channel[:3] != ["union", "all", "select"] or channel[-2:] != ["from", name]:
        return False
    outputs = [expression for expression, _ in _projection(channel[3:-2])]
    if len(outputs) != 5:
        return False
    if outputs[1] == ["'trigram'", "::", "text"]:
        outputs[1] = ["'trigram'"]
    return outputs == [
        ["product_id"],
        ["'trigram'"],
        ["trigram_rank"],
        ["trigram_score"],
        _sql_tokens(f"{schema}.reciprocal_rank_contribution(trigram_rank, rrf_k)"),
    ]


def _lab3_matches_contract(source: str) -> bool:
    """Check that the participant assembles the supplied model, tools and hooks.

    Local variable names and extra instructions do not change the contract.
    A separate process bounds bad edits without importing module
    startup code into the lab-status request.
    """
    for start, end, _, _ in LABS[3][1]:
        if source.count(start) != 1 or source.count(end) != 1:
            return False
    try:
        functions = [
            node
            for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef) and node.name == "create_agent"
        ]
        if len(functions) != 1 or functions[0].decorator_list:
            return False
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                str(Path(__file__).with_name("agent_assembly_probe.py")),
            ],
            input=ast.unparse(functions[0]),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
        return (
            result.returncode == 0 and result.stdout.strip() == "agent assembly ready"
        )
    except (SyntaxError, OSError, subprocess.TimeoutExpired):
        return False


def lab_is_solved(lab: int, *, repo: Path = REPO) -> bool:
    relative_path, _ = LABS[lab]
    source = (repo / relative_path).read_text(encoding="utf-8")
    if lab == 1:
        return _lab1_matches_contract(source)
    if lab == 2:
        return _lab2_matches_contract(source)
    if lab == 3:
        return _lab3_matches_contract(source)
    raise ValueError(f"unknown lab: {lab}")


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
    "Lab 3 builds labs/lab3/agent.py. Run make deploy-agent to publish the "
    "agent and SQL tools; deployed source must match before a run is accepted."
)


def _lab_1_database_state(connection: Any) -> LabDatabaseState:
    schema = search_schema()
    signature = LAB1_FUNCTION_SIGNATURE.replace("mosaic_search.", schema + ".")
    row = connection.execute(
        f"SELECT pg_get_functiondef({signature}) AS definition"
    ).fetchone()
    definition = row["definition"]
    applied = _lab1_matches_contract(definition, schema=schema)
    return LabDatabaseState(
        state="applied" if applied else "stale",
        detail=(
            f"{schema}.search_hybrid_rrf reads the trigram CTE"
            if applied
            else explain(
                f"the installed {schema}.search_hybrid_rrf does not connect "
                "search_trigram(q, f, trigram_limit, trigram_threshold) to the "
                "trigram channel with its source rank, score and RRF contribution",
                "repair both Lab 1 blocks and run make db-apply-search-functions",
            )
        ),
    )


def _lab_2_database_state(connection: Any) -> LabDatabaseState:
    from scripts.retrieval_profile import load_profile

    rrf_k = load_profile().rrf_k
    schema = search_schema()
    row = connection.execute(
        f"""
        SELECT
            {schema}.reciprocal_rank_contribution(1, %s)
                AS first_contribution,
            {schema}.reciprocal_rank_contribution(2, %s)
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
            f"{schema}.reciprocal_rank_contribution decays with rank"
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
        assert_reset_database(args.database_url)
        paths = set_isolated_lab_state(args.lab)
        rendered = ", ".join(str(path.relative_to(REPO)) for path in paths)
        print(f"Lab {args.lab}: RESET ISOLATED ({rendered})")
        return 0
    if args.action == "solution":
        path = set_lab_state(args.lab, solved=True)
        print(f"Lab {args.lab}: SOLUTION ({path.relative_to(REPO)})")
        return 0
    if not lab_is_solved(args.lab):
        if args.lab == 3:
            from service.agent_setup import AGENT_STARTER_MESSAGE

            raise SystemExit(AGENT_STARTER_MESSAGE)
        raise SystemExit(
            f"Lab {args.lab}: the SQL change is incomplete. Open {LABS[args.lab][0]} "
            f"in Code Editor and find the LAB{args.lab}_ markers. Next: complete the "
            f"marked block, run make db-apply-search-functions, then make validate-lab-{args.lab}. "
            f"For recovery, follow Hint 4 in the Lab {args.lab} guide."
        )
    if args.database_url:
        _validate_applied_state(args.lab, args.database_url)
    elif args.lab in {1, 2}:
        raise SystemExit(
            f"Lab {args.lab}: source is solved but DATABASE_URL is required "
            "to validate the applied Aurora function"
        )
    print(f"Lab {args.lab}: PASS")
    return 0


def assert_reset_database(database_url: str | None) -> None:
    """Refuse a destructive exercise reset outside the named workshop database."""
    import psycopg
    from psycopg.rows import dict_row

    expected = os.getenv("MOSAIC_WORKSHOP_DATABASE", "mosaic_catalog")
    if not database_url:
        raise SystemExit(
            "Lab reset rule: DATABASE_URL is missing; fix: select the authorized "
            "Aurora workshop database before resetting a lab."
        )
    with psycopg.connect(
        database_url, connect_timeout=15, row_factory=dict_row
    ) as connection:
        identity = connection.execute(
            "SELECT current_database() AS name, aurora_version() AS aurora, "
            f"to_regclass('{search_schema()}.product_document')::text AS catalog"
        ).fetchone()
    if (
        identity["name"] != expected
        or not identity["catalog"]
        or not identity["aurora"]
    ):
        raise SystemExit(
            f"Lab reset rule: found database {identity['name']!r}; expected "
            f"Aurora workshop database {expected!r} with the Mosaic catalog. "
            "Fix: select the workshop DATABASE_URL; for a custom workshop name, "
            "set MOSAIC_WORKSHOP_DATABASE to its provisioned DBName."
        )


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
