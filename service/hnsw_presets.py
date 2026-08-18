"""The six filter presets the HNSW instrument measures, and their ground truth.

Each preset is a fixed predicate rather than a template: the probe endpoint accepts
a key, so no request can reach the SQL text. The `character` field records what the
preset *demonstrates*, measured on the live 500,000-vector catalog at the served
`ef_search` and a top-k of ten, over 12 query vectors — because the lesson is that
selectivity does not predict behaviour, and the table has to carry that.

Measured, in the order below:

| key            | selectivity | iterative_scan=off | relaxed_order   |
|----------------|------------:|--------------------|-----------------|
| none           |     100%    | recall 0.992       | recall 0.992    |
| rating         |   17.035%   | recall 0.983       | recall 0.983    |
| domain         |   26.000%   | **0 rows**         | recall 0.375    |
| brand_stock    |    0.374%   | 1.75 rows, 0.175   | recall 1.000    |
| refurb_premium |    0.285%   | **0 rows**         | **0 rows**      |
| flagship       |   0.0012%   | 6 of 6, 1.000      | 6 of 6, 1.000   |

`domain` is *less* selective than `rating` and fails far worse, because all 12 query
vectors are consumer_electronics and 100 of their 100 nearest neighbours are too —
the filter is anti-correlated with the neighbourhood. `refurb_premium` returns
nothing even relaxed until the `work_mem x scan_mem_multiplier` budget is raised;
`max_scan_tuples` provably does not help it (0 rows at 20K, 100K, 500K and 1M).
`flagship` is where the planner leaves HNSW for a filtered exact scan, correctly.

The exact ground truth found 10 rows for every level except `flagship`, where only 6
exist, so every zero above is a silent empty result set where matches exist.
"""

from __future__ import annotations

from dataclasses import dataclass

# Only products with real media are offered as query anchors: 120 of 500,000 carry a
# media tier, and the 30 retrieval anchors are exactly the imaged, recognisable
# storefront products, spanning all three domains.
ANCHOR_PREDICATE = "is_retrieval_anchor"

# The exact baseline forces a sequential scan, which is what makes it exact. Both
# settings are required: disabling only index scans leaves the bitmap path.
EXACT_BASELINE_SETTINGS = ("enable_indexscan = off", "enable_bitmapscan = off")


@dataclass(frozen=True)
class FilterPreset:
    """One fixed filter predicate and the retrieval behaviour it demonstrates.

    Attributes:
        key: Stable identifier accepted by the probe endpoint.
        label: Human-readable name shown on the page.
        predicate_sql: Appended to the ANN query's WHERE clause. Fixed text, never
            a template, so no request value can reach it.
        character: What the preset demonstrates, measured. Selectivity does not
            predict it, which is the whole lesson.
        matching_rows: Rows satisfying the predicate on the 500,000-row corpus.
        served_filters: The `SearchFilters` payload producing the *same* row set
            through `mosaic_search.search_vector`, or `None` when no faithful
            equivalent exists. Three of the six are `None`, deliberately.
    """

    key: str
    label: str
    predicate_sql: str
    character: str
    matching_rows: int
    served_filters: dict[str, object] | None = None


FILTER_PRESETS: tuple[FilterPreset, ...] = (
    FilterPreset(
        key="none",
        label="No filter",
        predicate_sql="",
        character="unfiltered",
        matching_rows=500_000,
        served_filters={},
    ),
    FilterPreset(
        key="rating",
        label="Rating 4.8 and above",
        predicate_sql="rating >= 4.8",
        character="uncorrelated",
        matching_rows=85_175,
        served_filters={"min_rating": 4.8},
    ),
    FilterPreset(
        key="domain",
        label="Home office only",
        predicate_sql="domain = 'home_office'",
        character="anti_correlated",
        matching_rows=130_000,
        served_filters={"domain": "home_office"},
    ),
    # `HaloBeam` is pinned literally rather than resolved by `ORDER BY count(*) DESC
    # LIMIT 1`: it leads AuriLogic by a single row (2,142 to 2,141), so a computed
    # "top brand" would flip on any reseed and silently change what this measures.
    #
    # `served_filters` is None because `in_stock_only` expands to
    # `availability IN ('in_stock','low_stock')` in matches_filter_values, not to
    # `= 'in_stock'`. The two match different row sets.
    FilterPreset(
        key="brand_stock",
        label="One brand, in stock",
        predicate_sql="brand_name = 'HaloBeam' AND availability = 'in_stock'",
        character="selective_uncorrelated",
        matching_rows=1_872,
    ),
    # None because `include_refurbished` *permits* refurbished rows rather than
    # requiring them: the SearchFilters form matches the whole catalog, not the
    # 1,427 refurbished-and-premium rows this predicate selects.
    FilterPreset(
        key="refurb_premium",
        label="Refurbished above $800",
        predicate_sql="is_refurbished AND price_cents > 80000",
        character="selective_correlated",
        matching_rows=1_427,
    ),
    # None because SearchFilters has no `is_flagship` key. The cohort is reachable
    # from SQL and from merchandising, not from the retrieval filter contract.
    FilterPreset(
        key="flagship",
        label="Flagship products",
        predicate_sql="is_flagship",
        character="planner_abandons_hnsw",
        matching_rows=6,
    ),
)

PRESETS_BY_KEY: dict[str, FilterPreset] = {
    preset.key: preset for preset in FILTER_PRESETS
}
PRESET_KEYS: tuple[str, ...] = tuple(preset.key for preset in FILTER_PRESETS)
