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
from typing import Any, Literal, NamedTuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.checks.retrieval_profile import explain
from service.catalog_runtime import search_schema
from service.lab_files import LAB1_SQL, LAB2_SQL, LAB3_AGENT, solution_path
from service.participant_commands import (
    APPLY_SQL,
    DEPLOY_AGENT,
    complete_lab_3,
    solution,
    validate,
)

#: Slack for one reciprocal-rank contribution read back out of PostgreSQL by
#: calling `mosaic_search.reciprocal_rank_contribution` directly. Not a
#: retrieval tunable: it is the float comparison tolerance for a value the SQL
#: function already computed, and it is tighter than the tolerance
#: `service.lab_checks.CONTRIBUTION_TOLERANCE` applies to a contribution that
#: has been through JSON on the way out of a search response.
FUNCTION_CONTRIBUTION_TOLERANCE = 1e-12

#: What a participant finds in each marked block when a lab starts. Lab 1's TODO
#: names the symptom so that finding the lost search stays the participant's work;
#: the others repeat the lab guide's contract for the edit, not its answer.
LAB1_CHANNEL_STARTER = """-- TODO(Lab 1): one search's candidates never reach `channels`. Find which,
-- then add its branch here with the same five columns as the others."""
LAB2_STARTER = """-- TODO(Lab 2): return one source position's reciprocal-rank contribution.
-- Keep the signature, the double precision result and the configured rrf_k.
SELECT
    1.0::double precision
    / (
        rrf_k::double precision
        + 1.0::double precision
    )"""
LAB3_STARTER = f"""    # TODO(Lab 3): return a Strands Agent built from the supplied model, tools,
    # instructions (as system_prompt) and hooks, with callback_handler=None.
    raise NotImplementedError("Build your Strands agent here, then deploy with {DEPLOY_AGENT}.")"""


class Block(NamedTuple):
    """One marked block: its markers, the reference answer and the starter."""

    start: str
    end: str
    fixed: str
    broken: str


class LabSeam(NamedTuple):
    """The file a lab edits and the marked blocks inside it."""

    exercise: str
    blocks: tuple[Block, ...]


def _block_text(source: str, start: str, end: str, *, path: Path) -> str:
    if source.count(start) != 1 or source.count(end) != 1:
        raise ValueError(
            f"Lab solution rule: {path} must hold one {start!r} and one {end!r}; "
            "fix: restore the marked block in the solution file."
        )
    body = source.split(start, 1)[1].split(end, 1)[0]
    return body.strip("\n").rstrip()


def _seam(exercise: Path, *blocks: tuple[str, str, str]) -> LabSeam:
    """Read each block's reference answer from the lab's solution file."""
    solution = REPO / solution_path(exercise)
    source = solution.read_text(encoding="utf-8")
    return LabSeam(
        exercise.as_posix(),
        tuple(
            Block(start, end, _block_text(source, start, end, path=solution), broken)
            for start, end, broken in blocks
        ),
    )


