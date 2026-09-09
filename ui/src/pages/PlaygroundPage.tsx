import { ArrowRight, Check, ChevronDown, LoaderCircle, Play, Sparkles } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "wouter";
import { api } from "../api";
import { CodeBlock } from "../components/CodeBlock";
import { MosaicLabsTabs } from "../components/MosaicLabsTabs";
import { MosaicLabsMasthead } from "../components/MosaicLabsMasthead";
import { PersistedRunDisclosures, RrfMath } from "../components/RetrievalProvenance";
import { KeepInMind } from "../components/KeepInMind";
import { ProductAnswer } from "../components/ProductAnswer";
import { RankOverview, RetrieveOverview } from "../components/PipelineOverview";
import { formatPriceCompact } from "../format";
import { mosaicLabManifest, pipelineRequests } from "../labMissions";
import { SourceComparison } from "../components/SourceComparison";
import { productImageMap } from "../media";
import { forwardedSearchEvent, forwardedSearchFilters, useSearchParams } from "../navigation";
import type { AgentPartial, AgentResponse, ProductSummary, ReadinessResponse, SearchFilters, SearchResponse, ToolTraceStep } from "../types";
import { usePipelineRun, type PipelineReceipt } from "../usePipelineRun";
import { RetrievalLabPage } from "./RetrievalLabPage";
import "../inspector.css";

const requests = pipelineRequests;
/** Two rows of at most four, so no decision point shows more choices than a reader holds at once. */
const primaryRequestIds = new Set(mosaicLabManifest.playground.requests.map((request) => request.id));
const requestGroups = [
  { label: "Alex’s needs", requests: requests.filter((request) => primaryRequestIds.has(request.id)) },
  { label: "Agent examples", requests: requests.filter((request) => !primaryRequestIds.has(request.id)) },
].filter((group) => group.requests.length);
type Inspection = "retrieve" | "rank" | "reason";
type ColumnState = "idle" | "pending" | "active" | "complete" | "failed";

function PipelineColumn({ stage, state, number, title, description, expanded, onInspect, children, details }: {
  stage: Inspection; number: string; title: string; description: string;
  state: ColumnState;
  expanded: boolean; onInspect: () => void; children: ReactNode; details: ReactNode;
}) {
  return <section className="inspector-column" data-state={state} id={`inspect-${stage}`} aria-current={state === "active" ? "step" : undefined} aria-labelledby={`inspect-${stage}-title`}>
    <header><span className="inspector-step-number">{number}</span><h2 id={`inspect-${stage}-title`}>{title}</h2>{state !== "idle" ? <span className="inspector-stage-state" role="status" aria-label={`${title}: ${state === "active" ? "working" : state === "complete" ? "done" : state === "failed" ? "stopped" : "waiting"}`}>{state === "active" ? <LoaderCircle className="spin" size={15} aria-hidden="true" /> : state === "complete" ? <Check size={15} aria-hidden="true" /> : null}{state === "active" ? "Working" : state === "complete" ? "Done" : state === "failed" ? "Stopped" : "Waiting"}</span> : null}<p>{description}</p></header>
    <div className="inspector-column-body">{children}</div>
    <button id={`inspect-${stage}-button`} type="button" className="inspector-inspect-button" aria-expanded={expanded} aria-controls={`inspect-${stage}-details`} onClick={onInspect}>{stage === "retrieve" ? "Search details" : stage === "rank" ? "Why the order changed" : "Answer and sources"}<ChevronDown size={16} aria-hidden="true" /></button>
    <div id={`inspect-${stage}-details`} className="inspector-column-details" role="region" aria-labelledby={`inspect-${stage}-button`} hidden={!expanded}>{expanded ? details : null}</div>
  </section>;
}

