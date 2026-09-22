"""Keep imported evidence immutable and fail incomplete selections closed."""

import copy
import gzip
import json

import pytest

from scripts import prepare_real_catalog as catalog


@pytest.fixture
def plan():
    return {
        "version": 1,
        "selection_seed": "test",
        "minimum_source_text_characters": 10,
        "maximum_embedding_characters": 32000,
        "sources": [{"category": "Electronics", "products": 2}],
    }


def product(identity="EXAMPLE001"):
    return {
        "parent_asin": identity,
        "title": "Example monitor",
        "description": ["Original punctuation & spacing:  27 inches."],
        "features": ["USB-C input; 90 W charging."],
        "categories": ["Electronics", "Monitors"],
        "details": {"Touchscreen": False, "Speakers": 0},
        "images": [{"variant": "MAIN", "hi_res": "https://example.com/photo.jpg"}],
    }


def test_selection_is_independent_of_source_order(plan):
    records = [product(f"PRODUCT{i:03}") for i in range(20)]
    forward, report = catalog.select_ids(iter(records), 5, plan, set())
    reverse, _ = catalog.select_ids(reversed(records), 5, plan, set())
    assert forward == reverse
    assert report["source_rows"] == 20
    assert len(forward) == 5


def test_deduplicates_across_departments_and_refuses_short_selection(plan):
    records = [product("A"), product("B")]
    selected, report = catalog.select_ids(records, 1, plan, {"A"})
    assert selected == {"B"}
    assert report["excluded_counts"]["already_selected_from_another_department"] == 1
    with pytest.raises(ValueError, match="only 1 eligible distinct"):
        catalog.select_ids(records, 2, plan, {"A"})


def test_duplicate_source_identity_is_not_silently_counted_twice(plan):
    with pytest.raises(ValueError, match="repeated parent ASIN EXAMPLE001"):
        catalog.select_ids([product(), product()], 1, plan, set())


@pytest.mark.parametrize("identity", [None, {}, [], ""])
def test_invalid_identity_cannot_crash_or_enter_selection(plan, identity):
    bad = product(identity)
    selected, report = catalog.select_ids([bad, product("VALID")], 1, plan, set())
    assert selected == {"VALID"}
    assert report["excluded_counts"] == {"missing_identity": 1}


def test_embedding_projection_preserves_false_zero_and_original_text():
    original = product()
    saved = copy.deepcopy(original)
    text = catalog.embedding_text(original)
    assert "Touchscreen: false" in text
    assert "Speakers: 0" in text
    assert original["description"][0] in text
    assert original == saved


def test_photo_change_does_not_trigger_text_embedding_change():
    original = product()
    changed = copy.deepcopy(original)
    changed["images"][0]["hi_res"] = "https://example.com/clearer.jpg"
    assert catalog.embedding_text(changed) == catalog.embedding_text(original)
    changed["features"] = ["USB-C input; 65 W charging."]
    assert catalog.sha256(catalog.embedding_text(changed)) != catalog.sha256(
        catalog.embedding_text(original)
    )


def test_missing_specifications_are_not_invented(plan):
    original = product()
    original["details"] = {}
    assert catalog.rejection_reason(original, plan) is None
    assert "Specifications:" not in catalog.embedding_text(original)
    original["features"] = "Wrong shape"
    assert catalog.rejection_reason(original, plan) == "invalid_text_fields"


@pytest.mark.parametrize(
    "url", ["http://example.com/photo.jpg", "https://user:secret@example.com/photo.jpg"]
)
def test_unsafe_image_is_rejected(plan, url):
    original = product()
    original["images"][0]["hi_res"] = url
    assert catalog.rejection_reason(original, plan) == "missing_primary_image"


def test_published_selection_contains_unchanged_source_and_hashes(
    tmp_path, plan, monkeypatch
):
    records = [product("A"), product("B")]
    snapshots = copy.deepcopy(records)
    calls = []

    def read(path):
        calls.append(path.name)
        yield from records

    monkeypatch.setattr(catalog, "iter_records", read)
    output = tmp_path / "selected"
    catalog.prepare(tmp_path, output, plan)
    with gzip.open(output / "catalog.jsonl.gz", "rt") as stream:
        rows = [json.loads(line) for line in stream]
    assert calls == ["Electronics", "Electronics"]
    assert [row["original"] for row in rows] == snapshots
    assert len(rows) == 2
    for row in rows:
        assert row["source_record_sha256"] == catalog.sha256(
            catalog.canonical(row["original"])
        )
        assert row["embedding_text_sha256"] == catalog.sha256(row["embedding_text"])
    assert json.loads((output / "selection.json").read_text())["products"] == 2


def test_late_checksum_failure_never_publishes_partial_selection(
    tmp_path, plan, monkeypatch
):
    calls = 0

    def read(path):
        nonlocal calls
        calls += 1
        yield product("A")
        yield product("B")
        if calls == 2:
            raise ValueError("Source checksum rule: corrupted pinned source")

    monkeypatch.setattr(catalog, "iter_records", read)
    with pytest.raises(ValueError, match="Source checksum rule"):
        catalog.prepare(tmp_path, tmp_path / "selected", plan)
    assert calls == 2
    assert not (tmp_path / "selected" / "catalog.jsonl.gz").exists()
    assert not (tmp_path / "selected" / "selection.json").exists()


@pytest.mark.parametrize("value", [None, [], {"version": 99}])
def test_invalid_plan_is_rejected(value):
    with pytest.raises(ValueError, match="Source plan rule"):
        catalog.validate_plan(value)
