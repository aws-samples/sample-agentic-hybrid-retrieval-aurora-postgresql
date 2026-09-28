#!/usr/bin/env python3
"""Drop sampled reviews whose parent is not a staged catalog product, and count them.

The review scans are seeded from every product in the lab category leaves; the
catalog selection then excludes some of those products (source-text or image
rules). A review of a product outside the catalog is not evidence for any served
product, so those rows leave the release sample here, counted, never silently.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.catalog.fetch_catalog_reviews import (
    coverage_of,
    expand_review,
    review_parent,
)
from scripts.catalog.stage_real_catalog import validate_dsn

OUTSIDE_RULE = (
    "Parents present in the lab leaves but excluded by the catalog selection; their reviews "
    "are not evidence for any served product."
)


def staged_parents(dsn: str, dataset: str) -> set[str]:
    validate_dsn(dsn)
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT parent_asin FROM mosaic_catalog_stage.product WHERE dataset_id=%s",
            (dataset,),
        ).fetchall()
    if not rows:
        raise ValueError(
            f"Review filter rule: dataset {dataset!r} has no staged products; stage the catalog before filtering reviews."
        )
    return {row[0] for row in rows}


def filter_sample(state: dict, staged: set[str]) -> tuple[dict, dict]:
    """Return the sample without outside parents, and a receipt of what left."""
    before = len(state["reviews"])
    outside = {parent for parent in state["parent_asins"] if parent not in staged}
    kept = [row for row in state["reviews"] if review_parent(row) not in outside]
    filtered = dict(state)
    filtered["reviews"] = kept
    filtered["parent_asins"] = [
        parent for parent in state["parent_asins"] if parent not in outside
    ]
    filtered["coverage"] = coverage_of(
        [expand_review(row) for row in kept], filtered["parent_asins"]
    )
    filtered["parents_outside_catalog"] = len(outside)
    filtered["reviews_dropped_outside_catalog"] = before - len(kept)
    filtered["outside_catalog_rule"] = OUTSIDE_RULE
    receipt = {
        "parents_outside_catalog": len(outside),
        "reviews_dropped": before - len(kept),
        "reviews_kept": len(kept),
        "products_with_reviews": sum(
            1 for count in filtered["coverage"].values() if count
        ),
    }
    return filtered, receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument(
        "--samples",
        type=Path,
        nargs="+",
        required=True,
        help="release samples, rewritten in place",
    )
    args = parser.parse_args()
    staged = staged_parents(os.environ["DATABASE_URL"], args.dataset_id)
    for path in args.samples:
        filtered, receipt = filter_sample(json.loads(path.read_text()), staged)
        path.write_text(json.dumps(filtered, ensure_ascii=False) + "\n")
        print(json.dumps({"file": path.name, **receipt}), flush=True)


if __name__ == "__main__":
    main()
