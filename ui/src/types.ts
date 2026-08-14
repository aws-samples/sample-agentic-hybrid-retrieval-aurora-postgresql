export type Domain =
  | "consumer_electronics"
  | "running_fitness"
  | "home_office";

/** Mirrors mosaic.availability_status. Display labels live in formatAvailability. */
export type Availability =
  | "in_stock"
  | "low_stock"
  | "out_of_stock"
  | "preorder"
  | "discontinued";

/**
 * Mirrors the service's SearchFilters, which is what
 * `mosaic_search.matches_filters` accepts.
 *
 * Prices are integer cents. A float dollar amount loses precision the moment it
 * round-trips through JSON, so money crosses this boundary as a count of cents
 * and is formatted only for display.
 */
export interface SearchFilters {
  domain?: Domain;
  category_key?: string;
  brand?: string;
  brands?: string[];
  availability?: Availability;
  in_stock_only?: boolean;
  min_price_cents?: number;
  max_price_cents?: number;
  min_rating?: number;
  attributes?: Record<string, unknown>;
  include_refurbished?: boolean;
  include_sponsored?: boolean;
}

export interface RankSignal {
  rank: number | null;
  raw_score: number | null;
  rrf_contribution: number | null;
}

export interface ResultSignals {
  fts: RankSignal;
  trigram: RankSignal;
  semantic: RankSignal;
  rrf_score: number;
  pre_rerank_rank: number;
  pre_rerank_score: number;
  rerank_score: number | null;
  rerank_rank?: number | null;
  exact_sku_match?: boolean;
  final_rank: number;
  score_semantics: string;
}

export interface SourceAttribution {
  source_uri: string;
  revision: string;
  title: string;
  quote: string;
}

export interface ProductSummary {
  product_id: number;
  sku: string;
  title: string;
  short_description: string;
  domain: Domain;
  category_key: string;
  category_path: string;
  brand: string;
  model: string;
  price_cents: number;
  list_price_cents: number;
  currency: string;
  rating: number | null;
  review_count: number;
  availability: Availability;
  inventory_count: number;
  attributes: Record<string, unknown>;
  tags: unknown[];
  catalog_asset_key: string | null;
  canonical_group_id: string | null;
  media_tier: string | null;
  is_flagship: boolean;
  is_retrieval_anchor: boolean;
  image_url: string | null;
  image_source: string | null;
  signals: ResultSignals | null;
  sources: SourceAttribution[];
}

export interface ProductMedia {
  role: string;
  sort_order: number;
  image_url: string;
  image_source: string;
  image_key: string | null;
  alt_text: string;
}

export interface ProductReview {
  review_id: number;
  rating: number;
  title: string | null;
  body: string;
  verified_purchase: boolean;
  helpful_votes: number;
  review_date: string;
  sentiment_score: number | null;
  source_uri: string;
  source_name: string;
}

export interface ProductDetail extends ProductSummary {
  long_description: string;
  canonical_group_id: string;
  source_system: string;
  updated_at: string;
  media: ProductMedia[];
  reviews: ProductReview[];
}

export interface CatalogPage {
  total: number;
  offset: number;
  limit: number;
  products: ProductSummary[];
  facets: Record<string, Array<{ value: string; count: number }>>;
}

export interface RetrievalDiagnostics {
  strategy: string;
  embedding_model_id: string;
  embedding_dimensions: number;
  rerank_model_id: string | null;
  rerank_status: "applied" | "disabled" | "unavailable";
  ranking_policy?: string[];
  retrieval_profile: {
    rrf_k: number;
    fts_limit: number;
    trigram_limit: number;
    semantic_limit: number;
    fused_limit: number;
    result_limit: number;
    trigram_threshold: number;
    ef_search: number;
    iterative_scan: "off" | "strict_order" | "relaxed_order";
    max_scan_tuples: number;
    scan_mem_multiplier: number;
    weight_lexical: number;
    weight_semantic: number;
    weight_trigram: number;
  };
  candidate_counts: Record<string, number>;
  stage_timings_ms: Record<string, number>;
  total_latency_ms: number;
}

export interface SearchResponse {
  search_event_id: string;
  query: string;
  normalized_query: string;
  applied_filters: Record<string, unknown>;
  results: ProductSummary[];
  diagnostics: RetrievalDiagnostics | null;
}

export interface AgentCitation {
  number: number;
  evidence_id: number;
  evidence_type: string;
  product_id: number;
  source_uri: string;
  revision: string;
  title: string;
  quote: string;
}

export interface AgentConversationContext {
  previous_question: string;
  recommendations: Array<{
    product_id: number;
    title: string;
    model: string;
  }>;
}

export interface AgentResponse {
  agent_run_id: string;
  question: string;
  answer: string;
  plan: Array<{
    query: string;
    filters: SearchFilters;
    purpose: string;
  }>;
  recommendations: ProductSummary[];
  citations: AgentCitation[];
  trace: Array<{
    sequence: number;
    tool: string;
    detail: string;
    retrieval_run_id: string | null;
    result_count: number | null;
    arguments: Record<string, unknown>;
    outcome: "success" | "error";
    latency_ms: number | null;
  }>;
}

export interface CatalogSummary {
  total: {
    products: number;
    brands: number;
    subcategories: number;
    embedded_products: number;
  };
  domains: Array<{
    domain: Domain;
    products: number;
    categories: number;
    subcategories: number;
    brands: number;
  }>;
}

export interface RetrievalExample {
  query_id: string;
  domain: Domain;
  query: string;
  expected_techniques: string[];
  variant: number;
}

export interface BenchmarkProjection {
  warning: string;
  assumptions: {
    baseline_latency_p95_ms: number;
    baseline_build_min: number;
    baseline_index_gb: number;
    baseline_recall: number;
    dimensions: number;
    m: number;
    ef_search: number;
  };
  rows: Array<{
    scale: number;
    projection_kind: string;
    p95_latency_ms: number;
    recall_at_10: number;
    build_time_min: number;
    index_size_gb: number;
    dimensions: number;
    m: number;
    ef_search: number;
  }>;
}
