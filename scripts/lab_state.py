#!/usr/bin/env python3
"""Reset, solve, and inspect the three independent DAT410 lab seams."""

from __future__ import annotations

import argparse
import ast
import difflib
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, NamedTuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from service.catalog_runtime import search_schema
from service.lab_files import LAB1_SQL, LAB2_SQL, LAB3_AGENT, solution_path
from service.participant_commands import (
    APPLY_SQL,
    DEPLOY_AGENT,
    complete_lab_3,
    reset,
    solution,
    validate,
    validate_applied,
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


def _block_span(
    source: str, start: str, end: str, *, path: Path
) -> tuple[int, list[str]]:
    """A marked block's lines and the file line number of its first line."""
    lines = _block_text(source, start, end, path=path).splitlines()
    marker_line = source.split(start, 1)[0].count("\n") + 1
    body = source.split(start, 1)[1]
    leading = len(body) - len(body.lstrip("\n"))
    return marker_line + leading, lines


def _shift_hunks(line: str, expected_first: int, yours_first: int) -> str:
    """Move difflib's block-relative hunk header onto each file's own line numbers."""
    match = re.match(r"@@ -(\d+)(,\d+)? \+(\d+)(,\d+)? @@", line)
    if not match:
        return line
    expected = int(match[1]) + expected_first - 1
    yours = int(match[3]) + yours_first - 1
    return f"@@ -{expected}{match[2] or ''} +{yours}{match[4] or ''} @@"


def _paint(line: str, color: bool) -> str:
    if not color:
        return line
    for prefix, code in (
        ("---", "1"),
        ("+++", "1"),
        ("@@", "36"),
        ("-", "31"),
        ("+", "32"),
    ):
        if line.startswith(prefix):
            return f"\033[{code}m{line}\033[0m"
    return line


def _diff_footer(lab: int) -> list[str]:
    if lab == 3:
        verdict = (
            "Lab 3 also asks for your own instruction inside this block, so some "
            f"difference is expected. Deploy with {DEPLOY_AGENT}, then check the saved "
            f"run with {complete_lab_3()}."
        )
    else:
        verdict = (
            "A difference is not a failure: other SQL can be correct. Apply it with "
            f"{APPLY_SQL}, then prove it with {validate(lab)}."
        )
    return [
        "",
        "'-' lines are the reference answer; '+' lines are your file as it is now.",
        verdict,
        f"To install the reference answer instead (it overwrites this block): {solution(lab)}",
    ]


def lab_diff(lab: int, *, repo: Path = REPO, color: bool = False) -> tuple[str, bool]:
    """Compare a lab's marked blocks with the reference answer, as a unified diff.

    This prints the answer, so a coach runs it only when a participant asks to
    compare with the reference. Only the marked blocks are compared: the rest of
    the file is the same scaffold for everyone.

    Args:
        lab: The lab number.
        repo: The checkout whose exercise file is read.
        color: Colour the diff for a terminal.

    Returns:
        The report, and whether any marked block differs from the reference.
    """
    relative_path, blocks = LABS[lab]
    path = repo / relative_path
    expected_path = REPO / solution_path(Path(relative_path))
    yours_source = path.read_text(encoding="utf-8")
    expected_source = expected_path.read_text(encoding="utf-8")
    report: list[str] = []
    for start, end, _fixed, _broken in blocks:
        if yours_source.count(start) != 1 or yours_source.count(end) != 1:
            raise ValueError(
                f"Lab diff rule: {relative_path} must hold one {start!r} and one {end!r}; "
                f"fix: restore the marker lines, or run {reset(lab)} to restore the "
                "starter (it discards your edits to this lab)."
            )
        expected_first, expected = _block_span(
            expected_source, start, end, path=expected_path
        )
        yours_first, yours = _block_span(yours_source, start, end, path=path)
        report.extend(
            _shift_hunks(line, expected_first, yours_first)
            for line in difflib.unified_diff(
                expected,
                yours,
                fromfile=f"expected (Lab {lab} reference answer, {solution_path(Path(relative_path))})",
                tofile=f"yours ({relative_path})",
                lineterm="",
            )
        )
    if not report:
        return (
            f"Lab {lab}: the marked block in {relative_path} matches the reference answer.",
            False,
        )
    return "\n".join(
        _paint(line, color) for line in [*report, *_diff_footer(lab)]
    ), True


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


_LAB2_CAST = r" :: (?:double precision|float8|float|numeric|decimal)"
_LAB2_FORMULA = re.compile(
    rf"select (?P<open>\( )?(?P<numerator>1(?:\.0+)?)(?P<numerator_cast>{_LAB2_CAST})?"
    rf" / \( (?P<left>rrf_k|source_rank)(?P<left_cast>{_LAB2_CAST})?"
    rf" \+ (?P<right>rrf_k|source_rank)(?P<right_cast>{_LAB2_CAST})? \)"
    rf"(?P<close> \))?(?P<tail_cast>{_LAB2_CAST})?(?: as [a-z_]\w*)?(?: ;)?"
)


def lab2_contract_problem(source: str) -> str | None:
    """Say how the marked formula differs from floating reciprocal rank, or None.

    The bounded formula permits either addition order, lossless numeric casts,
    parentheses around the whole division and a column alias. Integer division
    must remain a failure even if the enclosing SQL function, or a cast of the
    whole quotient, converts its truncated result to double precision.

    Args:
        source: The lab file.

    Returns:
        The first difference, as a clause a participant can act on, or None.
    """
    start, end, _, _ = LABS[2][1][0]
    markers = _markers_problem(source, start, end)
    if markers:
        return markers
    tokens = _sql_tokens(source.split(start, 1)[1].split(end, 1)[0])
    match = _LAB2_FORMULA.fullmatch(" ".join(tokens))
    if (
        match is None
        or {match["left"], match["right"]} != {"rrf_k", "source_rank"}
        or bool(match["open"]) != bool(match["close"])
    ):
        if "source_rank" not in tokens:
            return (
                "the marked block never reads source_rank, so every position earns "
                "the same credit"
            )
        return (
            "the marked block is not in the form the check recognizes: one position's "
            "reciprocal-rank contribution, 1 / (rrf_k + source_rank), in decimal arithmetic"
        )
    # Without enclosing parentheses a trailing cast binds to the parenthesized
    # sum, so it makes the division itself decimal.
    decimal = (
        "." in match["numerator"]
        or any(match[name] for name in ("numerator_cast", "left_cast", "right_cast"))
        or (match["tail_cast"] and not match["open"])
    )
    if decimal:
        return None
    return (
        "the marked block divides whole numbers, so every contribution rounds down "
        "to 0; write the 1 as 1.0 or cast one operand to double precision"
    )


def _lab2_matches_contract(source: str) -> bool:
    return lab2_contract_problem(source) is None


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


#: Both names the search functions carry. The file says `mosaic_search`, the
#: guide's psql examples say `mosaic_live_search`, and apply installs either
#: spelling under the live schema, so a participant may copy either one.
SEARCH_SCHEMAS = frozenset({"mosaic_search", "mosaic_live_search"})

#: What each column of the close-spelling branch carries, as a mismatch names it.
_LAB1_COLUMN_ROLES = (
    "product_id",
    "the channel name 'trigram', which the rest of the search uses for close spelling",
    "the close-spelling position, trigram_rank",
    "the close-spelling score, trigram_score",
    (
        "the RRF contribution of that position, computed the way the other "
        "branches compute theirs"
    ),
)


def _sql_text(tokens: list[str]) -> str:
    text = re.sub(r" ?(\.|::) ?", r"\1", " ".join(tokens))
    text = re.sub(r"(\w) \(", r"\1(", text).replace("( ", "(")
    return re.sub(r" ([),])", r"\1", text)


def _markers_problem(source: str, start: str, end: str) -> str | None:
    if (
        source.count(start) == 1
        and source.count(end) == 1
        and source.index(start) < source.index(end)
    ):
        return None
    return (
        f"the {start.lstrip('-# ')} and {end.lstrip('-# ')} lines must each appear "
        "once, in that order; restore the marker line you changed (git diff shows it)"
    )


def _branch_source(tokens: list[str]) -> tuple[list[str], str, set[str]] | None:
    """Split `... FROM name [[AS] alias]` into the columns, the name and its qualifiers."""
    if "from" not in tokens:
        return None
    at = len(tokens) - 1 - tokens[::-1].index("from")
    tail = tokens[at + 1 :]
    if tail[1:2] == ["as"]:
        tail = [tail[0], *tail[2:]]
    if not 1 <= len(tail) <= 2 or not all(
        re.fullmatch(r"[a-z_]\w*", name) for name in tail
    ):
        return None
    return tokens[:at], tail[0], set(tail)


def _lab1_column_problem(
    columns: list[str], qualifiers: set[str], schema: str
) -> str | None:
    projected = _projection(columns)
    if not projected:
        return "the branch's column list is empty or has unbalanced parentheses"
    outputs = []
    for expression, _alias in projected:
        output: list[str] = []
        for token in expression:
            if token == "." and output and output[-1] in qualifiers:
                output.pop()
            else:
                output.append(schema if token in SEARCH_SCHEMAS else token)
        outputs.append(output)
    if len(outputs) != len(_LAB1_COLUMN_ROLES):
        return (
            f"the branch returns {len(outputs)} columns; every branch returns five: "
            "product ID, channel name, position, score and RRF contribution"
        )
    if outputs[1] == ["'trigram'", "::", "text"]:
        outputs[1] = ["'trigram'"]
    expected = [
        ["product_id"],
        ["'trigram'"],
        ["trigram_rank"],
        ["trigram_score"],
        _sql_tokens(f"{schema}.reciprocal_rank_contribution(trigram_rank, rrf_k)"),
    ]
    for number, (found, wanted, role) in enumerate(
        zip(outputs, expected, _LAB1_COLUMN_ROLES, strict=True), start=1
    ):
        if found != wanted:
            return f"column {number} is {_sql_text(found)}; it must be {role}"
    return None


def lab1_contract_problem(source: str, *, schema: str = "mosaic_search") -> str | None:
    """Say how the close-spelling branch breaks its data flow, or None when it holds.

    The shipped CTE must forward the four production parameters and expose the
    three result columns; the participant's UNION ALL branch must read it and
    preserve rank, score, channel and unweighted contribution. Column and table
    aliases, qualified columns and either search schema name do not change that
    contract. Production retrieval validation separately proves the behavior.

    Args:
        source: The lab file, or the function definition Aurora runs.
        schema: The schema the shipped CTE calls `search_trigram` in.

    Returns:
        The first difference, as a clause a participant can act on, or None.
    """
    ((start, end, _, _),) = LABS[1][1]
    markers = _markers_problem(source, start, end)
    if markers:
        return markers
    name = _trigram_cte(_sql_tokens(source), schema)
    if name is None:
        return (
            "the close-spelling step above the marked block has changed; undo edits "
            "outside the marked block (git diff shows them)"
        )
    channel = _sql_tokens(source.split(start, 1)[1].split(end, 1)[0])
    if not channel:
        return "the marked block holds only comments, so no branch reaches channels yet"
    if channel[:3] != ["union", "all", "select"]:
        return "the branch must start with UNION ALL SELECT, like the other branches"
    parts = _branch_source(channel[3:])
    if parts is None:
        return (
            "the branch must end with FROM and the results it reads, optionally "
            "with an alias, like the other branches"
        )
    columns, read, qualifiers = parts
    if read != name:
        return (
            f"the branch reads FROM {read}; it must read the search results that no "
            "other branch reads yet"
        )
    return _lab1_column_problem(columns, qualifiers, schema)


def _lab1_matches_contract(source: str, *, schema: str = "mosaic_search") -> bool:
    return lab1_contract_problem(source, schema=schema) is None


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


def _marked_tokens(source: str, lab: int) -> list[str] | None:
    """A lab's marked SQL as tokens, with both search schema names made equal.

    PostgreSQL keeps a SQL function's body as written, comments included, so
    the block Aurora runs can be compared with the saved one directly. Apply
    rewrites the schema name, and the comparison ignores only that.
    """
    ((start, end, _, _),) = LABS[lab][1]
    if _markers_problem(source, start, end):
        return None
    body = source.split(start, 1)[1].split(end, 1)[0]
    return [
        "mosaic_search" if token in SEARCH_SCHEMAS else token
        for token in _sql_tokens(body)
    ]


def _lab_1_database_state(connection: Any, repo: Path) -> LabDatabaseState:
    schema = search_schema()
    signature = LAB1_FUNCTION_SIGNATURE.replace("mosaic_search.", schema + ".")
    row = connection.execute(
        f"SELECT pg_get_functiondef({signature}) AS definition"
    ).fetchone()
    definition = row["definition"]
    path = LABS[1][0]
    saved = (repo / path).read_text(encoding="utf-8")
    if _marked_tokens(definition, 1) != _marked_tokens(saved, 1):
        return LabDatabaseState(
            state="stale",
            detail=(
                "Aurora runs a different LAB1_CHANNEL block from the one saved in "
                f"{path}. Saving changes only the file; applying it updates Aurora."
            ),
        )
    problem = lab1_contract_problem(definition, schema=schema)
    return LabDatabaseState(
        state="applied" if problem is None else "stale",
        detail=(
            f"Aurora runs the LAB1_CHANNEL block saved in {path}."
            if problem is None
            else f"Aurora runs the LAB1_CHANNEL block saved in {path}, but {problem}."
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
            else (
                f"In Aurora, position 1 earns {first:.6f} and position 2 earns "
                f"{second:.6f} at k={rrf_k}; repaired, position 1 earns "
                f"{1.0 / (rrf_k + 1):.6f}, more than position 2. Saving changes only "
                "the file; applying it updates Aurora."
            )
        ),
    )


def validate_database(
    lab: int, connection: Any, *, repo: Path = REPO
) -> LabDatabaseState:
    """Report whether Aurora holds the repair this lab's source declares.

    Takes an open connection rather than a DSN so the service reuses its pool
    and the CLI opens exactly one short-lived session. Rows are read by column
    name, because the pooled connections use `dict_row` and a positional read
    would work in one caller and raise in the other.

    Args:
        lab: The lab number, 1 to 3.
        connection: An open connection to the workshop cluster, with a
            dictionary row factory.
        repo: The checkout whose saved Lab 1 block Aurora is compared with.

    Returns:
        The applied/stale/not-applicable verdict and a readable reason.
    """
    if lab not in {1, 2}:
        return LabDatabaseState(state="not_applicable", detail=_LAB3_DETAIL)
    if lab == 1:
        return _lab_1_database_state(connection, repo)
    return _lab_2_database_state(connection)


@dataclass(frozen=True)
class LabProblem:
    """Why a SQL lab is not ready yet, in the participant's words, and the fix."""

    finding: str
    next_step: str


def source_problem(lab: int, *, repo: Path = REPO) -> LabProblem | None:
    """Say why a SQL lab's saved block is not repaired, or None when it is."""
    path = LABS[lab][0]
    source = (repo / path).read_text(encoding="utf-8")
    reason = (
        lab1_contract_problem(source) if lab == 1 else lab2_contract_problem(source)
    )
    if reason is None:
        return None
    return LabProblem(
        f"Lab {lab} is not repaired: in {path}, {reason}.",
        f"fix the marked block in Code Editor, save it, then run {APPLY_SQL}",
    )


def applied_problem(lab: int, applied: LabDatabaseState) -> LabProblem | None:
    """Say why Aurora does not run a SQL lab's saved repair, or None when it does."""
    if applied.state != "stale":
        return None
    return LabProblem(
        f"Lab {lab}'s saved repair is not in Aurora. {applied.detail}", APPLY_SQL
    )


def explain_problems(header: str, problems: list[LabProblem], then: str) -> str:
    """Lay out what blocks a command and how to continue, one problem per item."""
    lines = [header]
    for problem in problems:
        lines += [f"- {problem.finding}", f"  Next: {problem.next_step}"]
    return "\n".join([*lines, f"Then: {then}"])


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
            "advance --lab 1 validates Lab 1 and prepares Lab 2; "
            "start enters a lab once and keeps your edits on a rerun; reset "
            "discards one lab's edits and restores its starter; solution "
            "overwrites one lab with the reference repair; diff compares a lab's "
            "marked block with the reference repair and changes nothing."
        )
    )
    parser.add_argument(
        "action",
        choices=("start", "advance", "reset", "solution", "diff", "validate", "status"),
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
    if args.action in {"start", "advance", "reset"}:
        import psycopg

        from scripts.lab_entry import LabEntryError, advance, restart, start
        from scripts.validate_lab import LabValidationError

        action = {"start": start, "advance": advance, "reset": restart}[args.action]
        try:
            action(args.lab, api_url=args.api_url, dsn=args.database_url)
        except (LabEntryError, LabValidationError) as error:
            raise SystemExit(str(error)) from error
        except psycopg.Error as error:
            raise database_fault_exit(error, f"{args.action} Lab {args.lab}") from error
        return 0
    if args.action == "diff":
        color = sys.stdout.isatty() and "NO_COLOR" not in os.environ
        try:
            report, _differs = lab_diff(args.lab, color=color)
        except ValueError as error:
            raise SystemExit(str(error)) from error
        print(report)
        return 0
    if args.action == "solution":
        path = set_lab_state(args.lab, solved=True)
        print(solution_summary(args.lab, path.relative_to(REPO)))
        return 0
    return _validate_command(args.lab, args.database_url)


def _validate_command(lab: int, database_url: str | None) -> int:
    """Check one lab's saved source and, for a SQL lab, the block Aurora runs."""
    if lab == 3:
        if not lab_is_solved(3):
            from service.agent_setup import AGENT_STARTER_MESSAGE

            raise SystemExit(AGENT_STARTER_MESSAGE)
        print(
            "Lab 3: source assembled. This checks the file's shape, not your agent. "
            f"Next: deploy with {DEPLOY_AGENT}, ask Alex's request in Ask Mosaic, "
            f"then check the saved run with {complete_lab_3()}."
        )
        return 0
    problem = source_problem(lab)
    if problem is None and not database_url:
        problem = LabProblem(
            "DATABASE_URL is empty in this terminal, so the check cannot read Aurora.",
            "open a new terminal from the Terminal menu; it loads the workshop settings",
        )
    if problem is None:
        problem = _applied_problem_in(lab, database_url)
    if problem is not None:
        raise SystemExit(
            explain_problems(f"Lab {lab}: FAIL", [problem], validate_applied(lab))
        )
    print(
        f"Lab {lab}: PASS. {LABS[lab][0]} is repaired and Aurora runs it.\n"
        f"Next: {validate(lab)}"
    )
    return 0


def _applied_problem_in(lab: int, database_url: str) -> LabProblem | None:
    """Open one short-lived session and say whether Aurora runs the saved repair."""
    import psycopg
    from psycopg.rows import dict_row

    try:
        with psycopg.connect(
            database_url, connect_timeout=20, row_factory=dict_row
        ) as connection:
            return applied_problem(lab, validate_database(lab, connection))
    except psycopg.Error as error:
        raise database_fault_exit(error, f"check Lab {lab} in Aurora") from error


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
    """A clean exit for a database failure, without a traceback or the DSN.

    Only a fault of the connection, the server or the role is the environment's;
    any other rejection names Aurora's own reason, because edits outside a marked
    block, applied, are the one participant-made cause.
    """
    sqlstate = error.sqlstate or error.diag.sqlstate or "none"
    if is_environment_fault(error):
        return SystemExit(
            f"Could not {doing}: {type(error).__name__} (SQLSTATE {sqlstate}).\n"
            f"{FACILITATOR_ADVICE}"
        )
    reason = (error.diag.message_primary or type(error).__name__).strip()
    return SystemExit(
        f"Could not {doing}: Aurora rejected it with SQLSTATE {sqlstate}: {reason}\n"
        "Next: if you changed lines outside the marked LAB blocks, undo those changes "
        f"(git diff shows them), run {APPLY_SQL}, then run the same command again. "
        "Otherwise copy this message and the command you ran to your facilitator."
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


if __name__ == "__main__":
    raise SystemExit(main())
