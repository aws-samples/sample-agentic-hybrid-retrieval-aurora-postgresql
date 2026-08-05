#!/usr/bin/env python3
"""G-34 - prove pre-execution readiness cannot read execution evidence.

The row-level A5 tests prove that one successful execution does not rewrite one
proposal's pre-execution verdict. This gate proves the stronger structural
claim: the code that derives ``pre_execution_eligible`` cannot reach
``proof.action_executions`` directly, through a helper, through dynamic SQL, or
through a value laundered into the returned expression.

Read-only: catalog SELECTs plus one contradiction scan over existing proposals.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    BLOCKED,
    FAIL,
    PASS,
    finish,
    main_guard,
    print_header,
    read_env_value,
    redact_dsn,
)

GATE_ID = "G-34"
TITLE = "Retroactive-safety separation in the autonomy verdict"

SUBJECT_SIGNATURE = "proof.autonomy_readiness(uuid)"
PRE_ACCUMULATOR = "v_pre"

# Hardcoded deliberately. Deriving these from the table under test would let a
# dropped or renamed table produce an empty token list and a vacuous pass.
EXECUTION_TOKENS = (
    "action_executions",
    "v_exec",
    "fingerprint_matches",
    "observed_fingerprint",
    "observed_index_definition",
    "wave_b_ingest_id",
    "wave_b_capture_id",
)

IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
ELIGIBILITY_ALLOWED = frozenset(
    {
        PRE_ACCUMULATOR,
        "array_length",
        "cardinality",
        "coalesce",
        "is",
        "null",
        "not",
        "and",
        "or",
        "true",
        "false",
    }
)

SUBJECT_FUNCTION = """
SELECT p.oid, n.nspname, p.proname,
       pg_get_function_identity_arguments(p.oid), p.prosrc
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE p.oid = to_regprocedure(%s)
"""

ALL_FUNCTIONS = """
SELECT p.oid, n.nspname, p.proname,
       pg_get_function_identity_arguments(p.oid), p.prosrc
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND p.prokind = 'f'
"""

CONTRADICTION_SCAN = """
SELECT p.proposal_id,
       (btrim(coalesce(p.rollback_sql, '')) = ''
        AND btrim(coalesce(p.rollback_guidance, '')) = '') AS no_rollback,
       (jsonb_array_length(p.preconditions) = 0) AS no_preconditions,
       (p.statement_timeout IS NULL OR p.lock_timeout IS NULL) AS unbounded
FROM proof.action_proposals p
CROSS JOIN proof.autonomy_readiness(p.proposal_id) v
WHERE v.pre_execution_eligible
  AND ((btrim(coalesce(p.rollback_sql, '')) = ''
        AND btrim(coalesce(p.rollback_guidance, '')) = '')
       OR jsonb_array_length(p.preconditions) = 0
       OR p.statement_timeout IS NULL
       OR p.lock_timeout IS NULL)
