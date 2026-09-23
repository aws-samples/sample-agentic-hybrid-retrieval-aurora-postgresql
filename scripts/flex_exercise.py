#!/usr/bin/env python3
"""Grade the optional "Shrink it" exercise: a faster, smaller filtered vector search.

The participant writes two files:

- `.local/flex/index.sql`: one partial HNSW index on
  `mosaic_catalog_search.product_document` (full-precision, `halfvec` or
  `binary_quantize` expression), optionally followed by `SET hnsw.ef_search = N`.
- `.local/flex/search.sql`: one SELECT returning `product_id` for the nearest
  `:flex_limit` headphones to `:'flex_vector'`, written so the planner can use
  that index.

The grader builds the index twice inside its own transaction and rolls it back.
Recall is averaged over both builds and five real headphone queries against an
exact answer it computes itself, so one unlucky HNSW build cannot fail a sound
design. Timing compares medians of interleaved runs against the exact plan on
the same connection. Index size is compared with a full-precision reference
index built the same way, so any compression ratio is measured, not assumed.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import statistics
import struct
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.lab_exercise import ExerciseError, _connect, interpolate

INDEX_WORK = Path(".local/flex/index.sql")
SEARCH_WORK = Path(".local/flex/search.sql")
FILTER = "headphones"
LIMIT = 150
QUERIES = 5
BUILDS = 2
TIMING_RUNS = 5
MIN_RECALL = 0.90
MAX_TIME_RATIO = 0.5
MAX_SIZE_RATIO = 0.5
TABLE = "mosaic_catalog_search.product_document"
CREATE_INDEX = re.compile(
    r"(?is)^CREATE\s+INDEX\s+(?P<name>[a-z_][a-z0-9_]*)\s+ON\s+"
    r"mosaic_catalog_search\.product_document\s+USING\s+hnsw\s*\([^;]+\)"
    r"(?:\s+WITH\s*\([^;()]*\))?\s+WHERE\s+[^;]+$"
)
SET_EF_SEARCH = re.compile(
    r"(?is)^SET\s+(?:LOCAL\s+)?hnsw\.ef_search\s*(?:=|TO)\s*(\d+)$"
)
REFERENCE_INDEX = (
    f"CREATE INDEX flex_reference_hnsw ON {TABLE} USING hnsw "
    f"(embedding vector_cosine_ops) WHERE category_key = '{FILTER}'"
)
EXACT_SQL = (
    f"SELECT product_id FROM {TABLE} WHERE category_key = '{FILTER}' "
    "AND embedding IS NOT NULL ORDER BY (embedding <=> %s::vector) + 0, product_id "
    f"LIMIT {LIMIT}"
)


def parse_index(text: str) -> tuple[str, str, int | None]:
    """One CREATE INDEX on the catalog table, and an optional ef_search."""
    statements = [
        " ".join(line.split("--", 1)[0] for line in chunk.splitlines()).strip()
        for chunk in text.split(";")
    ]
    statements = [statement for statement in statements if statement]
    if not statements or len(statements) > 2:
        raise ExerciseError(
            "index.sql holds one CREATE INDEX and, optionally, SET hnsw.ef_search = N"
        )
    match = CREATE_INDEX.match(statements[0])
    if match is None:
        raise ExerciseError(
            f"the first statement must be CREATE INDEX <name> ON {TABLE} USING hnsw "
            "(<column or expression> <opclass>) [WITH (...)] WHERE <predicate>; "
            "CONCURRENTLY cannot run inside the grader's transaction"
        )
    ef_search = None
    if len(statements) == 2:
        setting = SET_EF_SEARCH.match(statements[1])
        if setting is None:
            raise ExerciseError("the second statement must be SET hnsw.ef_search = N")
        ef_search = int(setting.group(1))
    return statements[0], match.group("name"), ef_search


def query_vectors() -> list[str]:
    """Five headphone shopper queries from the committed ESCI subset."""
    subset = json.loads((REPO / "data/evals/esci_judged_subset.json").read_text())
    vectors = json.loads((REPO / "data/evals/esci_query_vectors.json").read_text())
    chosen = [
        case["query_id"]
        for case in subset["queries"]
        if case["filters"]["category_key"] == FILTER
    ][:QUERIES]
    rendered = []
    for query_id in chosen:
        values = struct.unpack(
            "<1024f", base64.b64decode(vectors["vectors"][str(query_id)])
        )
        rendered.append("[" + ",".join(repr(value) for value in values) + "]")
    return rendered


def _execution_ms(cur: Any, sql: str, args: tuple = ()) -> tuple[float, list[str]]:
    cur.execute("EXPLAIN (ANALYZE, COSTS OFF) " + sql, args)
    plan = [row["QUERY PLAN"] for row in cur.fetchall()]
    line = next(line for line in plan if "Execution Time" in line)
    return float(re.search(r"([\d.]+) ms", line).group(1)), plan


def _participant_ids(cur: Any, statement: str) -> list[int]:
    try:
        cur.execute(statement)
    except Exception as error:
        raise ExerciseError(f"PostgreSQL rejected search.sql: {error}") from error
    rows = cur.fetchall()
    if not rows or "product_id" not in rows[0]:
        raise ExerciseError("search.sql must return a product_id column")
    return [row["product_id"] for row in rows]


def measure_build(cur: Any, search: str, vectors: list[str], exact: list[set]) -> dict:
    """Recall, plan and timing of the participant's search against the exact plan."""
    recalls, ratios, uses_index = [], [], []
    for vector, truth in zip(vectors, exact, strict=True):
        statement = interpolate(
            search, {"flex_vector": vector, "flex_limit": str(LIMIT)}
        )
        ids = _participant_ids(cur, statement)
        if len(ids) != LIMIT or len(set(ids)) != LIMIT:
            raise ExerciseError(
                f"search.sql returned {len(ids)} rows; return {LIMIT} distinct"
            )
        recalls.append(len(set(ids) & truth) / LIMIT)
        yours, exact_times = [], []
        for _ in range(TIMING_RUNS):
            elapsed, plan = _execution_ms(cur, statement)
            yours.append(elapsed)
            exact_times.append(_execution_ms(cur, EXACT_SQL, (vector,))[0])
        uses_index.append(plan)
        ratios.append(statistics.median(yours) / statistics.median(exact_times))
    return {
        "recall": statistics.fmean(recalls),
        "time_ratio": statistics.median(ratios),
    }, uses_index


