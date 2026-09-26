#!/usr/bin/env python3
"""Select the HNSW instrument's query anchors from the served catalog, reproducibly.

The set is the lab products every participant meets plus a category-stratified
sample of the rest of the catalog. The sample is a hash order, not a random
draw: within each category the products are sorted by `md5(seed || ':' ||
parent_asin)` and the first N are taken, so the same seed on the same catalog
always yields the same ids and a reviewer can recompute the list from the
recorded inputs. No product row is modified; the selection lives only in the
committed file.

Usage
-----
    make select-hnsw-anchors
    uv run python scripts/select_hnsw_anchors.py --check   # verify, write nothing
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.retrieval_profile import explain
from service.catalog_runtime import active_dataset, product_document
from service.config import get_settings
from service.db import connect
from service.hnsw_anchors import (
    ANCHOR_FILE,
    ANCHOR_SET_KIND,
    AnchorSetError,
    anchor_ids_sha256,
    load_anchor_set,
)
from service.hnsw_corpus import corpus_manifest

LAB_PRODUCTS_FILE = REPO / "data" / "evals" / "real_catalog_lab_products.json"
DEFAULT_SEED = "mosaic-hnsw-anchors-v1"
# Ten from each category a lab teaches and from the long tail, five from each
# small accessory category. 70 anchors with the fifteen lab products.
DEFAULT_SAMPLE = {
    "other": 10,
    "headphones": 10,
    "chair": 10,
    "monitor": 10,
    "headphone_case": 5,
    "monitor_stand": 5,
    "chair_mat": 5,
}
ALGORITHM = (
    "lab products from real_catalog_lab_products.json, then per category_key the "
    "first N products by md5(seed || ':' || parent_asin) ascending, ties by "
    "product_id, excluding lab products; every anchor has a stored embedding"
)

ANCHOR_COLUMNS = (
    "product_id, parent_asin, category_key, domain::text AS domain, brand_name, title"
)


def lab_product_ids(path: Path = LAB_PRODUCTS_FILE) -> list[int]:
    """The served ids of the lab products, in file order."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [int(item["product_id"]) for item in payload["products"]]


def parse_sample(value: str | None) -> dict[str, int]:
    """Parse `category=N,category=N` into sizes, refusing non-positive sizes."""
    if not value:
        return dict(DEFAULT_SAMPLE)
    sizes: dict[str, int] = {}
    for part in value.split(","):
        key, _, count = part.partition("=")
        if not key or not count.isdigit() or int(count) < 1:
            raise SystemExit(
                explain(f"--per-category entry {part!r}", "use category=N with N >= 1")
            )
        sizes[key.strip()] = int(count)
    return sizes


def select_anchors(
    connection: Any, *, seed: str, sample: dict[str, int], lab_ids: list[int]
) -> list[dict[str, Any]]:
    """Return the anchor records: lab products first, then the stratified sample.

    Raises:
        SystemExit: A lab product is absent from the catalog or has no vector,
            or a category yields fewer products than requested.
    """
    relation = product_document()
    lab_rows = connection.execute(
        f"SELECT {ANCHOR_COLUMNS} FROM {relation} "
        "WHERE product_id = ANY(%s) AND embedding IS NOT NULL",
        (lab_ids,),
    ).fetchall()
    found = {int(row["product_id"]): dict(row) for row in lab_rows}
    missing = [item for item in lab_ids if item not in found]
    if missing:
        raise SystemExit(
            explain(
                f"lab products {missing} are not in the served catalog with a vector",
                "select anchors against the catalog the lab products file describes",
            )
        )
    anchors = [found[item] | {"source": "lab"} for item in lab_ids]
    for category, size in sample.items():
        rows = connection.execute(
            f"""
            SELECT {ANCHOR_COLUMNS}
            FROM {relation}
            WHERE embedding IS NOT NULL
              AND category_key = %s
              AND NOT (product_id = ANY(%s))
            ORDER BY md5(%s || ':' || parent_asin), product_id
            LIMIT %s
            """,
            (category, lab_ids, seed, size),
        ).fetchall()
        if len(rows) < size:
            raise SystemExit(
                explain(
                    f"category {category!r} has {len(rows)} eligible products, "
                    f"fewer than the {size} requested",
                    "lower its sample size or drop the category",
                )
            )
        anchors.extend(dict(row) | {"source": "sample"} for row in rows)
    return anchors


def anchor_set_payload(
    anchors: list[dict[str, Any]],
    *,
    dataset_id: str,
    catalog_sha256: str,
    seed: str,
    sample: dict[str, int],
    lab_ids: list[int],
    revision: str | None,
) -> dict[str, Any]:
    ids = [int(item["product_id"]) for item in anchors]
    return {
        "kind": ANCHOR_SET_KIND,
        "dataset_id": dataset_id,
        "catalog_sha256": catalog_sha256,
        "selected_at": datetime.now(UTC).isoformat(),
        "source_revision": revision,
        "selection": {
            "algorithm": ALGORITHM,
            "seed": seed,
            "lab_products_file": str(LAB_PRODUCTS_FILE.relative_to(REPO)),
            "lab_product_ids": lab_ids,
            "sample_per_category": sample,
            "anchor_count": len(ids),
        },
        "anchors": anchors,
        "sha256": anchor_ids_sha256(ids),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", default=DEFAULT_SEED)
    parser.add_argument("--per-category", help="category=N,category=N")
    parser.add_argument("--output", type=Path, default=ANCHOR_FILE)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Recompute the selection and compare it with the file. Writes nothing.",
    )
    arguments = parser.parse_args()
    dataset = active_dataset()
    if not dataset:
        raise SystemExit(
            explain(
                "no prepared catalog is selected",
                "export MOSAIC_CATALOG_DATASET; anchors are selected from the "
                "served real catalog only",
            )
        )
    sample = parse_sample(arguments.per_category)
    lab_ids = lab_product_ids()
    with connect(statement_timeout_ms=300_000) as connection:
        catalog_sha256 = corpus_manifest(connection)
        anchors = select_anchors(
            connection, seed=arguments.seed, sample=sample, lab_ids=lab_ids
        )
    payload = anchor_set_payload(
        anchors,
        dataset_id=dataset,
        catalog_sha256=catalog_sha256,
        seed=arguments.seed,
        sample=sample,
        lab_ids=lab_ids,
        revision=get_settings().source_revision,
    )
    if arguments.check:
        try:
            committed = load_anchor_set(arguments.output)
        except AnchorSetError as error:
            raise SystemExit(str(error)) from error
        if committed.sha256 != payload["sha256"] or committed.dataset_id != dataset:
            raise SystemExit(
                explain(
                    f"the committed anchor set ({committed.dataset_id}, "
                    f"{committed.sha256[:12]}) differs from the selection recomputed "
                    f"on {dataset} ({payload['sha256'][:12]})",
                    "run `make select-hnsw-anchors` and reseed ground truth",
                )
            )
        print(
            f"anchor set verified: {len(committed.product_ids)} anchors, {committed.sha256}"
        )
        return
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"wrote {len(anchors)} anchors for {dataset} ({catalog_sha256[:12]}) to "
        f"{arguments.output}; sha256 {payload['sha256']}"
    )


if __name__ == "__main__":
    main()
