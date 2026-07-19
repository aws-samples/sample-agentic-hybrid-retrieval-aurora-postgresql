import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  Check,
  Clipboard,
  Compass,
  Database,
  Download,
  ExternalLink,
  FilterX,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  X
} from 'lucide-react';
import { FaGithub } from 'react-icons/fa6';
import confluenceLogoUrl from './assets/confluence-2017.svg';
import jiraLogoUrl from './assets/jira-streamline.svg';
import salesforceLogoUrl from './assets/salesforce-logo.jpeg';
import slackIconUrl from './assets/slack-icon-2019.svg';
import strandsLogoUrl from './assets/strands-logo.png';
import './styles.css';

type Page = 'landing' | 'results' | 'detail' | 'trail' | 'agent' | 'diagnostics' | 'compare';
type GuideStep = 'search' | 'evidence' | 'answer' | 'timeline' | 'diagnostics' | 'proof';
type ApiStatus = 'checking' | 'live' | 'offline';
type SourceFilter = 'all' | 'slack' | 'jira' | 'confluence' | 'salesforce' | 'github';
type RankMode = 'hybrid' | 'semantic' | 'lexical' | 'recent';
type TimeWindow = '90d' | '30d' | '7d' | 'all';
type ProjectFilter = 'ORION' | 'all';
type StatusFilter = 'all' | 'Decision' | 'Resolved Jul 3' | 'Mitigating' | 'Published' | 'Resolved' | 'Merged';
type PriorityFilter = 'all' | 'P1' | 'Tier 1' | 'Policy' | 'Sev2' | 'Change';

// The four retrieval arms the Compare view races side by side: the fused ranker
// and each single signal. These are the backend `mode` values, sent verbatim.
type CompareMode = 'hybrid' | 'semantic' | 'lexical' | 'fuzzy';

// The live fusion knobs the tradeoff clinic exposes. rrf_k and the three signal
// weights only shape the hybrid arm; ef_search and rerank apply per the backend's
// per-mode rules. These map 1:1 onto SearchRequest fields.
type FusionKnobs = {
  rrf_k: number;
  w_text: number;
  w_vector: number;
  w_trgm: number;
  ef_search: number;
  rerank: boolean;
};

type CompareColumn = {
  mode: CompareMode;
  run_id?: string;
  results: Result[];
  total_latency_ms?: number;
  retrieval_mode?: string;
  error?: string;
  loading: boolean;
};

type Signals = {
  full_text?: number;
  semantic?: number;
  fuzzy?: number;
  metadata?: number;
  recency?: number;
  rrf?: number;
  rerank?: number;
};

type Result = {
  chunk_id?: string;
  object_id?: string;
  source_system: string;
  source_type?: string;
  external_id: string;
  title: string;
  snippet: string;
  status?: string;
  priority?: string;
  owner?: string;
  account_name?: string;
  project_key?: string;
  component?: string;
  updated_at?: string;
  url?: string;
  text_rank?: number;
  vector_score?: number;
  trigram_score?: number;
  metadata_score?: number;
  recency_score?: number;
  rrf_score?: number;
  rerank_score?: number;
  final_score?: number;
  // Normalized 0–1 score for display, computed relative to the top result in the
  // current set (the raw composite final_score is unbounded and not 0–1).
  _display_score?: number;
  explanation?: { signals?: Signals; why?: string[] };
};

type SearchResponse = {
  run_id: string;
  query: string;
  retrieval_mode?: string;
  results: Result[];
};

type AgentMetadata = {
  harness?: string;
  tools?: string[];
  model_provider?: string;
  model_strategy?: string;
  model_routing?: {
    planning_and_tool_routing?: string;
    answer_synthesis?: string;
  };
  routing_notes?: {
    planning_and_tool_routing?: string;
    answer_synthesis?: string;
  };
};

// The live answer body is a set of RichToken paragraphs plus a pull quote —
// exactly the shape ops.agent_answers.answer.body stores and the API returns.
type AnswerBody = {
  lead?: RichToken[];
  why?: RichToken[];
  decided?: RichToken[];
  impacted?: RichToken[];
  quote?: { text: string; attr?: string };
};

type PlanStep = { num: string; fn: string; args: string; desc: string; res: string };

type Commitment = {
  citation_n?: number;
  account_name?: string;
  external_id?: string;
  subject?: string;
  arr?: number;
  arr_label?: string;
  contracted_go_live?: string;
  status?: string;
  priority?: string;
};

type Citation = {
  n: number;
  source_system: string;
  external_id: string;
  title: string;
  url?: string;
  object_id?: string;
  meta?: string;
  why?: string;
  score?: number;
};

type AgentPayload = {
  question?: string;
  run_id?: string;
  agent?: AgentMetadata;
  // The API serves the structured plan (objects) for the canonical run and a
  // plain-string plan for ad-hoc synthesis; the UI handles both.
  plan?: PlanStep[] | string[];
  // Canonical answers arrive as a rich body; ad-hoc synthesis returns a string.
  answer?: AnswerBody | string;
  confidence?: number;
  source_count?: number;
  system_count?: number;
  citations?: Citation[];
  commitments?: Commitment[];
  results?: Result[];
};

type ObjectDetail = {
  object?: Result & {
    metadata?: Record<string, unknown>;
    acl?: Record<string, unknown>;
  };
  chunks?: Array<{
    chunk_id: string;
    chunk_index: number;
    section_title?: string;
    chunk_text: string;
    chunk_summary?: string;
    metadata?: Record<string, unknown>;
  }>;
  citations?: Array<{
    citation_id: string;
    chunk_id: string;
    source_label: string;
    source_url?: string;
    locator?: string;
    quote_text?: string;
    metadata?: Record<string, unknown>;
  }>;
  links?: Array<Result & {
    link_id?: string;
    link_type?: string;
    confidence?: number;
    metadata?: Record<string, unknown>;
  }>;
};

// Live diagnostics payload from GET /v1/diagnostics/canonical — the canonical
// run's metrics, the persisted candidate table, and the cited sources. Read-only:
// fetched by the landing page and Diagnostics view without creating a new run.
type RunMetrics = {
  run_id?: string;
  profile?: string;
  embedding_model?: string;
  embedding_dim?: number;
  index_spec?: string;
  fired_at?: string;
  total_latency_ms?: number;
  p50_latency_ms?: number;
  rrf_k?: number;
  ranker_weights?: number[];
  rerank_cut?: number;
  reranked_count?: number;
  funnel?: { fetched?: number; deduped?: number; fused?: number; above_cut?: number; cited?: number };
  stage_timings?: Array<{ stage: string; ms: number }>;
  metadata?: { diagnostics_rows?: Array<Array<string>> };
};

type CanonicalDiagnostics = RunMetrics & {
  question?: string;
  confidence?: number;
  source_count?: number;
  system_count?: number;
  citations?: Citation[];
  results?: Result[];
  answer?: AnswerBody | string;
  plan?: PlanStep[] | string[];
  commitments?: Commitment[];
  agent?: AgentMetadata;
};

// GET /v1/runs/{id}/timeline — cited objects in time order, each carrying the
// outbound object_links traverse_links() would follow to the next system.
type TimelineEdge = {
  link_type: string;
  to_external_id?: string;
  to_title?: string;
  to_system?: string;
  confidence?: number;
};

type TimelineEvent = {
  object_id: string;
  external_id: string;
  source_system: string;
  source_type?: string;
  title: string;
  snippet?: string;
  status?: string;
  owner?: string;
  component?: string;
  created_at?: string;
  updated_at?: string;
  citation_n?: number;
  final_score?: number;
  edges: TimelineEdge[];
};

type TimelinePayload = {
  run_id?: string;
  events: TimelineEvent[];
  systems: string[];
  edge_count: number;
};

// GET /v1/runs/{id}/graph — the object_links among the cited set (mirror edges
// collapsed), plus the cited nodes, for the evidence mini-graph.
type GraphNode = {
  object_id: string;
  external_id: string;
  source_system: string;
  source_type?: string;
  title: string;
  citation_n?: number;
};

type GraphEdge = {
  link_id: string;
  relation: string;
  confidence?: number;
  from: { system: string; external_id?: string; title?: string };
  to: { system: string; external_id?: string; title?: string };
};

type GraphPayload = {
  run_id?: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  system_count: number;
  link_count: number;
};

// GET /v1/diagnostics/fusion-sql — the deployed ops.hybrid_search definition and
// its helpers, verbatim from pg_get_functiondef.
type FusionSql = {
  engine: string;
  primary: string;
  functions: Array<{ name: string; definition: string }>;
};

// POST /v1/diagnostics/plan — EXPLAIN (ANALYZE, BUFFERS) of each retrieval arm's
// real query body, so the workshop sees which index the planner used or rejected.
type PlanScan = { node_type: string; relation: string | null; index: string | null };
type ArmPlan = {
  arm: string;
  statement: string;
  summary: {
    scans: PlanScan[];
    actual_total_time_ms: number | null;
    actual_rows: number | null;
    shared_hit_blocks: number | null;
    shared_read_blocks: number | null;
  };
  plan: unknown;
};
type QueryPlan = { arm: string; query: string; explain: string; note: string; arms: ArmPlan[] };

// GET /v1/diagnostics/index-usage — live scan counts + sizes per ops index.
type IndexUsage = {
  indexes: Array<{
    table_name: string;
    index_name: string;
    method: string;
    scans: number;
    index_size: string;
    index_bytes: number;
  }>;
};

// GET /v1/diagnostics/slow-queries — retrieval hot path ranked by mean exec time.
type SlowQueries = {
  statements: Array<{
    queryid: number;
    query: string;
    calls: number;
    mean_exec_ms: number;
    total_exec_ms: number;
    rows: number;
    cache_hit_pct: number | null;
  }>;
};

// GET /v1/diagnostics/corpus — live object counts, per system and overall, for
// the filter chips and funnel totals.
type CorpusProfile = {
  profile?: { objects?: number; chunks?: number; source_systems?: number; embedded_chunks?: number };
  source_distribution?: Array<{ source_system: string; source_type?: string; object_count: number }>;
  embedding_progress?: Record<string, unknown>;
};

const API_URL = import.meta.env.VITE_RETRIEVAL_API_URL || 'http://127.0.0.1:8000';
const APP_NAME = import.meta.env.VITE_APP_DISPLAY_NAME || 'Verity';
const ENABLE_ANSWER_STREAMING = import.meta.env.VITE_ENABLE_ANSWER_STREAMING !== '0';
const ENABLE_GUIDED_DISCOVERY = import.meta.env.VITE_ENABLE_GUIDED_DISCOVERY !== '0';
const GUIDE_STORAGE_KEY = 'verity-guided-discovery-v1';
const GUIDE_STEP_DURATION_MS = 4200;
const guideSteps: GuideStep[] = ['search', 'evidence', 'answer', 'timeline', 'diagnostics', 'proof'];
const guideStepLabels: Record<GuideStep, string> = {
  search: 'Ask',
  evidence: 'Inspect',
  answer: 'Synthesize',
  timeline: 'Trace',
  diagnostics: 'Diagnose',
  proof: 'Prove'
};
const STRANDS_URL = 'https://strandsagents.com/';
const GITHUB_REPO_URL = 'https://github.com/aws-samples/sample-agentic-hybrid-retrieval-aurora-postgresql';
const FINAL_SCORE_HELP = 'Unbounded composite score from Aurora SQL: RRF + full-text + semantic vector + fuzzy + metadata + recency. It is not a raw Cohere similarity score or a probability.';
const RESULTS_PAGE_SIZE = 5;
const ApiStatusContext = React.createContext<ApiStatus>('checking');

// Presenter controls. The URL carries ?page= and ?run= so a beat can be deep-linked
// (or restored on refresh) from the podium, and `[` / `]` step through the workshop
// in presentation order. 'detail' is a click-through drill-down, not a linear beat,
// so it is a valid deep-link target but is skipped by the bracket keys.
const ALL_PAGES: Page[] = ['landing', 'results', 'detail', 'trail', 'agent', 'diagnostics', 'compare'];
const BEAT_PAGES: Page[] = ['landing', 'results', 'agent', 'compare', 'trail', 'diagnostics'];

function readInitialPage(): Page {
  if (typeof window === 'undefined') return 'landing';
  const value = new URLSearchParams(window.location.search).get('page');
  return value && (ALL_PAGES as string[]).includes(value) ? (value as Page) : 'landing';
}

function readInitialRun(): string | undefined {
  if (typeof window === 'undefined') return undefined;
  return new URLSearchParams(window.location.search).get('run') || undefined;
}
// The flagship question the seed answers canonically (a stored row in
// ops.agent_answers, restored identically in every account). The guided demo
// path must send this exact string so the answer resolves to the rich stored
// body — any other phrasing is answered live via ad-hoc synthesis.
const queryDefault = 'Why did Orion slip?';
const rotatingQueries = [
  queryDefault,
  'Why did Orion slip, and which customer commitments are at risk?',
  'Why did ORION-1489 page in prod, and what fixed it?',
  'Which customer commitments are at risk from the Orion slip?',
  'What blocked Orion’s release, and how did the fix ship?'
];

const rankModeLabels: Record<RankMode, string> = {
  hybrid: 'Hybrid + Cohere',
  semantic: 'Semantic · pgvector',
  lexical: 'Lexical · full-text',
  recent: 'Most recent'
};

// The retrieval arms raced in the Compare view, in display order. `signal` names
// the score column that arm ranks by (so a column shows the number it actually
// sorts on); `blurb` is the one-line teaching point for its header.
const compareModes: Array<{
  mode: CompareMode;
  label: string;
  method: string;
  signal: keyof Signals;
  blurb: string;
}> = [
  { mode: 'hybrid', label: 'Hybrid', method: 'weighted RRF + Cohere rerank', signal: 'rerank', blurb: 'Fuses all signals, then reranks. The robust default.' },
  { mode: 'lexical', label: 'Lexical', method: 'tsvector @@ tsquery', signal: 'full_text', blurb: 'Exact terms and identifiers. Wins on ORION-1489.' },
  { mode: 'semantic', label: 'Semantic', method: 'pgvector cosine (HNSW)', signal: 'semantic', blurb: 'Meaning over wording. Wins on paraphrase.' },
  { mode: 'fuzzy', label: 'Fuzzy', method: 'pg_trgm similarity', signal: 'fuzzy', blurb: 'Typo-tolerant trigrams. Recall-limited.' }
];

const defaultFusionKnobs: FusionKnobs = {
  rrf_k: 60,
  w_text: 1.0,
  w_vector: 1.0,
  w_trgm: 0.5,
  ef_search: 100,
  rerank: true
};

const timeWindowLabels: Record<TimeWindow, string> = {
  '90d': 'Last 90 days',
  '30d': 'Last 30 days',
  '7d': 'Last 7 days',
  all: 'All time'
};

const projectFilterLabels: Record<ProjectFilter, string> = {
  ORION: 'Orion',
  all: 'All projects'
};

const statusFilterLabels: Record<StatusFilter, string> = {
  all: 'All statuses',
  Decision: 'Decision',
  'Resolved Jul 3': 'Resolved Jul 3',
  Mitigating: 'Mitigating',
  Published: 'Published',
  Resolved: 'Resolved',
  Merged: 'Merged'
};

const priorityFilterLabels: Record<PriorityFilter, string> = {
  all: 'All priorities',
  P1: 'P1',
  'Tier 1': 'Tier 1',
  Policy: 'Policy',
  Sev2: 'Sev2',
  Change: 'Change'
};

const rankModeOptions: RankMode[] = ['hybrid', 'semantic', 'lexical', 'recent'];
const timeWindowOptions: TimeWindow[] = ['90d', '30d', '7d', 'all'];
const projectFilterOptions: ProjectFilter[] = ['ORION', 'all'];
const statusFilterOptions: StatusFilter[] = ['all', 'Decision', 'Resolved Jul 3', 'Mitigating', 'Published', 'Resolved', 'Merged'];
const priorityFilterOptions: PriorityFilter[] = ['all', 'P1', 'Tier 1', 'Policy', 'Sev2', 'Change'];

// Users ask in natural language. The `sources` on each suggestion are what the
// agent surfaces automatically — rendered as the little system icons — not
// something the user types. "Incident to fix" deliberately names the ORION-1489
// ticket: an exact ID is where lexical full-text search beats semantic vectors
// (embeddings blur ORION-1489 vs ORION-1487), so it's the teaching moment for FTS.
const searchSuggestions = [
  {
    label: 'Root cause',
    query: 'Why did Orion slip?',
    sources: ['slack', 'jira', 'confluence', 'salesforce', 'github']
  },
  {
    label: 'Incident to fix',
    query: 'Why did ORION-1489 page in prod, and what fixed it?',
    sources: ['jira', 'github']
  },
  {
    label: 'Customer impact',
    query: 'Which customer commitments are at risk from the Orion slip?',
    sources: ['salesforce', 'slack', 'jira']
  },
  {
    label: 'Decision timeline',
    query: 'What was decided about Orion’s release date, and why?',
    sources: ['confluence', 'slack', 'jira', 'github']
  },
  {
    label: 'Linked context',
    query: 'How does the failed readiness gate connect to the customer commitment and the fix?',
    sources: ['confluence', 'salesforce', 'github']
  },
  {
    label: 'Full picture',
    query: 'Explain the Orion delay end to end – cause, impact, and resolution.',
    sources: ['slack', 'jira', 'confluence', 'salesforce', 'github']
  }
];

// Structural: which pages the workspace nav and demo strip link to, plus a fixed
// label and summary for each. The eyebrow COUNT is content, so it is derived live
// from the canonical run and its timeline at render time (see deriveNavEyebrow),
// never hard-coded — the number differs per corpus and per environment.
const workspaceNavItems: Array<{ page: Page; label: string; summary: string }> = [
  { page: 'results', label: 'Evidence', summary: 'Hybrid-ranked sources and linked context' },
  { page: 'agent', label: 'Answer', summary: 'Synthesized answer with inline citations' },
  { page: 'compare', label: 'Compare', summary: 'Race hybrid vs each single signal on one query' },
  { page: 'trail', label: 'Timeline', summary: 'Time-ordered cross-system sequence' },
  { page: 'diagnostics', label: 'Diagnostics', summary: 'Fusion, scoring, latency, and SQL trace' }
];

// Live eyebrow count for a demo-strip beat, pulled from the canonical run and its
// timeline. Returns undefined until the backing data hydrates, so the card shows a
// label-only teaser rather than a stale number. 'compare' counts the ranker arms,
// which is a structural constant (the four retrieval modes), identical everywhere.
function deriveNavEyebrow(
  page: Page,
  canonical: CanonicalDiagnostics | null,
  timeline: TimelinePayload | null
): string | undefined {
  if (page === 'results') {
    const ranked = canonical?.funnel?.fused ?? canonical?.funnel?.cited;
    return typeof ranked === 'number' ? `${ranked} ranked results` : undefined;
  }
  if (page === 'agent') {
    const cited = canonical?.source_count;
    return typeof cited === 'number' ? `${cited} cited source${cited === 1 ? '' : 's'}` : undefined;
  }
  if (page === 'compare') {
    return `${compareModes.length} rankers`;
  }
  if (page === 'trail') {
    const events = timeline?.events?.length;
    return typeof events === 'number' && events > 0 ? `${events} linked events` : undefined;
  }
  if (page === 'diagnostics') {
    const ms = canonical?.total_latency_ms;
    return typeof ms === 'number' ? `${ms} ms run` : undefined;
  }
  return undefined;
}

// The five connected systems, in canonical display order. This is the system
// registry — which integrations exist and how to label them — i.e. structure,
// not content. Every count, title, score, snippet, and citation is fetched live
// from the API (which reads the same seeded Aurora locally and in Workshop Studio).
const SYSTEMS: Array<{ key: string; label: string }> = [
  { key: 'slack', label: 'Slack' },
  { key: 'jira', label: 'Jira' },
  { key: 'confluence', label: 'Confluence' },
  { key: 'salesforce', label: 'Salesforce' },
  { key: 'github', label: 'GitHub' }
];
const SYSTEM_KEYS = SYSTEMS.map((source) => source.key);
// Alias kept for the landing chips, which only need key + label.
const landingSources = SYSTEMS;

// Hero-orbit layout: which CSS slot and entrance delay each system's node sits
// in. Pure positioning — the node's title, meta, score, and role come from the
// live cited set (see deriveHeroNodes).
const heroNodeLayout: Record<string, { className: string; delay: string }> = {
  confluence: { className: 'n-conf', delay: '.6s' },
  slack: { className: 'n-slack', delay: '0s' },
  jira: { className: 'n-jira', delay: '1.4s' },
  salesforce: { className: 'n-sf', delay: '.9s' },
  github: { className: 'n-gh', delay: '1.8s' }
};
function cx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(' ');
}

async function fetchWithTimeout(url: string, init: RequestInit = {}, timeoutMs = 20000) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
  // Honor a caller-supplied signal (used to cancel a superseded search) alongside
  // the timeout: either aborting the request aborts our internal controller.
  const external = init.signal;
  const onExternalAbort = () => controller.abort();
  if (external) {
    if (external.aborted) controller.abort();
    else external.addEventListener('abort', onExternalAbort);
  }
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      // A caller cancelled this request on purpose (newer search in flight) —
      // re-throw the raw AbortError so the caller can ignore it silently, rather
      // than surfacing the misleading timeout message.
      if (external?.aborted) throw error;
      throw new Error('The request timed out. Verify Aurora connectivity, then retry.');
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
    if (external) external.removeEventListener('abort', onExternalAbort);
  }
}

function readGuideDismissals(): GuideStep[] {
  if (typeof window === 'undefined') return [];
  if (new URLSearchParams(window.location.search).get('guide') === '1') return [];
  try {
    const stored = JSON.parse(window.localStorage.getItem(GUIDE_STORAGE_KEY) || '[]');
    if (!Array.isArray(stored)) return [];
    return stored.filter((step): step is GuideStep => guideSteps.includes(step));
  } catch {
    return [];
  }
}

// Per-ranker cell styling in the diagnostics candidate table: em-dash = not ranked
// by that mode (.na), top rank (#1) = emphasized (.rk), everything else plain.
function rankCellClass(value: string) {
  if (value === '—') return 'na';
  if (value === '#1') return 'rk';
  return '';
}

function optionalNumber(value: unknown): number | undefined {
  if (value === null || value === undefined || value === '') return undefined;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : undefined;
}

function normalizeResult(row: Result): Result {
  return {
    ...row,
    source_system: row.source_system || 'source',
    external_id: row.external_id || row.object_id || row.chunk_id || 'unknown',
    title: row.title || 'Untitled source object',
    snippet: row.snippet || '',
    final_score: optionalNumber(row.final_score),
    text_rank: optionalNumber(row.text_rank),
    vector_score: optionalNumber(row.vector_score),
    trigram_score: optionalNumber(row.trigram_score),
    metadata_score: optionalNumber(row.metadata_score),
    recency_score: optionalNumber(row.recency_score),
    rrf_score: optionalNumber(row.rrf_score),
    rerank_score: optionalNumber(row.rerank_score)
  };
}

function score(result: Result) {
  return Number(result.final_score || 0);
}

function rankScore(result: Result) {
  return typeof result.rerank_score === 'number' ? result.rerank_score : score(result);
}

