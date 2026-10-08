#!/usr/bin/env python3
"""Check the SQL exercises and the deployed participant agent.

Every check compares the participant's work with an answer this script computes
independently, in read-only transactions. It never repairs a lab, never
changes catalog data, and never shows the reference answer.

- Lab 1: a recall query for the filtered vector search, graded with the planner's
  own plan and again with the HNSW index forced.
- Lab 2: the applied reciprocal-rank contribution, graded against 1 / (k + rank)
  at the configured ``k`` and at four other values. ``compare --lab 2`` prints what
  three retrieval changes would do on the judged shopper queries.
- Lab 3: the deployed Strands agent and its saved, source-backed recommendation.

Every graded attempt is also recorded in ``mosaic.lab_decision`` (created here if
missing), so the workshop finale can read each participant's decisions back from
Aurora. That insert is the only write, and it records work, not catalog data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from psycopg.rows import dict_row

from scripts import lab2_tuning, lab_state
from service.lab_files import LAB2_SQL
from service.participant_commands import DEPLOY_AGENT

SCORE_TOLERANCE = 1e-9
LAB2_K_TRIALS = (1, 10, 30, 120)
DEFAULT_WORK = {
    1: Path(".local/lab-1/recall.sql"),
    2: LAB2_SQL,
    3: Path("labs/lab3_reason/agent.py"),
}
LAB1_COLUMNS = ("approximate_rows", "exact_rows", "recall")
LAB2_RANKS_CHECKED = 150
DECISION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS mosaic.lab_decision (
    decision_id bigserial PRIMARY KEY,
    lab smallint NOT NULL,
    exercise text NOT NULL,
    run_id uuid,
    work_sha256 text NOT NULL,
    verdict text NOT NULL CHECK (verdict IN ('PASS', 'FAIL')),
    decision jsonb NOT NULL DEFAULT '{}'::jsonb,
    measurement jsonb NOT NULL,
    graded_at timestamptz NOT NULL DEFAULT now()
)"""


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


