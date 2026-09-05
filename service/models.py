"""Typed public contracts for search, catalog inspection, and agent tools."""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

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


# Bounds measured against the live `mosaic_search.product_document.attributes`
# column on 2026-08-27: max key length 25, max scalar string value length 24,
# max array length 6, max string array-element length 25. Each bound below
# carries roughly 2.5-4x headroom over its measurement, matching `brands`
# above, which is bounded the same way. The value bound and the list-item
# bound are declared separately, even though both currently read 96, so that
# removing either one leaves the other in force.
AttributeKey = Annotated[str, StringConstraints(min_length=1, max_length=64)]
AttributeValueString = Annotated[str, StringConstraints(min_length=1, max_length=96)]
AttributeListItem = (
    Annotated[str, StringConstraints(min_length=1, max_length=96)] | int | float | bool
)
AttributeList = Annotated[list[AttributeListItem], Field(max_length=16)]
AttributeValue = AttributeValueString | int | float | bool | AttributeList


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
    brands: list[Annotated[str, StringConstraints(min_length=1, max_length=120)]] = (
        Field(default_factory=list, max_length=64)
    )
    availability: Availability | None = None
    in_stock_only: bool = False
    min_price_cents: int | None = Field(default=None, ge=0, le=100_000_000)
    max_price_cents: int | None = Field(default=None, ge=0, le=100_000_000)
    min_rating: float | None = Field(default=None, ge=0, le=5)
    attributes: dict[AttributeKey, AttributeValue] = Field(
        default_factory=dict, max_length=32
    )
    include_refurbished: bool = False
    include_sponsored: bool = False

    @model_validator(mode="after")
    def _reject_contradictions(self) -> SearchFilters:
        """Reject filter intersections that cannot match a catalog row."""
        if (
            self.min_price_cents is not None
            and self.max_price_cents is not None
            and self.min_price_cents > self.max_price_cents
        ):
            raise ValueError(
                f"min_price_cents is {self.min_price_cents}, which exceeds "
                f"max_price_cents {self.max_price_cents}; fix: lower "
                "min_price_cents or raise max_price_cents"
            )

        in_stock_availability = {"in_stock", "low_stock"}
        if (
            self.in_stock_only
            and self.availability is not None
            and self.availability not in in_stock_availability
        ):
            raise ValueError(
                f"availability is {self.availability!r} while in_stock_only is "
                f"{self.in_stock_only}; fix: use one of "
                f"{sorted(in_stock_availability)} or set in_stock_only to false"
            )

        if self.brand is not None and self.brands:
            normalized_brands = {brand.casefold() for brand in self.brands}
            if self.brand.casefold() not in normalized_brands:
                raise ValueError(
                    f"brand is {self.brand!r}, which is absent from brands "
                    f"{self.brands!r}; fix: include {self.brand!r} in brands or "
                    "remove one of the two brand constraints"
                )
        return self

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
    #: How many of the served results the caller authorizes for downstream
    #: evidence and comparison. Defaults to everything it was served. The agent
    #: declares a narrower window than it requests, because it asks for the full
    #: rerank pool to inspect it and hands the model only the top slice.
    authorized_limit: int | None = Field(default=None, ge=1, le=50)
    include_diagnostics: bool = True
    rerank: bool = True
    session_id: str | None = Field(default=None, max_length=200)

    @field_validator("query")
    @classmethod
    def _reject_blank_query(cls, value: str) -> str:
        """Reject a query that is only whitespace.

        `min_length` counts characters, so "  " passes it and then normalizes to
        the empty string, which still costs an embedding call and a persisted
        search event.
        """
        if not value.strip():
            raise ValueError(
                "query is only whitespace; fix: pass at least one "
                "non-whitespace character"
            )
        return value

    @model_validator(mode="after")
    def _bound_authorized_limit(self) -> SearchRequest:
        """Resolve and bound the authorization window against the served window.

        An authorization window wider than the served window would authorize
        products the caller never received, which is the fail-open this field
        exists to close.
        """
        if self.authorized_limit is None:
            self.authorized_limit = self.limit
        elif self.authorized_limit > self.limit:
            raise ValueError(
                f"authorized_limit is {self.authorized_limit}, which exceeds "
                f"limit {self.limit}; fix: set authorized_limit to at most "
                f"{self.limit}, or raise limit"
            )
        return self


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
    #: The caller's declared authorization window, persisted with the receipt.
    #: `None` on a profile built outside a request, which the scope guard treats
    #: as no grant at all rather than inferring one from `result_limit`.
    authorized_limit: int | None = Field(default=None, ge=1, le=100)
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
    #: `None` only on a replayed run. `mosaic.search_event` records the embedding
    #: model id but never the vector width, so the replay route reports the width
    #: as unknown rather than reading the running service's configured value and
    #: presenting today's settings as something the receipt witnessed. A live
    #: search always fills it, which is why there is no default here.
    embedding_dimensions: int | None
    rerank_model_id: str | None
    rerank_status: Literal["applied", "disabled", "unavailable"]
    ranking_policy: list[str] = Field(default_factory=list)
    retrieval_profile: RetrievalProfile
    candidate_counts: dict[str, int]
    stage_timings_ms: dict[str, float]
    total_latency_ms: int
    warnings: list[str] = Field(default_factory=list)


