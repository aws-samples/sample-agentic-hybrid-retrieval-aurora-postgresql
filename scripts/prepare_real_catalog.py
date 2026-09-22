#!/usr/bin/env python3
"""Select distinct real products while preserving source fields unchanged."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import heapq
import json
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fetch_catalog_metadata import REVISION, SOURCES, iter_records


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def source_image(record: dict) -> str | None:
    """Use the source's primary photograph, preferring its full-resolution URL."""
    for image in record.get("images") or []:
        if not isinstance(image, dict) or image.get("variant") != "MAIN":
            continue
        for field in ("hi_res", "large"):
            url = image.get(field)
            if not isinstance(url, str):
                continue
            try:
                parsed = urlsplit(url)
            except ValueError:
                continue
            if (
                parsed.scheme == "https"
                and parsed.hostname
                and not parsed.username
                and not parsed.password
            ):
                return url
    return None


def embedding_text(record: dict) -> str:
    """Build a separate text projection; never modify the original source object."""
    parts = [f"Title: {record['title']}"]
    if record.get("categories"):
        parts.append("Categories: " + " > ".join(record["categories"]))
    for key, label in (
        ("description", "Description"),
        ("features", "Listing features"),
    ):
        if record.get(key):
            parts.append(label + ":\n" + "\n".join(record[key]))
    if record.get("details"):
        parts.append(
            "Specifications:\n"
            + "\n".join(
                f"{key}: {value if isinstance(value, str) else canonical(value)}"
                for key, value in sorted(record["details"].items())
            )
        )
    return "\n\n".join(parts)


def rejection_reason(record: dict, plan: dict) -> str | None:
    """Reject missing evidence rather than filling product facts with inventions."""
    if not isinstance(record, dict):
        return "invalid_record"
    if (
        not isinstance(record.get("parent_asin"), str)
        or not record["parent_asin"].strip()
    ):
        return "missing_identity"
    if not isinstance(record.get("title"), str) or not record["title"].strip():
        return "missing_title"
    for key in ("features", "description", "categories"):
        if not isinstance(record.get(key), list) or not all(
            isinstance(value, str) for value in record[key]
        ):
            return "invalid_text_fields"
    if not isinstance(record.get("details"), dict):
        return "invalid_specifications"
    if not source_image(record):
        return "missing_primary_image"
    if (
        len("\n".join(record["features"] + record["description"]).strip())
        < plan["minimum_source_text_characters"]
    ):
        return "insufficient_source_text"
    if len(embedding_text(record)) > plan["maximum_embedding_characters"]:
        return "over_embedding_text_budget"
    return None


def select_ids(
    records, amount: int, plan: dict, excluded: set[str]
) -> tuple[set[str], dict]:
    """Choose the lowest stable hashes so file order cannot decide the sample."""
    if amount < 1:
        raise ValueError("Selection size rule: request at least one product.")
    selected: list[tuple[int, str]] = []
    seen: set[str] = set()
    reasons: Counter[str] = Counter()
    total = 0
    eligible = 0
    for record in records:
        total += 1
        identity = record.get("parent_asin") if isinstance(record, dict) else None
        if isinstance(identity, str) and identity in seen:
            raise ValueError(
                f"Distinct product rule: repeated parent ASIN {identity}; inspect the pinned source."
            )
        if isinstance(identity, str):
            seen.add(identity)
        reason = rejection_reason(record, plan)
        if reason:
            reasons[reason] += 1
            continue
        if identity in excluded:
            reasons["already_selected_from_another_department"] += 1
            continue
        eligible += 1
        priority = -int(sha256(plan["selection_seed"] + ":" + identity), 16)
        item = (priority, identity)
        if len(selected) < amount:
            heapq.heappush(selected, item)
        elif item > selected[0]:
            heapq.heapreplace(selected, item)
    if len(selected) != amount:
        raise ValueError(
            f"Selection coverage rule: only {eligible} eligible distinct products; "
            f"requested {amount}. Add an appropriate source or lower the declared count."
        )
    return {item[1] for item in selected}, {
        "source_rows": total,
        "eligible_products": eligible,
        "selected_products": amount,
        "excluded_counts": dict(sorted(reasons.items())),
    }


