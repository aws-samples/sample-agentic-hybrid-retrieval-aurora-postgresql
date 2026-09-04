"""Rebuilding one persisted retrieval as the response it originally served.

Every test here runs against a fake connection holding one `mosaic.search_event`
row and three `mosaic.search_result_event` rows. The point of the endpoint is
that a carried run renders from its receipt, so the tests assert the receipt is
the only source: nothing is recomputed, no model is called, and a field the
receipt does not store comes back `None` rather than filled in.
"""

from __future__ import annotations

from contextlib import contextmanager
from uuid import UUID

import pytest

from service.models import ProductSummary, SourceAttribution

EVENT_ID = UUID("6b1d2f80-4c7a-4f31-9a52-8e0c3d5a7b11")

# The three served rows, and the order the fake connection hands them back.
# It is deliberately NOT the served order: a reconstruction that keeps arrival
# order instead of sorting on `result_rank` returns 503 first and is caught.
STORED_ROW_ORDER = [503, 501, 502]
SERVED_ORDER = [502, 501, 503]
RANK_BY_PRODUCT = {502: 1, 501: 2, 503: 3}

PERSISTED_CANDIDATE_COUNTS = {
    "fused_pool": 47,
    "fts_in_pool": 12,
    "trigram_in_pool": 5,
    "semantic_in_pool": 47,
}
PERSISTED_STAGE_TIMINGS = {"embedding": 61.5, "postgresql_retrieval": 88.25}
PERSISTED_PROFILE = {
    "fts_limit": 120,
    "trigram_limit": 80,
    "semantic_limit": 150,
    "fused_limit": 50,
    "result_limit": 12,
    "authorized_limit": 12,
    "rrf_k": 60,
    "trigram_threshold": 0.3,
    "weight_lexical": 0.4,
    "weight_semantic": 0.4,
    "weight_trigram": 0.2,
    "ef_search": 100,
    "iterative_scan": "relaxed_order",
    "max_scan_tuples": 20000,
    "scan_mem_multiplier": 1.0,
}


def _event_row(**overrides):
    row = {
        "search_event_id": EVENT_ID,
        "query_text": "  noise cancelling  headphones ",
        "normalized_query": "noise cancelling headphones",
        "filters": {"in_stock_only": True},
        "retrieval_profile": dict(PERSISTED_PROFILE),
        "retrieval_strategy": "rrf_fusion+rerank+exact_sku_preservation",
        "embedding_model_id": "us.cohere.embed-v4:0",
        "rerank_model_id": "cohere.rerank-v3-5:0",
        "candidate_counts": dict(PERSISTED_CANDIDATE_COUNTS),
        "total_latency_ms": 214,
        "diagnostics": {
            "status": "ok",
            "strategy": "rrf_fusion+rerank+exact_sku_preservation",
            "rerank_status": "applied",
            "ranking_policy": [
                "RRF candidate fusion",
                "managed reranking",
                "exact SKU preservation",
            ],
            "stage_timings_ms": dict(PERSISTED_STAGE_TIMINGS),
            "warnings": [],
        },
    }
    row.update(overrides)
    return row


def _candidate_row(product_id):
    result_rank = RANK_BY_PRODUCT[product_id]
    return {
        "product_id": product_id,
        "result_rank": result_rank,
        "fts_rank": result_rank + 3,
        "trigram_rank": None,
        "semantic_rank": result_rank,
        "fused_rank": result_rank + 10,
        "rerank_rank": result_rank,
        "scores": {
            "fts": 0.25 + result_rank,
            "trigram": None,
            "semantic": 0.5 + result_rank,
            "rrf": 0.031 + result_rank,
            "pre_rerank": 0.031 + result_rank,
            "rerank": 0.9 - result_rank / 10,
            "exact_sku_match": False,
        },
        "provenance": {
            "channels": {
                "fts": {"rrf_contribution": 0.0151 + result_rank},
                "vector": {"rrf_contribution": 0.0161 + result_rank},
            },
            "is_retrieval_anchor": False,
        },
    }