export function InspectorSection({ id, number, title, description, children }: {
  id: string; number: string; title: string; description: string; children: ReactNode;
}) {
  return <section className="inspector-section" id={id} aria-labelledby={`${id}-title`}>
    <header><span className="inspector-step-number">{number}</span><h2 id={`${id}-title`}>{title}</h2><p>{description}</p></header>
    <div className="inspector-section-body">{children}</div>
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
  const counts = diagnostics?.candidate_counts;
  const arms = [
    { name: "Keyword", mechanism: "tsvector · GIN", purpose: "Words and model names that appear in the product text.", key: "fts_in_pool" },
    { name: "Close spelling", mechanism: "pg_trgm · GIN", purpose: "Character overlap recovers misspellings and small variations.", key: "trigram_in_pool" },
    { name: "Meaning", mechanism: "Cohere Embed v4 · pgvector · HNSW", purpose: "Vector similarity finds intent beyond shared words.", key: "semantic_in_pool" },
  ];
  return <>
    {receipts.length ? <div className="inspector-search-plan">
      <h3>Searches Mosaic made</h3>
      <p>Each search can focus on a different need. Select one to follow its products through Retrieve and Rank.</p>
      <ol>{receipts.map((receipt, index) => <li key={receipt.id}>
        <button type="button" aria-pressed={receipt.id === selectedId} onClick={() => onSelect(receipt.id)}>Search {index + 1}: {receipt.response?.query ?? (receipt.error ? "Details unavailable" : "Loading…")}</button>
        {receipt.response ? <p className="inspector-note">{receipt.response.applied_filters.category_key ? String(receipt.response.applied_filters.category_key).replaceAll("-", " ") : "Across the catalog"}{typeof receipt.response.applied_filters.max_price_cents === "number" ? ` · Up to ${formatPriceCompact(receipt.response.applied_filters.max_price_cents)}` : ""}</p> : null}
      </li>)}</ol>
    </div> : null}
    <div className="inspector-channel-head"><span>Three ways to find matching products</span><span>Matches found</span></div>
    <div className="inspector-channels">{arms.map((arm) => <div key={arm.name}>
      <div><h3>{arm.name}</h3><p>{arm.purpose}</p><span className="inspector-mechanism">{arm.mechanism}</span></div>
      <strong>{counts?.[arm.key] ?? "—"}</strong>
    </div>)}</div>
    <p className="inspector-note">A product can match in more than one way, so these counts can overlap.</p>
    {response ? <InspectorDetail title="Request, filters & retrieval settings">
      <p>PostgreSQL checks the search filters with <code>mosaic_search.matches_filters</code>.</p>
      <CodeBlock label="Search record" code={JSON.stringify({ query: response.query, applied_filters: response.applied_filters, embedding_model_id: diagnostics?.embedding_model_id, retrieval_profile: diagnostics?.retrieval_profile, candidate_counts: counts }, null, 2)} />
    </InspectorDetail> : <p className="inspector-waiting">Play the pipeline to see how each search helps.</p>}
    {response ? <PersistedRunDisclosures response={response} /> : null}
    {response ? <KeepInMind>Every search is a write: this run is saved as a receipt with an id, and its search record above carries the <code>ef_search</code> and <code>iterative_scan</code> settings that decide whether a filtered HNSW scan keeps going.</KeepInMind> : null}
  </>;
}

