#!/usr/bin/env python3
"""Build the held-out ESCI relevance corpus for the independent relevance runner.

ESCI's human labels are the only third-party relevance judgments this project
holds. The 141 queries in `data/evals/esci_judged_subset.json` were spent tuning
the RRF constant, and the canonical scorecard has its own query ids, so a
relevance claim needs queries disjoint from both. This selects every US ESCI
query whose judged products are catalog parents in one lab category, drops the
tuning and canonical ids, and writes records in the independent-corpus contract
with `status: "esci_human"`, grades mapped E=3, S=2, C=1, I=0, and the
anchor-overlap classification the runner reports separately.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.independent_relevance_eval import (
    ESCI_SUBSET_PATH,
    _canonical_judged_product_ids,
    _mission_anchor_product_ids,
    compute_anchor_overlap,
    esci_grade,
)
from scripts.prepare_esci_judged_subset import (
    EXAMPLES_SHA256,
    SOURCE_URL,
    catalog_products,
    select_cases,
    served_dataset,
)

CANONICAL_PATH = ROOT / "data" / "evals" / "canonical_queries.jsonl"
DEFAULT_OUTPUT = ROOT / "data" / "evals" / "esci_held_out_queries.jsonl"
COHORT_INTENT = "esci_shopping_query"


def tuning_query_ids(path: Path = ESCI_SUBSET_PATH) -> set[int]:
    """The ESCI query ids already spent on RRF-k tuning; never scored again."""
    return {case["query_id"] for case in json.loads(path.read_text())["queries"]}


def held_out_records(
    cases: list[dict],
    dataset: str,
    tuning_ids: set[int],
    anchors: tuple[set[int], set[int]],
) -> list[dict]:
    """Turn ESCI cases into corpus records, excluding every tuning query."""
    mission_ids, canonical_ids = anchors
    records = []
    for case in cases:
        if case["query_id"] in tuning_ids:
            continue
        judgments = []
        for row in case["judgments"]:
            grade = esci_grade(row["esci_label"])
            judgments.append(
                {
                    "product_id": row["product_id"],
                    "grade": grade,
                    "status": "esci_human",
                    "anchor_overlap": compute_anchor_overlap(
                        row["product_id"],
                        mission_ids=mission_ids,
                        canonical_ids=canonical_ids,
                    ),
                    "source": f"esci#{row['example_id']}",
                    "rationale": f"ESCI human label {row['esci_label']} for ASIN {row['asin']}.",
                }
            )
        records.append(
            {
                "query_id": f"ESCI-{case['query_id']}",
                "esci_query_id": case["query_id"],
                "query": case["query"],
                "dataset_id": dataset,
                "cohort_category": case["filters"]["category_key"],
                "cohort_intent": COHORT_INTENT,
                "filters": case["filters"],
                "expect_no_relevant_results": not any(
                    j["grade"] > 0 for j in judgments
                ),
                "judgments": judgments,
                "hard_negative_ids": [
                    j["product_id"] for j in judgments if j["grade"] == 0
                ],
                "source": {
                    "name": "Shopping Queries Dataset (ESCI)",
                    "license": "Apache-2.0",
                    "license_file": "data/evals/references/licenses/ESCI-LICENSE",
                    "url": SOURCE_URL,
                    "sha256": EXAMPLES_SHA256,
                },
            }
        )
    return records


def filter_eligible(
    records: list[dict], database_url: str, minimum: int = 3
) -> tuple[list[dict], dict]:
    """Drop judgments the served filters can never return, then thin queries.

    A refurbished listing, for example, is excluded by the default Mosaic
    filters, so a human label on it says nothing about the served ranking. The
    count of dropped judgments and queries is reported, never hidden.
    """
    import psycopg

    pairs = [
        {
            "query_id": r["query_id"],
            "product_id": j["product_id"],
            "filters": r["filters"],
        }
        for r in records
        for j in r["judgments"]
    ]
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            """
            WITH cases AS (
                SELECT * FROM jsonb_to_recordset(%s::jsonb)
                AS c(query_id text, product_id bigint, filters jsonb)
            )
            SELECT c.query_id, c.product_id
            FROM cases c
            JOIN mosaic_live_search.product_document d ON d.product_id = c.product_id
            WHERE NOT mosaic_live_search.matches_filters(d, c.filters)
            """,
            (json.dumps(pairs),),
        ).fetchall()
    ineligible = {(query_id, product_id) for query_id, product_id in rows}
    kept, dropped_queries = [], 0
    for record in records:
        judgments = [
            j
            for j in record["judgments"]
            if (record["query_id"], j["product_id"]) not in ineligible
        ]
        if len(judgments) < minimum:
            dropped_queries += 1
            continue
        record = {
            **record,
            "judgments": judgments,
            "hard_negative_ids": [
                j["product_id"] for j in judgments if j["grade"] == 0
            ],
            "expect_no_relevant_results": not any(j["grade"] > 0 for j in judgments),
        }
        kept.append(record)
    return kept, {
        "judgments_filter_ineligible": len(ineligible),
        "queries_dropped_below_minimum": dropped_queries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--examples", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    import pyarrow.parquet as pq

    table = pq.read_table(args.examples)
    columns = {name: table.column(name).to_pylist() for name in table.column_names}
    cases = select_cases(columns, catalog_products(os.environ["DATABASE_URL"]))
    anchors = (_mission_anchor_product_ids(), _canonical_judged_product_ids())
    records = held_out_records(cases, served_dataset(), tuning_query_ids(), anchors)
    records, eligibility = filter_eligible(records, os.environ["DATABASE_URL"])
    args.output.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    )
    by_category: dict[str, int] = {}
    for record in records:
        by_category[record["cohort_category"]] = (
            by_category.get(record["cohort_category"], 0) + 1
        )
    print(
        json.dumps(
            {
                "cases_on_catalog": len(cases),
                "tuning_excluded": sum(
                    1 for c in cases if c["query_id"] in tuning_query_ids()
                ),
                "held_out_queries": len(records),
                **eligibility,
                "by_category": by_category,
                "judgments": sum(len(r["judgments"]) for r in records),
                "output": str(args.output.relative_to(ROOT)),
            }
        )
    )


if __name__ == "__main__":
    main()