def _product(product_id):
    return ProductSummary(
        product_id=product_id,
        sku=f"SKU-{product_id}",
        title=f"Product {product_id}",
        short_description="A product.",
        domain="consumer_electronics",
        category_key="over-ear-headphones",
        category_path="Electronics",
        brand="Brand",
        model=f"M{product_id}",
        price_cents=19900,
        list_price_cents=19900,
        review_count=10,
        availability="in_stock",
        inventory_count=5,
        attributes={},
        tags=[],
        sources=[
            SourceAttribution(
                source_uri=f"mosaic://product/{product_id}",
                revision="1",
                title=f"Product {product_id}",
                quote="A product.",
            )
        ],
    )


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _Connection:
    """A `mosaic.search_event` receipt and its served rows, and nothing else."""

    def __init__(self, event, candidates):
        self.event = event
        self.candidates = candidates
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, sql, parameters=None):
        self.executed.append((sql, parameters))
        if "FROM mosaic.search_result_event" in sql:
            return _Result(self.candidates)
        if "FROM mosaic.search_event" in sql:
            return _Result([self.event] if self.event is not None else [])
        raise AssertionError(f"replay issued unexpected SQL: {sql}")


def _install(monkeypatch, *, event=..., candidates=...):
    """Point the replay module at a fake receipt and a recording loader.

    `event=None` stands for an id no `mosaic.search_event` row carries.
    """
    from service import retrieval_replay

    connection = _Connection(
        _event_row() if event is ... else event,
        [_candidate_row(product_id) for product_id in STORED_ROW_ORDER]
        if candidates is ...
        else candidates,
    )
    hydration_calls = []

    @contextmanager
    def connect():
        yield connection

    def load_products(product_ids):
        hydration_calls.append(list(product_ids))
        return [_product(product_id) for product_id in product_ids]

    monkeypatch.setattr(retrieval_replay, "connect", connect)
    monkeypatch.setattr(retrieval_replay, "get_product_summaries", load_products)
    return connection, hydration_calls


def test_replay_serves_the_persisted_request(monkeypatch):
    from service.retrieval_replay import replay_search_response

    _install(monkeypatch)

    response = replay_search_response(EVENT_ID)

    assert response.search_event_id == EVENT_ID
    assert response.query == "  noise cancelling  headphones "
    assert response.normalized_query == "noise cancelling headphones"
    assert response.applied_filters == {"in_stock_only": True}


def test_results_follow_result_rank_not_arrival_order(monkeypatch):
    """Falsifier: return the rows as stored and 502 stops leading the window."""
    from service.retrieval_replay import replay_search_response

    _install(monkeypatch)

    response = replay_search_response(EVENT_ID)

    assert STORED_ROW_ORDER != SERVED_ORDER
    assert [product.product_id for product in response.results] == SERVED_ORDER
    assert [product.signals.final_rank for product in response.results] == [1, 2, 3]


def test_only_the_served_window_is_replayed_not_the_whole_pool(monkeypatch):
    """`search()` persists every fused candidate and returns only `limit`.

    Falsifier: replay every stored row and a participant who was served two
    products sees three. The window is the receipt's own
    `retrieval_profile.result_limit`, which is that request's `limit`.
    """
    from service.retrieval_replay import replay_search_response

    profile = dict(PERSISTED_PROFILE, result_limit=2, authorized_limit=2)
    _, hydration_calls = _install(
        monkeypatch, event=_event_row(retrieval_profile=profile)
    )

    response = replay_search_response(EVENT_ID)

    assert len(STORED_ROW_ORDER) == 3
    assert [product.product_id for product in response.results] == [502, 501]
    assert hydration_calls == [[502, 501]]