#: Query-coverage verdicts live here rather than in `service.coverage` so that
#: importing the response models never imports psycopg: the packaged MCP
#: adapter compares its contract against these classes from an environment
#: that has no database driver.
CoverageConfidence = Literal["grounded", "unanchored", "unavailable"]


class TermCoverage(BaseModel):
    """One parsed request token, and what the catalog holds for it."""

    ordinal: int
    token: str
    token_kind: str
    lexeme: str | None = None
    ndoc: int = 0
    closest_lexeme: str | None = None
    closest_similarity: float | None = None
    verdict: Literal["matched", "recoverable", "unmatched_anchor", "ignored"]


class QueryCoverage(BaseModel):
    """Whether every identity-bearing term of a request exists in the catalog.

    `confidence` is the field a consumer branches on:

    - `grounded`: every term either matched or is a recoverable misspelling.
      Retrieval and citation proceed normally.
    - `unanchored`: at least one term named something the catalog does not
      carry. Results are still returned, and still ordered, but they answer a
      narrower question than the one asked. Synthesis must not present them as
      the answer of record.
    - `unavailable`: the corpus vocabulary has not been built, so no verdict was
      reached. Consumers must behave exactly as they did before this module
      existed. An unseeded vocabulary makes every term look absent, and treating
      that as `unanchored` would refuse every request on the deployment.
    """

    confidence: CoverageConfidence
    unmatched_terms: list[str] = Field(default_factory=list)
    terms: list[TermCoverage] = Field(default_factory=list)
    note: str = ""

    @property
    def is_anchored(self) -> bool:
        """False only when a term named something the catalog does not carry."""
        return self.confidence != "unanchored"


class SearchResponse(BaseModel):
    search_event_id: UUID
    query: str
    normalized_query: str
    applied_filters: dict[str, Any]
    results: list[ProductSummary]
    diagnostics: RetrievalDiagnostics | None = None
    #: Whether the request named anything the catalog does not carry. `results`
    #: is unaffected by this: coverage classifies, it never filters, so an
    #: unanchored request still returns its closest products in their measured
    #: order. What changes is how a surface may present them, and whether
    #: synthesis may treat them as an answer of record. `None` on a database
    #: without `mosaic_search.query_term_coverage` installed.
    coverage: QueryCoverage | None = None


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


class ReviewHighlight(BaseModel):
    """One verbatim customer-review excerpt with the product it reviews.

    `quote` is an excerpt, not a summary: the opening sentence of the review
    body, byte-for-byte. The full review stays one click away on the product
    page, and `source_uri` addresses the evidence row the excerpt came from.
    """

    review_id: int
    product_id: int
    product_title: str
    brand: str
    rating: float
    quote: str
    verified_purchase: bool
    review_date: str | None = None
    source_uri: str


