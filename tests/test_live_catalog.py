"""The real storefront must preserve source facts and stay within its selection."""

from contextlib import contextmanager
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from test_source_catalog import source_row

from service import catalog, live_catalog
from service.catalog_runtime import search_schema
from service.models import CatalogFilters
from service.retrieval import RetrievalService
from service.synthesis import _price_settled_claims


@pytest.fixture
def real_product(monkeypatch):
    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", "reviews-2023-v2")
    return {
        **source_row(price=79.99),
        "product_id": 1000001,
        "domain": "consumer_electronics",
        "category_key": "monitor",
    }


def test_current_offer_is_unknown_while_source_identity_rating_and_photo_are_preserved(
    real_product,
):
    product = live_catalog.summary_from_source(real_product)
    assert product.title == real_product["original"]["title"]
    assert product.short_description == real_product["original"]["description"][0]
    assert product.source_features == real_product["original"]["features"]
    assert product.image_url == real_product["image_url"]
    assert product.listing_url == "https://www.amazon.com/dp/PARENT0001"
    assert product.review_count == 123
    assert product.historical_price_cents == 7999
    assert (
        product.price_cents is product.availability is product.inventory_count is None
    )
    assert (
        _price_settled_claims("It costs less than $100.", ["10000"], [product]) == set()
    )


def test_storefront_rejects_changed_source_text_or_a_substituted_photo(real_product):
    original = real_product["original"]["features"][:]
    real_product["original"]["features"] = ["Unsupported new feature"]
    with pytest.raises(ValueError, match="Source product integrity rule"):
        live_catalog.summary_from_source(real_product)
    real_product["original"]["features"] = original
    assert live_catalog.summary_from_source(real_product).source_features == original
    real_product["image_url"] = "https://example.com/wrong-product.jpg"
    with pytest.raises(ValueError, match="Source photo rule"):
        live_catalog.summary_from_source(real_product)


class Connection:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        self.current = next(self.responses)
        return self

    def fetchall(self):
        return self.current

    def fetchone(self):
        return self.current


@pytest.fixture(autouse=True)
def clear_browse_statistics():
    live_catalog._BROWSE_STATISTICS.clear()
    yield
    live_catalog._BROWSE_STATISTICS.clear()


def test_pages_share_counts_but_recheck_readiness_and_load_their_own_sources(
    real_product, monkeypatch
):
    receipt = {"dataset_id": "reviews-2023-v2", "prepared_at": "now"}
    counts = [
        {"facet": "total", "value": None, "count": 24},
        {"facet": "category_key", "value": "monitor", "count": 24},
    ]
    database = Connection(
        [
            receipt,
            counts,
            [{"product_id": 1000001}],
            [real_product],
            receipt,
            [{"product_id": 1000001}],
            [real_product],
        ]
    )

    @contextmanager
    def connect():
        yield database

    monkeypatch.setattr(live_catalog, "connect", connect)
    monkeypatch.setattr(live_catalog, "monotonic", lambda: 1)
    first = live_catalog.list_products(
        CatalogFilters(category_key="monitor"), collection="workspace"
    )
    second = live_catalog.list_products(
        CatalogFilters(category_key="monitor"), offset=12, collection="workspace"
    )
    assert first.total == second.total == 24
    assert first.offset == 0 and second.offset == 12
    assert first.products[0].title == real_product["original"]["title"]
    assert len(database.calls) == 7
    assert sum("GROUPING SETS" in query for query, _ in database.calls) == 1
    assert (
        sum("FROM mosaic_live_search.receipt" in query for query, _ in database.calls)
        == 2
    )
    assert all(
        "matches_filter_values" in query
        for query, _ in database.calls
        if "WHERE d.dataset_id" in query and "p.original" not in query
    )


@pytest.mark.parametrize(
    "changed",
    [
        {"dataset": "other"},
        {"prepared_at": "new-preparation"},
        {"filters_json": '{"attributes":{"Color":"Black"}}'},
        {"featured": ("other-product",)},
        {"collection": "all"},
        {"freshness": 2},
    ],
)
def test_statistics_cache_cannot_cross_catalog_filter_collection_or_freshness_boundaries(
    changed,
):
    values = {
        "dataset": "real",
        "prepared_at": "now",
        "filters_json": "{}",
        "featured": ("one",),
        "collection": "workspace",
        "freshness": 1,
    }
    database = Connection(
        [
            [{"facet": "total", "value": None, "count": 1}],
            [{"facet": "total", "value": None, "count": 2}],
        ]
    )
    assert live_catalog._browse_statistics(database, **values)["total"] == 1
    assert live_catalog._browse_statistics(database, **values)["total"] == 1
    assert live_catalog._browse_statistics(database, **(values | changed))["total"] == 2
    assert len(database.calls) == 2


