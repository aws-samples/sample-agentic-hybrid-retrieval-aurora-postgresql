"""Typed public contracts for search, catalog inspection, and agent tools."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


Domain = Literal[
    "consumer_electronics",
    "running_fitness",
    "home_office",
]
Availability = Literal["In Stock", "Low Stock", "Out of Stock"]


class SearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: Domain | None = None
    category: str | None = Field(default=None, min_length=1, max_length=120)
    subcategory: str | None = Field(default=None, min_length=1, max_length=160)
    brand: str | None = Field(default=None, min_length=1, max_length=120)
    availability: Availability | None = None
    max_price: float | None = Field(default=None, ge=0, le=1_000_000)
    min_price: float | None = Field(default=None, ge=0, le=1_000_000)
    min_rating: float | None = Field(default=None, ge=0, le=5)
    attributes: dict[str, str | int | float | bool | list[Any]] = Field(
        default_factory=dict
    )

    def as_sql_json(self) -> dict[str, Any]:
        filters = self.model_dump(exclude_none=True)
        if not filters.get("attributes"):
            filters.pop("attributes", None)
        return filters


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=1_000)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    limit: int = Field(default=12, ge=1, le=50)
    include_diagnostics: bool = True
    rerank: bool = True


class RankSignal(BaseModel):
    rank: int | None = None
    raw_score: float | None = None
    rrf_contribution: float | None = None


class ResultSignals(BaseModel):
    lexical: RankSignal
    trigram: RankSignal
    semantic: RankSignal
    rrf_score: float
    pre_rerank_rank: int
    rerank_score: float | None = None
    final_rank: int
    business_score: float
    score_semantics: str = (
        "Raw arm, reciprocal-rank fusion, reranker, and business scores use "
        "different scales and are not probabilities."
    )


class SourceAttribution(BaseModel):
    source_uri: str
    revision: str
    title: str
    quote: str


class ProductSummary(BaseModel):
    product_id: int
    sku: str
    title: str
    short_description: str
    domain: str
    category: str
    subcategory: str
    brand: str
    model: str
    price_usd: float
    list_price_usd: float
    rating: float
    review_count: int
    availability: str
    inventory_count: int
    attributes: dict[str, Any]
    tags: list[Any]
    image_url: str | None = None
    image_source: str | None = None
    signals: ResultSignals | None = None
    sources: list[SourceAttribution] = Field(default_factory=list)


class RetrievalDiagnostics(BaseModel):
    strategy: str
    embedding_model_id: str
    rerank_model_id: str | None
    rerank_status: Literal["applied", "disabled", "unavailable"]
    rrf_k: int
    arm_weights: dict[str, float]
    candidate_counts: dict[str, int]
    stage_timings_ms: dict[str, float]
    total_latency_ms: int


class SearchResponse(BaseModel):
    run_id: UUID
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
    review_id: int
    rating: int
    title: str | None = None
    body: str
    verified_purchase: bool
    helpful_votes: int
    review_date: str
    sentiment_score: float | None = None
    source_uri: str


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


class RetrievalRunRecord(BaseModel):
    run_id: UUID
    started_at: datetime
    completed_at: datetime | None = None
    query_text: str
    normalized_query: str
    filters: dict[str, Any]
    strategy: str
    embedding_model_id: str
    rerank_model_id: str | None = None
    rrf_k: int
    arm_weights: dict[str, float]
    candidate_counts: dict[str, int]
    stage_timings_ms: dict[str, float]
    total_latency_ms: int | None = None
    result_product_ids: list[int]
    diagnostics: dict[str, Any]


class RetrievalCandidateRecord(BaseModel):
    run_id: UUID
    product_id: int
    lexical_rank: int | None = None
    lexical_score: float | None = None
    lexical_contribution: float | None = None
    trigram_rank: int | None = None
    trigram_score: float | None = None
    trigram_contribution: float | None = None
    semantic_rank: int | None = None
    semantic_score: float | None = None
    semantic_contribution: float | None = None
    rrf_score: float
    pre_rerank_rank: int
    rerank_score: float | None = None
    final_rank: int | None = None
    business_score: float
    hard_filter_pass: bool


class RetrievalRunResponse(BaseModel):
    run: RetrievalRunRecord
    candidates: list[RetrievalCandidateRecord]


class AgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=4, max_length=2_000)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    result_limit: int = Field(default=6, ge=2, le=12)


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


class AgentCitation(BaseModel):
    number: int
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