class ReviewHighlightsResponse(BaseModel):
    highlights: list[ReviewHighlight]


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

    #: The `search_event_id` of the retrieval that granted this product. Required:
    #: evidence is the capability the grant boundary protects, so there is no
    #: unscoped door. See `service/retrieval_scope.py`.
    retrieval_scope_id: UUID
    evidence_query: str = Field(min_length=1, max_length=1_000)
    limit: int = Field(default=6, ge=1, le=12)

    @field_validator("evidence_query")
    @classmethod
    def _reject_blank_evidence_query(cls, value: str) -> str:
        """Reject a question that is only whitespace.

        Same defect as `SearchRequest.query`: `min_length=1` admits a single
        space, which still reaches the embedding call in
        `get_question_ranked_product_evidence` after normalization strips it.
        """
        if not value.strip():
            raise ValueError(
                "evidence_query is only whitespace; fix: pass at least one "
                "non-whitespace character"
            )
        return value


class ProductEvidenceResponse(BaseModel):
    """Question-ranked evidence records for one product."""

    product_id: int
    evidence: list[EvidenceRecord]


class ProductComparisonRequest(BaseModel):
    """Products to compare, all of which the retrieval scope must have granted."""

    model_config = ConfigDict(extra="forbid")

    product_ids: list[int] = Field(min_length=2, max_length=5)


class ProductComparisonResponse(BaseModel):
    """A side-by-side projection over products one retrieval already granted."""

    retrieval_scope_id: UUID
    products: list[ProductSummary]


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
    # Mirrors the mosaic.tool_outcome enum in db/sql/01_schemas_and_types.sql;
    # a value the database accepts must survive the API response too.
    outcome: Literal["success", "denied", "error", "timeout"] = "success"
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


#: What the agent did with the question, as opposed to whether the request
#: succeeded. Both values are HTTP 200: a declined answer is an answer of
#: record, not a failure. HTTP 503 stays reserved for the fail-closed pipeline
#: signal Lab 3 teaches, where retrieval or grounding could not run at all.
AgentOutcome = Literal["grounded", "declined"]


class AgentResponse(BaseModel):
    """The agent's answer of record for one turn.

    `outcome` is the field a client branches on. A `declined` answer is what
    the agent returns when every search it issued named something the catalog
    does not carry: `answer` states the absence, and `recommendations` and
    `citations` are empty because there is nothing grounded to put in them.
    Presenting the closest products under that question would be the exact
    failure `service.coverage` exists to stop, since most of the query
    matching is what makes the wrong answer look right.
    """

    agent_run_id: UUID
    question: str
    answer: str
    plan: list[AgentPlanStep]
    recommendations: list[ProductSummary]
    citations: list[AgentCitation]
    trace: list[ToolTraceStep]
    outcome: AgentOutcome = "grounded"
    #: Why the run declined, naming the unmatched terms. `None` on a grounded
    #: answer, so its presence and `outcome` cannot disagree.
    decline_reason: str | None = None


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


