#!/usr/bin/env python3
"""Build the 200-product exact-photography manifest.

The manifest combines the fixed 120-product premium cohort with 80 exact-product
bindings selected for HNSW, Search, Discover, and lab paths. The focused binding
filenames come from `docs/hnsw-focused-product-prompts.md`; product identity
comes from the checked-in 500K catalog.

The premium cohort's upstream keys are normalized into readable asset names.
The focused set already uses product-id-qualified names, so those keys are
validated rather than rewritten.

Naming scheme
-------------
    <domain-prefix>-<subcategory-slug>-<discriminator>-<role>.<ext>

    ce-over-ear-headphones-auraluxe-h9-catalog-3x2.webp
    rf-carbon-racing-shoes-01-catalog-3x2.webp
    ho-standing-desks-01-detail-1x1.webp

`role` is `catalog-3x2` (grid/card) or `detail-1x1` (product page hero). The
domain prefix keeps the three workshop domains sorted together on disk, and the
subcategory segment means a directory listing reads as a shot list.

Usage
-----
    uv run python scripts/build_asset_labels.py
    uv run python scripts/build_asset_labels.py --check   # exit 1 if the plan drifts
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_COHORT = REPO / "db" / "data" / "premium_cohort_120.json"
DEFAULT_FOCUSED_PROMPTS = REPO / "docs" / "hnsw-focused-product-prompts.md"
DEFAULT_CATALOG_MANIFEST = REPO / "data" / "full" / "manifest.json"
DEFAULT_OUTPUT = REPO / "data" / "media" / "asset_labels_200.json"
RUNTIME_DIR = REPO / "ui" / "public" / "assets" / "images" / "mosaic"
# Every `import_batch_*.csv` in data/media is a provenance record for one
# generation batch. Globbing rather than naming one file means a new batch is
# picked up without editing this script; a hardcoded path silently dropped the
# provenance of every batch after the first.
IMPORT_MANIFEST_GLOB = "import_batch_*.csv"
IMPORT_MANIFEST_DIR = REPO / "data" / "media"
SHOP_PAGE_SIZE = 12

DOMAIN_PREFIX = {
    "consumer_electronics": "ce",
    "running_fitness": "rf",
    "home_office": "ho",
}

# Flagships keep the merchandising name as their discriminator; it is the name
# the UI shows and the workshop script says out loud.
FLAGSHIP_SLUGS = {
    1: "auraluxe-h9",
    17001: "echobud-s2",
    116001: "pulse-one",
    234001: "stride-pro",
    370001: "forma-ergonomic",
    420001: "atelier-32",
}


def slugify(value: str) -> str:
    """Lowercase, ASCII-only, hyphen-separated."""
    cleaned = re.sub(r"[&/]", " ", value.lower())
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned)
    return cleaned.strip("-")


def build_labels(cohort: list[dict]) -> list[dict]:
    """Return one label record per cohort product, in cohort order."""
    domain_sequences: Counter[str] = Counter()
    # Products sharing a subcategory need a stable discriminator. Sorting by
    # product_id first means the numbering does not shuffle between runs.
    by_subcategory: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in sorted(cohort, key=lambda r: r["product_id"]):
        by_subcategory[(row["domain"], row["subcategory"])].append(row)

    labels: dict[int, dict] = {}
    for (domain, subcategory), rows in by_subcategory.items():
        prefix = DOMAIN_PREFIX[domain]
        sub_slug = slugify(subcategory)
        for index, row in enumerate(rows, start=1):
            product_id = row["product_id"]
            domain_sequences[domain] += 1
            asset_id = f"{prefix.upper()}-{domain_sequences[domain]:03d}"
            flagship = FLAGSHIP_SLUGS.get(product_id)
            # Non-flagships in a single-product subcategory need no number.
            if flagship:
                discriminator = flagship
            elif len(rows) == 1:
                discriminator = ""
            else:
                discriminator = f"{index:02d}"

            stem = "-".join(part for part in (prefix, sub_slug, discriminator) if part)
            labels[product_id] = {
                "asset_id": asset_id,
                "product_id": product_id,
                "domain": domain,
                "category": row["category"],
                "subcategory": subcategory,
                "merchandising_title": row["merchandising_title"],
                "source_title": row["source_title"],
                "media_tier": row["media_tier"],
                "shop_page": row["shop_page"],
                "shop_position": row["shop_position"],
                "is_flagship": row["is_flagship"],
                "is_retrieval_anchor": row["is_retrieval_anchor"],
                "asset_stem": stem,
                "catalog_asset_key": f"{stem}-catalog-3x2",
                "catalog_runtime": f"{stem}-catalog-3x2.webp",
                "catalog_runtime_path": (
                    f"/assets/images/mosaic/{stem}-catalog-3x2.webp"
                ),
                # Only flagships get a square detail hero; the other 114 are
                # only ever seen in a 3:2 card frame.
                "detail_asset_key": f"{stem}-detail-1x1"
                if row["is_flagship"]
                else None,
                "detail_runtime": f"{stem}-detail-1x1.webp"
                if row["is_flagship"]
                else None,
                "upstream_catalog_asset_key": row["catalog_asset_key"],
            }

    return [labels[row["product_id"]] for row in cohort]


def focused_bindings(path: Path) -> list[tuple[int, str]]:
    """Return the 80 prompt-defined product IDs and catalog filenames."""
    pattern = re.compile(
        r"```text\nPRODUCT ID: (\d+)\n.*?"
        r"SAVE AS: ([^\n]+-catalog-3x2\.png)\n```",
        re.DOTALL,
    )
    bindings = [
        (int(product_id), filename)
        for product_id, filename in pattern.findall(path.read_text(encoding="utf-8"))
    ]
    if len(bindings) != 80:
        raise ValueError(
            f"{path.relative_to(REPO)} declares {len(bindings)} focused bindings; "
            "expected 80"
        )
    product_ids = [product_id for product_id, _ in bindings]
    filenames = [filename for _, filename in bindings]
    if len(set(product_ids)) != len(product_ids):
        raise ValueError("focused photography repeats a product ID")
    if len(set(filenames)) != len(filenames):
        raise ValueError("focused photography repeats a SAVE AS filename")
    return bindings


def catalog_rows(
    product_ids: set[int],
    manifest_path: Path,
) -> dict[int, dict[str, str]]:
    """Load the requested product rows from the checked-in catalog shards."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    found: dict[int, dict[str, str]] = {}
    for relative_path in manifest["full_datasets"]:
        with gzip.open(
            REPO / relative_path,
            "rt",
            encoding="utf-8",
            newline="",
        ) as source:
            for row in csv.DictReader(source):
                product_id = int(row["product_id"])
                if product_id in product_ids:
                    found[product_id] = row
    missing = product_ids - set(found)
    if missing:
        raise ValueError(
            f"focused photography product IDs are absent from the catalog: "
            f"{sorted(missing)}"
        )
    return found


