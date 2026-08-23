import {
  FINAL_LABEL,
  FUSED_LABEL,
  armLanguage,
  armPoolKey,
} from "../retrievalLanguage";
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

/**
 * Per-arm candidate counts, written so they cannot be read as ranks.
 *
 * This band used to print `FTS 4 / TRGM 2 / HNSW 6` under the word "Candidates".
 * Every other number in the receipt is a `#position`, and every per-arm number on
 * a product card is a rank, so four readers in a row took `TRGM 2` for "second in
 * the trigram arm". They are counts of a set, so they are printed as `2 of 12`
 * with the denominator that makes them counts, and the label says so.
 */
function armCountItems(
  counted: (key: string) => number,
  total: number,
): string {
  return armLanguage
    .map((arm) => `${arm.label} ${counted(armPoolKey[arm.key])} of ${total}`)
    .join(" · ");
}

function ReceiptBand({
  items,
  path,
}: {
  items: ReceiptItem[];
  path: string;
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

/**
 * The receipt, in the one vocabulary.
 *
 * This took a `plainLanguage` boolean and printed "Filters / Fusion / Rerank /
 * Latency" without it. Shop passed it and the Playground did not, so the Playground
 * showed "Fusion #1" directly under a matrix column headed "Before reranking" for
 * the same number. There is one set of words; the mechanism that produced each is
 * named in the Playground's bridge and matrix headers, where it has room.
 */
export function SearchRetrievalReceipt({
  response,
}: {
  response: SearchResponse;
}) {
  const diagnostics = response.diagnostics;
  if (!diagnostics) return null;
  const winner = topProduct(response.results);
  const signals = winner?.signals;
  const filters = nonEmptyFilterCount(response.applied_filters);
  const counts = diagnostics.candidate_counts;
  const pool = counts.fused_pool ?? 0;

  return (
    <ReceiptBand
      path="Eligibility → candidates → combined order → final order → evidence → time"
      items={[
        {
          label: "Eligibility",
          // "0" reads as a measurement that failed. It is an absence.
          value: filters ? String(filters) : "None",
          detail: filters ? "gates applied to every arm" : "no catalog gates",
        },
        {
          // A count of the pool, so it is stated as a share of the pool.
          label: "Candidates found",
          value: armCountItems((key) => counts[key] ?? 0, pool),
          detail: `${pool} in the combined candidate pool`,
        },
        {
          label: FUSED_LABEL,
          value: signals ? `#${signals.pre_rerank_rank}` : "-",
          detail: winner
            ? `${winner.model}, before reranking`
            : "no ranked candidate",
        },
        {
          label: FINAL_LABEL,
          value: signals ? `#${signals.final_rank}` : "-",
          detail: diagnostics.rerank_status === "applied"
            ? "model reranking applied"
            : diagnostics.rerank_status,
        },
        {
          label: "Evidence IDs",
          value: "Not requested",
          detail: "search receipt only",
        },
        {
          label: "Time",
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
  // Membership within the shortlist on screen, not the size of a candidate pool
  // this response never reported. Naming the denominator is what keeps the two
  // apart.
  const armMembership = (key: string) => {
    const arm = armLanguage.find((entry) => armPoolKey[entry.key] === key);
    if (!arm) return 0;
    return products.filter((product) => product.signals?.[arm.key].rank != null)
      .length;
  };

  return (
    <ReceiptBand
      path="Eligibility → candidates → combined order → final order → evidence → time"
      items={[
        {
          label: "Eligibility",
          value: plan.length ? String(filterCount) : "Inherited",
          detail: plan.length
            ? `${plan.length} focused search${plan.length === 1 ? "" : "es"}`
            : "authorized prior shortlist",
        },
        {
          label: "Found this shortlist",
          value: armCountItems(armMembership, products.length),
          detail: `${products.length} authorized product${products.length === 1 ? "" : "s"}`,
        },
        {
          label: FUSED_LABEL,
          value: signals ? `#${signals.pre_rerank_rank}` : "-",
          detail: executionPath === "focused_follow_up"
            ? "replayed prior receipt"
            : "current retrieval",
        },
        {
          label: FINAL_LABEL,
          value: signals ? `#${signals.final_rank}` : "-",
          detail: signals?.rerank_rank ? `rerank put it #${signals.rerank_rank}` : "not repeated",
        },
        {
          label: "Evidence IDs",
          value: String(evidenceIds.length),
          detail: evidenceIds.length
            ? evidenceIds.slice(0, 3).map((id) => `#${id}`).join(", ")
            : "none authorized",
        },
        {
          label: "Time",
          value: `${Math.round(latency)} ms`,
          detail: `${trace.length} tool receipt${trace.length === 1 ? "" : "s"}`,
        },
      ]}
    />
  );
}
