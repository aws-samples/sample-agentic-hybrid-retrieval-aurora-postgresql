"""Typed public contracts for search, catalog inspection, and agent tools."""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.retrieval_profile import load_profile


def _yaml_default(field: str) -> Callable[[], Any]:
    """Resolve one `RetrievalProfile` default from `db/config/retrieval.yaml`.

    Returns a factory rather than a value so the yaml is read when a profile is
    constructed, not when this module is imported. That keeps the file the single
    source at runtime instead of at import time.
    """
    return lambda: getattr(load_profile(), field)


Domain = Literal[
    "consumer_electronics",
    "running_fitness",
    "home_office",
]
# Matches mosaic.availability_status. The database is the source of truth for
# this vocabulary; the UI maps these to display labels at the edge.
Availability = Literal[
    "in_stock",
    "low_stock",
    "out_of_stock",
    "preorder",
    "discontinued",
]


class SearchFilters(BaseModel):
    """Filter set accepted by `mosaic_search.matches_filters`.

    Prices are integer cents throughout. `numeric` is exact in PostgreSQL but
    becomes an IEEE double the moment it crosses into JSON and JavaScript, so
    money is carried as a count of cents and formatted only for display.
    """

    model_config = ConfigDict(extra="forbid")

    domain: Domain | None = None
    category_key: str | None = Field(default=None, min_length=1, max_length=160)
    brand: str | None = Field(default=None, min_length=1, max_length=120)
    brands: list[str] = Field(default_factory=list)
    availability: Availability | None = None
    in_stock_only: bool = False
    min_price_cents: int | None = Field(default=None, ge=0, le=100_000_000)
    max_price_cents: int | None = Field(default=None, ge=0, le=100_000_000)
    min_rating: float | None = Field(default=None, ge=0, le=5)
    attributes: dict[str, str | int | float | bool | list[Any]] = Field(
        default_factory=dict
    )
    include_refurbished: bool = False
    include_sponsored: bool = False

    def as_sql_json(self) -> dict[str, Any]:
        """Render the filter set for `matches_filters`.

        Empty collections and false booleans are dropped rather than sent: the
        SQL treats a missing key as "unconstrained", and sending
        `in_stock_only: false` would be indistinguishable from sending nothing
        while making every logged filter set noisier to read.
        """
        filters = self.model_dump(exclude_none=True)
        for key in ("attributes", "brands"):
            if not filters.get(key):
                filters.pop(key, None)
        for key in ("in_stock_only", "include_refurbished", "include_sponsored"):
            if not filters.get(key):
                filters.pop(key, None)
        return filters


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=1_000)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    limit: int = Field(default=12, ge=1, le=50)
    include_diagnostics: bool = True
    rerank: bool = True
    session_id: str | None = Field(default=None, max_length=200)


class RankSignal(BaseModel):
    rank: int | None = None
    raw_score: float | None = None
    rrf_contribution: float | None = None


class ResultSignals(BaseModel):
    """Per-arm provenance for one candidate.

    `fts` is named for the PostgreSQL feature that produces it rather than the
    generic "lexical", so a participant reading the response can find the
    matching SQL function.
    """

    fts: RankSignal
    trigram: RankSignal
    semantic: RankSignal
    rrf_score: float
    pre_rerank_rank: int
    pre_rerank_score: float
    rerank_score: float | None = None
    rerank_rank: int | None = None
    exact_sku_match: bool = False
    final_rank: int
    score_semantics: str = (
        "Raw arm, reciprocal-rank fusion, and reranker scores use different "
        "scales and are not probabilities. An exact catalog SKU remains ahead "
        "of model reranking."
    )


class SourceAttribution(BaseModel):
    source_uri: str
    revision: str
    title: str
    quote: str


class ProductSummary(BaseModel):
    """One product as returned by search and catalog browsing.

    Shapes `mosaic_search.product_document`, which is the denormalized retrieval
    projection rather than a join across `mosaic.product` and
    `mosaic.product_offer`.
    """

    product_id: int
    sku: str
    title: str
    short_description: str
    domain: str
    category_key: str
    category_path: str
    brand: str
    model: str
    price_cents: int
    list_price_cents: int
    currency: str = "USD"
    rating: float | None = None
    review_count: int
    availability: Availability
    inventory_count: int
    attributes: dict[str, Any]
    tags: list[Any]
    catalog_asset_key: str | None = None
    canonical_group_id: str | None = None
    media_tier: str | None = None
    is_flagship: bool = False
    is_retrieval_anchor: bool = False
    image_url: str | None = None
    image_source: str | None = None
    signals: ResultSignals | None = None
    sources: list[SourceAttribution] = Field(default_factory=list)


