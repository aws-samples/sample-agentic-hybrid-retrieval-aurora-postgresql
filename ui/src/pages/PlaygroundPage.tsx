import { RETRIEVAL_CONNECTION_GUIDE } from "../components/RetrievalTakeawayLinks";
import { ArrowRight, ArrowUpRight, Download } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useReducedMotion } from "motion/react";
import { Link } from "wouter";
import { api } from "../api";
import { CodeBlock } from "../components/CodeBlock";
import { LabOutcomeBanner } from "../components/LabOutcomeBanner";
import { MosaicLabsMasthead } from "../components/MosaicLabsMasthead";
import { MosaicLabsTabs } from "../components/MosaicLabsTabs";
import { MosaicRunButton } from "../components/MosaicRunButton";
import { ProductAnswer } from "../components/ProductAnswer";
import { ProductReceiptBody } from "../components/ProductReceipt";
import { SearchTimingDetails } from "../components/RetrievalDiagnosticsStrip";
import { PersistedRunDisclosures } from "../components/RetrievalProvenance";
import { SourceComparison } from "../components/SourceComparison";
import { pickName } from "../components/ask-mosaic/comparison";
import { sourceAnchor } from "../components/ask-mosaic/citations";
import { useSoftReveal } from "../components/ask-mosaic/softReveal";
import { StreamedAnswer } from "../components/ask-mosaic/StreamedAnswer";
import { armReads } from "../components/playground/MethodReads";
import { CandidatePoolOrder } from "../components/playground/CandidatePoolOrder";
import { DepthRow } from "../components/playground/DepthRow";
import { FusionTable } from "../components/playground/FusionTable";
import { MethodBoard } from "../components/MethodBoard";
import { RankRace } from "../components/playground/RankRace";
import { RunSteps, agentChips, recordChip, searchChips, searchingChips } from "../components/playground/RunSteps";
import { ReturnedProducts } from "../components/playground/ReturnedProducts";
import { RunSummary } from "../components/playground/RunSummary";
import { MethodComparison, modelName, rerankStep, signedScore } from "../components/playground/RetrievalPath";
import { formatPriceCompact, withoutBreakTags } from "../format";
import { armLabel, armLanguage } from "../retrievalLanguage";
import { coreMosaicLabs, mosaicLabManifest, pipelineRequests, type MosaicLabMission } from "../labMissions";
import { retrievalLabOutcome, runMatchesMissionGates, targetRankBound, type LabOutcome } from "../labOutcome";
import { productImageMap } from "../media";
import { forwardedSearchEvent, forwardedSearchFilters, useSearchParams } from "../navigation";
import type { AgentCitation, AgentResponse, ProductSummary, ReadinessResponse, ScorecardStageAblation, SearchFilters, SearchResponse, ToolTraceStep } from "../types";
import { useLabStates } from "../useLabStates";
import { usePipelineRun, type PipelineReceipt } from "../usePipelineRun";
import { SpotlightTour } from "../components/SpotlightTour";
import { AGENT_STEPS_HINT, ASK_AGENT_HINT, SEARCH_FIRST_HINT } from "../tour";
import { useHint } from "../useHint";
import "../inspector.css";
import "../playground-page.css";

const requests = pipelineRequests;
/** Two rows of at most four, so no decision point shows more choices than a reader holds at once. */
const primaryRequestIds = new Set(mosaicLabManifest.playground.requests.map((request) => request.id));
const requestGroups = [
  { label: "Alex’s needs", requests: requests.filter((request) => primaryRequestIds.has(request.id)) },
  { label: "Retrieval agent examples", requests: requests.filter((request) => !primaryRequestIds.has(request.id)) },
].filter((group) => group.requests.length);
type Inspection = "retrieve" | "rank" | "rerank" | "reason";

const LESSONS: Record<Inspection, string> = {
  retrieve: "A reranker can only reorder what entered this pool.",
  rank: "A right winner can hide broken fusion: check the order before reranking.",
  rerank: "Re-rank compares the request with every candidate, but cannot recover a product Rank excluded.",
  reason: "A source link still has to support the claim; missing support stays an open question.",
};
const rank = (value: number | null | undefined) => (value == null ? "—" : `#${value}`);

/** The details a link opens: `#inspect-rank`, `#labs-stage-re-rank` and the like. */
function linkedDetail(): Inspection | null {
  const linked = linkedInspection();
  return (Object.keys(linked) as Inspection[]).find((stage) => linked[stage]) ?? null;
}

function linkedInspection(): Record<Inspection, boolean> {
  const stage = /^#(?:labs-stage-|inspect-)(retrieve|rank|re-rank|rerank|reason)$/.exec(window.location.hash)?.[1];
  return { retrieve: stage === "retrieve", rank: stage === "rank", rerank: stage === "rerank" || stage === "re-rank", reason: stage === "reason" };
}

export function InspectorDetail({ title, children }: { title: string; children: ReactNode }) {
  return <details className="inspector-detail"><summary>{title}</summary><div>{children}</div></details>;
}

