#!/usr/bin/env python3
"""Reset, solve, and inspect the three independent DAT410 lab seams."""

from __future__ import annotations

import argparse
import ast
import difflib
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, NamedTuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.progress import Progress
from service.agent_setup import AGENT_NOT_BUILT
from service.catalog_runtime import search_schema
from service.lab_files import (
    LAB1_SQL,
    LAB2_SQL,
    LAB3_AGENT,
    committed_text,
    shipped_files,
    shipped_text,
    solution_path,
)
from service.participant_commands import (
    ADVANCE_TO_LAB_2,
    APPLY_SQL,
    DEPLOY_AGENT,
    DIFF,
    DIFF_ANSWER,
    USUAL_SECONDS,
    apply_solution_command,
    ask_setup_command,
    finish_command,
    finish_steps,
    grade_exercise_command,
    grade_setup_run_command,
    proof_steps_text,
    repeat_request_command,
    reset_command,
    skip_to_command,
    start_command,
    validate_applied_command,
)

#: Slack for one reciprocal-rank contribution read back out of PostgreSQL by
#: calling `mosaic_search.reciprocal_rank_contribution` directly. Not a
#: retrieval tunable: it is the float comparison tolerance for a value the SQL
#: function already computed, and it is tighter than the tolerance
#: `service.lab_checks.CONTRIBUTION_TOLERANCE` applies to a contribution that
#: has been through JSON on the way out of a search response.
FUNCTION_CONTRIBUTION_TOLERANCE = 1e-12

#: Set for the commands `finish` and `skip-to` run, to the run's label, so a step does
#: not tell the participant to run the steps that come next: the run does that itself.
RUN_BY = "MOSAIC_RUN_BY"

#: What a participant finds in each marked block when a lab starts. Lab 1's TODO
#: names the symptom so that finding the lost search stays the participant's work;
#: the others repeat the lab guide's contract for the edit, not its answer.
LAB1_STARTER = """-- TODO(Lab 1): one search's candidates never reach `channels`. Find which,
-- then add its branch here with the same five columns as the others."""
LAB2_STARTER = """-- TODO(Lab 2): replace the SELECT below so each position earns its own score.
-- Keep the signature, the double precision result and the configured rrf_k.
SELECT
    1.0::double precision
    / (
        rrf_k::double precision
        + 1.0::double precision
    )"""
LAB3_STARTER = f"""    # TODO(Lab 3): return a Strands Agent built from the supplied model, tools,
    # instructions (as system_prompt) and hooks, with callback_handler=None.
    raise NotImplementedError("Build your Retrieval agent here, then deploy with {DEPLOY_AGENT}.")"""


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
    # Spaces after the marker belong to its line, not to the block.
    rest_of_marker_line, newline, after = body.partition("\n")
    if newline and not rest_of_marker_line.strip():
        body = after
    return body.strip("\n").rstrip()


def _reference_source(exercise: Path, blocks: tuple[tuple[str, str, str], ...]) -> str:
    """The lab's solution file, or Git's copy when its markers were edited away.

    Every script builds `LABS` at import, so a solution file whose markers a
    participant broke would stop even `reset`, the command that repairs it.
    """
    reference = solution_path(exercise)
    source = shipped_text(reference, REPO)
    try:
        for start, end, _broken in blocks:
            _block_text(source, start, end, path=REPO / reference)
        return source
    except ValueError:
        pass
    try:
        source = committed_text(reference, REPO)
        for start, end, _broken in blocks:
            _block_text(source, start, end, path=REPO / reference)
    except (FileNotFoundError, ValueError) as error:
        raise SystemExit(
            f"Lab file rule: {reference} no longer has its marked lines and Git holds no "
            "clean copy; fix: ask your facilitator to restore it from the workshop source."
        ) from error
    return source