LABS: dict[int, LabSeam] = {
    1: _seam(
        LAB1_SQL,
        (
            "-- LAB1_CHANNEL_START",
            "-- LAB1_CHANNEL_END",
            LAB1_CHANNEL_STARTER,
        ),
    ),
    2: _seam(
        LAB2_SQL,
        ("-- LAB2_RRF_FORMULA_START", "-- LAB2_RRF_FORMULA_END", LAB2_STARTER),
    ),
    3: _seam(LAB3_AGENT, ("# LAB3_AGENT_START", "# LAB3_AGENT_END", LAB3_STARTER)),
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


def _trigram_cte(tokens: list[str], schema: str) -> str | None:
    """Name of the CTE that forwards the four production parameters to search_trigram.

    The CTE is shipped code, not the participant's edit, so it is found by its call
    rather than by markers; it must still expose the three result columns.
    """
    call = [
        *_sql_tokens(
            f"{schema}.search_trigram(q, f, trigram_limit, trigram_threshold)"
        ),
        ")",
    ]
    starts = [i for i in range(len(tokens)) if tokens[i : i + len(call)] == call]
    if len(starts) != 1 or starts[0] < 1 or tokens[starts[0] - 1] != "from":
        return None
    boundary = starts[0] - 1
    heads = [
        i for i in range(2, boundary) if tokens[i : i + 3] == ["as", "(", "select"]
    ]
    if not heads or tokens[heads[-1] - 2] != ",":
        return None
    head = heads[-1]
    name = tokens[head - 1]
    if not re.fullmatch(r"[a-z_]\w*", name):
        return None
    columns = tokens[head + 3 : boundary]
    if columns != ["*"]:
        projected = _projection(columns)
        required = {"product_id", "trigram_rank", "trigram_score"}
        if len(projected) != len(required) or {
            tuple(expression) for expression, _ in projected
        } != {(column,) for column in required}:
            return None
        if any(alias not in {None, expression[0]} for expression, alias in projected):
            return None
    return name


def _lab1_matches_contract(source: str, *, schema: str = "mosaic_search") -> bool:
    """Check the close-spelling path by its data flow, not local names.

    The shipped CTE must forward the four production parameters and expose the
    three result columns; the participant's UNION ALL branch must read it and
    preserve rank, score, channel and unweighted contribution. Aliases and explicit
    projections do not change that contract. Production retrieval validation
    separately proves the behavior.
    """
    ((start, end, _, _),) = LABS[1][1]
    if source.count(start) != 1 or source.count(end) != 1:
        return False
    body = source.split(start, 1)[1]
    if end not in body:
        return False
    channel = _sql_tokens(body.split(end, 1)[0])
    name = _trigram_cte(_sql_tokens(source), schema)
    if name is None:
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
    f"Lab 3 builds {LAB3_AGENT}. Deploy with {DEPLOY_AGENT} to publish the "
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
                f"complete the Lab 1 block and apply it with {APPLY_SQL}",
            )
        ),
    )


def _lab_2_database_state(connection: Any) -> LabDatabaseState:
    from scripts.checks.retrieval_profile import load_profile

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
                f"re-apply the edited file with {APPLY_SQL}, or restore the "
                f"reference repair with {solution(2)} and then apply it",
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


def status_line(lab: int, *, repo: Path = REPO) -> str:
    """One lab's state as the participant has it, not as the checkout ships it.

    The shipped seams for Labs 2 and 3 are repaired, so before a start they
    would read SOLVED for work nobody has done.
    """
    from scripts.lab_entry import FAULT_AT_ENTRY, load_record
    from service.participant_commands import start as start_command

    record = load_record(lab, repo)
    if record is None and lab in FAULT_AT_ENTRY:
        return f"Lab {lab}: NOT STARTED"
    if record is not None and not record.get("completed_at"):
        return (
            f"Lab {lab}: START INTERRUPTED. Next: run {start_command(lab)} "
            "again; it finishes the missing step and keeps your edits."
        )
    return f"Lab {lab}: {'SOLVED' if lab_is_solved(lab, repo=repo) else 'BROKEN'}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "start enters a lab once and keeps your edits on a rerun; reset "
            "discards one lab's edits and restores its starter; solution "
            "overwrites one lab with the reference repair."
        )
    )
    parser.add_argument(
        "action", choices=("start", "reset", "solution", "validate", "status")
    )
    parser.add_argument(
        "--source-only",
        action="store_true",
        help=(
            "reset only the lab's marked source, for provisioning: no apply, "
            "no saved request, no start record"
        ),
    )
    parser.add_argument("--lab", type=int, choices=LABS)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument(
        "--api-url", default=os.getenv("LAB_API_URL", "http://127.0.0.1:8000")
    )
    return parser


def solution_summary(lab: int, path: Path) -> str:
    """Say what `solution` overwrote and which commands come next."""
    if lab == 3:
        next_step = (
            f"deploy with {DEPLOY_AGENT}, ask Alex's request in Ask Mosaic, then "
            f"check the saved run with {complete_lab_3()}"
        )
    else:
        next_step = f"apply it with {APPLY_SQL}, then prove it with {validate(lab)}"
    return (
        f"Lab {lab}: SOLUTION ({path})\n"
        f"This overwrote the marked LAB{lab}_ block in {path} with the reference "
        "answer, so your own edits to that block are gone; run git diff to see "
        "the change.\n"
        f"Next: {next_step}."
    )


