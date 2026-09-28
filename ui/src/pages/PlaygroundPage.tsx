import { ArrowRight, ArrowUpRight, Check, ChevronDown, LoaderCircle } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "wouter";
import { api } from "../api";
import { CodeBlock } from "../components/CodeBlock";
import { KeepInMind } from "../components/KeepInMind";
import { LabOutcomeBanner } from "../components/LabOutcomeBanner";
import { MosaicLabsMasthead } from "../components/MosaicLabsMasthead";
import { MosaicLabsTabs } from "../components/MosaicLabsTabs";
import { MosaicRunButton } from "../components/MosaicRunButton";
import { ProductAnswer } from "../components/ProductAnswer";
import { ProductReceiptBody } from "../components/ProductReceipt";
import { SearchTimingDetails } from "../components/RetrievalDiagnosticsStrip";
import { PersistedRunDisclosures, RrfMath } from "../components/RetrievalProvenance";
import { SourceComparison } from "../components/SourceComparison";
import { pickName } from "../components/ask-mosaic/comparison";
import { LeadResult, type AgentVerdict } from "../components/playground/LeadResult";
import { MethodReads } from "../components/playground/MethodReads";
import { ReturnedProducts } from "../components/playground/ReturnedProducts";
import { MethodComparison, RetrievalPath, modelName, rerankStep, signedScore } from "../components/playground/RetrievalPath";
import { formatPriceCompact } from "../format";
import { coreMosaicLabs, mosaicLabManifest, pipelineRequests, type MosaicLabMission } from "../labMissions";
import { retrievalLabOutcome, runMatchesMissionGates, type LabOutcome } from "../labOutcome";
import { productImageMap } from "../media";
import { forwardedSearchEvent, forwardedSearchFilters, useSearchParams } from "../navigation";
import type { AgentCitation, AgentPartial, AgentResponse, ProductSummary, ReadinessResponse, ScorecardStageAblation, SearchFilters, SearchResponse, ToolTraceStep } from "../types";
import { usePipelineRun, type PipelineReceipt } from "../usePipelineRun";
import { RetrievalLabPage } from "./RetrievalLabPage";
import "../inspector.css";
import "../playground-page.css";

const requests = pipelineRequests;
/** Two rows of at most four, so no decision point shows more choices than a reader holds at once. */
const primaryRequestIds = new Set(mosaicLabManifest.playground.requests.map((request) => request.id));
const requestGroups = [
  { label: "Alex’s needs", requests: requests.filter((request) => primaryRequestIds.has(request.id)) },
  { label: "Agent examples", requests: requests.filter((request) => !primaryRequestIds.has(request.id)) },
].filter((group) => group.requests.length);
type Inspection = "retrieve" | "rank" | "reason";
type ColumnState = "idle" | "pending" | "active" | "complete" | "failed" | "blocked";

const LESSONS: Record<Inspection, string> = {
  retrieve: "A reranker can only reorder what entered this pool. Each search method applies the filters before limiting its results. A filtered vector scan can still return too few matches; eligible products may be missed. Check both which products qualify and how many the search found.",
  rank: "Each search method scores matches differently. RRF combines them using 1 / (k + rank) for each position. A correct final winner can hide broken fusion. Compare the order before reranking, then weigh any measured improvement against the extra time and model usage.",
  reason: "Evidence the model has read is not citable until the application registers it. A valid source link still needs to support the claim. Read the source for the specific requirement; missing support should remain an open question.",
};
const STATE_LABEL: Record<ColumnState, string> = { idle: "", pending: "Waiting", active: "Working", complete: "Done", failed: "Stopped", blocked: "Not reached" };
const STATE_SPOKEN: Record<ColumnState, string> = { idle: "", pending: "waiting", active: "working", complete: "done", failed: "stopped", blocked: "not reached" };
const rank = (value: number | null | undefined) => (value == null ? "—" : `#${value}`);

