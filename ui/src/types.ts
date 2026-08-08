export type Domain =
  | "consumer_electronics"
  | "running_fitness"
  | "home_office";

export type Availability = "In Stock" | "Low Stock" | "Out of Stock";

export interface SearchFilters {
  domain?: Domain;
  category?: string;
  subcategory?: string;
  brand?: string;
  availability?: Availability;
  min_price?: number;
  max_price?: number;
  min_rating?: number;
  attributes?: Record<string, unknown>;
}

export interface RankSignal {
  rank: number | null;
  raw_score: number | null;
  rrf_contribution: number | null;
}

export interface ResultSignals {
  lexical: RankSignal;
  trigram: RankSignal;
  semantic: RankSignal;
  rrf_score: number;
  pre_rerank_rank: number;
  rerank_score: number | null;
  final_rank: number;
  business_score: number;
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
  category: string;
  subcategory: string;
  brand: string;
  model: string;
  price_usd: number;
  list_price_usd: number;
  rating: number;
  review_count: number;
  availability: Availability;
  inventory_count: number;
  attributes: Record<string, unknown>;
  tags: unknown[];
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
  rerank_model_id: string | null;
  rerank_status: "applied" | "disabled" | "unavailable";
  rrf_k: number;
  arm_weights: Record<string, number>;
  candidate_counts: Record<string, number>;
  stage_timings_ms: Record<string, number>;
  total_latency_ms: number;
}

export interface SearchResponse {
  run_id: string;
  query: string;
  normalized_query: string;
  applied_filters: Record<string, unknown>;
  results: ProductSummary[];
  diagnostics: RetrievalDiagnostics | null;
}

export interface AgentCitation {
  number: number;
  product_id: number;
  source_uri: string;
  revision: string;
  title: string;
  quote: string;
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