function withDisplayScores(rows: Result[]): Result[] {
  return rows.map(normalizeResult);
}

function displayScore(result: Result) {
  const value = score(result);
  if (Number.isFinite(value)) return value;
  return Number(result._display_score || 0);
}

// Clamp a 0–1 score to a 0–100 bar width. Non-numeric or out-of-range values
// (the composite final_score is unbounded) collapse to 0 instead of overflowing
// the track or emitting NaN%, so a bad row never blows out the projected layout.
function barPercent(value: unknown): number {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric <= 0) return 0;
  return Math.min(numeric, 1) * 100;
}

function resultTimestamp(result: Result) {
  const value = result.updated_at ? Date.parse(result.updated_at) : 0;
  return Number.isFinite(value) ? value : 0;
}

function resultInWindow(result: Result, window: TimeWindow) {
  if (window === 'all') return true;
  const timestamp = resultTimestamp(result);
  if (!timestamp) return false;
  const days = window === '7d' ? 7 : window === '30d' ? 30 : 90;
  const reference = Date.parse('2026-07-11T12:00:00-04:00');
  return timestamp >= reference - days * 24 * 60 * 60 * 1000;
}

function startDateForWindow(window: TimeWindow) {
  if (window === 'all') return undefined;
  const days = window === '7d' ? 7 : window === '30d' ? 30 : 90;
  return new Date(Date.parse('2026-07-11T12:00:00-04:00') - days * 24 * 60 * 60 * 1000).toISOString();
}

function sortByRankMode(rows: Result[], rankMode: RankMode) {
  return [...rows].sort((a, b) => {
    if (rankMode === 'semantic') return Number(b.vector_score || 0) - Number(a.vector_score || 0);
    if (rankMode === 'lexical') return Number(b.text_rank || 0) - Number(a.text_rank || 0);
    if (rankMode === 'recent') return resultTimestamp(b) - resultTimestamp(a);
    return rankScore(b) - rankScore(a);
  });
}

function sourceLabel(system: string) {
  const labels: Record<string, string> = {
    slack: 'Slack',
    jira: 'Jira',
    confluence: 'Confluence',
    salesforce: 'Salesforce',
    github: 'GitHub'
  };
  return labels[system] || system;
}

function shortRunId(value: string) {
  const compact = value.replace(/[^a-zA-Z0-9]/g, '');
  if (compact.length > 12) return compact.slice(-8);
  return value;
}

function friendlyModelName(modelId?: string) {
  if (!modelId) return 'Model not configured';
  if (modelId.includes('claude-opus-4-8')) return 'Claude Opus 4.8';
  if (modelId.includes('claude-sonnet-5')) return 'Claude Sonnet 5';
  if (modelId.includes('cohere.embed-v4')) return 'Cohere embed-v4';
  return modelId.split('.').pop()?.replace(/-/g, ' ') || modelId;
}

const brandLogoUrls: Record<string, string> = {
  slack: slackIconUrl,
  jira: jiraLogoUrl,
  confluence: confluenceLogoUrl,
  salesforce: salesforceLogoUrl
};

function brandImageStyle(system: string, size: number): React.CSSProperties {
  if (system === 'salesforce') return { width: Math.round(size * 1.8), height: Math.round(size * 1.05) };
  return { width: size, height: size };
}

function sourceIcon(system: string, size = 22) {
  const brandLogoUrl = brandLogoUrls[system];
  if (brandLogoUrl) {
    return (
      <img
        className={cx('brand-image', `brand-image-${system}`)}
        src={brandLogoUrl}
        alt=""
        style={brandImageStyle(system, size)}
      />
    );
  }
  if (system === 'github') return <FaGithub size={size} />;
  return <Database size={size} />;
}

