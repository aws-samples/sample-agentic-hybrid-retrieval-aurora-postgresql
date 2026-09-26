"""Source-faithful product and evidence projections for the staged catalog."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from scripts.fetch_catalog_metadata import REVISION
from scripts.prepare_real_catalog import canonical, embedding_text, sha256, source_image

SOURCE_NAME = "Amazon Reviews 2023"


def rerank_document(parent_asin: str, source_text: str) -> str:
    """Keep the source identity available when the model reorders search rows."""
    return f"Catalog identity: parent ASIN {parent_asin}.\n{source_text}"


def historical_price(value: Any) -> int | None:
    """Normalize reported USD amounts without turning missing prices into zero."""
    if value is None or (
        isinstance(value, str) and value.strip().lower() in {"", "none", "null", "—"}
    ):
        return None
    try:
        amount = Decimal(str(value))
        cents = amount * 100
        if not amount.is_finite() or amount < 0 or cents != cents.to_integral_value():
            raise InvalidOperation
        return int(cents)
    except InvalidOperation:
        raise ValueError(
            f"Source price rule: {value!r} is not a non-negative USD amount; keep it unnormalized and inspect the source."
        ) from None


def product_kind(categories: list[str]) -> str:
    """Use source taxonomy, never a compatible product name in accessory text."""
    leaf = categories[-1].casefold() if categories else ""
    if leaf == "monitors":
        return "monitor"
    if leaf in {"monitor arms", "monitor stands"}:
        return "monitor_stand"
    if leaf in {
        "over-ear headphones",
        "on-ear headphones",
        "earbud headphones",
        "open-ear headphones",
        "headphones & earbuds",
        "headphones",
        "computer headsets",
        "bluetooth headsets",
        "cell phone headsets",
        "car headphones",
    }:
        return "headphones"
    # A bicycle headset is a different product; a broad substring match would
    # also turn replacement parts and mixed accessory categories into products.
    if leaf == "headsets" and any(
        parent.casefold() in {"telephone accessories", "pc gaming accessories"}
        for parent in categories[:-1]
    ):
        return "headphones"
    if leaf in {
        "managerial & executive chairs",
        "home office desk chairs",
        "home office chairs",
        "desk chairs",
        "task chairs",
        "computer gaming chairs",
        "video game chairs",
        "gaming chairs",
        "kneeling chairs",
        "guest & reception chairs",
        "drafting chairs",
        "stacking chairs",
    }:
        return "chair"
    if leaf in {"chair mats", "carpet chair mats", "hard-floor chair mats"}:
        return "chair_mat"
    if leaf in {"cases", "headphone cases"} and any(
        "headphone" in part.casefold() for part in categories
    ):
        return "headphone_case"
    return "other"


def verify_source_product(row: dict) -> dict:
    """Bind every displayed fact to the preserved product and embedding inputs."""
    original = row["original"]
    if (
        original.get("parent_asin") != row["parent_asin"]
        or sha256(canonical(original)) != row["source_record_sha256"]
        or embedding_text(original) != row["embedding_text"]
        or sha256(row["embedding_text"]) != row["embedding_text_sha256"]
    ):
        raise ValueError(
            f"Source product integrity rule: {row['parent_asin']} changed; restore the selected source record and its hashed projection."
        )
    return original


def project_product(row: dict) -> dict:
    """Separate historical offers, source ratings and unreported current facts."""
    original = verify_source_product(row)
    if row["image_url"] != source_image(original):
        raise ValueError(
            f"Source photo rule: {row['parent_asin']} points outside its primary source image; restore the preserved photo URL."
        )
    details = original["details"]
    average, count = original.get("average_rating"), original.get("rating_number")
    rating = None
    if (
        type(average) in (int, float)
        and math.isfinite(average)
        and 1 <= average <= 5
        and type(count) is int
        and count > 0
    ):
        rating = {
            "average": average,
            "count": count,
            "basis": "historical_rating_aggregate",
        }
    brand = details.get("Brand")
    model = details.get("Model Name") or details.get("Item model number")
    condition = (
        "refurbished"
        if re.search(r"\b(?:renewed|refurbished)\b", original["title"], re.IGNORECASE)
        else "unspecified"
    )
    source_price = original.get("price")
    starting_price = isinstance(source_price, str) and source_price.startswith("from ")
    amount = historical_price(source_price[5:] if starting_price else source_price)
    return {
        "identity": f"amazon_reviews_2023:parent:{row['parent_asin']}",
        "parent_asin": row["parent_asin"],
        "identity_kind": "parent_asin",
        "source_name": SOURCE_NAME,
        "source_revision": REVISION,
        "source_record_sha256": row["source_record_sha256"],
        "embedding_text_sha256": row["embedding_text_sha256"],
        "title": original["title"],
        "brand": brand if isinstance(brand, str) and brand.strip() else None,
        "model": model if isinstance(model, str) and model.strip() else None,
        "categories": original["categories"],
        "product_kind": product_kind(original["categories"]),
        "condition": condition,
        "condition_source": "/title" if condition != "unspecified" else None,
        "description": original["description"],
        "features": original["features"],
        "specifications": details,
        "image_url": row["image_url"],
        "listing_url": f"https://www.amazon.com/dp/{row['parent_asin']}",
        "historical_price_cents": None if starting_price else amount,
        "historical_price_min_cents": amount if starting_price else None,
        "historical_price_basis": "starting_at"
        if starting_price
        else "exact"
        if amount is not None
        else "not_reported",
        "historical_price_source_value": source_price,
        "historical_price_currency": "USD",
        "current_price_cents": None,
        "availability": None,
        "inventory_count": None,
        "rating": rating,
        "embedded": row.get("embedding_model_key") is not None,
    }


def specification_evidence(row: dict) -> dict:
    """Reuse source text as evidence without rewriting it into stronger claims."""
    original = verify_source_product(row)
    return {
        "evidence_id": "spec-" + row["source_record_sha256"],
        "parent_asin": row["parent_asin"],
        "variant_asin": None,
        "evidence_type": "product_spec",
        "title": original["title"],
        "text": row["embedding_text"],
        "source_name": SOURCE_NAME,
        "source_revision": REVISION,
        "source_record_sha256": row["source_record_sha256"],
        "source_reference": "https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/"
        f"blob/{REVISION}/raw/meta_categories/meta_{row['source_department']}.jsonl",
        "source_date": None,
        "verified_purchase": None,
        "rating": None,
        "scope": "Historical parent-product listing. Confirm exact variant and current offer separately.",
    }


def question_evidence(row: dict) -> dict:
    """Expose a buyer question with its community answers as its own evidence kind.

    Answers are what other customers said, so the record is labelled as an
    opinion and never carries a rating or a purchase flag.
    """
    original = row["original"]
    if (
        sha256(canonical(original)) != row["source_record_sha256"]
        or original["asin"] != row["asin"]
    ):
        raise ValueError(
            f"Question boundary rule: {row['question_id']} has inconsistent source identity; restore its original record."
        )
    answers = original["answers"]
    text = "Question: " + original["question_text"] + "\n\nAnswer: " + answers[0]
    if len(answers) > 1:
        text += "\n\nOther answers:\n" + "\n".join(
            "- " + answer for answer in answers[1:]
        )
    return {
        "evidence_id": row["question_id"],
        "parent_asin": row["parent_asin"],
        "variant_asin": row["asin"] if row["asin"] != row["parent_asin"] else None,
        "evidence_type": "product_qa",
        "title": original["question_text"],
        "text": text,
        "source_name": "Amazon PQA",
        "source_revision": row.get("source_file_sha256"),
        "source_record_sha256": row["source_record_sha256"],
        "source_reference": row["source_reference"],
        "source_date": None,
        "verified_purchase": None,
        "rating": None,
        "answers": len(answers),
        "license": row.get("license"),
        "scope": "A buyer question and the answers other customers gave about the recorded listing; answers are opinions, not specifications.",
    }


def review_evidence(row: dict) -> dict:
    """Expose the source's review attribution without exposing reviewer identity."""
    original = row["original"]
    if (
        sha256(canonical(original)) != row["source_record_sha256"]
        or original["parent_asin"] != row["parent_asin"]
        or original["asin"] != row["variant_asin"]
    ):
        raise ValueError(
            f"Review product boundary rule: {row['evidence_id']} has inconsistent source identity; restore its original parent and variant."
        )
    return {
        "evidence_id": row["evidence_id"],
        "parent_asin": row["parent_asin"],
        "variant_asin": row["variant_asin"],
        "evidence_type": "customer_review",
        "title": original["title"],
        "text": original["text"],
        "source_name": SOURCE_NAME,
        "source_revision": REVISION,
        "source_record_sha256": row["source_record_sha256"],
        "source_reference": row["source_reference"],
        "source_location": row["source_location"],
        "source_date": datetime.fromtimestamp(original["timestamp"] / 1000, UTC)
        .date()
        .isoformat(),
        "verified_purchase": original["verified_purchase"],
        "rating": original["rating"],
        "helpful_votes": original["helpful_vote"],
        "scope": "One customer's experience of the recorded variant; it does not establish another variant's specifications.",
    }
