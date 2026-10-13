"""A budget on the real catalog is matched against the price its source recorded.

The original listings carry no current offer, only the price each listing
reported when the catalog was collected. Every place that evaluates a price
filter must use that same price, or a search, a Shop count and a lab check
would disagree about which products are within budget.
"""

import re

import pytest

from service.catalog_runtime import filter_predicate
from service.lab_checks import eligible
from service.search_sql import ROOT, search_sql

SOURCE = search_sql()
FILTER_PRICE = "coalesce(d.price_cents, d.historical_price_cents)"
PROJECTION = (ROOT / "db/sql/06_retrieval_projection.sql").read_text()
VIEW_SQL = PROJECTION[PROJECTION.index("CREATE OR REPLACE VIEW") :]


def test_every_filter_call_matches_the_source_price():
    calls = re.findall(
        r"matches_filter_values\((.*?)is_sponsored", SOURCE, flags=re.DOTALL
    )
    arguments = [call for call in calls if "product_domain" not in call]
    assert len(arguments) == 6
    for call in arguments:
        assert "historical_price_cents" in call
        bare = call.replace(FILTER_PRICE, "").replace(
            "coalesce((d).price_cents, (d).historical_price_cents)", ""
        )
        assert "price_cents" not in bare


def test_returned_rows_still_report_the_current_price_column():
    assert re.search(r"d\.price_cents,\s+d\.availability,\s+d\.rating", SOURCE)


def test_shop_filters_use_the_same_price_as_search():
    assert FILTER_PRICE in filter_predicate("%s")


@pytest.mark.parametrize(
    "product,within_budget",
    [
        ({"price_cents": None, "historical_price_cents": 24_999}, True),
        ({"price_cents": None, "historical_price_cents": 34_999}, False),
        ({"price_cents": None, "historical_price_cents": None}, False),
        ({"price_cents": 24_999}, True),
    ],
)
def test_lab_checks_judge_a_budget_by_the_price_search_used(product, within_budget):
    assert eligible(product, {"max_price_cents": 30_000}) is within_budget


def test_the_view_never_reads_the_raw_source_record_per_row():
    """Reading `original->'price'` per row made a budgeted headphones count 831 ms.

    A keyed table of source prices answered the same count in 143 ms and cost
    nothing measurable without a budget (Aurora, reviews-2023-v2, 2026-09-27).
    """
    assert "original" not in VIEW_SQL
    assert "mosaic_catalog_stage.product" not in VIEW_SQL
    assert "mosaic_search.source_price" in VIEW_SQL
