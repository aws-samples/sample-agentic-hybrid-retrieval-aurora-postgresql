import type {
  AgentCitation,
  AgentPlanStep,
  ProductSummary,
  SearchResponse,
  ToolTraceStep,
} from "../types";

type ReceiptItem = {
  label: string;
  value: string;
  detail: string;
};

function nonEmptyFilterCount(filters: object): number {
  return Object.values(filters).filter((value) => {
    if (value == null || value === false || value === "") return false;
    if (Array.isArray(value)) return value.length > 0;
    if (typeof value === "object") return Object.keys(value).length > 0;
    return true;
  }).length;
}

function topProduct(products: ProductSummary[]): ProductSummary | undefined {
  return products.find((product) => product.signals?.final_rank === 1)
    ?? products[0];
}

function armCounts(products: ProductSummary[]): string {
  const fts = products.filter((product) => product.signals?.fts.rank != null).length;
  const trigram = products.filter(
    (product) => product.signals?.trigram.rank != null,
  ).length;
  const semantic = products.filter(
    (product) => product.signals?.semantic.rank != null,
  ).length;
  return `FTS ${fts} / TRGM ${trigram} / HNSW ${semantic}`;
}

function ReceiptBand({
  items,
  path = "Filters → candidates → fusion → rerank → evidence → latency",
}: {
  items: ReceiptItem[];
  path?: string;
}) {
  return (
    <section className="retrieval-receipt" aria-label="End-to-end retrieval receipt">
      <header>
        <strong>Retrieval receipt</strong>
        <span>{path}</span>
      </header>
      <dl>
        {items.map((item) => (
          <div key={item.label}>
            <dt>{item.label}</dt>
            <dd>{item.value}</dd>
            <small>{item.detail}</small>
          </div>
        ))}
      </dl>
    </section>
  );
}

export function SearchRetrievalReceipt({
  response,
  plainLanguage = false,
}: {
  response: SearchResponse;
  plainLanguage?: boolean;
}) {
  const diagnostics = response.diagnostics;
  if (!diagnostics) return null;
  const winner = topProduct(response.results);
  const signals = winner?.signals;
  const filters = nonEmptyFilterCount(response.applied_filters);
  const counts = diagnostics.candidate_counts;
  const candidates = plainLanguage
    ? `Exact terms ${counts.fts_in_pool ?? 0} / Close spelling ${counts.trigram_in_pool ?? 0} / Meaning ${counts.semantic_in_pool ?? 0}`
    : `FTS ${counts.fts_in_pool ?? 0} / TRGM ${counts.trigram_in_pool ?? 0} / HNSW ${counts.semantic_in_pool ?? 0}`;

  return (
    <ReceiptBand
      path={
        plainLanguage
          ? "Filters → candidates → combined order → final order → evidence → latency"
          : undefined
      }
      items={[
        {
          label: "Filters",
          value: String(filters),
          detail: filters ? "eligibility gates applied" : "no catalog gates",
        },
        {
          label: "Candidates",
          value: candidates,
          detail: plainLanguage
            ? `${counts.fused_pool ?? 0} candidates combined`
            : `${counts.fused_pool ?? 0} in fused pool`,
        },
        {
          label: plainLanguage ? "Before reranking" : "Fusion",
          value: signals ? `#${signals.pre_rerank_rank}` : "-",
          detail: winner
            ? `${winner.model} before rerank`
            : "no ranked candidate",
        },
        {
          label: plainLanguage ? "Final order" : "Rerank",
          value: signals ? `#${signals.final_rank}` : "-",
          detail: plainLanguage && diagnostics.rerank_status === "applied"
            ? "model reranking applied"
            : diagnostics.rerank_status,
        },
        {
          label: "Evidence IDs",
          value: "Not requested",
          detail: "search receipt only",
        },
        {
          label: "Latency",
          value: `${diagnostics.total_latency_ms} ms`,
          detail: "end to end",
        },
      ]}
    />
  );
}

export function AgentRetrievalReceipt({
  citations,
  executionPath,
  plan,
  products,
  trace,
}: {
  citations: AgentCitation[];
  executionPath: "focused_follow_up" | "full_retrieval";
  plan: AgentPlanStep[];
  products: ProductSummary[];
  trace: ToolTraceStep[];
}) {
  const winner = topProduct(products);
  const signals = winner?.signals;
  const filterCount = plan.reduce(
    (count, step) => count + nonEmptyFilterCount(step.filters),
    0,
  );
  const evidenceIds = Array.from(
    new Set(citations.map((citation) => citation.evidence_id)),
  );
  const latency = trace.reduce(
    (total, step) => total + (step.latency_ms ?? 0),
    0,
  );

  return (
    <ReceiptBand
      items={[
        {
          label: "Filters",
          value: plan.length ? String(filterCount) : "Inherited",
          detail: plan.length
            ? `${plan.length} focused search${plan.length === 1 ? "" : "es"}`
            : "authorized prior shortlist",
        },
        {
          label: "Candidates",
          value: armCounts(products),
          detail: `${products.length} authorized product${products.length === 1 ? "" : "s"}`,
        },
        {
          label: "Fusion",
          value: signals ? `#${signals.pre_rerank_rank}` : "-",
          detail: executionPath === "focused_follow_up"
            ? "replayed prior receipt"
            : "current retrieval",
        },
        {
          label: "Rerank",
          value: signals ? `#${signals.final_rank}` : "-",
          detail: signals?.rerank_rank ? `rerank #${signals.rerank_rank}` : "not repeated",
        },
        {
          label: "Evidence IDs",
          value: String(evidenceIds.length),
          detail: evidenceIds.length
            ? evidenceIds.slice(0, 3).map((id) => `#${id}`).join(", ")
            : "none authorized",
        },
        {
          label: "Latency",
          value: `${Math.round(latency)} ms`,
          detail: `${trace.length} tool receipt${trace.length === 1 ? "" : "s"}`,
        },
      ]}
    />
  );
}