def main() -> int:
    args = _parser().parse_args()
    if args.action != "status" and args.lab is None:
        valid = ", ".join(str(lab) for lab in sorted(LABS))
        raise SystemExit(
            f"Lab rule: {args.action} needs --lab, with one of {valid}. "
            f"Next: run uv run python scripts/lab_state.py {args.action} --lab N, "
            f"for example uv run python scripts/lab_state.py {args.action} --lab 1."
        )
    if args.action == "status":
        for lab in LABS:
            print(status_line(lab))
        return 0
    if args.action == "reset" and args.source_only:
        # Provisioning installs Lab 1's fault before the API exists, then
        # applies it itself. Only the named lab's seam changes.
        assert_reset_database(args.database_url)
        path = set_lab_state(args.lab, solved=False)
        print(f"Lab {args.lab}: RESET ({path.relative_to(REPO)})")
        return 0
    if args.action in {"start", "reset"}:
        import psycopg

        from scripts.lab_entry import LabEntryError, restart, start
        from scripts.validate_lab import LabValidationError

        action = start if args.action == "start" else restart
        try:
            action(args.lab, api_url=args.api_url, dsn=args.database_url)
        except (LabEntryError, LabValidationError) as error:
            raise SystemExit(str(error)) from error
        except psycopg.Error as error:
            raise database_fault_exit(error, f"{args.action} Lab {args.lab}") from error
        return 0
    if args.action == "solution":
        path = set_lab_state(args.lab, solved=True)
        print(solution_summary(args.lab, path.relative_to(REPO)))
        return 0
    if not lab_is_solved(args.lab):
        if args.lab == 3:
            from service.agent_setup import AGENT_STARTER_MESSAGE

            raise SystemExit(AGENT_STARTER_MESSAGE)
        raise SystemExit(
            f"Lab {args.lab}: the SQL change is incomplete. Open {LABS[args.lab][0]} "
            f"in Code Editor and find the LAB{args.lab}_ markers. Next: complete the "
            f"marked block, apply it with {APPLY_SQL}, then prove it with {validate(args.lab)}. "
            f"For recovery, follow Hint 4 in the Lab {args.lab} guide."
        )
    if args.database_url:
        _validate_applied_state(args.lab, args.database_url)
    elif args.lab in {1, 2}:
        raise SystemExit(
            f"Lab {args.lab}: source is solved but DATABASE_URL is required "
            "to validate the applied Aurora function"
        )
    if args.lab == 3:
        print(
            "Lab 3: source assembled. This checks the file's shape, not your agent. "
            f"Next: deploy with {DEPLOY_AGENT}, ask Alex's request in Ask Mosaic, "
            f"then check the saved run with {complete_lab_3()}."
        )
        return 0
    print(f"Lab {args.lab}: PASS")
    return 0


#: SQLSTATE classes that describe the connection, the server's resources or its
#: operator, never the participant's SQL: 08 connection, 53 resources, 57 operator.
_ENVIRONMENT_SQLSTATE_CLASSES = frozenset({"08", "53", "57"})
_INSUFFICIENT_PRIVILEGE = "42501"

FACILITATOR_ADVICE = (
    "This is an environment problem, not a mistake in your SQL, so do not edit the "
    "LAB blocks. Fix: copy this message and the command you ran, and give them to "
    "your facilitator."
)


def is_environment_fault(error) -> bool:
    """True when Aurora, the network or the database role failed, not the SQL.

    A missing SQLSTATE means the failure happened before the server answered.
    """
    sqlstate = error.sqlstate or error.diag.sqlstate
    return (
        sqlstate is None
        or sqlstate[:2] in _ENVIRONMENT_SQLSTATE_CLASSES
        or sqlstate == _INSUFFICIENT_PRIVILEGE
    )


def database_fault_exit(error, doing: str) -> SystemExit:
    """A clean exit for a database failure, without a traceback or the DSN."""
    sqlstate = error.sqlstate or error.diag.sqlstate or "none"
    return SystemExit(
        f"Could not {doing}: {type(error).__name__} (SQLSTATE {sqlstate}).\n"
        f"{FACILITATOR_ADVICE}"
    )


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
    try:
        with psycopg.connect(
            database_url, connect_timeout=15, row_factory=dict_row
        ) as connection:
            identity = connection.execute(
                "SELECT current_database() AS name, aurora_version() AS aurora, "
                f"to_regclass('{search_schema()}.product_document')::text AS catalog"
            ).fetchone()
    except psycopg.Error as error:
        raise database_fault_exit(error, "check the workshop database") from error
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
