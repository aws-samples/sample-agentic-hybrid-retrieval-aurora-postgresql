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
  rating: number | null;
  title: string | null;
  body: string;
  verified_purchase: boolean;
  helpful_votes: number;
  review_date: string | null;
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

/**
 * One verbatim customer-review excerpt with the product it reviews. The quote
 * is the review body's opening sentence, byte-for-byte; `source_uri` addresses
 * the evidence row it came from.
 */
export interface ReviewHighlight {
  review_id: number;
  product_id: number;
  product_title: string;
  brand: string;
  rating: number;
  quote: string;
  verified_purchase: boolean;
  review_date: string | null;
  source_uri: string;
}

export interface CatalogPage {
  total: number;
  offset: number;
  limit: number;
  products: ProductSummary[];
  facets: Record<string, Array<{ value: string; count: number }>>;
}

export interface CatalogSuggestion {
  kind: "product" | "brand" | "category";
  label: string;
  query: string;
  product_id: number | null;
  domain: Domain | null;
  brand: string | null;
  category_key: string | null;
  category_path: string | null;
}

export interface CatalogSuggestionsResponse {
  query: string;
  suggestions: CatalogSuggestion[];
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

/**
 * One parsed request token and what the catalog holds for it.
 *
 * `verdict` separates a misspelling from an absence. Both match zero documents,
 * so the distinction is whether anything close exists: `hedfones` is
 * recoverable by the close-spelling arm, `A2342` is recoverable by nothing.
 */
export interface TermCoverage {
  ordinal: number;
  token: string;
  token_kind: string;
  lexeme: string | null;
  ndoc: number;
  closest_lexeme: string | null;
  closest_similarity: number | null;
  verdict: "matched" | "recoverable" | "unmatched_anchor" | "ignored";
}

/**
 * Whether the request named anything the catalog does not carry.
 *
 * `unanchored` never means the results are wrong or absent; they are the same
 * rows in the same measured order. It means they answer a narrower question
 * than the shopper asked, so a surface must say so rather than present them as
 * a match. `unavailable` is a database without the coverage function or its
 * vocabulary, and must read exactly as it did before coverage existed.
 */
export interface QueryCoverage {
  confidence: "grounded" | "unanchored" | "unavailable";
  unmatched_terms: string[];
  terms: TermCoverage[];
  note: string;
}

export interface SearchResponse {
  search_event_id: string;
  query: string;
  normalized_query: string;
  applied_filters: Record<string, unknown>;
  results: ProductSummary[];
  diagnostics: RetrievalDiagnostics | null;
  coverage?: QueryCoverage | null;
}

/**
 * One row of `mosaic.search_event`, as `/api/retrieval/events/{id}` replays it.
 *
 * The Playground's "View retrieval event" disclosure reads this rather than the
 * in-memory response, which is the point: the receipt comes back out of Postgres,
 * so a participant can see that what the surface showed was persisted.
 */
export interface SearchEventRecord {
  search_event_id: string;
  occurred_at: string;
  session_id: string | null;
  query_text: string;
  normalized_query: string | null;
  filters: Record<string, unknown>;
  retrieval_profile: Record<string, unknown>;
  source_revision: string | null;
  embedding_model_id: string | null;
  rerank_model_id: string | null;
  retrieval_strategy: string | null;
  database_version: string | null;
  vector_extension_version: string | null;
  aurora_instance_class: string | null;
  hnsw_settings: Record<string, unknown>;
  candidate_counts: Record<string, number>;
  total_latency_ms: number | null;
  diagnostics: Record<string, unknown>;
}

/** One row of `mosaic.search_result_event`. Arm ranks as the database wrote them. */
export interface SearchResultEventRecord {
  product_id: number;
  result_rank: number;
  fts_rank: number | null;
  trigram_rank: number | null;
  semantic_rank: number | null;
  fused_rank: number | null;
  rerank_rank: number | null;
  scores: Record<string, unknown>;
  provenance: Record<string, unknown>;
}

export interface RetrievalRunResponse {
  run: SearchEventRecord;
  candidates: SearchResultEventRecord[];
}

/** `EXPLAIN (ANALYZE, FORMAT JSON)` over the run's own SQL path. */
export interface RetrievalPlanResponse {
  search_event_id: string;
  plan: Array<Record<string, unknown>>;
}

/** One source-addressable evidence record, as `/api/evidence/{id}` serves it. */
export interface EvidenceRecord {
  evidence_id: number;
  product_id: number;
  evidence_type: string;
  source_name: string;
  source_uri: string;
  revision: string;
  title: string;
  text: string;
  rating: number | null;
  is_verified: boolean;
  metadata: Record<string, unknown>;
}

/** One entry of `/api/tools`: the contract a tool call is audited against. */
export interface ToolContract {
  name: string;
  capability: string;
  tool_version: string;
  description: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  read_only: boolean;
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
  previous_agent_run_id: string;
  previous_question: string;
  recommendations: Array<{
    product_id: number;
    title: string;
    model: string;
  }>;
}

export interface AgentPlanStep {
  query: string;
  filters: SearchFilters;
  purpose: string;
}

export interface ToolTraceStep {
  sequence: number;
  tool: string;
  detail: string;
  retrieval_run_id: string | null;
  result_count: number | null;
  arguments: Record<string, unknown>;
  outcome: "success" | "error";
  origin?: "model" | "controller_fallback";
  latency_ms: number | null;
}

export interface AgentResponse {
  agent_run_id: string;
  question: string;
  answer: string;
  plan: AgentPlanStep[];
  recommendations: ProductSummary[];
  citations: AgentCitation[];
  trace: ToolTraceStep[];
}

/**
 * Retrieval that has already run, delivered mid-stream.
 *
 * No answer and no citations: those only exist once the grounded synthesis tool
 * writes the answer of record, which is the last thing a run does.
 */
export interface AgentPartial {
  plan: AgentPlanStep[];
  candidates: ProductSummary[];
  trace: ToolTraceStep[];
}

export interface CatalogSummary {
  total: {
    products: number;
    brands: number;
    subcategories: number;
    embedded_products: number;
    reviews: number;
    reviewed_products: number;
    average_rating: number | null;
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

/**
 * The scale envelope, extrapolated from the measured 500K baseline.
 *
 * `assumptions` carries the provenance of that baseline rather than a set of
 * hand-chosen numbers: it names the measured artifact, when it was captured, and the
 * growth rules applied on top. `baseline_index_gb` is gone because index size is no
 * longer a fitted parameter — it is `bytes_per_vector` times the vector count.
 */
export interface BenchmarkProjection {
  warning: string;
  assumptions: {
    measured_source: string;
    measured_captured_at: string;
    measured_source_revision: string | null;
    measured_instance_class: string | null;
    baseline_latency_p95_ms: number;
    baseline_recall: number;
    bytes_per_vector: number;
    dimensions: number;
    m: number;
    ef_construction: number;
    ef_search: number;
    index_size_growth: string;
    latency_growth: string;
    recall_decay: string;
    output: string;
  };
  rows: Array<{
    scale: number;
    projection_kind: string;
    p95_latency_ms: number;
    recall_at_10: number;
    index_size_gb: number;
    dimensions: number;
    m: number;
    ef_search: number;
  }>;
}

export interface ReadinessResponse {
  status: "ready" | "blocked";
  database_ready: boolean;
  model_space_ready: boolean;
  database: {
    database_name: string;
    server_version: string;
    schema_ready: boolean;
    vector_version: string | null;
    product_count: number;
    embedded_product_count: number;
    embedding_dimensions: number | null;
    embedding_model_ids: string[] | null;
    premium_product_count: number;
    evidence_product_count: number;
    missing_retrieval_indexes: string[] | null;
    missing_retrieval_functions: string[] | null;
  };
  configured_models: {
    embedding: string;
    rerank: string;
    agent: string;
    synthesis: string;
  };
  bedrock_credentials: {
    ready: boolean;
    [key: string]: unknown;
  };
}

/**
 * Live HNSW index anatomy, read from the cluster on request.
 *
 * `overhead_factor` is the measured index cost against the raw fp32 payload: 8,189
 * bytes stored per 4,096-byte vector, exactly 2.0x. There is deliberately no
 * distinct-vector count here — deduplicating 500,000 `vector(1024)` values sorts
 * roughly 2 GB and terminated the Aurora backend when tried.
 */
export interface HnswSubstrate {
  index: {
    name: string;
    definition: string;
    size_bytes: number;
    bytes_per_vector: number;
    fp32_payload_bytes: number;
    overhead_factor: number | null;
  };
  storage: HnswStorage;
  corpus: {
    vector_count: number;
    anchor_count: number;
    dimensions: number | null;
  };
  aurora: {
    database_instance_id: string;
    database_version: string;
    vector_extension_version: string | null;
    instance_class: string | null;
  };
  settings: Record<string, string>;
}

export interface HnswStorage {
  heap_bytes: number;
  toast_bytes: number;
  hnsw_bytes: number;
  other_indexes_bytes: number;
  total_bytes: number;
}

/** One measured operating point on the recall/latency curve. */
export interface HnswEfPoint {
  ef_search: number;
  server_ms: number;
  shared_hit_blocks: number;
  recall_at_k: number;
  estimated_total_cost: number;
}

export interface HnswFilterMode {
  iterative_scan: "off" | "strict_order" | "relaxed_order";
  scan_mem_multiplier: number;
  scan_mem_mb: number;
  rows_returned: number;
  min_rows_returned: number;
  recall_at_k: number;
  server_ms: number;
  shared_hit_blocks: number;
  node: string;
}

export interface HnswFilterLevel {
  preset: string;
  label: string;
  character: string;
  predicate_sql: string;
  matching_rows: number;
  selectivity: number;
  exact_rows_found: number;
  modes: HnswFilterMode[];
}

/**
 * The measured benchmark artifact the instrument replays.
 *
 * Rendered under a MEASURED label, so the endpoint refuses to serve any payload whose
 * `kind` is not `measured`.
 */
/**
 * Whether the committed HNSW artifact describes the cluster this page is
 * connected to, mirrors `service.hnsw._measured_attribution`.
 *
 * The gate is two facts: the artifact was measured from a clean worktree, and
 * against the same dataset manifest the running service reports. Revision
 * equality is deliberately absent for the same reason it is absent from the
 * scorecard -- the artifact is always committed one revision after the run that
 * produced it -- so both revisions are carried for display, not as the gate.
 * When `attributed` is false the badge must read MEASURED ELSEWHERE.
 */
export interface HnswAttribution {
  measured_source_revision: string | null;
  measured_source_worktree_dirty: boolean | null;
  measured_dataset_manifest_sha256: string | null;
  current_source_revision: string;
  current_source_worktree_dirty: boolean;
  current_dataset_manifest_sha256: string;
  attributed: boolean;
  attribution_note: string;
}

export interface HnswMeasured {
  kind: "measured";
  captured_at: string;
  attribution: HnswAttribution;
  provenance: {
    source_revision?: string;
    dataset_manifest_sha256?: string;
    database_instance_id?: string;
    instance_class?: string;
    query_sample_sha256?: string;
    queries?: number;
    k?: number;
    work_mem_mb?: number;
    [key: string]: unknown;
  };
  index: {
    name: string;
    definition: string;
    size_bytes: number;
    bytes_per_vector: number;
    fp32_payload_bytes: number;
    overhead_factor: number | null;
    vector_count: number;
    dimensions: number;
    m: number;
    ef_construction: number;
  };
  exact_baseline: {
    p50_ms: number;
    p95_ms: number;
    mean_ms: number;
    server_ms: number;
    shared_hit_blocks: number;
    node: string;
    method: string;
  };
  missing_predicate: {
    node: string;
    server_ms: number;
    shared_hit_blocks: number;
    index_name: string | null;
    compared_at_ef_search: number | null;
    slowdown_factor: number | null;
  };
  ef_sweep: HnswEfPoint[];
  filter_matrix: HnswFilterLevel[];
  /**
   * Withheld by the server when the halfvec or binary index does not exist on
   * the connected cluster. Nothing in the bootstrap builds them, so on a fresh
   * cluster `representations_unavailable_reason` is present instead.
   */
  representations?: HnswRepresentations;
  representations_unavailable_reason?: string;
  local_nvme?: HnswLocalNvme;
}

/** One index representation of the same vectors, and what it cost. */
export interface HnswRepresentationRow {
  representation: string;
  overfetch: number | null;
  index_size_bytes: number;
  bytes_per_vector: number;
  recall_at_k: number;
  server_ms: number;
  shared_hit_blocks: number;
  build_seconds: number | null;
}

export interface HnswRepresentations {
  ef_search: number;
  k: number;
  anchors: number;
  payload_bytes: { fp32: number; halfvec: number; binary: number };
  note: string;
  rows: HnswRepresentationRow[];
  quantization_distribution: {
    why_binary_underperforms_here: string;
    fraction_components_positive: number;
    components_within_10pct_of_zero: number;
    dimensions_over_80pct_one_sided: number;
    dimensions_total: number;
    hamming_band: [number, number];
    top50_hamming_cosine_overlap: number;
  };
  blog_operating_point: {
    correction: string;
    reference: string;
    /** Optional so an artifact written before the post published still parses. */
    reference_source?: string;
    reference_url?: string;
    anchors: number;
    k: number;
    rows: Array<{
      config: string;
      recall_at_k: number;
      server_ms: number;
      shared_hit_blocks: number;
    }>;
    tradeoff: string;
  };
  native_binary_comparison: {
    question: string;
    answer: string;
    evidence: string[];
    conclusion: string;
  };
}

/**
 * The controlled scale A/B, kept structurally separate from the workshop baseline.
 *
 * This is a different claim class from everything else on the page: a purpose-built cluster
 * pair with a non-default shared_buffers and Aurora I/O-Optimized enabled. The badge says so
 * because AWS documents I/O-Optimized as required for the tiered-cache behaviour, which
 * makes it a condition of the result rather than a footnote to it.
 */
export interface HnswLocalNvme {
  claim_class: string;
  region: string;
  control_cluster: string;
  test_cluster: string;
  headline: string;
  controls: string[];
  boundary: string;
  crossover_wording: string;
  crossover_products: number;
  shared_buffers_bytes: number;
  working_set_bytes: number;
  oversubscription: number;
  instrumentation_limit: string;
  warm: { r8g_p50_ms: number; r8gd_p50_ms: number; read_blocks: number };
  storage_configuration: {
    finding: string;
    aurora_standard: { r8g_p50_ms: number[]; r8gd_p50_ms: number[]; mean_improvement: number };
    aurora_io_optimized: {
      r8g_p50_ms: number[];
      r8gd_p50_ms_steady: number[];
      r8gd_first_pass_ms: number;
      r8g_io_read_ms: number[];
      r8gd_io_read_ms_steady: number[];
      read_blocks_r8g: number[];
      read_blocks_r8gd: number[];
      p50_speedup: number;
      io_reduction: number;
    };
  };
  index_build: { verdict: string; r8g_seconds: number[]; r8gd_seconds: number[] };
}

export interface HnswProduct {
  product_id: number;
  title: string;
  brand_name: string;
  domain: Domain;
  category_key: string;
  catalog_asset_key: string | null;
  media_tier: string | null;
}

export interface HnswNeighbor extends HnswProduct {
  neighbor_rank: number;
  cosine_distance: number;
}

/** The distance span the true neighbours occupy, excluding the anchor itself. */
export interface HnswBand {
  nearest: number;
  kth: number;
  width: number;
}

export interface HnswNeighborhood {
  anchor: HnswProduct;
  preset: string;
  k: number;
  neighbors: HnswNeighbor[];
  band: HnswBand | null;
}

/**
 * What a probe request may carry.
 *
 * The tuning values are optional because the endpoint resolves them from
 * `db/config/retrieval.yaml`. Supplying them is for deliberately reproducing a
 * non-default operating point, not for restating the served one.
 */
export interface HnswProbeInput {
  anchor_product_id: number;
  ef_search?: number;
  iterative_scan?: "off" | "strict_order" | "relaxed_order";
  scan_mem_multiplier?: number;
  max_scan_tuples?: number;
  filter_preset?: string;
  k?: number;
}

/** What a probe response reports back, with every value resolved. */
export interface HnswProbeSettings {
  ef_search: number;
  iterative_scan: "off" | "strict_order" | "relaxed_order";
  scan_mem_multiplier: number;
  max_scan_tuples: number;
  k: number;
}

/** What one real query did, as reported by the server that ran it. */
export interface HnswProbe {
  anchor: HnswProduct;
  preset: string;
  settings: HnswProbeSettings;
  sql: string;
  rows_returned: number;
  exact_rows_available: number;
  recall_at_k: number;
  missed: number[];
  unexpected: number[];
  plan: {
    /**
     * Which of the probe's two executions the timing below came from. The rows
     * and recall come from the first; `server_ms` and the buffer counts come
     * from the EXPLAIN (ANALYZE) run that followed it, against a warm cache.
     */
    execution: string;
    node: string;
    index_name: string | null;
    server_ms: number;
    shared_hit_blocks: number;
    shared_read_blocks: number;
    estimated_total_cost: number;
    estimated_rows: number;
  };
  products: Array<HnswProduct & { cosine_distance: number }>;
}

/**
 * Whether the Retrieval Scorecard's population metrics describe the system
 * currently running, mirrors `service.models.ScorecardProvenance`.
 *
 * `attributed` is the one field the Playground must branch on for section A.
 * A strict `source_revision` equality can never hold here -- the artifact is
 * always committed one revision after it was measured -- so the real gate is
 * a hash over the retrieval-defining files (`service.retrieval_fingerprint`),
 * plus `source_worktree_dirty` being `false` at measurement time, plus the
 * pinned models and query-set hashes still matching what is running.
 * `source_revision` and the current server's own worktree cleanliness are
 * carried for display and audit but do not gate `attributed`. When
 * `attributed` is false, `attribution_note` starts with the exact string
 * "Metrics pending evaluation for this retrieval revision".
 */
export interface ScorecardProvenance {
  measured_at: string;
  query_set: string;
  query_set_sha256: string;
  scored_query_set_sha256: string;
  ranked_result_sha256: string;
  dataset_manifest_sha256: string;
  models: Record<string, string>;
  aurora_configuration: Record<string, unknown>;
  hnsw_settings: Record<string, unknown>;
  retrieval_profile: Record<string, unknown>;
  database_instance_id: string;
  strategy: string;
  source_revision: string | null;
  source_worktree_dirty: boolean | null;
  current_source_revision: string | null;
  current_source_worktree_dirty: boolean;
  attributed: boolean;
  attribution_note: string;
}

/** Section A: population IR metrics over the scored search population. */
export interface ScorecardRetrievalQuality {
  sample_size: number;
  canonical_query_count: number;
  sample_description: string;
  recall_at_10: number;
  mrr: number;
  ndcg_at_10: number;
  metric_explanations: Record<string, string>;
  excluded_agent_contract_query_ids: string[];
  /**
   * Each row always carries `query_id`, `recall@10`, `reciprocal_rank`, and
   * `ndcg@10`. `query_text` and `concept_label` are present only once the
   * artifact was measured after labels were added -- absent on the artifact
   * committed today, so callers must degrade to `query_id` alone.
   */
  per_query_metrics: Array<Record<string, unknown>>;
}

/**
 * `query_text` and `concept_label` are only present once the canonical
 * scorecard was measured after labels were added to
 * `scripts/score_evals.py`; the artifact committed today carries neither, so
 * both are optional and the UI must degrade to `query_id` alone.
 */
export interface ScorecardGoldenAnchor {
  query_id: string;
  product_id: number;
  type: "top_rank" | "present_top_k";
  k?: number | null;
  query_text?: string | null;
  concept_label?: string | null;
}

/**
 * Section B: compact PASS/total over golden regression anchors.
 *
 * `passed` can only ever equal the number of checks the artifact recorded,
 * because the harness raises on the first failing check and never writes a
 * failing entry. `verified_for_running_revision` is therefore what carries
 * whether that N/N still describes the running code -- without it the section
 * presents a historical result as present-tense verification.
 */
export interface ScorecardRegressionAnchors {
  passed: number;
  total: number;
  anchors: ScorecardGoldenAnchor[];
  verified_for_running_revision: boolean;
}

/**
 * Section C: hard eligibility/filter contracts. Not a relevance judgment.
 *
 * `held` is `null` -- unknown -- when the measurement no longer describes the
 * running revision. It is never an unconditional `true`.
 */
export interface ScorecardEligibilityContracts {
  fixture_count: number;
  held: boolean | null;
  description: string;
  fixture_query_ids: string[];
}

export interface ScorecardAgentContractGuarantee {
  key:
    | "retrieval_scope"
    | "compare_boundary"
    | "evidence_authorization"
    | "citation_resolution"
    | "tool_contract";
  label: string;
  description: string;
  assertion_names: string[];
  falsifiers: string[];
  fixture_count: number | null;
}

/** Section D: deterministic agent and evidence contracts. */
export interface ScorecardAgentContracts {
  guarantees: ScorecardAgentContractGuarantee[];
}

/**
 * One retrieval-stage arm in Lab 2's ablation (section E).
 *
 * `ndcg_at_10_min`/`_max`/`_stdev` are the per-query spread across the same
 * 20 scored queries `recall_at_10`/`mrr`/`ndcg_at_10` are averaged over --
 * every mean here travels with the spread that qualifies it. See
 * `ScorecardStageAblation.spread_note`.
 */
export interface ScorecardStageArm {
  key: "semantic_only" | "rrf_fused_no_rerank" | "rrf_fused_reranked";
  label: string;
  description: string;
  recall_at_10: number;
  mrr: number;
  ndcg_at_10: number;
  ndcg_at_10_min: number;
  ndcg_at_10_max: number;
  ndcg_at_10_stdev: number;
  ndcg_at_10_query_wins: number;
}

/**
 * The ceiling reranking could ever reach: share of judged-relevant products
 * present anywhere in the fused candidate pool before reranking. Reranking
 * only ever reorders that pool -- it never adds a candidate.
 */
export interface ScorecardCandidateRecallCeiling {
  pool_recall_ceiling: number;
  judged_relevant_never_fetched: number;
  description: string;
}

/** One scored query's nDCG@10 under every arm, keyed by `ScorecardStageArm.key`. */
export interface ScorecardStageAblationQuery {
  query_id: string;
  query_text: string;
  ndcg_at_10: Record<string, number>;
  pool_recall: number;
  relevant_count: number;
  found_in_pool: number;
  missed_product_ids: number[];
}

/**
 * Section E: what each retrieval stage contributes, measured rather than
 * asserted. A separate artifact and a separate attribution gate from section
 * A -- `attributed` here can be false while section A's is true, or the
 * reverse, because each is judged against its own committed measurement.
 */
export interface ScorecardStageAblation {
  attributed: boolean;
  attribution_note: string;
  measured_at: string;
  spread_note: string;
  scored_query_count: number;
  arms: ScorecardStageArm[];
  candidate_recall_ceiling: ScorecardCandidateRecallCeiling;
  per_query: ScorecardStageAblationQuery[];
}

/** The Prove step. Five sections, never conflated -- see each interface above. */
export interface RetrievalScorecardResponse {
  provenance: ScorecardProvenance;
  retrieval_quality: ScorecardRetrievalQuality;
  regression_anchors: ScorecardRegressionAnchors;
  eligibility_contracts: ScorecardEligibilityContracts;
  agent_contracts: ScorecardAgentContracts;
  stage_ablation: ScorecardStageAblation;
}