def _indexable_filter_sql(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    """Restate the filter's domain and category as index-servable predicates.

    `matches_filters` takes the whole row, so no index can serve it and a scan
    guarded by it alone reads all 500,000 products (26 s on the workshop
    cluster, twice per grade). These predicates narrow the scan to the eligible
    category; `matches_filters` still decides eligibility.
    """
    clauses: list[str] = []
    params: list[Any] = []
    if "domain" in filters:
        clauses.append("d.domain = %s::mosaic.product_domain")
        params.append(filters["domain"])
    if "category_key" in filters:
        clauses.append("d.category_key = %s")
        params.append(filters["category_key"])
    return "".join(f" AND {clause}" for clause in clauses), params


def _lab1_exact(cur: Any, values: dict[str, str]) -> set[int]:
    """The true nearest eligible products, by a sort no index can serve."""
    from service.catalog_runtime import search_schema

    schema = search_schema()
    narrowing, params = _indexable_filter_sql(json.loads(values["lab_filters"]))
    cur.execute(
        f"SELECT d.product_id FROM {schema}.product_document d "
        f"WHERE d.embedding IS NOT NULL{narrowing} "
        f"AND {schema}.matches_filters(d, %s::jsonb) "
        "ORDER BY (d.embedding <=> %s::vector) + 0, d.product_id LIMIT %s",
        (
            *params,
            values["lab_filters"],
            values["lab_vector"],
            int(values["lab_semantic_limit"]),
        ),
    )
    return {row["product_id"] for row in cur.fetchall()}


def _lab1_truth(cur: Any, values: dict[str, str], exact: set[int]) -> dict[str, Any]:
    """The installed approximate search, scored against the exact neighbours."""
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
    if mine["recall"] is None:
        return (
            f"{condition}: recall is NULL, so your exact CTE returned no rows; "
            "it must return the true nearest :lab_semantic_limit eligible products"
        )
    same_counts = (
        mine["approximate_rows"] == truth["approximate_rows"]
        and mine["exact_rows"] == truth["exact_rows"]
    )
    if same_counts and abs(float(mine["recall"]) - truth["recall"]) <= SCORE_TOLERANCE:
        return None
    if float(mine["recall"]) == 1.0 and truth["recall"] < 1.0:
        return (
            f"{condition}: your query reports recall 1.0, but the true recall is "
            f"{truth['recall']:.3f}, so your 'exact' set is the approximate one. "
            "PostgreSQL can serve `ORDER BY embedding <=> ... LIMIT` from the same "
            "HNSW index, with default settings or with enable_sort off. Compute "
            "ground truth in a way no index can serve."
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
        with connection.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SET LOCAL statement_timeout = '120s'")
            exact = _lab1_exact(cur, values)
        connection.rollback()
        for condition, force in (("planner's plan", False), ("forced HNSW", True)):
            with connection.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                _configure(cur, values, force_hnsw=force)
                rows = _participant_rows(cur, statement, LAB1_COLUMNS)
                if len(rows) != 1:
                    raise ExerciseError(f"expected one result row; found {len(rows)}")
                truth = _lab1_truth(cur, values, exact)
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


def _lab2_contribution_mismatch(
    cur: Any, schema: str, k: int, ranks: int
) -> str | None:
    """The applied function must give each position 1 / (k + rank), not a shared value."""
    cur.execute(
        f"SELECT r, {schema}.reciprocal_rank_contribution(r, %s) AS c "
        "FROM generate_series(1, %s) AS r ORDER BY r",
        (k, ranks),
    )
    for row in cur.fetchall():
        expected = 1.0 / (k + row["r"])
        actual = float(row["c"]) if row["c"] is not None else float("nan")
        if not math.isfinite(actual) or abs(actual - expected) > SCORE_TOLERANCE:
            return (
                f"k={k}: position {row['r']} earns {actual:.12f}; expected "
                f"1 / ({k} + {row['r']}) = {expected:.12f}. Each source position needs "
                "its own contribution; apply your edit with "
                "`uv run python scripts/apply_search_functions.py`."
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
            "`uv run python scripts/lab_terminal.py run --lab 2 --phase after`"
        )
    cur.execute(
        "SELECT product_id, (SELECT sum((c.value->>'rrf_contribution')::float8) "
        "FROM jsonb_each(provenance->'channels') c) AS score "
        "FROM mosaic.search_result_event WHERE search_event_id = %s::uuid",
        (search_id,),
    )
    return {row["product_id"]: row["score"] for row in cur.fetchall()}


def grade_lab2(values: dict[str, str]) -> dict[str, Any]:
    """Grade the applied contribution at the configured k and four other values."""
    from service.catalog_runtime import search_schema

    schema = search_schema()
    configured = int(values["lab_rrf_k"])
    target = int(values["lab_target"])
    cutoff = int(values["lab_fused_limit"])
    report: dict[str, Any] = {"k_trials": [], "failures": []}
    with _connect() as connection, connection.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        _configure(cur, values, force_hnsw=False)
        arms = _lab2_arms(cur, values)
        for k in sorted({configured, *LAB2_K_TRIALS}):
            failure = _lab2_contribution_mismatch(cur, schema, k, LAB2_RANKS_CHECKED)
            if failure:
                report["failures"].append(failure)
            truth = _fuse(arms, k)
            position = next(
                (i for i, (pid, _) in enumerate(truth, 1) if pid == target), None
            )
            report["k_trials"].append(
                {
                    "k": k,
                    "contribution_correct": failure is None,
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
        "rows_disagreeing_with_correct_fusion": sum(
            1
            for pid, score in saved.items()
            if pid not in truth
            or score is None
            or not math.isfinite(score)
            or abs(score - truth[pid]) > SCORE_TOLERANCE
        ),
        "distinct_saved_scores": len(
            {
                round(score, 12)
                for score in saved.values()
                if score is not None and math.isfinite(score)
            }
        ),
        "target_saved": target in saved,
    }
    rerun = "rerun `uv run python scripts/lab_terminal.py run --lab 2 --phase after`, then check again"
    if not saved:
        report["failures"].append(f"no saved rows prove the fusion repair; {rerun}")
    else:
        mismatches = report["saved_run"]["rows_disagreeing_with_correct_fusion"]
        if mismatches:
            report["failures"].append(
                f"{mismatches} saved rows disagree with correct fusion; {rerun}"
            )
        if target not in saved:
            report["failures"].append(
                f"target {target} is absent from the saved results; {rerun}"
            )
    report["cutoff"] = cutoff
    return report


def grade_lab3(path: Path) -> dict[str, Any]:
    """Check the participant's deployed agent and the answer they just produced."""
    from uuid import UUID

    from service.agentcore_transport import runtime_arn
    from service.lab_proof import completion_proof

    if path.resolve() != (REPO / DEFAULT_WORK[3]).resolve():
        raise ExerciseError(
            f"Lab 3 runs labs/lab3_reason/agent.py; save your agent there, then deploy with {DEPLOY_AGENT}."
        )
    if not lab_state.lab_is_solved(3):
        raise ExerciseError(
            f"Open labs/lab3_reason/agent.py, complete create_agent, then deploy with {DEPLOY_AGENT}."
        )
    if not runtime_arn():
        raise ExerciseError(
            "AgentCore Runtime is not connected. Ask your facilitator to check this workshop's deployment."
        )
    values = load_context(3)
    proof = completion_proof(3, agent_run_id=UUID(values["lab_agent_id"]))
    failures = [check.detail for check in proof.checks if not check.passed]
    if proof.status != "pass" and not failures:
        failures.append(
            f"Your current code does not match the completed labs. Apply Labs 1 and 2, then deploy with {DEPLOY_AGENT}."
        )
    return {"agent_run_id": values["lab_agent_id"], "failures": failures}


def record_decision(lab: int, report: dict[str, Any], values: dict[str, str]) -> None:
    """Save the graded attempt in Aurora so the finale can read it back."""
    run_id = values.get("lab_search_id") or values.get("lab_agent_id")
    with _connect() as connection:
        connection.execute(DECISION_TABLE_SQL)
        connection.execute(
            "INSERT INTO mosaic.lab_decision "
            "(lab, exercise, run_id, work_sha256, verdict, decision, measurement) "
            "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)",
            (
                lab,
                report["exercise"],
                run_id,
                report["work_sha256"],
                report["verdict"],
                json.dumps(report.get("decision", {})),
                json.dumps(
                    {k: v for k, v in report.items() if k not in {"decision"}},
                    default=str,
                ),
            ),
        )


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
        verdict = "correct" if trial["contribution_correct"] else "WRONG"
        print(
            f"k={trial['k']:<4} contribution {verdict}; target combined position "
            f"{where} ({status})"
        )
    saved = report["saved_run"]
    print(
        f"saved run: {saved['rows']} rows, {saved['distinct_saved_scores']} distinct "
        f"scores, {saved['rows_disagreeing_with_correct_fusion']} disagree with "
        f"correct fusion; target present: {saved['target_saved']}"
    )


def print_comparison(table: dict) -> None:
    """Print the measured effect of each derived change, for the participant to judge."""
    base = table["baseline"]
    print(
        f"Served profile: {base['exact_in_cutoff']} exact matches reach reranking "
        f"across the judged queries; {base['billed_search_units_per_query']} billed "
        "rerank unit per query."
    )
    print(
        f"{'Change':<18}{'Exact found':>12}{'Better':>8}{'Worse':>7}{'Sign test p':>13}{'Rerank units':>14}"
    )
    for row in table["rows"]:
        p_value = "<0.0001" if row["sign_test_p"] == 0 else row["sign_test_p"]
        print(
            f"{row['label']:<18}{row['exact_gain']:>+12}{row['queries_better']:>8}"
            f"{row['queries_worse']:>7}{p_value:>13}"
            f"{row['billed_search_units_per_query']:>14}"
        )
        for moved in row["chair_controls_moved"]:
            print(f"  chair control {moved['id']}: {moved['from']} -> {moved['to']}")
    print(table["scope"])
    print("Decide in one sentence: which change would you ship, and why?")


def _print_lab3(report: dict) -> None:
    if not report["failures"]:
        print("Your agent is live and using your hybrid search to answer with sources.")
        print(
            "Next: change Alex's requirements in Mosaic and see how its recommendation changes."
        )


def grade(lab: int, work: Path) -> dict[str, Any]:
    """Grade one lab's written work and return the report."""
    if not work.exists():
        raise ExerciseError(f"{work} does not exist; save your work there first")
    if lab == 3:
        return grade_lab3(work)
    values = load_context(lab)
    if lab == 2:
        return grade_lab2(values)
    return grade_lab1(interpolate(work.read_text(encoding="utf-8"), values), values)


def compare(lab: int) -> dict[str, Any]:
    """Measure the derived retrieval changes for Lab 2's decision."""
    if lab != 2:
        raise ExerciseError("compare is Lab 2's decision step; use --lab 2")
    values = load_context(2)
    baseline = {
        key: int(values[f"lab_{key}"])
        for key in (
            "rrf_k",
            "fused_limit",
            "fts_limit",
            "trigram_limit",
            "semantic_limit",
        )
    }
    try:
        with _connect() as connection:
            connection.row_factory = dict_row
            table = lab2_tuning.comparison_table(connection, baseline)
            connection.rollback()
    except lab2_tuning.TuningError as error:
        raise ExerciseError(str(error)) from error
    return table


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("check", "compare"))
    parser.add_argument("--lab", type=int, choices=(1, 2, 3), required=True)
    parser.add_argument("--work", type=Path)
    args = parser.parse_args()
    if args.action == "compare":
        try:
            print_comparison(compare(args.lab))
        except ExerciseError as error:
            print(f"Lab {args.lab} comparison: CANNOT MEASURE - {error}")
            return 2
        return 0
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
    report["exercise"] = {1: "recall_instrument", 2: "fusion", 3: "managed_agent"}[
        args.lab
    ]
    context = REPO / f".local/lab-{args.lab}/context.json"
    if context.exists():
        record_decision(args.lab, report, json.loads(context.read_text()))
    receipt = REPO / f".local/lab-{args.lab}/exercise-receipt.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(report, indent=2, default=str) + "\n")
    for failure in report["failures"]:
        print(f"FAIL: {failure}")
    print(f"Lab {args.lab} exercise: {report['verdict']} ({receipt.relative_to(REPO)})")
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
