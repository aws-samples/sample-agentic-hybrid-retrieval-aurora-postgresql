#!/usr/bin/env python3
"""Review and repair derived category filters without rewriting source records.

Run without --apply to save a plan. Apply that exact plan with --expected-plan.
The transaction preserves every other search column, including vector bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.prepare_staged_catalog_search import PROJECTION_SQL, require_complete
from scripts.stage_real_catalog import require_aurora_writer, validate_dsn
from service.source_catalog import product_kind


def require_preserved(expected: int, present: int, changed: int) -> None:
    """Reject removed rows or any non-category change, even if counts agree."""
    if present != expected or changed:
        raise ValueError(
            f"Category preservation rule: expected {expected} rows, found {present}, "
            f"with {changed} other-column changes; roll back and inspect the projection."
        )


def reconcile(conn, dataset_id: str, *, apply: bool, expected_plan: str | None) -> dict:
    """Bind a reviewed category plan to its source selection and apply atomically.

    Args:
        conn: Aurora writer connection with the dataset writer lock.
        dataset_id: Verified catalog selection to reconcile.
        apply: Whether to update the derived projection inside this transaction.
        expected_plan: SHA-256 returned by the preceding review run.

    Returns:
        Category changes, unchanged-column checks and the new projection hash.
    """
    if apply:
        conn.execute(
            "LOCK TABLE mosaic_catalog_search.product_document IN SHARE ROW EXCLUSIVE MODE"
        )
    dataset = conn.execute(
        "SELECT expected_products,records_complete,embeddings_complete,catalog_sha256 "
        "FROM mosaic_catalog_stage.dataset WHERE dataset_id=%s",
        (dataset_id,),
    ).fetchone()
    actual = conn.execute(
        "SELECT count(*) FROM mosaic_catalog_search.product_document WHERE dataset_id=%s",
        (dataset_id,),
    ).fetchone()[0]
    require_complete(dataset, actual)
    receipt = conn.execute(
        "SELECT dataset_id,catalog_sha256,projection_sha256 FROM mosaic_catalog_search.receipt"
    ).fetchall()
    if len(receipt) != 1 or receipt[0][:2] != (dataset_id, dataset[3]):
        raise ValueError(
            "Category selection rule: search receipt does not match the verified dataset; "
            "inspect the active selection before changing filters."
        )
    paths = conn.execute(
        """
        SELECT p.categories,d.category_key,count(*)
        FROM mosaic_catalog_search.product_document d
        JOIN mosaic_catalog_stage.product p USING(dataset_id,parent_asin)
        WHERE d.dataset_id=%s
        GROUP BY p.categories,d.category_key ORDER BY p.categories,d.category_key
    """,
        (dataset_id,),
    ).fetchall()
    require_preserved(actual, sum(count for _, _, count in paths), 0)
    changes = [
        {
            "categories": path,
            "before": old,
            "after": product_kind(path),
            "products": count,
        }
        for path, old, count in paths
        if old != product_kind(path)
    ]
    projection_hash = hashlib.sha256(
        (PROJECTION_SQL + inspect.getsource(product_kind)).encode()
    ).hexdigest()
    plan = {
        "dataset_id": dataset_id,
        "catalog_sha256": dataset[3],
        "previous_projection_sha256": receipt[0][2],
        "projection_sha256": projection_hash,
        "total_products": actual,
        "changed_products": sum(change["products"] for change in changes),
        "changes": changes,
    }
    plan_hash = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    report = {**plan, "plan_sha256": plan_hash, "applied": False}
    if not apply:
        return report
    if expected_plan != plan_hash:
        raise ValueError(
            f"Category plan rule: expected {expected_plan!r}, current plan is {plan_hash}; "
            "review a fresh plan and pass its hash before applying."
        )
    conn.execute(
        "CREATE TEMP TABLE category_repairs (categories text[] PRIMARY KEY, kind text) ON COMMIT DROP"
    )
    with conn.cursor().copy("COPY category_repairs FROM STDIN") as copy:
        for path in sorted({tuple(change["categories"]) for change in changes}):
            copy.write_row((list(path), product_kind(list(path))))
    # Hash the complete row minus the one field we intend to change. Checking
    # only stored source hashes would miss an accidental vector or text rewrite.
    conn.execute(
        """CREATE TEMP TABLE category_before ON COMMIT DROP AS
        SELECT d.product_id,md5((to_jsonb(d)-'category_key')::text) AS row_hash
        FROM mosaic_catalog_search.product_document d
        JOIN mosaic_catalog_stage.product p USING(dataset_id,parent_asin)
        JOIN category_repairs r ON p.categories=r.categories
        WHERE d.dataset_id=%s AND d.category_key IS DISTINCT FROM r.kind
    """,
        (dataset_id,),
    )
    updated = conn.execute(
        """UPDATE mosaic_catalog_search.product_document d
        SET category_key=r.kind
        FROM mosaic_catalog_stage.product p,category_repairs r
        WHERE d.dataset_id=%s AND p.dataset_id=d.dataset_id AND p.parent_asin=d.parent_asin
          AND p.categories=r.categories AND d.category_key IS DISTINCT FROM r.kind
    """,
        (dataset_id,),
    ).rowcount
    checked, changed = conn.execute("""SELECT count(d.product_id),count(*) FILTER (
        WHERE b.row_hash IS DISTINCT FROM md5((to_jsonb(d)-'category_key')::text))
        FROM category_before b LEFT JOIN mosaic_catalog_search.product_document d USING(product_id)
    """).fetchone()
    require_preserved(plan["changed_products"], updated, 0)
    require_preserved(updated, checked, changed)
    conn.execute(
        """UPDATE mosaic.category c SET display_name=d.category_key
        FROM (SELECT DISTINCT domain,category_path,category_key
              FROM mosaic_catalog_search.product_document WHERE dataset_id=%s) d
        WHERE c.category_key='reviews-2023:'||md5(d.domain::text||':'||d.category_path)
          AND c.display_name IS DISTINCT FROM d.category_key
    """,
        (dataset_id,),
    )
    conn.execute(
        "UPDATE mosaic_catalog_search.receipt SET projection_sha256=%s WHERE singleton",
        (projection_hash,),
    )
    return {
        **report,
        "applied": True,
        "other_columns_checked": checked,
        "other_column_changes": changed,
        "embeddings_regenerated": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-plan")
    args = parser.parse_args()
    dsn = os.environ.get("DATABASE_URL", "")
    validate_dsn(dsn)
    with psycopg.connect(
        dsn, connect_timeout=10, application_name="mosaic-category-reconcile"
    ) as conn:
        require_aurora_writer(conn, args.dataset_id)
        report = reconcile(
            conn, args.dataset_id, apply=args.apply, expected_plan=args.expected_plan
        )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "changes"}))


if __name__ == "__main__":
    main()