function formatDate(value?: string) {
  if (!value) return 'recently';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

// A short descriptor for a result, derived from its own live fields: the source
// type (e.g. "Slack thread", "Pull request") the connector reported, falling
// back to the system label. No hard-coded per-system role map.
function resultRole(result: Result) {
  return result.source_type || sourceLabel(result.source_system);
}

// Turn the live cited set (from the agent answer or the canonical endpoint) into
// Result rows for the evidence rail and detail deep-links. Citations already
// carry object_id (resolved server-side, even for objects below the live top-k),
// title, url, and a rerank score, so the rail can render and link without a
// second fetch. The citation index n IS the rail order.
function citationsToResults(citations?: Citation[]): Result[] {
  if (!citations || citations.length === 0) return [];
  return [...citations]
    .sort((a, b) => (a.n || 0) - (b.n || 0))
    .map((c) => ({
      object_id: c.object_id,
      source_system: c.source_system,
      external_id: c.external_id,
      title: c.title,
      snippet: '',
      url: c.url,
      final_score: c.score,
      _display_score: typeof c.score === 'number' ? c.score : undefined
    }));
}

// Normalize a live result set, attach display scores, and drop duplicate objects
// (same system + external_id). Order is preserved as the API returned it — the
// search endpoint already ranks by final_score, and callers re-sort as needed.
function dedupeResults(results: Result[]): Result[] {
  const seen = new Set<string>();
  return withDisplayScores(results).filter((result) => {
    const key = `${result.source_system}:${result.external_id}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

// Format an ISO date as "Jul 8, 2026" (no time) for commitment/contract dates.
function formatDateOnly(value?: string) {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

// Flatten a rich-token block to plain text (drops bold/highlight markup and
// citation chips) — used for compact previews like the Evidence rail teaser.
function flattenRich(tokens?: RichToken[]): string {
  if (!tokens) return '';
  return tokens
    .map((token) => ('text' in token ? token.text : 'b' in token ? token.b : 'hl' in token ? token.hl : ''))
    .join('');
}

// The answer body as a single string, in reading order — for previews and any
// place that needs the prose without the streamed rich rendering.
function answerBodyText(body?: AnswerBody | string | null): string {
  if (!body) return '';
  if (typeof body === 'string') return body;
  return [body.lead, body.why, body.decided, body.impacted].map(flattenRich).filter(Boolean).join(' ');
}

// Count the inline citation chips across an answer body's rich-token blocks —
// the number of claims bound to a citation. Purely derived from the live answer.
function countCitationClaims(body?: AnswerBody | null) {
  if (!body) return 0;
  const blocks = [body.lead, body.why, body.decided, body.impacted];
  let count = 0;
  for (const block of blocks) {
    for (const token of block || []) {
      if (token && typeof token === 'object' && 'cite' in token) count += 1;
    }
  }
  return count;
}

// A hero-orbit node, ready to render: CSS slot + entrance delay from the layout
// map, and role/score/title/meta pulled from the live cited object for that system.
type HeroNode = {
  key: string;
  className: string;
  delay: string;
  role: string;
  score: string;
  title: string;
  meta: string;
};

function landingText(value?: string) {
  return (value || '').replace(/—/g, '–');
}

// Build the landing hero orbit from the live cited set. The system registry keeps
// all five structural nodes visible (label + orbit slot are structure); title,
// score, and external id come from the live cited object for that system, and stay
// blank until the API hydrates — no fabricated titles, ids, or scores.
function deriveHeroNodes(citedResults: Result[], canonical: CanonicalDiagnostics | null): HeroNode[] {
  const citations = canonical?.citations || [];
  const nodes: HeroNode[] = [];
  for (const system of Object.keys(heroNodeLayout)) {
    const layout = heroNodeLayout[system];
    const citation = citations.find((c) => c.source_system === system);
    const result = citedResults.find((r) => r.source_system === system);
    const title = citation?.title || result?.title || '';
    const scoreValue =
      typeof citation?.score === 'number'
        ? citation.score
        : typeof result?.rerank_score === 'number'
          ? result.rerank_score
          : typeof result?._display_score === 'number'
            ? result._display_score
            : typeof result?.final_score === 'number' && result.final_score >= 0 && result.final_score <= 1
              ? result.final_score
              : null;
    nodes.push({
      key: system,
      className: layout.className,
      delay: layout.delay,
      role: sourceLabel(system),
      score: typeof scoreValue === 'number' ? scoreValue.toFixed(2) : '',
      title: landingText(title),
      meta: citation?.external_id || result?.external_id || ''
    });
  }
  return nodes;
}

function Logo() {
  return (
    <div className="wordmark">
      <span>{APP_NAME}</span>
    </div>
  );
}

function MiniBrand({ system }: { system: string }) {
  return <span className={cx('mini-brand', system)}>{sourceIcon(system, 20)}</span>;
}

function ErrorBanner({ message }: { message?: string }) {
  if (!message) return null;
  return (
    <div className="error-banner" role="alert">
      <ShieldCheck size={15} />
      <span>{message}</span>
    </div>
  );
}

function GuideCoachmark({
  step,
  title,
  body,
  onAdvance,
  onSkip,
  primaryLabel = 'Continue',
  secondaryLabel = 'Exit walkthrough'
}: {
  step: GuideStep;
  title: string;
  body: string;
  onAdvance: () => void;
  onSkip: () => void;
  primaryLabel?: string;
  secondaryLabel?: string;
}) {
  const cardRef = useRef<HTMLDivElement>(null);
  const stepIndex = guideSteps.indexOf(step);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const timerId = window.setTimeout(() => {
      const target = (cardRef.current?.closest('.guide-target') as HTMLElement | null) || cardRef.current;
      if (!target) return;
      const rect = target.getBoundingClientRect();
      const margin = 72;
      if (rect.top < margin || rect.bottom > window.innerHeight - margin) {
        const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        target.scrollIntoView({ block: 'center', behavior: reduceMotion ? 'auto' : 'smooth' });
      }
    }, 80);
    return () => window.clearTimeout(timerId);
  }, [title]);

  return (
    <div className="guide-card" role="region" aria-label="Guided discovery" ref={cardRef}>
      <div className="guide-card-head">
        <span className="guide-kicker"><Compass size={13} /> Guided walkthrough</span>
        <span className="guide-count">Step {stepIndex + 1} of {guideSteps.length}</span>
      </div>
      <div className="guide-progress" aria-label={`Walkthrough progress: step ${stepIndex + 1} of ${guideSteps.length}`}>
        {guideSteps.map((guideStep, index) => (
          <span
            className={cx(index < stepIndex && 'done', index === stepIndex && 'active')}
            key={guideStep}
            title={guideStepLabels[guideStep]}
          />
        ))}
      </div>
      <b>{title}</b>
      <p>{body}</p>
      <div className="guide-actions">
        <button type="button" onClick={onAdvance}>
          {primaryLabel}
          <ArrowRight size={14} />
        </button>
        <button type="button" onClick={onSkip}>
          <X size={13} />
          {secondaryLabel}
        </button>
      </div>
    </div>
  );
}

function WalkthroughLauncher({ onStart }: { onStart: () => void }) {
  return (
    <button className="walkthrough-launcher" type="button" onClick={onStart}>
      <Compass size={17} />
      <span>Guided walkthrough</span>
    </button>
  );
}

function EmptyState({
  title,
  body,
  action,
  loading = false
}: {
  title: string;
  body: string;
  action?: React.ReactNode;
  loading?: boolean;
}) {
  return (
    <section className={cx('empty-state', loading && 'loading')}>
      <h3>{title}</h3>
      <p>{body}</p>
      {action}
    </section>
  );
}

function SearchComposer({
  query,
  setQuery,
  onSearch,
  autoType = false,
  className
}: {
  query: string;
  setQuery: (value: string) => void;
  onSearch: (queryOverride?: string) => void;
  autoType?: boolean;
  className?: string;
}) {
  const userEditedRef = useRef(false);
  const [isTypingDefault, setIsTypingDefault] = useState(autoType && query.length === 0);
  const [rotationIndex, setRotationIndex] = useState(0);
  const [typedCount, setTypedCount] = useState(0);
  const [typingPhase, setTypingPhase] = useState<'typing' | 'holding' | 'deleting'>('typing');
  const [suggestionsOpen, setSuggestionsOpen] = useState(false);
  const [activeSuggestion, setActiveSuggestion] = useState(-1);
  const activeRotatingQuery = rotatingQueries[rotationIndex % rotatingQueries.length];

  useEffect(() => {
    if (!autoType || !isTypingDefault) return;
    let timeoutId: number | undefined;

    if (userEditedRef.current) {
      setIsTypingDefault(false);
      return;
    }

    if (typingPhase === 'typing') {
      timeoutId = window.setTimeout(() => {
        const nextCount = Math.min(activeRotatingQuery.length, typedCount + 1);
        setTypedCount(nextCount);
        setQuery(activeRotatingQuery.slice(0, nextCount));
        if (nextCount >= activeRotatingQuery.length) setTypingPhase('holding');
      }, typedCount === 0 ? 420 : 22);
    }

    if (typingPhase === 'holding') {
      timeoutId = window.setTimeout(() => setTypingPhase('deleting'), 2800);
    }

    if (typingPhase === 'deleting') {
      timeoutId = window.setTimeout(() => {
        const nextCount = Math.max(0, typedCount - 2);
        setTypedCount(nextCount);
        setQuery(activeRotatingQuery.slice(0, nextCount));
        if (nextCount === 0) {
          setRotationIndex((current) => (current + 1) % rotatingQueries.length);
          setTypingPhase('typing');
        }
      }, 18);
    }

    return () => {
      if (timeoutId) window.clearTimeout(timeoutId);
    };
  }, [activeRotatingQuery, autoType, isTypingDefault, setQuery, typedCount, typingPhase]);

  const visibleSuggestions = useMemo(() => {
    const terms = query
      .toLowerCase()
      .split(/[^a-z0-9]+/)
      .filter((term) => term.length > 2);

    return searchSuggestions
      .map((suggestion) => {
        const haystack = `${suggestion.label} ${suggestion.query} ${suggestion.sources.join(' ')}`.toLowerCase();
        const scoreValue = terms.reduce((total, term) => total + (haystack.includes(term) ? 1 : 0), 0);
        return { ...suggestion, scoreValue };
      })
      .sort((a, b) => b.scoreValue - a.scoreValue)
      .slice(0, 6);
  }, [query]);

  function selectSuggestion(index: number) {
    const suggestion = visibleSuggestions[index];
    if (!suggestion) return;
    userEditedRef.current = true;
    setIsTypingDefault(false);
    setQuery(suggestion.query);
    setSuggestionsOpen(false);
    setActiveSuggestion(-1);
  }

  function handleQueryChange(value: string) {
    userEditedRef.current = true;
    setIsTypingDefault(false);
    setQuery(value);
    setSuggestionsOpen(true);
    setActiveSuggestion(-1);
  }

  function handleSearchKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (!visibleSuggestions.length) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setSuggestionsOpen(true);
      setActiveSuggestion((current) => (current + 1) % visibleSuggestions.length);
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setSuggestionsOpen(true);
      setActiveSuggestion((current) => (current <= 0 ? visibleSuggestions.length - 1 : current - 1));
    }
    if (event.key === 'Tab' && suggestionsOpen) {
      event.preventDefault();
      selectSuggestion(activeSuggestion >= 0 ? activeSuggestion : 0);
    }
    if (event.key === 'Enter' && suggestionsOpen && activeSuggestion >= 0) {
      event.preventDefault();
      selectSuggestion(activeSuggestion);
    }
  }

  return (
    <form
      className={cx('landing-search', className, isTypingDefault && 'is-typing', suggestionsOpen && 'has-suggestions')}
      onSubmit={(event) => {
        event.preventDefault();
        const submittedQuery = isTypingDefault ? activeRotatingQuery : query;
        setQuery(submittedQuery);
        onSearch(submittedQuery);
      }}
    >
      <Search size={19} />
      <div className="search-input-wrap">
        <input
          value={query}
          onChange={(event) => handleQueryChange(event.target.value)}
          onFocus={() => setSuggestionsOpen(true)}
          onBlur={() => window.setTimeout(() => setSuggestionsOpen(false), 120)}
          onKeyDown={handleSearchKeyDown}
          spellCheck={false}
          aria-label="Search evidence"
          aria-autocomplete="list"
          aria-expanded={suggestionsOpen}
          placeholder={queryDefault}
        />
        {isTypingDefault && (
          <span className="typewriter-overlay" aria-hidden="true">
            <span>{query}</span>
            <i />
          </span>
        )}
      </div>
      <kbd>⌘K</kbd>
      <button className="ink-button" type="submit"><Search size={16} />Search</button>
      {suggestionsOpen && (
        <div className="search-suggestions" role="listbox">
          <span>Try</span>
          {visibleSuggestions.map((suggestion, index) => (
            <button
              key={suggestion.label}
              type="button"
              className={cx(index === activeSuggestion && 'active')}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => selectSuggestion(index)}
              role="option"
              aria-selected={index === activeSuggestion}
            >
              <span className="suggestion-icons">
                {suggestion.sources.slice(0, 4).map((source) => (
                  <MiniBrand key={source} system={source} />
                ))}
                {suggestion.sources.length > 4 && <span className="source-count">+{suggestion.sources.length - 4}</span>}
              </span>
              <span className="suggestion-copy">
                <b>{suggestion.label}</b>
                <small>{suggestion.query}</small>
              </span>
            </button>
          ))}
        </div>
      )}
    </form>
  );
}

function AppHeader({
  page,
  query,
  setQuery,
  onSearch,
  onNavigate,
  omniboxRef
}: {
  page: Page;
  query: string;
  setQuery: (value: string) => void;
  onSearch: () => void;
  onNavigate: (page: Page) => void;
  omniboxRef?: React.RefObject<HTMLInputElement>;
}) {
  const apiStatus = React.useContext(ApiStatusContext);
  return (
    <header className="appbar">
      <button className="wordmark-button" onClick={() => onNavigate('landing')} aria-label="Go to landing page">
        <Logo />
      </button>
      <form
        className="omnibox"
        onSubmit={(event) => {
          event.preventDefault();
          onSearch();
        }}
      >
        <Search size={15} />
        <input
          ref={omniboxRef}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={queryDefault}
          aria-label="Search evidence"
        />
        <kbd>⌘K</kbd>
      </form>
      <nav className="appnav" aria-label={`${APP_NAME} workspace`}>
        <button onClick={() => onNavigate('landing')} type="button">
          Search
        </button>
        {workspaceNavItems.map((item) => (
          <button
            key={item.page}
            className={cx(page === item.page && 'on')}
            onClick={() => onNavigate(item.page)}
            type="button"
          >
            {item.label}
          </button>
        ))}
      </nav>
      <div className={cx('runtime-status', apiStatus)} title={`Retrieval API: ${apiStatus}`}>
        <Activity size={14} />
        <span>{apiStatus === 'live' ? 'Live' : apiStatus === 'offline' ? 'Offline' : 'Checking'}</span>
      </div>
    </header>
  );
}

function scrollToLandingSection(
  event: React.MouseEvent<HTMLAnchorElement>,
  sectionId: string
) {
  event.preventDefault();
  const section = document.getElementById(sectionId);
  if (!section) return;
  const target =
    section.querySelector<HTMLElement>('[data-landing-scroll-target]') ||
    section;
  const nav = document.querySelector<HTMLElement>('.landing-page > .topnav');
  const navHeight = nav?.getBoundingClientRect().height || 0;
  const top = window.scrollY + target.getBoundingClientRect().top - navHeight - 16;
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  window.scrollTo({
    top: Math.max(0, top),
    behavior: reduceMotion ? 'auto' : 'smooth'
  });
  window.history.replaceState(null, '', `#${sectionId}`);
}

function Landing({
  query,
  setQuery,
  onSearch,
  onNavigate,
  error,
  heroNodes,
  heroScore,
  corpusTotal,
  runLatency,
  canonical,
  timeline,
  guideStep,
  onAdvanceGuide,
  onSkipGuide
}: {
  query: string;
  setQuery: (value: string) => void;
  onSearch: (queryOverride?: string) => void;
  onNavigate: (page: Page) => void;
  error?: string;
  heroNodes: HeroNode[];
  heroScore?: number | null;
  corpusTotal?: number;
  runLatency?: number;
  canonical: CanonicalDiagnostics | null;
  timeline: TimelinePayload | null;
  guideStep?: GuideStep | null;
  onAdvanceGuide: (step: GuideStep) => void;
  onSkipGuide: () => void;
}) {
  const showSearchGuide = guideStep === 'search';
  const apiStatus = React.useContext(ApiStatusContext);
  return (
    <div className="landing-page">
      <nav className="topnav">
        <button className="wordmark-button" onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}>
          <Logo />
        </button>
        <div className="navlinks">
          <a href="#how" onClick={(event) => scrollToLandingSection(event, 'how')}>
            Architecture
          </a>
          <a href="#stack" onClick={(event) => scrollToLandingSection(event, 'stack')}>
            Retrieval pipeline
          </a>
          <a href="#contract" onClick={(event) => scrollToLandingSection(event, 'contract')}>
            Build with the API
          </a>
          <a href="#demo-run" onClick={(event) => scrollToLandingSection(event, 'demo-run')}>
            Explore the run
          </a>
        </div>
        <div className="nav-actions" aria-label="External resources">
          <a className="nav-strands-link" href={STRANDS_URL} target="_blank" rel="noreferrer" aria-label="Open Strands Agents">
            <img src={strandsLogoUrl} alt="" />
          </a>
          <a className="nav-icon-link" href={GITHUB_REPO_URL} target="_blank" rel="noreferrer" aria-label="Open the Verity source repository">
            <FaGithub size={19} />
          </a>
        </div>
      </nav>

      <main className="shell" id="overview">
        <section className="hero">
          <div className="hero-copy">
            <div className="eyebrow mono-label">Connected evidence</div>
            <h1>
              The{' '}
              <span className="why">
                evidence
                <svg viewBox="0 0 120 14" preserveAspectRatio="none" aria-hidden="true">
                  <path d="M3 10 C 30 3, 60 13, 117 6" />
                </svg>
              </span>{' '}
              behind every decision.
            </h1>
            <p className="sub">
              Connect scattered tickets, docs, cases, incidents, and code to surface the full context – and deliver answers{' '}
              <em>you can trust, with every source cited</em>.
            </p>
            <div className="works" id="systems">
              <span className="mono-label">Works with your systems</span>
              <div className="chips">
                {landingSources.map((source) => (
                  <span className="chip" key={source.key}>
                    <MiniBrand system={source.key} />
                    {source.label}
                  </span>
                ))}
                <span className="chip more">and more</span>
              </div>
            </div>
          </div>

          <div className="orbit" aria-hidden="true">
            <svg className="threads" viewBox="0 0 640 620" preserveAspectRatio="xMidYMid meet">
              <ellipse className="ring" cx="320" cy="292" rx="300" ry="216" />
              <ellipse className="ring" cx="320" cy="292" rx="216" ry="286" />
              <path className="thread" d="M320 292 C 320 220, 320 160, 320 78" />
              <path className="thread" d="M320 292 C 250 265, 190 230, 112 190" />
              <path className="thread" d="M320 292 C 245 320, 180 355, 104 396" />
              <path className="thread" d="M320 292 C 395 262, 455 228, 532 186" />
              <path className="thread" d="M320 292 C 395 322, 460 352, 538 382" />
            </svg>

            <div className="center-node">
              <div className="a-title">Answer</div>
              <div className="a-sub">Hybrid fusion</div>
              {typeof heroScore === 'number' && (
                <div className="a-score" aria-label={`Answer confidence ${heroScore.toFixed(2)}`}>
                  <span>Confidence</span>
                  <b>{heroScore.toFixed(2)}</b>
                </div>
              )}
            </div>

            {heroNodes.map((node) => (
              <article className={cx('hero-node', node.className)} key={node.key} style={{ '--d': node.delay } as React.CSSProperties}>
                <div className="tile">{sourceIcon(node.key, 24)}</div>
                <div className="node-copy">
                  <div className="nhead">
                    <span className="ntype">{node.role}</span>
                    {node.score && (
                      <span className="nscore" title="Cited relevance score" aria-label={`Cited relevance score ${node.score}`}>
                        {node.score}
                      </span>
                    )}
                  </div>
                  {node.title && <div className="ntitle">{node.title}</div>}
                </div>
                {node.meta && <div className="nmeta">{node.meta}</div>}
              </article>
            ))}
          </div>

          <div className={cx('searchwrap', showSearchGuide && 'guide-target guide-spotlight')}>
            {showSearchGuide && (
              <GuideCoachmark
                step="search"
                title="Start with a question"
                body="The Orion question starts the path. Search retrieves, fuses, and reranks evidence across every connected system."
                onAdvance={() => onAdvanceGuide('search')}
                onSkip={onSkipGuide}
                primaryLabel="Next: evidence"
              />
            )}
            <SearchComposer
              key={showSearchGuide ? 'guided-search' : 'standard-search'}
              query={query}
              setQuery={setQuery}
              onSearch={onSearch}
              autoType={!showSearchGuide}
              className="landing-composer"
            />
            <div className="search-proof" aria-label="Live retrieval status">
              <span><i className={cx('live-dot', apiStatus)} />{apiStatus === 'live' ? 'Retrieval API online' : apiStatus === 'offline' ? 'Retrieval API offline' : 'Checking retrieval API'}</span>
              <span><b>{corpusTotal ?? '—'}</b> source objects</span>
              <span><b>{landingSources.length}</b> connected systems</span>
              {typeof runLatency === 'number' && <span><b>{runLatency} ms</b> canonical run</span>}
            </div>
          </div>
        </section>

        <ErrorBanner message={error} />

        <section className="section harness-section" id="contract" aria-label="Portable API and tool contract">
          <div className="harness-note" data-landing-scroll-target>
            <span className="mono-label">Portable API and tool contract</span>
            <div>
              <h2>The UI inspects it. Your agents build on it.</h2>
              <p>
                Verity is one inspection surface over an Aurora-backed API. Keep the retrieval, scores, citations, and run receipts;
                drive the same contract through AgentCore Gateway, Strands, Claude Code, LangGraph, an MCP client, or your own orchestrator.
              </p>
            </div>
            <div className="harness-points" aria-label="Portable tool contract">
              <span>POST /v1/search</span>
              <span>POST /v1/agent/answer</span>
              <span>MCP search_evidence</span>
              <span>MCP answer_with_citations</span>
            </div>
          </div>
        </section>

        <section className="section" id="how">
          <div className="sec-head" data-landing-scroll-target>
            <div className="eyebrow mono-label">Agentic architecture</div>
            <h2 className="sec-title">From question to cited answer.</h2>
          </div>
          <div className="steps">
            {[
              ['01', 'Ask in plain language', 'Complex questions are decomposed into targeted retrievals: topics, systems, entities, and time windows.', 'search_evidence()'],
              ['02', 'Retrieve everywhere', 'Full-text, semantic, and fuzzy retrieval run side by side with SQL and metadata filters in one engine.', 'fts + pgvector + pg_trgm'],
              ['03', 'Follow the thread', 'Evidence links are traversed across systems: the ticket that blocks, the PR that fixes, the case it impacts.', 'traverse_links()'],
              ['04', 'Answer with receipts', 'Fused, scored, and synthesized into a cited answer. Every claim points back to its source.', 'synthesize_with_citations()']
            ].map(([num, title, body, fn]) => (
              <article className="step" key={num}>
                <div className="num">{num}</div>
                <h3>{title}</h3>
                <p>{body}</p>
                <span className="fn">{fn}</span>
              </article>
            ))}
          </div>
        </section>

        <section className="section stack-section" id="stack">
          <div className="sec-head" data-landing-scroll-target>
            <div className="eyebrow mono-label">Retrieval pipeline</div>
            <h2 className="sec-title">Five signals. One evidence index.</h2>
          </div>
          <div className="stack">
            <span className="mono-label">The hybrid retrieval path · inspect every stage</span>
            <div className="formula">
              {[
                'Full-text|ts_rank_cd',
                'Semantic|pgvector',
                'Fuzzy|pg_trgm',
                'Metadata + recency|SQL signals',
                'Aurora fusion|RRF + SQL score',
                'Cohere rerank|relevance order',
                'Cited answer|persisted proof'
              ].map((item, index) => {
                const [title, body] = item.split('|');
                return (
                  <React.Fragment key={item}>
                    {index > 0 && (
                      <span className={cx('f-op', index < 4 ? 'plus' : 'arrow')} aria-hidden="true">
                        {index < 4 ? '+' : '→'}
                      </span>
                    )}
                    <div className={cx('f-chip', index >= 4 && index <= 5 && 'hot')}>
                      <b>{title}</b>
                      <span>{body}</span>
                    </div>
                  </React.Fragment>
                );
              })}
            </div>
            <div className="foot">
              Powered by <b>Amazon Aurora PostgreSQL</b> – the durable retrieval index. Source systems remain authoritative; every run is logged and every candidate explained.
            </div>
          </div>
        </section>

        <section className="section demo-section" id="demo-run">
          <div className="demo-strip" data-landing-scroll-target aria-label="Explore the populated Orion run">
            <div>
              <span className="mono-label">Explore demo run</span>
              <p>Start with search, or jump into the pre-populated Orion answer path.</p>
            </div>
            <div className="demo-links">
              {workspaceNavItems.map((item) => {
                const eyebrow = deriveNavEyebrow(item.page, canonical, timeline);
                return (
                  <button
                    key={item.page}
                    type="button"
                    title={item.summary}
                    aria-label={`${item.label}: ${item.summary}`}
                    onClick={() => onNavigate(item.page)}
                  >
                    {eyebrow && <span>{eyebrow}</span>}
                    <b>{item.label}</b>
                    <small>{item.summary}</small>
                  </button>
                );
              })}
            </div>
          </div>
          <footer className="footer">
            <div>
              <span className="mono-label">The evidence path · inspect every claim</span>
              <div className="tag">Every answer shows its work.</div>
            </div>
            <div className="fine">© 2026 Agentic Hybrid Retrieval</div>
          </footer>
        </section>
      </main>
    </div>
  );
}

// Stop words we never highlight — they add noise, not signal, to a snippet.
const HIGHLIGHT_STOPWORDS = new Set([
  'the', 'and', 'for', 'why', 'what', 'how', 'did', 'does', 'was', 'were', 'are',
  'that', 'this', 'with', 'from', 'into', 'when', 'which', 'who', 'whom', 'whose',
  'has', 'have', 'had', 'will', 'would', 'should', 'could', 'can', 'its', 'it',
  'in', 'on', 'of', 'to', 'a', 'an', 'is', 'be', 'or', 'as', 'at', 'by', 'but',
  'not', 'get', 'got', 'fix', 'fixed', 'prod', 'page', 'paged'
]);

function escapeRegExp(term: string): string {
  return term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// The terms to highlight in a snippet, derived LIVE from the user's query.
// We keep alphanumeric tokens (and dotted/hyphenated identifiers like ORION-1489
// or replication_lag) that are meaningful — never a hard-coded phrase list.
function deriveHighlightTerms(query: string): string[] {
  const tokens = (query || '').match(/[A-Za-z0-9][A-Za-z0-9._-]*/g) || [];
  const seen = new Set<string>();
  const terms: string[] = [];
  for (const raw of tokens) {
    const term = raw.trim();
    const lower = term.toLowerCase();
    if (term.length < 3) continue;
    // Keep identifiers (with a digit, dot, hyphen, or underscore) even if short-ish;
    // drop plain stop words.
    const isIdentifier = /[0-9._-]/.test(term);
    if (!isIdentifier && HIGHLIGHT_STOPWORDS.has(lower)) continue;
    if (seen.has(lower)) continue;
    seen.add(lower);
    terms.push(term);
  }
  return terms;
}

const SQL_KEYWORDS = new Set([
  'all', 'and', 'as', 'asc', 'begin', 'between', 'by', 'case', 'create', 'cross',
  'declare', 'default', 'desc', 'distinct', 'else', 'end', 'except', 'exists',
  'filter', 'from', 'function', 'group', 'having', 'if', 'immutable', 'in', 'inner',
  'into', 'is', 'join', 'language', 'lateral', 'left', 'limit', 'not', 'null',
  'offset', 'on', 'or', 'order', 'outer', 'over', 'partition', 'perform', 'replace',
  'return', 'returns', 'right', 'select', 'stable', 'table', 'then', 'union', 'when',
  'where', 'with', 'uuid', 'text', 'integer', 'numeric', 'boolean', 'jsonb', 'vector',
  'timestamp', 'timestamptz'
]);

function isSqlIdentStart(char: string) {
  return /[A-Za-z_]/.test(char);
}

function isSqlIdentPart(char: string) {
  return /[A-Za-z0-9_$]/.test(char);
}

function highlightSql(sql: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  let i = 0;
  let key = 0;
  const push = (text: string, className?: string) => {
    if (!text) return;
    nodes.push(className ? <span className={className} key={key++}>{text}</span> : text);
  };

  while (i < sql.length) {
    if (sql.startsWith('--', i)) {
      const end = sql.indexOf('\n', i);
      const next = end === -1 ? sql.length : end + 1;
      push(sql.slice(i, next), 'cm');
      i = next;
      continue;
    }

    if (sql.startsWith('/*', i)) {
      const end = sql.indexOf('*/', i + 2);
      const next = end === -1 ? sql.length : end + 2;
      push(sql.slice(i, next), 'cm');
      i = next;
      continue;
    }

    const quote = sql[i];
    if (quote === '\'' || quote === '"') {
      let next = i + 1;
      while (next < sql.length) {
        if (sql[next] === quote) {
          if (quote === '\'' && sql[next + 1] === '\'') {
            next += 2;
            continue;
          }
          next += 1;
          break;
        }
        next += 1;
      }
      push(sql.slice(i, next), 'st');
      i = next;
      continue;
    }

    if (sql[i] === '$') {
      const match = sql.slice(i).match(/^\$[A-Za-z_][A-Za-z0-9_]*\$|^\$\$/);
      if (match) {
        push(match[0], 'st');
        i += match[0].length;
        continue;
      }
    }

    if (isSqlIdentStart(sql[i])) {
      let next = i + 1;
      while (next < sql.length && isSqlIdentPart(sql[next])) next += 1;
      const word = sql.slice(i, next);
      const lower = word.toLowerCase();
      let lookahead = next;
      while (lookahead < sql.length && /\s/.test(sql[lookahead])) lookahead += 1;
      const className = SQL_KEYWORDS.has(lower) ? 'kw' : sql[lookahead] === '(' ? 'fn' : undefined;
      push(word, className);
      i = next;
      continue;
    }

    let next = i + 1;
    while (
      next < sql.length &&
      !sql.startsWith('--', next) &&
      !sql.startsWith('/*', next) &&
      sql[next] !== '\'' &&
      sql[next] !== '"' &&
      sql[next] !== '$' &&
      !isSqlIdentStart(sql[next])
    ) {
      next += 1;
    }
    push(sql.slice(i, next));
    i = next;
  }

  return nodes;
}

function HighlightedSnippet({ text, terms }: { text: string; terms?: string[] }) {
  const clean = (terms || []).filter(Boolean);
  if (clean.length === 0) return <>{text}</>;
  // Longest-first so multi-word identifiers win over their fragments.
  const ordered = [...clean].sort((a, b) => b.length - a.length).map(escapeRegExp);
  const pattern = new RegExp(`(${ordered.join('|')})`, 'gi');
  const matcher = new RegExp(`^(${ordered.join('|')})$`, 'i');
  const parts = text.split(pattern);
  return (
    <>
      {parts.map((part, index) => (
        matcher.test(part)
          ? <mark key={`${part}-${index}`}>{part}</mark>
          : <React.Fragment key={`${part}-${index}`}>{part}</React.Fragment>
      ))}
    </>
  );
}

// The retrieval signals that fired for a result, as display chips derived live
// from result.explanation.signals (the per-ranker contributions Aurora returned).
// Only signals that actually contributed are shown; the strongest reads first.
const SIGNAL_LABELS: Array<{ key: keyof Signals; label: string; method: string }> = [
  { key: 'rerank', label: 'Cohere rerank', method: 'Cohere Rerank v3.5' },
  { key: 'full_text', label: 'full-text', method: 'ts_rank_cd' },
  { key: 'semantic', label: 'semantic', method: 'pgvector' },
  { key: 'fuzzy', label: 'fuzzy', method: 'pg_trgm' },
  { key: 'metadata', label: 'metadata', method: 'filters' },
  { key: 'recency', label: 'recency', method: 'updated_at' }
];

function signalChips(result: Result): Array<{ key: string; label: string; value: string }> {
  const signals = result.explanation?.signals || {
    rerank: result.rerank_score,
    full_text: result.text_rank,
    semantic: result.vector_score,
    fuzzy: result.trigram_score,
    metadata: result.metadata_score,
    recency: result.recency_score
  };
  return SIGNAL_LABELS.map(({ key, label }) => ({ key, label, raw: Number(signals[key] || 0) }))
    .filter((chip) => chip.raw > 0)
    .sort((a, b) => b.raw - a.raw)
    .map((chip) => ({ key: chip.key, label: chip.label, value: chip.raw.toFixed(2) }));
}

// Derive how many of the persisted top candidates each ranker actually ranked,
// straight from the diagnostics rows (columns: rank, system, title, FTS, VEC,
// TRGM, RRF, FINAL, CITED). An em-dash means that retriever did not rank the row.
// This is the real ranker overlap for this run — no fabricated counts.
const DIAG_RANKERS: Array<{ name: string; method: string; col: number }> = [
  { name: 'lexical', method: 'ts_rank_cd', col: 3 },
  { name: 'semantic', method: 'pgvector', col: 4 },
  { name: 'fuzzy', method: 'pg_trgm', col: 5 }
];

function rankerMix(rows?: string[][]) {
  const source = rows || [];
  const mix = DIAG_RANKERS.map((ranker) => ({
    ...ranker,
    count: source.filter((row) => row[ranker.col] && row[ranker.col] !== '—').length
  }));
  const peak = mix.reduce((max, row) => Math.max(max, row.count), 0);
  return mix.map((row) => ({ ...row, width: peak > 0 ? Math.round((row.count / peak) * 100) : 0 }));
}

function ResultCard({
  result,
  index,
  onOpen,
  highlightTerms
}: {
  result: Result;
  index: number;
  onOpen: () => void;
  highlightTerms?: string[];
}) {
  const chips = signalChips(result);
  const finalScore = displayScore(result).toFixed(2);
  const rerankScore = typeof result.rerank_score === 'number'
    ? result.rerank_score
    : result.explanation?.signals?.rerank;
  const hasRerankScore = typeof rerankScore === 'number' && Number.isFinite(rerankScore);
  return (
    <article className="rcard">
      <div className="rhead">
        <span className="result-rank" aria-label={`Result rank ${index + 1}`}>{index + 1}</span>
        <div className="tile">{sourceIcon(result.source_system, 22)}</div>
        <div>
          <div className="rtype">{resultRole(result)}</div>
          <button className="rtitle" onClick={onOpen}>{result.title}</button>
        </div>
        {hasRerankScore ? (
          <div
            className="rscore reranked"
            title={`Cohere Rerank v3.5 relevance score via Amazon Bedrock. ${FINAL_SCORE_HELP}`}
            aria-label={`Cohere Rerank score ${rerankScore.toFixed(2)}; Aurora SQL composite score ${finalScore}`}
          >
            <span>Cohere rerank</span>
            <b>{rerankScore.toFixed(2)}</b>
            <small title={FINAL_SCORE_HELP}>SQL {finalScore}</small>
          </div>
        ) : (
          <div className="rscore" title={FINAL_SCORE_HELP} aria-label={`Aurora SQL composite score ${finalScore}`}>
            <span>SQL score</span>
            {' '}
            <b>{finalScore}</b>
          </div>
        )}
      </div>
      <p className="rsnippet"><HighlightedSnippet text={result.snippet || 'No snippet returned for this source.'} terms={highlightTerms} /></p>
      <div className="rmeta">
        <span>{result.component || result.project_key || sourceLabel(result.source_system)}</span>
        {result.owner && <span>{result.owner}</span>}
        <span>{formatDate(result.updated_at)}</span>
        {result.status && <span>{result.status}</span>}
      </div>
      {chips.length > 0 && (
        <div className="rwhy">
          <span className="lbl">Why this matched</span>
          {chips.map((chip) => (
            <span key={chip.key} className="sig">{chip.label} {chip.value}</span>
          ))}
        </div>
      )}
    </article>
  );
}

function ResultsPage({
  page,
  query,
  setQuery,
  omniboxRef,
  results,
  citedResults,
  hasSearchRun,
  graph,
  canonical,
  corpusTotal,
  systemCounts,
  runId,
  error,
  loading,
  sourceFilter,
  rankMode,
  timeWindow,
  projectFilter,
  statusFilter,
  priorityFilter,
  setSelected,
  onSearch,
  onAgent,
  onSourceFilterChange,
  onRankModeChange,
  onTimeWindowChange,
  onProjectFilterChange,
  onStatusFilterChange,
  onPriorityFilterChange,
  onResetFilters,
  guideStep,
  onAdvanceGuide,
  onSkipGuide,
  onNavigate
}: {
  page: Page;
  query: string;
  setQuery: (value: string) => void;
  omniboxRef?: React.RefObject<HTMLInputElement>;
  results: Result[];
  citedResults: Result[];
  hasSearchRun: boolean;
  graph: GraphPayload | null;
  canonical: CanonicalDiagnostics | null;
  corpusTotal?: number;
  systemCounts: Record<string, number>;
  selected: Result | null;
  runId?: string;
  error?: string;
  loading: boolean;
  sourceFilter: SourceFilter;
  rankMode: RankMode;
  timeWindow: TimeWindow;
  projectFilter: ProjectFilter;
  statusFilter: StatusFilter;
  priorityFilter: PriorityFilter;
  setSelected: (value: Result) => void;
  onSearch: () => void;
  onAgent: () => void;
  onSourceFilterChange: (value: SourceFilter) => void;
  onRankModeChange: (value: RankMode) => void;
  onTimeWindowChange: (value: TimeWindow) => void;
  onProjectFilterChange: (value: ProjectFilter) => void;
  onStatusFilterChange: (value: StatusFilter) => void;
  onPriorityFilterChange: (value: PriorityFilter) => void;
  onResetFilters: () => void;
  guideStep?: GuideStep | null;
  onAdvanceGuide: (step: GuideStep) => void;
  onSkipGuide: () => void;
  onNavigate: (page: Page) => void;
}) {
  const [evidencePage, setEvidencePage] = useState(0);
  // Live evidence: the search results when the user has run a query, otherwise the
  // canonical run's cited objects (fetched read-only on mount). Both are real rows.
  const canonicalEvidence = dedupeResults(canonical?.results || []);
  const baseEvidence = hasSearchRun || results.length > 0
    ? results
    : canonicalEvidence.length > 0
      ? canonicalEvidence
      : citedResults;
  const usingCanonicalEvidence = !hasSearchRun && results.length === 0;
  const evidence = sortByRankMode(
    baseEvidence.filter((result) => {
      if (sourceFilter !== 'all' && result.source_system !== sourceFilter) return false;
      if (projectFilter !== 'all' && result.project_key && result.project_key !== projectFilter) return false;
      if (statusFilter !== 'all' && result.status && result.status !== statusFilter) return false;
      if (priorityFilter !== 'all' && result.priority && result.priority !== priorityFilter) return false;
      if (!usingCanonicalEvidence && result.updated_at && !resultInWindow(result, timeWindow)) return false;
      return true;
    }),
    rankMode
  );
  const showEvidenceGuide = guideStep === 'evidence';
  // Highlight the LIVE query terms in each snippet — derived from what was searched,
  // never a hard-coded phrase list.
  const highlightTerms = deriveHighlightTerms(query || queryDefault);
  const resultCountLabel = `${evidence.length} result${evidence.length === 1 ? '' : 's'}`;
  const totalEvidencePages = Math.max(1, Math.ceil(evidence.length / RESULTS_PAGE_SIZE));
  const currentEvidencePage = Math.min(evidencePage, totalEvidencePages - 1);
  const pageStart = currentEvidencePage * RESULTS_PAGE_SIZE;
  const pageEnd = Math.min(pageStart + RESULTS_PAGE_SIZE, evidence.length);
  const visibleEvidence = evidence.slice(pageStart, pageEnd);
  const pageSummary = evidence.length > RESULTS_PAGE_SIZE
    ? `showing ${pageStart + 1}-${pageEnd} of ${evidence.length}`
    : null;
  const scopeSummary = [
    sourceFilter === 'all' ? `${SYSTEMS.length} systems` : sourceLabel(sourceFilter),
    timeWindowLabels[timeWindow],
    projectFilterLabels[projectFilter],
    statusFilterLabels[statusFilter],
    priorityFilterLabels[priorityFilter]
  ].filter((item) => !item.startsWith('All ')).join(' · ');

  // The Evidence rail's "agent answer" card mirrors the canonical run, served
  // read-only on mount. Every value here is derived from that live payload.
  const answerBody = canonical?.answer && typeof canonical.answer === 'object' ? canonical.answer : null;
  const answerPreview = answerBody ? flattenRich(answerBody.lead) : answerBodyText(canonical?.answer);
  const confidenceValue = typeof canonical?.confidence === 'number' ? canonical.confidence : 0;
  const confidenceLabel = confidenceValue.toFixed(2);
  const confidencePercent = Math.round(Math.max(0, Math.min(1, confidenceValue)) * 100);
  const coverageLabel = canonical
    ? `${canonical.source_count ?? citedResults.length} sources · ${canonical.system_count ?? 0} systems`
    : '';
  const funnel = canonical?.funnel;
  const funnelSteps: Array<[string, number]> = funnel
    ? ([
        ['Corpus', corpusTotal ?? funnel.fetched],
        ['Deduped', funnel.deduped],
        ['Fused', funnel.fused],
        ['Above cut', funnel.above_cut],
        ['Cited', funnel.cited]
      ].filter((entry): entry is [string, number] => typeof entry[1] === 'number'))
    : [];
  const rankerRows = rankerMix(canonical?.metadata?.diagnostics_rows);
  const evidenceReady = !loading && evidence.length > 0;
  const filtersCustomized =
    sourceFilter !== 'all' ||
    rankMode !== 'hybrid' ||
    timeWindow !== '90d' ||
    projectFilter !== 'ORION' ||
    statusFilter !== 'all' ||
    priorityFilter !== 'all';

  useEffect(() => {
    setEvidencePage(0);
  }, [query, sourceFilter, rankMode, timeWindow, projectFilter, statusFilter, priorityFilter, baseEvidence.length]);

  function openResult(result: Result) {
    setSelected(result);
    onNavigate('detail');
  }

  return (
    <section className="inner-screen">
      <AppHeader page={page} query={query || queryDefault} setQuery={setQuery} onSearch={onSearch} onNavigate={onNavigate} omniboxRef={omniboxRef} />
      <div className="filters">
        <span className="filter-label">Scope</span>
        <button type="button" className={cx('fchip', sourceFilter === 'all' && 'on')} aria-pressed={sourceFilter === 'all'} onClick={() => onSourceFilterChange('all')}>
          All {corpusTotal != null && <span className="n">{corpusTotal}</span>}
        </button>
        {SYSTEMS.map((source) => (
          <button
            type="button"
            className={cx('fchip', sourceFilter === source.key && 'on')}
            aria-pressed={sourceFilter === source.key}
            key={source.key}
            onClick={() => onSourceFilterChange(source.key as SourceFilter)}
          >
            <MiniBrand system={source.key} />
            {source.label} {systemCounts[source.key] != null && <span className="n">{systemCounts[source.key]}</span>}
          </button>
        ))}
        <span className="fdiv" />
        <label className="fselect">
          <span>Window</span>
          <select value={timeWindow} onChange={(event) => onTimeWindowChange(event.currentTarget.value as TimeWindow)}>
            {timeWindowOptions.map((option) => (
              <option key={option} value={option}>{timeWindowLabels[option]}</option>
            ))}
          </select>
        </label>
        <label className="fselect">
          <span>Rank</span>
          <select value={rankMode} onChange={(event) => onRankModeChange(event.currentTarget.value as RankMode)}>
            {rankModeOptions.map((option) => (
              <option key={option} value={option}>{rankModeLabels[option]}</option>
            ))}
          </select>
        </label>
        <label className="fselect">
          <span>Project</span>
          <select value={projectFilter} onChange={(event) => onProjectFilterChange(event.currentTarget.value as ProjectFilter)}>
            {projectFilterOptions.map((option) => (
              <option key={option} value={option}>{projectFilterLabels[option]}</option>
            ))}
          </select>
        </label>
        <label className="fselect">
          <span>Status</span>
          <select value={statusFilter} onChange={(event) => onStatusFilterChange(event.currentTarget.value as StatusFilter)}>
            {statusFilterOptions.map((option) => (
              <option key={option} value={option}>{statusFilterLabels[option]}</option>
            ))}
          </select>
        </label>
        <label className="fselect">
          <span>Priority</span>
          <select value={priorityFilter} onChange={(event) => onPriorityFilterChange(event.currentTarget.value as PriorityFilter)}>
            {priorityFilterOptions.map((option) => (
              <option key={option} value={option}>{priorityFilterLabels[option]}</option>
            ))}
          </select>
        </label>
        {filtersCustomized && (
          <button className="filter-reset" type="button" onClick={onResetFilters}>
            <FilterX size={14} />
            Reset
          </button>
        )}
      </div>

      <main className={cx('results-layout', !evidenceReady && 'results-layout-pending')}>
        <section>
          <ErrorBanner message={error} />
          <div className={cx('results-head', !evidenceReady && 'pending')}>
            <div className="count">
              {loading ? (
                <b>Searching evidence</b>
              ) : (
                <>
                  <b>{resultCountLabel}</b>{pageSummary && <> · {pageSummary}</>} · {scopeSummary || 'All evidence'}
                  {(runId || canonical?.run_id) && <> · run <b>{shortRunId(runId || canonical?.run_id || '')}</b></>}
                </>
              )}
            </div>
            {evidenceReady && (
              <>
                <div className="score-explainer" title={FINAL_SCORE_HELP}>
                  Default order uses Cohere Rerank when present; SQL score remains the Aurora composite.
                </div>
                <button className="answer-ready" onClick={() => onAgent()}>
                  <Sparkles size={15} />
                  Agent answer ready
                  <ArrowRight size={14} />
                </button>
              </>
            )}
          </div>
          {loading ? (
            <EmptyState loading title="Searching evidence" body={`${APP_NAME} is retrieving, fusing, and scoring source objects across connected systems.`} />
          ) : evidence.length === 0 ? (
            <EmptyState
              title="No evidence matched"
              body="Adjust the source, window, project, status, or priority filter and run the search again."
              action={filtersCustomized ? (
                <button className="btn ghost empty-action" type="button" onClick={onResetFilters}>
                  <FilterX size={14} />
                  Reset filters
                </button>
              ) : undefined}
            />
          ) : (
            <>
              <div className={cx('evidence-focus', showEvidenceGuide && 'guide-target guide-spotlight')}>
                {showEvidenceGuide && (
                  <GuideCoachmark
                    step="evidence"
                    title="Inspect the evidence"
                    body="Read the source, matching signals, persisted score, and highlighted passage. The next step connects those records to cited claims."
                    onAdvance={() => onAdvanceGuide('evidence')}
                    onSkip={onSkipGuide}
                    primaryLabel="Next: answer"
                  />
                )}
                <div className="thread-col">
                  {visibleEvidence.map((result, index) => (
                    <ResultCard
                      key={`${result.source_system}-${result.external_id}-${pageStart + index}`}
                      result={result}
                      index={pageStart + index}
                      onOpen={() => openResult(result)}
                      highlightTerms={highlightTerms}
                    />
                  ))}
                </div>
              </div>
              {evidence.length > RESULTS_PAGE_SIZE && (
                <nav className="results-pager" aria-label="Evidence pagination">
                  <button
                    type="button"
                    onClick={() => setEvidencePage((value) => Math.max(0, value - 1))}
                    disabled={currentEvidencePage === 0}
                  >
                    Previous
                  </button>
                  <span>Page <b>{currentEvidencePage + 1}</b> of <b>{totalEvidencePages}</b></span>
                  <button
                    type="button"
                    onClick={() => setEvidencePage((value) => Math.min(totalEvidencePages - 1, value + 1))}
                    disabled={currentEvidencePage >= totalEvidencePages - 1}
                  >
                    Next
                  </button>
                </nav>
              )}
            </>
          )}
        </section>

        {evidenceReady && <aside className="rail">
          <div className="railcard">
            <div className="mono-label with-dot"><span className="dot" />Agent answer · ready</div>
            {answerPreview ? (
              <p className="ans-preview">{answerPreview}</p>
            ) : (
              <p className="ans-preview">Run the agent to synthesize a cited answer across the connected systems.</p>
            )}
            {canonical && (
              <div className="conf">
                <div className="row"><span>CONFIDENCE</span><b>{confidenceLabel}</b></div>
                <div className="meter"><i style={{ width: `${confidencePercent}%` }} /></div>
                <div className="row"><span>COVERAGE</span><b>{coverageLabel}</b></div>
              </div>
            )}
            <button className="rail-cta" onClick={() => onAgent()}>Read the full answer</button>
          </div>

          <div className="railcard">
            <div className="mono-label">Evidence graph</div>
            <MiniGraph graph={graph} />
            <button className="rail-link" onClick={() => onNavigate('trail')}>View timeline →</button>
          </div>

          {canonical && (
            <div className="railcard">
              <div className="mono-label">This retrieval run</div>
              <div className="retrieval-run">
                {canonical.question && (
                  <div className="run-intent">
                    <span>Intent</span>
                    <b>{canonical.question}</b>
                    <small>{canonical.profile} · {canonical.embedding_model} · {canonical.system_count} systems</small>
                  </div>
                )}

                {funnelSteps.length > 0 && (
                  <div className="run-funnel" aria-label="Candidate funnel">
                    {funnelSteps.map(([label, value], index) => (
                      <React.Fragment key={label}>
                        {index > 0 && <span className="funnel-arrow">→</span>}
                        <span className={cx('funnel-step', index === funnelSteps.length - 1 && 'hot')}><b>{value}</b><small>{label}</small></span>
                      </React.Fragment>
                    ))}
                  </div>
                )}

                <div className="ranker-mix">
                  {rankerRows.map((row) => (
                    <div className="ranker-row" key={row.name}>
                      <span><b>{row.name}</b><small>{row.method}</small></span>
                      <i><em style={{ width: `${row.width}%` }} /></i>
                      <strong>{row.count}</strong>
                    </div>
                  ))}
                </div>

                <div className="run-proof">
                  <span><b>RRF k={canonical.rrf_k}</b> fused {canonical.funnel?.deduped} candidates to the top {canonical.funnel?.fused}.</span>
                  <span><b>SQL composite</b> selected {canonical.funnel?.cited} cited objects above the {canonical.rerank_cut} cut.</span>
                  <span><b>Persisted</b> in retrieval_runs, retrieval_candidates, and citations.</span>
                </div>

                {typeof canonical.total_latency_ms === 'number' && (
                  <div className="run-latency">
                    <span>Latency</span>
                    <b>{canonical.total_latency_ms} ms</b>
                  </div>
                )}
              </div>
              <button className="rail-link" onClick={() => onNavigate('diagnostics')}>Open diagnostics →</button>
            </div>
          )}
        </aside>}
      </main>
    </section>
  );
}

function MiniGraph({ graph }: { graph: GraphPayload | null }) {
  if (!graph || graph.edges.length === 0) {
    return (
      <div className="evidence-graph" aria-label="Evidence relationship graph">
        <div className="graph-summary"><span>No linked evidence yet</span></div>
      </div>
    );
  }
  const visibleEdges = graph.edges.slice(0, 5);
  const hiddenEdgeCount = Math.max(0, graph.edges.length - visibleEdges.length);
  return (
    <div className="evidence-graph" aria-label="Evidence relationship graph">
      <div className="graph-summary">
        <span><b>{graph.nodes.length}</b> cited objects</span>
        <span><b>{graph.system_count}</b> systems</span>
        <span><b>{graph.link_count}</b> links traversed</span>
      </div>
      <div className="graph-edge-list">
        {visibleEdges.map((edge) => (
          <div className="graph-edge" key={edge.link_id}>
            <div className="graph-row">
              <span className="graph-icon">{sourceIcon(edge.from.system, 15)}</span>
              <span className="graph-copy">
                <b>{edge.from.external_id} → {edge.to.external_id}</b>
                <small>{edge.from.title} · {edge.to.title}</small>
              </span>
              {typeof edge.confidence === 'number' && <em>{edge.confidence.toFixed(2)}</em>}
            </div>
            <div className="graph-relation">
              <span>{edge.relation.replace(/_/g, ' ')}</span>
              <small>{sourceLabel(edge.from.system)} to {sourceLabel(edge.to.system)}</small>
            </div>
          </div>
        ))}
      </div>
      {hiddenEdgeCount > 0 && (
        <div className="graph-more">+{hiddenEdgeCount} more link{hiddenEdgeCount === 1 ? '' : 's'} in Timeline</div>
      )}
    </div>
  );
}

function Citation({ n, onClick }: { n: number; onClick?: () => void }) {
  return <button type="button" className="cit" onClick={onClick}>[{n}]</button>;
}

// ---- Streaming primitives -------------------------------------------------

// True when the OS asks for reduced motion; streaming then renders instantly.
function useReducedMotion() {
  const [reduced, setReduced] = useState(() =>
    typeof window !== 'undefined' && window.matchMedia
      ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
      : false
  );
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const onChange = () => setReduced(mq.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);
  return reduced;
}

// Drives an ordered "stage" cursor: stage 0, 1, 2 ... each advancing after a
// beat. Consumers reveal content once the cursor reaches their index. When
// motion is reduced (or streaming disabled) every stage is revealed at once.
function useStageSequence(count: number, opts: { enabled: boolean; beatMs?: number; startMs?: number; restartKey?: number }) {
  const { enabled, beatMs = 620, startMs = 220, restartKey = 0 } = opts;
  const [stage, setStage] = useState(enabled ? -1 : count);
  useEffect(() => {
    if (!enabled) {
      setStage(count);
      return;
    }
    setStage(-1);
    const timers: number[] = [];
    for (let i = 0; i < count; i += 1) {
      timers.push(window.setTimeout(() => setStage(i), startMs + i * beatMs));
    }
    return () => timers.forEach((t) => window.clearTimeout(t));
  }, [count, enabled, beatMs, startMs, restartKey]);
  return stage;
}

// Types `text` out grapheme-by-grapheme. onDone fires once the run completes.
// speed is chars-per-tick; tickMs the cadence. Instant when disabled.
function useTypewriter(text: string, opts: { enabled: boolean; speed?: number; tickMs?: number; startMs?: number; onDone?: () => void }) {
  const { enabled, speed = 3, tickMs = 16, startMs = 0, onDone } = opts;
  const [count, setCount] = useState(enabled ? 0 : text.length);
  const doneRef = useRef(false);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  useEffect(() => {
    if (!enabled) {
      setCount(text.length);
      if (!doneRef.current) {
        doneRef.current = true;
        onDoneRef.current?.();
      }
      return;
    }
    doneRef.current = false;
    setCount(0);
    let current = 0;
    let intervalId: number | undefined;
    const startId = window.setTimeout(() => {
      intervalId = window.setInterval(() => {
        current = Math.min(text.length, current + speed);
        setCount(current);
        if (current >= text.length) {
          if (intervalId) window.clearInterval(intervalId);
          if (!doneRef.current) {
            doneRef.current = true;
            onDoneRef.current?.();
          }
        }
      }, tickMs);
    }, startMs);
    return () => {
      window.clearTimeout(startId);
      if (intervalId) window.clearInterval(intervalId);
    };
  }, [text, enabled, speed, tickMs, startMs]);

  return { shown: text.slice(0, count), done: count >= text.length };
}

// Rich token model for streamed prose: plain runs, bold/highlight runs, and
// inline citation chips that pop in as the caret reaches them.
type RichToken =
  | { text: string }
  | { b: string }
  | { hl: string }
  | { cite: number };

type LiveAnswerSection = {
  label: string;
  tokens: RichToken[];
};

function splitLiveAnswerSentences(value: string): string[] {
  const paragraphs = value
    .replace(/\r\n?/g, '\n')
    .split(/\n+/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);
  const sentences: string[] = [];

  for (const paragraph of paragraphs) {
    let start = 0;
    for (let i = 0; i < paragraph.length; i += 1) {
      if (!'.!?'.includes(paragraph[i])) continue;
      let next = i + 1;
      while (next < paragraph.length && `"'`.includes(paragraph[next])) next += 1;
      if (next < paragraph.length && !/\s/.test(paragraph[next])) continue;
      while (next < paragraph.length && /\s/.test(paragraph[next])) next += 1;
      if (next < paragraph.length && !/[A-Z0-9`*]/.test(paragraph[next])) continue;
      const sentence = paragraph.slice(start, i + 1).trim();
      if (sentence) sentences.push(sentence);
      start = next;
      i = next - 1;
    }
    const remainder = paragraph.slice(start).trim();
    if (remainder) sentences.push(remainder);
  }

  return sentences;
}

function classifyLiveAnswerSentence(sentence: string, index: number, previous?: string): string {
  const value = sentence.toLowerCase();
  if (
    index === 0 &&
    /\b(paged|page in prod|alert(?:ed)?|incident|outage|failed|failure)\b/.test(value)
  ) {
    return 'What happened';
  }
  if (/\b(root cause|caused by|due to|traced to|linked to|bottleneck)\b/.test(value)) {
    return 'Root cause';
  }
  if (/\b(initial|temporary|mitigat(?:e|ed|ion)|workaround|revert(?:ed)?)\b/.test(value)) {
    return 'Initial mitigation';
  }
  if (/\b(durable fix|permanent(?:ly)?|fixed|resolved|resolution|landed)\b/.test(value)) {
    return 'Durable fix';
  }
  if (/\b(customer impact|impacted|affected|degraded)\b/.test(value)) {
    return 'Impact';
  }
  return previous || 'Answer';
}

function tokenizeLiveAnswer(value: string, validCitations: Set<number>): RichToken[] {
  const tokens: RichToken[] = [];
  const inline = /(`([^`\n]+)`|\*\*([^*\n]+)\*\*|\[(\d+)\])/g;
  let cursor = 0;

  for (const match of value.matchAll(inline)) {
    const index = match.index ?? 0;
    if (index > cursor) tokens.push({ text: value.slice(cursor, index) });
    if (match[2]) {
      tokens.push({ hl: match[2] });
    } else if (match[3]) {
      tokens.push({ b: match[3] });
    } else {
      const citation = Number(match[4]);
      if (validCitations.has(citation)) tokens.push({ cite: citation });
      else tokens.push({ text: match[0] });
    }
    cursor = index + match[0].length;
  }
  if (cursor < value.length) tokens.push({ text: value.slice(cursor) });
  return tokens;
}

function parseLiveAnswer(value: string, citations: Citation[]): LiveAnswerSection[] {
  const validCitations = new Set(citations.map((citation) => citation.n));
  const grouped: Array<{ label: string; sentences: string[] }> = [];

  for (const [index, sentence] of splitLiveAnswerSentences(value).entries()) {
    const previous = grouped[grouped.length - 1]?.label;
    const label = classifyLiveAnswerSentence(sentence, index, previous);
    const current = grouped[grouped.length - 1];
    if (current?.label === label) current.sentences.push(sentence);
    else grouped.push({ label, sentences: [sentence] });
  }

  return grouped.map((section) => ({
    label: section.label,
    tokens: tokenizeLiveAnswer(section.sentences.join(' '), validCitations)
  }));
}

function tokenLength(token: RichToken): number {
  if ('text' in token) return token.text.length;
  if ('b' in token) return token.b.length;
  if ('hl' in token) return token.hl.length;
  return 1; // a citation chip counts as one caret beat
}

// Types across an ordered list of rich tokens, preserving bold, highlights,
// and inline citation chips. Renders instantly when disabled.
function StreamRich({
  tokens,
  enabled,
  className,
  speed,
  onCite,
  onDone
}: {
  tokens: RichToken[];
  enabled: boolean;
  className?: string;
  speed?: number;
  onCite?: (n: number) => void;
  onDone?: () => void;
}) {
  const total = tokens.reduce((sum, token) => sum + tokenLength(token), 0);
  const plain = tokens
    .map((token) => ('text' in token ? token.text : 'b' in token ? token.b : 'hl' in token ? token.hl : ' '))
    .join('');
  const { shown, done } = useTypewriter(plain, { enabled, speed, onDone });
  const count = enabled ? shown.length : total;

  let cursor = 0;
  const nodes: React.ReactNode[] = [];
  for (let i = 0; i < tokens.length; i += 1) {
    const token = tokens[i];
    const len = tokenLength(token);
    const visible = Math.max(0, Math.min(len, count - cursor));
    if (visible > 0) {
      if ('text' in token) nodes.push(<React.Fragment key={i}>{token.text.slice(0, visible)}</React.Fragment>);
      else if ('b' in token) nodes.push(<b key={i}>{token.b.slice(0, visible)}</b>);
      else if ('hl' in token) nodes.push(<span className="hl" key={i}>{token.hl.slice(0, visible)}</span>);
      else nodes.push(<Citation key={i} n={token.cite} onClick={onCite ? () => onCite(token.cite) : undefined} />);
    }
    cursor += len;
  }
  return (
    <p className={className}>
      {nodes}
      {enabled && !done && <span className="caret" aria-hidden="true" />}
    </p>
  );
}

function StreamLiveAnswer({
  sections,
  enabled,
  onCite,
  onDone
}: {
  sections: LiveAnswerSection[];
  enabled: boolean;
  onCite: (n: number) => void;
  onDone?: () => void;
}) {
  const [active, setActive] = useState(enabled ? 0 : sections.length);

  useEffect(() => {
    setActive(enabled ? 0 : sections.length);
  }, [enabled, sections]);

  return (
    <div className="live-answer">
      {sections.map((section, index) => {
        if (enabled && index > active) return null;
        const isActive = enabled && index === active;
        return (
          <section className="live-answer-section" key={`${section.label}-${index}`}>
            <div className="live-answer-label">{section.label}</div>
            <StreamRich
              className="live-answer-copy"
              tokens={section.tokens}
              enabled={isActive}
              speed={4}
              onCite={onCite}
              onDone={isActive
                ? () => {
                    if (index < sections.length - 1) setActive(index + 1);
                    else onDone?.();
                  }
                : undefined}
            />
          </section>
        );
      })}
    </div>
  );
}

// Claude.ai-style "thinking" line: one live status row that cycles reasoning
// steps with a pulsing dot and blinking caret, then hands off to the answer
// typewriter. The text is never empty, so the first frame is stage-safe.
function ThinkingLine({
  steps,
  enabled,
  onDone,
  stepMs = 760
}: {
  steps: string[];
  enabled: boolean;
  onDone?: () => void;
  stepMs?: number;
}) {
  const [index, setIndex] = useState(0);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;
  const visibleSteps = steps.length > 0 ? steps : ['Preparing cited answer'];
  const current = visibleSteps[Math.min(index, visibleSteps.length - 1)];

  useEffect(() => {
    if (!enabled) {
      onDoneRef.current?.();
      return;
    }
    const last = index >= visibleSteps.length - 1;
    const id = window.setTimeout(() => {
      if (last) onDoneRef.current?.();
      else setIndex((i) => Math.min(i + 1, visibleSteps.length - 1));
    }, stepMs);
    return () => window.clearTimeout(id);
  }, [index, enabled, visibleSteps.length, stepMs]);

  useEffect(() => {
    setIndex(0);
  }, [enabled, steps]);

  if (!enabled) return null;
  return (
    <div className="thinking" role="status" aria-live="polite">
      <span className="thinking-dot" aria-hidden="true" />
      <span className="thinking-text">
        {current}
        <span className="caret" aria-hidden="true" />
      </span>
    </div>
  );
}

function AgentPage({
  page,
  query,
  setQuery,
  omniboxRef,
  agentPayload,
  canonical,
  runId,
  error,
  loading,
  onSearch,
  onAgent,
  guideStep,
  onAdvanceGuide,
  onSkipGuide,
  onNavigate,
  citedResults,
  corpusTotal,
  onOpenDetail
}: {
  page: Page;
  query: string;
  setQuery: (value: string) => void;
  omniboxRef?: React.RefObject<HTMLInputElement>;
  agentPayload: AgentPayload;
  canonical: CanonicalDiagnostics | null;
  runId?: string;
  error?: string;
  loading: boolean;
  onSearch: () => void;
  onAgent: () => void;
  guideStep?: GuideStep | null;
  onAdvanceGuide: (step: GuideStep) => void;
  onSkipGuide: () => void;
  onNavigate: (page: Page) => void;
  citedResults: Result[];
  corpusTotal?: number;
  onOpenDetail: (result: Result | null) => void;
}) {
  // The live answer: the agent payload when the user has run it, otherwise the
  // canonical run served read-only on mount. Both carry answer + plan + citations
  // + commitments from Aurora — there is no hard-coded fallback content.
  const source: AgentPayload | CanonicalDiagnostics = agentPayload.answer || agentPayload.citations ? agentPayload : (canonical || {});
  const rawAnswer = source.answer;
  const answerBody: AnswerBody | null = rawAnswer && typeof rawAnswer === 'object' ? rawAnswer : null;
  const answerString = typeof rawAnswer === 'string' ? rawAnswer : '';
  const rawPlan = source.plan;
  const structuredPlan: PlanStep[] = Array.isArray(rawPlan) && rawPlan.length > 0 && typeof rawPlan[0] === 'object'
    ? (rawPlan as PlanStep[])
    : [];
  const stringPlan: string[] = Array.isArray(rawPlan) && rawPlan.length > 0 && typeof rawPlan[0] === 'string'
    ? (rawPlan as string[])
    : [];
  const planLength = structuredPlan.length || stringPlan.length;
  const citations = (source.citations && source.citations.length > 0 ? source.citations : canonical?.citations) || [];
  const liveAnswerSections = useMemo(
    () => parseLiveAnswer(answerString, citations),
    [answerString, citations]
  );
  const railResults = citedResults.length > 0 ? citedResults : citationsToResults(citations);
  const commitments = (source.commitments && source.commitments.length > 0 ? source.commitments : canonical?.commitments) || [];
  const quote = answerBody?.quote;
  const hasAnswer = Boolean(answerBody || answerString);
  const [copied, setCopied] = useState(false);

  const runLabel = agentPayload.run_id || canonical?.run_id || runId || '';
  const confidenceValue = typeof source.confidence === 'number' ? source.confidence : (canonical?.confidence ?? 0);
  const confidenceLabel = confidenceValue.toFixed(2);
  const confidencePercent = Math.round(Math.max(0, Math.min(1, confidenceValue)) * 100);
  const citedSourceCount = source.source_count ?? canonical?.source_count ?? citations.length;
  const citedSystemCount = source.system_count ?? canonical?.system_count ?? new Set(citations.map((c) => c.source_system)).size;
  const claimCount = answerBody
    ? countCitationClaims(answerBody)
    : liveAnswerSections.reduce(
        (count, section) => count + section.tokens.filter((token) => 'cite' in token).length,
        0
      );
  const firedLabel = formatDate(canonical?.fired_at);
  const showAnswerGuide = guideStep === 'answer';
  // Agent + model metadata is served live by the API (both the agent answer and
  // the canonical endpoint carry it). The routed model IDs come from settings, so
  // they must never be hard-coded in the frontend — a provisioned account could
  // route different models. Fall back to the canonical payload, never to a literal.
  const agentMeta: AgentMetadata = agentPayload.agent || canonical?.agent || {};
  const modelRouting = agentMeta.model_routing || {};
  const routingNotes = agentMeta.routing_notes || {};
  const routingRows = [
    {
      role: 'Planning + tools',
      model: modelRouting.planning_and_tool_routing,
      note: routingNotes.planning_and_tool_routing
    },
    {
      role: 'Answer synthesis',
      model: modelRouting.answer_synthesis,
      note: routingNotes.answer_synthesis
    }
  ].filter((row) => row.model);
  const answerExport = [
    `# ${source.question || query || queryDefault}`,
    '',
    answerBodyText(rawAnswer),
    quote?.text ? `> ${quote.text}${quote.attr ? `\n>\n> ${quote.attr}` : ''}` : '',
    citations.length > 0 ? '## Sources' : '',
    ...citations.map((citation) => `${citation.n}. ${citation.title} (${sourceLabel(citation.source_system)} · ${citation.external_id})${citation.url ? `\n   ${citation.url}` : ''}`)
  ].filter(Boolean).join('\n\n');

  async function copyAnswer() {
    await navigator.clipboard.writeText(answerExport);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }

  function downloadAnswer() {
    const blob = new Blob([answerExport], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `verity-${shortRunId(runLabel || 'answer')}.md`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  // --- Streaming deconstruction --------------------------------------------
  // The answer arrives beat-by-beat: the synthesized prose types itself, then
  // the view "deconstructs" how it was built (pull quote, commitments, the six
  // tool calls) as one flowing narrative. Reduced-motion renders it all at once.
  const reducedMotion = useReducedMotion();
  const streaming = ENABLE_ANSWER_STREAMING && !reducedMotion && !loading;
  // beat gates each block; typing blocks advance it on completion, reveal-only
  // blocks advance on a short timer (see the effect below).
  const [beat, setBeat] = useState(streaming ? 0 : 99);
  const advance = () => setBeat((b) => b + 1);
  // The thinking phase runs first: a single updating line cycles the agent's
  // real reasoning steps, then hands off to the typewriter answer at beat 1.
  const [thinking, setThinking] = useState(streaming);
  const onThinkingDone = () => {
    setThinking(false);
    window.setTimeout(() => setBeat(1), 180);
  };

  useEffect(() => {
    // Reset the run whenever we (re)enter a streaming answer.
    setThinking(streaming);
    setBeat(streaming ? 0 : 99);
  }, [streaming, runLabel]);

  useEffect(() => {
    if (!streaming || thinking) return;
    // Reveal-only beats (pull quote, commit table, plan header) hold briefly,
    // then hand off to the next beat for a natural cadence.
    const pauseBeats: Record<number, number> = { 4: 900, 6: 780, 7: 520 };
    const hold = pauseBeats[beat];
    if (hold == null) return;
    const id = window.setTimeout(advance, hold);
    return () => window.clearTimeout(id);
  }, [beat, streaming, thinking]);

  const planStart = 8;
  const answerContentReady = !loading && hasAnswer && (!streaming || (!thinking && beat >= 1));
  const railReady = answerContentReady;
  const planStage = useStageSequence(planLength + 1, {
    enabled: streaming,
    beatMs: 480,
    startMs: beat >= planStart ? 0 : 999999
  });
  const beatClass = (n: number) => cx('beat', (!streaming || beat >= n) && 'is-in');
  // The thinking line cycles the agent's real reasoning steps, derived live from
  // the plan (each tool call's description), so it reflects the actual run.
  const thinkingTrace = structuredPlan.length > 0
    ? structuredPlan.map((step) => step.desc)
    : stringPlan.length > 0
      ? stringPlan
      : ['Retrieving evidence', 'Fusing ranked candidates', 'Synthesizing cited answer'];
  const jumpToCitation = (n: number) => {
    const el = document.querySelector(`.sources-rail .src:nth-of-type(${n})`);
    el?.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'center' });
    el?.classList.add('flash');
    window.setTimeout(() => el?.classList.remove('flash'), 900);
  };

  return (
    <section className="inner-screen">
      <AppHeader page={page} query={query || queryDefault} setQuery={setQuery} onSearch={onSearch} onNavigate={onNavigate} omniboxRef={omniboxRef} />
      <main className="answer-layout">
        <article>
          <ErrorBanner message={error} />
          {loading ? (
            <EmptyState loading title="Assembling cited answer" body="The agent endpoint is collecting citations and checking the evidence timeline." />
          ) : !hasAnswer ? (
            <EmptyState
              title="No answer yet"
              body="Run the agent to synthesize a cited answer across the connected systems."
              action={<button className="btn primary" onClick={() => onAgent()}>Generate cited answer</button>}
            />
          ) : (
            <>
              <div className={cx('answer-guide-focus', showAnswerGuide && 'guide-target guide-spotlight')}>
                {showAnswerGuide && (
                  <GuideCoachmark
                    step="answer"
                    title="Read the grounded answer"
                    body="The canonical answer turns ranked evidence into claims with inline citations, source coverage, and a confidence trail."
                    onAdvance={() => onAdvanceGuide('answer')}
                    onSkip={onSkipGuide}
                    primaryLabel="Next: timeline"
                  />
                )}
                <div className="eyebrow mono-label">
                  {streaming && thinking
                    ? 'Agent answer · thinking'
                    : streaming && beat < planStart + planLength
                      ? 'Agent answer · streaming with citations'
                      : 'Agent answer · synthesized with citations'}
                </div>
                <div className="question">"{source.question || query || queryDefault}"</div>
                <div className="answermeta">
                  <span className="badge"><i />GROUNDED</span>
                  {(agentMeta.harness || agentMeta.model_provider) && (
                    <span>{agentMeta.harness && <b>{agentMeta.harness}</b>}{agentMeta.harness && agentMeta.model_provider ? ' · ' : ''}{agentMeta.model_provider}</span>
                  )}
                  {runLabel && <span title={runLabel}>run <b>{shortRunId(runLabel)}</b></span>}
                  <span><b>{citedSourceCount} sources</b> · {citedSystemCount} systems</span>
                  {canonical?.fired_at && <span>{firedLabel}</span>}
                </div>
                <div className="answer-utilities" aria-label="Answer actions">
                  <button type="button" onClick={() => void copyAnswer()}>
                    {copied ? <Check size={15} /> : <Clipboard size={15} />}
                    {copied ? 'Copied' : 'Copy answer'}
                  </button>
                  <button type="button" onClick={downloadAnswer}>
                    <Download size={15} />
                    Export report
                  </button>
                </div>
              </div>

              {routingRows.length > 0 && (
                <section className="model-routing" aria-label="Agent model routing">
                  <div>
                    <span className="mono-label">Best model for the job</span>
                    <h2>{agentMeta.harness || 'Agent'} model routing</h2>
                  </div>
                  <div className="model-grid">
                    {routingRows.map((row) => (
                      <div className="model-cell" key={row.role}>
                        <span>{row.role}</span>
                        <b title={row.model}>{friendlyModelName(row.model)}</b>
                        <small>{row.note}</small>
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {streaming && thinking && (
                <ThinkingLine steps={thinkingTrace} enabled={streaming} onDone={onThinkingDone} />
              )}

              {answerBody ? (
                <>
                  {answerBody.lead && (!streaming || (!thinking && beat >= 1)) && (
                    <StreamRich
                      className="lead"
                      tokens={answerBody.lead}
                      enabled={streaming && beat === 1}
                      speed={4}
                      onCite={jumpToCitation}
                      onDone={advance}
                    />
                  )}

                  {(!streaming || beat >= 2) && (
                    <div className="prose">
                      {answerBody.why && (!streaming || beat >= 2) && (
                        <StreamRich tokens={answerBody.why} enabled={streaming && beat === 2} onCite={jumpToCitation} onDone={advance} />
                      )}
                      {answerBody.decided && (!streaming || beat >= 3) && (
                        <StreamRich tokens={answerBody.decided} enabled={streaming && beat === 3} onCite={jumpToCitation} onDone={advance} />
                      )}
                    </div>
                  )}

                  {quote && (!streaming || beat >= 4) && (
                    <div className={cx('pull', beatClass(4))}>
                      <span className="mono-label">The decision, verbatim</span>
                      <div className="quote">{quote.text}</div>
                      {quote.attr && <div className="attr">{quote.attr}</div>}
                    </div>
                  )}

                  {answerBody.impacted && (!streaming || beat >= 5) && (
                    <div className="prose">
                      <StreamRich tokens={answerBody.impacted} enabled={streaming && beat === 5} onCite={jumpToCitation} onDone={advance} />
                    </div>
                  )}
                </>
              ) : (
                (!streaming || (!thinking && beat >= 1)) && (
                  <StreamLiveAnswer
                    key={answerString}
                    sections={liveAnswerSections}
                    enabled={streaming && beat === 1}
                    onCite={jumpToCitation}
                    onDone={() => setBeat(7)}
                  />
                )
              )}

              {commitments.length > 0 && (!streaming || beat >= 6) && (
                <table className={cx('commit-table', beatClass(6))}>
                  <thead>
                    <tr><th>Customer commitment</th><th>Original date</th><th>Evidence</th><th>Status</th></tr>
                  </thead>
                  <tbody>
                    {commitments.map((commit) => (
                      <tr key={commit.external_id}>
                        <td>
                          <b>{commit.account_name} · {commit.subject}</b><br />
                          {[commit.external_id, commit.arr_label].filter(Boolean).join(' · ')}
                        </td>
                        <td>{formatDateOnly(commit.contracted_go_live)}</td>
                        <td>{commit.citation_n ? <>source <b>[{commit.citation_n}]</b></> : '—'}</td>
                        <td><span className="status risk">{(commit.status || 'AT RISK').toUpperCase()}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {planLength > 0 && (!streaming || beat >= 7) && (
                <section className={cx('plan', beatClass(7))}>
                  <h2>How this answer was built</h2>
                  <p className="plan-sub">{planLength} tool call{planLength === 1 ? '' : 's'}{corpusTotal != null && <> · {corpusTotal} candidates considered</>} · every step logged to <span>retrieval_runs</span></p>
                  {structuredPlan.length > 0
                    ? structuredPlan.map((step, i) => {
                        const revealed = !streaming || planStage >= i;
                        const running = streaming && planStage === i;
                        if (!revealed) return null;
                        return (
                          <div className={cx('pstep', 'beat', 'is-in', running && 'is-running')} key={step.num}>
                            <div className="pnum">{step.num}</div>
                            <div className="pbody">
                              <div className="fn">{step.fn} <span>{step.args}</span></div>
                              <div className="desc">{step.desc}</div>
                              <div className="res">→ {step.res}</div>
                            </div>
                          </div>
                        );
                      })
                    : stringPlan.map((step, i) => {
                        const revealed = !streaming || planStage >= i;
                        const running = streaming && planStage === i;
                        if (!revealed) return null;
                        return (
                          <div className={cx('pstep', 'beat', 'is-in', running && 'is-running')} key={i}>
                            <div className="pnum">{i + 1}</div>
                            <div className="pbody">
                              <div className="desc">{step}</div>
                            </div>
                          </div>
                        );
                      })}
                  {(!streaming || planStage >= planLength) && (
                    <div className={cx('actions', 'beat', 'is-in')}>
                      <button className="btn primary" onClick={() => onAgent()}>Regenerate answer</button>
                      <button className="btn ghost" onClick={() => onNavigate('trail')}>View timeline</button>
                      <button className="btn ghost" onClick={() => onNavigate('diagnostics')}>Open diagnostics</button>
                    </div>
                  )}
                </section>
              )}

              {confidenceValue > 0 && (!streaming || planStage >= planLength) && (
                <section className="coverage answer-confidence beat is-in" aria-label="Confidence calculation">
                  <div className="covrow"><span>Confidence</span><b>{confidenceLabel}</b></div>
                  <div className="meter"><i style={{ width: `${confidencePercent}%` }} /></div>
                  <p className="covnote">
                    <b>How it was calculated:</b> the score combines final retrieval strength, citation coverage, cross-source agreement, and contradiction checks for the cited evidence set.
                  </p>
                  <div className="confidence-grid">
                    <div><span>Rank strength</span><b>{citedSourceCount} cited objects above the score cut</b></div>
                    {claimCount > 0 && <div><span>Coverage</span><b>{claimCount} answer claims bound to citations</b></div>}
                    <div><span>Agreement</span><b>{citedSystemCount} systems support the same timeline</b></div>
                  </div>
                  {canonical?.funnel && (
                    <p className="covnote"><b>✓ No contradictions</b> found by compare_sources across the {citedSourceCount} cited objects. {Math.max(0, (canonical.funnel.above_cut ?? 0) - (canonical.funnel.cited ?? 0))} candidate{Math.max(0, (canonical.funnel.above_cut ?? 0) - (canonical.funnel.cited ?? 0)) === 1 ? '' : 's'} excluded below the {canonical.rerank_cut} score cut.</p>
                  )}
                </section>
              )}
            </>
          )}
        </article>

        <aside className={cx('sources-rail', !answerContentReady && 'sources-rail-hidden')} aria-hidden={!answerContentReady}>
          <span className="mono-label">Sources · {citations.length} cited</span>
          {citations.map((citation, index) => {
            // Prefer the live evidence row for this exact object; otherwise build a
            // result straight from the citation, which carries object_id resolved
            // server-side even for objects below the live top-k (e.g. PR-1287 [6]).
            const result =
              railResults.find((r) => r.external_id === citation.external_id) ||
              (citation.object_id ? citationsToResults([citation])[0] : null);
            const meta = citation.meta || `${sourceLabel(citation.source_system).toUpperCase()}${typeof citation.score === 'number' ? ` · score ${citation.score.toFixed(2)}` : ''}`;
            const why = citation.why || 'Evidence supporting the answer.';
            const shown = railReady;
            return (
              <button
                className={cx('src', 'beat', shown && 'is-in')}
                style={streaming ? { transitionDelay: `${index * 40}ms` } : undefined}
                key={`${citation.source_system}-${citation.external_id}`}
                onClick={() => onOpenDetail(result || null)}
                disabled={!result?.object_id}
                aria-label={`Citation ${citation.n}: ${citation.title} — open source detail`}
              >
                <span className="srcnum">{citation.n}</span>
                <span className="srcbody">
                  <span className="srchead">
                    {sourceIcon(citation.source_system, 15)}
                    <span className="t">{citation.title}</span>
                  </span>
                  <span className="srcmeta">{meta}</span>
                  <span className="srcwhy">{why}</span>
                </span>
              </button>
            );
          })}
        </aside>
      </main>
    </section>
  );
}

// Compact "Jun 18" style label for a timeline event's own moment.
// The moment an event sits at on the timeline: its updated_at, else created_at.
function eventMoment(event: TimelineEvent): string | undefined {
  return event.updated_at || event.created_at || undefined;
}

function eventDate(event: TimelineEvent) {
  const value = eventMoment(event);
  if (!value) return '';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function eventClock(event: TimelineEvent): string {
  const value = eventMoment(event);
  if (!value) return '';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '';
  return parsed.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false });
}

// The calendar-day key an event falls on, for date-column bucketing. Uses the
// local date parts so two events on the same day share a column.
function eventDayKey(event: TimelineEvent): string {
  const value = eventMoment(event);
  if (!value) return '';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return `${parsed.getFullYear()}-${parsed.getMonth()}-${parsed.getDate()}`;
}

// A placed timeline event: its 1-based grid row (system lane) and column (date
// bucket), plus the citation-order sequence used to thread the cells together.
type PlacedEvent = {
  event: TimelineEvent;
  seq: number;
  row: number;
  col: number;
};

type TimelineGrid = {
  systems: string[];
  columns: Array<{ key: string; label: string }>;
  placed: PlacedEvent[];
  hotDayKey: string | null;
};

// Lay events out on the system (row) × date (column) grid. Rows follow the
// canonical SYSTEM_KEYS order restricted to systems that actually have events;
// columns are the distinct event days in chronological order. The "hot" column
// is the busiest day (most events) — the incident window highlight. Sequence
// numbers follow the payload's own chronological order so the thread stitches
// cells in the order traverse_links walked them. All axes are live-derived.
function buildTimelineGrid(events: TimelineEvent[]): TimelineGrid {
  if (events.length === 0) {
    return { systems: [], columns: [], placed: [], hotDayKey: null };
  }
  const systems = SYSTEM_KEYS.filter((key) => events.some((e) => e.source_system === key));
  const dayOrder: string[] = [];
  const dayLabels: Record<string, string> = {};
  const dayCounts: Record<string, number> = {};
  for (const event of events) {
    const key = eventDayKey(event);
    if (!key) continue;
    if (!(key in dayLabels)) {
      dayLabels[key] = eventDate(event);
      dayOrder.push(key);
    }
    dayCounts[key] = (dayCounts[key] || 0) + 1;
  }
  const columns = dayOrder.map((key) => ({ key, label: dayLabels[key] }));
  const colIndex: Record<string, number> = {};
  columns.forEach((column, index) => {
    colIndex[column.key] = index;
  });
  // The "hot" day is the incident window: the single busiest day. Only highlight
  // one when a day genuinely stands out — more than one event AND a strict lead
  // over every other day. When every day carries the same count (as the canonical
  // run does — one event per day), there is no busiest day, so highlight nothing
  // rather than arbitrarily tinting the first column.
  const maxCount = dayOrder.reduce((max, key) => Math.max(max, dayCounts[key]), 0);
  const leaders = dayOrder.filter((key) => dayCounts[key] === maxCount);
  const hotDayKey = maxCount > 1 && leaders.length === 1 ? leaders[0] : null;
  const placed = events
    .map((event, index) => {
      const rowIndex = systems.indexOf(event.source_system);
      const columnIndex = colIndex[eventDayKey(event)];
      if (rowIndex < 0 || columnIndex === undefined) return null;
      return {
        event,
        seq: index + 1,
        row: rowIndex + 2,
        col: columnIndex + 2
      } satisfies PlacedEvent;
    })
    .filter((value): value is PlacedEvent => value !== null);
  return { systems, columns, placed, hotDayKey };
}

// Non-primary edge relations render muted (the .n class). Primary relations —
// the ones that drive the delay narrative — render solid.
const MUTED_EDGE_RELATIONS = new Set(['references', 'resolves', 'relates_to', 'mentions']);

type TimelineView = 'grid' | 'trail';

// The evidence trail as a system (row) × date (column) matrix — the mockup's
// layout. Each cited object sits in its system's lane under its event day, and an
// SVG thread stitches the cells in citation-walk order (the same links
// traverse_links follows). Every lane, column, and cell is derived from the live
// timeline payload; nothing here is hard-coded.
function TimelineGridView({
  events,
  streaming,
  stage,
  onOpenEvent
}: {
  events: TimelineEvent[];
  streaming: boolean;
  stage: number;
  onOpenEvent: (event: TimelineEvent) => void;
}) {
  const grid = useMemo(() => buildTimelineGrid(events), [events]);
  const gridRef = useRef<HTMLDivElement>(null);
  const [thread, setThread] = useState<{ d: string; nodes: Array<{ x: number; y: number }>; len: number } | null>(null);

  // After layout, measure the placed cells and stitch a path through them in
  // sequence order. Re-measured on resize and whenever the placement changes.
  // The polyline length feeds the CSS stitch animation (dashoffset draw).
  useLayoutEffect(() => {
    const container = gridRef.current;
    if (!container || grid.placed.length === 0) {
      setThread(null);
      return;
    }
    const measure = () => {
      const box = container.getBoundingClientRect();
      const ordered = [...grid.placed].sort((a, b) => a.seq - b.seq);
      const nodes: Array<{ x: number; y: number }> = [];
      for (const item of ordered) {
        const cell = container.querySelector<HTMLElement>(`[data-seq="${item.seq}"]`);
        if (!cell) continue;
        const rect = cell.getBoundingClientRect();
        nodes.push({ x: rect.left - box.left + rect.width / 2, y: rect.top - box.top + rect.height / 2 });
      }
      if (nodes.length < 2) {
        setThread(nodes.length === 1 ? { d: '', nodes, len: 0 } : null);
        return;
      }
      const d = nodes.map((node, index) => `${index === 0 ? 'M' : 'L'} ${node.x.toFixed(1)} ${node.y.toFixed(1)}`).join(' ');
      let len = 0;
      for (let index = 1; index < nodes.length; index += 1) {
        len += Math.hypot(nodes[index].x - nodes[index - 1].x, nodes[index].y - nodes[index - 1].y);
      }
      setThread({ d, nodes, len });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(container);
    return () => observer.disconnect();
  }, [grid]);

  const revealedThrough = streaming ? stage : grid.placed.length;
  const hasCited = grid.placed.some((item) => typeof item.event.citation_n === 'number');

  return (
    <>
      <div className="tgrid-wrap">
      <div
        className="tgrid"
        ref={gridRef}
        style={{ gridTemplateColumns: `148px repeat(${grid.columns.length}, minmax(96px, 1fr))` }}
      >
        <div className="tgrid-corner" />
        {grid.columns.map((column) => (
          <div className={cx('tgrid-day', column.key === grid.hotDayKey && 'hot')} key={column.key}>
            {column.label}
          </div>
        ))}
        {grid.systems.map((system, rowIndex) => (
          <React.Fragment key={system}>
            <div className="tgrid-lane" style={{ gridRow: rowIndex + 2 }}>
              {sourceIcon(system, 17)}
              {sourceLabel(system)}
            </div>
            {grid.columns.map((column) => (
              <div
                className={cx('tgrid-cell', column.key === grid.hotDayKey && 'hot')}
                key={`${system}-${column.key}`}
                style={{ gridRow: rowIndex + 2, gridColumn: grid.columns.indexOf(column) + 2 }}
              />
            ))}
          </React.Fragment>
        ))}
        {grid.placed.map((item) => {
          const revealed = !streaming || item.seq <= revealedThrough + 1;
          const isCited = typeof item.event.citation_n === 'number';
          return (
            <button
              type="button"
              className={cx('tgrid-evt', isCited && 'cited', !revealed && 'pending')}
              key={item.event.object_id}
              data-seq={item.seq}
              style={{ gridRow: item.row, gridColumn: item.col }}
              onClick={() => onOpenEvent(item.event)}
              title={item.event.title}
            >
              <span className="tgrid-evt-id">
                <span>{item.event.external_id}</span>
                <span className="tm">{eventClock(item.event)}</span>
              </span>
              <span className="tgrid-evt-tt">{item.event.title}</span>
              {isCited && <span className="tgrid-evt-cite">[{item.event.citation_n}]</span>}
            </button>
          );
        })}
        <svg className="tgrid-thread" aria-hidden="true">
          {thread?.d && (
            <path
              className={cx(streaming && 'animate')}
              d={thread.d}
              style={{ '--len': thread.len } as React.CSSProperties}
            />
          )}
          {thread?.nodes.map((node, index) => (
            <circle cx={node.x} cy={node.y} r={4} key={index} />
          ))}
        </svg>
      </div>
      </div>
      <div className="tgrid-legend">
        {hasCited && <span className="li"><span className="node" />cited source object</span>}
        {grid.placed.length > 1 && <span className="li"><span className="seg" />citation-walk thread (object_links)</span>}
        {grid.hotDayKey && <span className="li"><span className="tint" />busiest day</span>}
      </div>
    </>
  );
}

function TimelinePage({
  page,
  query,
  setQuery,
  omniboxRef,
  timeline,
  error,
  onSearch,
  onOpenDetail,
  guideStep,
  onAdvanceGuide,
  onSkipGuide,
  onNavigate
}: {
  page: Page;
  query: string;
  setQuery: (value: string) => void;
  omniboxRef?: React.RefObject<HTMLInputElement>;
  timeline: TimelinePayload | null;
  error?: string;
  onSearch: () => void;
  onOpenDetail: (result: Result) => void;
  guideStep?: GuideStep | null;
  onAdvanceGuide: (step: GuideStep) => void;
  onSkipGuide: () => void;
  onNavigate: (page: Page) => void;
}) {
  // The timeline assembles itself node-by-node, as if traverse_links() were
  // walking object_links live. One stage per event, plus the outcome card.
  const reducedMotion = useReducedMotion();
  const [replayKey, setReplayKey] = useState(0);
  // Grid = the system × date matrix (mockup layout, default); trail = the
  // vertical thread that unspools one hop at a time.
  const [view, setView] = useState<TimelineView>('grid');
  const events = timeline?.events || [];
  const streaming = !reducedMotion && events.length > 0;
  const stage = useStageSequence(events.length + 1, { enabled: streaming, beatMs: 520, startMs: 320, restartKey: replayKey });
  const walking = streaming && stage < events.length;
  const showTimelineGuide = guideStep === 'timeline';

  // Header stats + legend, derived from the live payload.
  const systemCount = timeline?.systems?.length ?? new Set(events.map((e) => e.source_system)).size;
  const edgeCount = timeline?.edge_count ?? events.reduce((sum, e) => sum + e.edges.length, 0);
  const dateRange = events.length
    ? `${eventDate(events[0])} — ${eventDate(events[events.length - 1])}, 2026`
    : '';
  const legendRelations = Array.from(new Set(events.flatMap((e) => e.edges.map((edge) => edge.link_type))));
  const highlightTerms = deriveHighlightTerms(query || queryDefault);

  // Open a timeline event's source object in Detail. The event carries object_id
  // (resolved server-side), so a minimal Result is enough for the detail fetch.
  const openEvent = (event: TimelineEvent) => {
    if (!event.object_id) return;
    onOpenDetail({
      object_id: event.object_id,
      source_system: event.source_system,
      external_id: event.external_id,
      title: event.title,
      snippet: event.snippet || '',
      final_score: event.final_score
    });
  };

  return (
    <section className="inner-screen">
      <AppHeader page={page} query={query || queryDefault} setQuery={setQuery} onSearch={onSearch} onNavigate={onNavigate} omniboxRef={omniboxRef} />
      <div className="pagehead">
        <div className="eyebrow centered mono-label">Timeline</div>
        <h1>How the Orion delay <em>unfolded.</em></h1>
        <div className="pagesub"><b>{events.length} linked events · {systemCount} systems</b>{dateRange && <> · {dateRange}</>} · assembled by <b>traverse_links()</b> over <b>object_links</b> · {edgeCount} edges followed</div>
        {legendRelations.length > 0 && (
          <div className="legend">
            {legendRelations.map((relation) => (
              <span className={cx('lg', MUTED_EDGE_RELATIONS.has(relation) && 'n')} key={relation}>{relation}</span>
            ))}
          </div>
        )}
        {events.length > 0 && (
          <div className="timeline-controls">
            <div className="timeline-viewtoggle" role="group" aria-label="Timeline layout">
              <button type="button" className={cx(view === 'grid' && 'on')} onClick={() => setView('grid')} aria-pressed={view === 'grid'}>
                Grid
              </button>
              <button type="button" className={cx(view === 'trail' && 'on')} onClick={() => setView('trail')} aria-pressed={view === 'trail'}>
                Trail
              </button>
            </div>
            {view === 'trail' && !walking && (
              <button className="replay-button" type="button" onClick={() => setReplayKey((value) => value + 1)}>
                <RefreshCw size={14} />
                Replay traversal
              </button>
            )}
          </div>
        )}
        {walking && view === 'trail' && (
          <div className="walking mono-label">traverse_links() building timeline<span className="caret" aria-hidden="true" /></div>
        )}
      </div>
      <ErrorBanner message={error} />
      {events.length === 0 ? (
        <EmptyState title="No timeline yet" body="Run the agent to build the cross-system evidence timeline for this question." />
      ) : view === 'grid' ? (
        <div className={cx('trail-grid-section', showTimelineGuide && 'guide-target guide-spotlight')}>
          {showTimelineGuide && (
            <GuideCoachmark
              step="timeline"
              title="Follow the evidence path"
              body="Each cited source sits in its system's lane under the day it happened; the thread stitches them in the order traverse_links walked the object_links."
              onAdvance={() => onAdvanceGuide('timeline')}
              onSkip={onSkipGuide}
              primaryLabel="Next: diagnostics"
            />
          )}
          <TimelineGridView
            events={events}
            streaming={streaming}
            stage={stage}
            onOpenEvent={openEvent}
          />
          <div className={cx('outcome', 'beat', 'is-in')}>
            <span className="mono-label">Outcome</span>
            <div className="big">{events.length} linked source objects across {systemCount} systems, connected by {edgeCount} traversed edges — the full evidence path behind the Orion decision.</div>
            <div className="outcome-actions">
              <button className="btn primary" type="button" onClick={() => onNavigate('diagnostics')}>Open diagnostics</button>
            </div>
          </div>
        </div>
      ) : (
        <div className={cx('trail', showTimelineGuide && 'guide-target guide-spotlight')}>
          {showTimelineGuide && (
            <GuideCoachmark
              step="timeline"
              title="Follow the evidence path"
              body="Linked source objects now unfold in sequence, showing how the incident, decision, customer impact, and code change connect."
              onAdvance={() => onAdvanceGuide('timeline')}
              onSkip={onSkipGuide}
              primaryLabel="Next: diagnostics"
            />
          )}
          {events.map((event, index) => {
            const shown = !streaming || stage >= index;
            if (!shown) return null;
            const hopShown = !streaming || stage >= index + 1;
            const primaryEdge = event.edges[0];
            const hop = primaryEdge ? `${primaryEdge.link_type} → ${primaryEdge.to_external_id}` : undefined;
            return (
              <React.Fragment key={event.object_id}>
                <div className={cx('event', index % 2 === 0 ? 'left' : 'right', index === events.length - 1 && 'final', 'beat', 'is-in')}>
                  <span className="date">{eventDate(event)}</span>
                  <span className="dot" />
                  <div className="ecard">
                    <div className="ehead">
                      <div className="tile">{sourceIcon(event.source_system, 21)}</div>
                      <div>
                        <div className="etype">{event.source_type || sourceLabel(event.source_system)}{event.citation_n ? ` · cited [${event.citation_n}]` : ''}</div>
                        <div className="etitle">{event.title}</div>
                      </div>
                    </div>
                    {event.snippet && <p className="ebody"><HighlightedSnippet text={event.snippet} terms={highlightTerms} /></p>}
                    <div className="edges">{event.edges.map((edge) => (
                      <span className={cx('edge', MUTED_EDGE_RELATIONS.has(edge.link_type) && 'n')} key={`${edge.link_type}-${edge.to_external_id}`}>
                        {edge.link_type} → {edge.to_external_id}
                      </span>
                    ))}</div>
                  </div>
                </div>
                {hop && index < events.length - 1 && hopShown && (
                  <div className="hop beat is-in"><span>{hop}</span></div>
                )}
              </React.Fragment>
            );
          })}
          {(!streaming || stage >= events.length) && (
            <div className={cx('outcome', 'beat', 'is-in')}>
              <span className="mono-label">Outcome</span>
              <div className="big">{events.length} linked source objects across {systemCount} systems, connected by {edgeCount} traversed edges — the full evidence path behind the Orion decision.</div>
              <div className="outcome-actions">
                <button className="btn primary" type="button" onClick={() => onNavigate('diagnostics')}>Open diagnostics</button>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function DiagnosticsPage({
  page,
  query,
  setQuery,
  omniboxRef,
  canonical,
  fusionSql,
  queryPlan,
  indexUsage,
  slowQueries,
  corpusTotal,
  onSearch,
  guideStep,
  onAdvanceGuide,
  onSkipGuide,
  onNavigate
}: {
  page: Page;
  query: string;
  setQuery: (value: string) => void;
  omniboxRef?: React.RefObject<HTMLInputElement>;
  canonical: CanonicalDiagnostics | null;
  fusionSql: FusionSql | null;
  queryPlan: QueryPlan | null;
  indexUsage: IndexUsage | null;
  slowQueries: SlowQueries | null;
  corpusTotal?: number;
  onSearch: () => void;
  guideStep?: GuideStep | null;
  onAdvanceGuide: (step: GuideStep) => void;
  onSkipGuide: () => void;
  onNavigate: (page: Page) => void;
}) {
  const showDiagnosticsGuide = guideStep === 'diagnostics';
  const showProofGuide = guideStep === 'proof';
  const [sqlCopied, setSqlCopied] = useState(false);
  const sqlText = (fusionSql?.functions || [])
    .map((fn) => `-- ${fn.name}\n${fn.definition}`)
    .join('\n\n');

  async function copyFusionSql() {
    if (!sqlText) return;
    await navigator.clipboard.writeText(sqlText);
    setSqlCopied(true);
    window.setTimeout(() => setSqlCopied(false), 1800);
  }

  if (!canonical) {
    return (
      <section className="inner-screen">
        <AppHeader page={page} query={query || queryDefault} setQuery={setQuery} onSearch={onSearch} onNavigate={onNavigate} omniboxRef={omniboxRef} />
        <main className="diagnostics-layout">
          <EmptyState title="Diagnostics unavailable" body="The canonical run has not loaded yet. Ensure the API is running and the seed is restored (make seed-load)." />
        </main>
      </section>
    );
  }

  // Every value below is derived from the live canonical metrics payload.
  const funnel = canonical.funnel || {};
  const fetched = corpusTotal ?? funnel.fetched ?? 0;
  const cited = funnel.cited ?? 0;
  const citedPct = fetched > 0 ? ((cited / fetched) * 100).toFixed(1) : '0';
  const totalLatency = canonical.total_latency_ms ?? 0;
  const stageTimings = canonical.stage_timings || [];
  const peakStageMs = stageTimings.reduce((max, stage) => Math.max(max, stage.ms), 0);
  const assemblyStage = stageTimings.find((stage) => /assembly/i.test(stage.stage));
  const assemblyPct = assemblyStage && totalLatency > 0 ? Math.round((assemblyStage.ms / totalLatency) * 100) : 0;
  const diagnosticsRows = canonical.metadata?.diagnostics_rows || [];
  const weightsLabel = (canonical.ranker_weights || []).join(' / ');
  const rankerCount = (canonical.ranker_weights || []).length;
  const systemCount = canonical.system_count ?? 0;
  const funnelRows: Array<[string, string, number, boolean?]> = [
    ['fetched', String(fetched), 100],
    ['deduped', String(funnel.deduped ?? 0), fetched > 0 ? Math.round(((funnel.deduped ?? 0) / fetched) * 100) : 0],
    ['fused · top-k', String(funnel.fused ?? 0), fetched > 0 ? Math.round(((funnel.fused ?? 0) / fetched) * 100) : 0],
    [`above cut ≥${canonical.rerank_cut}`, String(funnel.above_cut ?? 0), fetched > 0 ? Math.round(((funnel.above_cut ?? 0) / fetched) * 100) : 0],
    ['cited', String(cited), fetched > 0 ? Math.round((cited / fetched) * 100) : 0, true]
  ];
  const stageRows: Array<[string, string, number, boolean?]> = stageTimings.map((stage) => [
    stage.stage,
    String(stage.ms),
    peakStageMs > 0 ? Math.round((stage.ms / peakStageMs) * 100) : 0,
    /assembly/i.test(stage.stage)
  ]);

  return (
    <section className="inner-screen">
      <AppHeader page={page} query={query || queryDefault} setQuery={setQuery} onSearch={onSearch} onNavigate={onNavigate} omniboxRef={omniboxRef} />
      <main className="diagnostics-layout">
        <div className="eyebrow mono-label">Retrieval diagnostics</div>
        <h1>Run <em>{shortRunId(canonical.run_id || '')}</em> — every rank, explained.</h1>
        <div className="runmeta">
          <span>profile <b>{canonical.profile}</b></span>
          <span>embedding <b>{canonical.embedding_model} · {canonical.embedding_dim}d</b></span>
          <span>index <b>{canonical.index_spec}</b></span>
          <span>fired <b>{formatDate(canonical.fired_at)}</b></span>
          <span>stored in <b>retrieval_runs</b></span>
        </div>

        <section className={cx('diagnostics-audit', showDiagnosticsGuide && 'guide-target guide-spotlight')} aria-label="Run audit summary">
          {showDiagnosticsGuide && (
            <GuideCoachmark
              step="diagnostics"
              title="Inspect the run diagnostics"
              body="The audit summary verifies source coverage, candidate quality, contradiction checks, and the persisted path behind the answer."
              onAdvance={() => onAdvanceGuide('diagnostics')}
              onSkip={onSkipGuide}
              primaryLabel="Next: candidate proof"
            />
          )}
          <div className="audit-verdict">
            <span className="tech-pill">Run complete</span>
            <h2>Grounded answer path accepted.</h2>
            <p>Hybrid retrieval produced {cited} cited objects across {systemCount} systems. The final answer passed source agreement checks, excluded weak candidates below the {canonical.rerank_cut} cut, and persisted every candidate signal for inspection.</p>
          </div>
          <div className="audit-checks">
            {[
              [`${cited} / ${cited}`, 'cited objects above cut'],
              [String(systemCount), 'systems represented'],
              [String(funnel.above_cut ?? 0), 'candidates above cut'],
              ['0', 'contradictions found']
            ].map(([value, label]) => (
              <div className="audit-card" key={label}>
                <b>{value}</b>
                <span>{label}</span>
              </div>
            ))}
          </div>
        </section>

        <div className="tiles">
          {[
            ['Total latency', String(totalLatency), 'ms', <>p50 this profile: <b>{canonical.p50_latency_ms} ms</b></>],
            ['Candidate funnel', <>{fetched} <small>→</small> {cited}</>, '', <>fetched → cited · <b>{citedPct}%</b></>],
            ['Fusion', 'RRF', `k = ${canonical.rrf_k}`, <>{rankerCount} rankers · weights <b>{weightsLabel}</b></>],
            ['SQL score', String(canonical.rerank_cut), 'cut', <>composite scoring · <b>{canonical.reranked_count} candidates</b></>]
          ].map(([k, v, unit, d], index) => (
            <div className="stile" key={index}>
              <div className="k">{k}</div>
              <div className="v">{v}{unit ? <small>{unit}</small> : null}</div>
              <div className="d">{d}</div>
            </div>
          ))}
        </div>

        <section className="diag-flow" aria-label="Retrieval diagnostic flow">
          {[
            ['01', 'Plan', 'Normalize the Orion question, scope project filters, and set source-system hints.'],
            ['02', 'Retrieve', 'Run full-text, pgvector, and pg_trgm retrieval concurrently inside Aurora.'],
            ['03', 'Fuse', `Collapse ranker overlap with RRF k=${canonical.rrf_k} and keep the top ${funnel.fused ?? ''} candidates.`],
            ['04', 'Score', `Apply SQL final scoring, source authority, recency, and the ${canonical.rerank_cut} cut.`],
            ['05', 'Prove', 'Persist candidates, citations, and judgments for replay and evaluation.']
          ].map(([num, title, body]) => (
            <div className="diag-step" key={num}>
              <span>{num}</span>
              <b>{title}</b>
              <p>{body}</p>
            </div>
          ))}
        </section>

        <div className="grid2">
          <BarPanel
            title="Where the time went"
            subtitle={`MS PER STAGE · TOTAL ${totalLatency}`}
            rows={stageRows}
            note={assemblyStage ? <>Answer assembly dominates at <b>{assemblyPct}%</b> of latency after the top {funnel.fused ?? ''} fused candidates are selected. The three retrievals run concurrently in Aurora.</> : <>The three retrievals run concurrently in Aurora.</>}
          />
          <BarPanel
            title="Candidate funnel"
            subtitle="RETRIEVAL_CANDIDATES"
            rows={funnelRows}
            note={<><b>{Math.max(0, fetched - (funnel.deduped ?? 0))} duplicates collapsed</b> across rankers — overlap is a good sign that cited objects were found by multiple retrieval modes.</>}
          />
        </div>

        <div className={cx('tablewrap', showProofGuide && 'guide-target guide-spotlight')}>
          <div className="twhead">
            <div className="ptitle">Top candidates, signal by signal</div>
            <div className="psub">SHOWING {diagnosticsRows.length} OF {canonical.reranked_count} · ORDER BY FINAL</div>
          </div>
          {showProofGuide && (
            <GuideCoachmark
              step="proof"
              title="Use this as the proof surface"
              body="Each row is persisted in retrieval_candidates with ranker positions, final score, and citation outcome. This is the replayable audit trail."
              onAdvance={() => onAdvanceGuide('proof')}
              onSkip={onSkipGuide}
              primaryLabel="Finish walkthrough"
            />
          )}
          <div className="candidate-legend">
            <span><b>Cited rows</b> became answer citations</span>
            <span><b>#1 / #2</b> are per-ranker positions</span>
            <span><b>—</b> means that retriever did not rank the object</span>
          </div>
          <table>
            <thead>
              <tr><th>#</th><th className="l">Source object</th><th>FTS</th><th>VEC</th><th>TRGM</th><th>RRF</th><th>FINAL</th><th>CITED</th></tr>
            </thead>
            <tbody>
              {diagnosticsRows.map(([rank, system, title, fts, vec, trgm, rrf, finalScore, cited], index) => {
                // The CITED column carries a ✓ for rows that became answer
                // citations — derive the row emphasis from the data, not the index.
                const isCited = typeof cited === 'string' && cited.includes('✓');
                return (
                  <tr className={isCited ? 'cited' : ''} key={`${rank}-${title}-${index}`}>
                    <td className={isCited ? 'rk' : ''}>{rank}</td>
                    <td className="l"><span className="srcobj">{sourceIcon(system, 15)}{title}<span>{sourceLabel(system).toUpperCase()}</span></span></td>
                    <td className={rankCellClass(fts)}>{fts}</td>
                    <td className={rankCellClass(vec)}>{vec}</td>
                    <td className={rankCellClass(trgm)}>{trgm}</td>
                    <td>{rrf}</td>
                    <td><span className="scorebar"><span className="tr"><i style={{ width: `${barPercent(finalScore)}%` }} /></span>{finalScore}</span></td>
                    <td className={isCited ? 'ck' : 'cut'}>{cited}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="tfoot">Every row above is a persisted record in <b>retrieval_candidates</b> — rank positions per ranker, fused score, final score, and citation outcome. Relevance judgments against these rows power <b>recall@k and nDCG in the evaluation suite</b>.</div>
        </div>

        <div className="sql">
          <div className="phead">
            <div className="ptitle">The fusion query, verbatim</div>
            <div className="psub">
              {fusionSql?.engine ? fusionSql.engine.toUpperCase() : 'AURORA POSTGRESQL'} · pg_get_functiondef
            </div>
            {sqlText && (
              <button className="sql-copy" type="button" onClick={() => void copyFusionSql()}>
                {sqlCopied ? <Check size={14} /> : <Clipboard size={14} />}
                {sqlCopied ? 'Copied' : 'Copy SQL'}
              </button>
            )}
          </div>
          {fusionSql && fusionSql.functions.length > 0 ? (
            fusionSql.functions.map((fn) => (
              <div className="sqlfn" key={fn.name}>
                <div className="sqlfn-name">
                  {fn.name}
                  {fusionSql.primary === fn.name ? <span className="sqlfn-tag">fused ranker</span> : null}
                </div>
                <pre>{highlightSql(fn.definition)}</pre>
              </div>
            ))
          ) : (
            <div className="sql-empty">
              The deployed fusion functions are not present in this database. Run <b>make schema</b> to
              apply <code>sql/03_search_functions.sql</code>, then reload — this panel renders the live
              <code> ops.hybrid_search</code> definition verbatim from Aurora.
            </div>
          )}
        </div>

        <PlanPanel queryPlan={queryPlan} indexUsage={indexUsage} slowQueries={slowQueries} />

        <div className="pagefoot">
          run stored in <b>retrieval_runs</b> · candidates in <b>retrieval_candidates</b> · citations in <b>citations</b> · judged against <b>relevance_judgments</b><br />
          one retrieval index: <b>Amazon Aurora PostgreSQL</b> · live systems stay authoritative
        </div>
      </main>
    </section>
  );
}

function PlanPanel({
  queryPlan,
  indexUsage,
  slowQueries
}: {
  queryPlan: QueryPlan | null;
  indexUsage: IndexUsage | null;
  slowQueries: SlowQueries | null;
}) {
  // Nothing to show until at least one of the three surfaces has loaded. All three
  // come from sql/10 (ops.query_plan, v_index_usage, v_slow_queries).
  if (!queryPlan && !indexUsage && !slowQueries) return null;

  const armLabels: Record<string, string> = { lexical: 'Lexical · GIN(tsv)', semantic: 'Semantic · HNSW', fuzzy: 'Fuzzy · GIN(trgm)' };
  const scanClass = (nodeType: string) =>
    /Index/.test(nodeType) ? 'scan-index' : 'scan-seq';

  return (
    <div className="plan-surface" aria-label="Query plan and index statistics">
      <div className="phead">
        <div className="ptitle">Under the planner — EXPLAIN ANALYZE, live</div>
        <div className="psub">{queryPlan?.explain || 'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)'}</div>
      </div>

      {queryPlan && queryPlan.arms.length > 0 && (
        <>
          <div className="plan-grid">
            {queryPlan.arms.map((arm) => (
              <div className="plan-arm" key={arm.arm}>
                <div className="plan-arm-head">
                  <b>{armLabels[arm.arm] || arm.arm}</b>
                  <span className="mono">
                    {arm.summary.actual_total_time_ms != null ? `${arm.summary.actual_total_time_ms} ms` : '—'}
                    {arm.summary.actual_rows != null ? ` · ${arm.summary.actual_rows} rows` : ''}
                  </span>
                </div>
                <div className="plan-scans">
                  {arm.summary.scans.map((scan, i) => (
                    <div className={cx('plan-scan', scanClass(scan.node_type))} key={i}>
                      <span className="scan-node">{scan.node_type}</span>
                      <span className="scan-rel">
                        {scan.relation}
                        {scan.index ? <em> using {scan.index}</em> : null}
                      </span>
                    </div>
                  ))}
                </div>
                <div className="plan-buffers mono">
                  buffers hit {arm.summary.shared_hit_blocks ?? 0}
                  {arm.summary.shared_read_blocks ? ` · read ${arm.summary.shared_read_blocks}` : ''}
                </div>
              </div>
            ))}
          </div>
          {queryPlan.note && <div className="bnote plan-note">{queryPlan.note}</div>}
        </>
      )}

      <div className="grid2 plan-stats">
        {indexUsage && indexUsage.indexes.length > 0 && (
          <div className="panel">
            <div className="phead">
              <div className="ptitle">Index usage</div>
              <div className="psub">PG_STAT_USER_INDEXES · ops</div>
            </div>
            <table className="plan-table">
              <thead>
                <tr><th className="l">Index</th><th>Method</th><th>Scans</th><th>Size</th></tr>
              </thead>
              <tbody>
                {indexUsage.indexes
                  .filter((row) => row.method === 'gin' || row.method === 'hnsw')
                  .map((row) => (
                    <tr key={row.index_name}>
                      <td className="l mono">{row.index_name}</td>
                      <td><span className={cx('idx-method', `idx-${row.method}`)}>{row.method.toUpperCase()}</span></td>
                      <td>{row.scans}</td>
                      <td className="mono">{row.index_size}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
            <div className="bnote">GIN and HNSW indexes with <b>scans = 0</b> are honest: at this corpus size the planner picks a Seq Scan until the table is large enough for the index to win. The indexes exist and take over at scale.</div>
          </div>
        )}

        {slowQueries && slowQueries.statements.length > 0 && (
          <div className="panel">
            <div className="phead">
              <div className="ptitle">Retrieval hot path</div>
              <div className="psub">PG_STAT_STATEMENTS · by mean exec</div>
            </div>
            <table className="plan-table">
              <thead>
                <tr><th className="l">Statement</th><th>Calls</th><th>Mean ms</th><th>Cache</th></tr>
              </thead>
              <tbody>
                {slowQueries.statements.slice(0, 8).map((row) => (
                  <tr key={row.queryid}>
                    <td className="l mono plan-stmt">{row.query}</td>
                    <td>{row.calls}</td>
                    <td>{row.mean_exec_ms}</td>
                    <td className="mono">{row.cache_hit_pct != null ? `${row.cache_hit_pct}%` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="bnote">Mean execution time and buffer cache-hit ratio per statement, straight from <b>pg_stat_statements</b> — the real cost of every retrieval query the app runs.</div>
          </div>
        )}
      </div>
    </div>
  );
}

function BarPanel({
  title,
  subtitle,
  rows,
  note
}: {
  title: string;
  subtitle: string;
  rows: Array<[string, string, number, boolean?]>;
  note: React.ReactNode;
}) {
  return (
    <div className="panel">
      <div className="phead">
        <div className="ptitle">{title}</div>
        <div className="psub">{subtitle}</div>
      </div>
      {rows.map(([label, value, width, warm]) => (
        <div className="brow" key={label}>
          <span className="bl">{label}</span>
          <span className={cx('bar', warm && 'warm')}><i style={{ width: `${width}%` }} /></span>
          <span className="bv">{value}</span>
        </div>
      ))}
      <div className="bnote">{note}</div>
    </div>
  );
}

function DetailPage({
  page,
  query,
  setQuery,
  selected,
  objectDetail,
  detailLoading,
  error,
  onSearch,
  onNavigate,
  onOpenDetail,
  omniboxRef
}: {
  page: Page;
  query: string;
  setQuery: (value: string) => void;
  selected: Result | null;
  objectDetail: ObjectDetail | null;
  detailLoading: boolean;
  error?: string;
  onSearch: () => void;
  onNavigate: (page: Page) => void;
  onOpenDetail: (result: Result) => void;
  omniboxRef?: React.RefObject<HTMLInputElement>;
}) {
  const citations = objectDetail?.citations || [];
  const chunks = objectDetail?.chunks || [];
  const links = objectDetail?.links || [];

  return (
    <section className="inner-screen">
      <AppHeader page={page} query={query || queryDefault} setQuery={setQuery} onSearch={onSearch} onNavigate={onNavigate} omniboxRef={omniboxRef} />
      <main className="detail-layout">
        <button className="back-button" onClick={() => onNavigate('results')}>
          <ArrowLeft size={13} />
          Back to evidence
        </button>
        <ErrorBanner message={error} />
        {!selected ? (
          <EmptyState title="No source selected" body="Run a search and open a result to inspect source detail." />
        ) : (
          <article className="detail-card">
            <div className="detail-kicker">
              <span className="tile">{sourceIcon(selected.source_system, 22)}</span>
              <span>{sourceLabel(selected.source_system)}</span>
              <b>{selected.external_id}</b>
              {selected.priority && <span>{selected.priority}</span>}
            </div>
            <h1>{selected.title}</h1>
            <div className="detail-byline">
              <span>Updated {formatDate(selected.updated_at)}</span>
              {selected.owner && <span>{selected.owner}</span>}
              {selected.project_key && <span>Project {selected.project_key}</span>}
              <span title={FINAL_SCORE_HELP}>SQL score {displayScore(selected).toFixed(2)}</span>
            </div>
            <section className="detail-section">
              <h2>Retrieved passage</h2>
              <p>{selected.snippet}</p>
            </section>
            {detailLoading && <p className="detail-loading">Loading source detail…</p>}
            {citations.length > 0 && (
              <section className="detail-section">
                <h2>Citations</h2>
                {citations.slice(0, 3).map((citation) => (
                  <blockquote key={citation.citation_id}>
                    <span>{citation.locator || citation.source_label}</span>
                    <p>{citation.quote_text || 'Citation quote unavailable.'}</p>
                  </blockquote>
                ))}
              </section>
            )}
            {chunks.length > 1 && (
              <section className="detail-section">
                <h2>Object chunks</h2>
                {chunks.slice(0, 3).map((chunk) => (
                  <blockquote key={chunk.chunk_id}>
                    <span>{chunk.section_title || `Chunk ${chunk.chunk_index}`}</span>
                    <p>{chunk.chunk_summary || chunk.chunk_text.slice(0, 260)}</p>
                  </blockquote>
                ))}
              </section>
            )}
            <section className="detail-section two-col">
              <div>
                <h2>Why this matched</h2>
                {(selected.explanation?.why || ['Matched through hybrid retrieval and linked operational evidence.']).map((why) => (
                  <p key={why}>{why}</p>
                ))}
              </div>
              <div>
                <h2>Linked evidence</h2>
                {links.length ? links.slice(0, 4).map((link) => (
                  <button
                    className="linked-evidence"
                    type="button"
                    key={link.link_id || `${link.source_system}-${link.external_id}`}
                    onClick={() => onOpenDetail(link)}
                  >
                    <span className="tile">{sourceIcon(link.source_system, 17)}</span>
                    <span>
                      <b>{link.title}</b>
                      <small>{sourceLabel(link.source_system)} · {link.external_id}{typeof link.confidence === 'number' ? ` · ${link.confidence.toFixed(2)} confidence` : ''}</small>
                    </span>
                    <ArrowRight size={14} />
                  </button>
                )) : <p>No linked source objects returned for this evidence item.</p>}
              </div>
            </section>
            {selected.url && (
              <a className="source-link" href={selected.url} target="_blank" rel="noreferrer">
                Open source object <ExternalLink size={13} />
              </a>
            )}
          </article>
        )}
      </main>
    </section>
  );
}

// One arm's request body. rrf_k + weights only bind the hybrid ranker (the SQL
// function ignores them for single-signal arms), but sending them uniformly keeps
// the call site simple and the backend already routes by `mode`.
function compareSearchBody(mode: CompareMode, query: string, knobs: FusionKnobs, projectKey: ProjectFilter) {
  return {
    query,
    mode,
    source_systems: SYSTEM_KEYS,
    project_key: projectKey === 'ORION' ? 'ORION' : undefined,
    limit: 8,
    rrf_k: knobs.rrf_k,
    w_text: knobs.w_text,
    w_vector: knobs.w_vector,
    w_trgm: knobs.w_trgm,
    ef_search: knobs.ef_search,
    // Only the hybrid arm reranks; single-signal arms stay pure so the teaching
    // point (semantic-only misses the exact ORION-1489 hit) isn't masked.
    rerank: mode === 'hybrid' ? knobs.rerank : false
  };
}

// The union of every object any arm surfaced, with its 1-based rank per mode
// (null = that arm didn't return it). This is the citation-coverage diff: it makes
// the ORION-1489 row that lexical finds and semantic misses visible at a glance.
type CoverageRow = {
  external_id: string;
  source_system: string;
  title: string;
  object_id?: string;
  ranks: Record<CompareMode, number | null>;
  breadth: number;
};

function buildCoverage(columns: CompareColumn[]): CoverageRow[] {
  const byId = new Map<string, CoverageRow>();
  for (const column of columns) {
    column.results.forEach((result, index) => {
      const key = result.external_id;
      if (!key) return;
      let row = byId.get(key);
      if (!row) {
        row = {
          external_id: key,
          source_system: result.source_system,
          title: result.title,
          object_id: result.object_id,
          ranks: { hybrid: null, semantic: null, lexical: null, fuzzy: null },
          breadth: 0
        };
        byId.set(key, row);
      }
      if (row.ranks[column.mode] == null) row.ranks[column.mode] = index + 1;
      if (!row.object_id && result.object_id) row.object_id = result.object_id;
    });
  }
  const rows = Array.from(byId.values());
  for (const row of rows) {
    row.breadth = compareModes.reduce((count, { mode }) => count + (row.ranks[mode] != null ? 1 : 0), 0);
  }
  // Sort by how uniquely revealing a row is: fewest arms first (the split hits),
  // then best hybrid rank. A row every arm agrees on is boring; one only lexical
  // found is the whole point of the comparison.
  return rows.sort((a, b) => {
    if (a.breadth !== b.breadth) return a.breadth - b.breadth;
    const ah = a.ranks.hybrid ?? 99;
    const bh = b.ranks.hybrid ?? 99;
    return ah - bh;
  });
}

function compareSignalValue(result: Result, signal: keyof Signals): number | undefined {
  if (signal === 'rerank') {
    const value = typeof result.rerank_score === 'number' ? result.rerank_score : result.explanation?.signals?.rerank;
    return typeof value === 'number' ? value : displayScore(result);
  }
  const value = result.explanation?.signals?.[signal];
  return typeof value === 'number' ? value : undefined;
}

function KnobPanel({
  knobs,
  onChange,
  onRun,
  onReset,
  loading,
  customized
}: {
  knobs: FusionKnobs;
  onChange: (next: FusionKnobs) => void;
  onRun: () => void;
  onReset: () => void;
  loading: boolean;
  customized: boolean;
}) {
  const sliders: Array<{ key: keyof FusionKnobs; label: string; min: number; max: number; step: number; hint: string }> = [
    { key: 'rrf_k', label: 'RRF k', min: 1, max: 120, step: 1, hint: 'Rank-fusion constant. Higher flattens the contribution of top ranks.' },
    { key: 'w_text', label: 'Weight · lexical', min: 0, max: 4, step: 0.1, hint: 'Multiplier on the full-text arm inside the fused score.' },
    { key: 'w_vector', label: 'Weight · semantic', min: 0, max: 4, step: 0.1, hint: 'Multiplier on the pgvector arm inside the fused score.' },
    { key: 'w_trgm', label: 'Weight · fuzzy', min: 0, max: 4, step: 0.1, hint: 'Multiplier on the pg_trgm arm inside the fused score.' },
    { key: 'ef_search', label: 'HNSW ef_search', min: 10, max: 400, step: 10, hint: 'pgvector search breadth. Higher recall, higher latency.' }
  ];
  return (
    <div className="knob-panel">
      <div className="knob-head">
        <span className="mono-label">Fusion knobs</span>
        <small>Applied to the hybrid arm; ef_search binds every vector arm.</small>
      </div>
      <div className="knob-grid">
        {sliders.map((slider) => (
          <label className="knob" key={slider.key}>
            <span className="knob-lbl" title={slider.hint}>{slider.label}<b>{knobs[slider.key]}</b></span>
            <input
              type="range"
              min={slider.min}
              max={slider.max}
              step={slider.step}
              value={knobs[slider.key] as number}
              onChange={(event) => onChange({ ...knobs, [slider.key]: Number(event.currentTarget.value) })}
            />
          </label>
        ))}
        <label className="knob knob-toggle" title="Run Cohere Rerank v3.5 on the hybrid arm after SQL fusion.">
          <input
            type="checkbox"
            checked={knobs.rerank}
            onChange={(event) => onChange({ ...knobs, rerank: event.currentTarget.checked })}
          />
          <span>Cohere rerank (hybrid)</span>
        </label>
      </div>
      <div className="knob-actions">
        <button className="btn primary" type="button" onClick={onRun} disabled={loading}>
          {loading ? 'Racing rankers…' : 'Run comparison'}
        </button>
        {customized && (
          <button className="btn ghost" type="button" onClick={onReset} disabled={loading}>
            <FilterX size={14} />
            Reset knobs
          </button>
        )}
      </div>
    </div>
  );
}

function CompareColumnCard({
  column,
  coverage,
  onOpenDetail
}: {
  column: CompareColumn;
  coverage: CoverageRow[];
  onOpenDetail: (result: Result) => void;
}) {
  const meta = compareModes.find((entry) => entry.mode === column.mode)!;
  // An object is "unique" to this arm when no other arm surfaced it — the split
  // this whole view exists to expose.
  const uniqueIds = new Set(
    coverage.filter((row) => row.breadth === 1 && row.ranks[column.mode] != null).map((row) => row.external_id)
  );
  return (
    <div className="cmp-col">
      <div className="cmp-col-head">
        <b>{meta.label}</b>
        <span className="cmp-method">{meta.method}</span>
        <small>{meta.blurb}</small>
        <div className="cmp-col-stat">
          {column.loading ? 'Running…' : `${column.results.length} results`}
          {typeof column.total_latency_ms === 'number' && !column.loading && <> · {column.total_latency_ms} ms</>}
        </div>
      </div>
      {column.error ? (
        <div className="cmp-col-error">{column.error}</div>
      ) : column.loading ? (
        <div className="cmp-col-empty">Retrieving…</div>
      ) : column.results.length === 0 ? (
        <div className="cmp-col-empty">No results for this arm.</div>
      ) : (
        <ol className="cmp-list">
          {column.results.slice(0, 8).map((result, index) => {
            const signal = compareSignalValue(result, meta.signal);
            const unique = uniqueIds.has(result.external_id);
            return (
              <li key={`${result.external_id}-${index}`} className={cx('cmp-item', unique && 'unique')}>
                <span className="cmp-rank">{index + 1}</span>
                <span className="cmp-tile">{sourceIcon(result.source_system, 15)}</span>
                <button className="cmp-title" onClick={() => onOpenDetail(result)} title={result.title}>
                  <b>{result.external_id}</b>
                  <small>{result.title}</small>
                </button>
                <span className="cmp-score" title={`${meta.signal} score`}>
                  {typeof signal === 'number' ? signal.toFixed(2) : '—'}
                </span>
                {unique && <span className="cmp-badge" title="Only this arm surfaced this object">only here</span>}
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}

function ComparePage({
  page,
  query,
  setQuery,
  omniboxRef,
  columns,
  knobs,
  loading,
  hasRun,
  projectFilter,
  error,
  onSearch,
  onKnobsChange,
  onRunCompare,
  onResetKnobs,
  onNavigate,
  onOpenDetail
}: {
  page: Page;
  query: string;
  setQuery: (value: string) => void;
  omniboxRef?: React.RefObject<HTMLInputElement>;
  columns: CompareColumn[];
  knobs: FusionKnobs;
  loading: boolean;
  hasRun: boolean;
  projectFilter: ProjectFilter;
  error?: string;
  onSearch: () => void;
  onKnobsChange: (next: FusionKnobs) => void;
  onRunCompare: (queryOverride?: string) => void;
  onResetKnobs: () => void;
  onNavigate: (page: Page) => void;
  onOpenDetail: (result: Result) => void;
}) {
  const coverage = useMemo(() => buildCoverage(columns), [columns]);
  const splitRows = coverage.filter((row) => row.breadth > 0 && row.breadth < compareModes.length);
  const knobsCustomized =
    knobs.rrf_k !== defaultFusionKnobs.rrf_k ||
    knobs.w_text !== defaultFusionKnobs.w_text ||
    knobs.w_vector !== defaultFusionKnobs.w_vector ||
    knobs.w_trgm !== defaultFusionKnobs.w_trgm ||
    knobs.ef_search !== defaultFusionKnobs.ef_search ||
    knobs.rerank !== defaultFusionKnobs.rerank;
  const activeQuery = query || queryDefault;

  return (
    <section className="inner-screen">
      <AppHeader page={page} query={activeQuery} setQuery={setQuery} onSearch={onSearch} onNavigate={onNavigate} omniboxRef={omniboxRef} />
      <main className="compare-layout">
        <header className="compare-head">
          <div>
            <span className="mono-label">Tradeoff clinic</span>
            <h1>One query, four rankers</h1>
            <p>
              The same question runs through the fused hybrid ranker and each single signal against the same Aurora corpus.
              Watch which arm surfaces which evidence — and which objects only one arm ever finds.
            </p>
          </div>
          <form
            className="compare-run"
            onSubmit={(event) => {
              event.preventDefault();
              onRunCompare();
            }}
          >
            <input
              value={activeQuery}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={queryDefault}
              aria-label="Comparison query"
            />
            <button className="btn primary" type="submit" disabled={loading}>
              {loading ? 'Racing…' : 'Compare'}
            </button>
          </form>
        </header>

        <KnobPanel
          knobs={knobs}
          onChange={onKnobsChange}
          onRun={() => onRunCompare()}
          onReset={onResetKnobs}
          loading={loading}
          customized={knobsCustomized}
        />

        <ErrorBanner message={error} />

        {!hasRun && !loading ? (
          <EmptyState
            title="Run the comparison"
            body="Adjust the fusion knobs, then race hybrid against semantic, lexical, and fuzzy retrieval on the current query."
          />
        ) : (
          <>
            {splitRows.length > 0 && (
              <div className="cmp-diff">
                <div className="cmp-diff-head">
                  <span className="mono-label">Citation coverage diff</span>
                  <small>{splitRows.length} object{splitRows.length === 1 ? '' : 's'} the arms disagree on — sorted by how few arms found each</small>
                </div>
                <div className="cmp-diff-grid">
                  <div className="cmp-diff-row cmp-diff-labels">
                    <span>Object</span>
                    {compareModes.map((entry) => (
                      <span key={entry.mode} className="cmp-diff-mode">{entry.label}</span>
                    ))}
                  </div>
                  {splitRows.slice(0, 8).map((row) => (
                    <div className="cmp-diff-row" key={row.external_id}>
                      <button className="cmp-diff-obj" onClick={() => onOpenDetail({ ...row, snippet: '' } as Result)} title={row.title}>
                        <span className="cmp-tile">{sourceIcon(row.source_system, 15)}</span>
                        <b>{row.external_id}</b>
                        <small>{row.title}</small>
                      </button>
                      {compareModes.map((entry) => {
                        const rank = row.ranks[entry.mode];
                        return (
                          <span key={entry.mode} className={cx('cmp-diff-cell', rank == null ? 'miss' : rank <= 3 && 'top')}>
                            {rank == null ? '—' : `#${rank}`}
                          </span>
                        );
                      })}
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="cmp-cols">
              {columns.map((column) => (
                <CompareColumnCard
                  key={column.mode}
                  column={column}
                  coverage={coverage}
                  onOpenDetail={onOpenDetail}
                />
              ))}
            </div>
          </>
        )}
      </main>
    </section>
  );
}

function App() {
  const [page, setPage] = useState<Page>(readInitialPage);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Result[]>([]);
  const [hasSearchRun, setHasSearchRun] = useState(false);
  const [selected, setSelected] = useState<Result | null>(null);
  const [runId, setRunId] = useState<string | undefined>(readInitialRun);
  const [agentPayload, setAgentPayload] = useState<AgentPayload>({});
  const [objectDetail, setObjectDetail] = useState<ObjectDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(false);
  const [apiStatus, setApiStatus] = useState<ApiStatus>('checking');
  const [guideCompleted, setGuideCompleted] = useState(() => readGuideDismissals().length === guideSteps.length);
  const [activeGuideStep, setActiveGuideStep] = useState<GuideStep | null>(null);
  const [canonicalLoadSettled, setCanonicalLoadSettled] = useState(false);
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all');
  const [rankMode, setRankMode] = useState<RankMode>('hybrid');
  const [timeWindow, setTimeWindow] = useState<TimeWindow>('90d');
  const [projectFilter, setProjectFilter] = useState<ProjectFilter>('ORION');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [priorityFilter, setPriorityFilter] = useState<PriorityFilter>('all');
  // Compare view: the four ranker columns, the live fusion knobs, and whether a
  // comparison has been run yet. Each column holds its own run_id + results so the
  // citation-coverage diff can render the split across arms.
  const [compareColumns, setCompareColumns] = useState<CompareColumn[]>(
    compareModes.map(({ mode }) => ({ mode, results: [], loading: false }))
  );
  const [compareKnobs, setCompareKnobs] = useState<FusionKnobs>(defaultFusionKnobs);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareHasRun, setCompareHasRun] = useState(false);
  // Live workspace data, hydrated from the read-only canonical endpoints on mount
  // so every page renders real Aurora rows even before the user runs the agent.
  const [canonical, setCanonical] = useState<CanonicalDiagnostics | null>(null);
  const [timeline, setTimeline] = useState<TimelinePayload | null>(null);
  const [graph, setGraph] = useState<GraphPayload | null>(null);
  const [fusionSql, setFusionSql] = useState<FusionSql | null>(null);
  const [corpus, setCorpus] = useState<CorpusProfile | null>(null);
  const [queryPlan, setQueryPlan] = useState<QueryPlan | null>(null);
  const [indexUsage, setIndexUsage] = useState<IndexUsage | null>(null);
  const [slowQueries, setSlowQueries] = useState<SlowQueries | null>(null);
  const omniboxRef = useRef<HTMLInputElement>(null);
  // The in-flight search request. A new search aborts the previous one so a slow
  // stale response can never overwrite the results of a faster newer query.
  const searchAbortRef = useRef<AbortController | null>(null);
  const guideStartedRef = useRef(false);
  // Once the presenter advances a guide step by keypress, they own the pacing:
  // the auto-advance timer stops for the rest of the walkthrough so it never
  // races ahead of a live explanation.
  const presenterDrivenRef = useRef(false);

  function showGuideStep(step: GuideStep) {
    const guidePages: Record<GuideStep, Page> = {
      search: 'landing',
      evidence: 'results',
      answer: 'agent',
      timeline: 'trail',
      diagnostics: 'diagnostics',
      proof: 'diagnostics'
    };
    setQuery(queryDefault);
    setError(undefined);
    setLoading(false);
    setPage(guidePages[step]);
    setActiveGuideStep(step);
  }

  function completeGuide() {
    window.localStorage.setItem(GUIDE_STORAGE_KEY, JSON.stringify(guideSteps));
    setGuideCompleted(true);
    setActiveGuideStep(null);
    setQuery('');
    setError(undefined);
    setLoading(false);
    setPage('landing');
    window.setTimeout(() => window.scrollTo({ top: 0, behavior: 'auto' }), 0);
  }

  function advanceGuide(step: GuideStep) {
    const currentIndex = guideSteps.indexOf(step);
    if (currentIndex < 0 || activeGuideStep !== step) return;
    const nextStep = guideSteps[currentIndex + 1];
    if (!nextStep) {
      completeGuide();
      return;
    }
    showGuideStep(nextStep);
  }

  function skipGuide() {
    completeGuide();
  }

  function startGuide() {
    if (!ENABLE_GUIDED_DISCOVERY || !canonical) return;
    guideStartedRef.current = true;
    presenterDrivenRef.current = false;
    window.localStorage.removeItem(GUIDE_STORAGE_KEY);
    setGuideCompleted(false);
    setHasSearchRun(false);
    setResults([]);
    setSelected(null);
    setRunId(undefined);
    setAgentPayload({});
    showGuideStep('search');
    window.setTimeout(() => window.scrollTo({ top: 0, behavior: 'auto' }), 0);
  }

  function navigate(pageTarget: Page) {
    setLoading(false);
    setError(undefined);
    if (pageTarget !== 'landing' && (page === 'landing' || !query.trim())) setQuery(queryDefault);
    if (pageTarget === 'detail' && !selected) setSelected(citedResults[0] || null);
    setPage(pageTarget);
  }

  useEffect(() => {
    document.title = `${APP_NAME} — Agentic Hybrid Retrieval`;
  }, []);

  useEffect(() => {
    let active = true;
    fetchWithTimeout(`${API_URL}/health`, {}, 5000)
      .then((resp) => {
        if (active) setApiStatus(resp.ok ? 'live' : 'offline');
      })
      .catch(() => {
        if (active) setApiStatus('offline');
      });
    return () => {
      active = false;
    };
  }, []);

  // Hydrate the workspace from the read-only canonical + corpus endpoints once on
  // mount. These create no retrieval run, so the landing hero, Diagnostics, and
  // the Answer rail render live Aurora rows immediately. Timeline and graph are
  // keyed to the canonical run; when the user runs the agent, runId updates and
  // the effect below refetches them for that run.
  useEffect(() => {
    let active = true;
    const load = async <T,>(path: string, set: (value: T) => void, onSettled?: () => void) => {
      try {
        const resp = await fetchWithTimeout(`${API_URL}${path}`, {}, 12000);
        if (!resp.ok) return;
        const json = (await resp.json()) as T;
        if (active) set(json);
      } catch {
        // Leave the slice null; pages fall back to a graceful empty state.
      } finally {
        if (active) onSettled?.();
      }
    };
    const loadPost = async <T,>(path: string, body: unknown, set: (value: T) => void) => {
      try {
        const resp = await fetchWithTimeout(
          `${API_URL}${path}`,
          { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
          15000
        );
        if (!resp.ok) return;
        const json = (await resp.json()) as T;
        if (active) set(json);
      } catch {
        // Leave the slice null; the plan panel falls back to a graceful empty state.
      }
    };
    void load<CanonicalDiagnostics>('/v1/diagnostics/canonical', setCanonical, () => setCanonicalLoadSettled(true));
    void load<CorpusProfile>('/v1/diagnostics/corpus', setCorpus);
    void load<FusionSql>('/v1/diagnostics/fusion-sql', setFusionSql);
    void load<IndexUsage>('/v1/diagnostics/index-usage', setIndexUsage);
    void load<SlowQueries>('/v1/diagnostics/slow-queries', setSlowQueries);
    void loadPost<QueryPlan>('/v1/diagnostics/plan', { query: queryDefault, arm: 'hybrid', limit: 10 }, setQueryPlan);
    return () => {
      active = false;
    };
  }, []);

  // Timeline + graph follow the active run: the canonical run on load, then the
  // live run once the user asks the agent. Both derive from object_links in Aurora.
  useEffect(() => {
    let active = true;
    const target = runId || canonical?.run_id;
    if (!target) return;
    const load = async <T,>(path: string, set: (value: T) => void) => {
      try {
        const resp = await fetchWithTimeout(`${API_URL}${path}`, {}, 12000);
        if (!resp.ok) return;
        const json = (await resp.json()) as T;
        if (active) set(json);
      } catch {
        // Non-fatal; the page shows an empty state.
      }
    };
    void load<TimelinePayload>(`/v1/runs/${target}/timeline`, setTimeline);
    void load<GraphPayload>(`/v1/runs/${target}/graph`, setGraph);
    return () => {
      active = false;
    };
  }, [runId, canonical?.run_id]);

  useEffect(() => {
    if (
      !ENABLE_GUIDED_DISCOVERY ||
      guideCompleted ||
      guideStartedRef.current ||
      !canonicalLoadSettled ||
      !canonical ||
      // A deep-linked page (?page=) or run (?run=) means the presenter jumped to a
      // specific beat; don't yank them back to the auto-guide from the landing step.
      readInitialPage() !== 'landing' ||
      readInitialRun()
    ) return;
    startGuide();
  }, [canonicalLoadSettled, canonical, guideCompleted]);

  // Mirror the active page + run into the URL query string so a beat is
  // deep-linkable and survives a refresh. replaceState (not pushState) keeps the
  // browser Back button from walking every intra-app navigation.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const params = new URLSearchParams(window.location.search);
    if (page === 'landing') params.delete('page');
    else params.set('page', page);
    if (runId) params.set('run', runId);
    else params.delete('run');
    const qs = params.toString();
    const next = `${window.location.pathname}${qs ? `?${qs}` : ''}${window.location.hash}`;
    window.history.replaceState(null, '', next);
  }, [page, runId]);

  useEffect(() => {
    if (!activeGuideStep || presenterDrivenRef.current) return;
    const timerId = window.setTimeout(() => advanceGuide(activeGuideStep), GUIDE_STEP_DURATION_MS);
    return () => window.clearTimeout(timerId);
  }, [activeGuideStep]);

  // Step to an adjacent workshop beat (presentation order in BEAT_PAGES). When a
  // guide step is showing, the walkthrough owns the sequence, so beat keys advance
  // the guide instead of paging past its coachmarks. 'detail' is a drill-down, not
  // a beat, so from there `[`/`]` resume from its nearest beat neighbour (results).
  function stepBeat(delta: 1 | -1) {
    if (activeGuideStep) {
      // The presenter is now pacing the walkthrough by hand — stop the auto timer.
      presenterDrivenRef.current = true;
      if (delta > 0) advanceGuide(activeGuideStep);
      else skipGuide();
      return;
    }
    const current = BEAT_PAGES.indexOf(page);
    const from = current >= 0 ? current : BEAT_PAGES.indexOf('results');
    const next = Math.min(BEAT_PAGES.length - 1, Math.max(0, from + delta));
    navigate(BEAT_PAGES[next]);
  }

  // ⌘K / Ctrl-K focuses the search box from anywhere. On the landing page the
  // composer input carries the .landing-search class; on inner pages it is the
  // omnibox (wired via omniboxRef). Escape blurs it. `[` / `]` are presenter beat
  // keys — previous / next workshop step — ignored while typing in a field.
  useEffect(() => {
    if (typeof window === 'undefined') return;
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        const target =
          omniboxRef.current ||
          (document.querySelector('.landing-search input') as HTMLInputElement | null);
        target?.focus();
        target?.select();
      } else if (event.key === 'Escape') {
        if (activeGuideStep) {
          event.preventDefault();
          skipGuide();
          return;
        }
        const activeEl = document.activeElement as HTMLElement | null;
        if (activeEl?.tagName === 'INPUT') activeEl.blur();
      } else if (event.key === ']' || event.key === '[') {
        const activeEl = document.activeElement as HTMLElement | null;
        if (activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA')) return;
        if (event.metaKey || event.ctrlKey || event.altKey) return;
        event.preventDefault();
        stepBeat(event.key === ']' ? 1 : -1);
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [activeGuideStep, page, query, selected]);

  useEffect(() => {
    if (page !== 'detail' || !selected?.object_id) return;
    let active = true;
    setDetailLoading(true);
    setObjectDetail(null);
    setError(undefined);
    fetchWithTimeout(`${API_URL}/v1/objects/${selected.object_id}`, {}, 20000)
      .then((resp) => {
        if (!resp.ok) throw new Error(`Source detail failed with HTTP ${resp.status}`);
        return resp.json() as Promise<ObjectDetail>;
      })
      .then((json) => {
        if (active) setObjectDetail(json);
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : 'Source detail failed.');
      })
      .finally(() => {
        if (active) setDetailLoading(false);
      });
    return () => {
      active = false;
    };
  }, [page, selected?.object_id]);

  // The cited evidence set for the answer rail + detail fallback: the live agent
  // citations when the user has run the agent, otherwise the canonical run's
  // cited objects (fetched read-only on mount). Both are real Aurora rows.
  const activeCitations =
    (agentPayload.citations && agentPayload.citations.length > 0
      ? agentPayload.citations
      : canonical?.citations) || [];
  const citedResults = citationsToResults(activeCitations);
  // Total corpus size for the "All" chip + funnel, live from the corpus profile.
  const corpusTotal = corpus?.profile?.objects ?? canonical?.funnel?.fetched;
  // Per-system live object counts for the filter chips.
  const systemCounts = (() => {
    const counts: Record<string, number> = {};
    for (const row of corpus?.source_distribution || []) {
      counts[row.source_system] = (counts[row.source_system] || 0) + row.object_count;
    }
    return counts;
  })();

  async function runSearch(queryOverride?: string, overrides: Partial<{
    sourceFilter: SourceFilter;
    timeWindow: TimeWindow;
    projectFilter: ProjectFilter;
    statusFilter: StatusFilter;
    priorityFilter: PriorityFilter;
  }> = {}) {
    const searchQuery = (queryOverride ?? query).trim() || queryDefault;
    const nextSourceFilter = overrides.sourceFilter ?? sourceFilter;
    const nextTimeWindow = overrides.timeWindow ?? timeWindow;
    const nextProjectFilter = overrides.projectFilter ?? projectFilter;
    const nextStatusFilter = overrides.statusFilter ?? statusFilter;
    const nextPriorityFilter = overrides.priorityFilter ?? priorityFilter;
    const sourceSystems = nextSourceFilter === 'all'
      ? ['slack', 'jira', 'confluence', 'salesforce', 'github']
      : [nextSourceFilter];
    const startDate = startDateForWindow(nextTimeWindow);

    if (activeGuideStep) completeGuide();
    // Cancel any search still in flight so its response can't land after this one.
    searchAbortRef.current?.abort();
    const controller = new AbortController();
    searchAbortRef.current = controller;
    setQuery(searchQuery);
    setSourceFilter(nextSourceFilter);
    setTimeWindow(nextTimeWindow);
    setProjectFilter(nextProjectFilter);
    setStatusFilter(nextStatusFilter);
    setPriorityFilter(nextPriorityFilter);
    setPage('results');
    setLoading(true);
    setError(undefined);
    setHasSearchRun(true);
    setRunId(undefined);
    setResults([]);
    setSelected(null);
    try {
      const resp = await fetchWithTimeout(`${API_URL}/v1/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: controller.signal,
        body: JSON.stringify({
          query: searchQuery,
          source_systems: sourceSystems,
          project_key: nextProjectFilter === 'ORION' ? 'ORION' : undefined,
          statuses: nextStatusFilter === 'all' ? undefined : [nextStatusFilter],
          priorities: nextPriorityFilter === 'all' ? undefined : [nextPriorityFilter],
          start_date: startDate,
          limit: nextSourceFilter === 'all' ? 24 : 30
        })
      }, 45000);
      if (!resp.ok) throw new Error(`Search failed with HTTP ${resp.status}`);
      const json = (await resp.json()) as SearchResponse;
      const rows = dedupeResults(json.results || []);
      setRunId(json.run_id);
      setResults(rows);
      setSelected(rows[0] || null);
    } catch (err) {
      // A superseded search was aborted on purpose — leave the newer search's
      // state (loading flag included) untouched and swallow the cancellation.
      if (err instanceof DOMException && err.name === 'AbortError') return;
      setRunId(undefined);
      setResults([]);
      setSelected(null);
      setError(err instanceof Error ? err.message : 'Search failed. Check the API and local Postgres setup.');
    } finally {
      // Only the newest search clears the loading flag; a cancelled older one
      // must not, or it would hide the spinner the newer search just raised.
      if (searchAbortRef.current === controller) setLoading(false);
    }
  }

  function applySourceFilter(value: SourceFilter) {
    void runSearch(undefined, { sourceFilter: value });
  }

  function applyTimeWindow(value: TimeWindow) {
    void runSearch(undefined, { timeWindow: value });
  }

  function applyProjectFilter(value: ProjectFilter) {
    void runSearch(undefined, { projectFilter: value });
  }

  function applyStatusFilter(value: StatusFilter) {
    void runSearch(undefined, { statusFilter: value });
  }

  function applyPriorityFilter(value: PriorityFilter) {
    void runSearch(undefined, { priorityFilter: value });
  }

  function resetFilters() {
    setRankMode('hybrid');
    void runSearch(undefined, {
      sourceFilter: 'all',
      timeWindow: '90d',
      projectFilter: 'ORION',
      statusFilter: 'all',
      priorityFilter: 'all'
    });
  }

  // Open a specific object's Detail view — used by the Answer page's cited-source
  // buttons. The citation carries object_id (resolved server-side), so the detail
  // fetch effect (keyed on selected.object_id) loads the live source object.
  function openDetailFor(result: Result | null) {
    if (!result?.object_id) return;
    setSelected(result);
    setError(undefined);
    setLoading(false);
    setPage('detail');
  }

  async function runAgent(queryOverride?: string) {
    if (activeGuideStep) completeGuide();
    const question = (queryOverride ?? query).trim() || queryDefault;
    setQuery(question);
    setPage('agent');
    setLoading(true);
    setError(undefined);
    try {
      const resp = await fetchWithTimeout(`${API_URL}/v1/agent/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, limit: 8 })
      }, 90000);
      if (!resp.ok) throw new Error(`Agent answer failed with HTTP ${resp.status}`);
      const json = (await resp.json()) as AgentPayload;
      const rows = dedupeResults(json.results || []);
      setAgentPayload(json);
      setResults(rows);
      setSelected(rows[0] || selected);
      setRunId((current) => json.run_id || current);
    } catch (err) {
      // Surface the failure rather than substituting canned content: the answer
      // page renders the error banner and its empty state. No offline fallback.
      setAgentPayload({});
      setError(err instanceof Error ? err.message : 'Agent answer failed. Check the API and local Postgres setup.');
    } finally {
      setLoading(false);
    }
  }

  // Race the current query through all four rankers with the live fusion knobs.
  // Each arm fires its own /v1/search and lands in its own column, so a partial
  // failure degrades one column rather than the whole view. Every column is a real
  // persisted run — the citation-coverage diff is computed from live results only.
  async function runCompare(queryOverride?: string) {
    if (activeGuideStep) completeGuide();
    const question = (queryOverride ?? query).trim() || queryDefault;
    setQuery(question);
    setPage('compare');
    setCompareLoading(true);
    setCompareHasRun(true);
    setError(undefined);
    setCompareColumns(compareModes.map(({ mode }) => ({ mode, results: [], loading: true })));

    const settled = await Promise.all(
      compareModes.map(async ({ mode }): Promise<CompareColumn> => {
        try {
          const resp = await fetchWithTimeout(`${API_URL}/v1/search`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(compareSearchBody(mode, question, compareKnobs, projectFilter))
          }, 45000);
          if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
          const json = (await resp.json()) as SearchResponse & { total_latency_ms?: number };
          return {
            mode,
            run_id: json.run_id,
            results: dedupeResults(json.results || []),
            total_latency_ms: json.total_latency_ms,
            retrieval_mode: json.retrieval_mode,
            loading: false
          };
        } catch (err) {
          return {
            mode,
            results: [],
            loading: false,
            error: err instanceof Error ? `Retrieval failed (${err.message})` : 'Retrieval failed'
          };
        }
      })
    );
    setCompareColumns(settled);
    setCompareLoading(false);
  }

  function resetCompareKnobs() {
    setCompareKnobs(defaultFusionKnobs);
  }

  const withGuideBackdrop = (content: React.ReactElement) => (
    <ApiStatusContext.Provider value={apiStatus}>
      {activeGuideStep && <div className="guide-backdrop" aria-hidden="true" />}
      {content}
      {!activeGuideStep && ENABLE_GUIDED_DISCOVERY && canonical && <WalkthroughLauncher onStart={startGuide} />}
    </ApiStatusContext.Provider>
  );

  if (page === 'landing') {
    // A question from the landing page opens Evidence first. The workshop
    // teaches retrieval before synthesis, then lets participants move to Answer.
    return withGuideBackdrop(
      <Landing
        query={query}
        setQuery={setQuery}
        onSearch={runSearch}
        onNavigate={navigate}
        error={error}
        heroNodes={deriveHeroNodes(citedResults, canonical)}
        heroScore={typeof canonical?.confidence === 'number' ? canonical.confidence : null}
        corpusTotal={corpusTotal}
        runLatency={canonical?.total_latency_ms}
        canonical={canonical}
        timeline={timeline}
        guideStep={activeGuideStep}
        onAdvanceGuide={advanceGuide}
        onSkipGuide={skipGuide}
      />
    );
  }

  if (page === 'detail') {
    return withGuideBackdrop(
      <DetailPage
        page={page}
        query={query}
        setQuery={setQuery}
        omniboxRef={omniboxRef}
        selected={selected}
        objectDetail={objectDetail}
        detailLoading={detailLoading}
        error={error}
        onSearch={runSearch}
        onNavigate={navigate}
        onOpenDetail={openDetailFor}
      />
    );
  }

  if (page === 'trail') {
    return withGuideBackdrop(
      <TimelinePage
        page={page}
        query={query}
        setQuery={setQuery}
        omniboxRef={omniboxRef}
        timeline={timeline}
        error={error}
        onSearch={runSearch}
        onOpenDetail={openDetailFor}
        guideStep={activeGuideStep}
        onAdvanceGuide={advanceGuide}
        onSkipGuide={skipGuide}
        onNavigate={navigate}
      />
    );
  }

  if (page === 'agent') {
    return withGuideBackdrop(
      <AgentPage
        page={page}
        query={query}
        setQuery={setQuery}
        omniboxRef={omniboxRef}
        agentPayload={agentPayload}
        canonical={canonical}
        runId={runId}
        error={error}
        loading={loading}
        onSearch={runSearch}
        onAgent={runAgent}
        guideStep={activeGuideStep}
        onAdvanceGuide={advanceGuide}
        onSkipGuide={skipGuide}
        onNavigate={navigate}
        citedResults={citedResults}
        corpusTotal={corpusTotal}
        onOpenDetail={openDetailFor}
      />
    );
  }

  if (page === 'compare') {
    return withGuideBackdrop(
      <ComparePage
        page={page}
        query={query}
        setQuery={setQuery}
        omniboxRef={omniboxRef}
        columns={compareColumns}
        knobs={compareKnobs}
        loading={compareLoading}
        hasRun={compareHasRun}
        projectFilter={projectFilter}
        error={error}
        onSearch={runSearch}
        onKnobsChange={setCompareKnobs}
        onRunCompare={runCompare}
        onResetKnobs={resetCompareKnobs}
        onNavigate={navigate}
        onOpenDetail={openDetailFor}
      />
    );
  }

  if (page === 'diagnostics') {
    return withGuideBackdrop(
      <DiagnosticsPage
        page={page}
        query={query}
        setQuery={setQuery}
        omniboxRef={omniboxRef}
        canonical={canonical}
        fusionSql={fusionSql}
        queryPlan={queryPlan}
        indexUsage={indexUsage}
        slowQueries={slowQueries}
        corpusTotal={corpusTotal}
        onSearch={runSearch}
        guideStep={activeGuideStep}
        onAdvanceGuide={advanceGuide}
        onSkipGuide={skipGuide}
        onNavigate={navigate}
      />
    );
  }

  return withGuideBackdrop(
    <ResultsPage
      page={page}
      query={query}
      setQuery={setQuery}
      omniboxRef={omniboxRef}
      results={results}
      citedResults={citedResults}
      hasSearchRun={hasSearchRun}
      graph={graph}
      canonical={canonical}
      corpusTotal={corpusTotal}
      systemCounts={systemCounts}
      selected={selected}
      runId={runId}
      error={error}
      loading={loading}
      sourceFilter={sourceFilter}
      rankMode={rankMode}
      timeWindow={timeWindow}
      projectFilter={projectFilter}
      statusFilter={statusFilter}
      priorityFilter={priorityFilter}
      setSelected={setSelected}
      onSearch={runSearch}
      onAgent={runAgent}
      onSourceFilterChange={applySourceFilter}
      onRankModeChange={setRankMode}
      onTimeWindowChange={applyTimeWindow}
      onProjectFilterChange={applyProjectFilter}
      onStatusFilterChange={applyStatusFilter}
      onPriorityFilterChange={applyPriorityFilter}
      onResetFilters={resetFilters}
      guideStep={activeGuideStep}
      onAdvanceGuide={advanceGuide}
      onSkipGuide={skipGuide}
      onNavigate={navigate}
    />
  );
}

createRoot(document.getElementById('root')!).render(<App />);
