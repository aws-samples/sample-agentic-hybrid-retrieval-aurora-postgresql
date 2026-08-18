"""The filter presets are one enumeration, and each one has a measured character."""

from __future__ import annotations

from service.hnsw_presets import FILTER_PRESETS, PRESET_KEYS, PRESETS_BY_KEY
from service.models import SearchFilters


def test_six_presets_keyed_uniquely():
    assert len(FILTER_PRESETS) == 6
    assert len(PRESETS_BY_KEY) == 6
    assert PRESET_KEYS == (
        "none",
        "rating",
        "domain",
        "brand_stock",
        "refurb_premium",
        "flagship",
    )


def test_the_unfiltered_preset_carries_no_predicate():
    assert PRESETS_BY_KEY["none"].predicate_sql == ""
    assert PRESETS_BY_KEY["none"].served_filters == {}


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


def test_every_preset_states_its_measured_character():
    assert {preset.character for preset in FILTER_PRESETS} == {
        "unfiltered",
        "uncorrelated",
        "anti_correlated",
        "selective_uncorrelated",
        "selective_correlated",
        "planner_abandons_hnsw",
    }


def test_served_filters_are_valid_search_filters_or_explicitly_absent():
    """`None` records that the predicate has no faithful SearchFilters form.

    Three of the six do not, and saying so is the point. `in_stock_only` expands to
    `availability IN ('in_stock','low_stock')` rather than `= 'in_stock'`;
    `include_refurbished` *permits* refurbished rather than requiring it; and
    `is_flagship` has no SearchFilters key at all. Claiming an equivalence that
    matches a different row set would make the served-path comparison meaningless.
    """
    for preset in FILTER_PRESETS:
        if preset.served_filters is None:
            continue
        SearchFilters.model_validate(preset.served_filters)


def test_exactly_the_expressible_presets_carry_served_filters():
    expressible = {
        preset.key for preset in FILTER_PRESETS if preset.served_filters is not None
    }

    assert expressible == {"none", "rating", "domain"}


def test_matching_rows_are_recorded_in_descending_selectivity():
    """The table is ordered so the page can walk from permissive to extreme.

    Ordering matters for the lesson: `rating` (17%) sits before `domain` (26%) so a
    reader meets the working case before the one that fails at lower selectivity.
    """
    filtered = [preset for preset in FILTER_PRESETS if preset.key != "none"]

    assert [preset.matching_rows for preset in filtered] == [
        85_175,
        130_000,
        1_872,
        1_427,
        6,
    ]
