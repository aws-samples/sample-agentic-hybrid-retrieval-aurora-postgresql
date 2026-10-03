"""The Shop edit must reject poor examples without altering the searchable corpus."""

import json
from pathlib import Path

import pytest
from test_source_catalog import source_row

from scripts.catalog import curate_shop_collection as curate
from scripts.catalog.curate_shop_collection import eligible, select_group
from scripts.catalog.prepare_real_catalog import source_image


def record(**changes):
    row = source_row(
        features=[
            "27-inch display with 3840 x 2160 pixels.",
            "USB-C video and 65W power delivery.",
        ],
        details={
            "Brand": "Source",
            "Screen Size": "27 Inches",
            "Resolution": "3840 x 2160",
        },
        images=[
            {
                "variant": "MAIN",
                "hi_res": "https://m.media-amazon.com/images/I/source.jpg",
            }
        ],
        **changes,
    )
    row["image_url"] = source_image(row["original"])
    return row


@pytest.mark.parametrize(
    "title",
    [
        "Replacement monitor stand only",
        "Portable laptop monitor",
        "Renewed 27-inch monitor",
        "27-inch monitor (Discontinued)",
    ],
)
def test_accessories_and_poor_story_fits_do_not_enter_the_edit(title):
    assert eligible(record(), "monitors")
    assert not eligible(record(title=title), "monitors")


def test_source_mutation_and_missing_required_examples_fail_loudly():
    row = record()
    row["original"]["features"][0] = "Invented higher resolution"
    with pytest.raises(ValueError, match="Source product integrity rule"):
        eligible(row, "monitors")
    with pytest.raises(ValueError, match="Shop opening rule.*missing or ineligible"):
        select_group([], "monitors", 40)


def test_committed_edit_is_balanced_distinct_and_bound_to_original_records():
    manifest = json.loads(
        (Path(__file__).parents[1] / "data/real-shop-collection.json").read_text()
    )
    assert [group["category"] for group in manifest["groups"]] == [
        "headphones",
        "chairs",
        "monitors",
    ]
    ids = [asin for group in manifest["groups"] for asin in group["parent_asins"]]
    assert [len(group["parent_asins"]) for group in manifest["groups"]] == [40, 40, 40]
    assert len(ids) == len(set(ids)) == 120
    assert set(ids) == set(manifest["records"])
    for row in manifest["records"].values():
        assert (
            len(row["source_record_sha256"]) == len(row["embedding_text_sha256"]) == 64
        )
        assert len(row["topics_to_inspect"]) >= 2
    assert not set(ids) & {"B06XCDVNK2", "B01HE0W2WC", "B09C87JBHV", "B01NAKXH73"}


def test_opening_identities_skip_form_factor_patterns_but_not_condition(monkeypatch):
    row = record(title="Portable 27-inch monitor")
    assert not eligible(row, "monitors")
    monkeypatch.setitem(
        curate.OPENING, "monitors", (row["parent_asin"], *curate.OPENING["monitors"])
    )
    assert eligible(row, "monitors")
    assert not eligible(record(title="Renewed portable 27-inch monitor"), "monitors")


def test_committed_edit_opens_with_the_scripted_opening_identities():
    manifest = json.loads(
        (Path(__file__).parents[1] / "data/real-shop-collection.json").read_text()
    )
    for group in manifest["groups"]:
        name = group["category"]
        opening = curate.OPENING[name]
        assert tuple(group["parent_asins"][: len(opening)]) == opening
        assert all(manifest["records"][asin]["opening_example"] for asin in opening)
    assert manifest["review_exclusions"] == curate.REVIEW_EXCLUSIONS