function linkedInspection(): Record<Inspection, boolean> {
  const stage = /^#(?:labs-stage-|inspect-)(retrieve|rank|reason)$/.exec(window.location.hash)?.[1];
  return { retrieve: stage === "retrieve", rank: stage === "rank", reason: stage === "reason" };
}

/**
 * One stage of the run as a full-width section: a sentence for its heading,
 * its live state, its body, then its details on request. The section keeps the
 * stage's name, so a guide can say "Playground → Reason" and mean this one.
 */
function StageSection({ stage, state, title, heading, lede, expanded, onInspect, detailsLabel, children, details }: {
  stage: Inspection; state: ColumnState; title: string; heading: string; lede: string;
  expanded: boolean; onInspect: () => void; detailsLabel: string; children: ReactNode; details: ReactNode;
}) {
  return <section className="pg-section" data-stage={stage} data-state={state} id={`inspect-${stage}`} aria-current={state === "active" ? "step" : undefined} aria-label={title}>
    <header className="pg-section-head">
      <h2 id={`inspect-${stage}-title`}>{heading}</h2>
      <span className="pg-stage-chip" data-stage={stage}>
        <i aria-hidden="true" />{title}
        {state !== "idle" ? <span className="pg-stage-state" role="status" aria-label={`${title}: ${STATE_SPOKEN[state]}`}>
          {state === "active" ? <LoaderCircle className="spin" size={14} aria-hidden="true" /> : state === "complete" ? <Check size={14} aria-hidden="true" /> : null}
          {STATE_LABEL[state]}
        </span> : null}
      </span>
      <p>{lede}</p>
    </header>
    <div className="pg-section-body">{children}</div>
    <button id={`inspect-${stage}-button`} type="button" className="pg-inspect" aria-expanded={expanded} aria-controls={`inspect-${stage}-details`} onClick={onInspect}>{detailsLabel}<ChevronDown size={16} aria-hidden="true" /></button>
    <div id={`inspect-${stage}-details`} className="pg-section-details" role="region" aria-labelledby={`inspect-${stage}-button`} hidden={!expanded}>{expanded ? details : null}</div>
  </section>;
}

export function InspectorDetail({ title, children }: { title: string; children: ReactNode }) {
  return <details className="inspector-detail"><summary>{title}</summary><div>{children}</div></details>;
}