def test_the_served_window_never_exceeds_the_authorized_limit(monkeypatch):
    """An agent run records the reranker's pool but grants only a few products.

    Falsifier: slice to `result_limit` alone and a receipt with `result_limit`
    3 and `authorized_limit` 1 replays three products with full content where
    `POST /api/retrieval/events/{id}/compare` refuses anything past the first.
    """
    from service.retrieval_replay import replay_search_response

    profile = dict(PERSISTED_PROFILE, result_limit=3, authorized_limit=1)
    _, hydration_calls = _install(
        monkeypatch, event=_event_row(retrieval_profile=profile)
    )

    response = replay_search_response(EVENT_ID)

    assert [product.product_id for product in response.results] == [502]
    assert hydration_calls == [[502]]


def test_a_receipt_without_a_served_window_is_refused(monkeypatch):
    """Guessing the window from today's configured display limit would lie."""
    from service.retrieval_replay import replay_search_response

    profile = {key: value for key, value in PERSISTED_PROFILE.items()}
    del profile["result_limit"]
    _install(monkeypatch, event=_event_row(retrieval_profile=profile))

    with pytest.raises(KeyError) as error:
        replay_search_response(EVENT_ID)

    detail = str(error.value)
    assert "result_limit" in detail
    assert "fix:" in detail


def test_a_receipt_without_an_authorized_limit_is_refused(monkeypatch):
    """No grant on the receipt is a denial, not an unbounded window.

    `SearchRequest._bound_authorized_limit` resolves the field to the served
    `limit` when the caller omits it, so every receipt `service.retrieval.search`
    writes carries an integer. Reading a receipt without one as "no narrowing"
    replays the whole fused pool with full product content, which is exactly the
    window `service.retrieval_scope` refuses to open, and that guard denies on a
    null `authorized_limit` for the same reason.
    """
    from service.retrieval_replay import replay_search_response

    profile = dict(PERSISTED_PROFILE)
    del profile["authorized_limit"]
    _install(monkeypatch, event=_event_row(retrieval_profile=profile))

    with pytest.raises(KeyError) as error:
        replay_search_response(EVENT_ID)

    detail = str(error.value)
    assert "authorized_limit" in detail
    assert "fix:" in detail
    # Named to the served window, not to the diagnostics profile. Both gates
    # refuse an absent key, and a test that accepted either would stay green
    # while the window itself reopened.
    assert "served window" in detail


def test_a_null_authorized_limit_is_refused_like_an_absent_one(monkeypatch):
    """A receipt predating explicit authorization records null, not a window."""
    from service.retrieval_replay import replay_search_response

    profile = dict(PERSISTED_PROFILE, authorized_limit=None)
    _install(monkeypatch, event=_event_row(retrieval_profile=profile))

    with pytest.raises(KeyError, match="authorized_limit"):
        replay_search_response(EVENT_ID)


def test_a_partial_profile_is_refused_rather_than_defaulted_from_the_yaml(
    monkeypatch,
):
    """`RetrievalProfile` resolves absent fields from today's configuration.

    Falsifier: build the diagnostics profile straight from the persisted dict,
    and a receipt recorded before `db/config/retrieval.yaml` was last edited
    replays with today's `ef_search` and `rrf_k` presented as the values that
    run used. `served_window` already refuses that for `result_limit`; the rest
    of the profile is the same claim.
    """
    from service.retrieval_replay import replay_search_response

    profile = dict(PERSISTED_PROFILE)
    del profile["ef_search"]
    del profile["rrf_k"]
    _install(monkeypatch, event=_event_row(retrieval_profile=profile))

    with pytest.raises(KeyError) as error:
        replay_search_response(EVENT_ID)

    detail = str(error.value)
    assert "ef_search" in detail
    assert "rrf_k" in detail
    assert "retrieval.yaml" in detail
    assert "fix:" in detail