function RetrieveDetails({ response, receipts, selectedId, onSelect, ablation }: {
  response?: SearchResponse; receipts: PipelineReceipt[]; selectedId?: string;
  onSelect: (id: string) => void; ablation: ScorecardStageAblation | null;
}) {
  const diagnostics = response?.diagnostics;
  return <>
    <p className="inspector-note">{LESSONS.retrieve}</p>
    {receipts.length > 1 ? <div className="inspector-search-plan">
      <h3>The Retrieval agent’s searches</h3>
      <ol>{receipts.map((receipt, index) => <li key={receipt.id}>
        <button type="button" aria-pressed={receipt.id === selectedId} onClick={() => onSelect(receipt.id)}>Search {index + 1}: {receipt.response?.query ?? (receipt.error ? "Details unavailable" : "Loading…")}</button>
      </li>)}</ol>
    </div> : null}
    <MethodComparison response={response} ablation={ablation} />
    {response ? <InspectorDetail title="Request, filters and retrieval settings">
      <CodeBlock label="Search record" code={JSON.stringify({ query: response.query, applied_filters: response.applied_filters, embedding_model_id: diagnostics?.embedding_model_id, retrieval_profile: diagnostics?.retrieval_profile, candidate_counts: diagnostics?.candidate_counts }, null, 2)} />
    </InspectorDetail> : null}
  </>;
}

function RankDetails({ response, images, highlightedId }: { response?: SearchResponse; images: Map<number, string>; highlightedId: number | null }) {
  const products = response?.results ?? [];
  if (!response) return <p className="inspector-waiting">The same products will appear here with their positions at each ranking step.</p>;
  return <>
    <p className="inspector-note">Reranker: <strong>{response.diagnostics?.rerank_status ?? "not reported"}</strong>{response.diagnostics?.rerank_model_id ? ` · ${response.diagnostics.rerank_model_id}` : ""}. Showing the products returned by this search.</p>
    {products.length ? <div role="region" aria-label="Product ranking details">
      <ul className="inspector-product-ranks">{products.map((product) => <li key={product.product_id} id={`ranked-product-${product.product_id}`} tabIndex={-1} className={highlightedId === product.product_id ? "inspector-highlighted-product" : undefined}>
        <Link href={`/products/${product.product_id}`} className="inspector-product"><img src={images.get(product.product_id)} alt="" width={56} height={48} /><span>{product.title}<small>{formatPriceCompact(product.price_cents, product.currency)}</small></span></Link>
        <dl>{[[armLabel.fts, product.signals?.fts.rank], [armLabel.trigram, product.signals?.trigram.rank], [armLabel.semantic, product.signals?.semantic.rank], ["Combined", product.signals?.pre_rerank_rank], ["Reranked", product.signals?.rerank_rank], ["Final", product.signals?.final_rank]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{rank(value as number | null | undefined)}</dd></div>)}</dl>
      </li>)}</ul>
    </div> : <p className="inspector-waiting">This search returned no products. No ranking is available.</p>}
    <InspectorDetail title="Ranking rules and time taken"><SearchTimingDetails response={response} /><CodeBlock label="Ranking details" code={JSON.stringify({ ranking_policy: response.diagnostics?.ranking_policy, stage_timings_ms: response.diagnostics?.stage_timings_ms, total_latency_ms: response.diagnostics?.total_latency_ms }, null, 2)} /></InspectorDetail>
  </>;
}

/**
 * The receipt for one returned product, then how the order was set: the lead's
 * movement through reranking, the reranker that ran, and what reranking is
 * measured to add on this catalog.
 */
function RankBody({ response, receiptProduct, ablation, stopped, images, onSelect }: {
  response?: SearchResponse; receiptProduct?: ProductSummary; ablation: ScorecardStageAblation | null;
  stopped: boolean; images: Map<number, string>; onSelect: (productId: number) => void;
}) {
  const products = response?.results ?? [];
  const leading = receiptProduct?.signals;
  const step = rerankStep(ablation);
  if (!response || !products.length) {
    return <>
      <p className="inspector-waiting">{!response ? (stopped ? "No ranking is available from this run." : "See how the order changes as Mosaic compares the products.") : "No products were returned, so no ranking is available."}</p>
    </>;
  }
  return <>
    <div className="pg-why">
      {receiptProduct ? <article className="pg-receipt" aria-label={`Receipt for ${receiptProduct.title}`}>
        <h3>{pickName(receiptProduct)}</h3>
        <p className="pg-receipt-sub">{[receiptProduct.sku, receiptProduct.brand].filter(Boolean).join(" · ")}</p>
        <ProductReceiptBody product={receiptProduct} diagnostics={response.diagnostics} />
      </article> : null}
      <div className="pg-order">
        <h3>How the order was set</h3>
        <p className="pg-order-flow"><span>Combined score</span><ArrowRight size={14} aria-hidden="true" /><span>{modelName(response.diagnostics?.rerank_model_id) ?? "Cohere Rerank"}</span><ArrowRight size={14} aria-hidden="true" /><span>Final order</span></p>
        {leading ? <p className="pg-rank-move" aria-label={`${rank(leading.pre_rerank_rank)} before rerank, ${rank(leading.final_rank)} in the final order`}>
          <b>{rank(leading.pre_rerank_rank)}</b><ArrowRight size={20} aria-hidden="true" /><b>{rank(leading.final_rank)}</b>
          <span>The selected product’s position before and after reranking.</span>
        </p> : null}
        <p>Reranking: <strong>{response.diagnostics?.rerank_status ?? "not reported"}</strong>. #1 is the highest rank. Combined and reranker scores use different scales; a higher score is better within each step.</p>
        {step ? <p>Measured on {ablation?.scored_query_count} judged searches: reranking moved the ordering score by {signedScore(step.mean_difference)} on average, {step.separable ? "more than" : "inside"} the spread of the per-search differences.</p> : null}
      </div>
    </div>
    <h3 className="pg-subhead">Everything it returned.</h3>
    <ReturnedProducts products={products} images={images} selectedId={receiptProduct?.product_id ?? null} onSelect={onSelect} />
  </>;
}