class ScorecardProvenance(BaseModel):
    """Whether the canonical scorecard's numbers may be shown as current.

    `attributed` is the one field the Prove-step UI must branch on for section
    A. It is true only when the artifact's `retrieval_fingerprint` (a hash
    over the files that can move the scored numbers; see
    `service.retrieval_fingerprint`) matches what is currently running, the
    measurement's own worktree was clean, the resolved retrieval settings are
    the ones it was measured with, and the pinned models and query-set hashes
    still match; see `service.scorecard._attribution`. `source_revision`
    is no longer part of that gate -- a strict revision equality can never
    hold, because the artifact is always committed one revision after it was
    measured -- but it stays here as display and audit evidence. Every other
    field here is read straight from the committed artifact, so a reader can
    verify the verdict rather than take it on faith.
    """

    #: What this is, so the surface can name it honestly. The canonical
    #: scorecard is a maintainers' release artifact measured against Aurora at
    #: one revision, not a live proof of the attendee's own retrieval run.
    artifact_kind: Literal["release_baseline"]
    #: When this response was assembled, always distinct from `measured_at`.
    #: A baseline rendered months after it was measured must not read as a
    #: measurement taken now.
    served_at: datetime
    measured_at: datetime
    query_set: str
    query_set_sha256: str
    scored_query_set_sha256: str
    ranked_result_sha256: str
    dataset_manifest_sha256: str
    models: dict[str, str]
    aurora_configuration: dict[str, Any]
    hnsw_settings: dict[str, Any]
    retrieval_profile: dict[str, Any]
    #: The resolved retrieval settings the artifact was measured with, hashed
    #: by `service.retrieval_fingerprint.compute_retrieval_settings_sha256`.
    #: `None` on every artifact written before that hash existed, which fails
    #: the gate closed rather than being read as agreement. It is carried
    #: separately from `retrieval_profile` because environment variables beat
    #: `db/config/retrieval.yaml`, so no file hash can see a change to it.
    retrieval_settings_sha256: str | None
    #: The fingerprint the artifact recorded for itself, which is the identity
    #: of this baseline. Served as its own field because a surface that names
    #: the measurement it is showing must read a value, not scrape one out of
    #: `attribution_note`'s prose. `None` on an artifact that recorded none,
    #: never filled in from the running process.
    retrieval_fingerprint: str | None
    database_instance_id: str
    strategy: str
    source_revision: str | None
    source_worktree_dirty: bool | None
    current_source_revision: str | None
    current_source_worktree_dirty: bool
    #: The same hash resolved by the running process, so a reader can check the
    #: verdict against both halves rather than trusting `attributed`.
    current_retrieval_settings_sha256: str
    attributed: bool
    attribution_note: str


class ScorecardRetrievalQuality(BaseModel):
    """Section A: population IR metrics over the scored search population.

    Real numbers, always present here; the Playground withholds them from
    display whenever `ScorecardProvenance.attributed` is false rather than the
    API inventing a null. `excluded_agent_contract_query_ids` names the query
    that must never be scored as search relevance.
    """

    sample_size: int
    canonical_query_count: int
    sample_description: str
    recall_at_10: float
    mrr: float
    ndcg_at_10: float
    metric_explanations: dict[str, str]
    excluded_agent_contract_query_ids: list[str]
    #: Read straight from the artifact's `per_query_metrics`: `query_id`,
    #: `recall@k`, `reciprocal_rank`, `ndcg@k`, plus `query_text` and
    #: `concept_label` when the artifact was measured after labels were
    #: added. Untyped deliberately -- this is a pass-through of whatever the
    #: committed artifact recorded, not a contract this service defines.
    per_query_metrics: list[dict[str, Any]]


class ScorecardGoldenAnchor(BaseModel):
    """One golden regression anchor, with `query_id` remaining the audit key.

    `query_text` and `concept_label` are read straight from the committed
    artifact's `deterministic_release_checks` entries when present, so a
    golden anchor reads as a behaviour rather than an opaque code. Both
    default to `None`: the artifact committed before this field existed
    carries neither, and the UI must degrade to `query_id` alone rather than
    render `None`.
    """

    query_id: str
    product_id: int
    type: Literal["top_rank", "present_top_k"]
    k: int | None = None
    query_text: str | None = None
    concept_label: str | None = None


class ScorecardRegressionAnchors(BaseModel):
    """Section B: compact PASS/total over golden regression anchors.

    Never mixed into `ScorecardRetrievalQuality`: an anchor is a pass/fail
    check tied to one product's rank, not a graded relevance judgment.
    """

    passed: int
    total: int
    anchors: list[ScorecardGoldenAnchor]
    #: False when the artifact these anchors came from no longer describes the
    #: running revision. `passed` can only ever equal the number of checks the
    #: artifact recorded, because `scripts.score_evals.validate_release_checks`
    #: raises on the first failure and never writes a failing entry -- so a
    #: written artifact always reads N/N. Without this flag the section presents
    #: a historical N/N as present-tense verification.
    verified_for_running_revision: bool


