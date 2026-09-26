#!/usr/bin/env python3
"""Select ESCI judgments whose products are in the served catalog.

The Shopping Queries Dataset (ESCI, Apache-2.0) judges query-product pairs as
Exact, Substitute, Complement or Irrelevant. This keeps the US judgments whose
product ASIN is a parent ASIN in the served catalog, for queries whose judged
catalog products fall in a lab category. Unjudged catalog products stay unknown;
they are never counted as irrelevant.

pyarrow is not a project dependency, so run this in a throwaway environment:

    uv run --no-project --with pyarrow --with 'psycopg[binary]' \
        python scripts/prepare_esci_judged_subset.py \
        --examples .local/esci/examples.parquet \
        --output data/evals/esci_judged_subset.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path

SOURCE_COMMIT = "7916cdf6ab75a462e77f20ab40428a10923998d5"
SOURCE_URL = (
    "https://github.com/amazon-science/esci-data/blob/"
    f"{SOURCE_COMMIT}/shopping_queries_dataset/shopping_queries_dataset_examples.parquet"
)
EXAMPLES_SHA256 = "4a735b693b4a424a6fc67f5be6e4c811495c488bbf66d02a602d308b2744263a"
LAB_CATEGORIES = ("headphones", "monitor", "chair")
MINIMUM_JUDGED = 3


def catalog_products(database_url: str) -> dict[str, dict]:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        rows = connection.execute(
            "SELECT parent_asin, product_id, category_key, domain::text AS domain "
            "FROM mosaic_live_search.product_document"
        ).fetchall()
    return {row["parent_asin"]: row for row in rows}


def select_cases(columns: dict, catalog: dict[str, dict]) -> list[dict]:
    """Group US judgments on catalog products into per-query cases."""
    grouped: dict[int, list[int]] = defaultdict(list)
    for index, locale in enumerate(columns["product_locale"]):
        if locale == "us" and columns["product_id"][index] in catalog:
            grouped[columns["query_id"][index]].append(index)
    cases = []
    for query_id, indexes in sorted(grouped.items()):
        categories = Counter(
            catalog[columns["product_id"][i]]["category_key"] for i in indexes
        )
        category, _ = categories.most_common(1)[0]
        judged = [
            i
            for i in indexes
            if catalog[columns["product_id"][i]]["category_key"] == category
        ]
        if category not in LAB_CATEGORIES or len(judged) < MINIMUM_JUDGED:
            continue
        first = catalog[columns["product_id"][judged[0]]]
        cases.append(
            {
                "query_id": query_id,
                "query": columns["query"][judged[0]],
                "filters": {"domain": first["domain"], "category_key": category},
                "judgments": sorted(
                    (
                        {
                            "asin": columns["product_id"][i],
                            "product_id": catalog[columns["product_id"][i]][
                                "product_id"
                            ],
                            "esci_label": columns["esci_label"][i],
                            "example_id": columns["example_id"][i],
                        }
                        for i in judged
                    ),
                    key=lambda row: row["asin"],
                ),
            }
        )
    return cases


def served_dataset() -> str:
    """The catalog the judgments were joined against, never a literal in this file."""
    dataset = os.environ.get("MOSAIC_CATALOG_DATASET", "").strip()
    if not dataset:
        raise SystemExit(
            "ESCI subset rule: set MOSAIC_CATALOG_DATASET to the served catalog the subset is joined against."
        )
    return dataset


def main() -> None:
    import pyarrow.parquet as pq

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--examples", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    digest = hashlib.sha256(args.examples.read_bytes()).hexdigest()
    if digest != EXAMPLES_SHA256:
        raise SystemExit(
            f"ESCI source rule: {args.examples} has SHA-256 {digest}; download "
            f"the file pinned at {SOURCE_URL}"
        )
    columns = pq.read_table(args.examples).to_pydict()
    cases = select_cases(columns, catalog_products(os.environ["DATABASE_URL"]))
    labels = Counter(j["esci_label"] for case in cases for j in case["judgments"])
    args.output.write_text(
        json.dumps(
            {
                "source": {
                    "name": "Shopping Queries Dataset (ESCI)",
                    "license": "Apache-2.0",
                    "license_file": "data/evals/references/licenses/ESCI-LICENSE",
                    "url": SOURCE_URL,
                    "sha256": EXAMPLES_SHA256,
                },
                "dataset_id": served_dataset(),
                "selection": (
                    "US judgments whose product ASIN is a catalog parent ASIN; per "
                    "query, the judgments in its most-judged category, kept when "
                    f"that category is one of {list(LAB_CATEGORIES)} and has at "
                    f"least {MINIMUM_JUDGED} judged products. Unjudged products are "
                    "unknown, not irrelevant."
                ),
                "cases": len(cases),
                "labels": dict(sorted(labels.items())),
                "queries": cases,
            },
            indent=1,
            ensure_ascii=False,
        )
        + "\n"
    )
    print(f"{len(cases)} queries, labels {dict(labels)} -> {args.output}")


if __name__ == "__main__":
    main()
