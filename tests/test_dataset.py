import csv
import gzip
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from scripts.catalog_contract import (
    SUPPORTED_FILTER_KEYS,
    product_matches_filters,
    unsupported_filter_keys,
)
from scripts.generate_catalog import ProductContext, specialized_attributes
from service.models import SearchFilters

ROOT = Path(__file__).resolve().parents[1]
SKU_PATTERN = re.compile(r"^[A-Z]{2}-[A-Z0-9]{1,5}-[0-9]{7}$")


def manifest() -> dict:
    return json.loads((ROOT / "data/full/manifest.json").read_text())


def catalog_paths() -> list[Path]:
    return [ROOT / path for path in manifest()["full_datasets"]]


def iter_products():
    for path in catalog_paths():
        with gzip.open(path, "rt", encoding="utf-8", newline="") as source:
            yield from csv.DictReader(source)


def test_manifest_counts_and_github_safe_shards():
    catalog_manifest = manifest()
    assert catalog_manifest["total_products"] == 500_000
    assert catalog_manifest["domain_counts"] == {
        "consumer_electronics": 210_000,
        "running_fitness": 160_000,
        "home_office": 130_000,
    }
    assert len(catalog_paths()) == 3
    assert all(path.is_file() for path in catalog_paths())
    assert all(path.stat().st_size < 100_000_000 for path in catalog_paths())


def test_full_catalog_identity_dates_skus_and_filter_targets():
    queries = [
        json.loads(line)
        for line in (ROOT / "data/evals/queries.jsonl").read_text().splitlines()
        if line.strip()
    ]
    target_filters: dict[int, list[tuple[str, dict]]] = defaultdict(list)
    for query in queries:
        target_filters[int(query["target_product_id"])].append(
            (query["query_id"], query["filters"])
        )
    target_matches: set[str] = set()
    product_uids: set[str] = set()
    skus: set[str] = set()
    domain_counts: Counter[str] = Counter()
    rows = 0

    for product in iter_products():
        rows += 1
        product_id = int(product["product_id"])
        product_uids.add(product["product_uid"])
        skus.add(product["sku"])
        domain_counts[product["domain"]] += 1
        assert product["updated_at"][:10] >= product["launch_date"]
        assert SKU_PATTERN.fullmatch(product["sku"])
        if product_id in target_filters:
            for query_id, filters in target_filters[product_id]:
                assert product_matches_filters(product, filters)
                target_matches.add(query_id)

    assert rows == 500_000
    assert len(product_uids) == rows
    assert len(skus) == rows
    assert domain_counts == Counter(manifest()["domain_counts"])
    assert target_matches == {query["query_id"] for query in queries}


def test_evaluation_filters_match_the_sql_contract():
    queries = [
        json.loads(line)
        for line in (ROOT / "data/evals/queries.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert len(queries) == 720
    assert all(not unsupported_filter_keys(query["filters"]) for query in queries)
    assert all(
        isinstance(query["filters"].get("attributes", {}), dict) for query in queries
    )
    for query in queries:
        SearchFilters.model_validate(query["filters"])

    sql = (ROOT / "db/sql/09_search_functions.sql").read_text(encoding="utf-8")
    assert SUPPORTED_FILTER_KEYS == set(SearchFilters.model_fields)
    for key in SUPPORTED_FILTER_KEYS:
        assert f"'{key}'" in sql, (
            f"{key} is accepted by SearchFilters but matches_filters never reads it"
        )


def test_balanced_sample():
    curated = {
        int(item["product_id"])
        for item in json.loads((ROOT / "data/curated/demo_products.json").read_text())
    }
    with gzip.open(
        ROOT / "data/sample/products_5000.csv.gz",
        "rt",
        encoding="utf-8",
        newline="",
    ) as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 5_000
    assert Counter(row["domain"] for row in rows) == Counter(
        {
            "consumer_electronics": 2_100,
            "running_fitness": 1_600,
            "home_office": 1_300,
        }
    )
    assert all(json.loads(row["attributes_json"]) for row in rows[:100])
    assert all(row["updated_at"][:10] >= row["launch_date"] for row in rows)
    assert all(SKU_PATTERN.fullmatch(row["sku"]) for row in rows)
    sample_by_id = {int(row["product_id"]): row for row in rows}
    assert curated <= set(sample_by_id)
    assert all(
        sample_by_id[product_id]["source_system"] == "curated_merchandising"
        for product_id in curated
    )


def test_typo_cases():
    with (ROOT / "data/evals/typo_cases.csv").open(newline="") as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 5_000
    assert len({row["typo_type"] for row in rows}) >= 5


def test_review_sample_matches_the_quick_start_catalog():
    product_ids = {int(row["product_id"]) for row in iter_products()}
    sample_ids: set[int] = set()
    with gzip.open(
        ROOT / "data/sample/products_5000.csv.gz",
        "rt",
        encoding="utf-8",
        newline="",
    ) as source:
        sample_ids = {int(row["product_id"]) for row in csv.DictReader(source)}
    with gzip.open(
        ROOT / "data/sample/reviews_15000.csv.gz",
        "rt",
        encoding="utf-8",
        newline="",
    ) as source:
        reviews = list(csv.DictReader(source))

    assert len(reviews) == 15_000
    assert {int(review["product_id"]) for review in reviews} == sample_ids
    assert sample_ids <= product_ids


def test_subcategory_routing_does_not_use_ambiguous_substrings():
    organizer = ProductContext(
        464423,
        "home_office",
        "Organization",
        "Desktop Organizers",
        423,
    )
    cable_management = ProductContext(
        467891,
        "home_office",
        "Organization",
        "Cable Management",
        1_891,
    )

    organizer_attributes, organizer_tags, *_ = specialized_attributes(
        organizer, random.Random(1), []
    )
    cable_attributes, cable_tags, *_ = specialized_attributes(
        cable_management, random.Random(1), []
    )

    assert organizer_tags == ["organization", "storage", "workspace"]
    assert cable_tags == ["organization", "storage", "workspace"]
    assert "moisture_wicking" not in organizer_attributes
    assert "max_power_w" not in cable_attributes


def test_exact_apparel_and_charging_subcategories_keep_their_specialization():
    running_top = ProductContext(
        261304,
        "running_fitness",
        "Apparel",
        "Running Tops",
        1_304,
    )
    charger = ProductContext(
        100001,
        "consumer_electronics",
        "Mobile & Power",
        "USB-C Chargers",
        1,
    )

    apparel_attributes, apparel_tags, *_ = specialized_attributes(
        running_top, random.Random(1), []
    )
    charger_attributes, charger_tags, *_ = specialized_attributes(
        charger, random.Random(1), []
    )

    assert "apparel" in apparel_tags
    assert apparel_attributes["moisture_wicking"] is True
    assert "charging" in charger_tags
    assert charger_attributes["usb_c_pd"] is True
