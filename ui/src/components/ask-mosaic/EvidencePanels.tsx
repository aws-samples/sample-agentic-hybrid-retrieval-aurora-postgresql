import {
  ChevronRight,
  CircleCheck,
  FileText,
  GitCompareArrows,
} from "lucide-react";
import {
  formatAvailability,
  formatCategoryKey,
  formatPrice,
} from "../../format";
import { productImage } from "../../media";
import {
  FINAL_LABEL,
  FUSED_LABEL,
  armLanguage,
} from "../../retrievalLanguage";
import type {
  AgentCitation,
  ProductSummary,
  ResultSignals,
  ToolTraceStep,
} from "../../types";

/**
 * Every tool the service registers, from `service/agent_tools.py`.
 *
 * The label is what the tool does in shopping terms, taken from each function's
 * docstring, and the function name stays beside it. A shopper reads the left
 * column and a participant can open that file and read all five in the right
 * one, which is the whole claim of this panel: the agent orchestrates retrieval
 * rather than replacing it.
 *
 * This is also the panel's opening state, and it used to be three invented
 * example questions: one of them asked the agent to explain a ranking before
 * anything had been ranked. The starters below are the eval set instead.
 */
const agentTools = [
  { fn: "search_products", label: "Search the catalog" },
  { fn: "compare_products", label: "Compare options side by side" },
  { fn: "get_product_evidence", label: "Look up specs and reviews" },
  { fn: "explain_retrieval", label: "Replay the ranking signals" },
  { fn: "synthesize_cited_answer", label: "Write the cited recommendation" },
];

const toolLabels = new Map(agentTools.map((tool) => [tool.fn, tool.label]));

/**
 * One chip per arm that retrieved the row.
 *
 * `RankSignal.rank` is null for an arm that never retrieved the product, so this
 * reports measured arm membership. The reference design put a "96% match" badge
 * on every row; no such number exists in `ResultSignals`, and the reranker score
 * is the one bounded relevance figure the service actually produces — which is
 * why it is the last chip and carries its own word rather than a bare decimal.
 *
 * The labels used to be a third set: "Your exact words", "Close spellings",
 * "What you meant", against the product card's "Exact terms" / "Close spelling" /
 * "Meaning match" for the same three arms.
 */
export function retrievalChips(signals: ResultSignals | null | undefined): string[] {
  if (!signals) return ["In the shortlist"];
  const matched = armLanguage
    .filter((arm) => signals[arm.key].rank != null)
    .map((arm) => arm.label);
  const chips = matched.length ? matched : ["Carried in by combined ranking"];
  if (signals.rerank_score != null) {
    chips.push(`Rerank score ${signals.rerank_score.toFixed(2)}`);
  }
  return chips;
}

/** A value the comparison table can print without inventing anything. */
function comparableAttribute(value: unknown): value is string | number | boolean {
  return (
    (typeof value === "string" && value.length > 0 && value.length <= 40)
    || typeof value === "number"
    || typeof value === "boolean"
  );
}

