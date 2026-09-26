"""The filter presets are one enumeration of source-supported predicates."""

from __future__ import annotations

from service.hnsw_presets import (
    CHARACTERS,
    FILTER_PRESETS,
    PRESET_KEYS,
    PRESETS_BY_KEY,
    presets_sha256,
)
from service.models import SearchFilters


def test_six_presets_keyed_uniquely():
    assert len(FILTER_PRESETS) == 6
    assert len(PRESETS_BY_KEY) == 6
    assert PRESET_KEYS == (
        "none",
        "rating",
        "domain",
        "category",
        "brand",
        "brand_rating",
    )


def test_the_unfiltered_preset_carries_no_predicate():
    assert PRESETS_BY_KEY["none"].predicate_sql == ""
    assert PRESETS_BY_KEY["none"].served_filters == {
        "include_refurbished": True,
        "include_sponsored": True,
    }


def test_every_filtered_preset_has_a_predicate():
    for preset in FILTER_PRESETS:
        if preset.key == "none":
            continue
        assert preset.predicate_sql, preset.key


def test_no_predicate_interpolates_a_parameter():
    """A preset is a fixed predicate, never a template. The probe takes a key."""
    for preset in FILTER_PRESETS:
        assert "%s" not in preset.predicate_sql
        assert "{" not in preset.predicate_sql


def test_every_predicate_uses_only_source_supported_fields():
    """Price and availability are not recorded for the served catalog.

    A preset over them matched zero rows on every anchor, which measured the
    absence of data rather than the index.
    """
    allowed = {"rating", "domain", "category_key", "brand_name"}
    for preset in FILTER_PRESETS:
        words = {
            token.strip("()")
            for token in preset.predicate_sql.replace(">=", " ")
            .replace("=", " ")
            .split()
        }
        assert not words & {
            "price_cents",
            "availability",
            "is_flagship",
            "is_refurbished",
        }, preset.key
        assert words & allowed or preset.key == "none", preset.key


def test_every_preset_names_a_selectivity_band_not_an_outcome():
    assert [preset.character for preset in FILTER_PRESETS] == list(CHARACTERS)
    for preset in FILTER_PRESETS:
        assert "correlated" not in preset.character
        assert "planner" not in preset.character


def test_served_filters_are_valid_search_filters_or_explicitly_absent():
    """`None` records that the predicate has no faithful SearchFilters form.

    The served rule compares brands case-insensitively while the predicate
    compares the recorded spelling, and the catalog spells some brands more
    than one way, so the brand presets say so rather than claim equivalence.
    """
    for preset in FILTER_PRESETS:
        if preset.served_filters is None:
            continue
        SearchFilters.model_validate(preset.served_filters)


def test_exactly_the_expressible_presets_carry_served_filters():
    expressible = {
        preset.key for preset in FILTER_PRESETS if preset.served_filters is not None
    }

    assert expressible == {"none", "rating", "domain", "category"}


def test_served_filters_keep_the_rows_the_predicate_keeps():
    """The served rule drops refurbished and sponsored rows unless told not to."""
    for preset in FILTER_PRESETS:
        if preset.served_filters is None:
            continue
        assert preset.served_filters["include_refurbished"] is True
        assert preset.served_filters["include_sponsored"] is True


def test_matching_rows_are_recorded_in_descending_selectivity():
    """The table is ordered so the page can walk from permissive to extreme."""
    rows = [preset.matching_rows for preset in FILTER_PRESETS]

    assert rows == sorted(rows, reverse=True)
    assert rows[0] == 553_911


def test_predicate_identity_changes_with_the_predicate_text():
    rating = PRESETS_BY_KEY["rating"]
    assert rating.predicate_sha256 != PRESETS_BY_KEY["domain"].predicate_sha256
    assert len(rating.predicate_sha256) == 64
    assert len(presets_sha256()) == 64