def test_the_replayed_profile_requires_every_field_the_model_declares(monkeypatch):
    """Witness: the required set is read off the model, not hand-listed.

    A literal list would go stale the first time `RetrievalProfile` grew a
    field, and that field's persisted value would then be defaulted in silence.
    The count is pinned independently so adding one is a decision rather than an
    accident.
    """
    from service.models import RetrievalProfile
    from service.retrieval_replay import replay_search_response

    fields = sorted(RetrievalProfile.model_fields)
    assert len(fields) == 15, fields
    assert sorted(PERSISTED_PROFILE) == fields, (
        "the fixture must be a complete receipt, or dropping one field proves "
        "nothing about the field it names"
    )

    refused = []
    for field in fields:
        profile = {key: value for key, value in PERSISTED_PROFILE.items()}
        del profile[field]
        _install(monkeypatch, event=_event_row(retrieval_profile=profile))

        with pytest.raises(KeyError) as error:
            replay_search_response(EVENT_ID)

        assert field in str(error.value), field
        refused.append(field)

    assert refused == fields


def test_products_are_hydrated_once_with_the_served_ids(monkeypatch):
    """One hydration call, in served order -- not one query per candidate."""
    from service.retrieval_replay import replay_search_response

    _, hydration_calls = _install(monkeypatch)

    replay_search_response(EVENT_ID)

    assert hydration_calls == [SERVED_ORDER]


def test_signals_come_from_the_receipt_not_from_recomputation(monkeypatch):
    """`final_rank` is the served space and `pre_rerank_rank` the pool space."""
    from service.retrieval_replay import replay_search_response

    _install(monkeypatch)

    leader = replay_search_response(EVENT_ID).results[0]

    assert leader.product_id == 502
    assert leader.signals.final_rank == 1
    assert leader.signals.pre_rerank_rank == 11
    assert leader.signals.rrf_score == pytest.approx(1.031)
    assert leader.signals.fts.rank == 4
    assert leader.signals.fts.rrf_contribution == pytest.approx(1.0151)
    assert leader.signals.semantic.rrf_contribution == pytest.approx(1.0161)
    assert leader.signals.trigram.rank is None
    assert leader.signals.trigram.raw_score is None
    assert leader.signals.rerank_rank == 1
    assert leader.signals.rerank_score == pytest.approx(0.8)


def test_coverage_is_none_because_the_receipt_does_not_store_it(monkeypatch):
    from service.retrieval_replay import replay_search_response

    _install(monkeypatch)

    assert replay_search_response(EVENT_ID).coverage is None


def test_diagnostics_repeat_the_receipt_and_invent_nothing(monkeypatch):
    """Stored fields come back verbatim; the one unstored field is `None`.

    `embedding_dimensions` is the only `RetrievalDiagnostics` field neither
    `mosaic.search_event` nor its `diagnostics` jsonb records. Filling it from
    the running service's configuration would report today's settings as though
    the receipt had witnessed them.
    """
    from service.retrieval_replay import replay_search_response

    _install(monkeypatch)

    diagnostics = replay_search_response(EVENT_ID).diagnostics

    assert diagnostics is not None
    assert diagnostics.candidate_counts == PERSISTED_CANDIDATE_COUNTS
    assert diagnostics.embedding_dimensions is None
    assert diagnostics.strategy == "rrf_fusion+rerank+exact_sku_preservation"
    assert diagnostics.embedding_model_id == "us.cohere.embed-v4:0"
    assert diagnostics.rerank_model_id == "cohere.rerank-v3-5:0"
    assert diagnostics.rerank_status == "applied"
    assert diagnostics.ranking_policy == [
        "RRF candidate fusion",
        "managed reranking",
        "exact SKU preservation",
    ]
    assert diagnostics.stage_timings_ms == PERSISTED_STAGE_TIMINGS
    assert diagnostics.total_latency_ms == 214
    assert diagnostics.warnings == []
    assert diagnostics.retrieval_profile.fused_limit == 50
    assert diagnostics.retrieval_profile.authorized_limit == 12