def grade(index_text: str, search_text: str) -> dict[str, Any]:
    create, name, ef_search = parse_index(index_text)
    interpolate(search_text, {"flex_vector": "[0]", "flex_limit": str(LIMIT)})
    vectors = query_vectors()
    with _connect() as connection, connection.cursor() as cur:
        cur.execute("SET LOCAL statement_timeout = '600s'")
        cur.execute("SET LOCAL hnsw.iterative_scan = 'relaxed_order'")
        exact = []
        for vector in vectors:
            cur.execute(EXACT_SQL, (vector,))
            exact.append({row["product_id"] for row in cur.fetchall()})
        cur.execute("SAVEPOINT reference")
        cur.execute(REFERENCE_INDEX)
        cur.execute(
            "SELECT pg_relation_size('mosaic_catalog_search.flex_reference_hnsw') AS b"
        )
        reference_bytes = cur.fetchone()["b"]
        cur.execute("ROLLBACK TO SAVEPOINT reference")
        builds = []
        for _ in range(BUILDS):
            cur.execute("SAVEPOINT build")
            try:
                cur.execute(create)
            except Exception as error:
                raise ExerciseError(
                    f"PostgreSQL rejected the index: {error}"
                ) from error
            if ef_search is not None:
                cur.execute(
                    "SELECT set_config('hnsw.ef_search', %s, true)", (str(ef_search),)
                )
            cur.execute(f"SELECT pg_relation_size('mosaic_catalog_search.{name}') AS b")
            size = cur.fetchone()["b"]
            result, plans = measure_build(cur, search_text, vectors, exact)
            result["index_bytes"] = size
            result["uses_index"] = all(
                any(name in line for line in plan) for plan in plans
            )
            builds.append(result)
            cur.execute("ROLLBACK TO SAVEPOINT build")
        connection.rollback()
    return summarize(name, ef_search, builds, reference_bytes)


def summarize(
    name: str, ef_search: int | None, builds: list, reference_bytes: int
) -> dict:
    recall = statistics.fmean(build["recall"] for build in builds)
    ratio = statistics.median(build["time_ratio"] for build in builds)
    size_ratio = builds[0]["index_bytes"] / reference_bytes
    failures = []
    if not all(build["uses_index"] for build in builds):
        failures.append(
            f"the plan for search.sql does not use {name}; match its expression"
        )
    if recall < MIN_RECALL:
        failures.append(
            f"mean recall {recall:.3f} over {BUILDS} builds; the bar is {MIN_RECALL}"
        )
    if ratio > MAX_TIME_RATIO:
        failures.append(
            f"your search takes {ratio:.0%} of the exact plan; the bar is 50%"
        )
    return {
        "index": name,
        "ef_search": ef_search,
        "builds": builds,
        "mean_recall": round(recall, 4),
        "median_time_ratio": round(ratio, 4),
        "index_bytes": builds[0]["index_bytes"],
        "reference_index_bytes": reference_bytes,
        "size_ratio_vs_full_precision": round(size_ratio, 4),
        "fast": not failures,
        "small": not failures and size_ratio <= MAX_SIZE_RATIO,
        "failures": failures,
    }


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("check",))
    args = parser.parse_args()
    del args
    try:
        missing = [str(p) for p in (INDEX_WORK, SEARCH_WORK) if not (REPO / p).exists()]
        if missing:
            raise ExerciseError(f"write {', '.join(missing)} first")
        report = grade(
            (REPO / INDEX_WORK).read_text(encoding="utf-8"),
            (REPO / SEARCH_WORK).read_text(encoding="utf-8"),
        )
    except ExerciseError as error:
        print(f"Shrink it: CANNOT GRADE - {error}")
        return 2
    for number, build in enumerate(report["builds"], start=1):
        print(
            f"build {number}: recall {build['recall']:.3f}, "
            f"{build['time_ratio']:.0%} of exact time, "
            f"{build['index_bytes'] / 1e6:.1f} MB, uses index: {build['uses_index']}"
        )
    print(
        f"reference full-precision index: {report['reference_index_bytes'] / 1e6:.1f} MB; "
        f"yours is {report['size_ratio_vs_full_precision']:.0%} of it"
    )
    for failure in report["failures"]:
        print(f"FAIL: {failure}")
    tier = (
        "FAST AND SMALL" if report["small"] else "FAST" if report["fast"] else "NOT YET"
    )
    print(f"Shrink it: {tier}")
    receipt = REPO / ".local/flex/exercise-receipt.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["fast"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