function ProductSearchLinks({ product, receipts, running, onSelect }: {
  product: ProductSummary; receipts: PipelineReceipt[]; running: boolean;
  onSelect: (searchId: string, productId: number) => void;
}) {
  const matches = receipts.filter((receipt) => receipt.origin !== "reference").flatMap((receipt, index) => {
    const result = receipt.response?.results.find((item) => item.product_id === product.product_id);
    return result ? [{ receipt, index, rank: result.signals?.final_rank }] : [];
  });
  if (!matches.length) {
    const loading = running || receipts.some((receipt) => !receipt.response && !receipt.error);
    return <p className="inspector-product-search-note">{loading ? "Loading this product’s search…" : receipts.some((receipt) => receipt.error) ? "This product’s search details could not be loaded." : "This product was not found in the recorded searches."}</p>;
  }
  return <div className="inspector-product-search-links">{matches.map(({ receipt, index, rank: final }) => <button key={receipt.id} type="button" aria-label={`${product.title}: show Search ${index + 1}${final == null ? "" : `, rank ${final}`}`} onClick={() => onSelect(receipt.id, product.product_id)}>Search {index + 1}{final == null ? "" : ` · #${final} in Rank`} <ArrowRight size={13} aria-hidden="true" /></button>)}</div>;
}

const EXCERPT = 160;
const excerpt = (raw: string) => {
  const text = withoutBreakTags(raw);
  return text.length > EXCERPT ? `${text.slice(0, EXCERPT).replace(/\s\S*$/, "")}…` : text;
};

/** The answer's sources, numbered as its prose cites them; each citation chip jumps to its entry. */
function AnswerSources({ citations, answerId }: { citations: AgentCitation[]; answerId: string }) {
  if (!citations.length) return null;
  return <aside className="pg-sources" aria-labelledby="pg-sources-title">
    <h3 id="pg-sources-title">Sources</h3>
    <ol>{citations.map((citation) => <li key={`${citation.number}-${citation.evidence_id}`} id={sourceAnchor(answerId, citation.number)} tabIndex={-1} value={citation.number}>
      <span className="pg-source-kind">{/review/i.test(citation.evidence_type) ? "Review" : "Listing"}</span>
      <strong>{citation.title}</strong>
      {/review/i.test(citation.evidence_type) && citation.quote ? <q>{excerpt(citation.quote)}</q> : null}
      <a href={`/api/evidence/${citation.evidence_id}`} target="_blank" rel="noreferrer">Record {citation.evidence_id} <ArrowUpRight size={12} aria-hidden="true" /></a>
    </li>)}</ol>
  </aside>;
}

/**
 * The Retrieval agent's answer, read out as Ask Mosaic reads it: a few words at a
 * time, each fading in once. Its sources and picks wait until the prose is out,
 * so nothing moves the sentence being read. Mounted per run, because the reveal
 * paces only an answer that was still streaming when it first appeared.
 */
function RevealedAnswer({ answer, streamed, completed, renderSearchLink, multipleSearches, onSettled }: {
  answer: AgentResponse; streamed: string; completed: boolean;
  renderSearchLink: (product: ProductSummary) => ReactNode; multipleSearches: boolean;
  onSettled: (agentRunId: string) => void;
}) {
  const reduceMotion = useReducedMotion();
  const reveal = useSoftReveal(streamed || answer.answer, !completed, true, reduceMotion ?? false);
  const done = completed && reveal.done;
  useEffect(() => { if (done) onSettled(answer.agent_run_id); }, [done, answer.agent_run_id, onSettled]);
  const answerId = `pg-answer-${answer.agent_run_id}`;
  const status = answer.outcome === "declined"
    ? "No recommendation: the available sources do not support a choice."
    : done
      ? `${answer.recommendations.length ? `${answer.recommendations.length} ${answer.recommendations.length === 1 ? "recommendation" : "recommendations"}` : "Answer ready"} · ${answer.citations.length} ${answer.citations.length === 1 ? "source link" : "source links"}.`
      : "Writing the answer…";
  // The result leads on the left from the first word; the prose reads out beside it,
  // and its sources follow once it is out, so nothing moves the line being read.
  const picks = answer.outcome !== "declined" && answer.recommendations.length > 0;
  return <div className="pg-answer-layout" data-picks={picks || undefined}>
    {picks ? <div className="pg-picks">
      <ProductAnswer text="" products={answer.recommendations} citations={answer.citations} complete renderSearchLink={renderSearchLink} />
      {multipleSearches && done ? <p className="inspector-note">Each pick links to the search that found it.</p> : null}
    </div> : null}
    <div className="pg-answer-text">
      <p className="pg-reason-summary">{status}</p>
      <div className="inspector-answer pg-answer" aria-busy={!done}>
        <StreamedAnswer className="product-answer" text={reveal.text} chunks={reveal.chunks} citations={answer.citations} answerId={answerId} />
      </div>
      {done ? <AnswerSources citations={answer.citations} answerId={answerId} /> : null}
    </div>
  </div>;
}