function RankDetails({ response, highlightedId }: { response?: SearchResponse; highlightedId: number | null }) {
  const products = response?.results ?? [];
  const images = productImageMap(products);
  const rank = (value: number | null | undefined) => value == null ? "—" : `#${value}`;
  const leading = products[0];
  const changed = leading?.signals && leading.signals.pre_rerank_rank !== leading.signals.final_rank;
  return <>
    <div className="inspector-rank-flow"><span>Search results</span><ArrowRight size={16} aria-hidden="true" /><span>RRF fusion</span><ArrowRight size={16} aria-hidden="true" /><span>Cohere Rerank</span><ArrowRight size={16} aria-hidden="true" /><span>Final order</span></div>
    <p>RRF combines the search results. Cohere Rerank then checks how well each product fits the request. Any extra ranking rules are listed below.</p>
    {response ? <>
      {changed ? <p className="inspector-rank-change"><strong>{rank(leading.signals!.pre_rerank_rank)} before rerank <ArrowRight size={18} aria-hidden="true" /> {rank(leading.signals!.final_rank)} in the final order</strong><span>{leading.title}</span></p> : null}
      <p className="inspector-note">Reranker: <strong>{response.diagnostics?.rerank_status ?? "not reported"}</strong>{response.diagnostics?.rerank_model_id ? ` · ${response.diagnostics.rerank_model_id}` : ""}. Showing the products returned by this search.</p>
      {products.length ? <div role="region" aria-label="Product ranking details">
        <ul className="inspector-product-ranks">{products.map((product) => <li key={product.product_id} id={`ranked-product-${product.product_id}`} tabIndex={-1} className={highlightedId === product.product_id ? "inspector-highlighted-product" : undefined}>
          <Link href={`/products/${product.product_id}`} className="inspector-product"><img src={images.get(product.product_id)} alt="" width={56} height={48} /><span>{product.title}<small>{formatPriceCompact(product.price_cents, product.currency)}</small></span></Link>
          <dl>{[["Keyword", product.signals?.fts.rank], ["Spelling", product.signals?.trigram.rank], ["Meaning", product.signals?.semantic.rank], ["RRF rank", product.signals?.pre_rerank_rank], ["Reranker", product.signals?.rerank_rank], ["Final rank", product.signals?.final_rank]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{rank(value as number | null | undefined)}</dd></div>)}</dl>
        </li>)}</ul>
      </div> : <p className="inspector-waiting">This search returned no products. No ranking is available.</p>}
      <InspectorDetail title="How the combined score is calculated"><RrfMath response={response} /></InspectorDetail>
      <InspectorDetail title="Ranking rules and time taken"><CodeBlock label="Ranking details" code={JSON.stringify({ ranking_policy: response.diagnostics?.ranking_policy, stage_timings_ms: response.diagnostics?.stage_timings_ms, total_latency_ms: response.diagnostics?.total_latency_ms }, null, 2)} /></InspectorDetail>
    </> : <p className="inspector-waiting">The same products will appear here with their positions at each ranking step.</p>}
  </>;
}

function ReasonAnswer({ answer, streamed, completed, renderSearchLink }: { answer: AgentResponse; streamed: string; completed: boolean; renderSearchLink: (product: ProductSummary) => ReactNode }) {
  const text = completed ? answer.answer : streamed;
  return <div className="inspector-answer" aria-busy={!completed}>
    <p className="inspector-answer-status" role="status"><Sparkles size={17} aria-hidden="true" />{answer.outcome === "declined" ? "No recommendation" : completed ? "Mosaic’s answer" : "Writing Mosaic’s answer…"}</p>
    <div className="inspector-answer-prose"><ProductAnswer text={text} products={answer.recommendations} citations={answer.citations} complete={completed} renderSearchLink={renderSearchLink} /></div>
  </div>;
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
  return <div className="inspector-product-search-links">{matches.map(({ receipt, index, rank }) => <button key={receipt.id} type="button" aria-label={`${product.title}: show Search ${index + 1}${rank == null ? "" : `, rank ${rank}`}`} onClick={() => onSelect(receipt.id, product.product_id)}>Search {index + 1}{rank == null ? "" : ` · #${rank} in Rank`} <ArrowRight size={13} aria-hidden="true" /></button>)}</div>;
}

