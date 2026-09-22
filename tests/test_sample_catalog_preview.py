"""Keep a visual sample faithful to selected source products and their gaps."""

import copy
import gzip
import hashlib
import json

import pytest

from scripts.prepare_real_catalog import canonical, embedding_text, sha256
from scripts.sample_catalog_preview import (
    build_preview,
    category,
    diverse_sample,
    preview_product,
)


def record(identity="PRODUCT1", brand="Source brand", leaf="Monitors", **changes):
    original = {
        "parent_asin": identity,
        "title": "Original source product",
        "categories": ["Electronics", leaf],
        "description": ["Original wording."],
        "features": ["One unchanged feature."],
        "details": {"Brand": brand, "Screen Size": "27 Inches"},
        "images": [
            {"variant": "MAIN", "hi_res": f"https://example.com/{identity}.jpg"}
        ],
        "average_rating": 4.4,
        "rating_number": 123,
        **changes,
    }
    text = embedding_text(original)
    return {
        "parent_asin": identity,
        "source_department": "Electronics",
        "original": original,
        "source_record_sha256": sha256(canonical(original)),
        "embedding_text": text,
        "embedding_text_sha256": sha256(text),
        "image_url": original["images"][0]["hi_res"],
    }


def test_sample_preserves_text_photos_ratings_and_missing_specifications():
    row = record()
    before = canonical(row)
    product = preview_product(row, "monitors")
    assert canonical(row) == before
    assert product["title"] == row["original"]["title"]
    assert product["originalDescription"] == "Original wording."
    assert product["originalBulletPoints"] == "One unchanged feature."
    assert product["image"] == row["image_url"]
    assert product["rating"] == {"average": 4.4, "count": 123}
    assert product["listingUrl"].endswith("/PRODUCT1")
    assert {fact["label"]: fact["value"] for fact in product["facts"]}[
        "Resolution"
    ] == "Not supplied"
    assert all("meetsNeed" not in fact for fact in product["facts"])
    assert "rating" not in preview_product(record(average_rating=None), "monitors")


def test_rewritten_source_or_another_products_photo_is_rejected():
    row = record()
    saved = canonical(row)
    row["original"]["description"] = ["Invented USB-C power delivery"]
    with pytest.raises(ValueError, match="Source product integrity rule"):
        preview_product(row, "monitors")
    row = json.loads(saved)
    assert canonical(row) == saved
    preview_product(row, "monitors")
    row["image_url"] = "https://example.com/another-product.jpg"
    with pytest.raises(ValueError, match="Preview photo rule"):
        preview_product(row, "monitors")


def test_accessories_are_excluded_even_when_source_category_is_broad():
    assert category(record()) == "monitors"
    assert category(record(leaf="Over-Ear Headphones")) == "headphones"
    assert category(record(leaf="Home Office Desk Chairs")) == "chairs"
    assert category(record(title="Monitor arm for 27-inch display")) is None
    assert (
        category(record(leaf="Over-Ear Headphones", title="Replacement ear pads"))
        is None
    )
    assert category(record(leaf="Cases", title="Case for headphones")) is None


def test_selection_is_repeatable_with_a_brand_cap_and_unique_photos():
    rows = [record(str(index), brand=f"Brand {index // 4}") for index in range(16)]
    rows[-1]["image_url"] = rows[0]["image_url"]
    chosen = diverse_sample(rows, 6)
    assert chosen == diverse_sample(list(reversed(rows)), 6)
    assert len({row["image_url"] for row in chosen}) == 6
    brands = [row["original"]["details"]["Brand"] for row in chosen]
    assert max(brands.count(brand) for brand in brands) <= 2
    with pytest.raises(ValueError, match="Preview diversity rule"):
        diverse_sample(rows, 9)


def test_full_selection_preserves_reviewed_examples_and_excludes_their_ids(tmp_path):
    rows = [record("reviewed")]
    rows += [
        record(identity, leaf=leaf)
        for identity, leaf in [
            ("new-monitor", "Monitors"),
            ("new-chair", "Home Office Desk Chairs"),
            ("new-headphones", "Over-Ear Headphones"),
        ]
    ]
    path = tmp_path / "catalog.jsonl.gz"
    with gzip.open(path, "wt") as stream:
        for row in rows:
            stream.write(canonical(row) + "\n")
    manifest = {
        "products": len(rows),
        "catalog_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    (tmp_path / "selection.json").write_text(json.dumps(manifest))
    preview = {
        "groups": [
            {"id": group, "products": [{"id": "reviewed", "title": "Keep me"}]}
            for group in ["headphones", "chairs", "monitors"]
        ]
    }
    before = copy.deepcopy(preview)
    result = build_preview(tmp_path, preview, 1)
    assert all(
        group["products"] == old["products"]
        for group, old in zip(result["groups"], before["groups"])
    )
    assert {group["catalogSamples"][0]["id"] for group in result["groups"]} == {
        "new-monitor",
        "new-chair",
        "new-headphones",
    }
    manifest["products"] += 1
    (tmp_path / "selection.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Preview selection count rule"):
        build_preview(tmp_path, before, 1)