/** Where the followed product stood in each search, in one sentence. */
function followSentence(product: ProductSummary): string {
  const signals = product.signals;
  const found = armLanguage.filter((arm) => signals?.[arm.key].rank != null);
  const missed = armLanguage.filter((arm) => signals?.[arm.key].rank == null);
  const ranks = found.map((arm) => `${arm.label.toLowerCase()} #${signals?.[arm.key].rank}`).join(", ");
  const unfound = missed.length ? ` Not found by ${missed.map((arm) => arm.label.toLowerCase()).join(" or ")}.` : "";
  return `${pickName(product)}: ${ranks || "no search recorded a rank"}.${unfound}`;
}

/** Retrieve at a glance: each search's own top five, then where the followed product stood. */
function RetrieveGlance({ response, follow, missing, stopped, wanted, images, onSelect }: {
  response?: SearchResponse; follow?: ProductSummary; missing?: string; stopped: boolean;
  wanted?: { id: number | null; name?: string; targetRank?: number };
  images: Map<number, string>; onSelect: (productId: number) => void;
}) {
  if (!response) return <p className="inspector-waiting">{stopped ? "No search results are available from this run." : "Run a search to see what each search found."}</p>;
  return <>
    <MethodBoard response={response} only={SEARCH_COLUMNS} reads={armReads(response)} wantedId={wanted?.id ?? null} wantedName={wanted?.name} targetRank={wanted?.targetRank} images={images} onSelect={onSelect} />
    {missing || follow ? <p className="pg-follow">{missing ? `The ${missing} is not among the products this search returned.` : followSentence(follow as ProductSummary)}</p> : null}
  </>;
}

const SEARCH_COLUMNS = ["fts", "trigram", "semantic"] as const;

/** Rank at a glance: the followed product's shares, their sum, and the combined position it earned. */
function RankGlance({ response, follow, missing }: { response?: SearchResponse; follow?: ProductSummary; missing?: string }) {
  if (!response) return <p className="inspector-waiting">Run a search to see how Aurora combined the positions.</p>;
  if (missing) return <p className="pg-follow">The {missing} is not among the products this search returned. Fusion details lists every saved candidate.</p>;
  const signals = follow?.signals;
  const k = response.diagnostics?.retrieval_profile?.rrf_k;
  if (!follow || !signals || k == null) return null;
  const parts = armLanguage.filter((arm) => signals[arm.key].rank != null);
  const sum = parts.reduce((total, arm) => total + (signals[arm.key].rrf_contribution ?? 0), 0);
  const pool = response.diagnostics?.candidate_counts?.fused_pool;
  const reported = Math.abs(sum - signals.rrf_score) > 1e-6 ? ` (reported ${signals.rrf_score.toFixed(4)})` : "";
  return <div className="pg-rrf-glance">
    <p className="pg-follow">{pickName(follow)}</p>
    <p className="pg-rrf-sum">
      {parts.map((arm, index) => <span key={arm.key}>{index ? <i aria-hidden="true">+</i> : null}<span className="pg-rrf-term"><small>{arm.label}</small><code>1 / ({k} + {signals[arm.key].rank})</code></span></span>)}
      <i aria-hidden="true">=</i><b className="pg-rrf-score">{sum.toFixed(4)}</b>{reported}
      <i aria-hidden="true">→</i><span>combined #{signals.pre_rerank_rank}{pool ? ` of ${pool}` : ""}</span>
    </p>
  </div>;
}

/** Reason's own body: who asked for each step, and where the answer is. */
function ReasonSummary({ trace, answered, working, failed, hasSearch }: {
  trace: ToolTraceStep[]; answered: boolean; working: boolean; failed: boolean; hasSearch: boolean;
}) {
  if (!trace.length) {
    return <p className="inspector-waiting">{failed ? "The run stopped before the answer was ready. Open Steps and sources for details." : working ? "The Retrieval agent is choosing its searches." : hasSearch ? "This view holds the saved search. Ask the Retrieval agent to search and recommend." : "The Retrieval agent compares the products and explains its picks, with links to the sources."}</p>;
  }
  const model = trace.filter((step) => step.origin === "model").length;
  const application = trace.filter((step) => step.origin === "controller_fallback").length;
  return <p className="pg-reason-steps">
    {trace.length} tool {trace.length === 1 ? "call" : "calls"}: <strong>{model} requested by the model</strong>, {application} started by the application.
    {answered ? " Its answer leads this page; Steps and sources lists every call with its inputs." : ""}
  </p>;
}

