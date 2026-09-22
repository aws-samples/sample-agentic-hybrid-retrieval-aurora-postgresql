"""Keep dataset coverage separate from product truth and catalog publication."""

import gzip
import io
import json
import tarfile
from dataclasses import replace

import pytest

from scripts.catalog_source_audit import (
    Listing,
    abo_listing,
    esci_listing,
    present,
    read_abo,
    read_reviews,
    reviews_listing,
    summarize,
    title_screen,
)


def listing(identity=("item-1", "us"), **overrides):
    fields = {
        "identity": identity,
        "title": "Headphones",
        "description": None,
        "features": None,
        "details": None,
        "images": None,
        "price": None,
    }
    fields.update(overrides)
    return Listing(**fields)


def test_missing_is_not_false_or_zero():
    for missing in (None, "", " None ", "null", "N/A", [], {}):
        assert not present(missing)
    assert present(False)
    assert present(0)
    assert present({"noise_cancellation": False})


def test_audit_fails_empty_and_duplicate_inputs_but_not_other_marketplaces():
    with pytest.raises(ValueError, match="found 0 rows"):
        summarize([])
    with pytest.raises(ValueError, match="duplicate.*item-1"):
        summarize([listing(), listing(title="Different text, same identity")])
    report = summarize([listing(), listing(identity=("item-1", "jp"))])
    assert report["rows_examined"] == 2
    assert report["pilot_rows"] == 1


def test_counts_executed_records_without_inferring_capabilities():
    record = listing(details={"microphone": False}, price=0)
    report = summarize([record])
    assert report["rows_examined"] == 1
    assert report["nonempty_fields"] == {"details": 1, "price": 1, "title": 1}
    assert record.details == {"microphone": False}
    assert "noise_cancellation" not in record.details
    assert (
        summarize([replace(record, description="Unrelated description")])[
            "rows_examined"
        ]
        == 1
    )


def test_abo_locale_and_structured_fields_are_preserved():
    record = abo_listing(
        {
            "item_id": "ASIN",
            "domain_name": "amazon.com",
            "item_name": [
                {"language_tag": "de_DE", "value": "Ignore translation"},
                {"language_tag": "en_US", "value": "Office chair"},
            ],
            "item_dimensions": {"height": {"value": 36, "unit": "inches"}},
            "main_image_id": "image-id",
        }
    )
    assert record.identity == ("ASIN", "amazon.com")
    assert record.title == "Office chair"
    assert record.images == "image-id"
    assert record.price is None
    assert record.details["item_dimensions"]["height"]["unit"] == "inches"


def test_esci_does_not_acquire_prices_reviews_or_images():
    record = esci_listing(
        {
            "product_id": "ASIN",
            "product_locale": "us",
            "product_title": "Monitor",
            "product_bullet_point": "3840 x 2160",
            "price": 100,
        }
    )
    assert record.identity == ("ASIN", "us")
    assert record.features == "3840 x 2160"
    assert record.price is None
    assert record.images is None


def test_reviews_parent_key_is_not_an_esci_variant_key():
    record = reviews_listing(
        {"parent_asin": "PARENT", "asin": "CHILD", "title": "Monitor"}
    )
    assert record.identity == ("PARENT", "parent_asin")


@pytest.mark.parametrize(
    "title",
    [
        "USB-C to HDMI Monitor Adapter",
        "27 inch Monitor Privacy Screen Filter",
        "Dual Monitor Arm",
        "Replacement Cable for Headphones",
        "Headphone Jack Splitter",
    ],
)
def test_accessories_are_not_counted_as_devices(title):
    assert title_screen(listing(title=title)) == "accessory_title"


def test_archive_is_read_without_extracting_paths(tmp_path):
    path = tmp_path / "source.tar"
    with tarfile.open(path, "w") as archive:
        for name, data in [
            ("../escaped.txt", b"must not be written"),
            (
                "listings/metadata/listings_0.json.gz",
                gzip.compress(
                    json.dumps(
                        {
                            "item_id": "ASIN",
                            "domain_name": "amazon.com",
                            "item_name": [
                                {"language_tag": "en_US", "value": "Office chair"}
                            ],
                        }
                    ).encode()
                    + b"\n"
                ),
            ),
        ]:
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    result = summarize(read_abo(path))
    assert result["rows_examined"] == 1
    assert result["pilot_title_screens"] == {"office_chair_title": 1}
    assert list(tmp_path.iterdir()) == [path]


def test_customer_reviews_cannot_be_counted_as_products(tmp_path):
    path = tmp_path / "wrong.jsonl"
    path.write_text(json.dumps({"parent_asin": "ASIN", "rating": 4.0}) + "\n")
    with pytest.raises(ValueError, match="not product metadata"):
        list(read_reviews(path))
    path.write_text(json.dumps({"parent_asin": "ASIN", "title": "Product"}) + "\n")
    assert summarize(read_reviews(path))["rows_examined"] == 1


def test_missing_identity_is_a_loud_error():
    with pytest.raises(ValueError, match="original product ID"):
        summarize([reviews_listing({"title": "Missing key"})])
