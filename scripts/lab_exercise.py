#!/usr/bin/env python3
"""Grade the query or test a participant writes in each lab.

Every check compares the participant's work with an answer this script computes
independently, in the same read-only transaction. It never repairs a lab, never
writes to Aurora, and never shows the reference answer.

- Lab 1: a recall query for the filtered vector search, graded with the planner's
  own plan and again with the HNSW index forced.
- Lab 2: reciprocal rank fusion written in SQL over the three installed search
  functions, graded at the configured ``k`` and at four other values.
- Lab 3: pytest tests for ``register_evidence``, graded against the reference
  repair and four faulty variants that the tests must reject.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts import lab_state

SCORE_TOLERANCE = 1e-9
LAB2_K_TRIALS = (1, 10, 30, 120)
DEFAULT_WORK = {
    1: Path(".local/lab-1/recall.sql"),
    2: Path(".local/lab-2/rrf.sql"),
    3: Path("labs/lab3/test_evidence_contract.py"),
}
LAB1_COLUMNS = ("approximate_rows", "exact_rows", "recall")
LAB2_COLUMNS = ("product_id", "rrf_score", "combined_position")
LAB3_MINIMUM_TESTS = 3
LAB3_VARIANTS: dict[str, str] = {
    "no registration (the broken seam)": lab_state.LAB3_BROKEN_STATE,
    "records kept, product list never written": """    for item in evidence:
        state["evidence"][item.evidence_id] = item""",
    "duplicate IDs on a repeated call": """    for item in evidence:
        state["evidence"][item.evidence_id] = item
        state["evidence_by_product"].setdefault(product_id, []).append(
            item.evidence_id
        )""",
    "a later call replaces earlier IDs": """    state["evidence_by_product"][product_id] = []
    for item in evidence:
        state["evidence"][item.evidence_id] = item
        state["evidence_by_product"][product_id].append(item.evidence_id)""",
}


class ExerciseError(RuntimeError):
    """The participant's work cannot be graded as written."""


