import { ArrowRight, Play, Sparkles } from "lucide-react";
import { useReducedMotion } from "motion/react";
import { useEffect, useState, type ReactNode } from "react";
import Markdown from "react-markdown";
import { Link } from "wouter";
import { api } from "../api";
import { CodeBlock } from "../components/CodeBlock";
import { MosaicLabsTabs } from "../components/MosaicLabsTabs";
import { MosaicLabsMasthead } from "../components/MosaicLabsMasthead";
import { RrfMath } from "../components/RetrievalProvenance";
import { ReasonProducts } from "../components/ReasonProducts";
import { formatPriceCompact } from "../format";
import { mosaicLabManifest } from "../labMissions";
import { productImageMap } from "../media";
import { forwardedSearchEvent, forwardedSearchFilters, useSearchParams } from "../navigation";
import type { AgentPartial, AgentResponse, ReadinessResponse, SearchFilters, SearchResponse, ToolTraceStep } from "../types";
import { usePipelineRun } from "../usePipelineRun";
import { useTypewriterReveal } from "../useTypewriterReveal";
import { RetrievalLabPage } from "./RetrievalLabPage";
import "../inspector.css";

const requests = mosaicLabManifest.playground.requests;

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

function RetrieveDetails({ response }: { response?: SearchResponse }) {
  const diagnostics = response?.diagnostics;
  const counts = diagnostics?.candidate_counts;
  const arms = [
    { name: "Keyword", mechanism: "tsvector · GIN", purpose: "Words and model names that appear in the product text.", key: "fts_in_pool" },
    { name: "Close spelling", mechanism: "pg_trgm · GIN", purpose: "Character overlap recovers misspellings and small variations.", key: "trigram_in_pool" },
    { name: "Meaning", mechanism: "Cohere Embed v4 · pgvector · HNSW", purpose: "Vector similarity finds intent beyond shared words.", key: "semantic_in_pool" },
  ];
  return <>
    <div className="inspector-channel-head"><span>Three ways into the same candidate pool</span><span>In fused pool</span></div>
    <div className="inspector-channels">{arms.map((arm) => <div key={arm.name}>
      <div><h3>{arm.name}</h3><p>{arm.purpose}</p><span className="inspector-mechanism">{arm.mechanism}</span></div>
      <strong>{counts?.[arm.key] ?? "—"}</strong>
    </div>)}</div>
    <p className="inspector-note">A product can come from several arms. These counts overlap; they are not added together.</p>
    {response ? <InspectorDetail title="Request, filters & retrieval settings">
      <p>PostgreSQL applies the structured eligibility rules through <code>mosaic_search.matches_filters</code>.</p>
      <CodeBlock label="Search record" code={JSON.stringify({ query: response.query, applied_filters: response.applied_filters, embedding_model_id: diagnostics?.embedding_model_id, retrieval_profile: diagnostics?.retrieval_profile, candidate_counts: counts }, null, 2)} />
    </InspectorDetail> : <p className="inspector-waiting">Play the pipeline to see which arms actually contribute.</p>}
  </>;
}