function ReasonEvidence({ answer, trace, failed }: { answer: AgentResponse | null; trace: ToolTraceStep[]; failed: boolean }) {
  const modelSteps = trace.filter((step) => step.origin === "model").length;
  const applicationSteps = trace.filter((step) => step.origin === "controller_fallback").length;
  const unreportedSteps = trace.length - modelSteps - applicationSteps;
  return <>
    <p className="inspector-note">{LESSONS.reason}</p>
    {answer ? <p className="inspector-note">Source numbers in the answer identify evidence, not recommendation ranks.</p> : <p className="inspector-note">{failed ? "The run stopped without a completed answer. Any recorded steps are shown below." : "The answer is not ready yet. You can see the steps taken so far below."}</p>}
    <p className="inspector-note">The model can request searches, comparisons and sources. Application code checks the arguments, filters and allowed records before carrying out those requests. Each search repeats Retrieve and Rank.</p>
    {trace.length ? <p className="inspector-note" aria-label="Who requested the recorded steps"><strong>Requested by the model: {modelSteps}.</strong> Started by the application: {applicationSteps}.{unreportedSteps ? ` Origin not recorded: ${unreportedSteps}.` : ""} The activity log shows which steps succeeded, failed or were declined.</p> : null}
    {answer?.recommendations.length ? <InspectorDetail title="Compare the sources"><SourceComparison answer={answer} /></InspectorDetail> : null}
    <InspectorDetail title={`Activity log${trace.length ? ` · ${trace.length} calls` : ""}`}>
      {trace.length ? <ol className="inspector-trace">{trace.map((step) => <li key={step.sequence}>
        <header><code>{step.tool}</code><span>{step.outcome}{step.latency_ms == null ? "" : ` · ${Math.round(step.latency_ms)} ms`}</span></header>
        <p className="inspector-note">{step.origin === "model" ? "Requested by the model" : step.origin === "controller_fallback" ? "Started by the application" : "Origin not recorded"}</p>
        <p>{step.detail}</p><CodeBlock label="Step details" code={JSON.stringify({ arguments: step.arguments, retrieval_run_id: step.retrieval_run_id, result_count: step.result_count, origin: step.origin }, null, 2)} />
      </li>)}</ol> : <p>No tool calls have been recorded in this view.</p>}
    </InspectorDetail>
    <p className="inspector-note">Mosaic checks the product details and sources before making a recommendation.</p>
  </>;
}

/** Alex's request as the page's stage: the choice of request, the words, and the one run action. */
function RequestStage({ selectedId, carried, question, context, runButton, onChoose }: {
  selectedId?: string; carried: boolean; question: string; context: string;
  runButton: ReactNode; onChoose: (id: string) => void;
}) {
  return <section className="pg-stage" aria-label="Alex’s request">
    <MosaicLabsMasthead title={<>Behind a <span className="inspector-title-emphasis">better answer.</span></>} deck="Follow one request from three searches to one answer." />
    <div className="pg-query" data-tour="pg-search">
      <img className="pg-alex" src="/assets/images/mosaic/alex-headshot-v1.jpg" alt="Alex, Mosaic’s example shopper" width={44} height={44} />
      <div><h2>{question || "No request is available"}</h2><p>{context}</p></div>
      {runButton}
    </div>
    <nav className="pg-requests" aria-label="Alex’s requests" data-tour="pg-suggestions">{requestGroups.map((group) => <div key={group.label} role="group" aria-label={group.label}>
      {group.requests.map((request) => <button key={request.id} type="button" aria-pressed={!carried && selectedId === request.id} onClick={() => onChoose(request.id)}>{request.label}</button>)}
    </div>)}</nav>
  </section>;
}

/**
 * The lab's verdict on this run, when the link names a lab and the run is that
 * lab's own request under its own gates. Shop's lab callouts link here, and a
 * page of plausible results with no verdict was the trap the lab teaches.
 */
function missionOutcome(
  mission: MosaicLabMission | undefined,
  response: SearchResponse | undefined,
  readiness: ReadinessResponse | null,
): LabOutcome | null {
  if (!mission || !response || (mission.stage !== "retrieve" && mission.stage !== "rank")) return null;
  if (response.query !== mission.query || !runMatchesMissionGates(mission, response)) return null;
  return retrievalLabOutcome(mission, response, readiness);
}

