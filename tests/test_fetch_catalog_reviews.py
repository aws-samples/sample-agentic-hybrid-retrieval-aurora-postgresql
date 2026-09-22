"""Review imports retain source identity and distinguish samples from coverage."""

import copy
import json

import pytest

from scripts import fetch_catalog_reviews as sampler
from scripts.fetch_catalog_reviews import (
    consume_range,
    review_record,
    select_reviews,
    verify_review,
)


def original(**changes):
    return {
        "parent_asin": "PARENT0001",
        "asin": "VARIANT001",
        "title": "A review",
        "text": "Comfortable for my calls, but the microphone has limits.",
        "rating": 4.0,
        "timestamp": 1600000000000,
        "helpful_vote": 2,
        "verified_purchase": False,
        "user_id": "source-reviewer",
        **changes,
    }


def record(**changes):
    return review_record((json.dumps(original(**changes)) + "\n").encode(), 0)


def test_original_and_variant_are_preserved_without_promoting_purchase_verification():
    row = record()
    verify_review(row)
    assert row["original"] == original()
    assert row["original"]["asin"] != row["original"]["parent_asin"]
    assert row["original"]["verified_purchase"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"rating": True},
        {"rating": 6},
        {"rating": float("nan")},
        {"verified_purchase": "true"},
        {"helpful_vote": -1},
    ],
)
def test_invalid_evidence_fails_in_the_import_path(change):
    with pytest.raises(ValueError, match="Review shape rule.*inspect"):
        record(**change)


def test_altered_product_identity_is_red_then_byte_identical_restoration_is_green():
    row = record()
    saved = copy.deepcopy(row)
    row["original"]["parent_asin"] = "OTHER00001"
    with pytest.raises(ValueError, match="Review integrity rule.*restore"):
        verify_review(row)
    row = copy.deepcopy(saved)
    verify_review(row)
    assert row == saved


def test_chunk_boundary_re_reads_the_tail_without_losing_or_duplicating_a_review():
    first = (json.dumps(original()) + "\n").encode()
    second = json.dumps(original(text="A second experience.")).encode()
    found, used, count = consume_range(
        first + second[:20], 0, final=False, parents={"PARENT0001"}
    )
    assert (used, count, len(found)) == (len(first), 1, 1)
    rest, used_again, count_again = consume_range(
        second, used, final=True, parents={"PARENT0001"}
    )
    assert (used_again, count_again, len(rest)) == (len(second), 1, 1)
    assert rest[0]["source_location"]["offset"] == len(first)
    assert found[0]["source_record_sha256"] != rest[0]["source_record_sha256"]


def test_unrelated_products_do_not_enter_the_selected_sample():
    rows = (
        json.dumps(original(parent_asin="OTHER00001"))
        + "\n"
        + json.dumps(original())
        + "\n"
    ).encode()
    selected, _, count = consume_range(rows, 0, final=True, parents={"PARENT0001"})
    assert count == 2
    assert len(selected) == 1
    assert selected[0]["original"]["parent_asin"] == "PARENT0001"


def test_positive_popularity_cannot_displace_critical_experiences():
    positive = record(rating=5, helpful_vote=100)
    critical = record(rating=1, helpful_vote=0)
    less_helpful = record(rating=5, helpful_vote=1)
    result = select_reviews([positive, critical, less_helpful, positive], per_group=1)
    assert {row["source_record_sha256"] for row in result} == {
        positive["source_record_sha256"],
        critical["source_record_sha256"],
    }
    assert (
        select_reviews(list(reversed([positive, critical, less_helpful])), per_group=1)
        == result
    )


def test_scan_budget_stops_at_the_requested_range_and_preserves_the_tail(
    tmp_path, monkeypatch
):
    first = (json.dumps(original()) + "\n").encode()
    tail = (json.dumps(original(text="Second review")) + "\n").encode()
    body = first + tail
    budget = len(first) + 10
    monkeypatch.setattr(sampler, "RANGE_BYTES", budget)
    source = {**sampler.source_identity("Electronics"), "bytes": len(body)}
    monkeypatch.setattr(sampler, "source_identity", lambda category: source)
    calls = []

    def fetch_range(source, start, end):
        calls.append((start, end))
        return body[start : end + 1]

    monkeypatch.setattr(sampler, "fetch_range", fetch_range)
    state = sampler.fetch("Electronics", tmp_path, {"PARENT0001"}, budget, 1)
    assert calls == [(0, budget - 1)]
    assert state["next_byte"] == len(first)
    assert state["records_scanned"] == 1
    assert state["reviews"][0]["original"] == original()
    resumed = sampler.fetch("Electronics", tmp_path, {"PARENT0001"}, budget, 1)
    assert resumed["records_scanned"] == 2
    assert resumed["complete_source_scan"] is True
    assert calls == [(0, budget - 1), (len(first), len(body) - 1)]