function RetrieveDetails({ response, receipts, selectedId, onSelect }: {
  response?: SearchResponse; receipts: PipelineReceipt[]; selectedId?: string;
  onSelect: (id: string) => void;
}) {
  const diagnostics = response?.diagnostics;
  return <>
    {receipts.length ? <div className="inspector-search-plan">
      <h3>Searches Mosaic made</h3>
      <p>Each search can focus on a different need. Select one to follow its products through Retrieve and Rank.</p>
      <ol>{receipts.map((receipt, index) => <li key={receipt.id}>
        <button type="button" aria-pressed={receipt.id === selectedId} onClick={() => onSelect(receipt.id)}>Search {index + 1}: {receipt.response?.query ?? (receipt.error ? "Details unavailable" : "Loading…")}</button>
        {receipt.response ? <p className="inspector-note">{receipt.response.applied_filters.category_key ? String(receipt.response.applied_filters.category_key).replaceAll("-", " ") : "Across the catalog"}{typeof receipt.response.applied_filters.max_price_cents === "number" ? ` · Up to ${formatPriceCompact(receipt.response.applied_filters.max_price_cents)}` : ""}</p> : null}
      </li>)}</ol>
    </div> : null}
    <p className="inspector-note">Word search uses PostgreSQL’s built-in cover-density ranking, not BM25. Spelling and meaning search cover different ways a request can differ from the product text.</p>
    {response ? <InspectorDetail title="Request, filters & retrieval settings">
      <p>PostgreSQL checks the search filters with <code>mosaic_search.matches_filters</code>.</p>
      <CodeBlock label="Search record" code={JSON.stringify({ query: response.query, applied_filters: response.applied_filters, embedding_model_id: diagnostics?.embedding_model_id, retrieval_profile: diagnostics?.retrieval_profile, candidate_counts: diagnostics?.candidate_counts }, null, 2)} />
    </InspectorDetail> : <p className="inspector-waiting">Run Mosaic to see how each search helps.</p>}
    {response ? <PersistedRunDisclosures response={response} /> : null}
    {response ? <KeepInMind>Aurora saves each search with an ID. The saved record includes the <code>ef_search</code> and <code>iterative_scan</code> settings that decide whether a filtered HNSW scan keeps going.</KeepInMind> : null}
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
        <dl>{[["Keyword", product.signals?.fts.rank], ["Spelling", product.signals?.trigram.rank], ["Meaning", product.signals?.semantic.rank], ["RRF rank", product.signals?.pre_rerank_rank], ["Reranker", product.signals?.rerank_rank], ["Final rank", product.signals?.final_rank]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{rank(value as number | null | undefined)}</dd></div>)}</dl>
      </li>)}</ul>
    </div> : <p className="inspector-waiting">This search returned no products. No ranking is available.</p>}
    <InspectorDetail title="How the combined score is calculated"><RrfMath response={response} /></InspectorDetail>
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
  const leading = products[0]?.signals;
  const step = rerankStep(ablation);
  if (!response || !products.length) {
    return <>
      <p className="inspector-waiting">{!response ? (stopped ? "No ranking is available from this run." : "See how the order changes as Mosaic compares the products.") : "No products were returned, so no ranking is available."}</p>
      <KeepInMind>{LESSONS.rank}</KeepInMind>
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
          <span>The first result’s position before and after reranking.</span>
        </p> : null}
        <p>Reranking: <strong>{response.diagnostics?.rerank_status ?? "not reported"}</strong>. #1 is the highest rank. Combined and reranker scores use different scales; a higher score is better within each step.</p>
        {step ? <p>Measured on {ablation?.scored_query_count} graded searches: reranking moved the ordering score by {signedScore(step.mean_difference)} on average, {step.separable ? "more than" : "inside"} the spread of the per-search differences.</p> : null}
        <KeepInMind>{LESSONS.rank}</KeepInMind>
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
  const matches = receipts.flatMap((receipt, index) => {
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
const excerpt = (text: string) => (text.length > EXCERPT ? `${text.slice(0, EXCERPT).replace(/\s\S*$/, "")}…` : text);

/** The answer's sources, numbered as its prose cites them. */
function AnswerSources({ citations }: { citations: AgentCitation[] }) {
  if (!citations.length) return null;
  return <aside className="pg-sources" aria-labelledby="pg-sources-title">
    <h3 id="pg-sources-title">Sources</h3>
    <ol>{citations.map((citation) => <li key={`${citation.number}-${citation.evidence_id}`} value={citation.number}>
      <span className="pg-source-kind">{/review/i.test(citation.evidence_type) ? "Review" : "Listing"}</span>
      <strong>{citation.title}</strong>
      {/review/i.test(citation.evidence_type) && citation.quote ? <q>{excerpt(citation.quote)}</q> : null}
      <a href={`/api/evidence/${citation.evidence_id}`} target="_blank" rel="noreferrer">Record {citation.evidence_id} <ArrowUpRight size={12} aria-hidden="true" /></a>
    </li>)}</ol>
  </aside>;
}

function AgentSteps({ trace }: { trace: ToolTraceStep[] }) {
  if (!trace.length) return null;
  return <ol className="pg-steps" aria-label="Tool calls">{trace.map((step) => <li key={step.sequence} data-outcome={step.outcome}>
    <code>{step.tool}</code>{step.latency_ms == null ? null : <span>{step.latency_ms >= 1000 ? `${(step.latency_ms / 1000).toFixed(1)} s` : `${Math.round(step.latency_ms)} ms`}</span>}
  </li>)}</ol>;
}

function ReasonBody({ answer, partial, streamed, completed, running, active, hasSearch, failed, trace, renderSearchLink, multipleSearches }: {
  answer: AgentResponse | null; partial: AgentPartial | null; streamed: string; completed: boolean;
  running: boolean; active: boolean; hasSearch: boolean; failed: boolean; trace: ToolTraceStep[];
  renderSearchLink: (product: ProductSummary) => ReactNode; multipleSearches: boolean;
}) {
  const working = running && !completed && !failed;
  const status = !answer
    ? null
    : answer.outcome === "declined"
      ? "No recommendation: the available sources do not support a choice."
      : completed
        ? `${answer.recommendations.length ? `${answer.recommendations.length} ${answer.recommendations.length === 1 ? "recommendation" : "recommendations"}` : "Answer ready"} · ${answer.citations.length} ${answer.citations.length === 1 ? "source link" : "source links"}.`
        : "Writing Mosaic’s answer…";
  return <>
    {status ? <p className="pg-reason-summary" role="status">{status}</p> : null}
    <AgentSteps trace={trace} />
    {answer ? <>
      <div className="pg-answer-grid">
        <div className="inspector-answer pg-answer" aria-busy={!completed}>
          <ProductAnswer text={completed ? answer.answer : streamed} products={[]} complete={completed} />
        </div>
        {completed ? <AnswerSources citations={answer.citations} /> : null}
      </div>
      {completed && answer.recommendations.length ? <div className="pg-picks">
        <ProductAnswer text="" products={answer.recommendations} citations={answer.citations} complete renderSearchLink={renderSearchLink} />
        {multipleSearches ? <p className="inspector-note">Each pick links to its search; Rank shows one search at a time.</p> : null}
      </div> : null}
    </>
      : working && active ? <p className="inspector-waiting pg-reason-status" role="status"><LoaderCircle className="spin" size={20} aria-hidden="true" /><span>The agent is working. {partial?.candidates.length ? `Comparing ${partial.candidates.length} products and checking their sources.` : "It is checking products and sources."}</span></p>
      : <p className="inspector-waiting">{failed ? "The run stopped before the answer was ready. Open the activity log for details." : working ? "Mosaic will explain its picks after checking the products and sources." : hasSearch ? "This view contains the saved search results. Start a new run to let Mosaic search and make recommendations." : "Mosaic will compare the products and explain its picks, with links to the sources."}</p>}
    <KeepInMind>{LESSONS.reason}</KeepInMind>
  </>;
}

function ReasonEvidence({ answer, trace, failed }: { answer: AgentResponse | null; trace: ToolTraceStep[]; failed: boolean }) {
  const modelSteps = trace.filter((step) => step.origin === "model").length;
  const applicationSteps = trace.filter((step) => step.origin === "controller_fallback").length;
  const unreportedSteps = trace.length - modelSteps - applicationSteps;
  return <>
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
function RequestStage({ selectedId, carried, question, context, notice, runButton, onChoose }: {
  selectedId?: string; carried: boolean; question: string; context: string; notice?: string;
  runButton: ReactNode; onChoose: (id: string) => void;
}) {
  return <section className="pg-stage" aria-label="Alex’s request">
    <nav className="pg-requests" aria-label="Alex’s requests">{requestGroups.map((group) => <div key={group.label} role="group" aria-label={group.label}>
      {group.requests.map((request) => <button key={request.id} type="button" aria-pressed={!carried && selectedId === request.id} onClick={() => onChoose(request.id)}>{request.label}</button>)}
    </div>)}</nav>
    <MosaicLabsMasthead title={<>Behind a <span className="inspector-title-emphasis">better answer.</span></>} deck="Find eligible products. Establish their order. Check the sources to help Alex decide." />
    <div className="pg-query">
      <img className="pg-alex" src="/assets/images/mosaic/alex-headshot-v1.jpg" alt="Alex, Mosaic’s example shopper" width={44} height={44} />
      <div><h2>{question || "No request is available"}</h2><p>{context}</p></div>
      {runButton}
    </div>
    {notice ? <p className="pg-notice">{notice} Each search passes through Retrieve and Rank; Reason can request more searches before comparing the sources.</p> : null}
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

/** Whether the first result is the listing the lab is looking for. */
function missionNote(mission: MosaicLabMission | undefined, first: ProductSummary) {
  if (!mission?.target_display_name || !mission.target_product_ids.length) return undefined;
  return mission.target_product_ids.includes(first.product_id)
    ? { text: `This is the listing Alex meant: the ${mission.target_display_name}.`, missing: false }
    : { text: `Not the listing Alex meant. Lab ${coreMosaicLabs.indexOf(mission) + 1} is looking for the ${mission.target_display_name}.`, missing: true };
}

/** Between the request and the result: a saved search's status, a stopped run, and which search is shown. */
function RunNotes({ carried, started, running, error, receipts, selected, onRestore, onSelectSearch, labDetailsHref, labOutcome }: {
  carried: boolean; started: boolean; running: boolean; error: string; receipts: PipelineReceipt[];
  selected?: PipelineReceipt; onRestore: () => void; onSelectSearch: (id: string) => void; labDetailsHref: string;
  labOutcome: LabOutcome | null;
}) {
  return <div className="pg-run-notes">
    {labOutcome ? <LabOutcomeBanner outcome={labOutcome} /> : null}
    {carried ? <div className="inspector-saved-search pg-saved">
      <p>{started ? "This is a new run. Mosaic can change the search wording and choose different products." : "You’re viewing the saved Shop search. Starting a new run lets Mosaic search again; its picks may change."}</p>
      {started ? <button type="button" disabled={running} onClick={onRestore}>Back to saved Shop results <ArrowRight size={14} aria-hidden="true" /></button> : <Link className="inspector-lab-details-link" href={labDetailsHref}>Open lab details</Link>}
    </div> : null}
    {error ? <p className="inspector-error" role="alert">{error}</p> : null}
    {receipts.length > 1 ? <div className="inspector-search-selector pg-search-selector"><label htmlFor="inspector-search">Search shown in Retrieve and Rank</label><select id="inspector-search" value={selected?.id} onChange={(event) => onSelectSearch(event.target.value)}>{receipts.map((item, index) => <option key={item.id} value={item.id}>{index + 1}. {item.response?.query ?? "Reading search…"}</option>)}</select><p>Counts and ranks stay on the selected search. Choose another search here or follow a pick in Reason.</p></div> : null}
    {selected ? <p className="inspector-receipt pg-record">Search {receipts.indexOf(selected) + 1}{selected.response ? ` · ${selected.response.query}` : selected.error ? " · Could not load" : " · Reading…"}<span>Search record <code>{selected.id}</code></span></p> : null}
    {selected?.response ? <MethodReads response={selected.response} label={`Search ${receipts.indexOf(selected) + 1} reads it as`} /> : null}
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
  const [expanded, setExpanded] = useState<Record<Inspection, boolean>>(linkedInspection);
  const [highlightedId, setHighlightedId] = useState<number | null>(null);
  const [receiptId, setReceiptId] = useState<number | null>(null);
  useEffect(() => { setExpanded(linkedInspection()); setSelectedId(null); setHighlightedId(null); setReceiptId(null); }, [requestKey]);
  useEffect(() => {
    if (!expanded.rank || highlightedId == null) return;
    const target = document.getElementById(`ranked-product-${highlightedId}`);
    target?.scrollIntoView({ block: "nearest" });
    target?.focus({ preventScroll: true });
  }, [expanded.rank, highlightedId, selectedId, pipeline.receipts]);
  const selected = pipeline.receipts.find((item) => item.id === selectedId) ?? pipeline.receipts[0];
  const response = selected?.response;
  const products = response?.results ?? [];
  const images = productImageMap(products);
  const receiptProduct = products.find((product) => product.product_id === receiptId) ?? products[0];
  const labOutcome = missionOutcome(mission, response, readiness);
  const verdict: AgentVerdict = !pipeline.completed || !pipeline.answer || !products[0] ? null
    : pipeline.answer.outcome === "declined" ? "declined"
      : pipeline.answer.recommendations.some((pick) => pick.product_id === products[0].product_id) ? "picked" : "not-picked";
  const question = pipeline.savedResponse?.query ?? initialQuestion;
  const runFilters = (pipeline.savedResponse?.applied_filters ?? filters) as SearchFilters;
  const labDetailsParams = new URLSearchParams(params);
  labDetailsParams.set("view", "lab");
  const eligible = runFilters.category_key ? runFilters.category_key.replaceAll("-", " ") : "Whole catalog";
  const reset = () => { setSelectedId(null); setHighlightedId(null); setReceiptId(null); };
  const inspect = (stage: Inspection) => { setHighlightedId(null); setExpanded((value) => ({ ...value, [stage]: !value[stage] })); };
  const showReceipt = (productId: number) => { setReceiptId(productId); document.getElementById("inspect-rank")?.scrollIntoView({ behavior: "smooth", block: "start" }); };
  const renderSearchLink = (product: ProductSummary) => <ProductSearchLinks product={product} receipts={pipeline.receipts} running={pipeline.running} onSelect={(id, productId) => { setSelectedId(id); setHighlightedId(productId); setReceiptId(productId); setExpanded((value) => ({ ...value, rank: true })); }} />;
  const runLabel = pipeline.running
    ? pipeline.completed ? "Finishing up" : ({ retrieve: "Finding products", rank: "Comparing matches", reason: "Preparing the answer" })[pipeline.phase ?? "retrieve"]
    : pipeline.reading ? "Reading saved search" : pipeline.error ? "Try again" : pipeline.completed ? "Run again" : carriedEvent ? "Start a new run" : "Run Mosaic";
  const columnState = (stage: Inspection): ColumnState => {
    if (!pipeline.started) return "idle";
    if (pipeline.completed) return "complete";
    if (stage === pipeline.phase) return pipeline.error ? "failed" : pipeline.running ? "active" : "pending";
    const order: Inspection[] = ["retrieve", "rank", "reason"];
    if (pipeline.phase && order.indexOf(stage) < order.indexOf(pipeline.phase)) return "complete";
    return pipeline.error ? "blocked" : "pending";
  };
  const context = `Alex’s workspace${catalogCount ? ` · Catalog: ${catalogCount.toLocaleString()} products` : ""}${runFilters.category_key ? ` · Filter: ${runFilters.category_key.replaceAll("-", " ")}` : ""}`;
  const runButton = <MosaicRunButton type="button" className="inspector-play" label={runLabel} showLabel running={pipeline.running} disabled={pipeline.reading || !question || Boolean(carriedEvent && !pipeline.savedResponse)} onClick={() => { reset(); setExpanded({ retrieve: false, rank: false, reason: false }); void pipeline.play(question, runFilters); }} />;
  return <div className="page pg-a pipeline-inspector">
    <MosaicLabsTabs active="retrieval" />
    <RequestStage selectedId={selectedRequest?.id} carried={params.has("q") || Boolean(carriedEvent)} question={question} context={context} notice={!params.has("q") && !carriedEvent ? selectedRequest?.notice : undefined} runButton={runButton} onChoose={(id) => setParams(new URLSearchParams({ scene: id }))} />
    <p className="pg-run-status" role="status">{pipeline.reading ? "Reading the saved Shop search…" : pipeline.status || (carriedEvent ? "Saved Shop search" : "Ready to follow Alex’s request.")}</p>
    <RunNotes carried={Boolean(carriedEvent)} started={pipeline.started} running={pipeline.running} error={pipeline.error} receipts={pipeline.receipts} selected={selected} onRestore={() => { reset(); setExpanded({ retrieve: false, rank: false, reason: false }); pipeline.restoreSavedSearch(); }} onSelectSearch={(id) => { setSelectedId(id); setHighlightedId(null); setReceiptId(null); }} labDetailsHref={`/labs/retrieval?${labDetailsParams}`} labOutcome={labOutcome} />
    {products[0] ? <LeadResult product={products[0]} imageSrc={images.get(products[0].product_id)} verdict={verdict} missionNote={missionNote(mission, products[0])} onWhy={() => showReceipt(products[0].product_id)} /> : null}
    <StageSection stage="retrieve" state={columnState("retrieve")} title="Retrieve" heading="How it got here." lede="Filters decide what is eligible. Three methods find candidates, and fusion combines their positions." expanded={expanded.retrieve} onInspect={() => inspect("retrieve")} detailsLabel="Search details" details={<RetrieveDetails response={response} receipts={pipeline.receipts} selectedId={selected?.id} onSelect={(id) => { setSelectedId(id); setHighlightedId(null); setReceiptId(null); }} />}>
      <RetrievalPath response={response} catalogCount={catalogCount} eligible={eligible} />
      {!response && pipeline.error ? <p className="inspector-waiting">No search results are available from this run.</p> : null}
      <div className="pg-retrieve-notes"><KeepInMind>{LESSONS.retrieve}</KeepInMind><MethodComparison response={response} ablation={ablation} /></div>
    </StageSection>
    <StageSection stage="rank" state={columnState("rank")} title="Rank" heading="Why this position." lede="One line for each method that found the product, then the combined score and the reranker. Choose Receipt on any result to read its lines." expanded={expanded.rank} onInspect={() => inspect("rank")} detailsLabel="Why the order changed" details={<RankDetails response={response} images={images} highlightedId={highlightedId} />}>
      <RankBody response={response} receiptProduct={receiptProduct} ablation={ablation} stopped={Boolean(pipeline.error)} images={images} onSelect={showReceipt} />
    </StageSection>
    <StageSection stage="reason" state={columnState("reason")} title="Reason" heading="Then the agent compares and cites." lede="A Strands agent calls the same search as a tool, reads each pick’s evidence, and answers only from sources the application registered." expanded={expanded.reason} onInspect={() => inspect("reason")} detailsLabel="Steps and sources" details={<ReasonEvidence answer={pipeline.completed ? pipeline.answer : null} trace={pipeline.trace} failed={Boolean(pipeline.error)} />}>
      <ReasonBody answer={pipeline.answer} partial={pipeline.partial} streamed={pipeline.streamed} completed={pipeline.completed} running={pipeline.running} active={pipeline.phase === "reason"} hasSearch={Boolean(response)} failed={Boolean(pipeline.error)} trace={pipeline.completed ? pipeline.trace : []} renderSearchLink={renderSearchLink} multipleSearches={pipeline.receipts.length > 1} />
      {pipeline.runId ? <p className="pg-run-id">Agent record <code>{pipeline.runId}</code></p> : null}
    </StageSection>
    <aside className="inspector-scale-link inspector-takeaway pg-takeaway">
      <div>
        <h2>Use what you built in your own agent</h2>
        <p>Reuse filtered search, ranking explanations and product evidence. The implementation guide maps the code and checks; the skill provides calling instructions for a running Mosaic service.</p>
      </div>
      <div className="inspector-takeaway-actions">
        <a href="/api/builder-package" download>Adapt the implementation <ArrowRight size={18} aria-hidden="true" /></a>
        <a href="/api/skill-package" download>Download the skill <ArrowRight size={18} aria-hidden="true" /></a>
      </div>
      <nav aria-label="Optional explorations"><span>Optional</span><Link href="/labs/examples?case=saved-headphones">Compare product details</Link><Link href="/mosaic-labs/hnsw">Explore scale & HNSW</Link><Link href="/mosaic-labs/memory">Explore session & memory</Link></nav>
    </aside>
  </div>;
}

/** A saved Shop search stays in the pipeline view; lab details are an explicit destination. */
export function PlaygroundPage() {
  const [params] = useSearchParams();
  const shopRequest = Boolean(forwardedSearchEvent(params) || params.get("q")?.trim());
  const labDetails = params.get("view") === "lab" || params.has("run") || (params.has("example") && !shopRequest);
  return labDetails ? <RetrievalLabPage /> : <PipelineInspector />;
}