/** Between the request and the result: a saved search's status, a stopped run, and which search is shown. */
function RunNotes({ carried, started, running, error, receipts, selected, onRestore, onSelectSearch, labOutcome }: {
  carried: boolean; started: boolean; running: boolean; error: string; receipts: PipelineReceipt[];
  selected?: PipelineReceipt; onRestore: () => void; onSelectSearch: (id: string) => void;
  labOutcome: LabOutcome | null;
}) {
  return <div className="pg-run-notes">
    {labOutcome ? <LabOutcomeBanner outcome={labOutcome} /> : null}
    {carried && started ? <p className="pg-saved-line">
      A new run of the saved Shop search · <button type="button" disabled={running} onClick={onRestore}>Back to saved Shop results</button>
    </p> : null}
    {error ? <p className="inspector-error" role="alert">{error}</p> : null}
    {receipts.length > 1 ? <div className="inspector-search-selector pg-search-selector"><label htmlFor="inspector-search">Search shown in Retrieve, Rank and Re-rank</label><select id="inspector-search" value={selected?.id} onChange={(event) => onSelectSearch(event.target.value)}>{receipts.map((item, index) => <option key={item.id} value={item.id}>{index + 1}. {item.origin === "reference" ? "Original search · " : ""}{item.response?.query ?? "Reading search…"}</option>)}</select><p>Counts and ranks stay on the selected search. Choose another search here or follow a pick in Reason.</p></div> : null}
    {selected?.error ? <p className="inspector-error" role="alert">This record could not be read: {selected.error} {carried && !started ? "Reload this page to retry the saved Shop search." : "Start a new run to try again."}</p> : null}
  </div>;
}

function useInspectorData() {
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  const [ablation, setAblation] = useState<ScorecardStageAblation | null>(null);
  useEffect(() => {
    let active = true;
    void api.readiness().then((value) => { if (active) setReadiness(value); }).catch(() => {});
    // The committed measurement behind "why hybrid": read-only, no Aurora call.
    void api.scorecard().then((value) => { if (active) setAblation(value.stage_ablation); }).catch(() => {});
    return () => { active = false; };
  }, []);
  return { readiness, catalogCount: readiness?.database.product_count, ablation };
}

