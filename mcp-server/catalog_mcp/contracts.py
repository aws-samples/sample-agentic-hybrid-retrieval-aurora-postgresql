"""Versioned wire contracts for the catalog API consumed by this adapter.

These models intentionally describe the HTTP boundary rather than importing the
application package. The source test suite compares their response fields with
``service.models``; the built wheel remains independently installable.
"""

from __future__ import annotations

from datetime import datetime
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

Domain = Literal[
    "consumer_electronics",
    "running_fitness",
    "home_office",
]
Availability = Literal[
    "in_stock",
    "low_stock",
    "out_of_stock",
    "preorder",
    "discontinued",
]
AttributeKey = Annotated[str, StringConstraints(min_length=1, max_length=64)]
AttributeValueString = Annotated[str, StringConstraints(min_length=1, max_length=96)]
AttributeListItem = (
    Annotated[str, StringConstraints(min_length=1, max_length=96)] | int | float | bool
)
AttributeList = Annotated[list[AttributeListItem], Field(max_length=16)]
AttributeValue = AttributeValueString | int | float | bool | AttributeList


class WireModel(BaseModel):
    """Reject API drift instead of silently dropping fields from tool output."""

    model_config = ConfigDict(extra="forbid")


class SearchFilters(WireModel):
    """The filter subset exposed by the MCP search tool."""

    domain: Domain | None = None
    category_key: str | None = Field(default=None, min_length=1, max_length=160)
    brand: str | None = Field(default=None, min_length=1, max_length=120)
    availability: Availability | None = None
    in_stock_only: bool = False
    min_price_cents: int | None = Field(default=None, ge=0, le=100_000_000)
    max_price_cents: int | None = Field(default=None, ge=0, le=100_000_000)
    min_rating: float | None = Field(default=None, ge=0, le=5)
    attributes: dict[AttributeKey, AttributeValue] = Field(
        default_factory=dict,
        max_length=32,
    )

    def as_sql_json(self) -> dict[str, Any]:
        """Render only filters that constrain the API request."""
        filters = self.model_dump(exclude_none=True)
        if not filters.get("attributes"):
            filters.pop("attributes", None)
        if not filters.get("in_stock_only"):
            filters.pop("in_stock_only", None)
        return filters


class SearchRequest(WireModel):
    query: str = Field(min_length=2, max_length=1_000)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    limit: int = Field(default=12, ge=1, le=50)
    authorized_limit: int | None = Field(default=None, ge=1, le=50)
    include_diagnostics: bool = True
    rerank: bool = True
    session_id: str | None = Field(default=None, max_length=200)

    @field_validator("query")
    @classmethod
    def _reject_blank_query(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(
                "query is only whitespace; fix: pass at least one "
                "non-whitespace character"
            )
        return value

    @model_validator(mode="after")
    def _bound_authorized_limit(self) -> SearchRequest:
        if self.authorized_limit is None:
            self.authorized_limit = self.limit
        elif self.authorized_limit > self.limit:
            raise ValueError(
                f"authorized_limit is {self.authorized_limit}, which exceeds "
                f"limit {self.limit}; fix: set authorized_limit to at most "
                f"{self.limit}, or raise limit"
            )
        return self


class RankSignal(WireModel):
    rank: int | None = None
    raw_score: float | None = None
    rrf_contribution: float | None = None


class ResultSignals(WireModel):
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


class SourceAttribution(WireModel):
    source_uri: str
    revision: str
    title: str
    quote: str


class ProductSummary(WireModel):
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


class RetrievalProfile(WireModel):
    fts_limit: int
    trigram_limit: int
    semantic_limit: int
    fused_limit: int
    result_limit: int
    authorized_limit: int | None = None
    rrf_k: int
    trigram_threshold: float
    weight_lexical: float
    weight_semantic: float
    weight_trigram: float
    ef_search: int
    iterative_scan: Literal["off", "strict_order", "relaxed_order"]
    max_scan_tuples: int
    scan_mem_multiplier: float


class RetrievalDiagnostics(WireModel):
    strategy: str
    embedding_model_id: str
    # `None` on a replayed run: the receipt records the embedding model id but
    # not the vector width. Tracks `service.models.RetrievalDiagnostics`.
    embedding_dimensions: int | None
    rerank_model_id: str | None
    rerank_status: Literal["applied", "disabled", "unavailable"]
    ranking_policy: list[str] = Field(default_factory=list)
    retrieval_profile: RetrievalProfile
    candidate_counts: dict[str, int]
    stage_timings_ms: dict[str, float]
    total_latency_ms: int
    warnings: list[str] = Field(default_factory=list)


class TermCoverage(WireModel):
    ordinal: int
    token: str
    token_kind: str
    lexeme: str | None = None
    ndoc: int = 0
    closest_lexeme: str | None = None
    closest_similarity: float | None = None
    verdict: Literal["matched", "recoverable", "unmatched_anchor", "ignored"]


class QueryCoverage(WireModel):
    confidence: Literal["grounded", "unanchored", "unavailable"]
    unmatched_terms: list[str] = Field(default_factory=list)
    terms: list[TermCoverage] = Field(default_factory=list)
    note: str = ""


class SearchResponse(WireModel):
    search_event_id: UUID
    query: str
    normalized_query: str
    applied_filters: dict[str, Any]
    results: list[ProductSummary]
    diagnostics: RetrievalDiagnostics | None = None
    coverage: QueryCoverage | None = None


class EvidenceRecord(WireModel):
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


class ProductEvidenceResponse(WireModel):
    product_id: int
    evidence: list[EvidenceRecord]


class SearchEventRecord(WireModel):
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


class SearchResultEventRecord(WireModel):
    product_id: int
    result_rank: int
    fts_rank: int | None = None
    trigram_rank: int | None = None
    semantic_rank: int | None = None
    fused_rank: int | None = None
    rerank_rank: int | None = None
    scores: dict[str, Any]
    provenance: dict[str, Any]


class RetrievalRunResponse(WireModel):
    run: SearchEventRecord
    candidates: list[SearchResultEventRecord]