class ScorecardEligibilityContracts(BaseModel):
    """Section C: did retrieval violate a hard eligibility or filter contract.

    Not a relevance judgment: no Recall, MRR, or nDCG is computed over these.
    `fixture_count` is read from the harness's own query-population filter
    (`scripts.score_evals.product_retrieval_queries`), not a number retyped
    for this surface.

    `held` is **not** a constant. It is `True` only while the measurement is
    attributed to the running revision, and `None` -- unknown -- otherwise. The
    justification for `True` is that `scripts.score_evals.validate_hard_negatives`
    raises when any graded-0 product reaches the result window, so an artifact
    cannot exist for a run that violated a contract. That reasoning holds only
    for the revision actually measured, which is why a provenance mismatch makes
    this unknown rather than true.
    """

    fixture_count: int
    held: bool | None
    description: str
    fixture_query_ids: list[str]


class ScorecardAgentContractGuarantee(BaseModel):
    """One deterministic agent/evidence guarantee, backed by real assertions."""

    key: Literal[
        "retrieval_scope",
        "compare_boundary",
        "evidence_authorization",
        "citation_resolution",
        "tool_contract",
    ]
    label: str
    description: str
    assertion_names: list[str]
    falsifiers: list[str]
    #: Populated only for `tool_contract`: the live count of registered agent
    #: tool contracts, from the same registry `/api/tools` serves.
    fixture_count: int | None = None


class ScorecardAgentContracts(BaseModel):
    """Section D: deterministic agent and evidence contracts.

    Real validation data: every assertion name and falsifier is read from
    `service.assertions.ASSERTIONS`, not typed fresh for this surface. No IR
    metric and no LLM judge appears here.
    """

    guarantees: list[ScorecardAgentContractGuarantee]


class ScorecardStageArm(BaseModel):
    """One retrieval-stage arm in Lab 2's ablation.

    `ndcg_at_10_min`/`_max`/`_stdev` are the per-query spread across the same
    20 scored queries `recall_at_10`/`mrr`/`ndcg_at_10` are averaged over --
    carried on every arm so a mean is never shown without the spread that
    qualifies it. 20 queries cannot separate small differences between arms;
    see `stage_ablation.spread_note`.
    """

    key: Literal["semantic_only", "rrf_fused_no_rerank", "rrf_fused_reranked"]
    label: str
    description: str
    recall_at_10: float
    mrr: float
    ndcg_at_10: float
    ndcg_at_10_min: float
    ndcg_at_10_max: float
    ndcg_at_10_stdev: float
    ndcg_at_10_query_wins: int


class ScorecardUnboundedCeilingArm(BaseModel):
    """One ablation arm that the fused-pool ceiling does not constrain."""

    note: str
    recall_at_10: float = Field(validation_alias="recall@10")


class ScorecardCandidateRecallCeiling(BaseModel):
    """The ceiling reranking could ever reach.

    Share of judged-relevant products present anywhere in the fused
    candidate pool before reranking, averaged over the scored queries.
    Reranking only ever reorders that pool -- it never adds a candidate --
    so only the explicitly listed arms downstream of fusion are bounded.
    """

    bounds_arms: list[Literal["rrf_fused_no_rerank", "rrf_fused_reranked"]]
    pool_recall_ceiling: float
    judged_relevant_never_fetched: int
    description: str
    unbounded_arms: dict[
        Literal["semantic_only"],
        ScorecardUnboundedCeilingArm,
    ]


class ScorecardStageAblationQuery(BaseModel):
    """One scored query's nDCG@10 under every arm, plus its own pool-recall
    ceiling row. `ndcg_at_10` is keyed by the same arm keys as
    `ScorecardStageArm.key`."""

    query_id: str
    query_text: str
    ndcg_at_10: dict[str, float]
    pool_recall: float
    relevant_count: int
    found_in_pool: int
    missed_product_ids: list[int]


class ScorecardStageAblation(BaseModel):
    """Section E: what each retrieval stage contributes, measured rather than
    asserted -- semantic-only vs the served fusion function with reranking
    off vs the full served path. A separate artifact and a separate
    attribution gate from section A: this decomposes the same served-path
    quality section A reports as a single number, but is its own
    `data/evals/canonical_stage_ablation.json` measurement, not a re-labeling
    of section A's fields.
    """

    attributed: bool
    attribution_note: str
    measured_at: str
    spread_note: str
    scored_query_count: int
    arms: list[ScorecardStageArm]
    candidate_recall_ceiling: ScorecardCandidateRecallCeiling
    per_query: list[ScorecardStageAblationQuery]