def build_focused_labels(
    bindings: list[tuple[int, str]],
    products: dict[int, dict[str, str]],
    cohort_labels: list[dict],
) -> list[dict]:
    """Build exact-product media records for the focused 80-product set."""
    domain_sequences = Counter(row["domain"] for row in cohort_labels)
    focused: list[dict] = []
    for product_id, filename in bindings:
        row = products[product_id]
        prefix = DOMAIN_PREFIX[row["domain"]]
        expected_prefix = f"{prefix}-{slugify(row['subcategory'])}-p{product_id}"
        stem = filename.removesuffix(".png").removesuffix("-catalog-3x2")
        if stem != expected_prefix:
            raise ValueError(
                f"focused product {product_id} filename stem is {stem!r}; "
                f"expected {expected_prefix!r}"
            )
        domain_sequences[row["domain"]] += 1
        focused.append(
            {
                "asset_id": (f"{prefix.upper()}-{domain_sequences[row['domain']]:03d}"),
                "product_id": product_id,
                "domain": row["domain"],
                "category": row["category"],
                "subcategory": row["subcategory"],
                "merchandising_title": row["title"],
                "source_title": row["title"],
                "media_tier": "premium",
                "binding_source": "focused_hnsw_search",
                "shop_page": None,
                "shop_position": None,
                "is_flagship": False,
                "is_retrieval_anchor": False,
                "asset_stem": stem,
                "catalog_asset_key": f"{stem}-catalog-3x2",
                "catalog_runtime": f"{stem}-catalog-3x2.webp",
                "catalog_runtime_path": (
                    f"/assets/images/mosaic/{stem}-catalog-3x2.webp"
                ),
                "detail_asset_key": None,
                "detail_runtime": None,
                "upstream_catalog_asset_key": row["image_key"],
                "source_batch": "dat410-focused-2026-08-17",
                "source_filename": filename,
            }
        )
    return focused


def installed_stems() -> set[str]:
    """Runtime filenames already present, without extension."""
    if not RUNTIME_DIR.is_dir():
        return set()
    return {path.stem for path in RUNTIME_DIR.glob("*.webp")}