function RankDetails({ response }: { response?: SearchResponse }) {
  const products = response?.results ?? [];
  const images = productImageMap(products);
  const rank = (value: number | null | undefined) => value == null ? "—" : `#${value}`;
  const leading = products[0];
  const changed = leading?.signals && leading.signals.pre_rerank_rank !== leading.signals.final_rank;
  return <>
    <div className="inspector-rank-flow"><span>Arm ranks</span><ArrowRight size={16} aria-hidden="true" /><span>RRF fusion</span><ArrowRight size={16} aria-hidden="true" /><span>Cohere Rerank</span><ArrowRight size={16} aria-hidden="true" /><span>Final order</span></div>
    <p>Reciprocal rank fusion combines positions from different arms. The reranker evaluates query–product relevance; the final policy applies any reported boosts.</p>
    {response ? <>
      {changed ? <p className="inspector-rank-change"><strong>{rank(leading.signals!.pre_rerank_rank)} before rerank <ArrowRight size={18} aria-hidden="true" /> {rank(leading.signals!.final_rank)} in the final order</strong><span>{leading.title}</span></p> : null}
      <p className="inspector-note">Reranker: <strong>{response.diagnostics?.rerank_status ?? "not reported"}</strong>{response.diagnostics?.rerank_model_id ? ` · ${response.diagnostics.rerank_model_id}` : ""}. Only the returned window is shown.</p>
      {products.length ? <div className="inspector-table-scroll" role="region" aria-label="Product ranking details" tabIndex={0}>
        <table className="inspector-table"><thead><tr><th>Product</th><th>Keyword</th><th>Spelling</th><th>Vector</th><th>Before rerank</th><th>Cohere</th><th>Final</th></tr></thead>
          <tbody>{products.map((product) => <tr key={product.product_id}>
            <th scope="row"><Link href={`/products/${product.product_id}`} className="inspector-product"><img src={images.get(product.product_id)} alt="" width={56} height={48} /><span>{product.title}<small>{formatPriceCompact(product.price_cents, product.currency)}</small></span></Link></th>
            <td>{rank(product.signals?.fts.rank)}</td><td>{rank(product.signals?.trigram.rank)}</td><td>{rank(product.signals?.semantic.rank)}</td><td>{rank(product.signals?.pre_rerank_rank)}</td><td>{rank(product.signals?.rerank_rank)}</td><td>{rank(product.signals?.final_rank)}</td>
          </tr>)}</tbody></table>
      </div> : <p className="inspector-waiting">This search returned no products. No ranking is available.</p>}
      <InspectorDetail title="Inspect the RRF arithmetic"><RrfMath response={response} /></InspectorDetail>
      <InspectorDetail title="Recorded ranking policy & timings"><CodeBlock label="Ranking diagnostics" code={JSON.stringify({ ranking_policy: response.diagnostics?.ranking_policy, stage_timings_ms: response.diagnostics?.stage_timings_ms, total_latency_ms: response.diagnostics?.total_latency_ms }, null, 2)} /></InspectorDetail>
    </> : <p className="inspector-waiting">The same products will appear here with their positions at each ranking step.</p>}
  </>;
}

function ReasonAnswer({ answer, streamed, completed }: { answer: AgentResponse; streamed: string; completed: boolean }) {
  const reduceMotion = useReducedMotion();
  const reveal = useTypewriterReveal(streamed || answer.answer, !completed, true, reduceMotion ?? false);
  const settled = completed && reveal.done;
  return <div className="inspector-answer" aria-busy={!settled}>
    <p className="inspector-answer-status" role="status"><Sparkles size={17} aria-hidden="true" />{answer.outcome === "declined" ? "No recommendation" : settled ? "Mosaic’s answer" : "Revealing Mosaic’s answer…"}</p>
    <div className="inspector-answer-prose"><Markdown>{reveal.text}</Markdown></div>
  </div>;
}

