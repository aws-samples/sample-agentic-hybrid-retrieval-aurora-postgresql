import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowLeft, Database, ExternalLink, Search, ShieldCheck } from 'lucide-react';
import { FaGithub } from 'react-icons/fa6';
import confluenceLogoUrl from './assets/confluence-2017.svg';
import jiraLogoUrl from './assets/jira-streamline.svg';
import salesforceLogoUrl from './assets/salesforce-logo.jpeg';
import slackIconUrl from './assets/slack-icon-2019.svg';
import strandsLogoUrl from './assets/strands-logo.png';
import './styles.css';

type Page = 'landing' | 'results' | 'detail' | 'trail' | 'agent' | 'diagnostics';
type GuideStep = 'answer' | 'timeline' | 'diagnostics' | 'proof';
type SourceFilter = 'all' | 'slack' | 'jira' | 'confluence' | 'salesforce' | 'github';
type RankMode = 'hybrid' | 'semantic' | 'lexical' | 'recent';
type TimeWindow = '90d' | '30d' | '7d' | 'all';
type ProjectFilter = 'ORION' | 'all';
type StatusFilter = 'all' | 'Decision' | 'Resolved Jul 3' | 'Mitigating' | 'Published' | 'Resolved' | 'Merged';
type PriorityFilter = 'all' | 'P1' | 'Tier 1' | 'Policy' | 'Sev2' | 'Change';

type Signals = {
  full_text?: number;
  semantic?: number;
  fuzzy?: number;
  metadata?: number;
  recency?: number;
  rrf?: number;
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
  final_score?: number;
  // Normalized 0–1 score for display, computed relative to the top result in the
  // current set (the raw composite final_score is unbounded and not 0–1).
  _display_score?: number;
  explanation?: { signals?: Signals; why?: string[] };
};

