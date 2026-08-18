import csv
import gzip
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from scripts.media_manifest import iter_media_records, normalize_asset_url

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "ui" / "public"
MAPPING = ROOT / "data" / "full" / "product_image_urls.csv.gz"
PRODUCT_MEDIA = ROOT / "data" / "media" / "asset_labels_200.json"

SHOWCASE = {
    1: ("Mosaic Auraluxe H9 Premium Wireless Headphones", "auraluxe-h9.webp"),
    17_001: ("Mosaic EchoBud S2 Premium Wireless Earbuds", "echobud-s2.webp"),
    116_001: ("Mosaic Pulse One Health & Fitness Smartwatch", "pulse-one.webp"),
    210_001: ("Mosaic Stride Pro Performance Running Shoes", "stride-pro.webp"),
    370_001: ("Mosaic Forma Ergonomic Office Chair", "forma-ergonomic.webp"),
    420_001: ("Mosaic Atelier 32 Premium Workspace Display", "atelier-32.webp"),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_mosaic_showcase_products_and_assets_match():
    products = {
        int(item["product_id"]): item
        for item in json.loads(
            (ROOT / "data/curated/demo_products.json").read_text(encoding="utf-8")
        )
    }
    for product_id, (title, image_key) in SHOWCASE.items():
        assert products[product_id]["brand"] == "Mosaic"
        assert products[product_id]["title"] == title
        assert products[product_id]["image_key"] == image_key

    expected_hashes = {
        "mosaic/echobud-s2.webp": "b517ebdf1418050f1770032d0a7f1c0d6a320bd7482f4fa27685331d34643731",
        "mosaic/pulse-one.webp": "de888bab65dc3d2b3bc124482d3e7bdb36f32ab607142e40b491a7ae5ed8f666",
        "mosaic/stride-pro.webp": "86e43e7372cdbcbab73c41f275995e5822eab02ba4354c9881b9dbeab020e366",
        "mosaic/atelier-32.webp": "c905713ae271cfd2feaa0f5b73a8edcb97c3f162c97388554ce94e4293a116d3",
    }
    for relative, expected in expected_hashes.items():
        assert digest(PUBLIC / "assets/images" / relative) == expected


def test_media_mapping_covers_every_product_with_local_assets():
    media_manifest = json.loads(PRODUCT_MEDIA.read_text(encoding="utf-8"))
    installed = [
        item for item in media_manifest["products"] if item["catalog_installed"]
    ]
    installed_by_id = {item["product_id"]: item for item in installed}
    flagship_count = sum(item["is_flagship"] for item in installed)
    source_counts: Counter[str] = Counter()
    product_ids: set[int] = set()
    image_urls: set[str] = set()
    showcase_urls: dict[int, str] = {}
    with gzip.open(MAPPING, "rt", encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            product_id = int(row["product_id"])
            product_ids.add(product_id)
            source_counts[row["image_source"]] += 1
            image_url = normalize_asset_url(row["image_url"])
            image_urls.add(image_url)
            if product_id in SHOWCASE:
                showcase_urls[product_id] = image_url

    assert len(product_ids) == 500_000
    assert source_counts == Counter(
        {
            "category_fallback": 500_000 - len(installed),
            "product_bound": len(installed) - flagship_count,
            "mosaic_showcase": flagship_count,
        }
    )
    assert showcase_urls == {
        product_id: installed_by_id[product_id]["catalog_runtime_path"]
        for product_id in SHOWCASE
    }
    assert all((PUBLIC / url.lstrip("/")).is_file() for url in image_urls)


def test_product_bound_manifest_is_one_truthful_200_product_contract():
    manifest = json.loads(PRODUCT_MEDIA.read_text(encoding="utf-8"))
    products = manifest["products"]
    installed = [item for item in products if item["catalog_installed"]]

    assert manifest["version"] == 2
    assert manifest["binding_sets"] == {
        "premium_cohort": 120,
        "focused_hnsw_search": 80,
    }
    assert manifest["summary"]["products"] == len(products) == 200
    assert len({item["product_id"] for item in products}) == 200
    assert len({item["catalog_asset_key"] for item in products}) == 200
    assert Counter(item["shop_page"] for item in products) == Counter(
        {**{page: 12 for page in range(1, 17)}, 17: 8}
    )
    assert [(item["shop_page"], item["shop_position"]) for item in products] == [
        (index // 12 + 1, index % 12 + 1) for index in range(200)
    ]
    assert manifest["summary"]["catalog_still_to_generate"] == 200 - len(installed)

    for item in installed:
        runtime = PUBLIC / item["catalog_runtime_path"].lstrip("/")
        assert runtime.is_file()
        assert digest(runtime) == item["catalog_sha256"]

    focused = {
        item["source_filename"]
        for item in products
        if item.get("binding_source") == "focused_hnsw_search"
    }
    prompt_filenames = {
        match.group(1)
        for match in re.finditer(
            r"^SAVE AS: ([^\s]+\.png)$",
            (ROOT / "docs/hnsw-focused-product-prompts.md").read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    }
    assert focused == prompt_filenames


def test_the_manifest_emits_only_approved_hashed_local_media():
    """Every mapped asset must exist on disk and be content-addressed.

    A retired photograph that stays mapped is invisible otherwise: the dev server
    answers a missing asset with `index.html` and a 200, so the grid renders empty
    boxes and no other check fails. `_asset_digest` raises instead.
    """
    roles: Counter[str] = Counter()
    rows = 0
    for record in iter_media_records():
        rows += 1
        roles[record.role] += 1
        assert record.publication_status == "approved"
        assert len(record.asset_sha256) == 64
        assert record.image_url.startswith("/assets/images/")
    assert rows == 500_007
    assert roles == Counter({"primary": 500_000, "gallery": 6, "detail": 1})


def test_landing_hero_is_the_unmodified_source_asset():
    hero = PUBLIC / "assets/images/mosaic/hero-editorial-mosaic.webp"
    assert (
        digest(hero)
        == "57aced551056a574340e081d9162d25b339f99f122ba0db0449e3517dec24044"
    )