"""


@dataclass(frozen=True)
class FunctionSource:
    oid: int
    schema: str
    name: str
    arguments: str
    source: str

    @property
    def label(self) -> str:
        return f"{self.schema}.{self.name}({self.arguments})"


@dataclass(frozen=True)
class LexedSource:
    """Two same-length views of one PL/pgSQL body.

    ``code`` blanks comments and string literals. ``with_literals`` blanks only
    comments. Keeping both views the same length avoids the offset bug caused by
    applying a cut measured on shortened text to the original function body.
    """

    code: str
    with_literals: str


def _blank_span(chars: list[str], start: int, end: int) -> None:
    for index in range(start, end):
        if chars[index] != "\n":
            chars[index] = " "


def lex_plpgsql(source: str) -> LexedSource:
    """Blank comments and literals without confusing one for the other."""
    code = list(source)
    with_literals = list(source)
    index = 0
    length = len(source)

    while index < length:
        if source.startswith("--", index):
            end = source.find("\n", index + 2)
            end = length if end < 0 else end
            _blank_span(code, index, end)
            _blank_span(with_literals, index, end)
            index = end
            continue

        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            end = length if end < 0 else end + 2
            _blank_span(code, index, end)
            _blank_span(with_literals, index, end)
            index = end
            continue

        if source[index] == "'":
            end = index + 1
            while end < length:
                if source[end] != "'":
                    end += 1
                    continue
                if end + 1 < length and source[end + 1] == "'":
                    end += 2
                    continue
                end += 1
                break
            _blank_span(code, index, end)
            index = end
            continue

        if source[index] == "$":
            delimiter = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", source[index:])
            if delimiter:
                marker = delimiter.group(0)
                end = source.find(marker, index + len(marker))
                end = length if end < 0 else end + len(marker)
                _blank_span(code, index, end)
                index = end
                continue

        if source[index] == '"':
            # Quoted identifiers are code. Skip over doubled quotes so comment
            # markers or apostrophes inside the identifier are not re-tokenized.
            end = index + 1
            while end < length:
                if source[end] != '"':
                    end += 1
                    continue
                if end + 1 < length and source[end + 1] == '"':
                    end += 2
                    continue
                end += 1
                break
            index = end
            continue

        index += 1

    return LexedSource("".join(code), "".join(with_literals))


def executable_body(source: str) -> str:
    """Return the function text after the PL/pgSQL ``BEGIN``."""
    lexed = lex_plpgsql(source)
    match = re.search(r"\bBEGIN\b", lexed.code, re.I)
    return source if match is None else source[match.end():]


def split_top_level(select_list: str) -> list[str]:
    """Split a SELECT list only on commas outside parentheses."""
    columns: list[str] = []
    current: list[str] = []
    depth = 0
    for char in select_list:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            columns.append("".join(current))
            current = []
        else:
            current.append(char)
    columns.append("".join(current))
    return columns


def token_hits(text: str) -> list[str]:
    return [
        token
        for token in EXECUTION_TOKENS
        if re.search(rf"\b{re.escape(token)}\b", text, re.I)
    ]


def pre_region_end(code: str) -> int:
    """Return the end of the final ``v_pre := ...;`` statement."""
    assignments = list(
        re.finditer(rf"\b{re.escape(PRE_ACCUMULATOR)}\s*:=", code, re.I)
    )
    if not assignments:
        return len(code)

    depth = 0
    for index in range(assignments[-1].end(), len(code)):
        char = code[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == ";" and depth <= 0:
            return index + 1
    return len(code)


def called_functions(
    code: str, catalog: tuple[FunctionSource, ...]
) -> set[FunctionSource]:
    """Return every overload whose name appears as a function call.

    Over-approximating overloads can produce a visible false failure. Inspecting
    one arbitrary overload can produce a silent false pass, so every overload is
    the correct failure direction for this structural gate.
    """
    return {
        function
        for function in catalog
        if re.search(
            rf"\b(?:[A-Za-z_][A-Za-z0-9_]*\s*\.\s*)?"
            rf"{re.escape(function.name)}\s*\(",
            code,
            re.I,
        )
    }


def _dynamic_sql_problem(label: str, code: str) -> str | None:
    if re.search(r"\bEXECUTE\b", code, re.I):
        return (
            f"{label} builds dynamic SQL; this gate cannot prove the query text "
            "does not read execution evidence"
        )
    return None


def _literal_problem(label: str, code: str, with_literals: str) -> str | None:
    code_hits = set(token_hits(code))
    extra = [token for token in token_hits(with_literals) if token not in code_hits]
    if extra:
        return f"a string literal in {label} names execution evidence: {', '.join(extra)}"
    return None


def inspect_static(
    subject: FunctionSource,
    catalog: tuple[FunctionSource, ...],
) -> tuple[list[str], int, list[str]]:
    """Inspect the subject and every helper reachable from eligibility."""
    problems: list[str] = []
    body = executable_body(subject.source)
    lexed = lex_plpgsql(body)
    assignments = list(
        re.finditer(rf"\b{re.escape(PRE_ACCUMULATOR)}\s*:=", lexed.code, re.I)
    )
    if not assignments:
        problems.append(
            f"no {PRE_ACCUMULATOR} assignment found; the pre-execution region "
            "cannot be located"
        )

    cut = pre_region_end(lexed.code)
    pre_code = lexed.code[:cut]
    pre_with_literals = lexed.with_literals[:cut]
    hits = token_hits(pre_code)
    if hits:
        problems.append(
            "the pre-execution region reads execution evidence: " + ", ".join(hits)
        )

    for problem in (
        _dynamic_sql_problem(subject.label, lexed.code),
        _literal_problem("the pre-execution region", pre_code, pre_with_literals),
    ):
        if problem:
            problems.append(problem)

    returned = re.search(r"RETURN\s+QUERY\s+SELECT(.*?);", lexed.code, re.I | re.S)
    first = ""
    if returned is None:
        problems.append(
            "no `RETURN QUERY SELECT ...;` found; the eligibility expression "
            "cannot be verified"
        )
    else:
        first = split_top_level(returned.group(1))[0]
        if PRE_ACCUMULATOR not in first.lower():
            problems.append(
                f"the first returned column is not derived from {PRE_ACCUMULATOR}: "
                f"{first.strip()!r}"
            )
        returned_hits = token_hits(first)
        if returned_hits:
            problems.append(
                "the returned eligibility expression reads execution evidence: "
                + ", ".join(returned_hits)
            )
        strays = sorted(
            {
                match.group(0).lower()
                for match in IDENTIFIER.finditer(first)
                if match.group(0).lower() not in ELIGIBILITY_ALLOWED
            }
        )
        if strays:
            problems.append(
                "the returned eligibility expression names non-allowlisted "
                "constructs that could launder an execution read: "
                + ", ".join(strays)
            )

    checked: set[FunctionSource] = set()
    frontier = called_functions(pre_code, catalog) | called_functions(first, catalog)
    while frontier:
        function = frontier.pop()
        if function == subject or function in checked:
            continue
        checked.add(function)
        inner = lex_plpgsql(executable_body(function.source))
        inner_hits = token_hits(inner.code)
        if inner_hits:
            problems.append(
                f"{function.label}, reachable from eligibility, reads execution "
                "evidence: " + ", ".join(inner_hits)
            )
        for problem in (
            _dynamic_sql_problem(function.label, inner.code),
            _literal_problem(function.label, inner.code, inner.with_literals),
        ):
            if problem:
                problems.append(problem)
        frontier |= called_functions(inner.code, catalog)

    return problems, len(assignments), sorted(item.label for item in checked)


def _load_catalog(conn) -> tuple[FunctionSource | None, tuple[FunctionSource, ...]]:
    subject_row = conn.execute(SUBJECT_FUNCTION, (SUBJECT_SIGNATURE,)).fetchone()
    subject = FunctionSource(*subject_row) if subject_row is not None else None
    catalog = tuple(FunctionSource(*row) for row in conn.execute(ALL_FUNCTIONS))
    return subject, catalog


def run() -> int:
    print_header(GATE_ID, TITLE)
    dsn = read_env_value("DATABASE_URL")
    if not dsn:
        return finish(GATE_ID, BLOCKED, "DATABASE_URL is not configured")
    print(f"  database: {redact_dsn(dsn)}")

    try:
        import psycopg
    except ModuleNotFoundError:
        return finish(GATE_ID, BLOCKED, "psycopg is not installed")

    with psycopg.connect(dsn, autocommit=True) as conn:
        subject, catalog = _load_catalog(conn)
        if subject is None:
            return finish(
                GATE_ID,
                BLOCKED,
                "proof.autonomy_readiness(uuid) does not exist; apply "
                "sql/13_supervised_execution.sql",
            )

        problems, assignment_count, helpers = inspect_static(subject, catalog)
        for row in conn.execute(CONTRADICTION_SCAN):
            problems.append(
                f"proposal {row[0]} is reported eligible while its row "
                f"contradicts it (no_rollback={row[1]}, "
                f"no_preconditions={row[2]}, unbounded_timeout={row[3]})"
            )

    for problem in problems:
        print(f"  DEFECT: {problem}")
    if problems:
        return finish(GATE_ID, FAIL, f"{len(problems)} retroactive-safety defect(s)")

    return finish(
        GATE_ID,
        PASS,
        f"pre-execution region clean ({assignment_count} {PRE_ACCUMULATOR} "
        f"assignments, helpers checked: {helpers or 'none'}); "
        "contradiction scan clean",
    )


if __name__ == "__main__":
    main_guard(run)
