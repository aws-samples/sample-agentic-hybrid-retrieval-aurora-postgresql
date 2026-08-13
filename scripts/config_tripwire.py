#!/usr/bin/env python3
"""Fail the build if any file other than the yaml declares a retrieval number.

`db/config/retrieval.yaml` is the single source for candidate limits, fusion `k`,
per-arm weights, and the trigram threshold. Unit C removed the three live copies
that agreed by luck and the dead fourth that disagreed (LOSS-3). This check
prevents the fifth.

Two rules, because "one source" needs both halves:

1. **No second declaration.** A numeric literal assigned to a limit-, `k`-,
   weight- or threshold-shaped name outside the yaml is a failure. Environment
   variable reads are not declarations — they are the documented override path —
   and neither are bound constants, which are ranges rather than values.

2. **SQL defaults must AGREE.** A PostgreSQL function signature cannot read a
   file, so `db/sql/*.sql` parameter defaults are exempt from rule 1. They are
   **not** exempt from agreeing: every exempted default is asserted equal to its
   yaml counterpart. The exemption is a monitored seam, not a blind spot — an
   unmonitored exemption is how a "single source" acquires a second copy that
   nobody is looking for.

Usage
-----
    uv run python scripts/config_tripwire.py            # both rules
    uv run python scripts/config_tripwire.py --explain  # also list what was scanned
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.retrieval_profile import (  # noqa: E402  (path set above)
    RETRIEVAL_YAML,
    explain,
    load_profile,
)

# Surfaces scanned for a second declaration. `db/sql/` is scanned too: its
# parameter defaults are exempt from rule 1 but everything else in it is not.
SCAN_ROOTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("service", (".py",)),
    ("scripts", (".py",)),
    ("config", (".json", ".txt")),
    ("db/sql", (".sql",)),
    ("db/config", (".yaml", ".yml", ".json")),
    ("ui/src", (".ts", ".tsx")),
)

# Names that hold a retrieval number. Matched as whole identifiers, so
# `weight_g` and `page_limit` do not trip the check.
NUMBER_NAMES = (
    r"fts_limit",
    r"lexical_(?:candidate_)?limit",
    r"trigram_(?:candidate_)?limit",
    r"semantic_(?:candidate_)?limit",
    r"fused_limit",
    r"rerank_(?:candidate_)?limit",
    r"candidate_limit",
    r"rrf_k",
    r"weight_(?:lexical|semantic|trigram)",
    r"trigram_(?:similarity_)?threshold",
    r"minimum_similarity",
    r"ef_search",
    r"ef_construction",
    r"max_scan_tuples",
    r"scan_mem_multiplier",
)

# `name = 123`, `name: 123`, `"name": 123`, `name=0.5` — an assignment of a
# numeric literal to one of the names above.
DECLARATION = re.compile(
    r"""(?P<prefix>["'\s(,{]|^)
        (?P<name>"""
    + "|".join(NUMBER_NAMES)
    + r""")
        ["']?\s*(?:=|:)\s*
        (?P<value>-?\d+(?:\.\d+)?)
        (?![\d.])""",
    re.VERBOSE,
)

# A JS/TS fallback that supplies a retrieval number when the API omits one:
# `diagnostics?.rrf_k ?? 60`, `profile.fts_limit || 120`. Structurally a
# declaration — it decides what the participant sees — so rule 1 covers it.
FALLBACK = re.compile(
    r"(?P<name>" + "|".join(NUMBER_NAMES) + r")"
    r"\s*(?:\?\?|\|\|)\s*(?P<value>-?\d+(?:\.\d+)?)"
)

# Lines that name a number without declaring one.
ALLOWED_LINE = re.compile(
    r"""(?:
        os\.getenv | os\.environ            # the documented override path
      | ge\s*=|le\s*=|gt\s*=|lt\s*=         # pydantic bounds: ranges, not values
      | Bound\(                             # the bounds table in retrieval_profile
      | _yaml_default | load_profile        # yaml-sourced defaults
      | RAISE\s+EXCEPTION                   # SQL range guards
      | [<>]=?\s*\d                         # SQL/py comparisons in guards
    )""",
    re.VERBOSE,
)


# SQL parameter defaults exempt from rule 1, each pinned to a profile field that
# must equal it. `None` means "no yaml counterpart" and requires a stated reason.
@dataclass(frozen=True)
class SqlDefault:
    """One exempted SQL parameter default and the yaml value it must match."""

    file: str
    function: str
    parameter: str
    profile_field: str | None
    reason: str = ""


# `CREATE INDEX ... WITH (m = ..., ef_construction = ...)` build parameters.
# Exempt from rule 1 for the same reason as function defaults — DDL cannot read a
# file — and monitored the same way: each is pinned to a yaml field, or carries a
# stated reason for having none.
@dataclass(frozen=True)
class IndexParameter:
    """One exempted index build parameter and the yaml value it must match."""

    file: str
    index: str
    parameter: str
    profile_field: str | None
    reason: str = ""


INDEX_PARAMETERS: tuple[IndexParameter, ...] = (
    IndexParameter(
        "08_indexes_concurrent.sql",
        "product_document_embedding_hnsw_cosine_idx",
        "ef_construction",
        "hnsw_ef_construction",
    ),
)


SQL_DEFAULTS: tuple[SqlDefault, ...] = (
    SqlDefault("09_search_functions.sql", "search_fts", "candidate_limit", "fts_limit"),
    SqlDefault(
        "09_search_functions.sql", "search_trigram", "candidate_limit", "trigram_limit"
    ),
    SqlDefault(
        "09_search_functions.sql",
        "search_trigram",
        "minimum_similarity",
        "trigram_threshold",
    ),
    SqlDefault(
        "09_search_functions.sql", "search_vector", "candidate_limit", "semantic_limit"
    ),
    SqlDefault("09_search_functions.sql", "search_hybrid_rrf", "rrf_k", "rrf_k"),
    SqlDefault(
        "09_search_functions.sql", "search_hybrid_rrf", "fts_limit", "fts_limit"
    ),
    SqlDefault(
        "09_search_functions.sql", "search_hybrid_rrf", "trigram_limit", "trigram_limit"
    ),
    SqlDefault(
        "09_search_functions.sql",
        "search_hybrid_rrf",
        "semantic_limit",
        "semantic_limit",
    ),
    SqlDefault(
        "09_search_functions.sql", "search_hybrid_rrf", "result_limit", "fused_limit"
    ),
    SqlDefault(
        "09_search_functions.sql",
        "search_hybrid_rrf",
        "trigram_threshold",
        "trigram_threshold",
    ),
    # Unit D's weighted comparison function. Every arm cap and fusion input is
    # pinned to the same yaml field as its unweighted twin, which is what makes
    # "identical candidate lists" checkable at the config layer rather than only
    # at request time.
    SqlDefault(
        "09_search_functions.sql", "search_hybrid_rrf_weighted", "rrf_k", "rrf_k"
    ),
    SqlDefault(
        "09_search_functions.sql",
        "search_hybrid_rrf_weighted",
        "fts_limit",
        "fts_limit",
    ),
    SqlDefault(
        "09_search_functions.sql",
        "search_hybrid_rrf_weighted",
        "trigram_limit",
        "trigram_limit",
    ),
    SqlDefault(
        "09_search_functions.sql",
        "search_hybrid_rrf_weighted",
        "semantic_limit",
        "semantic_limit",
    ),
    SqlDefault(
        "09_search_functions.sql",
        "search_hybrid_rrf_weighted",
        "trigram_threshold",
        "trigram_threshold",
    ),
    SqlDefault(
        "09_search_functions.sql",
        "search_hybrid_rrf_weighted",
        "weight_lexical",
        "weight_lexical",
    ),
    SqlDefault(
        "09_search_functions.sql",
        "search_hybrid_rrf_weighted",
        "weight_semantic",
        "weight_semantic",
    ),
    SqlDefault(
        "09_search_functions.sql",
        "search_hybrid_rrf_weighted",
        "weight_trigram",
        "weight_trigram",
    ),
    SqlDefault(
        "09_search_functions.sql", "configure_hnsw", "p_ef_search", "hnsw_ef_search"
    ),
    SqlDefault(
        "09_search_functions.sql",
        "configure_hnsw",
        "p_max_scan_tuples",
        "hnsw_max_scan_tuples",
    ),
    SqlDefault(
        "09_search_functions.sql",
        "configure_hnsw",
        "p_scan_mem_multiplier",
        "hnsw_scan_mem_multiplier",
    ),
    SqlDefault(
        "09_search_functions.sql",
        "search_product_evidence",
        "result_limit",
        None,
        reason=(
            "evidence excerpt count, not a retrieval candidate limit; it has no "
            "yaml counterpart because it does not affect candidate generation"
        ),
    ),
)


class Report:
    """Collects every violation, so one run names all of them."""

    def __init__(self) -> None:
        self.failures: list[str] = []
        self.scanned: list[str] = []

    def fail(self, rule: str, detail: str) -> None:
        self.failures.append(f"{rule}: {detail}")


def check_exemptions_complete(report: Report, *, repo: Path = REPO) -> None:
    """Rule 3 — every SQL parameter default with a retrieval name is enumerated.

    Rule 1 cannot see these. `weight_lexical real DEFAULT 0.30` has no `=` or `:`,
    so the assignment-shaped pattern skips it, and rule 2 only checks defaults
    that are already in `SQL_DEFAULTS`. Together those leave a hole: adding a new
    default is silently unmonitored, and a "monitored seam" that only monitors
    what someone remembered to list is not monitored.

    Measured: Unit D added 13 defaults across two functions — including three
    fusion weights — and the tripwire stayed green with none of them pinned.
    """
    exempt = {(d.function, d.parameter) for d in SQL_DEFAULTS}
    pattern = re.compile(
        r"\b(?P<name>" + "|".join(NUMBER_NAMES) + r")\s+[\w()]+"
        r"(?:\s*\(\d+\))?\s+DEFAULT\s+(?P<value>-?\d+(?:\.\d+)?)",
        re.IGNORECASE,
    )
    for path in sorted((repo / "db" / "sql").glob("*.sql")):
        source = path.read_text(encoding="utf-8")
        for signature in re.finditer(
            r"FUNCTION\s+[\w.]*?(?P<function>\w+)\s*\((?P<body>.*?)\)\s*RETURNS",
            source,
            re.IGNORECASE | re.DOTALL,
        ):
            function = signature.group("function")
            for found in pattern.finditer(signature.group("body")):
                name = found.group("name")
                if (function, name) in exempt:
                    continue
                report.fail(
                    f"C1c {path.name}:{function}.{name}",
                    explain(
                        f"SQL parameter default {name}={found.group('value')} that "
                        f"no SQL_DEFAULTS entry pins",
                        f"add SqlDefault({path.name!r}, {function!r}, {name!r}, "
                        f"<profile_field>) to scripts/config_tripwire.py so the "
                        f"default is asserted equal to the yaml, or pass None with "
                        f"a written reason if it has no yaml counterpart",
                    ),
                )


def scan_declarations(report: Report, *, repo: Path = REPO) -> None:
    """Rule 1 — no file but the yaml declares a retrieval number.

    The yaml is identified by its path *relative to the tree being scanned*, not
    by the module-level constant, so a test fixture's copy is recognised as the
    single source rather than reported as a second one.
    """
    single_source = (repo / RETRIEVAL_YAML.relative_to(REPO)).resolve()
    for root, suffixes in SCAN_ROOTS:
        base = repo / root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.suffix not in suffixes or not path.is_file():
                continue
            if path.resolve() == single_source:
                continue
            relative = path.relative_to(repo).as_posix()
            report.scanned.append(relative)
            _scan_file(path, relative, report)


def _scan_file(path: Path, relative: str, report: Report) -> None:
    is_sql = path.suffix == ".sql"
    exempt = {(d.function, d.parameter) for d in SQL_DEFAULTS}
    exempt |= {(p.index, p.parameter) for p in INDEX_PARAMETERS}
    function = ""
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = _strip_comment(raw, is_sql)
        if not line.strip():
            continue
        if is_sql:
            # `function` doubles as "the SQL object whose body we are inside",
            # so an index's build parameters resolve against its index name the
            # same way a function's defaults resolve against its function name.
            match = re.search(r"FUNCTION\s+[\w.]*?(\w+)\s*\(", line, re.IGNORECASE)
            if match:
                function = match.group(1)
            index = re.search(
                r"CREATE\s+INDEX(?:\s+CONCURRENTLY)?"
                r"(?:\s+IF\s+NOT\s+EXISTS)?\s+(\w+)",
                line,
                re.IGNORECASE,
            )
            if index:
                function = index.group(1)
        if ALLOWED_LINE.search(line):
            continue
        for pattern in (DECLARATION, FALLBACK):
            for found in pattern.finditer(line):
                name = found.group("name")
                if is_sql and (function, name) in exempt:
                    continue
                report.fail(
                    f"C1 {relative}:{number}",
                    explain(
                        f"{name} declared as {found.group('value')}",
                        f"delete it and read the value from "
                        f"{RETRIEVAL_YAML.relative_to(REPO).as_posix()} "
                        f"(scripts/retrieval_profile.load_profile), or expose it "
                        f"through the API rather than defaulting locally",
                    ),
                )


def _strip_comment(line: str, is_sql: bool) -> str:
    """Drop trailing comments so prose about a number is not a declaration.

    Comments are where these numbers get explained, and an explanation is not a
    declaration. Naive but sufficient: no scanned file puts a `#` or `--` inside
    a string on a line that also assigns a retrieval number.
    """
    marker = "--" if is_sql else "#"
    text = line.split(marker, 1)[0]
    return text.split("//", 1)[0] if not is_sql else text


def check_sql_agreement(report: Report, *, repo: Path = REPO) -> None:
    """Rule 2 — every exempted SQL default equals its yaml value."""
    profile = load_profile()
    for entry in SQL_DEFAULTS:
        path = repo / "db" / "sql" / entry.file
        if not path.exists():
            report.fail(
                "C1b missing file",
                explain(
                    f"{entry.file} is absent but listed as an exemption",
                    "remove the SQL_DEFAULTS entry, or restore the file",
                ),
            )
            continue
        actual = _sql_default(path.read_text(encoding="utf-8"), entry)
        if actual is None:
            report.fail(
                f"C1b {entry.function}.{entry.parameter}",
                explain(
                    "no DEFAULT found for this parameter",
                    "the exemption list is stale: update SQL_DEFAULTS to match "
                    "the function signature, or restore the default",
                ),
            )
            continue
        if entry.profile_field is None:
            report.scanned.append(
                f"{entry.function}.{entry.parameter} (exempt: {entry.reason})"
            )
            continue
        expected = getattr(profile, entry.profile_field)
        if float(actual) != float(expected):
            report.fail(
                f"C1b {entry.function}.{entry.parameter}",
                explain(
                    f"SQL default {actual} but "
                    f"{RETRIEVAL_YAML.name} yields {expected} for "
                    f"{entry.profile_field!r}",
                    f"set the SQL default to {expected}, or change the yaml — "
                    f"they must agree, because a caller that omits the argument "
                    f"gets the SQL value and a caller that passes one gets the "
                    f"yaml value",
                ),
            )
        else:
            report.scanned.append(
                f"{entry.function}.{entry.parameter} == {entry.profile_field}"
            )


def check_index_agreement(report: Report, *, repo: Path = REPO) -> None:
    """Rule 2, second half — every exempted index build parameter agrees."""
    profile = load_profile()
    for entry in INDEX_PARAMETERS:
        path = repo / "db" / "sql" / entry.file
        if not path.exists():
            report.fail(
                "C1b missing file",
                explain(
                    f"{entry.file} is absent but listed as an exemption",
                    "remove the INDEX_PARAMETERS entry, or restore the file",
                ),
            )
            continue
        actual = _index_parameter(path.read_text(encoding="utf-8"), entry)
        if actual is None:
            report.fail(
                f"C1b {entry.index}.{entry.parameter}",
                explain(
                    "no build parameter found on this index",
                    "the exemption list is stale: update INDEX_PARAMETERS to "
                    "match the DDL, or restore the parameter",
                ),
            )
            continue
        if entry.profile_field is None:
            report.scanned.append(
                f"{entry.index}.{entry.parameter} (exempt: {entry.reason})"
            )
            continue
        expected = getattr(profile, entry.profile_field)
        if float(actual) != float(expected):
            report.fail(
                f"C1b {entry.index}.{entry.parameter}",
                explain(
                    f"index built with {entry.parameter}={actual} but "
                    f"{RETRIEVAL_YAML.name} yields {expected} for "
                    f"{entry.profile_field!r}",
                    f"set the index parameter to {expected}, or change the yaml; "
                    f"an index built at one value while the profile advertises "
                    f"another makes the recall the workshop measures untraceable "
                    f"to the configuration it displays",
                ),
            )
        else:
            report.scanned.append(
                f"{entry.index}.{entry.parameter} == {entry.profile_field}"
            )


def _index_parameter(source: str, entry: IndexParameter) -> str | None:
    """The literal value of one build parameter on one index."""
    statement = re.search(
        rf"CREATE\s+INDEX(?:\s+CONCURRENTLY)?(?:\s+IF\s+NOT\s+EXISTS)?\s+"
        rf"{re.escape(entry.index)}\b(?P<body>.*?);",
        source,
        re.IGNORECASE | re.DOTALL,
    )
    if not statement:
        return None
    found = re.search(
        rf"\b{re.escape(entry.parameter)}\s*=\s*(?P<value>-?\d+(?:\.\d+)?)",
        statement.group("body"),
        re.IGNORECASE,
    )
    return found.group("value") if found else None


def _sql_default(source: str, entry: SqlDefault) -> str | None:
    """The literal default of one parameter in one function."""
    signature = re.search(
        rf"FUNCTION\s+[\w.]*{re.escape(entry.function)}\s*\((?P<body>.*?)\)\s*RETURNS",
        source,
        re.IGNORECASE | re.DOTALL,
    )
    if not signature:
        return None
    found = re.search(
        rf"\b{re.escape(entry.parameter)}\s+[\w()]+(?:\s*\(\d+\))?\s+"
        rf"DEFAULT\s+(?P<value>-?\d+(?:\.\d+)?)",
        signature.group("body"),
        re.IGNORECASE,
    )
    return found.group("value") if found else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--explain",
        action="store_true",
        help="List every file scanned and every exemption checked",
    )
    args = parser.parse_args()

    report = Report()
    scan_declarations(report)
    check_exemptions_complete(report)
    check_sql_agreement(report)
    check_index_agreement(report)

    pinned = len(SQL_DEFAULTS) + len(INDEX_PARAMETERS)
    print(
        f"config tripwire: {len(report.scanned)} file(s)/exemption(s) checked, "
        f"{pinned} SQL default(s)/index parameter(s) pinned"
    )
    if args.explain:
        for item in report.scanned:
            print(f"  scanned {item}")
    if report.failures:
        print(f"\n{len(report.failures)} violation(s):", file=sys.stderr)
        for failure in report.failures:
            print(f"  FAIL {failure}", file=sys.stderr)
        return 1
    print("retrieval numbers are declared in exactly one place")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
