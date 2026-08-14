"""Typed application contracts for Mosaic.

These models describe API and ingestion payloads. PostgreSQL remains the source of
truth for constraints and indexes; these classes keep service/tool contracts aligned.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ProductDomain(str, Enum):
    CONSUMER_ELECTRONICS = "consumer_electronics"
    RUNNING_FITNESS = "running_fitness"
    HOME_OFFICE = "home_office"


class Availability(str, Enum):
    IN_STOCK = "in_stock"
    LOW_STOCK = "low_stock"
    OUT_OF_STOCK = "out_of_stock"
    PREORDER = "preorder"
    DISCONTINUED = "discontinued"


class MediaTier(str, Enum):
    FLAGSHIP = "flagship"
    PREMIUM = "premium"
    FAMILY = "family"
    GENERIC = "generic"


class MediaRole(str, Enum):
    CATALOG = "catalog"
    DETAIL = "detail"
    ALTERNATE = "alternate"
    MATERIAL_CLOSEUP = "material_closeup"
    LIFESTYLE = "lifestyle"
    FAMILY_FALLBACK = "family_fallback"
    HERO = "hero"


class EvidenceType(str, Enum):
    PRODUCT_SPEC = "product_spec"
    CUSTOMER_REVIEW = "customer_review"
    VERIFIED_REVIEW = "verified_review"
    EXPERT_SUMMARY = "expert_summary"
    PRODUCT_QA = "product_qa"
    BUYING_GUIDE = "buying_guide"
    BENCHMARK = "benchmark"


class ProductIngest(BaseModel):
    product_id: int | None = None
    product_uid: UUID | None = None
    sku: str = Field(min_length=1, max_length=160)
    domain: ProductDomain
    category_key: str
    category_path: str
    brand_key: str
    brand_name: str
    canonical_group_id: str
    model_name: str
    title: str
    short_description: str
    long_description: str
    language: str = "en-US"
    attributes: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    challenge_cohorts: list[str] = Field(default_factory=list)
    launch_date: date | None = None
    source_system: str
    is_active: bool = True


class ProductOfferIngest(BaseModel):
    product_id: int
    price_cents: int = Field(ge=0)
    list_price_cents: int = Field(ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    availability: Availability
    inventory_count: int = Field(default=0, ge=0)
    seller_count: int = Field(default=1, ge=0)
    shipping_days: int | None = Field(default=None, ge=0)
    warranty_months: int | None = Field(default=None, ge=0)
    rating: float | None = Field(default=None, ge=0, le=5)
    review_count: int = Field(default=0, ge=0)
    return_rate: float | None = Field(default=None, ge=0, le=1)
    popularity_score: float = Field(default=0, ge=0, le=1)
    quality_score: float = Field(default=0, ge=0, le=1)
    freshness_score: float = Field(default=0, ge=0, le=1)
    metadata_completeness: float = Field(default=1, ge=0, le=1)
    is_refurbished: bool = False
    is_sponsored: bool = False
    offer_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("list_price_cents")
    @classmethod
    def list_price_not_negative(cls, value: int) -> int:
        return value


class BrandMarkZone(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(ge=0, le=1)
    height: float = Field(ge=0, le=1)
    surface: str


class MediaAsset(BaseModel):
    asset_key: str
    tier: MediaTier
    master_uri: str | None = None
    runtime_uri: str
    mime_type: str = "image/webp"
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    aspect_ratio: str
    sha256_hex: str | None = None
    is_bespoke: bool = False
    generation_metadata: dict[str, Any] = Field(default_factory=dict)


class ProductMediaAssignment(BaseModel):
    product_id: int
    asset_key: str
    role: MediaRole
    sort_order: int = Field(default=0, ge=0)
    crop_anchor_x: float = Field(default=0.5, ge=0, le=1)
    crop_anchor_y: float = Field(default=0.5, ge=0, le=1)
    mark_zone: BrandMarkZone | None = None
    alt_text: str | None = None


class MerchandisingAssignment(BaseModel):
    product_id: int
    media_tier: MediaTier
    merchandising_title: str | None = None
    shop_page: int | None = Field(default=None, ge=1)
    shop_position: int | None = Field(default=None, ge=1)
    is_flagship: bool = False
    is_retrieval_anchor: bool = False
    catalog_asset_key: str | None = None
    detail_asset_key: str | None = None
    live_demo_queries: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProductEvidenceIngest(BaseModel):
    evidence_uid: UUID | None = None
    product_id: int
    evidence_type: EvidenceType
    source_name: str
    source_reference: str | None = None
    evidence_title: str | None = None
    evidence_text: str
    source_date: date | None = None
    rating: float | None = Field(default=None, ge=0, le=5)
    is_verified: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    embedding_text: str


class SearchFilters(BaseModel):
    domain: ProductDomain | None = None
    category_key: str | None = None
    brand: str | None = None
    brands: list[str] = Field(default_factory=list)
    min_price_cents: int | None = Field(default=None, ge=0)
    max_price_cents: int | None = Field(default=None, ge=0)
    availability: Availability | None = None
    in_stock_only: bool = False
    min_rating: float | None = Field(default=None, ge=0, le=5)
    attributes: dict[str, Any] = Field(default_factory=dict)
    include_refurbished: bool = False
    include_sponsored: bool = False


class RetrievalProfile(BaseModel):
    fts_limit: int = Field(default=120, ge=1, le=1000)
    trigram_limit: int = Field(default=80, ge=1, le=1000)
    semantic_limit: int = Field(default=150, ge=1, le=1000)
    fused_limit: int = Field(default=50, ge=1, le=250)
    result_limit: int = Field(default=12, ge=1, le=100)
    rrf_k: int = Field(default=60, ge=1)
    ef_search: int = Field(default=100, ge=1, le=1000)
    iterative_scan: Literal["off", "strict_order", "relaxed_order"] = "relaxed_order"
    max_scan_tuples: int = Field(default=20000, ge=1)
    scan_mem_multiplier: float = Field(default=1, ge=1)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    query_embedding: list[float] | None = None
    filters: SearchFilters = Field(default_factory=SearchFilters)
    profile: RetrievalProfile = Field(default_factory=RetrievalProfile)
    session_id: str | None = None


class ChannelContribution(BaseModel):
    rank: int
    raw_score: float
    rrf_contribution: float


class SearchCandidate(BaseModel):
    product_id: int
    title: str
    brand_name: str
    category_path: str
    price_cents: int
    availability: Availability
    rating: float | None = None
    catalog_asset_key: str | None = None
    canonical_group_id: str
    fts_score: float | None = None
    trigram_score: float | None = None
    semantic_score: float | None = None
    rrf_score: float
    pre_rerank_score: float
    rerank_score: float | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class SearchDiagnostics(BaseModel):
    search_event_id: UUID | None = None
    candidate_counts: dict[str, int] = Field(default_factory=dict)
    latency_ms: dict[str, int] = Field(default_factory=dict)
    retrieval_profile: RetrievalProfile
    warnings: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    query: str
    normalized_query: str | None = None
    results: list[SearchCandidate]
    diagnostics: SearchDiagnostics


class CompareProductsRequest(BaseModel):
    product_ids: list[int] = Field(min_length=2, max_length=8)
    criteria: list[str] = Field(default_factory=list)


class EvidenceSearchRequest(BaseModel):
    product_id: int
    query: str
    query_embedding: list[float] | None = None
    evidence_types: list[EvidenceType] = Field(default_factory=list)
    top_k: int = Field(default=8, ge=1, le=20)


class AgentToolEvent(BaseModel):
    tool_event_id: UUID | None = None
    agent_turn_id: UUID
    search_event_id: UUID | None = None
    tool_name: str
    tool_version: str
    outcome: Literal["success", "denied", "error", "timeout"]
    input_payload: dict[str, Any]
    output_payload: dict[str, Any] | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    error_detail: str | None = None
    occurred_at: datetime | None = None
