"""Opt-in, read-only source inspection before a catalog is promoted to search."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException
from fastapi import Path as ApiPath

from service.catalog_runtime import active_dataset
from service.db import connect
from service.source_catalog import (
    project_product,
    question_evidence,
    review_evidence,
    specification_evidence,
)

router = APIRouter(prefix="/api/catalog-staging", tags=["catalog-staging"])
_EXAMPLES = Path(__file__).resolve().parents[1] / "data/real-catalog-examples.json"
ParentAsin = Annotated[str, ApiPath(pattern=r"^[A-Za-z0-9]{10}$")]


def configured_dataset() -> str:
    dataset = os.getenv("MOSAIC_STAGED_CATALOG_DATASET", "").strip()
    if not dataset:
        raise HTTPException(404, "Staged catalog inspection is not enabled.")
    return dataset


def load_product(connection, dataset: str, parent_asin: str) -> dict:
    row = connection.execute(
        """
        SELECT parent_asin, source_department, original, source_record_sha256,
               image_url, embedding_text, embedding_text_sha256, embedding_model_key
        FROM mosaic_catalog_stage.product WHERE dataset_id=%s AND parent_asin=%s
    """,
        (dataset, parent_asin),
    ).fetchone()
    if row is None:
        raise HTTPException(
            404, "This exact parent product is not in the staged catalog."
        )
    return row


def product_evidence(
    connection, dataset: str, row: dict
) -> tuple[list[dict], list[dict]]:
    evidence = [specification_evidence(row)]
    present = connection.execute(
        "SELECT to_regclass('mosaic_catalog_stage.review_sample') IS NOT NULL AS present"
    ).fetchone()["present"]
    if not present:
        return evidence, []
    # A review is served only when a recorded sample imported it: by the
    # sample it names, or, for samples staged before that column existed, by
    # the id list inside the sample manifest.
    reviews = connection.execute(
        """
        SELECT e.* FROM mosaic_catalog_stage.review_evidence e
        WHERE e.dataset_id=%s AND e.parent_asin=%s
          AND EXISTS (
            SELECT 1 FROM mosaic_catalog_stage.review_sample s
            WHERE s.dataset_id=e.dataset_id
              AND (
                s.category = e.sample_category
                OR (e.sample_category IS NULL
                    AND s.sample_manifest->'evidence_ids' ? e.evidence_id)
              )
          )
        ORDER BY (e.original->>'rating')::numeric, e.evidence_id
    """,
        (dataset, row["parent_asin"]),
    ).fetchall()
    evidence.extend(review_evidence(review) for review in reviews)
    questions_present = connection.execute(
        "SELECT to_regclass('mosaic_catalog_stage.question_evidence') IS NOT NULL AS present"
    ).fetchone()["present"]
    if questions_present:
        questions = connection.execute(
            """
            SELECT q.* FROM mosaic_catalog_stage.question_evidence q
            WHERE q.dataset_id=%s AND q.parent_asin=%s
            ORDER BY q.question_id
            """,
            (dataset, row["parent_asin"]),
        ).fetchall()
        evidence.extend(question_evidence(question) for question in questions)
    samples = connection.execute(
        """
        SELECT s.category, s.sample_manifest, p.reviews_selected
        FROM mosaic_catalog_stage.review_sample s
        JOIN mosaic_catalog_stage.review_sample_parent p
          ON p.dataset_id=s.dataset_id AND p.category=s.category
        WHERE s.dataset_id=%s AND p.parent_asin=%s
        UNION ALL
        SELECT s.category, s.sample_manifest,
               (s.sample_manifest->'coverage'->>%s)::integer
        FROM mosaic_catalog_stage.review_sample s
        WHERE s.dataset_id=%s AND s.sample_manifest->'parent_asins' ? %s
        ORDER BY category
    """,
        (dataset, row["parent_asin"], row["parent_asin"], dataset, row["parent_asin"]),
    ).fetchall()
    coverage = [
        {
            "category": sample["category"],
            "reviews_selected": sample["reviews_selected"],
            "records_scanned": sample["sample_manifest"]["records_scanned"],
            "complete_source_scan": sample["sample_manifest"]["complete_source_scan"],
            "selection_policy": sample["sample_manifest"]["selection_policy"],
        }
        for sample in samples
    ]
    return evidence, coverage


@router.get("/examples")
def examples() -> dict:
    """Read reviewed identities from Aurora instead of reconstructing mock rows."""
    dataset = configured_dataset()
    selected = [
        row
        for row in json.loads(_EXAMPLES.read_text())["examples"]
        if row.get("selected_in_bulk")
    ]
    with connect() as connection:
        products = [
            {
                "group": item["group"],
                "display_model": item["model"],
                **project_product(
                    load_product(connection, dataset, item["product_id"])
                ),
            }
            for item in selected
        ]
    return {
        "dataset_id": dataset,
        "live_catalog_promoted": active_dataset() == dataset,
        "products": products,
    }


@router.get("/products/{parent_asin}")
def product(parent_asin: ParentAsin) -> dict:
    """Return traceable facts and separately attributed review experiences."""
    dataset = configured_dataset()
    with connect() as connection:
        row = load_product(connection, dataset, parent_asin)
        evidence, coverage = product_evidence(connection, dataset, row)
    return {
        "dataset_id": dataset,
        "live_catalog_promoted": active_dataset() == dataset,
        "product": project_product(row),
        "evidence": evidence,
        "review_coverage": coverage,
    }


@router.get("/products/{parent_asin}/evidence/{evidence_id}")
def evidence_record(parent_asin: ParentAsin, evidence_id: str) -> dict:
    """Resolve a source only within the parent product named by its citation."""
    result = product(parent_asin)
    for record in result["evidence"]:
        if record["evidence_id"] == evidence_id:
            return record
    raise HTTPException(
        404,
        "This evidence does not belong to the requested parent product or current sample.",
    )
