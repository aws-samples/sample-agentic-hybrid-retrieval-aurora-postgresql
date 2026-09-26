"""The six filter presets the HNSW instrument measures on Mosaic's catalog.

Each preset is a fixed predicate rather than a template: the probe endpoint
accepts a key, so no request can reach the SQL text. Every predicate uses a
field the source records support on the served catalog (domain, category,
brand, rating). Price and availability are not recorded for these products, so
a preset over them would match nothing.

`matching_rows` is the count each predicate selected on the 553,911-product
`reviews-2023-v2` catalog when the presets were chosen (2026-09-26). The
benchmark re-counts every predicate live and records the live figure in the
artifact; the figure here orders the table and is not evidence on its own.

`character` names the selectivity band a preset sits in. It does not claim what
the scan will do under that band: that is what the measurement is for, and the
recorded rows, recall and plan node say it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

# The exact baseline forces a sequential scan, which is what makes it exact. Both
# settings are required: disabling only index scans leaves the bitmap path.
EXACT_BASELINE_SETTINGS = ("enable_indexscan = off", "enable_bitmapscan = off")

# The selectivity bands, most permissive first. The page walks the table in this
# order so a reader meets the unfiltered baseline before any narrowing.
CHARACTERS = (
    "unfiltered",
    "broad",
    "moderate",
    "narrow",
    "very_narrow",
    "extreme",
)


@dataclass(frozen=True)
class FilterPreset:
    """One fixed filter predicate and the selectivity band it occupies.

    Attributes:
        key: Stable identifier accepted by the probe endpoint.
        label: Human-readable name shown on the page.
        predicate_sql: Appended to the ANN query's WHERE clause. Fixed text, never
            a template, so no request value can reach it.
        character: Selectivity band from `CHARACTERS`. Not a predicted outcome.
        matching_rows: Rows the predicate selected when the preset was chosen.
        served_filters: The `SearchFilters` payload producing the *same* row set
            through the served `search_vector`, or `None` when no faithful
            equivalent exists.
    """

    key: str
    label: str
    predicate_sql: str
    character: str
    matching_rows: int
    served_filters: dict[str, object] | None = None

    @property
    def predicate_sha256(self) -> str:
        """Identity of the predicate text, stored beside its ground truth.

        A preset whose predicate changes while its key survives would otherwise
        keep serving neighbours computed for the old predicate.
        """
        return hashlib.sha256(self.predicate_sql.encode("utf-8")).hexdigest()


# `served_filters` carry `include_refurbished` and `include_sponsored` because
# the served rule excludes those rows by default, and a preset predicate does
# not. Brand presets have no faithful form: the served rule compares brands
# case-insensitively, and the catalog spells some brands more than one way.
FILTER_PRESETS: tuple[FilterPreset, ...] = (
    FilterPreset(
        key="none",
        label="No filter",
        predicate_sql="",
        character="unfiltered",
        matching_rows=553_911,
        served_filters={"include_refurbished": True, "include_sponsored": True},
    ),
    FilterPreset(
        key="rating",
        label="Rating 4.5 and above",
        predicate_sql="rating >= 4.5",
        character="broad",
        matching_rows=195_951,
        served_filters={
            "min_rating": 4.5,
            "include_refurbished": True,
            "include_sponsored": True,
        },
    ),
    FilterPreset(
        key="domain",
        label="Home office only",
        predicate_sql="domain = 'home_office'",
        character="moderate",
        matching_rows=117_878,
        served_filters={
            "domain": "home_office",
            "include_refurbished": True,
            "include_sponsored": True,
        },
    ),
    FilterPreset(
        key="category",
        label="Monitors only",
        predicate_sql="category_key = 'monitor'",
        character="narrow",
        matching_rows=8_229,
        served_filters={
            "category_key": "monitor",
            "include_refurbished": True,
            "include_sponsored": True,
        },
    ),
    # `Dell` is pinned literally rather than resolved by `ORDER BY count(*) DESC`:
    # a computed "top brand" would change what this measures on any re-import.
    FilterPreset(
        key="brand",
        label="One brand",
        predicate_sql="brand_name = 'Dell'",
        character="very_narrow",
        matching_rows=3_320,
    ),
    FilterPreset(
        key="brand_rating",
        label="One brand, rating 4.5 and above",
        predicate_sql="brand_name = 'Bose' AND rating >= 4.5",
        character="extreme",
        matching_rows=95,
    ),
)

PRESETS_BY_KEY: dict[str, FilterPreset] = {
    preset.key: preset for preset in FILTER_PRESETS
}
PRESET_KEYS: tuple[str, ...] = tuple(preset.key for preset in FILTER_PRESETS)


def presets_sha256() -> str:
    """One identity for the whole enumeration: keys and predicates together."""
    joined = "\n".join(f"{p.key}\t{p.predicate_sql}" for p in FILTER_PRESETS)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