def load_context(lab: int) -> dict[str, str]:
    """Read the values ``lab_terminal.py run`` saved for this lab's psql session."""
    path = REPO / f".local/lab-{lab}/context.json"
    if not path.exists():
        raise ExerciseError(
            f"no saved context at {path.relative_to(REPO)}; run "
            f"`uv run python scripts/lab_terminal.py run --lab {lab} --phase before` first"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _quoted(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def interpolate(sql: str, values: dict[str, str]) -> str:
    """Expand psql variables the way psql does, outside literals and comments.

    ``:'name'`` becomes a quoted literal and ``:name`` the raw value. ``::``
    casts, quoted strings, quoted identifiers, and ``--`` comments are left
    alone. The result must be exactly one statement.
    """
    token = re.compile(
        r"(?P<skip>'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|--[^\n]*|::)"
        r"|:'(?P<quoted>[a-z_][a-z0-9_]*)'"
        r"|:(?P<raw>[a-z_][a-z0-9_]*)"
        r"|(?P<semicolon>;)"
        r"|(?P<meta>\\\w+)"
    )
    pieces: list[str] = []
    position = 0
    for match in token.finditer(sql):
        pieces.append(sql[position : match.start()])
        position = match.end()
        name = match.group("quoted") or match.group("raw")
        if match.group("skip") is not None:
            pieces.append(match.group("skip"))
        elif match.group("semicolon") is not None:
            if sql[position:].strip() and not _only_comments(sql[position:]):
                raise ExerciseError(
                    "the file holds more than one statement; keep one SELECT "
                    "(CTEs are fine) and run any SET commands in psql, not here"
                )
        elif match.group("meta") is not None:
            raise ExerciseError(
                f"psql command {match.group('meta')!r} found; the file must be "
                "plain SQL, because the grader runs it without psql"
            )
        elif name not in values:
            raise ExerciseError(
                f"unknown variable :{name}; available: " + ", ".join(sorted(values))
            )
        else:
            value = values[name]
            pieces.append(_quoted(value) if match.group("quoted") else value)
    pieces.append(sql[position:])
    statement = "".join(pieces).strip()
    if not re.match(r"(?is)^\s*(?:--[^\n]*\n\s*)*(select|with)\b", statement):
        raise ExerciseError("the statement must be a single SELECT or WITH query")
    return statement


def _only_comments(text: str) -> bool:
    return all(
        not line.strip() or line.strip().startswith("--") for line in text.splitlines()
    )


def _connect() -> Any:
    import psycopg
    from psycopg.rows import dict_row

    url = os.getenv("DATABASE_URL")
    if not url:
        raise ExerciseError("DATABASE_URL is missing; load the workshop environment")
    return psycopg.connect(url, connect_timeout=20, row_factory=dict_row)


def _configure(cur: Any, values: dict[str, str], *, force_hnsw: bool) -> None:
    """Apply the saved request's HNSW settings, optionally forcing the index."""
    from service.catalog_runtime import search_schema

    cur.execute(
        f"SELECT {search_schema()}.configure_hnsw(%s::int, %s::text, %s::int, %s::real)",
        (
            int(values["lab_ef_search"]),
            values["lab_iterative_scan"],
            int(values["lab_max_scan_tuples"]),
            float(values["lab_scan_mem_multiplier"]),
        ),
    )
    cur.execute("SET LOCAL statement_timeout = '120s'")
    if force_hnsw:
        cur.execute("SET LOCAL enable_sort = off")


def _participant_rows(cur: Any, statement: str, columns: tuple[str, ...]) -> list[dict]:
    try:
        cur.execute(statement)
    except Exception as error:
        raise ExerciseError(f"PostgreSQL rejected the query: {error}") from error
    rows = cur.fetchall()
    found = tuple(cur.description[i].name for i in range(len(cur.description)))
    missing = [column for column in columns if column not in found]
    if missing:
        raise ExerciseError(
            f"result is missing column(s) {missing}; the query must return "
            f"{list(columns)} (found {list(found)})"
        )
    return rows


def _lab1_truth(cur: Any, values: dict[str, str]) -> dict[str, Any]:
    """Index-proof exact neighbours against the installed approximate search."""
    from service.catalog_runtime import search_schema

    schema = search_schema()
    args = (
        values["lab_vector"],
        values["lab_filters"],
        int(values["lab_semantic_limit"]),
    )
    cur.execute(
        f"SELECT product_id FROM {schema}.search_vector(%s::vector, %s::jsonb, %s)",
        args,
    )
    approximate = {row["product_id"] for row in cur.fetchall()}
    cur.execute(
        f"SELECT d.product_id FROM {schema}.product_document d "
        f"WHERE d.embedding IS NOT NULL AND {schema}.matches_filters(d, %s::jsonb) "
        "ORDER BY (d.embedding <=> %s::vector) + 0, d.product_id LIMIT %s",
        (
            values["lab_filters"],
            values["lab_vector"],
            int(values["lab_semantic_limit"]),
        ),
    )
    exact = {row["product_id"] for row in cur.fetchall()}
    cur.execute(
        "EXPLAIN (ANALYZE, COSTS OFF) SELECT * FROM "
        f"{schema}.search_vector(%s::vector, %s::jsonb, %s)",
        args,
    )
    plan = [row["QUERY PLAN"] for row in cur.fetchall()]
    return {
        "approximate_rows": len(approximate),
        "exact_rows": len(exact),
        "recall": len(approximate & exact) / len(exact) if exact else 0.0,
        "access_path": next(
            (line.strip() for line in plan if "Scan using" in line), "?"
        ),
        "execution": next(
            (line.strip() for line in plan if "Execution Time" in line), ""
        ),
    }


def _lab1_verdict(condition: str, mine: dict, truth: dict) -> str | None:
    same_counts = (
        mine["approximate_rows"] == truth["approximate_rows"]
        and mine["exact_rows"] == truth["exact_rows"]
    )
    if same_counts and abs(float(mine["recall"]) - truth["recall"]) <= SCORE_TOLERANCE:
        return None
    if (
        condition == "forced HNSW"
        and float(mine["recall"]) == 1.0
        and truth["recall"] < 1.0
    ):
        return (
            "forced HNSW: your query reports recall 1.0, but the true recall is "
            f"{truth['recall']:.3f}. With enable_sort off, `ORDER BY embedding <=> ... "
            "LIMIT` is served by the same HNSW index, so your 'exact' set is the "
            "approximate one. Compute ground truth in a way no index can serve."
        )
    if same_counts:
        return (
            f"{condition}: your recall is {float(mine['recall']):.6f}; the true recall "
            f"is {truth['recall']:.6f}. Run EXPLAIN on your ground-truth CTE: if it "
            "scans real_search_vector_idx, it is approximate, not exact. A filter "
            "hidden inside a function call can also change the plan the planner picks."
        )
    return (
        f"{condition}: you returned approximate_rows={mine['approximate_rows']}, "
        f"exact_rows={mine['exact_rows']}, recall={float(mine['recall']):.6f}; the "
        f"independent answer is {truth['approximate_rows']}, {truth['exact_rows']}, "
        f"{truth['recall']:.6f}"
    )


def grade_lab1(statement: str, values: dict[str, str]) -> dict[str, Any]:
    """Grade the recall query with the planner's plan and with HNSW forced."""
    report: dict[str, Any] = {"conditions": {}, "failures": []}
    with _connect() as connection:
        for condition, force in (("planner's plan", False), ("forced HNSW", True)):
            with connection.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                _configure(cur, values, force_hnsw=force)
                rows = _participant_rows(cur, statement, LAB1_COLUMNS)
                if len(rows) != 1:
                    raise ExerciseError(f"expected one result row; found {len(rows)}")
                truth = _lab1_truth(cur, values)
            connection.rollback()
            failure = _lab1_verdict(condition, rows[0], truth)
            if failure:
                report["failures"].append(failure)
            report["conditions"][condition] = {
                "yours": {key: rows[0][key] for key in LAB1_COLUMNS},
                "independent": truth,
            }
    return report


def _fuse(arms: dict[str, dict[int, int]], k: int) -> list[tuple[int, float]]:
    scores: dict[int, float] = {}
    for ranks in arms.values():
        for product_id, rank in ranks.items():
            scores[product_id] = scores.get(product_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def _lab2_arms(cur: Any, values: dict[str, str]) -> dict[str, dict[int, int]]:
    from service.catalog_runtime import search_schema

    schema = search_schema()
    query, filters = values["lab_query"], values["lab_filters"]
    statements = {
        "fts": (
            f"SELECT product_id, fts_rank AS r FROM {schema}.search_fts(%s, %s::jsonb, %s)",
            (query, filters, int(values["lab_fts_limit"])),
        ),
        "trigram": (
            (
                f"SELECT product_id, trigram_rank AS r FROM {schema}.search_trigram("
                "%s, %s::jsonb, %s, %s::real)"
            ),
            (
                query,
                filters,
                int(values["lab_trigram_limit"]),
                float(values["lab_trigram_threshold"]),
            ),
        ),
        "vector": (
            (
                f"SELECT product_id, semantic_rank AS r FROM {schema}.search_vector("
                "%s::vector, %s::jsonb, %s)"
            ),
            (values["lab_vector"], filters, int(values["lab_semantic_limit"])),
        ),
    }
    arms = {}
    for name, (sql, args) in statements.items():
        cur.execute(sql, args)
        arms[name] = {row["product_id"]: row["r"] for row in cur.fetchall()}
    return arms


def _lab2_mismatch(
    rows: list[dict], truth: list[tuple[int, float]], k: int
) -> str | None:
    expected = {
        pid: (score, position) for position, (pid, score) in enumerate(truth, 1)
    }
    mine = {row["product_id"]: row for row in rows}
    if set(mine) != set(expected):
        missing, extra = set(expected) - set(mine), set(mine) - set(expected)
        return (
            f"k={k}: you returned {len(mine)} products; the three searches admit "
            f"{len(expected)}. Missing e.g. {sorted(missing)[:3]}, extra e.g. "
            f"{sorted(extra)[:3]}. Every product found by any search must appear once."
        )
    for product_id, (score, position) in expected.items():
        row = mine[product_id]
        if abs(float(row["rrf_score"]) - score) > SCORE_TOLERANCE:
            return (
                f"k={k}: product {product_id} scores {float(row['rrf_score']):.12f}; "
                f"expected {score:.12f}. Check each contribution against its own "
                "source position, and that k comes from :lab_rrf_k."
            )
        if int(row["combined_position"]) != position:
            return (
                f"k={k}: product {product_id} is at combined position "
                f"{row['combined_position']}; expected {position}. Break score ties "
                "by product_id, as production does."
            )
    return None


def _saved_run(cur: Any, values: dict[str, str]) -> dict[int, float]:
    search_id = values["lab_search_id"]
    cur.execute(
        "SELECT normalized_query, filters FROM mosaic.search_event "
        "WHERE search_event_id = %s::uuid",
        (search_id,),
    )
    event = cur.fetchone()
    if (
        event is None
        or event["normalized_query"] != values["lab_query"]
        or event["filters"] != json.loads(values["lab_filters"])
    ):
        raise ExerciseError(
            f"saved run {search_id} is not this lab's request; rerun "
            "`uv run python scripts/lab_terminal.py run --lab 2 --phase before`"
        )
    cur.execute(
        "SELECT product_id, (SELECT sum((c.value->>'rrf_contribution')::float8) "
        "FROM jsonb_each(provenance->'channels') c) AS score "
        "FROM mosaic.search_result_event WHERE search_event_id = %s::uuid",
        (search_id,),
    )
    return {row["product_id"]: row["score"] for row in cur.fetchall()}


def grade_lab2(statement_for_k: Any, values: dict[str, str]) -> dict[str, Any]:
    """Grade participant fusion at the configured k and four other values."""
    configured = int(values["lab_rrf_k"])
    target = int(values["lab_target"])
    cutoff = int(values["lab_fused_limit"])
    report: dict[str, Any] = {"k_trials": [], "failures": []}
    with _connect() as connection, connection.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        _configure(cur, values, force_hnsw=False)
        arms = _lab2_arms(cur, values)
        for k in sorted({configured, *LAB2_K_TRIALS}):
            rows = _participant_rows(cur, statement_for_k(k), LAB2_COLUMNS)
            truth = _fuse(arms, k)
            failure = _lab2_mismatch(rows, truth, k)
            if failure:
                report["failures"].append(failure)
            position = next(
                (i for i, (pid, _) in enumerate(truth, 1) if pid == target), None
            )
            report["k_trials"].append(
                {
                    "k": k,
                    "target_position": position,
                    "within_cutoff": position is not None and position <= cutoff,
                }
            )
        saved = _saved_run(cur, values)
        connection.rollback()
    truth = dict(_fuse(arms, configured))
    report["arms"] = {name: len(ranks) for name, ranks in arms.items()}
    report["saved_run"] = {
        "rows": len(saved),
        "rows_disagreeing_with_your_fusion": sum(
            1
            for pid, score in saved.items()
            if abs(score - truth.get(pid, float("nan"))) > SCORE_TOLERANCE
        ),
        "distinct_saved_scores": len({round(score, 12) for score in saved.values()}),
        "target_saved": target in saved,
    }
    report["cutoff"] = cutoff
    return report


def variant_source(body: str) -> str:
    """Return ``register_evidence`` source with its marked block replaced."""
    import inspect

    from service import agent_tools

    source = inspect.getsource(agent_tools.register_evidence)
    return lab_state._replace_block(
        source, "# LAB3_EVIDENCE_STATE_START", "# LAB3_EVIDENCE_STATE_END", body
    )


def variant_function(name: str) -> Any:
    """Compile the reference repair or one named faulty variant."""
    from service import agent_tools

    body = lab_state.LAB3_EVIDENCE_STATE if name == "reference" else LAB3_VARIANTS[name]
    namespace = dict(vars(agent_tools))
    exec(compile(variant_source(body), "<lab-3-variant>", "exec"), namespace)  # noqa: S102
    return namespace["register_evidence"]


def _run_tests(path: Path, variant: str | None) -> tuple[int, int]:
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    env.pop("LAB3_VARIANT", None)
    if variant:
        env["LAB3_VARIANT"] = variant
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--rootdir",
            str(path.parent),
            str(path),
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        env=env,
        check=False,
    )
    passed = sum(int(n) for n in re.findall(r"(\d+) passed", result.stdout))
    failed = sum(int(n) for n in re.findall(r"(\d+) (?:failed|error)", result.stdout))
    if passed + failed == 0:
        raise ExerciseError(f"pytest collected no tests:\n{result.stdout[-1500:]}")
    return passed, failed


def grade_lab3(path: Path) -> dict[str, Any]:
    """Tests must pass the reference, reject every variant, then pass your code."""
    report: dict[str, Any] = {"variants": {}, "failures": []}
    passed, failed = _run_tests(path, "reference")
    report["reference"] = {"passed": passed, "failed": failed}
    if passed + failed < LAB3_MINIMUM_TESTS:
        report["failures"].append(
            f"found {passed + failed} test(s); write at least {LAB3_MINIMUM_TESTS}"
        )
    if failed:
        report["failures"].append(
            f"{failed} test(s) fail against the reference repair, so they assert "
            "something the contract does not require"
        )
    for name in LAB3_VARIANTS:
        _, v_failed = _run_tests(path, name)
        report["variants"][name] = "rejected" if v_failed else "ACCEPTED"
        if not v_failed:
            report["failures"].append(f"your tests accept a faulty variant: {name}")
    passed, failed = _run_tests(path, None)
    report["your_code"] = {"passed": passed, "failed": failed}
    if failed:
        report["failures"].append(
            "your tests fail against service/agent_tools.py; repair "
            "register_evidence between the LAB3 markers"
        )
    return report


def _print_lab1(report: dict) -> None:
    for condition, result in report["conditions"].items():
        truth = result["independent"]
        print(
            f"{condition:15} recall {truth['recall']:.3f} "
            f"({truth['approximate_rows']} returned, {truth['exact_rows']} exact) "
            f"| {truth['access_path'][:70]} | {truth['execution']}"
        )


def _print_lab2(report: dict) -> None:
    print(f"search sizes: {report['arms']}; reranking cutoff: {report['cutoff']}")
    for trial in report["k_trials"]:
        where = trial["target_position"]
        status = (
            "reaches reranking" if trial["within_cutoff"] else "cut before reranking"
        )
        print(f"k={trial['k']:<4} target combined position {where} ({status})")
    saved = report["saved_run"]
    print(
        f"saved run: {saved['rows']} rows, {saved['distinct_saved_scores']} distinct "
        f"scores, {saved['rows_disagreeing_with_your_fusion']} disagree with your "
        f"fusion; target present: {saved['target_saved']}"
    )


def _print_lab3(report: dict) -> None:
    print(f"reference repair: {report['reference']}")
    for name, verdict in report["variants"].items():
        print(f"  variant '{name}': {verdict}")
    print(f"your service/agent_tools.py: {report['your_code']}")


def grade(lab: int, work: Path) -> dict[str, Any]:
    """Grade one lab's written work and return the report."""
    if not work.exists():
        raise ExerciseError(f"{work} does not exist; save your work there first")
    if lab == 3:
        return grade_lab3(work)
    values = load_context(lab)
    template = work.read_text(encoding="utf-8")
    if lab == 1:
        return grade_lab1(interpolate(template, values), values)
    return grade_lab2(
        lambda k: interpolate(template, {**values, "lab_rrf_k": str(k)}), values
    )


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("check",))
    parser.add_argument("--lab", type=int, choices=(1, 2, 3), required=True)
    parser.add_argument("--work", type=Path)
    args = parser.parse_args()
    work = args.work or DEFAULT_WORK[args.lab]
    try:
        report = grade(args.lab, work)
    except ExerciseError as error:
        print(f"Lab {args.lab} exercise: CANNOT GRADE - {error}")
        return 2
    {1: _print_lab1, 2: _print_lab2, 3: _print_lab3}[args.lab](report)
    report.update(
        lab=args.lab,
        work=str(work),
        work_sha256=hashlib.sha256(work.read_bytes()).hexdigest(),
        graded_at=datetime.now(UTC).isoformat(),
        verdict="FAIL" if report["failures"] else "PASS",
    )
    receipt = REPO / f".local/lab-{args.lab}/exercise-receipt.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(report, indent=2, default=str) + "\n")
    for failure in report["failures"]:
        print(f"FAIL: {failure}")
    print(f"Lab {args.lab} exercise: {report['verdict']} ({receipt.relative_to(REPO)})")
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