class RetrievalProfile(BaseModel):
    """Tunables for one search.

    Bounds are declared here and enforced per request. **Defaults are not
    declared here**: they resolve from `db/config/retrieval.yaml` through
    `scripts.retrieval_profile`, because a literal in this file would be a second
    copy of every number and the copies are what drifted. `default_factory` runs
    per construction rather than at import, so editing the yaml takes effect
    without restarting an interpreter that has already imported this module.
    """

    model_config = ConfigDict(extra="forbid")

    fts_limit: int = Field(default_factory=_yaml_default("fts_limit"), ge=1, le=1000)
    trigram_limit: int = Field(
        default_factory=_yaml_default("trigram_limit"), ge=1, le=1000
    )
    semantic_limit: int = Field(
        default_factory=_yaml_default("semantic_limit"), ge=1, le=1000
    )
    fused_limit: int = Field(default_factory=_yaml_default("fused_limit"), ge=1, le=250)
    result_limit: int = Field(
        default_factory=_yaml_default("display_limit"), ge=1, le=100
    )
    rrf_k: int = Field(default_factory=_yaml_default("rrf_k"), ge=1)
    # pg_trgm similarity floor for the fuzzy arm. Carried on the profile so both
    # fusion functions receive the same value; a literal at either call site would
    # let one arm's candidate set diverge from the other's.
    trigram_threshold: float = Field(
        default_factory=_yaml_default("trigram_threshold"), gt=0, le=1
    )
    # Per-arm fusion weights. Consumed ONLY by
    # `mosaic_search.search_hybrid_rrf_weighted`; default retrieval ignores them
    # because RRF weights by rank position. Ported historical values (LOSS-3).
    weight_lexical: float = Field(
        default_factory=_yaml_default("weight_lexical"), ge=0, le=1
    )
    weight_semantic: float = Field(
        default_factory=_yaml_default("weight_semantic"), ge=0, le=1
    )
    weight_trigram: float = Field(
        default_factory=_yaml_default("weight_trigram"), ge=0, le=1
    )
    ef_search: int = Field(
        default_factory=_yaml_default("hnsw_ef_search"), ge=1, le=1000
    )
    iterative_scan: Literal["off", "strict_order", "relaxed_order"] = "relaxed_order"
    max_scan_tuples: int = Field(
        default_factory=_yaml_default("hnsw_max_scan_tuples"), ge=1
    )
    scan_mem_multiplier: float = Field(
        default_factory=_yaml_default("hnsw_scan_mem_multiplier"), ge=1
    )


class RetrievalDiagnostics(BaseModel):
    strategy: str
    embedding_model_id: str
    embedding_dimensions: int
    rerank_model_id: str | None
    rerank_status: Literal["applied", "disabled", "unavailable"]
    ranking_policy: list[str] = Field(default_factory=list)
    retrieval_profile: RetrievalProfile
    candidate_counts: dict[str, int]
    stage_timings_ms: dict[str, float]
    total_latency_ms: int
    warnings: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    search_event_id: UUID
    query: str
    normalized_query: str
    applied_filters: dict[str, Any]
    results: list[ProductSummary]
    diagnostics: RetrievalDiagnostics | None = None


class ProductMedia(BaseModel):
    role: str
    sort_order: int
    image_url: str
    image_source: str
    image_key: str | None = None
    alt_text: str


class ProductReview(BaseModel):
    """One source-labeled customer-review evidence row.

    `rating` and `review_date` are optional because the evidence table allows
    both to be null. Defaulting a missing rating to a number would invent
    evidence the catalog does not hold.
    """

    review_id: int
    rating: float | None = None
    title: str | None = None
    body: str
    verified_purchase: bool
    helpful_votes: int
    review_date: str | None = None
    sentiment_score: float | None = None
    source_uri: str
    source_name: str