class RetrievalScorecardResponse(BaseModel):
    """The Prove step: one read of the committed canonical evaluation artifact.

    Five sections, never conflated -- A is population relevance metrics, B is
    pass/fail regression anchors, C is hard eligibility/filter contracts, D is
    deterministic agent/evidence contracts, E is the per-stage ablation over
    the same population. Framing: did we fix the scenarios without weakening
    the system, not a participant grade.
    """

    provenance: ScorecardProvenance
    retrieval_quality: ScorecardRetrievalQuality
    regression_anchors: ScorecardRegressionAnchors
    eligibility_contracts: ScorecardEligibilityContracts
    agent_contracts: ScorecardAgentContracts
    stage_ablation: ScorecardStageAblation


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


class LabCheckResult(BaseModel):
    """One acceptance condition, its verdict, and what would falsify it.

    `falsifier` is served alongside `passed` deliberately. A green check is not
    evidence on its own; a reader has to be able to see what would have made it
    fail before treating it as one.
    """

    name: str
    passed: bool
    falsifier: str
    detail: str


class LabStateRecord(BaseModel):
    """Where one lab stands, in the two places a lab can be broken.

    `source_state` reads the marker block the participant edits.
    `database_state` reads the object Aurora currently holds, which is a
    different question: editing `db/sql/09_search_functions.sql` without
    re-applying it leaves a repaired file in front of an unrepaired cluster.
    """

    lab_id: int
    source_state: Literal["solved", "broken"]
    database_state: Literal["applied", "stale", "not_applicable"]
    detail: str


class LabStateResponse(BaseModel):
    labs: list[LabStateRecord]


class CompletionProofRequest(BaseModel):
    """What a proof needs from the caller, which for labs 1 and 2 is nothing."""

    model_config = ConfigDict(extra="forbid")

    #: The turn to grade for Lab 3. Required there and ignored elsewhere: the
    #: proof reads persisted receipts and never spends an agent turn of its own,
    #: so it has to be told which run to read.
    agent_run_id: UUID | None = None


class CompletionProofEvidence(BaseModel):
    """The receipts this proof produced or read, addressable afterwards."""

    search_event_ids: list[UUID] = Field(default_factory=list)
    agent_run_id: UUID | None = None
    evidence_ids: list[int] = Field(default_factory=list)


class CompletionProofIdentity(BaseModel):
    """What produced this verdict, resolved from the running service.

    Distinct from `ReleaseBaselineReference` on purpose: these are the
    attendee's own retrieval identity, and that is the maintainers' measured
    artifact. Conflating them is how a participant's repair would come to be
    graded against numbers measured on a different tree.
    """

    source_revision: str | None
    retrieval_fingerprint: str
    retrieval_settings_sha256: str
    embedding_model_id: str
    rerank_model_id: str
    dataset_manifest_sha256: str


class ReleaseBaselineReference(BaseModel):
    """The release baseline this proof sits next to, never the proof itself.

    `attributed` is false whenever the running tree differs from the measured
    one -- which is the normal state mid-lab, because the participant edits a
    fingerprinted SQL file. It is context for the verdict, not part of it.
    """

    measured_at: datetime
    retrieval_fingerprint: str | None
    attributed: bool


class CompletionProofResponse(BaseModel):
    """One lab's completion verdict, with the evidence behind it.

    `status` is the conjunction of three separate facts, and all three are
    served: every check passed, the source seam is repaired, and Aurora holds
    that repair. A lab whose checks pass against a stale cluster is not
    finished, and neither is a Lab 3 whose old run predates re-breaking the
    source.
    """

    lab_id: int
    status: Literal["pass", "fail"]
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    source_state: Literal["solved", "broken"]
    database_state: Literal["applied", "stale", "not_applicable"]
    checks: list[LabCheckResult]
    evidence: CompletionProofEvidence
    identity: CompletionProofIdentity
    release_baseline: ReleaseBaselineReference