def test_statistics_failure_is_not_cached():
    broken = MagicMock()
    broken.execute.side_effect = RuntimeError("connection interrupted")
    with pytest.raises(RuntimeError, match="connection interrupted"):
        live_catalog._browse_statistics(broken, "real", "now", "{}", (), "all", 1)
    assert not live_catalog._BROWSE_STATISTICS


@pytest.mark.parametrize(
    "receipt",
    [
        None,
        {"dataset_id": "old-source", "prepared_at": "now"},
        {"dataset_id": "reviews-2023-v2", "prepared_at": None},
    ],
)
def test_missing_or_different_preparation_cannot_silently_serve_another_catalog(
    real_product, receipt
):
    with pytest.raises(HTTPException) as error:
        live_catalog._selection(Connection([receipt]))
    assert error.value.status_code == 503


def test_missing_real_identity_cannot_fall_back_to_an_old_product(
    real_product, monkeypatch
):
    @contextmanager
    def connection():
        yield object()

    monkeypatch.setattr(live_catalog, "connect", connection)
    monkeypatch.setattr(live_catalog, "_source_rows", lambda _connection, _ids: [])
    with pytest.raises(KeyError, match="Run a new search"):
        catalog.get_product_summaries([1])


@pytest.mark.parametrize("receipt", [None, {"catalog_sha256": "new-catalog"}])
def test_old_search_cannot_receive_a_plan_from_a_different_catalog(
    real_product, receipt
):
    connection = MagicMock()
    connection.execute.return_value.fetchone.side_effect = [
        {"dataset_manifest_sha256": "old-catalog"},
        receipt,
    ]

    @contextmanager
    def connect():
        yield connection

    embedder = MagicMock()
    retrieval = RetrievalService(
        embedding_provider=embedder, connection_factory=connect
    )

    with pytest.raises(KeyError, match="previous catalog"):
        retrieval.capture_plan(uuid4())

    embedder.embed_query.assert_not_called()
    assert not any(
        "EXPLAIN" in call.args[0] for call in connection.execute.call_args_list
    )


def test_runtime_schema_is_allowlisted_even_when_the_environment_is_malformed(
    monkeypatch,
):
    monkeypatch.setenv("MOSAIC_CATALOG_DATASET", "x; DROP SCHEMA mosaic")
    assert search_schema() == "mosaic_live_search"
    monkeypatch.delenv("MOSAIC_CATALOG_DATASET")
    assert search_schema() == "mosaic_search"


def test_multi_topic_review_fallback_keeps_the_product_type_and_limit(
    real_product, monkeypatch
):
    rows = [
        {
            "evidence_id": 101,
            "product_id": 1000001,
            "evidence_type": "product_spec",
            "source_name": "Original listing",
            "evidence_text": "Noise cancelling headphones",
            "metadata": {},
        },
        {
            "evidence_id": 102,
            "product_id": 1000001,
            "evidence_type": "customer_review",
            "source_name": "Original review",
            "evidence_text": "The noise cancellation is excellent.",
            "metadata": {"variant_asin": "VARIANT001"},
        },
    ]
    database = Connection(
        [
            [{"evidence_id": 101, "evidence_type": "product_spec"}],
            [{"evidence_id": 102}],
            rows,
        ]
    )

    @contextmanager
    def connection():
        yield database

    monkeypatch.setattr(catalog, "connect", connection)
    monkeypatch.setattr(live_catalog, "ensure_product_evidence", lambda _id: None)
    records = catalog.get_product_evidence_records(
        1000001, "noise cancellation and phone calls", [0.1], limit=2
    )
    assert [record.evidence_id for record in records] == [101, 102]
    fallback_sql, parameters = database.calls[1]
    assert "mosaic_live_search.search_product_evidence" in fallback_sql
    assert "ARRAY['customer_review']" in fallback_sql
    assert parameters[0] == 1000001
    assert '"noise" OR "cancellation"' in parameters[1]
    assert parameters[3] == 1
    assert records[1].metadata["variant_asin"] == "VARIANT001"
    assert "At least one query term" in records[1].metadata["retrieval_match"]
    assert records[1].text == rows[1]["evidence_text"]