def _seam(exercise: Path, *blocks: tuple[str, str, str]) -> LabSeam:
    """Read each block's reference answer from the lab's solution file."""
    solution = REPO / solution_path(exercise)
    source = _reference_source(exercise, blocks)
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
            "-- LAB1_EDIT_START",
            "-- LAB1_EDIT_END",
            LAB1_STARTER,
        ),
    ),
    2: _seam(
        LAB2_SQL,
        ("-- LAB2_EDIT_START", "-- LAB2_EDIT_END", LAB2_STARTER),
    ),
    3: _seam(LAB3_AGENT, ("# LAB3_EDIT_START", "# LAB3_EDIT_END", LAB3_STARTER)),
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
    # Count from the line after the marker, so trailing spaces on the marker line
    # cannot hide its newline from the blank-line count.
    after_marker = source.split(start, 1)[1].partition("\n")[2]
    inside = after_marker.split(end, 1)[0]
    leading = len(inside) - len(inside.lstrip("\n"))
    return marker_line + 1 + leading, lines


def _plain_differences(
    expected: list[str],
    yours: list[str],
    numbers: list[int],
    *,
    outside: bool = False,
    fallback_line: int = 0,
) -> list[tuple[str, str, list[str], list[str]]]:
    """Each place the participant's lines differ: where, the label, the expected lines, theirs.

    numbers holds the line number in the participant's file of each line in yours.
    fallback_line is where a gap is reported when yours has no lines at all, such
    as a marked block emptied of everything: the block's marker line.
    """
    prefix = "Outside the markers, " if outside else ""
    label = "Original file" if outside else "Reference answer"
    groups = []
    matcher = difflib.SequenceMatcher(a=expected, b=yours, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "delete":
            # The gap sits just before the participant's next line, even when a
            # marked block lies between it and the previous unchanged line.
            after = (
                numbers[j1] - 1
                if j1 < len(numbers)
                else (numbers[-1] if numbers else fallback_line)
            )
            where = f"{prefix}missing from your file, after line {after}"
        else:
            first, last = numbers[j1], numbers[j2 - 1]
            span = f"line {first}" if first == last else f"lines {first}-{last}"
            where = f"{prefix}at {span} of your file"
        groups.append(
            (where[0].upper() + where[1:], label, expected[i1:i2], yours[j1:j2])
        )
    return groups


def _outside_markers(source: str, blocks: list[Block]) -> tuple[list[str], list[int]]:
    """The file's lines outside every marked block, markers included, with their numbers."""
    lines = source.splitlines()
    inside: set[int] = set()
    for start, end, _fixed, _broken in blocks:
        first = next(index for index, line in enumerate(lines) if start in line)
        last = next(index for index, line in enumerate(lines) if end in line)
        inside.update(range(first, last + 1))
    kept = [index for index in range(len(lines)) if index not in inside]
    return [lines[index] for index in kept], [index + 1 for index in kept]


def _paint(line: str, code: str, color: bool) -> str:
    return f"\033[{code}m{line}\033[0m" if color else line


# Commands sit on their own lines under a short label, so a long line never wraps
# mid-word in a terminal and each command copies whole.
COMMAND_INDENT = "      "


def _diff_footer(
    lab: int, *, block_differs: bool, outside_differs: bool, answer: bool
) -> list[str]:
    footer = []
    if outside_differs:
        footer += [
            (
                "Lines outside the markers are not yours to change: put them back "
                "as the original file has them."
            ),
            "To start over instead (it discards your edits to this lab):",
            f"{COMMAND_INDENT}{reset_command(lab)}",
        ]
    if block_differs and lab == 3:
        footer += [
            (
                "Lab 3 also asks for your own instruction inside this block, so "
                "some difference is expected."
            ),
            f"Deploy:   {DEPLOY_AGENT}",
            f"Check:    {grade_setup_run_command()}",
        ]
    elif block_differs:
        check = ADVANCE_TO_LAB_2 if lab == 1 else grade_exercise_command(lab)
        footer += [
            "A different line is not always wrong: other SQL can work too.",
            f"Apply:    {APPLY_SQL}",
            f"Prove:    {repeat_request_command(lab)}",
            f"Then:     {check}",
        ]
    if block_differs and not answer:
        footer += [
            "To see the reference answer for these lines:",
            f"{COMMAND_INDENT}{DIFF_ANSWER}",
        ]
    if block_differs:
        footer += [
            "To use the reference answer instead (it replaces your block):",
            f"{COMMAND_INDENT}{apply_solution_command(lab)}",
        ]
    return footer


def lab_diff(
    lab: int, *, repo: Path = REPO, color: bool = False, answer: bool = False
) -> tuple[str, bool]:
    """Show where a lab's file differs from the reference answer, in plain words.

    The marked blocks are compared with the reference answer, and the lines outside
    them with the original file, so an edit that drifted outside the markers shows
    too. Each difference names the line in the participant's file and prints their
    lines. Only with answer does it print the reference answer's lines as well, so
    the default report is a hint rather than the solution.

    Args:
        lab: The lab number.
        repo: The checkout whose exercise file is read.
        color: Colour the two versions for a terminal.
        answer: Also print the reference answer's lines inside the marked blocks.

    Returns:
        The report, and whether the file differs from the reference.
    """
    relative_path, blocks = LABS[lab]
    path = repo / relative_path
    missing = missing_file_problem(lab, repo)
    if missing:
        raise ValueError(missing.line)
    expected_path = REPO / solution_path(Path(relative_path))
    yours_source = path.read_text(encoding="utf-8")
    expected_source = shipped_text(solution_path(Path(relative_path)), REPO)
    inside = []
    for start, end, _fixed, _broken in blocks:
        markers = _markers_problem(yours_source, start, end)
        if markers:
            raise ValueError(f"Lab diff rule: in {relative_path}, {markers}.")
        _expected_first, expected = _block_span(
            expected_source, start, end, path=expected_path
        )
        yours_first, yours = _block_span(yours_source, start, end, path=path)
        numbers = list(range(yours_first, yours_first + len(yours)))
        marker_line = yours_source.split(start, 1)[0].count("\n") + 1
        inside.extend(
            _plain_differences(expected, yours, numbers, fallback_line=marker_line)
        )
    expected_outside, _numbers = _outside_markers(expected_source, blocks)
    yours_outside, numbers = _outside_markers(yours_source, blocks)
    outside = _plain_differences(expected_outside, yours_outside, numbers, outside=True)
    if not inside and not outside:
        matches = (
            f"Lab {lab}: {relative_path} matches the reference answer, inside and "
            "outside the markers."
        )
        return matches, False
    report = [
        f"Lab {lab}: where your {relative_path} differs from the reference answer.",
        "Only those lines are shown; nothing was changed."
        if answer
        else "Only those lines are shown, without the answer; nothing was changed.",
    ]
    for where, label, expected_lines, theirs in [*inside, *outside]:
        hidden = label == "Reference answer" and not answer
        versions = [] if hidden else [(label, expected_lines, "32")]
        versions.append(("Your file", theirs, "33"))
        shown = [
            line for _name, lines, _code in versions for line in lines if line.strip()
        ]
        indent = min((len(line) - len(line.lstrip()) for line in shown), default=0)
        report += ["", f"{where}:"]
        for name, lines, code in versions:
            report.append(f"  {name}:" if lines else f"  {name}: (nothing here)")
            report += [_paint(f"      {line[indent:]}", code, color) for line in lines]
    footer = _diff_footer(
        lab, block_differs=bool(inside), outside_differs=bool(outside), answer=answer
    )
    return "\n".join([*report, "", *footer]), True


def _put_back_lab_folder(exercise: Path, repo: Path) -> None:
    """Restore the files a deleted lab folder shipped, other than its exercise.

    The exercise gets its starting code from the caller, never the answer Git holds.
    """
    for relative in shipped_files(exercise.parent, REPO):
        target = repo / relative
        if relative == exercise or target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(shipped_text(relative, REPO), encoding="utf-8")


def _repair_reference_markers(exercise: Path, blocks: tuple[Block, ...]) -> None:
    """Put Git's copy over a solution file whose markers a participant edited away.

    Only a file that no longer reads as the reference is replaced; a solution file
    with its markers intact is left as it is.
    """
    reference = solution_path(exercise)
    if not (REPO / reference).exists():
        return
    source = (REPO / reference).read_text(encoding="utf-8")
    if not all(_markers_intact(source, block.start, block.end) for block in blocks):
        (REPO / reference).write_text(committed_text(reference, REPO), encoding="utf-8")


def set_lab_state(
    lab: int,
    *,
    solved: bool,
    repo: Path = REPO,
) -> Path:
    relative_path, blocks = LABS[lab]
    path = repo / relative_path
    _repair_reference_markers(Path(relative_path), blocks)
    if not path.exists():
        _put_back_lab_folder(Path(relative_path), repo)
    source = path.read_text(encoding="utf-8") if path.exists() else ""
    if not all(_markers_intact(source, start, end) for start, end, _, _ in blocks):
        # A deleted file, or a deleted or repeated marker that hides where the block
        # is, has reset as its way out, so start from the reference file.
        source = shipped_text(solution_path(Path(relative_path)), REPO)
    for start, end, fixed, broken in blocks:
        source = _replace_block(source, start, end, fixed if solved else broken)
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _fuzzy_cte(tokens: list[str], schema: str) -> str | None:
    """Name of the CTE that forwards the four production parameters to search_fuzzy.

    The CTE is shipped code, not the participant's edit, so it is found by its call
    rather than by markers; it must still expose the three result columns.
    """
    call = [
        *_sql_tokens(f"{schema}.search_fuzzy(q, f, fuzzy_limit, fuzzy_threshold)"),
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
        required = {"product_id", "fuzzy_rank", "fuzzy_score"}
        if len(projected) != len(required) or {
            tuple(expression) for expression, _ in projected
        } != {(column,) for column in required}:
            return None
        if any(alias not in {None, expression[0]} for expression, alias in projected):
            return None
    return name


#: What each column of the fuzzy matching branch carries, as a mismatch names it.
_LAB1_COLUMN_ROLES = (
    "product_id",
    "the channel name 'fuzzy', which the rest of the search uses for fuzzy matching",
    "the fuzzy matching position, fuzzy_rank",
    "the fuzzy matching score, fuzzy_score",
    (
        "the RRF contribution of that position, computed the way the other "
        "branches compute theirs"
    ),
)


def _sql_text(tokens: list[str]) -> str:
    text = re.sub(r" ?(\.|::) ?", r"\1", " ".join(tokens))
    text = re.sub(r"(\w) \(", r"\1(", text).replace("( ", "(")
    return re.sub(r" ([),])", r"\1", text)


def _markers_intact(source: str, start: str, end: str) -> bool:
    return (
        source.count(start) == 1
        and source.count(end) == 1
        and source.index(start) < source.index(end)
    )


def _markers_problem(source: str, start: str, end: str) -> str | None:
    """Say which marker line is missing, repeated or out of order, and the way out.

    It names the exact lines and the comment above the block rather than pointing
    at git diff: the checkout commits the repaired file, so git diff would print
    the reference answer.
    """
    if _markers_intact(source, start, end):
        return None
    lab = next(lab for lab, seam in LABS.items() if seam.blocks[0].start == start)
    faults = []
    for marker in (start, end):
        count = source.count(marker)
        if count == 0:
            faults.append(f"the line '{marker}' is missing")
        elif count > 1:
            faults.append(f"the line '{marker}' appears {count} times")
    if not faults:
        faults.append(f"the line '{end}' comes before '{start}'")
    above = shipped_text(solution_path(Path(LABS[lab].exercise)), REPO).split(start, 1)[
        0
    ]
    anchor = above.rstrip().splitlines()[-1].strip()
    return (
        f"{' and '.join(faults)}: your edit goes between the lines '{start}' and "
        f"'{end}', each once and in that order, with the first directly under "
        f"'{anchor}'; put the marker lines back, or run {reset_command(lab)} to put back "
        f"the starting code (it discards your Lab {lab} edits)"
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


def _lab1_column_problem(columns: list[str], qualifiers: set[str]) -> str | None:
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
                output.append(token)
        outputs.append(output)
    if len(outputs) != len(_LAB1_COLUMN_ROLES):
        return (
            f"the branch returns {len(outputs)} columns; every branch returns five: "
            "product ID, channel name, position, score and RRF contribution"
        )
    if outputs[1] == ["'fuzzy'", "::", "text"]:
        outputs[1] = ["'fuzzy'"]
    expected = [
        ["product_id"],
        ["'fuzzy'"],
        ["fuzzy_rank"],
        ["fuzzy_score"],
        _sql_tokens(
            f"{search_schema()}.reciprocal_rank_contribution(fuzzy_rank, rrf_k)"
        ),
    ]
    for number, (found, wanted, role) in enumerate(
        zip(outputs, expected, _LAB1_COLUMN_ROLES, strict=True), start=1
    ):
        if found != wanted:
            return f"column {number} is {_sql_text(found)}; it must be {role}"
    return None


def lab1_contract_problem(source: str, *, schema: str = "mosaic_search") -> str | None:
    """Say how the fuzzy matching branch breaks its data flow, or None when it holds.

    The shipped CTE must forward the four production parameters and expose the
    three result columns; the participant's UNION ALL branch must read it and
    preserve rank, score, channel and unweighted contribution. Column and table
    aliases, qualified columns and either search schema name do not change that
    contract. Production retrieval validation separately proves the behavior.

    Args:
        source: The lab file, or the function definition Aurora runs.
        schema: The schema the shipped CTE calls `search_fuzzy` in.

    Returns:
        The first difference, as a clause a participant can act on, or None.
    """
    ((start, end, _, _),) = LABS[1][1]
    markers = _markers_problem(source, start, end)
    if markers:
        return markers
    name = _fuzzy_cte(_sql_tokens(source), schema)
    if name is None:
        return (
            "the fuzzy matching step above the marked block has changed; undo edits "
            f"outside the marked block ({DIFF} shows them)"
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
    return _lab1_column_problem(columns, qualifiers)


def _lab1_matches_contract(source: str, *, schema: str = "mosaic_search") -> bool:
    return lab1_contract_problem(source, schema=schema) is None


#: What each answer of `scripts/agent_assembly_probe.py` means, as a clause a
#: participant can act on.
_LAB3_PROBE_PROBLEMS = {
    "not_built": AGENT_NOT_BUILT,
    "not_returned": "create_agent must build one Agent and return it",
    "model": "Agent needs model=model, the supplied model",
    "tools": "Agent needs tools=tools, the supplied tools",
    "instructions": (
        "system_prompt must keep the supplied instructions, which hold the tool order "
        "and evidence rules; pass system_prompt=instructions, and put any rule of your "
        'own after them, as instructions + "\\n..."'
    ),
    "hooks": "Agent needs hooks=hooks, the supplied execution hooks",
}


def lab3_contract_problem(source: str) -> str | None:
    """Say which part of the Lab 3 contract `create_agent` misses, or None.

    The participant assembles the supplied model, tools, instructions and hooks.
    Local variable names and a rule added before or after the instructions do
    not change the contract. A separate process bounds bad edits without
    importing module startup code into the lab-status request.

    Args:
        source: The lab file.

    Returns:
        The first difference, as a clause a participant can act on, or None.
    """
    start, end, _, _ = LABS[3][1][0]
    markers = _markers_problem(source, start, end)
    if markers:
        return markers
    try:
        functions = [
            node
            for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef) and node.name == "create_agent"
        ]
    except SyntaxError as error:
        return f"line {error.lineno} is not valid Python: {error.msg}"
    if len(functions) != 1 or functions[0].decorator_list:
        return "agent.py must define create_agent once, without a decorator"
    try:
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
    except (OSError, subprocess.TimeoutExpired):
        return "create_agent did not return within 2 seconds"
    answer = result.stdout.strip()
    if result.returncode == 0 and answer == "agent assembly ready":
        return None
    key = answer.removeprefix("problem: ")
    if key.startswith("raised "):
        return (
            f"create_agent {key} when given the supplied model, tools, instructions "
            "and hooks"
        )
    return _LAB3_PROBE_PROBLEMS.get(key, "create_agent could not be checked")


def _lab3_matches_contract(source: str) -> bool:
    return lab3_contract_problem(source) is None


def lab3_problem(*, repo: Path = REPO) -> str | None:
    """Say why the saved `agent.py` cannot run as the Retrieval agent, or None."""
    if missing_file_problem(3, repo):
        return f"{LABS[3][0]} was deleted; run {reset_command(3)} to put back its starting code"
    return lab3_contract_problem((repo / LABS[3][0]).read_text(encoding="utf-8"))


def lab_source_is_repaired(lab: int, *, repo: Path = REPO) -> bool:
    """Whether the lab's saved source holds the repair; reads the file and writes nothing."""
    relative_path, _ = LABS[lab]
    if missing_file_problem(lab, repo):
        return False
    source = (repo / relative_path).read_text(encoding="utf-8")
    if lab == 1:
        return _lab1_matches_contract(source)
    if lab == 2:
        return _lab2_matches_contract(source)
    if lab == 3:
        return _lab3_matches_contract(source)
    raise ValueError(f"unknown lab: {lab}")


def fault_untouched(lab: int, *, repo: Path = REPO) -> bool:
    """Whether the lab's marked block still holds the exercise's fault, unedited."""
    if missing_file_problem(lab, repo):
        return False
    source = (repo / LABS[lab][0]).read_text(encoding="utf-8")
    try:
        faulted = source
        for start, end, _, broken in LABS[lab][1]:
            faulted = _replace_block(faulted, start, end, broken)
    except ValueError:
        return False
    return faulted == source


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
    "Retrieval agent and SQL tools; deployed source must match before a run is accepted."
)


def _marked_tokens(source: str, lab: int) -> list[str] | None:
    """A lab's marked SQL as tokens.

    PostgreSQL keeps a SQL function's body as written, comments included, and
    apply sends the file as written, so the block Aurora runs can be compared
    with the saved one directly.
    """
    ((start, end, _, _),) = LABS[lab][1]
    if not _markers_intact(source, start, end):
        return None
    return _sql_tokens(source.split(start, 1)[1].split(end, 1)[0])


def _lab_1_database_state(connection: Any, repo: Path) -> LabDatabaseState:
    schema = search_schema()
    signature = LAB1_FUNCTION_SIGNATURE
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
                "Aurora runs a different LAB1_EDIT block from the one saved in "
                f"{path}. Saving changes only the file; applying it updates Aurora."
            ),
        )
    problem = lab1_contract_problem(definition, schema=schema)
    return LabDatabaseState(
        state="applied" if problem is None else "stale",
        detail=(
            f"Aurora runs the LAB1_EDIT block saved in {path}."
            if problem is None
            else f"Aurora runs the LAB1_EDIT block saved in {path}, but {problem}."
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


def read_applied_sql_state(
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

    @property
    def line(self) -> str:
        """The finding and the fix on one line, for a command that has no list to lay out."""
        return f"{self.finding} Next: {self.next_step}"


def source_problem(lab: int, *, repo: Path = REPO) -> LabProblem | None:
    """Say why a SQL lab's saved block is not repaired, or None when it is."""
    path = LABS[lab][0]
    if missing := missing_file_problem(lab, repo):
        return missing
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


def missing_file_problem(lab: int, repo: Path = REPO) -> LabProblem | None:
    """Say that a lab's exercise file was deleted and how to get its starting code back."""
    exercise = LABS[lab].exercise
    if (repo / exercise).exists():
        return None
    return LabProblem(
        f"Lab {lab}: FILE MISSING ({exercise}).",
        f"run {reset_command(lab)} to put back its starting code; your edits to that file "
        "are gone either way.",
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

    if missing := missing_file_problem(lab, repo):
        return missing.line
    record = load_record(lab, repo)
    if record is None and lab in FAULT_AT_ENTRY:
        return f"Lab {lab}: NOT STARTED"
    if record is not None and not record.get("completed_at"):
        return (
            f"Lab {lab}: START INTERRUPTED. Next: run {start_command(lab)} "
            "again; it finishes the missing step and keeps your edits."
        )
    if lab == 3:
        return _lab_3_status(repo)
    return (
        f"Lab {lab}: {'SOLVED' if lab_source_is_repaired(lab, repo=repo) else 'BROKEN'}"
    )


def _lab_3_passed_since(deployed_at: datetime, repo: Path) -> bool:
    """Whether a passing completion was saved after the given deploy."""
    receipt = repo / ".local" / "lab-3" / "exercise-receipt.json"
    try:
        saved = json.loads(receipt.read_text(encoding="utf-8"))
        graded_at = datetime.fromisoformat(saved["graded_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if graded_at.tzinfo is None:
        graded_at = graded_at.replace(tzinfo=UTC)
    return saved.get("verdict") == "PASS" and graded_at > deployed_at


def _lab_3_status(repo: Path) -> str:
    """Lab 3 is solved by a passing run of the participant's deployed agent, not by source."""
    from service.agent_deploys import lab_3_started_at, load_deploys
    from service.participant_commands import ask_setup_command, grade_setup_run_command

    if not lab_source_is_repaired(3, repo=repo):
        return "Lab 3: BROKEN"
    try:
        started = lab_3_started_at(repo)
        deploys = [d for d in load_deploys(repo) if started and d.deployed_at > started]
    except ValueError as error:
        return f"Lab 3: {error}"
    if not deploys:
        return f"Lab 3: REPAIRED, NOT DEPLOYED. Next: deploy with {DEPLOY_AGENT}."
    if _lab_3_passed_since(deploys[-1].deployed_at, repo):
        return "Lab 3: SOLVED"
    return f"Lab 3: DEPLOYED, NOT YET PROVED. Next: {ask_setup_command()}, then {grade_setup_run_command()}"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "advance --lab 1 validates Lab 1 and prepares Lab 2, and advance "
            "--lab 2 validates Lab 2 and prepares Lab 3; "
            "start enters a lab once and keeps your edits on a rerun; reset "
            "discards one lab's edits and restores its starting code; solution "
            "overwrites one lab with the reference repair; finish completes a lab "
            "with its reference answer, checks and hand-off; skip-to starts a later "
            "lab after finishing the earlier ones. To see where your lab "
            f"files differ from the reference, run {DIFF}."
        )
    )
    parser.add_argument(
        "action",
        choices=(
            "start",
            "advance",
            "reset",
            "apply-solution",
            "finish",
            "skip-to",
            "validate",
            "status",
        ),
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


def solution_summary(lab: int, path: Path, *, run_by: str | None = None) -> str:
    """Say what `apply-solution` overwrote and, run by hand, which commands come next."""
    overwrote = (
        f"Lab {lab}: SOLUTION ({path})\n"
        f"This overwrote the marked LAB{lab}_ block in {path} with the reference "
        "answer, so your own edits to that block are gone."
    )
    if run_by:
        return overwrote
    if lab == 3:
        next_step = (
            f"deploy with {DEPLOY_AGENT}, ask Alex's setup request with "
            f"{ask_setup_command()}, then check that run with {grade_setup_run_command()}"
        )
    else:
        next_step = (
            f"apply it with {APPLY_SQL}, then prove it with {proof_steps_text(lab)}"
        )
    return f"{overwrote}\nNext: {next_step}."


def _entered(lab: int) -> bool:
    """True once a lab's start finished; the previous lab's handoff starts it."""
    from scripts.lab_entry import load_record

    record = load_record(lab, REPO)
    return bool(record and record.get("completed_at"))


def _earlier_labs_to_finish(lab: int) -> list[int]:
    """The labs before this one that have not handed off, which it cannot start without."""
    earlier = [number for number in range(1, lab) if not _entered(number + 1)]
    for number in earlier:
        print(
            f"Lab {number} has not handed off yet, so this finishes it first with the "
            "reference answer.",
            flush=True,
        )
    return earlier


def _run_steps(steps: list[str], *, label: str, resume: str) -> int:
    """Run participant commands in order, each with its usual time; stop at the first failure."""
    progress = Progress(label, name="step", commands=True)
    progress.plan([USUAL_SECONDS[step] for step in steps])
    for step in steps:
        # Each command prints its own output, so a step prints lines instead of a redrawn bar.
        progress.begin(step, typical=USUAL_SECONDS[step], done="done", animate=False)
        command = [sys.executable, *shlex.split(step.removeprefix("uv run python "))]
        result = subprocess.run(
            command, cwd=REPO, check=False, env={**os.environ, RUN_BY: label}
        )
        if result.returncode != 0:
            progress.fail()
            print(
                f"\n{label} stopped at: {step}\n"
                f"Next: fix what it names above, then run {resume} again; "
                "the steps before it are safe to repeat."
            )
            return result.returncode
    progress.finish()
    return 0


def finish_lab(lab: int) -> int:
    """Finish a lab with its reference answer, its checks and its hand-off.

    Any earlier lab that has not handed off is finished first, so a participant
    can finish from wherever they are.
    """
    labs = [*_earlier_labs_to_finish(lab), lab]
    steps = [step for number in labs for step in finish_steps(number)]
    code = _run_steps(steps, label=f"Finish Lab {lab}", resume=finish_command(lab))
    if code:
        return code
    if lab == 3:
        print(
            "\nLab 3: the reference Retrieval agent is deployed. Next: ask Alex's "
            f"setup request with {ask_setup_command()}, then check that run with "
            f"{grade_setup_run_command()}."
        )
    else:
        print(f"\nLab {lab}: finished with the reference answer.")
    return 0


def skip_to_lab(lab: int) -> int:
    """Start at a later lab, finishing the earlier ones with their reference answers.

    The last hand-off starts the chosen lab; when nothing earlier needs finishing,
    its own start runs, which keeps any edits already made there.
    """
    earlier = _earlier_labs_to_finish(lab)
    steps = [step for number in earlier for step in finish_steps(number)]
    code = _run_steps(
        steps or [start_command(lab)],
        label=f"Skip to Lab {lab}",
        resume=skip_to_command(lab),
    )
    if code:
        return code
    print(f"\nLab {lab}: ready. Continue with Lab {lab} in the guide.")
    return 0


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
    if args.action == "finish":
        return finish_lab(args.lab)
    if args.action == "skip-to":
        return skip_to_lab(args.lab)
    if args.action == "reset" and args.source_only:
        # Provisioning installs Lab 1's fault before the API exists, then
        # applies it itself. Only the named lab's seam changes.
        assert_workshop_database(args.database_url)
        path = set_lab_state(args.lab, solved=False)
        print(f"Lab {args.lab}: RESET ({path.relative_to(REPO)})")
        return 0
    if args.action in {"start", "advance", "reset"}:
        import psycopg

        from scripts.lab_entry import LabEntryError, advance, restart, start
        from scripts.prove_lab import LabValidationError

        action = {"start": start, "advance": advance, "reset": restart}[args.action]
        try:
            action(args.lab, api_url=args.api_url, dsn=args.database_url)
        except (LabEntryError, LabValidationError) as error:
            raise SystemExit(str(error)) from error
        except ValueError as error:
            # A dataset mismatch is refused before Aurora's functions change.
            raise SystemExit(
                f"{error}\nNothing was applied: Aurora still runs its previous functions."
            ) from error
        except psycopg.Error as error:
            raise database_fault_exit(error, f"{args.action} Lab {args.lab}") from error
        return 0
    if args.action == "apply-solution":
        path = set_lab_state(args.lab, solved=True)
        print(
            solution_summary(
                args.lab, path.relative_to(REPO), run_by=os.environ.get(RUN_BY)
            )
        )
        return 0
    return _validate_command(args.lab, args.database_url)


def _validate_command(lab: int, database_url: str | None, *, repo: Path = REPO) -> int:
    """Check one lab's saved source and, for a SQL lab, the block Aurora runs."""
    if missing := missing_file_problem(lab, repo):
        raise SystemExit(missing.line)
    if lab == 3:
        if not lab_source_is_repaired(3):
            from service.agent_setup import AGENT_STARTER_MESSAGE

            raise SystemExit(AGENT_STARTER_MESSAGE)
        print(
            "Lab 3: source assembled. This checks the file's shape, not your Retrieval agent. "
            f"Next: deploy with {DEPLOY_AGENT}, ask Alex's setup request with "
            f"{ask_setup_command()}, then check that run with {grade_setup_run_command()}."
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
            explain_problems(
                f"Lab {lab}: FAIL", [problem], validate_applied_command(lab)
            )
        )
    print(
        f"Lab {lab}: PASS. {LABS[lab][0]} is repaired and Aurora runs it.\n"
        f"Next: {proof_steps_text(lab)}"
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
            return applied_problem(lab, read_applied_sql_state(lab, connection))
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
        f"({DIFF} shows them), run {APPLY_SQL}, then run the same command again. "
        "Otherwise copy this message and the command you ran to your facilitator."
    )


def assert_workshop_database(database_url: str | None) -> None:
    """Exit unless `database_url` is the named workshop database with the Mosaic catalog.

    Reads only (one identity query); guards the destructive exercise reset.
    """
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
                f"to_regclass('{search_schema()}.product_listing_view')::text AS catalog"
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
