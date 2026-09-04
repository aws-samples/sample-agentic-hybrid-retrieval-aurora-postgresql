"""Rebuild one persisted retrieval as the `SearchResponse` it originally served.

A run carried from Shop into the retrieval lab has to render the rows Shop was
shown, not rows a second search happens to produce for the same words. So this
module reads `mosaic.search_event` and `mosaic.search_result_event` and hydrates
the served products through `service.catalog.get_product_summaries` -- the same
loader the compare route uses. It embeds nothing, fuses nothing, and reranks
nothing.

`mosaic.search_result_event` records the whole fused pool while the response
returned only the top `result_limit` of it, so `served_window` narrows the stored
rows back to the window the participant was actually shown.

What the receipt does not record is reported as `None`, never filled in from the
running service. `SearchResponse.coverage` is not persisted at all, and
`RetrievalDiagnostics.embedding_dimensions` is the one diagnostics field neither
the columns nor the `diagnostics` jsonb carries.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from service.catalog import get_product_summaries
from service.db import connect
from service.models import (
    ProductSummary,
    RetrievalDiagnostics,
    RetrievalProfile,
    SearchResponse,
)
from service.retrieval import signals_from_receipt

_EVENT_SQL = """
    SELECT search_event_id, query_text, normalized_query, filters,
           retrieval_profile, retrieval_strategy, embedding_model_id,
           rerank_model_id, candidate_counts, total_latency_ms, diagnostics
    FROM mosaic.search_event
    WHERE search_event_id = %s
"""

_CANDIDATE_SQL = """
    SELECT product_id, result_rank, fts_rank, trigram_rank, semantic_rank,
           fused_rank, rerank_rank, scores, provenance
    FROM mosaic.search_result_event
    WHERE search_event_id = %s
    ORDER BY result_rank
"""


class UnknownSearchEvent(Exception):
    """No `mosaic.search_event` row carries the requested id."""


def replay_search_response(search_event_id: UUID) -> SearchResponse:
    """Serve one persisted retrieval as a `SearchResponse`.

    Raises:
        UnknownSearchEvent: no event row carries `search_event_id`.
    """
    event, candidates = _read_receipt(search_event_id)
    served = served_window(event, candidates)
    products = get_product_summaries([row["product_id"] for row in served])
    return build_search_response(event, served, products)


def served_window(
    event: dict[str, Any], candidates: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The rows the original response returned, in the order it returned them.

    `mosaic.search_result_event` holds the whole fused pool, not the served
    window: `RetrievalService.search` persists every candidate it fused and then
    returns `candidates[:request.limit]`. Replaying every stored row would show
    fifty products to a participant who was served twelve.

    The window is the receipt's own `retrieval_profile.result_limit`, which
    `RetrievalService._profile` sets from that request's `limit`, narrowed to
    `authorized_limit`. An agent-originated search records the reranker's pool
    (`result_limit` 50) while granting one to three products, and
    `service.retrieval_scope` refuses anything past that grant; serving product
    content for the whole pool here would reopen the window that guard closes.
    On a Shop run the two limits are equal, so the narrowing is a no-op.

    Both are required, and both are read from the persisted jsonb rather than
    from a parsed `RetrievalProfile`, because a receipt missing either key would
    otherwise take today's yaml value and present it as the window that request
    used. A null `authorized_limit` is refused for the same reason
    `service.retrieval_scope` denies on one: `SearchRequest` resolves the field
    to the served `limit` when the caller omits it, so every receipt written by
    `service.retrieval.search` carries an integer. A receipt without one either
    predates explicit authorization or was not written by that path, and reading
    it as "no narrowing" is precisely the fail-open the field exists to close.
    """
    result_limit = (event["retrieval_profile"] or {}).get("result_limit")
    if result_limit is None:
        raise KeyError(
            f"FAIL replay {event['search_event_id']} served window: found a "
            "persisted retrieval_profile with no result_limit, so how many of "
            "the pooled rows the response returned is unknown; fix: replay an "
            "event recorded by service.retrieval.search, which always persists "
            "result_limit."
        )
    authorized_limit = (event["retrieval_profile"] or {}).get("authorized_limit")
    if authorized_limit is None:
        raise KeyError(
            f"FAIL replay {event['search_event_id']} served window: found a "
            "persisted retrieval_profile with no authorized_limit, so how many "
            "of the pooled rows the caller was authorized to see is unknown; "
            "fix: replay an event recorded by service.retrieval.search, which "
            "always persists authorized_limit."
        )
    window = min(result_limit, authorized_limit)
    ordered = sorted(candidates, key=lambda row: row["result_rank"])
    return ordered[:window]