function ReasonOverview({ answer, partial, streamed, completed, running, active, hasSearch, failed, renderSearchLink, multipleSearches }: {
  answer: AgentResponse | null; partial: AgentPartial | null; streamed: string; completed: boolean;
  running: boolean; active: boolean; hasSearch: boolean; failed: boolean;
  renderSearchLink: (product: ProductSummary) => ReactNode; multipleSearches: boolean;
}) {
  const working = running && !completed && !failed;
  return <>
    {answer ? <ReasonAnswer answer={answer} streamed={streamed} completed={completed} renderSearchLink={renderSearchLink} />
      : working && active ? <p className="inspector-waiting inspector-reason-status" role="status"><LoaderCircle className="spin" size={20} aria-hidden="true" /><span>The agent is working. {partial?.candidates.length ? `Comparing ${partial.candidates.length} products and checking their sources.` : "It is checking products and sources."}</span></p>
      : <p className="inspector-waiting">{failed ? "The run stopped before the answer was ready. Open the activity log for details." : working ? "Mosaic will explain its picks after checking the products and sources." : hasSearch ? "This view contains the saved search results. Start a new run to let Mosaic search and make recommendations." : "Mosaic will compare the products and explain its picks, with links to the sources."}</p>}
    {answer && completed && multipleSearches ? <p className="inspector-note">Each pick links to its search; Rank shows one search at a time.</p> : null}
    <KeepInMind>Evidence the model has read is not citable until the application registers it. The model requests tools; the application decides what runs, and the agent never writes SQL.</KeepInMind>
  </>;
}

function ReasonEvidence({ answer, trace }: { answer: AgentResponse | null; trace: ToolTraceStep[] }) {
  return <>
    {answer ? <p className="inspector-note">Source numbers in the answer identify evidence, not recommendation ranks.</p> : <p className="inspector-note">The answer is not ready yet. You can see the steps taken so far below.</p>}
    {answer?.recommendations.length ? <InspectorDetail title="Compare the sources"><SourceComparison answer={answer} /></InspectorDetail> : null}
    {answer?.citations.length ? <InspectorDetail title={`Sources for this answer · ${answer.citations.length} citations`}>
      <ol className="inspector-citations">{answer.citations.map((citation) => <li key={`${citation.number}-${citation.evidence_id}`} value={citation.number}>
        <strong>{citation.title}</strong><blockquote>{citation.quote}</blockquote><a href={`/api/evidence/${citation.evidence_id}`} target="_blank" rel="noreferrer">Read evidence record {citation.evidence_id}</a><small>Revision {citation.revision} · {citation.evidence_type}</small>
      </li>)}</ol>
    </InspectorDetail> : null}
    <InspectorDetail title={`Activity log${trace.length ? ` · ${trace.length} calls` : ""}`}>
      {trace.length ? <ol className="inspector-trace">{trace.map((step) => <li key={step.sequence}>
        <header><code>{step.tool}</code><span>{step.outcome}{step.latency_ms == null ? "" : ` · ${Math.round(step.latency_ms)} ms`}</span></header>
        <p>{step.detail}</p><CodeBlock label="Step details" code={JSON.stringify({ arguments: step.arguments, retrieval_run_id: step.retrieval_run_id, result_count: step.result_count, origin: step.origin }, null, 2)} />
      </li>)}</ol> : <p>No tool calls have been recorded in this view.</p>}
    </InspectorDetail>
    <p className="inspector-note">Mosaic checks the product details and sources before making a recommendation.</p>
  </>;
}