class EvidenceRecord(BaseModel):
    evidence_id: int
    product_id: int
    evidence_type: str
    source_name: str
    source_uri: str
    revision: str
    title: str
    text: str
    rating: float | None = None
    is_verified: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProductEvidenceRequest(BaseModel):
    """Question used to rank evidence records for one already-retrieved product."""

    model_config = ConfigDict(extra="forbid")

    evidence_query: str = Field(min_length=1, max_length=1_000)
    limit: int = Field(default=6, ge=1, le=12)


class ProductEvidenceResponse(BaseModel):
    """Question-ranked evidence records for one product."""

    product_id: int
    evidence: list[EvidenceRecord]


class ProductDetail(ProductSummary):
    long_description: str
    canonical_group_id: str
    source_system: str
    updated_at: datetime
    media: list[ProductMedia] = Field(default_factory=list)
    reviews: list[ProductReview] = Field(default_factory=list)


class CatalogPage(BaseModel):
    total: int
    offset: int
    limit: int
    products: list[ProductSummary]
    facets: dict[str, list[dict[str, Any]]]


class CatalogSuggestion(BaseModel):
    """One catalog identity that can complete a shopper's query."""

    kind: Literal["product", "brand", "category"]
    label: str
    query: str
    product_id: int | None = None
    domain: Domain | None = None
    brand: str | None = None
    category_key: str | None = None
    category_path: str | None = None


class CatalogSuggestionsResponse(BaseModel):
    query: str
    suggestions: list[CatalogSuggestion]


class SearchEventRecord(BaseModel):
    """One row of `mosaic.search_event`."""

    search_event_id: UUID
    occurred_at: datetime
    session_id: str | None = None
    query_text: str
    normalized_query: str | None = None
    filters: dict[str, Any]
    retrieval_profile: dict[str, Any]
    source_revision: str | None = None
    source_worktree_dirty: bool | None = None
    dataset_manifest_sha256: str | None = None
    embedding_model_id: str | None = None
    rerank_model_id: str | None = None
    retrieval_strategy: str | None = None
    database_instance_id: str | None = None
    database_version: str | None = None
    vector_extension_version: str | None = None
    aurora_instance_class: str | None = None
    hnsw_settings: dict[str, Any] = Field(default_factory=dict)
    candidate_counts: dict[str, int]
    total_latency_ms: int | None = None
    plan_json: list[dict[str, Any]] | None = None
    diagnostics: dict[str, Any]


class SearchResultEventRecord(BaseModel):
    """One row of `mosaic.search_result_event`.

    `scores` and `provenance` are passed through as the database wrote them
    rather than flattened into typed fields: the arm set is a database concern,
    and re-declaring it here would mean editing two places whenever a channel is
    added.
    """

    product_id: int
    result_rank: int
    fts_rank: int | None = None
    trigram_rank: int | None = None
    semantic_rank: int | None = None
    fused_rank: int | None = None
    rerank_rank: int | None = None
    scores: dict[str, Any]
    provenance: dict[str, Any]


class RetrievalRunResponse(BaseModel):
    run: SearchEventRecord
    candidates: list[SearchResultEventRecord]


class RetrievalPlanResponse(BaseModel):
    search_event_id: UUID
    plan: list[dict[str, Any]]


class FusionCandidateComparison(BaseModel):
    """One candidate's position under both fusion methods.

    All three arm ranks travel with the row. `NULL` means the arm did not return
    this candidate, which is a fact about the arm rather than a missing value.
    """

    product_id: int
    fts_rank: int | None = None
    trigram_rank: int | None = None
    semantic_rank: int | None = None
    unweighted_rrf_score: float
    weighted_rrf_score: float
    unweighted_rank: int
    weighted_rank: int
    # Negative means the weighted order moved this candidate up.
    rank_delta: int


class FusionComparisonResponse(BaseModel):
    """Unweighted and weighted RRF over one identical candidate pool.

    `candidate_sets_identical` is the substrate assertion's verdict. It cannot be
    false in a response — the service raises instead of returning a comparison
    over two different pools — so it is carried to make the guarantee legible
    rather than implicit.
    """

    fusion_comparison_id: UUID
    query: str
    applied_filters: dict[str, Any]
    rrf_k: int
    weights: dict[str, float]
    candidate_sets_identical: bool
    candidate_count: int
    unweighted_order: list[int]
    weighted_order: list[int]
    orders_differ: bool
    unweighted_latency_ms: int
    weighted_latency_ms: int
    candidates: list[FusionCandidateComparison]
    moved_count: int


class AgentContextProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=300)
    model: str = Field(min_length=1, max_length=120)


class AgentConversationContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    previous_agent_run_id: UUID
    previous_question: str = Field(min_length=4, max_length=2_000)
    recommendations: list[AgentContextProduct] = Field(
        min_length=1,
        max_length=4,
    )


class AgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=4, max_length=2_000)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    result_limit: int = Field(default=6, ge=2, le=12)
    context: AgentConversationContext | None = None


class AgentPlanStep(BaseModel):
    query: str
    filters: SearchFilters = Field(default_factory=SearchFilters)
    purpose: str = Field(min_length=1, max_length=300)


class ToolTraceStep(BaseModel):
    sequence: int
    tool: str
    detail: str
    retrieval_run_id: UUID | None = None
    result_count: int | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    outcome: Literal["success", "error"] = "success"
    origin: Literal["model", "controller_fallback"] = "model"
    latency_ms: float | None = Field(default=None, ge=0)


class AgentCitation(BaseModel):
    number: int
    evidence_id: int
    evidence_type: str
    product_id: int
    source_uri: str
    revision: str
    title: str
    quote: str


class AgentResponse(BaseModel):
    agent_run_id: UUID
    question: str
    answer: str
    plan: list[AgentPlanStep]
    recommendations: list[ProductSummary]
    citations: list[AgentCitation]
    trace: list[ToolTraceStep]


class AgentPartial(BaseModel):
    """What retrieval has produced part-way through a run.

    The same fields as `AgentResponse` minus the answer and its citations, which
    do not exist until the grounded synthesis tool writes the answer of record.
    Every row here was returned by a tool that already ran, so a client can show
    the shortlist the agent is working from without waiting for, or inferring,
    the answer.
    """

    plan: list[AgentPlanStep]
    candidates: list[ProductSummary]
    trace: list[ToolTraceStep]


class HnswProbeRequest(BaseModel):
    """One live HNSW probe.

    Every bound here is enforced before any SQL runs. `filter_preset` is a key into
    `service.hnsw_presets.FILTER_PRESETS`, never a predicate, so no request value can
    reach the query text. `extra="forbid"` keeps a caller from smuggling in a planner
    setting alongside the tuning parameters.

    The ranges mirror what `mosaic_search.configure_hnsw` already validates, so a
    rejected probe fails at the contract rather than as a database exception.
    """

    model_config = ConfigDict(extra="forbid")

    anchor_product_id: int = Field(ge=1)
    # Bounds are declared here; defaults are not. They resolve from
    # db/config/retrieval.yaml through scripts.retrieval_profile, exactly as
    # RetrievalProfile does, because a literal here would be a second copy of a served
    # number — and config_tripwire caught precisely that when these were hardcoded.
    ef_search: int = Field(
        default_factory=_yaml_default("hnsw_ef_search"), ge=1, le=1000
    )
    # Taken from RetrievalProfile rather than restated. `iterative_scan` is a string,
    # so it sits outside the yaml's numeric bounds table and outside the tripwire's
    # NUMBER_NAMES; deferring to the served profile keeps it to one default rather than
    # a copy the check cannot see.
    iterative_scan: Literal["off", "strict_order", "relaxed_order"] = Field(
        default_factory=lambda: RetrievalProfile().iterative_scan
    )
    # The lower bound is 1, the pre-2026-08-17 default, so a participant can reproduce
    # the candidate truncation it caused and then fix it. The *default* is the yaml's.
    scan_mem_multiplier: float = Field(
        default_factory=_yaml_default("hnsw_scan_mem_multiplier"), ge=1, le=64
    )
    max_scan_tuples: int = Field(
        default_factory=_yaml_default("hnsw_max_scan_tuples"), ge=1, le=2_000_000
    )
    filter_preset: str = Field(default="none", min_length=1, max_length=40)
    k: int = Field(default=10, ge=1, le=50)
    # Which index representation to probe. halfvec and bit are casts of the same fp32
    # column, so switching here changes the index the query reaches, not the data.
    representation: Literal["fp32", "halfvec", "binary"] = "fp32"
    # Candidates the binary first pass retrieves before the fp32 rerank. Ignored for the
    # other two. The upper bound is generous because the measured curve is still climbing
    # at 200: 0.44 at x10, 0.76 at x50, 0.93 at x200 against 0.99 for fp32.
    overfetch: int = Field(default=100, ge=1, le=1000)