def build_search_response(
    event: dict[str, Any],
    served: list[dict[str, Any]],
    products: list[ProductSummary],
) -> SearchResponse:
    """Assemble the response from persisted rows and already-hydrated products.

    Pure: it issues no query, so the reconstruction can be read and tested apart
    from the two SELECTs that feed it. `served` must already be the window
    `served_window` returns.
    """
    by_product = {product.product_id: product for product in products}
    missing = [
        row["product_id"] for row in served if row["product_id"] not in by_product
    ]
    if missing:
        raise KeyError(
            f"FAIL replay {event['search_event_id']} product hydration: found "
            f"receipt rows for products {missing} that the catalog no longer "
            "returns; fix: the receipt outlived its products, so re-run the "
            "search instead of replaying this event."
        )
    return SearchResponse(
        search_event_id=event["search_event_id"],
        query=event["query_text"],
        normalized_query=event["normalized_query"],
        applied_filters=event["filters"],
        results=[
            by_product[row["product_id"]].model_copy(
                update={"signals": signals_from_receipt(row)}
            )
            for row in served
        ],
        diagnostics=_diagnostics(event),
        # Term coverage is computed per request against the corpus vocabulary
        # and never written to the receipt, so a replay has nothing to report.
        # Recomputing it here would answer for today's corpus, not the run's.
        coverage=None,
    )


def _read_receipt(
    search_event_id: UUID,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with connect() as connection:
        event = connection.execute(_EVENT_SQL, (search_event_id,)).fetchone()
        if event is None:
            raise UnknownSearchEvent(
                f"FAIL replay {search_event_id}: found no mosaic.search_event "
                "row with that id; fix: run the search again and use the "
                "`search_event_id` its response returns."
            )
        candidates = connection.execute(_CANDIDATE_SQL, (search_event_id,)).fetchall()
    return dict(event), [dict(row) for row in candidates]


def _recorded_rerank_status(event: dict[str, Any], recorded: dict[str, Any]) -> str:
    """The rerank outcome the receipt recorded, refused by name when absent."""
    status = recorded.get("rerank_status")
    if status is None:
        raise KeyError(
            f"FAIL replay {event['search_event_id']} diagnostics: found a completed "
            "receipt with no rerank_status, so whether reranking was applied is "
            "unknown; fix: replay an event recorded by service.retrieval.search, "
            "which persists rerank_status on every completed run."
        )
    return str(status)


def _replayed_profile(event: dict[str, Any]) -> RetrievalProfile:
    """The receipt's own profile, refused unless it carries every field.

    `RetrievalProfile` resolves its defaults from `db/config/retrieval.yaml` at
    construction time, so `RetrievalProfile(**persisted)` fills any absent key
    with today's configured value and serves it as a number the run witnessed.
    `served_window` already refuses that for `result_limit`; every other field
    on the profile has the same problem, and a reader comparing an old receipt's
    `ef_search` or `rrf_k` against a re-run is exactly who it misleads.

    `service.retrieval.search` persists `profile.model_dump_json()`, so a
    receipt from that path carries the whole key set.

    Raises:
        KeyError: The persisted profile is missing at least one field.
    """
    persisted = event["retrieval_profile"] or {}
    missing = sorted(set(RetrievalProfile.model_fields) - set(persisted))
    if missing:
        raise KeyError(
            f"FAIL replay {event['search_event_id']} diagnostics: found a "
            f"persisted retrieval_profile with no {', '.join(missing)}, so "
            "those fields would be filled from today's db/config/retrieval.yaml "
            "and served as the run's own; fix: replay an event recorded by "
            "service.retrieval.search, which persists the whole profile."
        )
    return RetrievalProfile(**persisted)


def _diagnostics(event: dict[str, Any]) -> RetrievalDiagnostics | None:
    """Rebuild the diagnostics the original response carried, or report none.

    Split across the receipt: the columns hold strategy, model ids, candidate
    counts, and latency, while the `diagnostics` jsonb holds the rerank status,
    ranking policy, stage timings, and warnings.

    That jsonb reaches `status = 'ok'` only in the UPDATE a completed run makes,
    so any other value means there is no diagnostics record to serve. A failed
    run stores an error type and nothing else, and assembling the rest from the
    columns would describe a run that never finished as though it had.
    """
    recorded = event.get("diagnostics") or {}
    if recorded.get("status") != "ok":
        return None
    return RetrievalDiagnostics(
        strategy=event["retrieval_strategy"],
        embedding_model_id=event["embedding_model_id"],
        # Not persisted anywhere on the receipt. Reading the running service's
        # configured width would report today's settings as the run's.
        embedding_dimensions=None,
        rerank_model_id=event["rerank_model_id"],
        rerank_status=_recorded_rerank_status(event, recorded),
        ranking_policy=recorded.get("ranking_policy") or [],
        retrieval_profile=_replayed_profile(event),
        candidate_counts=event["candidate_counts"],
        stage_timings_ms=recorded.get("stage_timings_ms") or {},
        total_latency_ms=event["total_latency_ms"],
        warnings=recorded.get("warnings") or [],
    )
