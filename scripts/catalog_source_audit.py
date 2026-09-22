#!/usr/bin/env python3
"""Inspect public product sources without loading Aurora or calling a model.

Coverage is evidence about fields, not a judgment that the fields are correct.
The conservative title screens below identify records for manual review; they
must never supply a product's category or a boolean capability at ingestion.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import tarfile
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Listing:
    """One source-native identity, with no cross-source identity assumptions."""

    identity: tuple[str, str]
    title: str
    description: Any
    features: Any
    details: Any
    images: Any
    price: Any
    types: tuple[str, ...] = ()


def present(value: Any) -> bool:
    """Count missing sentinels as absent without treating false or zero as null."""
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() not in {"", "none", "null", "nan", "n/a"}
    if isinstance(value, (dict, list, tuple)):
        return bool(value)
    return True


def _english_values(row: dict[str, Any], field: str) -> list[str]:
    return [
        str(item["value"])
        for item in row.get(field, [])
        if item.get("language_tag") == "en_US" and present(item.get("value"))
    ]


def abo_listing(row: dict[str, Any]) -> Listing:
    """Preserve ABO's documented composite key of item ID and marketplace."""
    return Listing(
        identity=(str(row.get("item_id") or ""), str(row.get("domain_name") or "")),
        title=" ".join(_english_values(row, "item_name")),
        description=_english_values(row, "product_description"),
        features=_english_values(row, "bullet_point"),
        details={
            field: row[field]
            for field in ("item_dimensions", "item_weight", "material", "model_number")
            if present(row.get(field))
        },
        images=row.get("main_image_id"),
        price=None,
        types=tuple(str(item["value"]) for item in row.get("product_type", [])),
    )


def esci_listing(row: dict[str, Any]) -> Listing:
    """Keep ESCI's ASIN and locale key; the source supplies no image or price."""
    return Listing(
        identity=(
            str(row.get("product_id") or ""),
            str(row.get("product_locale") or ""),
        ),
        title=str(row.get("product_title") or ""),
        description=row.get("product_description"),
        features=row.get("product_bullet_point"),
        details=None,
        images=None,
        price=None,
    )


def reviews_listing(row: dict[str, Any]) -> Listing:
    """Retain the parent ASIN; it is not automatically an ESCI variant ASIN."""
    return Listing(
        identity=(str(row.get("parent_asin") or ""), "parent_asin"),
        title=str(row.get("title") or ""),
        description=row.get("description"),
        features=row.get("features"),
        details=row.get("details"),
        images=row.get("images"),
        price=row.get("price"),
    )


def title_screen(listing: Listing) -> str | None:
    """Screen likely devices separately from common accessories for review.

    This is deliberately not an ingestion classifier. For example a listing
    mentioning a microphone says nothing conclusive about active cancellation
    for the listener, and an image of a monitor says nothing about USB-C power.
    """
    title = listing.title.lower()
    if re.search(
        r"\b(ear\s*pads?|ear\s*cushions?|replacement cable|splitter|adapter|"
        r"privacy screen|screen filter|monitor (?:arm|stand|mount)|headphone jack)\b",
        title,
    ):
        return "accessory_title"
    if re.search(r"\b(?:office|desk|task|executive|computer|gaming) chair\b", title):
        return "office_chair_title"
    if "HEADPHONES" in listing.types or re.search(
        r"\b(headphones?|earphones?|earbuds?|headset)\b", title
    ):
        if re.search(r"\b(desk|stand|case|cover|cable)\b.*\bfor\b", title):
            return "accessory_title"
        return "headphone_title_or_type"
    if "MONITOR" in listing.types or re.search(r"\bmonitors?\b", title):
        return "monitor_title_or_type"
    return None