function PipelineInspector() {
  const [params, setParams] = useSearchParams();
  const carriedEvent = forwardedSearchEvent(params);
  const requestKey = params.toString();
  const selectedRequest = requests.find((request) => request.id === (params.get("scene") ?? mosaicLabManifest.playground.default_request));
  const initialQuestion = params.get("q") || selectedRequest?.query || "";
  const filters = (params.has("q") ? forwardedSearchFilters(params) : selectedRequest?.filters ?? {}) as SearchFilters;
  const pipeline = usePipelineRun(`${requestKey}:${initialQuestion}`, carriedEvent);
  const { readiness, catalogCount, ablation } = useInspectorData();
  const mission = coreMosaicLabs.find((item) => item.id === params.get("example"));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [openDetail, setOpenDetail] = useState<Inspection | null>(linkedDetail);
  const [highlightedId, setHighlightedId] = useState<number | null>(null);
  const [receiptId, setReceiptId] = useState<number | null>(null);
  const [settledRun, setSettledRun] = useState<string | null>(null);
  const onSettled = useCallback((agentRunId: string) => setSettledRun(agentRunId), []);
  useEffect(() => { setOpenDetail(linkedDetail()); setSelectedId(null); setHighlightedId(null); setReceiptId(null); }, [requestKey]);
  useEffect(() => {
    if (openDetail !== "rerank" || highlightedId == null) return;
    const target = document.getElementById(`ranked-product-${highlightedId}`);
    target?.scrollIntoView({ block: "nearest" });
    target?.focus({ preventScroll: true });
  }, [openDetail, highlightedId, selectedId, pipeline.receipts]);
  // An agent run's searches wait until its answer has been read out, then arrive together.
  const held = pipeline.started && !pipeline.error && !(pipeline.completed && (!pipeline.answer || settledRun === pipeline.runId));
  const askHint = useHint(ASK_AGENT_HINT.key);
  const stepsHint = useHint(AGENT_STEPS_HINT.key);
  const answered = pipeline.completed && Boolean(pipeline.answer) && !held;
  const showStepsHint = stepsHint.show;
  // Once the first answer has been read out, point at where its steps and sources are.
  useEffect(() => {
    if (!answered) return undefined;
    const timer = window.setTimeout(showStepsHint, 900);
    return () => window.clearTimeout(timer);
  }, [answered, showStepsHint]);
  const selected = held ? undefined : pipeline.receipts.find((item) => item.id === selectedId)
    ?? pipeline.receipts.find((item) => item.origin !== "reference") ?? pipeline.receipts[0];
  const response = selected?.response;
  const products = response?.results ?? [];
  const images = productImageMap(products);
  const raceMission = mission ?? coreMosaicLabs.find((item) => item.id === selectedRequest?.mission_id);
  const missionRun = Boolean(raceMission && response && response.query === raceMission.query && runMatchesMissionGates(raceMission, response));
  const wantedId = missionRun && raceMission
    ? raceMission.target_product_ids.find((id) => products.some((product) => product.product_id === id)) ?? null
    : null;
  const missingWanted = missionRun && wantedId == null ? raceMission?.target_display_name : undefined;
  const { labStates, failed: labStatesFailed } = useLabStates(response?.search_event_id ?? "");
  const rankEntry = labStates?.find((lab) => lab.lab_id === 2)?.entry_state;
  const rankRun = missionRun && raceMission?.stage === "rank";
  // Lab 2's results wait while its state is read, or they would show and then vanish.
  const rankChecking = Boolean(rankRun && !labStates && !labStatesFailed);
  const rankNotOpen = Boolean(rankRun && (rankChecking || rankEntry === "not_started" || rankEntry === "incomplete"));
  const followId = receiptId ?? wantedId ?? products[0]?.product_id ?? null;
  // Each time a search's results come into view the stages arrive again. Alternating two
  // identical animations restarts them without remounting what a reader may be focused on.
  const arrivalKey = response ? `${selected?.id}:${response.search_event_id}` : null;
  const [arrival, setArrival] = useState({ key: null as string | null, count: 0 });
  if (arrivalKey !== arrival.key) setArrival({ key: arrivalKey, count: arrivalKey ? arrival.count + 1 : arrival.count });
  const receiptProduct = products.find((product) => product.product_id === followId) ?? products[0];
  const labOutcome = missionOutcome(mission, response, readiness);
  const question = pipeline.savedResponse?.query ?? initialQuestion;
  const runFilters = (pipeline.savedResponse?.applied_filters ?? filters) as SearchFilters;
  const reset = () => { setSelectedId(null); setHighlightedId(null); setReceiptId(null); };
  const openDetails = (stage: Inspection | null) => {
    setHighlightedId(null);
    setOpenDetail(stage);
    // The agent's steps exist only once it has run, and the bar's button is what runs it.
    if (stage === "reason" && !pipeline.started) askHint.show();
  };
  const showReceipt = (productId: number) => { setReceiptId(productId); };
  const inspectProduct = (id: string, productId: number) => {
    setSelectedId(id); setHighlightedId(productId); setReceiptId(productId); setOpenDetail("rerank");
    window.requestAnimationFrame(() => document.getElementById("inspect-rerank")?.scrollIntoView({ block: "start" }));
  };
  const renderSearchLink = (product: ProductSummary) => <ProductSearchLinks product={product} receipts={pipeline.receipts} running={pipeline.running} onSelect={inspectProduct} />;
  const agentRequest = Boolean(selectedRequest && !primaryRequestIds.has(selectedRequest.id) && !params.has("q") && !carriedEvent);
  // Once a search's results are in, the bar's button asks the Retrieval agent about the same need.
  const askNext = agentRequest || (Boolean(response) && !rankNotOpen);
  const runLabel = pipeline.running
    ? pipeline.completed ? "Finishing up" : ({ retrieve: "Finding products", rank: "Comparing matches", reason: "Preparing the answer" })[pipeline.phase ?? "retrieve"]
    : pipeline.reading ? "Reading saved search" : pipeline.error ? "Try again" : agentRequest ? (pipeline.completed ? "Run again" : "Run Mosaic") : askNext ? "Ask the Retrieval agent" : "Run search";
  const context = `Alex’s workspace${catalogCount ? ` · Catalog: ${catalogCount.toLocaleString()} products` : ""}${runFilters.category_key ? ` · Filter: ${runFilters.category_key.replaceAll("-", " ")}` : ""}`;
  const runButton = <MosaicRunButton type="button" data-tour="pg-run-button" className="inspector-play" label={runLabel} icon={askNext ? "send" : "search"} showLabel={askNext && !agentRequest && !pipeline.running} running={pipeline.running} disabled={pipeline.reading || !question || Boolean(carriedEvent && !pipeline.savedResponse)} onClick={() => { reset(); setOpenDetail(null); void (askNext ? pipeline.play(question, runFilters) : pipeline.search(question, runFilters)); }} />;
  const chips = pipeline.started
    ? agentChips(pipeline.trace, pipeline.phase, pipeline.running && !pipeline.completed)
    : response ? searchChips(response) : pipeline.running ? searchingChips() : [];
  if (response && !held) chips.push(recordChip(response.search_event_id));
  return <div className="page pg-a pipeline-inspector">
    <MosaicLabsTabs active="retrieval" />
    <RequestStage selectedId={selectedRequest?.id} carried={params.has("q") || Boolean(carriedEvent)} question={question} context={context} runButton={runButton} onChoose={(id) => setParams(new URLSearchParams({ scene: id }))} />
    <section className="pg-run" aria-label="This run" data-tour={chips.length ? "pg-chips" : undefined}>
      <p className="pg-run-status" role="status">{pipeline.reading ? "Reading the saved Shop search…" : pipeline.status || (carriedEvent ? "Saved Shop search" : "Ready to follow Alex’s request.")}</p>
      {rankNotOpen ? null : <RunSteps chips={chips} label={pipeline.started ? "The Retrieval agent’s steps" : "How this search ran"} />}
      {pipeline.answer ? <RevealedAnswer key={pipeline.answer.agent_run_id} answer={pipeline.answer} streamed={pipeline.streamed} completed={pipeline.completed} renderSearchLink={renderSearchLink} multipleSearches={pipeline.receipts.length > 1} onSettled={onSettled} /> : null}
      {pipeline.completed && pipeline.answer && !held ? <RunSummary answer={pipeline.answer} receipts={pipeline.receipts} onInspect={inspectProduct} /> : null}
    </section>
    <RunNotes carried={Boolean(carriedEvent)} started={pipeline.started} running={pipeline.running} error={pipeline.error} receipts={held || rankNotOpen ? [] : pipeline.receipts} selected={selected} onRestore={() => { reset(); setOpenDetail(null); pipeline.restoreSavedSearch(); }} onSelectSearch={(id) => { setSelectedId(id); setHighlightedId(null); setReceiptId(null); }} labOutcome={labOutcome} />
    {rankChecking ? null : rankNotOpen ? <section className="pg-lab-gate" aria-label="Lab 2">
      <h2>The ranking exercise is next</h2>
      <p>Finish Lab 1 and prepare Lab 2 in the guide. This request shows its results once Lab 2 has started.</p>
    </section> : <div className="pg-stages" data-arrive={response ? (arrival.count % 2 ? "a" : "b") : undefined}>
      <section className="pg-board" aria-label="Watch the ranking change" data-tour="pg-board">
        {response?.results.length
          ? <RankRace key={response.search_event_id} response={response} followId={followId} wanted={followId != null && followId === wantedId} missing={missingWanted} onFollow={setReceiptId} />
          : <p className="inspector-waiting pg-board-empty">{pipeline.error ? "No ranking is available from this run." : pipeline.running ? "Searching Aurora…" : "Search to watch three searches, Aurora’s combined order and the reranker side by side."}</p>}
      </section>
      <DepthRow open={openDetail} onOpen={openDetails} items={[
        {
          id: "retrieve", label: "Each search’s top five",
          content: <><RetrieveGlance response={response} follow={receiptProduct} missing={missingWanted} stopped={Boolean(pipeline.error)} images={images} onSelect={setReceiptId} wanted={missionRun && raceMission ? { id: wantedId, name: raceMission.target_display_name, targetRank: targetRankBound(raceMission) } : undefined} /><RetrieveDetails response={response} receipts={held ? [] : pipeline.receipts} selectedId={selected?.id} ablation={ablation} onSelect={(id) => { setSelectedId(id); setHighlightedId(null); setReceiptId(null); }} /></>,
        },
        {
          id: "rank", label: "How Aurora combined them",
          content: <><RankGlance response={response} follow={receiptProduct} missing={missingWanted} />{response ? <FusionTable response={response} followId={followId} images={images} /> : null}<p className="inspector-note">{LESSONS.rank}</p>{response ? <PersistedRunDisclosures response={response} /> : null}</>,
        },
        {
          id: "rerank", label: "Why this position",
          content: <><p className="inspector-note">{LESSONS.rerank}</p><RankBody response={response} receiptProduct={receiptProduct} ablation={ablation} stopped={Boolean(pipeline.error)} images={images} onSelect={showReceipt} /><CandidatePoolOrder response={response} /><RankDetails response={response} images={images} highlightedId={highlightedId} /></>,
        },
        {
          id: "reason", label: "Agent steps and sources",
          content: <><ReasonSummary trace={pipeline.trace} answered={Boolean(pipeline.answer)} working={pipeline.running && !pipeline.completed} failed={Boolean(pipeline.error)} hasSearch={Boolean(response)} />{pipeline.runId ? <p className="pg-run-id">Retrieval agent record <code>{pipeline.runId}</code></p> : null}<ReasonEvidence answer={pipeline.completed ? pipeline.answer : null} trace={pipeline.trace} failed={Boolean(pipeline.error)} /></>,
        },
      ]} />
    </div>}
    <aside className="inspector-scale-link inspector-takeaway pg-takeaway">
      <div>
        <h2>Use it in your own agent</h2>
        <p>The SQL and service behind these searches, and a skill that teaches an agent to use them.</p>
      </div>
      <div className="inspector-takeaway-actions">
        <a href="/api/builder-package" download><Download size={16} aria-hidden="true" />Download the retrieval code</a>
        <a href="/api/skill-package" download><Download size={16} aria-hidden="true" />Download the agent skill</a>
        <a href={RETRIEVAL_CONNECTION_GUIDE} target="_blank" rel="noreferrer">Connect over MCP<ArrowUpRight size={16} aria-hidden="true" /></a>
      </div>
    </aside>
    <SpotlightTour hint open={askHint.open} onClose={askHint.close} steps={(response ? ASK_AGENT_HINT : SEARCH_FIRST_HINT).steps} storageKey={ASK_AGENT_HINT.key} />
    <SpotlightTour hint open={stepsHint.open} onClose={stepsHint.close} steps={AGENT_STEPS_HINT.steps} storageKey={AGENT_STEPS_HINT.key} />
  </div>;
}

export function PlaygroundPage() {
  return <PipelineInspector />;
}