function PipelineInspector() {
  const [params, setParams] = useSearchParams();
  const carriedEvent = forwardedSearchEvent(params);
  const requestKey = params.toString();
  const selectedRequest = requests.find((request) => request.id === (params.get("scene") ?? mosaicLabManifest.playground.default_request));
  const initialQuestion = params.get("q") || selectedRequest?.query || "";
  const filters = (params.has("q") ? forwardedSearchFilters(params) : selectedRequest?.filters ?? {}) as SearchFilters;
  const pipeline = usePipelineRun(`${requestKey}:${initialQuestion}`, carriedEvent);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<Inspection, boolean>>({ retrieve: false, rank: false, reason: false });
  const [highlightedId, setHighlightedId] = useState<number | null>(null);
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  useEffect(() => { setExpanded({ retrieve: false, rank: false, reason: false }); setSelectedId(null); setHighlightedId(null); }, [requestKey]);
  useEffect(() => {
    if (!expanded.rank || highlightedId == null) return;
    const target = document.getElementById(`ranked-product-${highlightedId}`);
    target?.scrollIntoView({ block: "nearest" });
    target?.focus({ preventScroll: true });
  }, [expanded.rank, highlightedId, selectedId, pipeline.receipts]);
  useEffect(() => {
    let active = true;
    void api.readiness().then((value) => { if (active) setReadiness(value); }).catch(() => {});
    return () => { active = false; };
  }, []);
  const selected = pipeline.receipts.find((item) => item.id === selectedId) ?? pipeline.receipts[0];
  const response = selected?.response;
  const question = pipeline.savedResponse?.query ?? initialQuestion;
  const runFilters = (pipeline.savedResponse?.applied_filters ?? filters) as SearchFilters;
  const inspect = (stage: Inspection) => { setHighlightedId(null); setExpanded((value) => ({ ...value, [stage]: !value[stage] })); };
  const renderSearchLink = (product: ProductSummary) => <ProductSearchLinks product={product} receipts={pipeline.receipts} running={pipeline.running} onSelect={(id, productId) => { setSelectedId(id); setHighlightedId(productId); setExpanded((value) => ({ ...value, rank: true })); }} />;
  const count = readiness?.database.product_count;
  const columnState = (stage: Inspection): ColumnState => {
    if (!pipeline.started) return "idle";
    if (pipeline.completed) return "complete";
    if (stage === pipeline.phase) return pipeline.error ? "failed" : pipeline.running ? "active" : "pending";
    const order: Inspection[] = ["retrieve", "rank", "reason"];
    return pipeline.phase && order.indexOf(stage) < order.indexOf(pipeline.phase) ? "complete" : "pending";
  };
  return <div className="page pipeline-inspector pipeline-overview">
    <MosaicLabsTabs active="retrieval" />
    <div className="inspector-intro"><MosaicLabsMasthead title="Behind a better answer." deck="Follow Alex’s request. See what Mosaic finds, how the order changes, and why it recommends each product." /></div>
    <nav className="inspector-request-choices" aria-label="Alex’s requests">{requestGroups.map((group) => <div key={group.label} role="group" aria-label={group.label}><span className="inspector-request-group-label" aria-hidden="true">{group.label}</span>{group.requests.map((request) => <button key={request.id} type="button" aria-pressed={!params.has("q") && selectedRequest?.id === request.id} onClick={() => setParams(new URLSearchParams({ scene: request.id }))}>{request.label}</button>)}</div>)}</nav>
    <section className="inspector-request" aria-label="Pipeline request">
      <img className="inspector-alex" src="/assets/images/mosaic/alex-headshot-v1.jpg" alt="Alex, Mosaic’s example shopper" width={128} height={128} />
      <div><h2>{question || "No request is available"}</h2><p>Alex’s workspace{count ? ` · Searching ${count.toLocaleString()} products` : ""}{runFilters.category_key ? ` · Filter: ${runFilters.category_key.replaceAll("-", " ")}` : ""}</p></div>
      <button type="button" className="inspector-play" disabled={pipeline.running || pipeline.reading || !question || Boolean(carriedEvent && !pipeline.savedResponse)} aria-busy={pipeline.running} onClick={() => { setSelectedId(null); setHighlightedId(null); setExpanded({ retrieve: false, rank: false, reason: false }); void pipeline.play(question, runFilters); }}><Play size={18} fill="currentColor" aria-hidden="true" />{pipeline.running ? "Playing pipeline…" : carriedEvent ? "Start a new run" : "Play pipeline"}</button>
    </section>
    <div className="inspector-context-bar">
      <details className="inspector-about-request"><summary>About Alex’s request</summary><p>Alex is a software engineer building a home office for coding, calls and focused work.</p>{!params.has("q") && selectedRequest ? <p>{selectedRequest.notice}</p> : null}<Link href="/catalog">Choose another request in Shop <ArrowRight size={14} aria-hidden="true" /></Link></details>
      <div className="inspector-run-status" role="status">{pipeline.reading ? "Reading the saved Shop search…" : pipeline.status || (carriedEvent ? "Saved Shop search" : "Ready when you are. See how Mosaic finds, ranks and recommends products for Alex.")}</div>
    </div>
    {carriedEvent ? <div className="inspector-saved-search"><p>{pipeline.started ? "This is a new run. Mosaic can change the search wording and choose different products." : "You’re viewing the saved Shop search. Starting a new run lets Mosaic search again; its picks may change."}</p>{pipeline.started ? <button type="button" disabled={pipeline.running} onClick={() => { setSelectedId(null); setHighlightedId(null); setExpanded({ retrieve: false, rank: false, reason: false }); pipeline.restoreSavedSearch(); }}>Back to saved Shop results <ArrowRight size={14} aria-hidden="true" /></button> : null}</div> : null}
    {pipeline.error ? <p className="inspector-error" role="alert">{pipeline.error}</p> : null}
    {pipeline.receipts.length > 1 ? <div className="inspector-search-selector"><label htmlFor="inspector-search">Search shown in Retrieve and Rank</label><select id="inspector-search" value={selected?.id} onChange={(event) => { setSelectedId(event.target.value); setHighlightedId(null); }}>{pipeline.receipts.map((item, index) => <option key={item.id} value={item.id}>{index + 1}. {item.response?.query ?? "Reading search…"}</option>)}</select><p>Counts and ranks stay on the selected search. Choose another search here or follow a pick in Reason.</p></div> : null}
    {selected ? <p className="inspector-receipt">Search {pipeline.receipts.indexOf(selected) + 1}{response ? ` · ${response.query}` : selected.error ? " · Could not load" : " · Reading…"}<span>Search record <code>{selected.id}</code></span></p> : null}
    {selected?.error ? <p className="inspector-error" role="alert">This record could not be read: {selected.error} {carriedEvent && !pipeline.started ? "Reload this page to retry the saved Shop search." : "Start a new run to try again."}</p> : null}
    <div className="inspector-pipeline-grid">
      <PipelineColumn stage="retrieve" state={columnState("retrieve")} number="01" title="Retrieve" description="Find products through words, spelling and meaning." expanded={expanded.retrieve} onInspect={() => inspect("retrieve")} details={<RetrieveDetails response={response} receipts={pipeline.receipts} selectedId={selected?.id} onSelect={(id) => { setSelectedId(id); setHighlightedId(null); }} />}><RetrieveOverview response={response} /></PipelineColumn>
      <PipelineColumn stage="rank" state={columnState("rank")} number="02" title="Rank" description="See which products rise to the top." expanded={expanded.rank} onInspect={() => inspect("rank")} details={<RankDetails response={response} highlightedId={highlightedId} />}><RankOverview response={response} /></PipelineColumn>
      <PipelineColumn stage="reason" state={columnState("reason")} number="03" title="Reason" description="Compare the products and explain the choice." expanded={expanded.reason} onInspect={() => inspect("reason")} details={<><ReasonEvidence answer={pipeline.completed ? pipeline.answer : null} trace={pipeline.trace} />{pipeline.runId ? <p className="inspector-receipt">Agent record <code>{pipeline.runId}</code></p> : null}</>}><ReasonOverview answer={pipeline.answer} partial={pipeline.partial} streamed={pipeline.streamed} completed={pipeline.completed} running={pipeline.running} active={pipeline.phase === "reason"} hasSearch={Boolean(response)} failed={Boolean(pipeline.error)} renderSearchLink={renderSearchLink} multipleSearches={pipeline.receipts.length > 1} /></PipelineColumn>
    </div>
    <aside className="inspector-scale-link"><div><h2>And when the catalog grows?</h2><p>Explore how HNSW finds similar products quickly, and how filters affect the search.</p></div><Link href="/mosaic-labs/hnsw">Explore scale & HNSW <ArrowRight size={18} aria-hidden="true" /></Link></aside>
  </div>;
}

/** Keep existing guide and proof deep links operational while the main surface inspects runs. */
export function PlaygroundPage() {
  const [params] = useSearchParams();
  return params.has("example") || params.get("view") === "lab" || params.has("run") ? <RetrievalLabPage /> : <PipelineInspector />;
}