def summarize(listings: Iterable[Listing]) -> dict[str, Any]:
    """Count distinct source identities and missing fields with an execution witness.

    Args:
        listings: Source-normalized records, including their original key scope.

    Returns:
        Counts for all rows and the US/English pilot selection. Screen counts
        are not reviewed product-category totals or capability judgments.

    Raises:
        ValueError: The input is empty or contains a missing or repeated key.
    """
    identities: set[tuple[str, str]] = set()
    fields: Counter[str] = Counter()
    pilot_fields: Counter[str] = Counter()
    screens: Counter[str] = Counter()
    scopes: Counter[str] = Counter()
    types: Counter[str] = Counter()
    pilot = 0
    for listing in listings:
        if not all(listing.identity):
            raise ValueError(
                f"Source identity rule: found {listing.identity!r}; "
                "supply the original product ID and locale or identity type."
            )
        if listing.identity in identities:
            raise ValueError(
                f"Source identity rule: duplicate {listing.identity!r}; "
                "resolve repeated source records before sampling."
            )
        identities.add(listing.identity)
        scopes[listing.identity[1]] += 1
        types.update(listing.types)
        in_pilot = listing.identity[1] in {"us", "amazon.com", "parent_asin"}
        if in_pilot:
            pilot += 1
            screen = title_screen(listing)
            if screen:
                screens[screen] += 1
        for field in ("title", "description", "features", "details", "images", "price"):
            if present(getattr(listing, field)):
                fields[field] += 1
                if in_pilot:
                    pilot_fields[field] += 1
    if not identities:
        raise ValueError(
            "Source coverage rule: found 0 rows; supply a non-empty source file."
        )
    return {
        "rows_examined": len(identities),
        "identity_scopes": dict(sorted(scopes.items())),
        "nonempty_fields": dict(sorted(fields.items())),
        "pilot_rows": pilot,
        "pilot_nonempty_fields": dict(sorted(pilot_fields.items())),
        "pilot_title_screens": dict(sorted(screens.items())),
        "top_product_types": types.most_common(20),
        "limits": [
            "Nonempty fields may be inaccurate. Image links are not verified images.",
            "Title screens identify records to review, not certified product categories.",
            "Absent features remain unknown; neither false values nor specifications are inferred.",
            "Parent ASINs and variant ASINs are not interchangeable join keys.",
        ],
    }


def read_abo(path: Path) -> Iterator[Listing]:
    """Read JSON members in place so archive paths cannot write to the filesystem."""
    with tarfile.open(path) as archive:
        for member in archive:
            if not member.isfile() or not member.name.startswith("listings/metadata/"):
                continue
            if not member.name.endswith(".json.gz"):
                continue
            handle = archive.extractfile(member)
            if handle is None:
                continue
            with handle, gzip.GzipFile(fileobj=handle) as stream:
                for line in stream:
                    yield abo_listing(json.loads(line))


def read_reviews(path: Path) -> Iterator[Listing]:
    """Stream metadata only, without executing a dataset's remote loader code."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if "parent_asin" not in row or "rating" in row:
                raise ValueError(
                    f"Metadata input rule: line {number} is not product metadata; "
                    "use meta_<category>.jsonl, not a customer-review file."
                )
            yield reviews_listing(row)


def read_esci(path: Path) -> Iterator[Listing]:
    """Load Parquet in bounded batches; PyArrow is an optional audit dependency."""
    try:
        from pyarrow import parquet
    except ImportError as error:
        raise ValueError(
            "ESCI input rule: PyArrow is unavailable; run with "
            "uv run --no-project --with pyarrow==21.0.0 python."
        ) from error
    columns = [
        "product_id",
        "product_locale",
        "product_title",
        "product_description",
        "product_bullet_point",
    ]
    for batch in parquet.ParquetFile(path).iter_batches(
        batch_size=20_000, columns=columns
    ):
        for row in batch.to_pylist():
            yield esci_listing(row)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", choices=["abo", "esci", "reviews-2023"])
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--sampling", required=True, help="Full source, or exact sample method."
    )
    args = parser.parse_args()
    readers = {"abo": read_abo, "esci": read_esci, "reviews-2023": read_reviews}
    report = summarize(readers[args.source](args.input))
    with args.input.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    report.update(
        {"source": args.source, "input_sha256": digest, "sampling": args.sampling}
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"Inspected {report['rows_examined']:,} source identities; report: {args.output}"
    )


if __name__ == "__main__":
    main()