function ReasonDetails({ answer, partial, streamed, completed, trace, running, hasSearch, failed }: {
  answer: AgentResponse | null; partial: AgentPartial | null; streamed: string; completed: boolean;
  trace: ToolTraceStep[]; running: boolean; hasSearch: boolean; failed: boolean;
}) {
  const products = answer?.recommendations ?? partial?.candidates.slice(0, 3) ?? [];
  const candidateCount = partial?.candidates.length ?? 0;
  return <>
    <ReasonProducts products={products} citations={answer?.citations} title={answer ? "Mosaic’s picks for Alex" : "Under consideration"} description={answer ? "The products behind this answer. Open a product to explore its details." : `Showing ${products.length} of ${candidateCount} retrieved products. ${failed ? "The run stopped before a final recommendation." : "Mosaic is checking the evidence before making a recommendation."}`} />
    {answer ? <ReasonAnswer answer={answer} streamed={streamed} completed={completed} />
      : <p className="inspector-waiting">{running ? "The agent is working. Tool receipts appear as they arrive." : failed ? "The run stopped before a completed answer. Inspect the tool trace to locate the failure." : hasSearch ? "This saved Shop search has no agent answer attached. Play pipeline starts a new, complete agent run for this request." : "The agent will use retrieved products and source evidence to produce a cited answer."}</p>}
    {answer?.citations.length ? <InspectorDetail title={`Sources behind the answer · ${answer.citations.length} citations`}>
      <ol className="inspector-citations">{answer.citations.map((citation) => <li key={`${citation.number}-${citation.evidence_id}`} value={citation.number}>
        <strong>{citation.title}</strong><blockquote>{citation.quote}</blockquote><a href={`/api/evidence/${citation.evidence_id}`} target="_blank" rel="noreferrer">Read evidence record {citation.evidence_id}</a><small>Revision {citation.revision} · {citation.evidence_type}</small>
      </li>)}</ol>
    </InspectorDetail> : null}
    <InspectorDetail title={`Tool trace${trace.length ? ` · ${trace.length} calls` : ""}`}>
      {trace.length ? <ol className="inspector-trace">{trace.map((step) => <li key={step.sequence}>
        <header><code>{step.tool}</code><span>{step.outcome}{step.latency_ms == null ? "" : ` · ${Math.round(step.latency_ms)} ms`}</span></header>
        <p>{step.detail}</p><CodeBlock label="Tool receipt" code={JSON.stringify({ arguments: step.arguments, retrieval_run_id: step.retrieval_run_id, result_count: step.result_count, origin: step.origin }, null, 2)} />
      </li>)}</ol> : <p>No tool calls have been recorded in this view.</p>}
    </InspectorDetail>
    <p className="inspector-note">The agent calls tools; PostgreSQL holds product and evidence records. A successful evidence lookup and an authorized, cited answer are separate steps.</p>
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
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  useEffect(() => {
    let active = true;
    void api.readiness().then((value) => { if (active) setReadiness(value); }).catch(() => {});
    return () => { active = false; };
  }, []);
  const selected = pipeline.receipts.find((item) => item.id === selectedId) ?? pipeline.receipts[0];
  const response = selected?.response;
  const question = !pipeline.runId && !pipeline.running && carriedEvent && response ? response.query : initialQuestion;
  const runFilters = !pipeline.runId && carriedEvent && response ? response.applied_filters as SearchFilters : filters;
  const count = readiness?.database.product_count;
  return <div className="page pipeline-inspector">
    <MosaicLabsTabs active="retrieval" />
    <div className="inspector-intro"><MosaicLabsMasthead title="Behind a better answer." deck="Follow Alex’s request from a catalog search to a considered recommendation. One run, with the work visible at every step." /></div>
    <nav className="inspector-request-choices" aria-label="Alex’s requests">{requests.map((request) => <button key={request.id} type="button" aria-pressed={!params.has("q") && selectedRequest?.id === request.id} onClick={() => setParams(new URLSearchParams({ scene: request.id }))}>{request.label}</button>)}</nav>
    <section className="inspector-request" aria-label="Pipeline request">
      <img className="inspector-alex" src="/assets/images/mosaic/alex-headshot-v1.jpg" alt="Alex, Mosaic’s example shopper" width={128} height={128} />
      <div><h2>{question || "No request is available"}</h2><p className="inspector-alex-bio">Meet Alex, a software engineer building a home office for coding, calls and focused work.</p><p>Alex’s workspace{count ? ` · Searching ${count.toLocaleString()} products` : ""}{filters.category_key ? ` · Filter: ${filters.category_key.replaceAll("-", " ")}` : ""}</p><Link href="/catalog">Choose another request in Shop <ArrowRight size={14} aria-hidden="true" /></Link></div>
      <button type="button" className="inspector-play" disabled={pipeline.running || pipeline.reading || !question} aria-busy={pipeline.running} onClick={() => void pipeline.play(question, runFilters)}><Play size={18} fill="currentColor" aria-hidden="true" />{pipeline.running ? "Playing pipeline…" : "Play pipeline"}</button>
    </section>
    <div className="inspector-run-status" role="status">{pipeline.reading ? "Reading the saved Shop search…" : pipeline.status || (carriedEvent ? "Saved Shop search · read from its original record" : "Ready when you are. Play makes one real agent request; the views below inspect its records.")}</div>
    {!params.has("q") && selectedRequest ? <p className="inspector-note">{selectedRequest.notice}</p> : null}
    {pipeline.error ? <p className="inspector-error" role="alert">{pipeline.error}</p> : null}
    <nav className="inspector-stage-nav" aria-label="Pipeline steps">
      <a href="#inspect-retrieve"><span>01</span><strong>Retrieve</strong><small>Find the candidates</small></a><ArrowRight size={20} aria-hidden="true" />
      <a href="#inspect-rank"><span>02</span><strong>Rank</strong><small>Order the possibilities</small></a><ArrowRight size={20} aria-hidden="true" />
      <a href="#inspect-reason"><span>03</span><strong>Reason</strong><small>Explain the choice</small></a>
    </nav>
    {pipeline.receipts.length > 1 ? <div className="inspector-search-selector"><label htmlFor="inspector-search">Search within this agent run</label><select id="inspector-search" value={selected?.id} onChange={(event) => setSelectedId(event.target.value)}>{pipeline.receipts.map((item, index) => <option key={item.id} value={item.id}>{index + 1}. {item.response?.query ?? item.id}</option>)}</select><p>The agent issued several searches. Retrieve and Rank inspect the same selected search.</p></div> : null}
    {selected ? <p className="inspector-receipt">Search record <code>{selected.id}</code>{response ? ` · ${response.query}` : selected.error ? " · Could not load" : " · Reading…"}</p> : null}
    {selected?.error ? <p className="inspector-error" role="alert">This record could not be read: {selected.error} Reload this page to retry a saved Shop link, or Play pipeline for a new run.</p> : null}
    <InspectorSection id="inspect-retrieve" number="01" title="Retrieve" description="Find useful candidates through words, spelling and meaning. Each approach covers a different kind of request."><RetrieveDetails response={response} /></InspectorSection>
    <InspectorSection id="inspect-rank" number="02" title="Rank" description="Turn overlapping candidates into an ordered shortlist. Follow each product through fusion and reranking."><RankDetails response={response} /></InspectorSection>
    <InspectorSection id="inspect-reason" number="03" title="Reason" description="Use the shortlist, inspect the evidence and explain a recommendation with citations."><ReasonDetails answer={pipeline.answer} partial={pipeline.partial} streamed={pipeline.streamed} completed={pipeline.completed} trace={pipeline.trace} running={pipeline.running} hasSearch={Boolean(response)} failed={Boolean(pipeline.error)} />{pipeline.runId ? <p className="inspector-receipt">Agent record <code>{pipeline.runId}</code></p> : null}</InspectorSection>
    <aside className="inspector-scale-link"><div><h2>And when the catalog grows?</h2><p>See how HNSW trades search effort for recall, and what changes under selective filters.</p></div><Link href="/mosaic-labs/hnsw">Explore scale & HNSW <ArrowRight size={18} aria-hidden="true" /></Link></aside>
  </div>;
}

/** Keep existing guide and proof deep links operational while the main surface inspects runs. */
export function PlaygroundPage() {
  const [params] = useSearchParams();
  return params.has("example") || params.get("view") === "lab" || params.has("run") ? <RetrievalLabPage /> : <PipelineInspector />;
}