def test_a_failed_run_reports_no_diagnostics_rather_than_a_partial_one(monkeypatch):
    """The failure UPDATE writes no rerank status, so there is nothing to serve."""
    from service.retrieval_replay import replay_search_response

    _install(
        monkeypatch,
        event=_event_row(
            candidate_counts={},
            total_latency_ms=91,
            diagnostics={"status": "failed", "error_type": "ClientError"},
        ),
    )

    assert replay_search_response(EVENT_ID).diagnostics is None


def test_unknown_event_is_refused(monkeypatch):
    from service.retrieval_replay import UnknownSearchEvent, replay_search_response

    _install(monkeypatch, event=None)

    with pytest.raises(UnknownSearchEvent) as error:
        replay_search_response(EVENT_ID)

    detail = str(error.value)
    assert str(EVENT_ID) in detail
    assert "fix:" in detail


def test_route_serves_the_reconstructed_response(monkeypatch):
    from fastapi.testclient import TestClient

    from service.main import app

    _install(monkeypatch)

    response = TestClient(app).get(f"/api/retrieval/events/{EVENT_ID}/response")

    assert response.status_code == 200
    body = response.json()
    assert body["search_event_id"] == str(EVENT_ID)
    assert [row["product_id"] for row in body["results"]] == SERVED_ORDER
    assert body["coverage"] is None
    assert body["diagnostics"]["candidate_counts"] == PERSISTED_CANDIDATE_COUNTS
    assert body["diagnostics"]["embedding_dimensions"] is None


def test_route_404s_on_an_unknown_event(monkeypatch):
    from fastapi.testclient import TestClient

    from service.main import app

    _install(monkeypatch, event=None)

    response = TestClient(app).get(f"/api/retrieval/events/{EVENT_ID}/response")

    assert response.status_code == 404
    assert "fix:" in response.json()["detail"]


def test_route_409s_on_a_receipt_that_cannot_be_replayed(monkeypatch):
    """An unreplayable receipt is a conflict with what is stored, not a 500.

    The event exists, so 404 would be wrong; the replay refuses because the
    receipt cannot answer faithfully. Before this the `KeyError` escaped the
    route and the reason went out as an unhandled server error.
    """
    from fastapi.testclient import TestClient

    from service.main import app

    profile = dict(PERSISTED_PROFILE)
    del profile["authorized_limit"]
    _install(monkeypatch, event=_event_row(retrieval_profile=profile))

    response = TestClient(app, raise_server_exceptions=False).get(
        f"/api/retrieval/events/{EVENT_ID}/response"
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "authorized_limit" in detail
    assert "fix:" in detail
    # `str()` on a KeyError quotes the whole message, so the route unwraps
    # `args[0]` the way the other KeyError handlers in `service/main.py` do.
    assert not detail.startswith("'")


def test_replay_calls_no_model_and_re_executes_no_retrieval(monkeypatch):
    """The receipt is the whole answer: no embedding, no fusion, no rerank.

    Witness: the fake connection records every statement, and the assertion
    below proves both reads ran, so the route cannot pass by doing nothing.
    """
    from fastapi.testclient import TestClient

    from service import embeddings, main, rerank, retrieval
    from service.main import app

    connection, hydration_calls = _install(monkeypatch)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("replay must not re-execute retrieval or call a model")

    monkeypatch.setattr(main, "search_with_telemetry", forbidden)
    monkeypatch.setattr(retrieval.RetrievalService, "search", forbidden)
    monkeypatch.setattr(retrieval, "get_embedding_provider", forbidden)
    monkeypatch.setattr(embeddings, "get_embedding_provider", forbidden)
    monkeypatch.setattr(rerank, "get_reranker", forbidden)

    response = TestClient(app).get(f"/api/retrieval/events/{EVENT_ID}/response")

    assert response.status_code == 200
    assert len(connection.executed) == 2
    assert hydration_calls == [SERVED_ORDER]
    statements = " ".join(sql for sql, _ in connection.executed)
    assert "INSERT" not in statements
    assert "UPDATE" not in statements
    assert "search_hybrid_rrf" not in statements
