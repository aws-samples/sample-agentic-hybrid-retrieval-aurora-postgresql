"""Ground truth is refused when it does not belong to the connected corpus.

Recall computed against another corpus is not recall. These are the falsifier
fixtures for that refusal.
"""

from __future__ import annotations

import pytest

from scripts.seed_exact_neighbors import StaleGroundTruth, assert_manifest_matches


def test_matching_manifest_is_accepted():
    assert_manifest_matches(stored="abc123", connected="abc123")


def test_a_mismatched_manifest_is_refused_with_both_values():
    with pytest.raises(StaleGroundTruth) as raised:
        assert_manifest_matches(stored="abc123", connected="def456")

    message = str(raised.value)
    assert "abc123" in message
    assert "def456" in message
    assert "fix:" in message


def test_an_empty_connected_manifest_is_refused():
    with pytest.raises(StaleGroundTruth):
        assert_manifest_matches(stored="abc123", connected="")


def test_an_unknown_connected_manifest_is_refused():
    """`unknown` is service.config's default when nothing resolved the manifest.

    Accepting it would pin ground truth to a sentinel, which then matches any other
    unresolved run regardless of what corpus produced it.
    """
    with pytest.raises(StaleGroundTruth):
        assert_manifest_matches(stored="unknown", connected="unknown")
