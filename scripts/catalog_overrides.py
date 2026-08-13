"""Apply the curated Mosaic catalog overrides from their single source."""

from __future__ import annotations

import json
from typing import Any


SCALAR_FIELDS = (
    "brand",
    "model",
    "title",
    "short_description",
    "long_description",
    "price_usd",
    "list_price_usd",
    "rating",
    "review_count",
    "availability",
    "inventory_count",
    "seller_count",
    "shipping_days",
    "warranty_months",
    "image_key",
)


def compact(value: Any) -> str:
    """Encode a catalog collection in the source CSV representation."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def text_parts(
    row: dict[str, str],
    attributes: dict[str, Any],
    tags: list[str],
    aliases: list[str],
) -> tuple[str, str]:
    """Build searchable source text after a curated record changes."""
    attribute_text = " ".join(
        f"{key.replace('_', ' ')} "
        f"{' '.join(map(str, value)) if isinstance(value, list) else value}"
        for key, value in attributes.items()
    )
    search_text = " ".join(
        part
        for part in (
            row["title"],
            row["brand"],
            row["model"],
            row["category"],
            row["subcategory"],
            row["short_description"],
            " ".join(tags),
            " ".join(aliases),
            attribute_text,
        )
        if part
    )
    embedding_text = (
        f"{row['title']}. {row['short_description']} {row['long_description']} "
        f"Use cases and tags: {' '.join(tags)}. "
        f"Specifications: {compact(attributes)}"
    )
    return search_text, embedding_text


def apply_curated_override(row: dict[str, str], override: dict[str, Any]) -> None:
    """Apply one curated source record while preserving its stable identity."""
    for field in SCALAR_FIELDS:
        if field not in override:
            continue
        value = override[field]
        if field in {"price_usd", "list_price_usd"}:
            row[field] = f"{float(value):.2f}"
        elif field == "rating":
            row[field] = f"{float(value):.1f}"
        else:
            row[field] = str(value)

    attributes = override.get("attributes", json.loads(row["attributes_json"]))
    tags = override.get("tags", json.loads(row["tags_json"]))
    aliases = override.get("aliases", json.loads(row["aliases_json"]))
    cohorts = override.get(
        "challenge_cohorts", json.loads(row["challenge_cohorts_json"])
    )
    row["attributes_json"] = compact(attributes)
    row["tags_json"] = compact(tags)
    row["aliases_json"] = compact(aliases)
    row["challenge_cohorts_json"] = compact(cohorts)
    row["metadata_completeness"] = "1.0000"
    row["quality_score"] = "0.9700"
    row["freshness_score"] = "0.9400"
    row["popularity_score"] = "0.9200"
    row["return_rate"] = "0.0280"
    row["source_system"] = "curated_merchandising"
    row["search_text"], row["embedding_text"] = text_parts(
        row, attributes, tags, aliases
    )