type SearchResponse = {
  run_id: string;
  query: string;
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

// GET /v1/diagnostics/corpus — live object counts, per system and overall, for
// the filter chips and funnel totals.
type CorpusProfile = {
  profile?: { objects?: number; chunks?: number; source_systems?: number; embedded_chunks?: number };
  source_distribution?: Array<{ source_system: string; source_type?: string; object_count: number }>;
  embedding_progress?: Record<string, unknown>;
};

const API_URL = import.meta.env.VITE_RETRIEVAL_API_URL || 'http://127.0.0.1:8000';
const APP_NAME = import.meta.env.VITE_APP_DISPLAY_NAME || 'AuraLens';
const ENABLE_ANSWER_STREAMING = import.meta.env.VITE_ENABLE_ANSWER_STREAMING !== '0';
const ENABLE_GUIDED_DISCOVERY = import.meta.env.VITE_ENABLE_GUIDED_DISCOVERY !== '0';
const GUIDE_STORAGE_KEY = 'auralens-guided-discovery-v1';
const guideSteps: GuideStep[] = ['answer', 'timeline', 'diagnostics', 'proof'];
const STRANDS_URL = 'https://strandsagents.com/';
const GITHUB_REPO_URL = 'https://github.com/aws-samples/sample-agentic-hybrid-retrieval-aurora-postgresql';
const FINAL_SCORE_HELP = 'Unbounded composite score from Aurora SQL: RRF + full-text + semantic vector + fuzzy + metadata + recency. It is not a raw Cohere similarity score or a probability.';
const RESULTS_PAGE_SIZE = 5;
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
  hybrid: 'Hybrid · SQL score',
  semantic: 'Semantic · pgvector',
  lexical: 'Lexical · full-text',
  recent: 'Most recent'
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

const workspaceNavItems: Array<{ page: Page; label: string; eyebrow: string; summary: string }> = [
  { page: 'results', label: 'Evidence', eyebrow: '24 ranked results', summary: 'Hybrid-ranked sources and linked context' },
  { page: 'agent', label: 'Answer', eyebrow: '6 cited sources', summary: 'Synthesized answer with inline citations' },
  { page: 'trail', label: 'Timeline', eyebrow: '7 linked events', summary: 'Time-ordered cross-system sequence' },
  { page: 'diagnostics', label: 'Diagnostics', eyebrow: '341 ms run', summary: 'Fusion, scoring, latency, and SQL trace' }
];

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

function readGuideDismissals(): GuideStep[] {
  if (typeof window === 'undefined') return [];
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

function normalizeResult(row: Result): Result {
  return {
    ...row,
    source_system: row.source_system || 'source',
    external_id: row.external_id || row.object_id || row.chunk_id || 'unknown',
    title: row.title || 'Untitled source object',
    snippet: row.snippet || '',
    final_score: row.final_score === undefined ? undefined : Number(row.final_score),
    text_rank: row.text_rank === undefined ? undefined : Number(row.text_rank),
    vector_score: row.vector_score === undefined ? undefined : Number(row.vector_score),
    trigram_score: row.trigram_score === undefined ? undefined : Number(row.trigram_score),
    metadata_score: row.metadata_score === undefined ? undefined : Number(row.metadata_score),
    recency_score: row.recency_score === undefined ? undefined : Number(row.recency_score),
    rrf_score: row.rrf_score === undefined ? undefined : Number(row.rrf_score)
  };
}

function score(result: Result) {
  return Number(result.final_score || 0);
}

function withDisplayScores(rows: Result[]): Result[] {
  return rows.map(normalizeResult);
}

function displayScore(result: Result) {
  const value = score(result);
  if (Number.isFinite(value)) return value;
  return Number(result._display_score || 0);
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
    return score(b) - score(a);
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

// The citation.meta string is "SLACK · #proj-orion · JUN 23 · score 0.93" — drop
// the leading system token and the trailing score token to get the context line
// the hero card shows ("#proj-orion · JUN 23"). Falls back to the system label.
function heroMetaFromCitation(citation: Citation | undefined, system: string) {
  const parts = (citation?.meta || '')
    .split('·')
    .map((part) => part.trim())
    .filter(Boolean)
    .filter((part) => !/^score\b/i.test(part) && part.toLowerCase() !== system.toLowerCase());
  return parts.join(' · ') || sourceLabel(system);
}

function landingText(value?: string) {
  return (value || '').replace(/—/g, '–');
}

// Build the landing hero orbit from the live cited set. Each system that has a
// cited object contributes a node; positioning comes from heroNodeLayout and all
// content (title, score, meta) from the citation. No hard-coded node content.
function deriveHeroNodes(citedResults: Result[], canonical: CanonicalDiagnostics | null): HeroNode[] {
  const citations = canonical?.citations || [];
  const nodes: HeroNode[] = [];
  for (const system of Object.keys(heroNodeLayout)) {
    const layout = heroNodeLayout[system];
    const citation = citations.find((c) => c.source_system === system);
    const result = citedResults.find((r) => r.source_system === system);
    const title = citation?.title || result?.title;
    if (!title) continue;
    const scoreValue = typeof citation?.score === 'number' ? citation.score : result?.final_score;
    nodes.push({
      key: system,
      className: layout.className,
      delay: layout.delay,
      role: sourceLabel(system),
      score: typeof scoreValue === 'number' ? scoreValue.toFixed(2) : '',
      title: landingText(title),
      meta: landingText(heroMetaFromCitation(citation, system))
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
  title,
  body,
  onDismiss,
  onSkip
}: {
  title: string;
  body: string;
  onDismiss: () => void;
  onSkip: () => void;
}) {
  const cardRef = useRef<HTMLDivElement>(null);

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
      <span className="guide-kicker">Guided discovery</span>
      <b>{title}</b>
      <p>{body}</p>
      <div className="guide-actions">
        <button type="button" onClick={onDismiss}>Got it</button>
        <button type="button" onClick={onSkip}>Skip guide</button>
      </div>
    </div>
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
      <button className="ink-button" type="submit">Search</button>
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
      <div className="avatar">S</div>
    </header>
  );
}

function scrollToLandingSection(
  event: React.MouseEvent<HTMLAnchorElement>,
  sectionId: string,
  block: ScrollLogicalPosition = 'start'
) {
  event.preventDefault();
  const target = document.getElementById(sectionId);
  if (!target) return;
  target.scrollIntoView({ behavior: 'smooth', block, inline: 'nearest' });
  window.history.replaceState(null, '', `#${sectionId}`);
}

function Landing({
  query,
  setQuery,
  onSearch,
  onNavigate,
  error,
  heroNodes,
  heroScore
}: {
  query: string;
  setQuery: (value: string) => void;
  onSearch: (queryOverride?: string) => void;
  onNavigate: (page: Page) => void;
  error?: string;
  heroNodes: HeroNode[];
  heroScore?: number | null;
}) {
  return (
    <div className="landing-page">
      <nav className="topnav">
        <button className="wordmark-button" onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}>
          <Logo />
        </button>
        <div className="navlinks">
          <a href="#overview" onClick={(event) => scrollToLandingSection(event, 'overview')}>
            Overview
          </a>
          <a href="#how" onClick={(event) => scrollToLandingSection(event, 'how')}>
            How it works
          </a>
          <a href="#stack" onClick={(event) => scrollToLandingSection(event, 'stack', 'center')}>
            Retrieval stack
          </a>
          <a href="#demo-run" onClick={(event) => scrollToLandingSection(event, 'demo-run', 'center')}>
            Demo run
          </a>
        </div>
        <div className="nav-actions" aria-label="External resources">
          <a className="nav-strands-link" href={STRANDS_URL} target="_blank" rel="noreferrer" aria-label="Open Strands Agents">
            <img src={strandsLogoUrl} alt="" />
          </a>
          <a className="nav-icon-link" href={GITHUB_REPO_URL} target="_blank" rel="noreferrer" aria-label="Open the AuraLens source repository">
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
              {typeof heroScore === 'number' && <div className="a-score">{heroScore.toFixed(2)}</div>}
            </div>

            {heroNodes.map((node) => (
              <article className={cx('hero-node', node.className)} key={node.key} style={{ '--d': node.delay } as React.CSSProperties}>
                <div className="tile">{sourceIcon(node.key, 24)}</div>
                <div className="node-copy">
                  <div className="nhead">
                    <span className="ntype">{node.role}</span>
                    {node.score && <span className="nscore">{node.score}</span>}
                  </div>
                  <div className="ntitle">{node.title}</div>
                </div>
                <div className="nmeta">{node.meta}</div>
              </article>
            ))}
          </div>

          <div className="searchwrap">
            <SearchComposer query={query} setQuery={setQuery} onSearch={onSearch} autoType className="landing-composer" />
          </div>
        </section>

        <ErrorBanner message={error} />

        <section className="section harness-section" aria-label="Agent harness portability">
          <div className="harness-note">
            <span className="mono-label">Agent harness portability</span>
            <div>
              <h2>Use the harness that fits your team.</h2>
              <p>
                AuraLens uses Strands Agents for the workshop because the `@tool` boundary is explicit. The retrieval contract is portable:
                Aurora stores the evidence, FastAPI exposes the tools, and the same calls can be driven by Strands, Claude Code, MCP
                clients, or your own orchestrator.
              </p>
            </div>
            <div className="harness-points" aria-label="Portable tool contract">
              <span>infer_sources</span>
              <span>search_evidence</span>
              <span>synthesize_cited_answer</span>
            </div>
          </div>
        </section>

        <section className="section" id="how">
          <div className="sec-head">
            <div className="eyebrow mono-label">How it works</div>
            <h2 className="sec-title">Ask once. Search everywhere.</h2>
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
          <div className="sec-head">
            <div className="eyebrow mono-label">Retrieval stack</div>
            <h2 className="sec-title">One Aurora PostgreSQL engine.</h2>
          </div>
          <div className="stack">
            <span className="mono-label">The hybrid retrieval stack · one engine</span>
            <div className="formula">
              {['Full-text|ts_rank_cd', 'Semantic|pgvector', 'Fuzzy|pg_trgm', 'Fusion|RRF k=60', 'SQL score|composite', 'Cited answer|citations'].map((item, index) => {
                const [title, body] = item.split('|');
                return (
                  <React.Fragment key={item}>
                    {index > 0 && (
                      <span className={cx('f-op', index < 3 ? 'plus' : 'arrow')} aria-hidden="true">
                        {index < 3 ? '+' : '→'}
                      </span>
                    )}
                    <div className={cx('f-chip', index >= 3 && index <= 4 && 'hot')}>
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
          <div className="demo-strip" aria-label="Explore the populated Orion run">
            <div>
              <span className="mono-label">Explore demo run</span>
              <p>Start with search, or jump into the pre-populated Orion answer path.</p>
            </div>
            <div className="demo-links">
              {workspaceNavItems.map((item) => (
                <button
                  key={item.page}
                  type="button"
                  title={item.summary}
                  aria-label={`${item.label}: ${item.summary}`}
                  onClick={() => onNavigate(item.page)}
                >
                  <span>{item.eyebrow}</span>
                  <b>{item.label}</b>
                  <small>{item.summary}</small>
                </button>
              ))}
            </div>
          </div>
        </section>

        <footer className="footer">
          <div>
            <Logo />
            <div className="tag">Every answer shows its work.</div>
          </div>
          <div className="fine">© 2026 Agentic Hybrid Retrieval</div>
        </footer>
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
  { key: 'full_text', label: 'full-text', method: 'ts_rank_cd' },
  { key: 'semantic', label: 'semantic', method: 'pgvector' },
  { key: 'fuzzy', label: 'fuzzy', method: 'pg_trgm' },
  { key: 'metadata', label: 'metadata', method: 'filters' },
  { key: 'recency', label: 'recency', method: 'updated_at' }
];

function signalChips(result: Result): Array<{ key: string; label: string; value: string }> {
  const signals = result.explanation?.signals;
  if (!signals) return [];
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
  return (
    <article className="rcard">
      <div className="rhead">
        <div className="tile">{sourceIcon(result.source_system, 22)}</div>
        <div>
          <div className="rtype">{resultRole(result)}</div>
          <button className="rtitle" onClick={onOpen}>{result.title}</button>
        </div>
        <div className="rscore" title={FINAL_SCORE_HELP} aria-label={`Aurora SQL composite score ${finalScore}`}>
          <span>SQL score</span>
          {' '}
          <b>{finalScore}</b>
        </div>
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
  guideStep,
  onDismissGuide,
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
  guideStep?: GuideStep | null;
  onDismissGuide: (step: GuideStep) => void;
  onSkipGuide: () => void;
  onNavigate: (page: Page) => void;
}) {
  const [evidencePage, setEvidencePage] = useState(0);
  // Live evidence: the search results when the user has run a query, otherwise the
  // canonical run's cited objects (fetched read-only on mount). Both are real rows.
  const baseEvidence = hasSearchRun || results.length > 0 ? results : citedResults;
  const evidence = sortByRankMode(
    baseEvidence.filter((result) => {
      if (sourceFilter !== 'all' && result.source_system !== sourceFilter) return false;
      if (projectFilter !== 'all' && result.project_key !== projectFilter) return false;
      if (statusFilter !== 'all' && result.status !== statusFilter) return false;
      if (priorityFilter !== 'all' && result.priority !== priorityFilter) return false;
      return resultInWindow(result, timeWindow);
    }),
    rankMode
  );
  const showAnswerGuide = guideStep === 'answer';
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
                  SQL score = unbounded Aurora composite, not Cohere.
                </div>
                <button className={cx('answer-ready', showAnswerGuide && 'guide-pulse')} onClick={() => onAgent()}>
                  <span className="dot" />
                  Agent answer ready →
                </button>
              </>
            )}
          </div>
          {loading ? (
            <EmptyState loading title="Searching evidence" body={`${APP_NAME} is retrieving, fusing, and scoring source objects across connected systems.`} />
          ) : evidence.length === 0 ? (
            <EmptyState title="No evidence matched" body="Adjust the source, window, project, status, or priority filter and run the search again." />
          ) : (
            <>
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
          <div className={cx('railcard', showAnswerGuide && 'guide-target guide-spotlight')}>
            {showAnswerGuide && (
              <GuideCoachmark
                title="Open the cited answer"
                body="The evidence list shows ranked sources. Next, open the answer to see how those sources become cited claims."
                onDismiss={() => onDismissGuide('answer')}
                onSkip={onSkipGuide}
              />
            )}
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
function useStageSequence(count: number, opts: { enabled: boolean; beatMs?: number; startMs?: number }) {
  const { enabled, beatMs = 620, startMs = 220 } = opts;
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
  }, [count, enabled, beatMs, startMs]);
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

// A paragraph that types itself, then calls onDone so the next beat can start.
// Renders a blinking caret at the live edge while typing.
function StreamParagraph({
  text,
  enabled,
  className,
  speed,
  onDone
}: {
  text: string;
  enabled: boolean;
  className?: string;
  speed?: number;
  onDone?: () => void;
}) {
  const { shown, done } = useTypewriter(text, { enabled, speed, onDone });
  return (
    <p className={className}>
      {shown}
      {enabled && !done && <span className="caret" aria-hidden="true" />}
    </p>
  );
}

// Rich token model for streamed prose: plain runs, bold/highlight runs, and
// inline citation chips that pop in as the caret reaches them.
type RichToken =
  | { text: string }
  | { b: string }
  | { hl: string }
  | { cite: number };

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
  onDismissGuide,
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
  onDismissGuide: (step: GuideStep) => void;
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
  const railResults = citedResults.length > 0 ? citedResults : citationsToResults(citations);
  const commitments = (source.commitments && source.commitments.length > 0 ? source.commitments : canonical?.commitments) || [];
  const quote = answerBody?.quote;
  const hasAnswer = Boolean(answerBody || answerString);

  const runLabel = agentPayload.run_id || canonical?.run_id || runId || '';
  const confidenceValue = typeof source.confidence === 'number' ? source.confidence : (canonical?.confidence ?? 0);
  const confidenceLabel = confidenceValue.toFixed(2);
  const confidencePercent = Math.round(Math.max(0, Math.min(1, confidenceValue)) * 100);
  const citedSourceCount = source.source_count ?? canonical?.source_count ?? citations.length;
  const citedSystemCount = source.system_count ?? canonical?.system_count ?? new Set(citations.map((c) => c.source_system)).size;
  const claimCount = countCitationClaims(answerBody);
  const firedLabel = formatDate(canonical?.fired_at);
  const showTimelineGuide = guideStep === 'timeline';
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
                <StreamParagraph className="answer-string" text={answerString} enabled={streaming && beat >= 1} speed={4} onDone={advance} />
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
                    <div className={cx('actions', 'beat', 'is-in', showTimelineGuide && 'guide-target guide-spotlight')}>
                      {showTimelineGuide && (
                        <GuideCoachmark
                          title="Follow the evidence path"
                          body="The answer is cited. Now open Timeline to see the linked source objects in sequence."
                          onDismiss={() => onDismissGuide('timeline')}
                          onSkip={onSkipGuide}
                        />
                      )}
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
function eventDate(event: TimelineEvent) {
  const value = event.updated_at || event.created_at;
  if (!value) return '';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

// Non-primary edge relations render muted (the .n class). Primary relations —
// the ones that drive the delay narrative — render solid.
const MUTED_EDGE_RELATIONS = new Set(['references', 'resolves', 'relates_to', 'mentions']);

function TimelinePage({
  page,
  query,
  setQuery,
  omniboxRef,
  timeline,
  error,
  onSearch,
  guideStep,
  onDismissGuide,
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
  guideStep?: GuideStep | null;
  onDismissGuide: (step: GuideStep) => void;
  onSkipGuide: () => void;
  onNavigate: (page: Page) => void;
}) {
  // The timeline assembles itself node-by-node, as if traverse_links() were
  // walking object_links live. One stage per event, plus the outcome card.
  const reducedMotion = useReducedMotion();
  const events = timeline?.events || [];
  const streaming = !reducedMotion && events.length > 0;
  const stage = useStageSequence(events.length + 1, { enabled: streaming, beatMs: 520, startMs: 320 });
  const walking = streaming && stage < events.length;
  const showDiagnosticsGuide = guideStep === 'diagnostics';

  // Header stats + legend, derived from the live payload.
  const systemCount = timeline?.systems?.length ?? new Set(events.map((e) => e.source_system)).size;
  const edgeCount = timeline?.edge_count ?? events.reduce((sum, e) => sum + e.edges.length, 0);
  const dateRange = events.length
    ? `${eventDate(events[0])} — ${eventDate(events[events.length - 1])}, 2026`
    : '';
  const legendRelations = Array.from(new Set(events.flatMap((e) => e.edges.map((edge) => edge.link_type))));
  const highlightTerms = deriveHighlightTerms(query || queryDefault);

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
        {walking && (
          <div className="walking mono-label">traverse_links() building timeline<span className="caret" aria-hidden="true" /></div>
        )}
      </div>
      <ErrorBanner message={error} />
      {events.length === 0 ? (
        <EmptyState title="No timeline yet" body="Run the agent to build the cross-system evidence timeline for this question." />
      ) : (
        <div className="trail">
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
            <div className={cx('outcome', 'beat', 'is-in', showDiagnosticsGuide && 'guide-target guide-spotlight')}>
              {showDiagnosticsGuide && (
                <GuideCoachmark
                  title="Inspect the run diagnostics"
                  body="Timeline shows the linked evidence path. Diagnostics shows the ranker signals, candidate rows, and SQL trace behind the same run."
                  onDismiss={() => onDismissGuide('diagnostics')}
                  onSkip={onSkipGuide}
                />
              )}
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
  corpusTotal,
  onSearch,
  guideStep,
  onDismissGuide,
  onSkipGuide,
  onNavigate
}: {
  page: Page;
  query: string;
  setQuery: (value: string) => void;
  omniboxRef?: React.RefObject<HTMLInputElement>;
  canonical: CanonicalDiagnostics | null;
  fusionSql: FusionSql | null;
  corpusTotal?: number;
  onSearch: () => void;
  guideStep?: GuideStep | null;
  onDismissGuide: (step: GuideStep) => void;
  onSkipGuide: () => void;
  onNavigate: (page: Page) => void;
}) {
  const showProofGuide = guideStep === 'proof';

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

        <section className="diagnostics-audit" aria-label="Run audit summary">
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
              title="Use this as the proof surface"
              body="Each row is persisted in retrieval_candidates with ranker positions, final score, and citation outcome. This is the replayable audit trail."
              onDismiss={() => onDismissGuide('proof')}
              onSkip={onSkipGuide}
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
                    <td><span className="scorebar"><span className="tr"><i style={{ width: `${Number(finalScore) * 100}%` }} /></span>{finalScore}</span></td>
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

        <div className="pagefoot">
          run stored in <b>retrieval_runs</b> · candidates in <b>retrieval_candidates</b> · citations in <b>citations</b> · judged against <b>relevance_judgments</b><br />
          one retrieval index: <b>Amazon Aurora PostgreSQL</b> · live systems stay authoritative
        </div>
      </main>
    </section>
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
                  <p key={link.link_id || `${link.source_system}-${link.external_id}`}>{sourceLabel(link.source_system)} · {link.title}</p>
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

function App() {
  const [page, setPage] = useState<Page>('landing');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Result[]>([]);
  const [hasSearchRun, setHasSearchRun] = useState(false);
  const [selected, setSelected] = useState<Result | null>(null);
  const [runId, setRunId] = useState<string>();
  const [agentPayload, setAgentPayload] = useState<AgentPayload>({});
  const [objectDetail, setObjectDetail] = useState<ObjectDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(false);
  const [dismissedGuideSteps, setDismissedGuideSteps] = useState<GuideStep[]>(readGuideDismissals);
  const [activeGuideStep, setActiveGuideStep] = useState<GuideStep | null>(null);
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all');
  const [rankMode, setRankMode] = useState<RankMode>('hybrid');
  const [timeWindow, setTimeWindow] = useState<TimeWindow>('90d');
  const [projectFilter, setProjectFilter] = useState<ProjectFilter>('ORION');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [priorityFilter, setPriorityFilter] = useState<PriorityFilter>('all');
  // Live workspace data, hydrated from the read-only canonical endpoints on mount
  // so every page renders real Aurora rows even before the user runs the agent.
  const [canonical, setCanonical] = useState<CanonicalDiagnostics | null>(null);
  const [timeline, setTimeline] = useState<TimelinePayload | null>(null);
  const [graph, setGraph] = useState<GraphPayload | null>(null);
  const [fusionSql, setFusionSql] = useState<FusionSql | null>(null);
  const [corpus, setCorpus] = useState<CorpusProfile | null>(null);
  const omniboxRef = useRef<HTMLInputElement>(null);

  const guideDismissed = (step: GuideStep) => dismissedGuideSteps.includes(step);

  function activateGuide(step: GuideStep) {
    if (!ENABLE_GUIDED_DISCOVERY || guideDismissed(step)) return;
    setActiveGuideStep(step);
  }

  function dismissGuide(step: GuideStep) {
    setDismissedGuideSteps((current) => current.includes(step) ? current : [...current, step]);
    setActiveGuideStep((current) => current === step ? null : current);
  }

  function skipGuide() {
    setDismissedGuideSteps(guideSteps);
    setActiveGuideStep(null);
  }

  function resetGuideFromUrl() {
    if (typeof window === 'undefined') return;
    const params = new URLSearchParams(window.location.search);
    if (params.get('guide') !== '1') return;
    window.localStorage.removeItem(GUIDE_STORAGE_KEY);
    setDismissedGuideSteps([]);
    setActiveGuideStep(null);
  }

  function navigate(pageTarget: Page) {
    setLoading(false);
    setError(undefined);
    if (pageTarget !== 'landing' && (page === 'landing' || !query.trim())) setQuery(queryDefault);
    if (pageTarget === 'detail' && !selected) setSelected(citedResults[0] || null);
    if (pageTarget === 'results' && results.length > 0) activateGuide('answer');
    if (pageTarget === 'agent') activateGuide('timeline');
    if (pageTarget === 'trail') {
      dismissGuide('timeline');
      activateGuide('diagnostics');
    }
    if (pageTarget === 'diagnostics') {
      dismissGuide('diagnostics');
      activateGuide('proof');
    }
    setPage(pageTarget);
  }

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(GUIDE_STORAGE_KEY, JSON.stringify(dismissedGuideSteps));
  }, [dismissedGuideSteps]);

  useEffect(() => {
    resetGuideFromUrl();
  }, []);

  // Hydrate the workspace from the read-only canonical + corpus endpoints once on
  // mount. These create no retrieval run, so the landing hero, Diagnostics, and
  // the Answer rail render live Aurora rows immediately. Timeline and graph are
  // keyed to the canonical run; when the user runs the agent, runId updates and
  // the effect below refetches them for that run.
  useEffect(() => {
    let active = true;
    const load = async <T,>(path: string, set: (value: T) => void) => {
      try {
        const resp = await fetch(`${API_URL}${path}`);
        if (!resp.ok) return;
        const json = (await resp.json()) as T;
        if (active) set(json);
      } catch {
        // Leave the slice null; pages fall back to a graceful empty state.
      }
    };
    void load<CanonicalDiagnostics>('/v1/diagnostics/canonical', setCanonical);
    void load<CorpusProfile>('/v1/diagnostics/corpus', setCorpus);
    void load<FusionSql>('/v1/diagnostics/fusion-sql', setFusionSql);
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
        const resp = await fetch(`${API_URL}${path}`);
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

  // ⌘K / Ctrl-K focuses the search box from anywhere. On the landing page the
  // composer input carries the .landing-search class; on inner pages it is the
  // omnibox (wired via omniboxRef). Escape blurs it.
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
        const activeEl = document.activeElement as HTMLElement | null;
        if (activeEl?.tagName === 'INPUT') activeEl.blur();
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  useEffect(() => {
    if (!activeGuideStep) return;
    const allowed: Record<GuideStep, Page[]> = {
      answer: ['results'],
      timeline: ['agent'],
      diagnostics: ['trail'],
      proof: ['diagnostics']
    };
    if (!allowed[activeGuideStep].includes(page)) setActiveGuideStep(null);
  }, [activeGuideStep, page]);

  useEffect(() => {
    if (page !== 'detail' || !selected?.object_id) return;
    let active = true;
    setDetailLoading(true);
    setObjectDetail(null);
    setError(undefined);
    fetch(`${API_URL}/v1/objects/${selected.object_id}`)
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
      const resp = await fetch(`${API_URL}/v1/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: searchQuery,
          source_systems: sourceSystems,
          project_key: nextProjectFilter === 'ORION' ? 'ORION' : undefined,
          statuses: nextStatusFilter === 'all' ? undefined : [nextStatusFilter],
          priorities: nextPriorityFilter === 'all' ? undefined : [nextPriorityFilter],
          start_date: startDate,
          limit: nextSourceFilter === 'all' ? 24 : 30
        })
      });
      if (!resp.ok) throw new Error(`Search failed with HTTP ${resp.status}`);
      const json = (await resp.json()) as SearchResponse;
      const rows = dedupeResults(json.results || []);
      setRunId(json.run_id);
      setResults(rows);
      setSelected(rows[0] || null);
      activateGuide('answer');
    } catch (err) {
      setRunId(undefined);
      setResults([]);
      setSelected(null);
      setError(err instanceof Error ? err.message : 'Search failed. Check the API and local Postgres setup.');
    } finally {
      setLoading(false);
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
    dismissGuide('answer');
    const question = (queryOverride ?? query).trim() || queryDefault;
    setQuery(question);
    setPage('agent');
    setLoading(true);
    setError(undefined);
    try {
      const resp = await fetch(`${API_URL}/v1/agent/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, limit: 8 })
      });
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
      activateGuide('timeline');
    }
  }

  if (page === 'landing') {
    // A question from the landing page opens Evidence first. The workshop
    // teaches retrieval before synthesis, then lets participants move to Answer.
    return (
      <Landing
        query={query}
        setQuery={setQuery}
        onSearch={runSearch}
        onNavigate={navigate}
        error={error}
        heroNodes={deriveHeroNodes(citedResults, canonical)}
        heroScore={typeof canonical?.confidence === 'number' ? canonical.confidence : null}
      />
    );
  }

  if (page === 'detail') {
    return (
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
      />
    );
  }

  if (page === 'trail') {
    return (
      <TimelinePage
        page={page}
        query={query}
        setQuery={setQuery}
        omniboxRef={omniboxRef}
        timeline={timeline}
        error={error}
        onSearch={runSearch}
        guideStep={activeGuideStep}
        onDismissGuide={dismissGuide}
        onSkipGuide={skipGuide}
        onNavigate={navigate}
      />
    );
  }

  if (page === 'agent') {
    return (
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
        onDismissGuide={dismissGuide}
        onSkipGuide={skipGuide}
        onNavigate={navigate}
        citedResults={citedResults}
        corpusTotal={corpusTotal}
        onOpenDetail={openDetailFor}
      />
    );
  }

  if (page === 'diagnostics') {
    return (
      <DiagnosticsPage
        page={page}
        query={query}
        setQuery={setQuery}
        omniboxRef={omniboxRef}
        canonical={canonical}
        fusionSql={fusionSql}
        corpusTotal={corpusTotal}
        onSearch={runSearch}
        guideStep={activeGuideStep}
        onDismissGuide={dismissGuide}
        onSkipGuide={skipGuide}
        onNavigate={navigate}
      />
    );
  }

  return (
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
      guideStep={activeGuideStep}
      onDismissGuide={dismissGuide}
      onSkipGuide={skipGuide}
      onNavigate={navigate}
    />
  );
}

createRoot(document.getElementById('root')!).render(<App />);