function attributeText(value: string | number | boolean): string {
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

/**
 * Side-by-side catalog facts for the top of the shortlist.
 *
 * Every row is a field of the product record: price, rating, availability,
 * and whichever attributes all compared products carry. The reference design
 * scored candidates "Very good" / "Excellent" per factor; no such judgment
 * exists in the contract, so none is printed.
 */
export function CompareMatrix({ candidates }: { candidates: ProductSummary[] }) {
  const products = candidates.slice(0, 3);
  if (products.length < 2) return null;
  const sharedAttributes = Object.entries(products[0].attributes)
    .filter(([name, value]) => (
      comparableAttribute(value)
      && products.every((product) => comparableAttribute(product.attributes[name]))
    ))
    .map(([name]) => name)
    .slice(0, 3);
  return (
    <section className="ask-mosaic-section ask-mosaic-comparison">
      <header>
        <GitCompareArrows size={18} />
        <div>
          <h3>Side by side, on catalog data</h3>
          <p>Every value below comes from the product records in this shortlist.</p>
        </div>
      </header>
      <div className="ask-mosaic-compare-scroll">
        <table className="ask-mosaic-compare">
          <thead>
            <tr>
              <td />
              {products.map((product, index) => (
                <th
                  className={index === 0 ? "leader" : undefined}
                  key={product.product_id}
                  scope="col"
                >
                  <small>{String(index + 1).padStart(2, "0")}</small>
                  {`${product.brand} ${product.model}`}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">Price</th>
              {products.map((product, index) => (
                <td className={index === 0 ? "leader" : undefined} key={product.product_id}>
                  {formatPrice(product.price_cents, product.currency)}
                </td>
              ))}
            </tr>
            <tr>
              <th scope="row">Rating</th>
              {products.map((product, index) => (
                <td className={index === 0 ? "leader" : undefined} key={product.product_id}>
                  {product.rating != null
                    ? `${product.rating.toFixed(1)} (${product.review_count})`
                    : "-"}
                </td>
              ))}
            </tr>
            <tr>
              <th scope="row">Availability</th>
              {products.map((product, index) => (
                <td className={index === 0 ? "leader" : undefined} key={product.product_id}>
                  {formatAvailability(product.availability)}
                </td>
              ))}
            </tr>
            {sharedAttributes.map((name) => (
              <tr key={name}>
                <th scope="row">{name.replace(/_/g, " ")}</th>
                {products.map((product, index) => (
                  <td className={index === 0 ? "leader" : undefined} key={product.product_id}>
                    {attributeText(product.attributes[name] as string | number | boolean)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

interface ShortlistProps {
  candidates: ProductSummary[];
  imageByProductId: Map<number, string>;
  highlightedProductId: number | null;
  onHighlight: (productId: number | null) => void;
  onSelectProduct: (productId: number) => void;
}

export function Shortlist({
  candidates,
  imageByProductId,
  highlightedProductId,
  onHighlight,
  onSelectProduct,
}: ShortlistProps) {
  return (
    <section className="ask-mosaic-section">
      <header>
        <GitCompareArrows size={18} />
        <div>
          <h3>The shortlist</h3>
          <p>Real catalog products, in the order search ranked them.</p>
        </div>
      </header>
      <ol className="ask-mosaic-shortlist">
        {candidates.slice(0, 4).map((product, index) => (
          <li
            className={highlightedProductId === product.product_id ? "highlighted" : ""}
            key={product.product_id}
          >
            <button
              type="button"
              onClick={() => onSelectProduct(product.product_id)}
              onFocus={() => onHighlight(product.product_id)}
              onBlur={() => onHighlight(null)}
              onMouseEnter={() => onHighlight(product.product_id)}
              onMouseLeave={() => onHighlight(null)}
            >
              <span className="ask-mosaic-shortlist-media">
                <img
                  src={imageByProductId.get(product.product_id) ?? productImage(product)}
                  alt={product.title}
                  width={1200}
                  height={800}
                  loading="lazy"
                  decoding="async"
                />
                <small>{String(index + 1).padStart(2, "0")}</small>
              </span>
              {/* Phrasing content only. A button may not contain `div` or `ol`,
                  and the row carries four distinct fields that each need their
                  own grid area. */}
              <span className="ask-mosaic-shortlist-copy">
                {index === 0 ? <span className="ask-mosaic-card-pick">Best match</span> : null}
                <strong>{product.brand} {product.model}</strong>
                <small>{formatCategoryKey(product.category_key)}</small>
              </span>
              <span className="ask-mosaic-shortlist-meta">
                <strong>{formatPrice(product.price_cents, product.currency)}</strong>
                {product.rating != null ? (
                  <small>{product.rating.toFixed(1)} · {product.review_count} reviews</small>
                ) : null}
              </span>
              <span
                className="ask-mosaic-shortlist-signals"
                aria-label="Why this candidate was retrieved"
              >
                {retrievalChips(product.signals).map((chip) => (
                  <span key={chip}>{chip}</span>
                ))}
              </span>
              <ChevronRight size={16} aria-hidden="true" />
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}

/**
 * Why the leader leads, in the shopper's vocabulary.
 *
 * The rows read "FTS / pg_trgm / Vector / RRF / Reranker / Final" — four Postgres
 * and information-retrieval terms inside a shopping concierge. The numbers are
 * unchanged, and every one of them is this product's own position, so each is
 * printed with a `#`. The mechanism behind each row is named on the Playground,
 * beside the SQL that produced it.
 */
export function Ranking({ candidates }: { candidates: ProductSummary[] }) {
  const winner = candidates[0];
  const signals = winner?.signals;
  if (!signals) return null;
  return (
    <details className="ask-mosaic-ranking">
      <summary>
        <span>Why this result ranks first</span>
        <small>{winner.model}</small>
      </summary>
      <dl>
        {armLanguage.map((arm) => (
          <div key={arm.key}>
            <dt>{arm.label}</dt>
            <dd>{signals[arm.key].rank ? `#${signals[arm.key].rank}` : "-"}</dd>
          </div>
        ))}
        <div>
          <dt>{FUSED_LABEL}</dt>
          <dd>#{signals.pre_rerank_rank}</dd>
        </div>
        <div>
          <dt>Rerank score</dt>
          <dd>
            {signals.rerank_score?.toFixed(3) ?? "-"}
            {signals.rerank_rank ? ` (#${signals.rerank_rank})` : ""}
          </dd>
        </div>
        {signals.exact_sku_match ? (
          <div>
            <dt>Exact model match</dt>
            <dd>Yes</dd>
          </div>
        ) : null}
        <div>
          <dt>{FINAL_LABEL}</dt>
          <dd>#{signals.final_rank}</dd>
        </div>
      </dl>
    </details>
  );
}

export function Evidence({ citations }: { citations: AgentCitation[] }) {
  return (
    <details className="ask-mosaic-receipt">
      <summary>
        <FileText size={17} />
        Evidence it cited
        <span>{citations.length}</span>
      </summary>
      <ol className="ask-mosaic-evidence">
        {citations.map((citation) => (
          <li key={`${citation.number}-${citation.evidence_id}`}>
            <span>[{citation.number}]</span>
            <div>
              <strong>{citation.title}</strong>
              <p>{citation.quote}</p>
              <small>
                Record #{citation.evidence_id} · {citation.evidence_type.replace(/_/g, " ")} ·{" "}
                {citation.revision}
              </small>
            </div>
          </li>
        ))}
      </ol>
    </details>
  );
}

/**
 * Closed on every turn, unlike the other two receipts. Expanded, the trace is
 * the longest block in the panel and pushes the answer, the shortlist, and the
 * citations off a laptop screen; the count in the summary is what a reader needs
 * at a glance.
 */
export function Activity({ trace }: { trace: ToolTraceStep[] }) {
  return (
    <details className="ask-mosaic-receipt">
      <summary>
        <CircleCheck size={17} />
        Recorded steps
        <span>{trace.length}</span>
      </summary>
      <ol className="ask-mosaic-activity">
        {trace.map((step) => (
          <li className={step.outcome} key={step.sequence}>
            <span>{String(step.sequence).padStart(2, "0")}</span>
            <div>
              <strong>{toolLabels.get(step.tool) ?? step.tool}</strong>
              <code className="ask-mosaic-tool-fn">{step.tool}</code>
              <small>{step.origin === "model" ? "Requested by the model" : step.origin === "controller_fallback" ? "Started by the application" : "Origin not recorded"}</small>
              <small>{step.outcome === "success" ? "Step completed" : step.outcome === "error" ? "Step failed" : "Step declined"}</small>
              <small>{step.detail}</small>
              {Object.keys(step.arguments).length ? (
                <code>{JSON.stringify(step.arguments)}</code>
              ) : null}
              <p>
                {step.retrieval_run_id ? (
                  <em>Run {step.retrieval_run_id.slice(0, 8)}</em>
                ) : null}
                {step.latency_ms != null ? (
                  <em>{Math.round(step.latency_ms)} ms</em>
                ) : null}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </details>
  );
}