def write_selection(
    source_root: Path, temporary: Path, chosen: dict
) -> tuple[set, dict]:
    """Copy complete selected objects while recording their separate text projection."""
    text_characters = 0
    photo_resolution: Counter[str] = Counter()
    leaf_categories: Counter[str] = Counter()
    written: set[str] = set()
    with (
        temporary.open("wb") as raw,
        gzip.GzipFile(
            filename="", fileobj=raw, mode="wb", compresslevel=1, mtime=0
        ) as compressed,
    ):
        for category, identities in chosen.items():
            for record in iter_records(source_root / category):
                identity = record.get("parent_asin")
                if not isinstance(identity, str) or identity not in identities:
                    continue
                if identity in written:
                    raise ValueError(
                        f"Output identity rule: repeated {identity}; do not load the partial selection."
                    )
                text = embedding_text(record)
                image = source_image(record)
                row = {
                    "source": "amazon_reviews_2023",
                    "source_revision": REVISION,
                    "source_department": category,
                    "parent_asin": identity,
                    "source_record_sha256": sha256(canonical(record)),
                    "original": record,
                    "image_url": image,
                    "embedding_text": text,
                    "embedding_text_sha256": sha256(text),
                }
                compressed.write((canonical(row) + "\n").encode())
                written.add(identity)
                text_characters += len(text)
                leaf_categories[
                    record["categories"][-1] if record["categories"] else "Unspecified"
                ] += 1
                photo_resolution[
                    "source_high_resolution"
                    if any(
                        isinstance(photo, dict)
                        and photo.get("variant") == "MAIN"
                        and photo.get("hi_res") == image
                        for photo in record["images"]
                    )
                    else "source_large"
                ] += 1
    return written, {
        "embedding_text_characters": text_characters,
        "primary_image_fields": dict(photo_resolution),
        "selected_leaf_categories": dict(sorted(leaf_categories.items())),
    }


def prepare(source_root: Path, output: Path, plan: dict) -> None:
    """Publish the selection file only after every source passes its full checksum."""
    validate_plan(plan)
    if any(item["category"] not in SOURCES for item in plan["sources"]):
        raise ValueError(
            "Source plan rule: unpinned category; use a category in fetch_catalog_metadata.SOURCES."
        )
    if len({item["category"] for item in plan["sources"]}) != len(plan["sources"]):
        raise ValueError("Source plan rule: repeated department; use it once.")
    output.mkdir(parents=True, exist_ok=True)
    final = output / "catalog.jsonl.gz"
    if final.exists():
        raise ValueError(
            "Selection output rule: catalog already exists; verify and reuse it or choose a new output directory."
        )
    chosen: dict[str, set[str]] = {}
    reports = {}
    all_ids: set[str] = set()
    for item in plan["sources"]:
        category = item["category"]
        chosen[category], reports[category] = select_ids(
            iter_records(source_root / category),
            item["products"],
            plan,
            all_ids,
        )
        all_ids.update(chosen[category])
        print(json.dumps({"category": category, **reports[category]}), flush=True)
    temporary = output / "catalog.jsonl.gz.partial"
    written, coverage = write_selection(source_root, temporary, chosen)
    if written != all_ids:
        raise ValueError(
            "Selection output rule: selected and written identities differ; do not load the partial selection."
        )
    with temporary.open("rb") as selected_file:
        file_hash = hashlib.file_digest(selected_file, "sha256").hexdigest()
    manifest = {
        "plan": plan,
        "plan_sha256": sha256(canonical(plan)),
        "products": len(written),
        "source_reports": reports,
        "source_revision": REVISION,
        "catalog_sha256": file_hash,
        **coverage,
        "image_validation": "Source URLs selected; availability and visual correctness are not certified for all rows.",
        "embedding_status": "Not yet embedded",
        "publication_status": "Local assessment; source rights remain under review.",
    }
    temporary.replace(final)
    (output / "selection.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: manifest[key]
                for key in (
                    "products",
                    "catalog_sha256",
                    "embedding_text_characters",
                    "primary_image_fields",
                )
            }
        ),
        flush=True,
    )


def validate_plan(plan: dict) -> None:
    """Reject ambiguous selection plans before reading or publishing records."""
    if not isinstance(plan, dict) or plan.get("version") != 1:
        raise ValueError(
            "Source plan rule: expected version 1; use data/real-catalog-plan.json."
        )
    for key in ("minimum_source_text_characters", "maximum_embedding_characters"):
        value = plan.get(key)
        if type(value) is not int or value <= 0:
            raise ValueError(
                f"Source plan rule: {key}={value!r}; supply a positive integer."
            )
    if plan["minimum_source_text_characters"] > plan["maximum_embedding_characters"]:
        raise ValueError(
            "Source plan rule: minimum text exceeds maximum; correct the text budgets."
        )
    if not isinstance(plan.get("selection_seed"), str) or not plan["selection_seed"]:
        raise ValueError(
            "Source plan rule: missing selection_seed; supply a fixed nonempty seed."
        )
    sources = plan.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError(
            "Source plan rule: no sources; select at least one pinned department."
        )
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("category"), str):
            raise TypeError(
                "Source plan rule: invalid department; supply a category and product count."
            )
        amount = source.get("products")
        if type(amount) is not int or amount < 1:
            raise ValueError(
                f"Source plan rule: products={amount!r}; request a positive integer."
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--plan", type=Path, default=ROOT / "data/real-catalog-plan.json"
    )
    args = parser.parse_args()
    prepare(args.source_root, args.output, json.loads(args.plan.read_text()))


if __name__ == "__main__":
    main()
