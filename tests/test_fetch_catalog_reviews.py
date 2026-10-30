"""Review imports retain source identity and distinguish samples from coverage."""

import copy
import hashlib
import json

import pytest

from scripts.catalog import fetch_catalog_reviews as sampler
from scripts.catalog.fetch_catalog_reviews import (
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
        {"helpful_vote": "2"},
        {"timestamp": 0},
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
    source = {
        **sampler.source_identity("Electronics"),
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }
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
    assert resumed["full_source_hash_verified"] is False
    assert "source_sha256_observed" not in resumed
    assert calls == [(0, budget - 1), (len(first), len(body) - 1)]


def test_a_record_straddling_two_planned_ranges_is_read_once_and_whole(
    tmp_path, monkeypatch
):
    rows = [
        original(text=f"Experience number {n} with enough words to matter.")
        for n in range(5)
    ]
    body = b"".join((json.dumps(row) + "\n").encode() for row in rows)
    span = len(body) // 3 + 7
    monkeypatch.setattr(sampler, "RANGE_BYTES", span)
    source = {
        **sampler.source_identity("Electronics"),
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }
    monkeypatch.setattr(sampler, "source_identity", lambda category: source)
    monkeypatch.setattr(
        sampler, "fetch_range", lambda source, start, end: body[start : end + 1]
    )
    state = sampler.fetch(
        "Electronics", tmp_path, {"PARENT0001"}, len(body), 5, workers=2
    )
    assert state["complete_source_scan"] is True
    assert state["full_source_hash_verified"] is True
    assert state["source_sha256_observed"] == hashlib.sha256(body).hexdigest()
    assert state["records_scanned"] == 5
    assert [
        row["original"]["text"]
        for row in sorted(
            state["reviews"], key=lambda r: r["source_location"]["offset"]
        )
    ] == [row["text"] for row in rows]
    assert [r["start"] for r in state["ranges"]] == [0, span, 2 * span]


def test_a_whole_file_scan_refuses_a_source_that_differs_from_its_pin(
    tmp_path, monkeypatch
):
    body = (json.dumps(original()) + "\n").encode()
    monkeypatch.setattr(sampler, "RANGE_BYTES", len(body))
    source = {
        **sampler.source_identity("Electronics"),
        "bytes": len(body),
        "sha256": "0" * 64,
    }
    monkeypatch.setattr(sampler, "source_identity", lambda category: source)
    monkeypatch.setattr(
        sampler, "fetch_range", lambda source, start, end: body[start : end + 1]
    )
    with pytest.raises(ValueError, match="Source hash rule"):
        sampler.fetch("Electronics", tmp_path, {"PARENT0001"}, len(body), 1)
    saved = json.loads((tmp_path / "Electronics-reviews.json").read_text())
    assert saved["full_source_hash_verified"] is False
    assert saved["source_sha256_observed"] == hashlib.sha256(body).hexdigest()


def test_an_unpinned_source_records_its_digest_without_claiming_verification(
    tmp_path, monkeypatch
):
    body = (json.dumps(original()) + "\n").encode()
    monkeypatch.setattr(sampler, "RANGE_BYTES", len(body))
    source = {
        **sampler.source_identity("Home_and_Kitchen"),
        "bytes": len(body),
        "sha256": None,
    }
    monkeypatch.setattr(sampler, "source_identity", lambda category: source)
    monkeypatch.setattr(
        sampler, "fetch_range", lambda source, start, end: body[start : end + 1]
    )
    state = sampler.fetch("Home_and_Kitchen", tmp_path, {"PARENT0001"}, len(body), 1)
    assert state["full_source_hash_verified"] is False
    assert state["source_sha256_observed"] == hashlib.sha256(body).hexdigest()


def test_trimming_a_complete_scan_keeps_the_most_helpful_reviews_per_group(tmp_path):
    rows = [
        record(text=f"Positive {n}", helpful_vote=n, rating=5.0) for n in range(4)
    ] + [record(text="Critical", rating=1.0)]
    state = {
        "reviews_per_rating_group": 20,
        "complete_source_scan": True,
        "reviews": rows,
        "coverage": {"PARENT0001": 5, "PARENT0002": 0},
    }
    trimmed = sampler.trim_sample(state, 2)
    assert all("original" not in row for row in trimmed["reviews"])
    assert [
        sampler.expand_review(row)["original"]["text"] for row in trimmed["reviews"]
    ] == ["Critical", "Positive 3", "Positive 2"]
    assert trimmed["coverage"] == {"PARENT0001": 3, "PARENT0002": 0}
    assert trimmed["reviews_per_rating_group"] == 2
    assert trimmed["trimmed_from_reviews_per_rating_group"] == 20
    assert len(state["reviews"]) == 5
    with pytest.raises(ValueError, match="between 1 and the scanned"):
        sampler.trim_sample(state, 21)
    with pytest.raises(ValueError, match="complete scan"):
        sampler.trim_sample({**state, "complete_source_scan": False}, 2)


def test_a_compact_row_rebuilds_its_record_and_still_detects_tampering():
    full = record()
    compact = sampler.compact_review(full)
    assert "original" not in compact and compact["raw_line"] == full["raw_line"]
    assert sampler.expand_review(compact) == full
    assert sampler.review_parent(compact) == sampler.review_parent(full) == "PARENT0001"
    altered = {**compact, "raw_line": compact["raw_line"].replace("limits", "none")}
    with pytest.raises(ValueError, match="Review integrity rule"):
        sampler.expand_review(altered)
    with pytest.raises(ValueError, match="Review integrity rule"):
        sampler.verify_review(altered)


def test_a_malformed_selected_line_is_skipped_and_counted_not_fatal():
    good = (json.dumps(original()) + "\n").encode()
    bad = (json.dumps(original(rating=7.0)) + "\n").encode()
    rejected: list[int] = []
    found, _used, count = consume_range(
        good + bad + good, 0, final=True, parents={"PARENT0001"}, rejected=rejected
    )
    assert (len(found), count, rejected) == (2, 3, [len(good)])
    with pytest.raises(ValueError, match="Review shape rule"):
        consume_range(bad, 0, final=True, parents={"PARENT0001"})


def test_negative_helpful_votes_are_source_values_not_corruption():
    row = record(helpful_vote=-2)
    assert row["original"]["helpful_vote"] == -2
    sampler.verify_review(row)


def _http_error(code, reason, retry_after=None):
    import email.message
    import io
    import urllib.error

    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError(
        "https://example/file", code, reason, headers, io.BytesIO(b"")
    )


class _RangeResponse:
    status = 206

    def __init__(self):
        self.headers = {"Content-Range": "bytes 0-3/10"}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size):
        return b"abcd"