def assign_shop_positions(labels: list[dict]) -> None:
    """Place every photographed product into the browsable Shop edit."""
    for index, row in enumerate(labels):
        row["shop_page"] = index // SHOP_PAGE_SIZE + 1
        row["shop_position"] = index % SHOP_PAGE_SIZE + 1


def report(labels: list[dict]) -> dict:
    have = installed_stems()
    needed_catalog = [row for row in labels if row["catalog_runtime"][:-5] not in have]
    needed_detail = [
        row
        for row in labels
        if row["detail_runtime"] and row["detail_runtime"][:-5] not in have
    ]
    return {
        "products": len(labels),
        "by_domain": dict(Counter(row["domain"] for row in labels)),
        "catalog_images_required": len(labels),
        "detail_images_required": sum(1 for row in labels if row["detail_runtime"]),
        "catalog_still_to_generate": len(needed_catalog),
        "detail_still_to_generate": len(needed_detail),
        "total_still_to_generate": len(needed_catalog) + len(needed_detail),
    }


def import_provenance() -> dict[str, dict[str, str]]:
    """Map runtime filename to its generation-batch record.

    Later batches win on collision: re-importing an asset is a deliberate
    replacement, so the newest manifest naming it describes the file on disk.
    """
    provenance: dict[str, dict[str, str]] = {}
    for manifest in sorted(IMPORT_MANIFEST_DIR.glob(IMPORT_MANIFEST_GLOB)):
        with manifest.open(newline="", encoding="utf-8") as source:
            for row in csv.DictReader(source):
                if row.get("output_filename"):
                    provenance[row["output_filename"]] = row
    return provenance


def attach_runtime_status(labels: list[dict]) -> None:
    provenance = import_provenance()
    for row in labels:
        runtime = RUNTIME_DIR / row["catalog_runtime"]
        row["catalog_installed"] = runtime.is_file()
        row["catalog_sha256"] = (
            hashlib.sha256(runtime.read_bytes()).hexdigest()
            if runtime.is_file()
            else None
        )
        imported = provenance.get(row["catalog_runtime"])
        row["source_batch"] = (
            imported["source_batch"] if imported else row.get("source_batch")
        )
        row["source_filename"] = (
            imported["source_filename"] if imported else row.get("source_filename")
        )

        detail_name = row["detail_runtime"]
        detail = RUNTIME_DIR / detail_name if detail_name else None
        row["detail_installed"] = bool(detail and detail.is_file())
        row["detail_sha256"] = (
            hashlib.sha256(detail.read_bytes()).hexdigest()
            if detail and detail.is_file()
            else None
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cohort",
        type=Path,
        default=DEFAULT_COHORT,
        help="fixed 120-product premium cohort",
    )
    parser.add_argument(
        "--focused-prompts",
        type=Path,
        default=DEFAULT_FOCUSED_PROMPTS,
        help="prompt document containing the 80 focused SAVE AS bindings",
    )
    parser.add_argument(
        "--catalog-manifest",
        type=Path,
        default=DEFAULT_CATALOG_MANIFEST,
        help="catalog package manifest used to resolve focused product identity",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail instead of writing when the plan would change",
    )
    args = parser.parse_args()

    cohort = json.loads(args.cohort.read_text())
    cohort_labels = build_labels(cohort)
    bindings = focused_bindings(args.focused_prompts)
    products = catalog_rows(
        {product_id for product_id, _ in bindings},
        args.catalog_manifest,
    )
    labels = cohort_labels + build_focused_labels(
        bindings,
        products,
        cohort_labels,
    )
    assign_shop_positions(labels)
    attach_runtime_status(labels)

    collisions = [
        key
        for key, count in Counter(r["asset_stem"] for r in labels).items()
        if count > 1
    ]
    if collisions:
        print(f"FAIL: duplicate asset stems: {collisions}", file=sys.stderr)
        return 1

    summary = report(labels)
    payload = {
        "version": 2,
        "naming_scheme": "<domain>-<subcategory>-<discriminator>-<role>",
        "binding_sets": {
            "premium_cohort": 120,
            "focused_hnsw_search": 80,
        },
        "summary": summary,
        "products": labels,
    }
    serialized = json.dumps(payload, indent=2) + "\n"

    if args.check:
        if not args.output.exists() or args.output.read_text() != serialized:
            print(
                "FAIL: asset labels are stale; re-run without --check", file=sys.stderr
            )
            return 1
        print("asset labels up to date")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(serialized)
    print(json.dumps(summary, indent=2))
    print(f"\nwrote {args.output.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