def test_a_rate_limit_waits_for_retry_after_then_succeeds(monkeypatch):
    sleeps = []
    answers = iter([_http_error(429, "Too Many Requests", retry_after=7), None])

    def urlopen(request, timeout):
        error = next(answers)
        if error is not None:
            raise error
        return _RangeResponse()

    monkeypatch.setattr(sampler.time, "sleep", sleeps.append)
    monkeypatch.setattr(sampler.urllib.request, "urlopen", urlopen)
    source = {"url": "https://example/file", "bytes": 10}
    assert sampler.fetch_range(source, 0, 3) == b"abcd"
    assert sleeps == [7.0]


def test_backoff_without_retry_after_doubles_up_to_the_cap():
    error = _http_error(503, "Service Unavailable")
    assert [sampler.retry_delay(error, attempt) for attempt in (0, 1, 5, 6, 11)] == [
        1.0,
        2.0,
        32.0,
        60.0,
        60.0,
    ]
    assert sampler.retry_delay(ValueError("short read"), 3) == 8.0


def test_a_persistent_rate_limit_raises_a_picklable_error_naming_the_cause(monkeypatch):
    import pickle

    def urlopen(request, timeout):
        raise _http_error(429, "Too Many Requests")

    monkeypatch.setattr(sampler.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(sampler.urllib.request, "urlopen", urlopen)
    source = {"url": "https://example/file", "bytes": 10}
    with pytest.raises(
        RuntimeError,
        match=(
            r"Review fetch rule: bytes 0-3 of https://example/file failed on 12 attempts, "
            r"last HTTP 429 Too Many Requests"
        ),
    ) as caught:
        sampler.fetch_range(source, 0, 3)
    # The worker processes of scan_catalog_reviews.py send this error back to the parent;
    # an HTTPError, with its open response, cannot make that trip.
    assert caught.value.__cause__ is None
    assert str(pickle.loads(pickle.dumps(caught.value))) == str(caught.value)


def test_a_budget_below_one_range_scans_the_remaining_bytes(tmp_path, monkeypatch):
    """A resumed part may have fewer bytes left than one range; it still finishes."""
    first = (json.dumps(original()) + "\n").encode()
    tail = (json.dumps(original(text="Second review")) + "\n").encode()
    body = first + tail
    monkeypatch.setattr(sampler, "RANGE_BYTES", len(body) * 4)
    source = {
        **sampler.source_identity("Electronics"),
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }
    monkeypatch.setattr(sampler, "source_identity", lambda category: source)
    monkeypatch.setattr(
        sampler, "fetch_range", lambda source, start, end: body[start : end + 1]
    )
    state = sampler.fetch("Electronics", tmp_path, {"PARENT0001"}, len(first), 1)
    assert state["next_byte"] == len(first)
    resumed = sampler.fetch("Electronics", tmp_path, {"PARENT0001"}, len(tail), 1)
    assert resumed["next_byte"] == len(body)
    assert resumed["records_scanned"] == 2
    with pytest.raises(ValueError, match="Review selection rule"):
        sampler.fetch("Electronics", tmp_path, {"PARENT0001"}, 0, 1)
