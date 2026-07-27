import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BookOpen,
  Check,
  ChevronRight,
  CircleDot,
  Clipboard,
  Code2,
  Database,
  FileCheck2,
  FileSearch,
  Gauge,
  GitMerge,
  Headphones,
  House,
  LoaderCircle,
  LockKeyhole,
  Network,
  Play,
  RefreshCw,
  Search,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  TriangleAlert,
  Wrench,
  X,
} from 'lucide-react';
import {
  FormEvent,
  ReactNode,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

type ModuleName = 'home' | 'results' | 'retrieve' | 'prove' | 'tools';
type DiagnoseTab = 'retrieval' | 'fusion' | 'plan' | 'scale';
type ProveTab = 'answer' | 'graph' | 'receipt' | 'replay' | 'evaluation';

// Overview-first IA (D16 / SPEC 6.0). Primary nav mirrors the lab ladder;
// each surface is a lens over the same run. The legacy module/proveTab/
// diagnoseTab state is derived from a (surface, subtab) selection so the
// existing panel render tree stays unchanged.
type Surface = 'overview' | 'retrieval' | 'agent' | 'proof' | 'evaluation';

type NavLens = { key: string; label: string; Icon: typeof House };
type NavSurface = {
  surface: Surface;
  label: string;
  Icon: typeof House;
  lenses: NavLens[];
};

// Nav labels are Law-1 nouns (SPEC 6.0). Lens keys map to legacy state in
// goTo(); order is the lab ladder. Corpus/Health utility surfaces land in a
// later pass; Evaluation is the one utility surface wired today.
const PRIMARY_NAV: NavSurface[] = [
  { surface: 'overview', label: 'Overview', Icon: House, lenses: [] },
  {
    surface: 'retrieval',
    label: 'Retrieval',
    Icon: FileSearch,
    lenses: [
      { key: 'results', label: 'Results', Icon: CircleDot },
      { key: 'fusion', label: 'Fusion', Icon: SlidersHorizontal },
      { key: 'plan', label: 'Plan', Icon: Code2 },
    ],
  },
  {
    surface: 'agent',
    label: 'Agent',
    Icon: Sparkles,
    lenses: [
      { key: 'answer', label: 'Answer', Icon: FileCheck2 },
      { key: 'graph', label: 'Graph', Icon: Network },
      { key: 'tools', label: 'Tools', Icon: Wrench },
    ],
  },
  {
    surface: 'proof',
    label: 'Proof',
    Icon: ShieldCheck,
    lenses: [
      { key: 'receipt', label: 'Receipt', Icon: Clipboard },
      { key: 'replay', label: 'Replay', Icon: Play },
    ],
  },
];

const UTILITY_NAV: NavSurface[] = [
  { surface: 'evaluation', label: 'Evaluation', Icon: Gauge, lenses: [] },
];
type RetrievalMode = 'hybrid' | 'semantic' | 'lexical' | 'fuzzy';
type EvidenceKind =
  | 'incident'
  | 'change'
  | 'support_case'
  | 'runbook'
  | 'lock_evidence'
  | 'commitment'
  | 'postmortem';
type JsonRecord = Record<string, unknown>;

// The exact statement the endpoint executed, bound to the visible run, so a
// participant can reproduce a rendered number in psql (Law 2 / gate G-13).
interface VerifySql {
  statement: string;
  binds: Record<string, unknown>;
}

// Panels whose value is a live capture or a harness aggregate cannot be replayed
// from a run_id; they say so honestly instead of publishing a decorative query.
interface VerifySqlUnavailable {
  reproducible: false;
  reason: string;
}

interface Health {
  status: string;
  drift_issues: number;
  current_chunks: number;
  ready_embeddings: number;
  source_documents: number;
  current_documents: number;
  last_indexed_at: string | null;
  cluster_id: string;
  engine_version: string;
  pgvector_version: string | null;
  embedding_spaces: Array<{
    embedding_model: string;
    dimensions: number;
    chunks: number;
  }>;
}

interface EvidenceSnapshot {
  evidence_id?: string;
  evidence_kind?: EvidenceKind;
  external_key?: string;
  title?: string;
  snippet?: string;
  source_system?: string;
  source_uri?: string;
  source_revision?: string;
  cluster_id?: string | null;
  incident_id?: string | null;
  account_name?: string | null;
  severity?: string | null;
  environment?: string | null;
  occurred_at?: string | null;
}

interface Candidate extends EvidenceSnapshot {
  result_rank?: number;
  document_version_id?: string;
  chunk_version_id?: string;
  text_rank?: number | null;
  vector_score?: number | null;
  trigram_score?: number | null;
  text_position?: number | null;
  vector_position?: number | null;
  trigram_position?: number | null;
  exact_identifier_position?: number | null;
  match_tier?: number | null;
  rrf_score?: number | null;
  rerank_score?: number | null;
  final_score?: number | null;
  explanation?: {
    exact_identifier?: boolean;
    note?: string;
    positions?: Record<string, number | null>;
  };
  evidence_snapshot?: EvidenceSnapshot;
}

interface MatchTier {
  tier: number;
  label: string;
  count: number;
  first_rank: number;
  last_rank: number;
}

interface SearchResponse {
  run_id: string;
  results: Candidate[];
  match_tiers?: MatchTier[];
}

interface Citation {
  n?: number;
  citation_number?: number;
  evidence_id?: string;
  external_key: string;
  title: string;
  source_uri: string;
  source_revision: string;
  quote_text?: string;
}

type AgentStreamState =
  | 'blocked'
  | 'streaming'
  | 'complete'
  | 'error';

interface AgentMetadata {
  orchestration?: string;
  framework?: string;
  model_provider?: string;
  synthesis_model?: string;
  model_transport?: string;
  model_selected_tools?: string[];
}

interface AgentTraceEvent {
  type?: string;
  question?: string;
  agent?: AgentMetadata;
  sequence?: number;
  tool?: string;
  arguments?: JsonRecord;
  latency_ms?: number;
  run_id?: string;
  result_count?: number;
  reached_count?: number;
  compared_count?: number;
  subquestion_count?: number;
  citation_count?: number;
  source_run_count?: number;
  status?: string;
  commentary?: string;
  text?: string;
  answer?: string | null;
  citations?: Citation[];
  agent_commentary?: string | null;
  run_ids?: string[];
  usage?: AgentUsage;
  total_latency_ms?: number;
  synthesis_mode?: string | null;
  error?: string;
}

interface AgentUsage {
  cycles?: number;
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
}

interface AnswerReceipt {
  run_id?: string;
  question: string;
  answer_text: string;
  synthesis_mode: string;
  model_id: string | null;
  model_transport: string | null;
  citations: Citation[];
}

interface RunSummary {
  run_id: string;
  query_text: string;
  retrieval_mode: RetrievalMode;
  embedding_model: string | null;
  rerank_model: string | null;
  rerank_applied: boolean;
  rrf_k: number;
  text_weight: number;
  vector_weight: number;
  fuzzy_weight: number;
  fuzzy_threshold: number;
  hnsw_ef_search: number | null;
  hnsw_iterative_scan: string | null;
  status: string;
  latency_ms: number | null;
  candidate_count: number;
  reranked_count: number;
  started_at: string;
  completed_at?: string | null;
  identifier_tokens?: string[];
  fuzzy_probe_tokens?: string[];
  candidate_pool?: number;
}

interface Stage {
  stage_ordinal: number;
  stage_name: string;
  duration_ms: number;
  details: JsonRecord;
}

interface RunReceipt {
  run: RunSummary;
  candidates: Candidate[];
  stages: Stage[];
  answer: AnswerReceipt | null;
  score_note: string;
  _verify_sql?: {
    run: VerifySql;
    candidates: VerifySql;
    stages: VerifySql;
    answer: VerifySql;
  };
}

interface GraphNode {
  evidence_id: string;
  evidence_kind: EvidenceKind;
  external_key: string;
  title: string;
  depth: number;
}

interface GraphEdge {
  edge_key: string;
  from_evidence_id: string;
  from_external_key: string;
  to_evidence_id: string;
  to_external_key: string;
  relation: string;
  origin: string;
  confidence: number;
  _verify_sql?: VerifySql;
}

interface RunGraph {
  run_id: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
  node_count: number;
  edge_count: number;
}

interface EvidenceDetail {
  evidence: EvidenceSnapshot & {
    body?: string;
    metadata?: JsonRecord;
    search_index_version?: string;
    index_state?: string;
  };
  chunks: Array<{
    chunk_version_id: string;
    chunk_text: string;
    embedding_model: string;
    embedding_state: string;
  }>;
  edges: Array<{
    edge_key: string;
    from_evidence_id: string;
    to_evidence_id: string;
    relation: string;
    origin: string;
    confidence: number;
  }>;
}

interface SearchIndexDiagnostics {
  health: {
    source_documents: number;
    current_documents: number;
    current_chunks: number;
    ready_embeddings: number;
    pending_embeddings: number;
    drift_issues: number;
    last_indexed_at: string | null;
  };
  embedding_spaces: Array<{
    embedding_model: string;
    dimensions: number;
    chunks: number;
  }>;
  distribution: Array<{
    evidence_kind: EvidenceKind;
    documents: number;
    chunks: number;
    oldest_evidence: string | null;
    newest_evidence: string | null;
  }>;
  recent_builds: Array<{
    build_id: string;
    status: string;
    document_count: number;
    chunk_count: number;
    cache_hit_count: number;
    embedded_count: number;
    started_at: string;
    completed_at: string | null;
    error?: string | null;
  }>;
}

interface EvaluationResult {
  query_count: number;
  retrieval_query_count: number;
  traversal_query_count: number;
  leaderboard: Array<{
    mode: RetrievalMode;
    successful_runs: number;
    ndcg_at_10: number;
    recall_at_10: number;
    mrr: number;
  }>;
  queries: Array<{
    query_id: string;
    query_text: string;
    evaluation_type: 'retrieval' | 'traversal';
    notes: string;
    results: Array<{
      mode?: RetrievalMode;
      run_id?: string;
      reached_count?: number;
      metrics?: {
        ndcg_at_10?: number;
        recall_at_10?: number;
        precision_at_10?: number;
        mrr?: number;
        recall?: number;
        precision?: number;
      };
      error?: string;
    }>;
  }>;
  metric_note: string;
  _verify_sql?: VerifySqlUnavailable;
}

interface RunTimeline {
  run_id: string;
  edge_count: number;
  events: Array<
    EvidenceSnapshot & {
      evidence_id: string;
      external_key: string;
      evidence_kind: EvidenceKind;
      title: string;
      occurred_at: string | null;
      _verify_sql?: VerifySql;
    }
  >;
}

interface QueryPlanResponse {
  arm: 'semantic' | 'lexical' | 'fuzzy';
  plan: {
    Plan?: JsonRecord;
    'Planning Time'?: number;
    'Execution Time'?: number;
  };
  scans: Array<{
    node_type: string;
    relation: string | null;
    index: string | null;
    actual_rows: number;
    loops: number;
  }>;
  note: string;
  _verify_sql?: VerifySqlUnavailable;
}

interface Controls {
  query: string;
  mode: RetrievalMode;
  kind: EvidenceKind | 'all';
  clusterId: string;
  environment: string;
  limit: number;
  candidatePool: number;
  rrfK: number;
  textWeight: number;
  vectorWeight: number;
  fuzzyWeight: number;
  fuzzyThreshold: number;
  efSearch: number;
  rerank: boolean;
  supportLead: boolean;
}

const API_BASE = (
  import.meta.env.VITE_RETRIEVAL_API_URL || 'http://127.0.0.1:8000'
).replace(/\/$/, '');
const APP_NAME = import.meta.env.VITE_APP_DISPLAY_NAME || 'Verity';
const DEFAULT_QUERY =
  'Why did CHG-1842 block checkout writes during INC-2047, which visible customer was affected, and what was the safe fix?';

const DEFAULT_CONTROLS: Controls = {
  query: DEFAULT_QUERY,
  mode: 'hybrid',
  kind: 'all',
  clusterId: 'checkout-prod-cluster-01',
  environment: 'production',
  limit: 8,
  candidatePool: 24,
  rrfK: 60,
  textWeight: 2,
  vectorWeight: 1,
  fuzzyWeight: 1,
  fuzzyThreshold: 0.3,
  efSearch: 40,
  rerank: false,
  supportLead: false,
};

const PRESETS = [
  {
    label: 'Incident cause',
    query: DEFAULT_QUERY,
    mode: 'hybrid' as RetrievalMode,
    kind: 'all' as const,
    clusterId: 'checkout-prod-cluster-01',
  },
  {
    label: 'Exact CHG-1842',
    query: 'Why did CHG-1842 block writes on checkout-prod-cluster-01?',
    mode: 'hybrid' as RetrievalMode,
    kind: 'all' as const,
    clusterId: 'checkout-prod-cluster-01',
  },
  {
    label: 'Read/write split',
    query:
      'Customers could read order history but new checkouts timed out after maintenance',
    mode: 'hybrid' as RetrievalMode,
    kind: 'all' as const,
    clusterId: '',
  },
  {
    label: 'Typo CGH-1842',
    query: 'CGH-1842',
    mode: 'hybrid' as RetrievalMode,
    kind: 'change' as const,
    clusterId: '',
  },
];

const KIND_LABELS: Record<EvidenceKind, string> = {
  incident: 'Incident',
  change: 'Change',
  support_case: 'Support case',
  runbook: 'Runbook',
  lock_evidence: 'Lock evidence',
  commitment: 'Commitment',
  postmortem: 'Postmortem',
};

const TOOL_NAMES = [
  'decompose_question',
  'search_evidence',
  'follow_evidence_links',
  'compare_sources',
  'explain_ranking',
  'synthesize_cited_answer',
] as const;

const HOME_THREAD_PATHS = [
  'M310 260 C310 190 310 108 310 38',
  'M310 260 C376 216 448 166 528 138',
  'M310 260 C376 304 448 354 528 382',
  'M310 260 C310 330 310 412 310 482',
  'M310 260 C244 304 172 354 92 382',
  'M310 260 C244 216 172 166 92 138',
];

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = (await response.json()) as {
        detail?: string;
        error?: string;
      };
      message = payload.detail || payload.error || message;
    } catch {
      // Keep the HTTP status if the body is not JSON.
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

function numberValue(value: unknown): number | null {
  if (typeof value === 'number') return value;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function score(value: unknown, digits = 4): string {
  const parsed = numberValue(value);
  return parsed === null ? '—' : parsed.toFixed(digits);
}

function dateTime(value?: string | null): string {
  if (!value) return '—';
  const valueDate = new Date(value);
  if (Number.isNaN(valueDate.getTime())) return value;
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(valueDate);
}

function compactId(value?: string | null): string {
  if (!value) return '—';
  return value.length > 20
    ? `${value.slice(0, 8)}…${value.slice(-6)}`
    : value;
}

function parseSseRecord(record: string): AgentTraceEvent | null {
  const lines = record.split(/\r?\n/);
  const eventType = lines
    .find((line) => line.startsWith('event:'))
    ?.slice(6)
    .trim();
  const data = lines
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice(5).trimStart())
    .join('\n');
  if (!data) return null;
  const payload = JSON.parse(data) as AgentTraceEvent;
  return { ...payload, type: payload.type || eventType };
}

function readableToolName(tool?: string): string {
  return (tool || 'agent event').replace(/_/g, ' ');
}

function toolDecision(event: AgentTraceEvent): string {
  const args = event.arguments || {};
  if (event.tool === 'decompose_question') {
    return `Split the compound question into ${event.subquestion_count || 'its'} evidence requirements.`;
  }
  if (event.tool === 'search_evidence') {
    const kinds = Array.isArray(args.kinds)
      ? (args.kinds as string[]).join(', ')
      : 'all evidence';
    const boundedRecovery =
      Array.isArray(args.kinds) &&
      (args.kinds as string[]).includes('runbook') &&
      !args.cluster_id &&
      !args.incident_id;
    return boundedRecovery
      ? `Relaxed incident scope only for reusable ${kinds}; the caller principal stayed fixed.`
      : `Searched ${kinds} with ${args.cluster_id || args.incident_id || 'no scope filter'}.`;
  }
  if (event.tool === 'follow_evidence_links') {
    return `Followed declared relationships from ${
      Array.isArray(args.seed_external_keys)
        ? (args.seed_external_keys as string[]).join(', ')
        : 'retrieved evidence'
    }.`;
  }
  if (event.tool === 'compare_sources') {
    return `Compared ${
      Array.isArray(args.external_keys)
        ? (args.external_keys as string[]).join(', ')
        : 'competing sources'
    } on scope, revision, and relationship.`;
  }
  if (event.tool === 'explain_ranking') {
    return 'Read the persisted rank receipt without recomputing scores.';
  }
  if (event.tool === 'synthesize_cited_answer') {
    return event.status === 'incomplete'
      ? 'Withheld synthesis because a required evidence kind was still missing.'
      : `Validated ${event.citation_count || 'the'} citations across ${
          event.source_run_count || 'the supporting'
        } retrieval runs.`;
  }
  return event.commentary || event.text || 'Recorded an observable agent event.';
}

function toolResult(event: AgentTraceEvent): string {
  if (event.result_count !== undefined) {
    return `${event.result_count} candidates`;
  }
  if (event.reached_count !== undefined) {
    return `${event.reached_count} linked records`;
  }
  if (event.compared_count !== undefined) {
    return `${event.compared_count} sources`;
  }
  if (event.citation_count !== undefined) {
    return `${event.citation_count} citations`;
  }
  if (event.subquestion_count !== undefined) {
    return `${event.subquestion_count} subquestions`;
  }
  return event.status || 'complete';
}

function sourceRole(citation: Citation): string {
  if (citation.external_key === 'RB-017') {
    return 'Approved guidance for recovery and prevention.';
  }
  if (citation.external_key.startsWith('RB-')) {
    return 'Superseded guidance retained for explicit comparison.';
  }
  if (citation.external_key.startsWith('LOCK-')) {
    return 'Observed lock state connecting the blocker to queued writers.';
  }
  if (citation.external_key === 'CASE-7419') {
    return 'Visible customer impact under the workshop principal.';
  }
  if (citation.external_key.startsWith('CASE-')) {
    return 'Comparison case used to rule out unrelated customer impact.';
  }
  if (citation.external_key === 'CHG-1842') {
    return 'Change record and exact DDL executed during the incident.';
  }
  if (citation.external_key.startsWith('CHG-')) {
    return 'Concurrent change compared and ruled out by lock evidence.';
  }
  if (citation.external_key === 'INC-2047') {
    return 'Incident scope, symptom, and impact window.';
  }
  if (citation.external_key.startsWith('INC-')) {
    return 'Look-alike incident retained for scope comparison.';
  }
  return 'Supporting evidence cited by the validated answer.';
}

function elapsedMilliseconds(stages: Stage[], throughIndex: number): number {
  return stages
    .slice(0, throughIndex)
    .reduce((total, stage) => total + stage.duration_ms, 0);
}

function metricBand(value: unknown): 'high' | 'medium' | 'low' | 'empty' {
  const parsed = numberValue(value);
  if (parsed === null) return 'empty';
  if (parsed >= 0.8) return 'high';
  if (parsed >= 0.5) return 'medium';
  return 'low';
}

function formatDuration(seconds: number): string {
  if (seconds < 90) return `${seconds.toFixed(0)} s`;
  if (seconds < 5400) return `${(seconds / 60).toFixed(seconds < 600 ? 1 : 0)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
}

function formatGiB(value: number): string {
  return value < 1
    ? `${Math.round(value * 1024).toLocaleString()} MiB`
    : `${value.toFixed(value < 10 ? 2 : 1)} GiB`;
}

function snapshot(candidate: Candidate): EvidenceSnapshot {
  return {
    ...candidate,
    ...(candidate.evidence_snapshot || {}),
    snippet:
      candidate.evidence_snapshot?.snippet ||
      candidate.snippet ||
      candidate.evidence_snapshot?.title ||
      '',
  };
}

function position(
  candidate: Candidate,
  arm: 'text' | 'vector' | 'fuzzy',
): number | null {
  const direct =
    arm === 'text'
      ? candidate.text_position
      : arm === 'vector'
        ? candidate.vector_position
        : candidate.trigram_position;
  if (typeof direct === 'number') return direct;
  const key =
    arm === 'text' ? 'full_text' : arm === 'vector' ? 'semantic' : 'fuzzy';
  return numberValue(candidate.explanation?.positions?.[key]);
}

function matchTier(candidate: Candidate): number {
  if (typeof candidate.match_tier === 'number') return candidate.match_tier;
  return candidate.explanation?.exact_identifier ? 1 : 2;
}

const TIER_LABELS: Record<number, string> = {
  1: 'Exact identifier',
  2: 'Fused candidates',
};

function tierLabel(tier: number): string {
  return TIER_LABELS[tier] || `Tier ${tier}`;
}

interface TierGroup {
  tier: number;
  count: number;
  rows: Candidate[];
}

// `count` stays the tier's full size while `rows` is truncated, so a heading
// never claims the tier holds only what the column had room to show.
function groupByTier(candidates: Candidate[], visible: number): TierGroup[] {
  const groups: TierGroup[] = [];
  candidates.forEach((candidate, index) => {
    const tier = matchTier(candidate);
    const last = groups[groups.length - 1];
    const group = last?.tier === tier ? last : { tier, count: 0, rows: [] };
    if (group !== last) groups.push(group);
    group.count += 1;
    if (index < visible) group.rows.push(candidate);
  });
  return groups.filter((group) => group.rows.length);
}

function KindIcon({
  kind,
  size = 15,
}: {
  kind?: EvidenceKind;
  size?: number;
}) {
  if (kind === 'incident') return <TriangleAlert size={size} />;
  if (kind === 'change') return <Wrench size={size} />;
  if (kind === 'support_case') return <Headphones size={size} />;
  if (kind === 'runbook') return <BookOpen size={size} />;
  if (kind === 'lock_evidence') return <Activity size={size} />;
  if (kind === 'commitment') return <FileCheck2 size={size} />;
  if (kind === 'postmortem') return <Clipboard size={size} />;
  return <FileSearch size={size} />;
}

function VerityMark({ className = '' }: { className?: string }) {
  return (
    <svg
      className={`verity-mark ${className}`.trim()}
      viewBox="0 0 32 32"
      aria-hidden="true"
      focusable="false"
    >
      <rect className="verity-mark-frame" x="0.75" y="0.75" width="30.5" height="30.5" rx="8" />
      <path
        className="verity-mark-thread"
        d="M7.5 8.5 16 20.5 24.5 8.5M16 6.25v14.25"
      />
      <circle className="verity-mark-source" cx="7.5" cy="8.5" r="2.25" />
      <circle className="verity-mark-source" cx="16" cy="6.25" r="2.25" />
      <circle className="verity-mark-source" cx="24.5" cy="8.5" r="2.25" />
      <circle className="verity-mark-answer" cx="16" cy="23" r="5" />
      <path className="verity-mark-check" d="m13.7 22.9 1.65 1.65 3.1-3.45" />
    </svg>
  );
}

function engineRelease(version: string | undefined): string {
  if (!version) return 'checking';
  const match = version.match(/PostgreSQL\s+([\d.]+)/i);
  return match ? `PostgreSQL ${match[1]}` : version;
}

function LiveBanner({ health }: { health: Health | null }) {
  const indexState =
    health?.status === 'ready' ? 'READY' : health?.status || 'checking';
  return (
    <div className="live-banner" role="status" aria-label="Live cluster status">
      <span className="live-banner-dot" aria-hidden="true" />
      <span className="live-banner-cluster">{health?.cluster_id || '—'}</span>
      <span className="live-banner-sep">·</span>
      <span>search index {indexState}</span>
      <span className="live-banner-sep">·</span>
      <span>{health?.current_documents?.toLocaleString() || '—'} docs</span>
      <span className="live-banner-sep">·</span>
      <span>engine {engineRelease(health?.engine_version)}</span>
      <span className="live-banner-sep">·</span>
      <span>pgvector {health?.pgvector_version || '—'}</span>
    </div>
  );
}

// Inline the named binds as SQL literals so the statement is copy-paste runnable
// in psql. The registry binds only text/uuid keys (run_id, edge_key, evidence_id),
// so a quote-escaped string literal is the correct and complete rendering.
function toPsql(descriptor: VerifySql): string {
  return Object.entries(descriptor.binds).reduce((statement, [name, value]) => {
    const literal =
      value === null || value === undefined
        ? 'NULL'
        : `'${String(value).replace(/'/g, "''")}'`;
    const token = `%(${name})s`.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return statement.replace(new RegExp(token, 'g'), literal);
  }, descriptor.statement);
}

// The "verify in psql" affordance (SPEC 6.2). An inline disclosure — never a
// modal — that reveals the exact statement the endpoint ran, bound to the
// visible run, with a copy button. Panels that cannot be reproduced from a
// run_id render their honest {reproducible:false, reason} label instead.
function VerifyAffordance({
  descriptor,
  label = 'verify in psql',
}: {
  descriptor?: VerifySql | VerifySqlUnavailable;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  if (!descriptor) return null;

  if ('reproducible' in descriptor) {
    return (
      <span className="verify-affordance verify-unavailable" role="note">
        <AlertTriangle size={12} aria-hidden="true" />
        not run-reproducible · {descriptor.reason}
      </span>
    );
  }

  const sql = toPsql(descriptor);
  return (
    <span className="verify-affordance">
      <button
        type="button"
        className={`verify-trigger ${open ? 'open' : ''}`}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <Code2 size={12} aria-hidden="true" />
        {label}
        <ChevronRight
          size={12}
          className={`verify-caret ${open ? 'open' : ''}`}
          aria-hidden="true"
        />
      </button>
      {open ? (
        <span className="verify-disclosure">
          <span className="verify-disclosure-head">
            <span className="verify-disclosure-title">exact statement · run-bound</span>
            <button
              type="button"
              className="verify-copy"
              onClick={async () => {
                await navigator.clipboard.writeText(sql);
                setCopied(true);
                window.setTimeout(() => setCopied(false), 1200);
              }}
            >
              {copied ? <Check size={12} /> : <Clipboard size={12} />}
              {copied ? 'copied' : 'copy'}
            </button>
          </span>
          <pre className="verify-sql">{sql}</pre>
        </span>
      ) : null}
    </span>
  );
}

function Empty({
  icon,
  title,
  detail,
}: {
  icon: ReactNode;
  title: string;
  detail?: string;
}) {
  return (
    <div className="empty-state">
      {icon}
      <strong>{title}</strong>
      {detail ? <span>{detail}</span> : null}
    </div>
  );
}

function FormattedAnswer({ text }: { text: string }) {
  return (
    <>
      {text.split(/(`[^`]+`|\[\d+\])/g).map((part, index) => {
        if (part.startsWith('`') && part.endsWith('`')) {
          return <code key={index}>{part.slice(1, -1)}</code>;
        }
        if (/^\[\d+\]$/.test(part)) {
          return <sup key={index}>{part.slice(1, -1)}</sup>;
        }
        return part;
      })}
    </>
  );
}

function CandidateRow({
  candidate,
  rank,
  selected,
  diagnostic,
  onSelect,
}: {
  candidate: Candidate;
  rank: number;
  selected: boolean;
  diagnostic: ReactNode;
  onSelect: () => void;
}) {
  const item = snapshot(candidate);
  return (
    <button
      className={`arm-item ${selected ? 'selected' : ''}`}
      onClick={onSelect}
      type="button"
    >
      <span className="arm-rank">{rank}</span>
      <span className={`kind-glyph kind-${item.evidence_kind || 'unknown'}`}>
        <KindIcon kind={item.evidence_kind} />
      </span>
      <span className="arm-copy">
        <span className="arm-key">
          {item.external_key || 'Unknown'}
          {candidate.explanation?.exact_identifier ? (
            <CircleDot size={11} aria-label="Exact identifier" />
          ) : null}
        </span>
        <span className="arm-title">{item.title || 'Untitled evidence'}</span>
      </span>
      <span className="arm-diagnostic">{diagnostic}</span>
    </button>
  );
}

function RetrievalArm({
  title,
  subtitle,
  candidates,
  selectedEvidenceId,
  diagnostic,
  onSelect,
  fused = false,
}: {
  title: string;
  subtitle: string;
  candidates: Candidate[];
  selectedEvidenceId: string | null;
  diagnostic: (candidate: Candidate) => ReactNode;
  onSelect: (candidate: Candidate) => void;
  fused?: boolean;
}) {
  return (
    <section className={`retrieval-arm ${fused ? 'fused' : ''}`}>
      <header>
        <div>
          <span className="section-label">{title}</span>
          <p>{subtitle}</p>
        </div>
        <span className="count-badge">{candidates.length}</span>
      </header>
      <div className="arm-list">
        {!candidates.length ? (
          <Empty
            icon={<FileSearch size={18} />}
            title="No candidates"
            detail="The arm returned an empty set."
          />
        ) : fused ? (
          groupByTier(candidates, 6).map((group) => (
            <div className="tier-group" key={group.tier}>
              <span className={`tier-heading tier-${group.tier}`}>
                {group.tier === 1 ? <CircleDot size={11} /> : null}
                {tierLabel(group.tier)}
                <small>{group.count}</small>
              </span>
              {group.rows.map((candidate, index) => (
                <CandidateRow
                  key={`${candidate.evidence_id}-${index}`}
                  candidate={candidate}
                  rank={candidate.result_rank || index + 1}
                  selected={candidate.evidence_id === selectedEvidenceId}
                  diagnostic={diagnostic(candidate)}
                  onSelect={() => onSelect(candidate)}
                />
              ))}
            </div>
          ))
        ) : (
          candidates.slice(0, 6).map((candidate, index) => (
            <CandidateRow
              key={`${candidate.evidence_id}-${index}`}
              candidate={candidate}
              rank={index + 1}
              selected={candidate.evidence_id === selectedEvidenceId}
              diagnostic={diagnostic(candidate)}
              onSelect={() => onSelect(candidate)}
            />
          ))
        )}
      </div>
    </section>
  );
}

function armContribution(
  candidate: Candidate,
  arm: 'text' | 'vector' | 'fuzzy',
  controls: Controls,
): number {
  const rank = position(candidate, arm);
  if (rank === null) return 0;
  const weight =
    arm === 'text'
      ? controls.textWeight
      : arm === 'vector'
        ? controls.vectorWeight
        : controls.fuzzyWeight;
  return weight / (controls.rrfK + rank);
}

function SignalCell({
  positionValue,
  rawValue,
  rawLabel,
}: {
  positionValue: number | null;
  rawValue: unknown;
  rawLabel: string;
}) {
  return positionValue === null ? (
    <span className="signal-empty">absent · +0</span>
  ) : (
    <span className="signal-cell">
      <strong>#{positionValue}</strong>
      <small>
        {rawLabel} {score(rawValue, 3)}
      </small>
    </span>
  );
}

function FusionAnatomyTable({
  candidates,
  controls,
  onSelect,
}: {
  candidates: Candidate[];
  controls: Controls;
  onSelect: (candidate: Candidate) => void;
}) {
  const maximum =
    Math.max(
      ...candidates.map(
        (candidate) =>
          armContribution(candidate, 'text', controls) +
          armContribution(candidate, 'vector', controls) +
          armContribution(candidate, 'fuzzy', controls),
      ),
      0.00001,
    ) || 1;

  return (
    <div className="table-scroll fusion-table">
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>
              Tier
              <small>ordered before RRF</small>
            </th>
            <th>Evidence</th>
            <th>
              Full-text
              <small>rank · ts_rank diagnostic</small>
            </th>
            <th>
              Semantic
              <small>rank · similarity diagnostic</small>
            </th>
            <th>
              Fuzzy
              <small>rank · trigram diagnostic</small>
            </th>
            <th>
              RRF contribution
              <small>shared rank scale</small>
            </th>
            <th>Aurora RRF</th>
            <th>Rerank</th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((candidate, index) => {
            const text = armContribution(candidate, 'text', controls);
            const vector = armContribution(candidate, 'vector', controls);
            const fuzzy = armContribution(candidate, 'fuzzy', controls);
            const total = text + vector + fuzzy;
            const item = snapshot(candidate);
            const tier = matchTier(candidate);
            return (
              <tr
                key={`${candidate.evidence_id}-${index}`}
                className="selectable-row"
                onClick={() => onSelect(candidate)}
              >
                <td>{candidate.result_rank || index + 1}</td>
                <td>
                  <span className={`tier-chip tier-${tier}`}>
                    {tier === 1 ? <CircleDot size={10} /> : null}
                    {tier === 1 ? 'exact' : 'fused'}
                  </span>
                </td>
                <td>
                  <strong>{item.external_key}</strong>
                  <span>{item.title}</span>
                </td>
                <td>
                  <SignalCell
                    positionValue={position(candidate, 'text')}
                    rawValue={candidate.text_rank}
                    rawLabel="raw"
                  />
                </td>
                <td>
                  <SignalCell
                    positionValue={position(candidate, 'vector')}
                    rawValue={candidate.vector_score}
                    rawLabel="raw"
                  />
                </td>
                <td>
                  <SignalCell
                    positionValue={position(candidate, 'fuzzy')}
                    rawValue={candidate.trigram_score}
                    rawLabel="raw"
                  />
                </td>
                <td>
                  <div
                    className="contribution-bar"
                    style={{ width: `${Math.max((total / maximum) * 100, 4)}%` }}
                    aria-label={`Text ${text.toFixed(5)}, semantic ${vector.toFixed(5)}, fuzzy ${fuzzy.toFixed(5)}`}
                  >
                    {total ? (
                      <>
                        <i
                          className="contribution-text"
                          style={{ width: `${(text / total) * 100}%` }}
                        />
                        <i
                          className="contribution-vector"
                          style={{ width: `${(vector / total) * 100}%` }}
                        />
                        <i
                          className="contribution-fuzzy"
                          style={{ width: `${(fuzzy / total) * 100}%` }}
                        />
                      </>
                    ) : null}
                  </div>
                </td>
                <td className="score-value">
                  {score(candidate.rrf_score ?? total, 5)}
                </td>
                <td className="score-value">
                  {score(candidate.rerank_score, 3)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function FusionControlPanel({
  controls,
  advancedOpen,
  onToggleAdvanced,
  onChange,
  onRun,
  busy,
}: {
  controls: Controls;
  advancedOpen: boolean;
  onToggleAdvanced: () => void;
  onChange: <K extends keyof Controls>(key: K, value: Controls[K]) => void;
  onRun: () => void;
  busy: boolean;
}) {
  return (
    <section className="fusion-controls">
      <header>
        <span className="section-label">Fusion controls</span>
        <div className="control-actions">
          <button
            type="button"
            className="text-command"
            onClick={onToggleAdvanced}
          >
            <SlidersHorizontal size={14} />
            {advancedOpen ? 'Close' : 'More'}
          </button>
          <button
            type="button"
            className="run-button"
            onClick={onRun}
            disabled={busy || !controls.query.trim()}
          >
            {busy ? (
              <LoaderCircle className="spin" size={14} />
            ) : (
              <Play size={13} />
            )}
            Apply & run
          </button>
        </div>
      </header>
      {(
        [
          ['rrfK', 'RRF k', 1, 200, 1],
          ['textWeight', 'Full-text', 0, 4, 0.25],
          ['vectorWeight', 'Semantic', 0, 4, 0.25],
          ['fuzzyWeight', 'Fuzzy', 0, 4, 0.25],
        ] as const
      ).map(([key, label, min, max, step]) => (
        <label key={key}>
          <span>{label}</span>
          <input
            type="range"
            min={min}
            max={max}
            step={step}
            value={controls[key]}
            onChange={(event) =>
              onChange(key, Number(event.target.value) as Controls[typeof key])
            }
          />
          <output>
            {key === 'rrfK'
              ? controls[key]
              : Number(controls[key]).toFixed(2)}
          </output>
        </label>
      ))}
      {advancedOpen ? (
        <div className="advanced-fields">
          <label>
            <span>Candidate pool</span>
            <input
              type="number"
              min={8}
              max={controls.efSearch}
              value={controls.candidatePool}
              onChange={(event) =>
                onChange('candidatePool', Number(event.target.value))
              }
            />
          </label>
          <label>
            <span>HNSW ef_search</span>
            <input
              type="number"
              min={controls.candidatePool}
              max={1000}
              value={controls.efSearch}
              onChange={(event) =>
                onChange('efSearch', Number(event.target.value))
              }
            />
          </label>
          <label>
            <span>Fuzzy threshold</span>
            <input
              type="number"
              min={0.1}
              max={1}
              step={0.05}
              value={controls.fuzzyThreshold}
              onChange={(event) =>
                onChange('fuzzyThreshold', Number(event.target.value))
              }
            />
          </label>
          <label>
            <span>Evidence kind</span>
            <select
              value={controls.kind}
              onChange={(event) =>
                onChange(
                  'kind',
                  event.target.value as EvidenceKind | 'all',
                )
              }
            >
              <option value="all">All kinds</option>
              {Object.entries(KIND_LABELS).map(([kind, label]) => (
                <option key={kind} value={kind}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
      ) : null}
    </section>
  );
}

const NODE_HALF_WIDTH = 62;
const NODE_HALF_HEIGHT = 24;

interface Point {
  x: number;
  y: number;
}

// Edges stop at the box border rather than the box centre, so an arrowhead
// lands where a reader can see it instead of underneath the node it points at.
function edgeAnchors(from: Point, to: Point): [Point, Point] {
  const horizontal = Math.abs(to.x - from.x) > NODE_HALF_WIDTH;
  if (!horizontal) {
    const down = to.y > from.y;
    return [
      { x: from.x, y: from.y + (down ? NODE_HALF_HEIGHT : -NODE_HALF_HEIGHT) },
      { x: to.x, y: to.y + (down ? -NODE_HALF_HEIGHT : NODE_HALF_HEIGHT) },
    ];
  }
  const right = to.x > from.x;
  return [
    { x: from.x + (right ? NODE_HALF_WIDTH : -NODE_HALF_WIDTH), y: from.y },
    { x: to.x + (right ? -NODE_HALF_WIDTH : NODE_HALF_WIDTH), y: to.y },
  ];
}

function EvidenceGraph({
  graph,
  onSelect,
  selectedEvidenceId,
}: {
  graph: RunGraph;
  onSelect: (evidenceId: string) => void;
  selectedEvidenceId: string | null;
}) {
  const width = 880;
  const height = 500;
  // Rightmost column plus NODE_HALF_WIDTH must stay inside `width`, or the
  // canvas needs a scrollbar and the last column's labels get cut off.
  const columns: Record<EvidenceKind, number> = {
    change: 100,
    lock_evidence: 270,
    incident: 440,
    support_case: 610,
    runbook: 780,
    commitment: 780,
    postmortem: 610,
  };
  const byKind: Record<EvidenceKind, GraphNode[]> = {
    incident: [],
    change: [],
    support_case: [],
    runbook: [],
    lock_evidence: [],
    commitment: [],
    postmortem: [],
  };
  graph.nodes.forEach((node) => {
    const bucket = byKind[node.evidence_kind];
    if (bucket) bucket.push(node);
  });
  const locations = new Map<string, { x: number; y: number }>();
  (Object.keys(byKind) as EvidenceKind[]).forEach((kind) => {
    byKind[kind].forEach((node, index, nodes) => {
      locations.set(node.evidence_id, {
        x: columns[kind],
        y: (height / (nodes.length + 1)) * (index + 1),
      });
    });
  });
  return (
    <div className="graph-scroll">
      <svg
        className="evidence-graph"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`${graph.node_count} evidence nodes and ${graph.edge_count} edges`}
      >
        <defs>
          <marker
            id="graph-arrow-canonical"
            viewBox="0 0 8 8"
            refX="7"
            refY="4"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M0 0 L8 4 L0 8 z" className="graph-arrow" />
          </marker>
          <marker
            id="graph-arrow-inferred"
            viewBox="0 0 8 8"
            refX="7"
            refY="4"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M0 1 L8 4 L0 7 z" className="graph-arrow inferred" />
          </marker>
        </defs>
        {graph.edges.map((edge) => {
          const from = locations.get(edge.from_evidence_id);
          const to = locations.get(edge.to_evidence_id);
          if (!from || !to) return null;
          const inferred = edge.origin === 'inferred';
          const [start, end] = edgeAnchors(from, to);
          return (
            <line
              key={edge.edge_key}
              x1={start.x}
              y1={start.y}
              x2={end.x}
              y2={end.y}
              markerEnd={`url(#graph-arrow-${inferred ? 'inferred' : 'canonical'})`}
              className={`graph-edge ${inferred ? 'inferred' : ''}`}
            />
          );
        })}
        {graph.nodes.map((node) => {
          const location = locations.get(node.evidence_id);
          if (!location) return null;
          return (
            <g
              key={node.evidence_id}
              className={`graph-node kind-${node.evidence_kind} ${
                node.evidence_id === selectedEvidenceId ? 'selected' : ''
              }`}
              transform={`translate(${location.x - 62} ${location.y - 24})`}
              onClick={() => onSelect(node.evidence_id)}
              role="button"
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  onSelect(node.evidence_id);
                }
              }}
            >
              <rect width="124" height="48" rx="5" />
              <text x="62" y="20" textAnchor="middle" className="graph-key">
                {node.external_key}
              </text>
              <text x="62" y="36" textAnchor="middle" className="graph-kind">
                {KIND_LABELS[node.evidence_kind]}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export default function VerityApp() {
  const [module, setModule] = useState<ModuleName>('home');
  const [diagnoseTab, setDiagnoseTab] =
    useState<DiagnoseTab>('fusion');
  const [proveTab, setProveTab] = useState<ProveTab>('answer');
  const [controls, setControls] = useState<Controls>(DEFAULT_CONTROLS);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [diagnostics, setDiagnostics] =
    useState<SearchIndexDiagnostics | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(
    null,
  );
  const [evidenceDetail, setEvidenceDetail] =
    useState<EvidenceDetail | null>(null);
  const [receipt, setReceipt] = useState<RunReceipt | null>(null);
  const [graph, setGraph] = useState<RunGraph | null>(null);
  const [timeline, setTimeline] = useState<RunTimeline | null>(null);
  const [answer, setAnswer] = useState<AnswerReceipt | null>(null);
  const [evaluation, setEvaluation] = useState<EvaluationResult | null>(null);
  const [planArm, setPlanArm] =
    useState<QueryPlanResponse['arm']>('semantic');
  const [queryPlan, setQueryPlan] = useState<QueryPlanResponse | null>(null);
  const [graphDepth, setGraphDepth] = useState(2);
  const [graphEdgeMode, setGraphEdgeMode] =
    useState<'canonical' | 'all'>('all');
  const [scalePosition, setScalePosition] = useState(0);
  const [scaleSelectivity, setScaleSelectivity] = useState(40);
  const [scaleRamGiB, setScaleRamGiB] = useState(32);
  const [optimizedReads, setOptimizedReads] = useState(false);
  const [runId, setRunId] = useState('');
  const [selectedTool, setSelectedTool] =
    useState<(typeof TOOL_NAMES)[number]>('search_evidence');
  const [busy, setBusy] = useState<
    'search' | 'answer' | 'run' | 'evaluation' | 'plan' | null
  >(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [resultRevealCount, setResultRevealCount] = useState(0);
  const [agentStreamState, setAgentStreamState] =
    useState<AgentStreamState>('blocked');
  const [streamingAnswer, setStreamingAnswer] = useState('');
  const [agentTrace, setAgentTrace] = useState<AgentTraceEvent[]>([]);
  const [streamCitations, setStreamCitations] = useState<Citation[]>([]);
  const [agentMetadata, setAgentMetadata] = useState<AgentMetadata | null>(null);
  const [agentCommentary, setAgentCommentary] = useState('');
  const [agentUsage, setAgentUsage] = useState<AgentUsage | null>(null);
  const [agentLatencyMs, setAgentLatencyMs] = useState<number | null>(null);
  const [homeQueryText, setHomeQueryText] = useState('');
  const [homeTyping, setHomeTyping] = useState(true);
  const [homeReceiptLoading, setHomeReceiptLoading] = useState(true);
  const homeTypingInterrupted = useRef(false);
  const homeQueryInput = useRef<HTMLInputElement>(null);

  const selectedCandidate = useMemo(
    () =>
      candidates.find(
        (candidate) => candidate.evidence_id === selectedEvidenceId,
      ) || null,
    [candidates, selectedEvidenceId],
  );

  const textCandidates = useMemo(
    () =>
      candidates
        .filter(
          (candidate) =>
            position(candidate, 'text') !== null ||
            candidate.explanation?.exact_identifier,
        )
        .sort(
          (left, right) =>
            (position(left, 'text') || 999) -
            (position(right, 'text') || 999),
        ),
    [candidates],
  );
  const vectorCandidates = useMemo(
    () =>
      candidates
        .filter((candidate) => position(candidate, 'vector') !== null)
        .sort(
          (left, right) =>
            (position(left, 'vector') || 999) -
            (position(right, 'vector') || 999),
        ),
    [candidates],
  );
  const fuzzyCandidates = useMemo(
    () =>
      candidates
        .filter((candidate) => position(candidate, 'fuzzy') !== null)
        .sort(
          (left, right) =>
            (position(left, 'fuzzy') || 999) -
            (position(right, 'fuzzy') || 999),
        ),
    [candidates],
  );

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setHomeQueryText(DEFAULT_QUERY);
      setHomeTyping(false);
      return;
    }

    let character = 0;
    let timer = 0;
    const typeNext = () => {
      if (homeTypingInterrupted.current) return;
      character += 1;
      setHomeQueryText(DEFAULT_QUERY.slice(0, character));
      if (character >= DEFAULT_QUERY.length) {
        setHomeTyping(false);
        return;
      }
      const typed = DEFAULT_QUERY[character - 1];
      timer = window.setTimeout(
        typeNext,
        typed === ',' || typed === '?' ? 90 : typed === ' ' ? 28 : 18,
      );
    };

    timer = window.setTimeout(typeNext, 180);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    const input = homeQueryInput.current;
    if (!input) return;
    input.scrollLeft = homeTyping ? input.scrollWidth : 0;
  }, [homeQueryText, homeTyping]);

  useEffect(() => {
    if (module !== 'results' || busy || !candidates.length) return;
    setResultRevealCount(0);
    let count = 0;
    const timer = window.setInterval(() => {
      count += 1;
      setResultRevealCount(count);
      if (count >= candidates.length) window.clearInterval(timer);
    }, 170);
    return () => window.clearInterval(timer);
  }, [module, busy, candidates]);

  useEffect(() => {
    let cancelled = false;
    api<Health>('/ready')
      .then((ready) => {
        if (!cancelled) setHealth(ready);
      })
      .catch((reason: Error) => {
        if (!cancelled) setError(reason.message);
      });
    api<SearchIndexDiagnostics>('/v1/diagnostics/search-index')
      .then((searchIndex) => {
        if (!cancelled) setDiagnostics(searchIndex);
      })
      .catch((reason: Error) => {
        if (!cancelled) setError(reason.message);
      });
    void (async () => {
      try {
        const latest = await api<{ run_id: string }>('/v1/runs/latest');
        if (!cancelled) await loadRun(latest.run_id);
      } catch {
        // A new environment can be ready before it has a cited receipt.
      } finally {
        if (!cancelled) setHomeReceiptLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedEvidenceId) {
      setEvidenceDetail(null);
      return;
    }
    let cancelled = false;
    api<EvidenceDetail>(`/v1/evidence/${selectedEvidenceId}`)
      .then((detail) => {
        if (!cancelled) setEvidenceDetail(detail);
      })
      .catch(() => {
        if (!cancelled) setEvidenceDetail(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedEvidenceId]);

  function setControl<K extends keyof Controls>(key: K, value: Controls[K]) {
    setControls((current) => ({ ...current, [key]: value }));
  }

  // Single navigation writer (SPEC 6.0). Every nav item, entry card, and
  // inline hand-off routes through here so the (surface, lens) selection stays
  // the source of truth; PR-5's URL router will drive the same helper.
  function goTo(surface: Surface, lens?: string) {
    switch (surface) {
      case 'overview':
        setModule('home');
        break;
      case 'retrieval':
        if (lens === 'fusion' || lens === 'plan') {
          setModule('retrieve');
          setDiagnoseTab(lens);
          if (lens === 'plan' && !queryPlan) void loadQueryPlan();
        } else {
          setModule('results');
        }
        break;
      case 'agent':
        if (lens === 'tools') {
          setModule('tools');
        } else {
          setModule('prove');
          setProveTab(lens === 'graph' ? 'graph' : 'answer');
        }
        break;
      case 'proof':
        setModule('prove');
        setProveTab(lens === 'replay' ? 'replay' : 'receipt');
        break;
      case 'evaluation':
        setModule('prove');
        setProveTab('evaluation');
        break;
    }
  }

  // Which primary surface + lens is live, derived from legacy state so the nav
  // highlight and the render tree never disagree.
  const activeSurface: Surface =
    module === 'home'
      ? 'overview'
      : module === 'results' || module === 'retrieve'
        ? 'retrieval'
        : module === 'tools'
          ? 'agent'
          : proveTab === 'evaluation'
            ? 'evaluation'
            : proveTab === 'receipt' || proveTab === 'replay'
              ? 'proof'
              : 'agent';
  const activeLens: string =
    activeSurface === 'retrieval'
      ? module === 'results'
        ? 'results'
        : diagnoseTab
      : activeSurface === 'agent'
        ? module === 'tools'
          ? 'tools'
          : proveTab
        : activeSurface === 'proof'
          ? proveTab
          : '';

  function interruptHomeTypewriter() {
    if (!homeTyping) return;
    homeTypingInterrupted.current = true;
    setHomeTyping(false);
    setControl('query', homeQueryText);
  }

  function searchPayload() {
    return {
      query: controls.query,
      mode: controls.mode,
      kinds: controls.kind === 'all' ? null : [controls.kind],
      cluster_id: controls.clusterId || null,
      incident_id: null,
      environment: controls.environment || null,
      limit: controls.limit,
      candidate_pool: controls.candidatePool,
      rrf_k: controls.rrfK,
      w_text: controls.textWeight,
      w_vector: controls.vectorWeight,
      w_trgm: controls.fuzzyWeight,
      fuzzy_threshold: controls.fuzzyThreshold,
      ef_search: controls.efSearch,
      iterative_scan: 'relaxed_order',
      rerank: controls.rerank,
      principal: {
        scopes: ['workshop'],
        principals: controls.supportLead ? ['support-lead'] : [],
      },
    };
  }

  async function loadRun(id: string | undefined) {
    const runKey = encodeURIComponent((id || '').trim());
    if (!runKey) return;
    setBusy('run');
    setError(null);
    try {
      const [runReceipt, runGraph, runTimeline] = await Promise.all([
        api<RunReceipt>(`/v1/runs/${runKey}`),
        api<RunGraph>(`/v1/runs/${runKey}/graph`),
        api<RunTimeline>(`/v1/runs/${runKey}/timeline`),
      ]);
      const ranked = runReceipt.candidates.map((candidate, index) => ({
        ...candidate,
        result_rank: candidate.result_rank || index + 1,
      }));
      setReceipt(runReceipt);
      setGraph(runGraph);
      setTimeline(runTimeline);
      setCandidates(ranked);
      setAnswer(runReceipt.answer);
      setRunId(runReceipt.run.run_id);
      setSelectedEvidenceId((current) =>
        ranked.some((candidate) => candidate.evidence_id === current)
          ? current
          : ranked[0]?.evidence_id || null,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Run unavailable');
    } finally {
      setBusy(null);
    }
  }

  async function loadQueryPlan(arm = planArm) {
    if (!controls.query.trim()) return;
    setBusy('plan');
    setError(null);
    try {
      const result = await api<QueryPlanResponse>('/v1/diagnostics/plan', {
        method: 'POST',
        body: JSON.stringify({
          query: controls.query,
          arm,
          limit: controls.limit,
          cluster_id: controls.clusterId || null,
          kinds: controls.kind === 'all' ? null : [controls.kind],
          principal: {
            scopes: ['workshop'],
            principals: controls.supportLead ? ['support-lead'] : [],
          },
        }),
      });
      setPlanArm(arm);
      setQueryPlan(result);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : 'Query plan unavailable',
      );
    } finally {
      setBusy(null);
    }
  }

  async function runSearch(event?: FormEvent) {
    event?.preventDefault();
    if (!controls.query.trim()) return;
    setBusy('search');
    setError(null);
    setAnswer(null);
    try {
      const response = await api<SearchResponse>('/v1/search', {
        method: 'POST',
        body: JSON.stringify(searchPayload()),
      });
      const ranked = response.results.map((candidate, index) => ({
        ...candidate,
        result_rank: index + 1,
      }));
      setCandidates(ranked);
      setRunId(response.run_id);
      setSelectedEvidenceId(ranked[0]?.evidence_id || null);
      await loadRun(response.run_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Search unavailable');
    } finally {
      setBusy(null);
    }
  }

  async function beginInvestigation() {
    if (!controls.query.trim()) return;
    setAgentStreamState('blocked');
    setStreamingAnswer('');
    setAgentTrace([]);
    setStreamCitations([]);
    setAgentMetadata(null);
    setAgentCommentary('');
    setAgentUsage(null);
    setAgentLatencyMs(null);
    setModule('results');
    setResultRevealCount(0);
    await runSearch();
  }

  function openAnswerExercise() {
    setAgentStreamState('blocked');
    setStreamingAnswer('');
    setAgentTrace([]);
    setStreamCitations([]);
    setAgentMetadata(null);
    setAgentCommentary('');
    setAgentUsage(null);
    setAgentLatencyMs(null);
    setAnswer(null);
    setModule('prove');
    setProveTab('answer');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  async function askAgent() {
    if (!controls.query.trim()) return;
    setModule('prove');
    setProveTab('answer');
    window.scrollTo({ top: 0, behavior: 'smooth' });
    setBusy('answer');
    setError(null);
    setAgentStreamState('streaming');
    setStreamingAnswer('');
    setAgentTrace([]);
    setStreamCitations([]);
    setAgentMetadata(null);
    setAgentCommentary('');
    setAgentUsage(null);
    setAgentLatencyMs(null);
    setAnswer(null);

    let completedRunId = '';
    let streamCompleted = false;
    try {
      const response = await fetch(
        `${API_BASE}/v1/agent/strands/answer/stream`,
        {
        method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: controls.query,
            max_tool_calls: 12,
          principal: {
            scopes: ['workshop'],
            principals: controls.supportLead ? ['support-lead'] : [],
          },
        }),
        },
      );
      if (!response.ok) {
        let message = `${response.status} ${response.statusText}`;
        try {
          const payload = JSON.parse(await response.text()) as {
            detail?: string;
            error?: string;
          };
          message = payload.detail || payload.error || message;
        } catch {
          // Keep the HTTP status if the body is not JSON.
        }
        throw new Error(message);
      }
      if (!response.body) {
        throw new Error('The Strands endpoint returned no event stream.');
      }

      const reducedMotion = window.matchMedia(
        '(prefers-reduced-motion: reduce)',
      ).matches;
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      const consumeEvent = async (event: AgentTraceEvent) => {
        if (event.type === 'meta') {
          setAgentMetadata(event.agent || null);
          return;
        }
        if (event.type === 'tool_call') {
          setAgentTrace((current) => {
            if (
              event.sequence &&
              current.some((item) => item.sequence === event.sequence)
            ) {
              return current;
            }
            return [...current, event];
          });
          return;
        }
        if (event.type === 'commentary') {
          setAgentCommentary(event.commentary || event.text || '');
          return;
        }
        if (event.type === 'answer_token') {
          setStreamingAnswer((current) => current + (event.text || ''));
          if (!reducedMotion) {
            await new Promise<void>((resolve) =>
              window.setTimeout(resolve, 18),
            );
          }
          return;
        }
        if (event.type === 'citations') {
          setStreamCitations(event.citations || []);
          return;
        }
        if (event.type === 'error') {
          setAgentStreamState('error');
          setError(event.error || 'The Strands agent stream failed.');
          return;
        }
        if (event.type !== 'done') return;

        streamCompleted = true;
        completedRunId = event.run_id || '';
        setAgentMetadata(event.agent || null);
        setAgentCommentary(event.agent_commentary || '');
        setAgentUsage(event.usage || null);
        setAgentLatencyMs(event.total_latency_ms ?? null);
        setStreamCitations(event.citations || []);
        if (event.answer) setStreamingAnswer(event.answer);

        const citedKeys = new Set(
          (event.citations || []).map((citation) => citation.external_key),
        );
        const requiredEvidenceCited =
          [...citedKeys].some((key) => key.startsWith('CHG-')) &&
          [...citedKeys].some((key) => key.startsWith('LOCK-')) &&
          [...citedKeys].some((key) => key.startsWith('CASE-')) &&
          citedKeys.has('RB-017');
        if (
          event.status !== 'complete' ||
          !event.answer ||
          !completedRunId ||
          !requiredEvidenceCited
        ) {
          setAgentStreamState('error');
          setError(
            event.error ||
              'The agent stopped before every required claim had cited evidence.',
          );
          return;
        }

        setAnswer({
          run_id: completedRunId,
          question: event.question || controls.query,
          answer_text: event.answer,
          synthesis_mode: event.synthesis_mode || 'validated',
          model_id: event.agent?.synthesis_model || null,
          model_transport: event.agent?.model_transport || null,
          citations: event.citations || [],
        });
        setRunId(completedRunId);
        setAgentStreamState('complete');
      };

      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value, { stream: !done });
        let boundary = buffer.indexOf('\n\n');
        while (boundary >= 0) {
          const record = buffer.slice(0, boundary).trim();
          buffer = buffer.slice(boundary + 2);
          if (record) {
            const event = parseSseRecord(record);
            if (event) await consumeEvent(event);
          }
          boundary = buffer.indexOf('\n\n');
        }
        if (done) break;
      }
      const finalRecord = buffer.trim();
      if (finalRecord) {
        const event = parseSseRecord(finalRecord);
        if (event) await consumeEvent(event);
      }
      if (!streamCompleted) {
        throw new Error('The Strands event stream ended before a final receipt.');
      }
      if (completedRunId) {
        await loadRun(completedRunId);
      }
    } catch (reason) {
      setAgentStreamState('error');
      setError(reason instanceof Error ? reason.message : 'Answer unavailable');
    } finally {
      setBusy(null);
    }
  }

  async function runEvaluation() {
    setBusy('evaluation');
    setError(null);
    try {
      setEvaluation(
        await api<EvaluationResult>('/v1/evaluation', {
          method: 'POST',
          body: JSON.stringify({
            modes: ['hybrid', 'semantic', 'lexical', 'fuzzy'],
            limit: 10,
          }),
        }),
      );
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : 'Evaluation unavailable',
      );
    } finally {
      setBusy(null);
    }
  }

  function selectCandidate(candidate: Candidate) {
    setSelectedEvidenceId(candidate.evidence_id || null);
  }

  const activeEvidence = selectedCandidate
    ? snapshot(selectedCandidate)
    : evidenceDetail?.evidence || null;
  const latestBuild = diagnostics?.recent_builds[0];
  const embeddingModel =
    health?.embedding_spaces[0]?.embedding_model || 'checking';
  const visibleGraph = useMemo<RunGraph | null>(() => {
    if (!graph) return null;
    const nodes = graph.nodes.filter((node) => node.depth <= graphDepth);
    const nodeIds = new Set(nodes.map((node) => node.evidence_id));
    const edges = graph.edges.filter(
      (edge) =>
        nodeIds.has(edge.from_evidence_id) &&
        nodeIds.has(edge.to_evidence_id) &&
        (graphEdgeMode === 'all' || edge.origin === 'canonical'),
    );
    return {
      ...graph,
      nodes,
      edges,
      node_count: nodes.length,
      edge_count: edges.length,
    };
  }, [graph, graphDepth, graphEdgeMode]);
  const selectedGraphNode =
    visibleGraph?.nodes.find(
      (node) => node.evidence_id === selectedEvidenceId,
    ) ||
    visibleGraph?.nodes[0] ||
    null;
  const selectedGraphCandidate =
    receipt?.candidates.find(
      (candidate) => candidate.evidence_id === selectedGraphNode?.evidence_id,
    ) || null;
  const selectedGraphEdges = (visibleGraph?.edges || []).filter(
    (edge) =>
      edge.from_evidence_id === selectedGraphNode?.evidence_id ||
      edge.to_evidence_id === selectedGraphNode?.evidence_id,
  );
  const evaluationLeader = evaluation?.leaderboard.reduce(
    (leader, row) =>
      row.ndcg_at_10 > leader.ndcg_at_10 ? row : leader,
    evaluation.leaderboard[0],
  );
  const targetIncident =
    receipt?.run.identifier_tokens?.find((token) => token.startsWith('INC-')) ||
    'INC-2047';
  const timelineEvents = useMemo(() => {
    const events = timeline?.events || [];
    const candidateKeys = new Set(
      candidates.map((candidate) => candidate.external_key).filter(Boolean),
    );
    const scoped = events.filter(
      (event) =>
        event.incident_id === targetIncident ||
        event.external_key === targetIncident ||
        candidateKeys.has(event.external_key),
    );
    return (scoped.length ? scoped : events).slice(0, 10);
  }, [timeline, candidates, targetIncident]);
  const homeCitations = (answer?.citations || []).slice(0, 6);
  const homeEvidenceState = homeCitations.length
    ? 'ready'
    : homeReceiptLoading
      ? 'loading'
      : 'empty';
  const homeCandidateById = new Map(
    candidates.map((candidate) => [candidate.evidence_id, candidate]),
  );
  const homeRrfScores = homeCitations
    .map((citation) =>
      numberValue(homeCandidateById.get(citation.evidence_id)?.rrf_score),
    )
    .filter((value): value is number => value !== null);
  const homeTopRrf = homeRrfScores.length
    ? Math.max(...homeRrfScores)
    : null;
  const resultKinds = new Set(
    candidates.map((candidate) => snapshot(candidate).evidence_kind),
  );
  const coverage = {
    cause:
      resultKinds.has('change') && resultKinds.has('lock_evidence')
        ? 'covered'
        : resultKinds.has('incident') || resultKinds.has('lock_evidence')
          ? 'partial'
          : 'missing',
    customer: resultKinds.has('support_case') ? 'covered' : 'missing',
    fix: resultKinds.has('runbook') ? 'covered' : 'missing',
  } as const;
  const missingEvidenceKinds = [
    coverage.cause !== 'covered' ? 'change + lock evidence' : null,
    coverage.customer !== 'covered' ? 'support case' : null,
    coverage.fix !== 'covered' ? 'approved runbook' : null,
  ].filter((value): value is string => Boolean(value));
  const answerCitations =
    answer?.citations.length ? answer.citations : streamCitations;
  const runbookRecovered = answerCitations.some(
    (citation) => citation.external_key === 'RB-017',
  );
  const currentAgentEvent = agentTrace[agentTrace.length - 1] || null;
  const boundedRecoveryObserved = agentTrace.some((event) => {
    const kinds = event.arguments?.kinds;
    return (
      event.tool === 'search_evidence' &&
      Array.isArray(kinds) &&
      kinds.includes('runbook') &&
      !event.arguments?.cluster_id &&
      !event.arguments?.incident_id
    );
  });
  const baselineChunks = health?.current_chunks || 15017;
  const scaleChunks = Math.round(
    baselineChunks * Math.pow(50_000_000 / baselineChunks, scalePosition / 100),
  );
  const scaleIndexGiB = (scaleChunks * (4096 + 288)) / 1073741824;
  const scalePoolGiB = scaleRamGiB * 0.75;
  const scaleFits = scaleIndexGiB <= scalePoolGiB;
  const scaleMissPenalty = scaleFits ? 1 : optimizedReads ? 3.2 : 9;
  const scaleOverfetch =
    1 + (1 / (scaleSelectivity / 100) - 1) * 0.4;
  const scaleVectorMs =
    (0.9 + controls.efSearch * 0.0725) *
    (Math.log2(scaleChunks) / Math.log2(baselineChunks)) *
    scaleMissPenalty *
    scaleOverfetch;
  const scaleBuildSeconds = scaleChunks / 2800;

  return (
    <div className={`verity-shell ${module === 'home' ? 'home-shell' : ''}`}>
      <aside className="side-rail">
        <button
          className="brand"
          type="button"
          onClick={() => setModule('home')}
          aria-label="Open Verity overview"
        >
          <VerityMark />
          <span className="brand-copy">
            <strong>{APP_NAME}</strong>
            <small>incident-evidence workbench</small>
          </span>
        </button>

        <nav className="side-nav journey-side-nav" aria-label="Workbench surfaces">
          {PRIMARY_NAV.map(({ surface, label, Icon, lenses }) => {
            const surfaceActive = activeSurface === surface;
            return (
              <div className="side-nav-group" key={surface}>
                <button
                  type="button"
                  className={surfaceActive ? 'active' : ''}
                  onClick={() => goTo(surface, lenses[0]?.key)}
                  aria-current={surfaceActive ? 'page' : undefined}
                >
                  <Icon size={15} />
                  {label}
                </button>
                {surfaceActive && lenses.length ? (
                  <div className="side-subnav" aria-label={`${label} views`}>
                    {lenses.map((lens) => (
                      <button
                        type="button"
                        key={lens.key}
                        className={activeLens === lens.key ? 'active' : ''}
                        onClick={() => goTo(surface, lens.key)}
                      >
                        <lens.Icon size={13} />
                        {lens.label}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            );
          })}
          <div className="side-nav-divider">Utility</div>
          {UTILITY_NAV.map(({ surface, label, Icon }) => (
            <button
              type="button"
              key={surface}
              className={activeSurface === surface ? 'active' : ''}
              onClick={() => goTo(surface)}
            >
              <Icon size={15} />
              {label}
            </button>
          ))}
        </nav>

        <div className="side-rail-details">
          <section className="side-rail-card">
            <span className="section-label">Incident scope</span>
            <strong>INC-2047 · CHG-1842</strong>
            <code>{health?.cluster_id || '—'}</code>
          </section>
          <section className="side-rail-card">
            <span className="section-label">Active receipt</span>
            <strong>{runId ? compactId(runId) : 'Not started'}</strong>
            <code>
              {health?.current_documents?.toLocaleString() || '—'} documents ·{' '}
              {health?.drift_issues ?? '—'} drift
            </code>
          </section>
        </div>
      </aside>

      <div className="app-column">
        {module === 'home' ? <LiveBanner health={health} /> : null}
        {module !== 'home' ? (
        <header className="chrome">
          <div className="chrome-inner">
          <button
              className="mobile-brand"
              type="button"
              onClick={() => setModule('home')}
              aria-label="Open Verity overview"
            >
              <VerityMark />
              <span>{APP_NAME}</span>
            </button>

            <form className="omnibox" onSubmit={runSearch}>
              <Search size={15} aria-hidden="true" />
              <input
                value={controls.query}
                onChange={(event) => setControl('query', event.target.value)}
                aria-label="Evidence query"
              />
              <button
                type="submit"
                className="icon-command"
                disabled={busy !== null || !controls.query.trim()}
                title="Run retrieval"
                aria-label="Run retrieval"
              >
                {busy === 'search' ? (
                  <LoaderCircle className="spin" size={16} />
                ) : (
                  <ArrowRight size={16} />
                )}
              </button>
            </form>

            <div className="chrome-actions">
              <button
                type="button"
                className="top-command"
                onClick={() => runSearch()}
                disabled={busy !== null || !controls.query.trim()}
              >
                {busy === 'search' ? (
                  <LoaderCircle className="spin" size={15} />
                ) : (
                  <Search size={15} />
                )}
                Run search
              </button>
              <button
                type="button"
                className="top-command primary agent-command"
                onClick={askAgent}
                disabled={busy !== null || !controls.query.trim()}
              >
                {busy === 'answer' ? (
                  <LoaderCircle className="spin" size={15} />
                ) : (
                  <Sparkles size={15} />
                )}
                Answer with evidence
              </button>
            </div>
          </div>
        </header>
        ) : null}

        {error ? (
          <div className="error-banner" role="alert">
            <AlertTriangle size={16} />
            <span>{error}</span>
            <button
              type="button"
              onClick={() => setError(null)}
              title="Dismiss"
              aria-label="Dismiss"
            >
              <X size={15} />
            </button>
          </div>
        ) : null}

        <main className={`workbench ${module === 'home' ? 'home-workbench' : ''}`}>
        {module === 'home' ? (
          <section className="verity-home">
            <header className="home-hero">
              <div className="home-copy">
                <span className="home-eyebrow">
                  Connected incident evidence
                </span>
                <h1>
                  <span>{APP_NAME}</span>
                  {' '}follows the <em className="home-why">why.</em>
                </h1>
                <p>
                  Trace an application incident on Aurora PostgreSQL across
                  lock evidence, change history, customer impact, and approved
                  remediation. Every conclusion resolves to replayable proof.
                </p>
                <div className="home-live-stats" aria-label="Live system status">
                  <div>
                    <span>search index</span>
                    <strong className={health?.status === 'ready' ? 'ready' : ''}>
                      {health?.status || 'checking'}
                    </strong>
                  </div>
                  <div>
                    <span>corpus</span>
                    <strong>
                      {health?.current_documents?.toLocaleString() || '—'} docs
                    </strong>
                  </div>
                  <div>
                    <span>latest proof</span>
                    <strong>{compactId(runId)}</strong>
                  </div>
                </div>
              </div>

              <div
                className={`home-thread-scene ${homeEvidenceState}`}
                aria-label={
                  homeEvidenceState === 'ready'
                    ? 'Latest cited evidence'
                    : homeEvidenceState === 'loading'
                      ? 'Loading the latest cited evidence'
                      : 'No cited receipt is available'
                }
              >
                <svg
                  className="home-threads"
                  viewBox="0 0 620 520"
                  role="img"
                  aria-label={
                    homeEvidenceState === 'ready'
                      ? `${homeCitations.length} citations connected to the latest answer`
                      : 'Evidence-thread frame awaiting a cited receipt'
                  }
                >
                  <circle cx="310" cy="260" r="168" />
                  <circle cx="310" cy="260" r="220" />
                  {homeCitations.map((citation, index) => (
                    <path
                      key={citation.evidence_id}
                      className="home-thread"
                      d={HOME_THREAD_PATHS[index]}
                    />
                  ))}
                </svg>

                <div className="home-answer-node">
                  <VerityMark className="home-answer-mark" />
                  <strong className="home-answer-title">
                    {homeEvidenceState === 'ready'
                      ? 'Cited answer'
                      : 'Evidence thread'}
                  </strong>
                  <small className="home-answer-model">
                    {answer?.synthesis_mode ||
                      (homeEvidenceState === 'loading'
                        ? 'loading receipt'
                        : 'awaiting run')}
                  </small>
                  <div className="home-answer-metrics">
                    <span>
                      <b>{answer?.citations.length || '—'}</b>
                      <small>cited</small>
                    </span>
                    <span>
                      <b>{score(homeTopRrf, 4)}</b>
                      <small>top RRF</small>
                    </span>
                  </div>
                  <i>
                    {homeEvidenceState === 'ready'
                      ? 'rank signal · not confidence'
                      : 'no active receipt'}
                  </i>
                </div>

                <div className="home-evidence-nodes">
                  {homeCitations.map((citation) => {
                    const candidate = homeCandidateById.get(
                      citation.evidence_id,
                    );
                    const candidateRrf = numberValue(candidate?.rrf_score);
                    const item = candidate ? snapshot(candidate) : null;
                    return (
                      <button
                        type="button"
                        className="home-evidence-node"
                        key={citation.evidence_id || citation.external_key}
                        onClick={() => {
                          if (citation.evidence_id) {
                            setSelectedEvidenceId(citation.evidence_id);
                          }
                          goTo('agent', 'answer');
                        }}
                      >
                        <span className="home-node-header">
                          <small>Cite {citation.citation_number}</small>
                          <span
                            className={`home-node-score ${
                              candidateRrf === null ? 'citation-only' : ''
                            }`}
                            title={
                              candidateRrf === null
                                ? 'Cited evidence without a score in the active receipt'
                                : 'Reciprocal rank fusion score'
                            }
                            aria-label={
                              candidateRrf === null
                                ? 'Cited evidence'
                                : `RRF score ${score(candidateRrf, 4)}`
                            }
                          >
                            {candidateRrf === null
                              ? 'cited'
                              : score(candidateRrf, 4)}
                          </span>
                        </span>
                        <span className="home-node-icon">
                          <KindIcon kind={item?.evidence_kind} size={16} />
                        </span>
                        <span>
                          <strong>{citation.external_key}</strong>
                          <b>{citation.title}</b>
                        </span>
                      </button>
                    );
                  })}
                  {homeEvidenceState !== 'ready' ? (
                    <div className={`home-evidence-state ${homeEvidenceState}`}>
                      {homeEvidenceState === 'loading' ? (
                        <LoaderCircle className="spin" size={18} />
                      ) : (
                        <FileSearch size={17} />
                      )}
                      {homeEvidenceState === 'loading'
                        ? 'Loading latest cited receipt'
                        : 'No cited receipt yet'}
                    </div>
                  ) : null}
                </div>
              </div>

              <form
                className="home-query"
                onSubmit={(event) => {
                  event.preventDefault();
                  void beginInvestigation();
                }}
              >
                <Search size={20} aria-hidden="true" />
                <span className="home-query-field">
                  <input
                    ref={homeQueryInput}
                    value={homeQueryText}
                    readOnly={homeTyping}
                    title={homeQueryText}
                    onFocus={interruptHomeTypewriter}
                    onChange={(event) => {
                      setHomeQueryText(event.target.value);
                      setControl('query', event.target.value);
                    }}
                    aria-label="Incident question"
                  />
                </span>
                <button
                  type="submit"
                  className="agent-command"
                  disabled={
                    busy !== null || homeTyping || !homeQueryText.trim()
                  }
                >
                  {busy === 'search' || busy === 'run' ? (
                    <LoaderCircle className="spin" size={17} />
                  ) : (
                    <Sparkles size={17} />
                  )}
                  Investigate
                  <ArrowRight size={16} />
                </button>
              </form>
            </header>

            <section className="home-workspaces">
              <header>
                <div>
                  <span className="section-label">Investigation workspaces</span>
                  <h2>Follow one evidence thread from retrieval to proof.</h2>
                </div>
                <span className="home-workspace-status">
                  <ShieldCheck size={14} />
                  {health?.drift_issues ?? '—'} search-index drift
                </span>
              </header>
              <div className="home-workspace-grid">
                <button
                  type="button"
                  onClick={() => goTo('agent', 'answer')}
                >
                  <FileCheck2 size={20} />
                  <span>
                    <strong>Casefile</strong>
                    <small>{answer?.citations.length || 0} cited sources</small>
                  </span>
                  <ArrowRight size={15} />
                </button>
                <button
                  type="button"
                  onClick={() => goTo('agent', 'graph')}
                >
                  <Network size={20} />
                  <span>
                    <strong>Evidence canvas</strong>
                    <small>{graph?.node_count || 0} visible nodes</small>
                  </span>
                  <ArrowRight size={15} />
                </button>
                <button
                  type="button"
                  onClick={() => goTo('retrieval', 'plan')}
                >
                  <Code2 size={20} />
                  <span>
                    <strong>Query microscope</strong>
                    <small>{queryPlan ? `${queryPlan.scans.length} plan scans` : 'live EXPLAIN'}</small>
                  </span>
                  <ArrowRight size={15} />
                </button>
                <button
                  type="button"
                  onClick={() => goTo('proof', 'replay')}
                >
                  <Play size={20} />
                  <span>
                    <strong>Replay theater</strong>
                    <small>{receipt?.stages.length || 0} persisted stages</small>
                  </span>
                  <ArrowRight size={15} />
                </button>
                <button
                  type="button"
                  onClick={() => goTo('evaluation')}
                >
                  <Gauge size={20} />
                  <span>
                    <strong>Benchmark matrix</strong>
                    <small>
                      {evaluation
                        ? `${evaluation.query_count} judged queries`
                        : 'judged retrieval set'}
                    </small>
                  </span>
                  <ArrowRight size={15} />
                </button>
              </div>
            </section>

            <section className="home-retrieval-path">
              <div>
                <span className="section-label">Aurora PostgreSQL retrieval path</span>
                <h2>Different signals. One inspectable rank.</h2>
              </div>
              <div className="home-path-flow">
                <span>
                  <strong>Exact + full text</strong>
                  <small>tsvector · GIN</small>
                </span>
                <b>+</b>
                <span>
                  <strong>Semantic</strong>
                  <small>pgvector · HNSW</small>
                </span>
                <b>+</b>
                <span>
                  <strong>Fuzzy</strong>
                  <small>pg_trgm · GIN</small>
                </span>
                <ArrowRight size={18} />
                <span className="active">
                  <strong>Weighted RRF</strong>
                  <small>
                    {controls.textWeight}:{controls.vectorWeight}:
                    {controls.fuzzyWeight} · k={controls.rrfK}
                  </small>
                </span>
                <ArrowRight size={18} />
                <span>
                  <strong>Cited receipt</strong>
                  <small>{runId ? compactId(runId) : 'awaiting run'}</small>
                </span>
              </div>
            </section>
          </section>
        ) : null}
        {module === 'results' ? (
          <section className="results-journey">
            <header className="results-journey-head">
              <div>
                <span className="module-kicker">Step 1 · Gather evidence</span>
                <h1>What did one retrieval pass <em>actually find?</em></h1>
                <p>{controls.query}</p>
              </div>
              <span className={`status-pill ${busy ? 'pending' : 'ready'}`}>
                {busy ? <LoaderCircle className="spin" size={13} /> : <Check size={13} />}
                {busy
                  ? 'retrieving from Aurora'
                  : `${resultRevealCount}/${candidates.length} results streamed`}
              </span>
            </header>

            <div className="results-journey-layout">
              <div className="thread-results">
                <div className="results-runline">
                  <strong>{candidates.length} persisted candidates</strong>
                  <span>
                    {receipt?.run.retrieval_mode || controls.mode} ·{' '}
                    {receipt?.run.latency_ms?.toLocaleString() || '—'} ms ·{' '}
                    {compactId(runId)}
                  </span>
                </div>
                {candidates.slice(0, resultRevealCount).map((candidate, index) => {
                  const item = snapshot(candidate);
                  return (
                    <button
                      className="thread-result-card"
                      type="button"
                      key={candidate.evidence_id}
                      onClick={() => setSelectedEvidenceId(candidate.evidence_id || null)}
                    >
                      <span className="thread-result-node" />
                      <span className={`kind-glyph kind-${item.evidence_kind || 'unknown'}`}>
                        <KindIcon kind={item.evidence_kind} />
                      </span>
                      <span className="thread-result-copy">
                        <small>
                          {item.evidence_kind
                            ? KIND_LABELS[item.evidence_kind]
                            : 'Evidence'}{' '}
                          · rank {index + 1}
                        </small>
                        <strong>{item.external_key} · {item.title}</strong>
                        <p>{item.snippet}</p>
                        <span className="thread-result-signals">
                          <b>FTS {position(candidate, 'text') ? `#${position(candidate, 'text')}` : '—'}</b>
                          <b>VECTOR {position(candidate, 'vector') ? `#${position(candidate, 'vector')}` : '—'}</b>
                          <b>FUZZY {position(candidate, 'fuzzy') ? `#${position(candidate, 'fuzzy')}` : '—'}</b>
                          <b>RRF {score(candidate.rrf_score, 4)}</b>
                        </span>
                      </span>
                      <span className="thread-result-score">
                        {score(candidate.rrf_score, 4)}
                      </span>
                    </button>
                  );
                })}
                {busy || resultRevealCount < candidates.length ? (
                  <div className="thread-result-loading">
                    <LoaderCircle className="spin" size={15} />
                    streaming persisted candidates
                  </div>
                ) : null}
              </div>

              <aside className="results-coverage-rail">
                <section>
                  <span className="section-label">Question coverage</span>
                  {(
                    [
                      ['cause', 'Why writes blocked', coverage.cause],
                      ['customer', 'Visible customer impact', coverage.customer],
                      ['fix', 'Safe remediation', coverage.fix],
                    ] as const
                  ).map(([key, label, state]) => (
                    <div className={`coverage-row ${state}`} key={key}>
                      <span>{state === 'covered' ? <Check size={13} /> : <CircleDot size={13} />}</span>
                      <strong>{label}</strong>
                      <small>{state}</small>
                    </div>
                  ))}
                </section>
                <section className="participant-checkpoint">
                  <span className="section-label">Participant exercise 1</span>
                  <h2>
                    {coverage.fix === 'missing'
                      ? 'The safe fix is still unsupported.'
                      : 'Every part of the question has evidence.'}
                  </h2>
                  <div className="checkpoint-explanation">
                    <strong>What is missing</strong>
                    <p>
                      {missingEvidenceKinds.length
                        ? `${missingEvidenceKinds.join(', ')}. Until it is recovered, Verity must withhold that part of the answer.`
                        : 'No required evidence kind is missing from the current result set.'}
                    </p>
                    <strong>Why it is missing</strong>
                    <p>
                      The first pass is scoped to <code>{controls.clusterId}</code>.
                      {' '}<code>RB-017</code> is reusable guidance and has no{' '}
                      <code>cluster_id</code>, so the filter correctly excludes it
                      before any retrieval arm enters fusion.
                    </p>
                    <strong>Your step</strong>
                    <p>
                      Decompose the question. Keep the production-cluster filter
                      for incident evidence, then relax only the runbook subquery
                      to <code>cluster_id = NULL</code>. Keep the workshop
                      principal and ACL checks unchanged.
                    </p>
                  </div>
                  <dl>
                    <div>
                      <dt>Current scope</dt>
                      <dd>{controls.clusterId}</dd>
                    </div>
                    <div>
                      <dt>Missing evidence</dt>
                      <dd>{missingEvidenceKinds.join(' · ') || 'none'}</dd>
                    </div>
                    <div>
                      <dt>Success</dt>
                      <dd>RB-017 · 3/3 covered · citations valid</dd>
                    </div>
                  </dl>
                  <button
                    type="button"
                    className="agent-command"
                    onClick={openAnswerExercise}
                    disabled={busy !== null}
                  >
                    <Sparkles size={15} />
                    Open the bounded-recovery exercise
                    <ArrowRight size={15} />
                  </button>
                </section>
              </aside>
            </div>
          </section>
        ) : null}
        {module === 'retrieve' ? (
          <section className="module-screen">
            <header className="module-heading">
              <div>
                <span className="module-kicker">
                  Module 1 ·{' '}
                  {diagnoseTab === 'retrieval'
                    ? 'Retrieval lab'
                    : diagnoseTab === 'fusion'
                      ? 'RRF anatomy'
                      : diagnoseTab === 'plan'
                        ? 'Query-plan X-Ray'
                        : 'Scale & capacity'}
                </span>
                <h1>
                  {diagnoseTab === 'retrieval' ? (
                    <>
                      One query, <em>every arm.</em>
                    </>
                  ) : diagnoseTab === 'fusion' ? (
                    <>
                      Rank arithmetic, <em>not score soup.</em>
                    </>
                  ) : diagnoseTab === 'plan' ? (
                    <>
                      Where the <em>milliseconds</em> go.
                    </>
                  ) : (
                    <>
                      The lab fits in memory. <em>Production might not.</em>
                    </>
                  )}
                </h1>
                <p className="module-deck">
                  {diagnoseTab === 'retrieval'
                    ? 'Exact, lexical, semantic, and fuzzy candidates over the same live Aurora corpus.'
                    : diagnoseTab === 'fusion'
                      ? 'Only integer positions enter weighted RRF; raw arm values remain diagnostics.'
                      : diagnoseTab === 'plan'
                        ? 'Inspect the planner choice for each arm under the active filters and principal.'
                        : 'Explore a labeled capacity model, then inspect the real search-index build history.'}
                </p>
              </div>
              <div className="heading-status">
                <span
                  className={`status-pill ${
                    health?.status === 'ready' ? 'ready' : 'pending'
                  }`}
                >
                  <ShieldCheck size={13} />
                  search index {health?.status || 'checking'}
                </span>
                <span className="status-pill">
                  {health?.current_documents?.toLocaleString() || '—'} docs
                </span>
                <span className="status-pill">
                  {health?.drift_issues ?? '—'} drift
                </span>
              </div>
            </header>

            {diagnoseTab === 'retrieval' ? (
              <>
                <div className="retrieval-toolbar">
                  <div className="preset-list" aria-label="Query presets">
                    {PRESETS.map((preset) => (
                      <button
                        key={preset.label}
                        type="button"
                        className={
                          controls.query === preset.query ? 'active' : ''
                        }
                        onClick={() =>
                          setControls((current) => ({
                            ...current,
                            query: preset.query,
                            mode: preset.mode,
                            kind: preset.kind,
                            clusterId: preset.clusterId,
                          }))
                        }
                      >
                        {preset.label}
                      </button>
                    ))}
                  </div>
                  <div className="segmented">
                    <button
                      type="button"
                      className={!controls.supportLead ? 'active' : ''}
                      onClick={() => setControl('supportLead', false)}
                    >
                      workshop
                    </button>
                    <button
                      type="button"
                      className={controls.supportLead ? 'active' : ''}
                      onClick={() => setControl('supportLead', true)}
                    >
                      support-lead
                    </button>
                  </div>
                  <div className="segmented">
                    <button
                      type="button"
                      className={!controls.rerank ? 'active' : ''}
                      onClick={() => setControl('rerank', false)}
                    >
                      Aurora RRF
                    </button>
                    <button
                      type="button"
                      className={controls.rerank ? 'active' : ''}
                      onClick={() => setControl('rerank', true)}
                    >
                      + rerank
                    </button>
                  </div>
                  <button
                    type="button"
                    className="run-button"
                    onClick={() => runSearch()}
                    disabled={busy !== null || !controls.query.trim()}
                  >
                    {busy === 'search' || busy === 'run' ? (
                      <LoaderCircle className="spin" size={15} />
                    ) : (
                      <Play size={14} />
                    )}
                    Run
                  </button>
                </div>

                <div className="lab-note">
                  <strong>Read the columns independently.</strong>
                  <span>
                    ACL and filters execute inside every arm before fusion.
                    One strongest passage survives per evidence item; an absent
                    arm contributes zero.
                  </span>
                </div>

                <div className="retrieval-arms">
                  <RetrievalArm
                    title="Exact + full-text"
                    subtitle="B-tree key · GIN tsvector · raw ts_rank"
                    candidates={textCandidates}
                    selectedEvidenceId={selectedEvidenceId}
                    diagnostic={(candidate) =>
                      candidate.explanation?.exact_identifier
                        ? 'exact'
                        : `#${position(candidate, 'text')}`
                    }
                    onSelect={selectCandidate}
                  />
                  <RetrievalArm
                    title="Semantic"
                    subtitle={`pgvector HNSW · ${embeddingModel} · ef ${controls.efSearch}`}
                    candidates={vectorCandidates}
                    selectedEvidenceId={selectedEvidenceId}
                    diagnostic={(candidate) =>
                      `#${position(candidate, 'vector')}`
                    }
                    onSelect={selectCandidate}
                  />
                  <RetrievalArm
                    title="Fuzzy"
                    subtitle={`pg_trgm keys/titles · threshold ${controls.fuzzyThreshold}`}
                    candidates={fuzzyCandidates}
                    selectedEvidenceId={selectedEvidenceId}
                    diagnostic={(candidate) =>
                      `#${position(candidate, 'fuzzy')}`
                    }
                    onSelect={selectCandidate}
                  />
                  <RetrievalArm
                    title="Final ranking"
                    subtitle={`exact tier above RRF · weights ${controls.textWeight}:${controls.vectorWeight}:${controls.fuzzyWeight} · k=${controls.rrfK}`}
                    candidates={candidates}
                    selectedEvidenceId={selectedEvidenceId}
                    diagnostic={(candidate) =>
                      score(candidate.rrf_score ?? candidate.final_score, 5)
                    }
                    onSelect={selectCandidate}
                    fused
                  />
                </div>

                <div className="retrieval-footnotes">
                  <span>filters + ACL before fusion</span>
                  <span>raw values are diagnostics</span>
                  <span>rank positions enter RRF</span>
                  <span>exact identifiers rank above every fused row</span>
                  <span>{runId ? `run ${compactId(runId)}` : 'run not started'}</span>
                </div>

                <div className="retrieve-lower retrieval-detail-grid">
                  <aside className="candidate-receipt">
                    <header>
                      <div>
                        <span className="section-label">
                          Candidate provenance
                        </span>
                        <strong>
                          {activeEvidence?.external_key || 'No selection'}
                        </strong>
                      </div>
                      {activeEvidence?.evidence_kind ? (
                        <span
                          className={`kind-glyph kind-${activeEvidence.evidence_kind}`}
                        >
                          <KindIcon kind={activeEvidence.evidence_kind} />
                        </span>
                      ) : null}
                    </header>
                    {activeEvidence ? (
                      <>
                        <h2>{activeEvidence.title}</h2>
                        <p className="receipt-snippet">
                          {activeEvidence.snippet ||
                            evidenceDetail?.chunks[0]?.chunk_text ||
                            evidenceDetail?.evidence.body ||
                            'No visible chunk text.'}
                        </p>
                        <div className="signal-row">
                          <span>
                            FTS
                            <b>
                              {selectedCandidate
                                ? position(selectedCandidate, 'text') || '—'
                                : '—'}
                            </b>
                          </span>
                          <span>
                            VEC
                            <b>
                              {selectedCandidate
                                ? position(selectedCandidate, 'vector') || '—'
                                : '—'}
                            </b>
                          </span>
                          <span>
                            TRGM
                            <b>
                              {selectedCandidate
                                ? position(selectedCandidate, 'fuzzy') || '—'
                                : '—'}
                            </b>
                          </span>
                          <span>
                            RRF
                            <b>
                              {score(
                                selectedCandidate?.rrf_score ??
                                  selectedCandidate?.final_score,
                                5,
                              )}
                            </b>
                          </span>
                        </div>
                        <dl className="receipt-metadata">
                          <div>
                            <dt>Source URI</dt>
                            <dd>{activeEvidence.source_uri || '—'}</dd>
                          </div>
                          <div>
                            <dt>Revision</dt>
                            <dd>{activeEvidence.source_revision || '—'}</dd>
                          </div>
                          <div>
                            <dt>Document</dt>
                            <dd>
                              {selectedCandidate?.document_version_id || '—'}
                            </dd>
                          </div>
                          <div>
                            <dt>Chunk</dt>
                            <dd>
                              {selectedCandidate?.chunk_version_id ||
                                evidenceDetail?.chunks[0]?.chunk_version_id ||
                                '—'}
                            </dd>
                          </div>
                          <div>
                            <dt>Embedding</dt>
                            <dd>{embeddingModel} · 1,024 dimensions</dd>
                          </div>
                          <div>
                            <dt>ACL</dt>
                            <dd>
                              {controls.supportLead
                                ? 'workshop + support-lead'
                                : 'workshop'}
                            </dd>
                          </div>
                        </dl>
                      </>
                    ) : (
                      <Empty
                        icon={<Gauge size={18} />}
                        title="Run a retrieval"
                      />
                    )}
                  </aside>

                  <section className="provenance-note">
                    <span className="section-label">Why this is inspectable</span>
                    <h2>Signals remain separate through the receipt.</h2>
                    <p>
                      `proof.retrieval_candidates` stores arm positions, raw
                      diagnostics, Aurora RRF, and the optional model rerank
                      score independently. No score is presented as a
                      probability.
                    </p>
                    <div className="provenance-facts">
                      <span>
                        <b>{controls.candidatePool}</b> candidates per arm
                      </span>
                      <span>
                        <b>{controls.limit}</b> final results
                      </span>
                      <span>
                        <b>{controls.efSearch}</b> HNSW ef_search
                      </span>
                      <span>
                        <b>{controls.fuzzyThreshold}</b> trigram threshold
                      </span>
                    </div>
                  </section>
                </div>
              </>
            ) : null}

            {diagnoseTab === 'fusion' ? (
              <>
                <div className="fusion-workspace">
                  <div className="fusion-workspace-controls">
                    <FusionControlPanel
                      controls={controls}
                      advancedOpen={advancedOpen}
                      onToggleAdvanced={() =>
                        setAdvancedOpen((open) => !open)
                      }
                      onChange={setControl}
                      onRun={() => runSearch()}
                      busy={busy !== null}
                    />
                    <div className="fusion-stat-row">
                      <span>
                        intended weight
                        <b>
                          text {controls.textWeight} · vector{' '}
                          {controls.vectorWeight} · fuzzy{' '}
                          {controls.fuzzyWeight}
                        </b>
                      </span>
                      <span>
                        active arms
                        <b>
                          {textCandidates.length ? 'text' : ''}
                          {vectorCandidates.length ? ' · vector' : ''}
                          {fuzzyCandidates.length ? ' · fuzzy' : ''}
                        </b>
                      </span>
                      <span>
                        current ordering
                        <b>{controls.rerank ? 'model rerank' : 'Aurora RRF'}</b>
                      </span>
                      <span>
                        receipt
                        <b>{runId ? compactId(runId) : 'not started'}</b>
                      </span>
                    </div>
                  </div>
                  <section className="sql-panel">
                    <header>
                      <span>Exact tier, then weighted reciprocal rank fusion</span>
                      <span>raw values excluded</span>
                    </header>
                    <pre>
                      <code>{`rrf_score =
  ${controls.textWeight} / (${controls.rrfK} + text_position)
+ ${controls.vectorWeight} / (${controls.rrfK} + vector_position)
+ ${controls.fuzzyWeight} / (${controls.rrfK} + trigram_position)

-- a missing arm contributes zero
-- match_tier 1 is exact identifier resolution: a B-tree probe,
-- not a score, so no weight above can demote it
ORDER BY
  match_tier,
  exact_identifier_position,
  rrf_score DESC
LIMIT ${controls.limit};`}</code>
                    </pre>
                  </section>
                </div>

                {candidates.length ? (
                  <section className="fusion-candidate-panel">
                    <header>
                      <div>
                        <span className="section-label">Candidate pool</span>
                        <h2>Every contribution on one shared rank scale</h2>
                      </div>
                      <div className="contribution-legend">
                        <span><i className="legend-text" /> full-text</span>
                        <span><i className="legend-vector" /> semantic</span>
                        <span><i className="legend-fuzzy" /> fuzzy</span>
                      </div>
                    </header>
                    <FusionAnatomyTable
                      candidates={candidates}
                      controls={controls}
                      onSelect={selectCandidate}
                    />
                  </section>
                ) : (
                  <Empty
                    icon={<GitMerge size={20} />}
                    title="Run retrieval to inspect fusion"
                  />
                )}

                <div className="fusion-explain-grid">
                  <section>
                    <span className="section-label">Why score sums drift</span>
                    <p>
                      `ts_rank`, vector similarity, and trigram similarity have
                      unrelated ranges and distributions. A numeric weight
                      cannot make those raw scales comparable. RRF uses only
                      each arm&apos;s integer order.
                    </p>
                  </section>
                  <section>
                    <span className="section-label">
                      Why rank 1 can hold a lower RRF
                    </span>
                    <p>
                      A query that names an identifier resolves it
                      deterministically, and those rows rank above the fused
                      tier regardless of score. RRF then orders within each
                      tier, so an exact hit can sit above a fused row that
                      scored higher.
                    </p>
                  </section>
                  <section>
                    <span className="section-label">
                      What the receipt preserves
                    </span>
                    <p>
                      Rank, raw diagnostic, weighted contribution, fused score,
                      and rerank score remain distinct. Rerank may reorder a
                      pool, but never overwrites the Aurora ordering.
                    </p>
                  </section>
                </div>
              </>
            ) : null}

            {diagnoseTab === 'plan' ? (
              <div className="query-microscope">
                <aside className="microscope-controls">
                  <header>
                    <span className="section-label">Query & controls</span>
                    <span className="status-pill">
                      {controls.supportLead ? 'support-lead' : 'workshop'}
                    </span>
                  </header>
                  <p>{controls.query}</p>
                  <div className="segmented">
                    {(['semantic', 'lexical', 'fuzzy'] as const).map((arm) => (
                      <button
                        key={arm}
                        type="button"
                        className={planArm === arm ? 'active' : ''}
                        onClick={() => void loadQueryPlan(arm)}
                      >
                        {arm}
                      </button>
                    ))}
                  </div>
                  <dl>
                    <div>
                      <dt>cluster</dt>
                      <dd>{controls.clusterId || 'all'}</dd>
                    </div>
                    <div>
                      <dt>evidence kind</dt>
                      <dd>
                        {controls.kind === 'all'
                          ? 'all'
                          : KIND_LABELS[controls.kind]}
                      </dd>
                    </div>
                    <div>
                      <dt>candidate pool</dt>
                      <dd>{controls.candidatePool}</dd>
                    </div>
                    <div>
                      <dt>hnsw.ef_search</dt>
                      <dd>{controls.efSearch}</dd>
                    </div>
                  </dl>
                  <button
                    type="button"
                    className="run-button"
                    onClick={() => void loadQueryPlan(planArm)}
                    disabled={busy !== null}
                  >
                    {busy === 'plan' ? (
                      <LoaderCircle className="spin" size={14} />
                    ) : (
                      <RefreshCw size={14} />
                    )}
                    Explain live
                  </button>
                </aside>

                <section className="microscope-trace">
                  <header>
                    <div>
                      <span className="section-label">
                        Planner trace · {planArm}
                      </span>
                      <h2>Observed scan path</h2>
                    </div>
                    <span className="status-pill ready">live Aurora</span>
                  </header>
                  <div className="microscope-runtime">
                    <span>
                      Planning
                      <strong>
                        {score(queryPlan?.plan['Planning Time'], 3)} ms
                      </strong>
                    </span>
                    <span>
                      Execution
                      <strong>
                        {score(queryPlan?.plan['Execution Time'], 3)} ms
                      </strong>
                    </span>
                    <span>
                      Scan nodes
                      <strong>{queryPlan?.scans.length || 0}</strong>
                    </span>
                  </div>
                  <div className="microscope-nodes">
                    {(queryPlan?.scans || []).map((scan, index) => (
                      <div key={`${scan.node_type}-${scan.index}-${index}`}>
                        <span>{index + 1}</span>
                        <div>
                          <strong>{scan.node_type}</strong>
                          <code>
                            {scan.index || scan.relation || 'working set'}
                          </code>
                        </div>
                        <small>
                          {scan.actual_rows} rows · {scan.loops} loop
                          {scan.loops === 1 ? '' : 's'}
                        </small>
                      </div>
                    ))}
                    {!queryPlan?.scans.length ? (
                      <Empty
                        icon={<Activity size={18} />}
                        title={
                          busy === 'plan' ? 'Explaining' : 'No plan loaded'
                        }
                      />
                    ) : null}
                  </div>
                  <footer>
                    <span>Filtered arm</span>
                    <ArrowRight size={16} />
                    <span>candidate pool</span>
                    <ArrowRight size={16} />
                    <span>
                      weighted RRF {controls.textWeight}:
                      {controls.vectorWeight}:{controls.fuzzyWeight} · k=
                      {controls.rrfK}
                    </span>
                    <ArrowRight size={16} />
                    <span>persist receipt</span>
                  </footer>
                </section>

                <aside className="microscope-inspector">
                  <span className="section-label">Why this plan?</span>
                  <p>{queryPlan?.note || 'Run EXPLAIN to inspect this arm.'}</p>
                  {queryPlan?._verify_sql ? (
                    <VerifyAffordance descriptor={queryPlan._verify_sql} />
                  ) : null}
                  <div className="microscope-facts">
                    <div>
                      <span>Arm</span>
                      <strong>{planArm}</strong>
                    </div>
                    <div>
                      <span>Filter boundary</span>
                      <strong>before ranking</strong>
                    </div>
                    <div>
                      <span>Iterative scan</span>
                      <strong>relaxed_order</strong>
                    </div>
                  </div>
                  <section className="microscope-sql">
                    <header>
                      <span>Runtime SQL</span>
                      <small>transaction local</small>
                    </header>
                    <pre>
                      <code>{`SET LOCAL hnsw.ef_search = ${controls.efSearch};
SET LOCAL hnsw.iterative_scan = relaxed_order;

SELECT *
FROM retrieval.${planArm}_search(
  query_text => $1,
  candidate_limit => ${controls.candidatePool},
  cluster_id => ${controls.clusterId ? `'${controls.clusterId}'` : 'NULL'}
);

-- Planner choices vary with corpus,
-- selectivity, statistics, and cache state.`}</code>
                    </pre>
                  </section>
                </aside>
              </div>
            ) : null}

            {diagnoseTab === 'scale' ? (
              <>
                <section className="scale-controls">
                  <label>
                    <span>Corpus · chunks</span>
                    <input
                      type="range"
                      min={0}
                      max={100}
                      value={scalePosition}
                      onChange={(event) =>
                        setScalePosition(Number(event.target.value))
                      }
                    />
                    <output>
                      {scaleChunks.toLocaleString()}
                      <small>
                        {scalePosition === 0 ? ' · live lab baseline' : ' · modeled'}
                      </small>
                    </output>
                  </label>
                  <label>
                    <span>Rows passing ACL + filters</span>
                    <input
                      type="range"
                      min={2}
                      max={100}
                      value={scaleSelectivity}
                      onChange={(event) =>
                        setScaleSelectivity(Number(event.target.value))
                      }
                    />
                    <output>{scaleSelectivity}%</output>
                  </label>
                  <label>
                    <span>ef_search</span>
                    <input
                      type="range"
                      min={10}
                      max={200}
                      step={5}
                      value={controls.efSearch}
                      onChange={(event) =>
                        setControl('efSearch', Number(event.target.value))
                      }
                    />
                    <output>{controls.efSearch}</output>
                  </label>
                  <div className="scale-switches">
                    <span>Instance memory</span>
                    <div className="segmented">
                      {[32, 128, 512].map((ram) => (
                        <button
                          key={ram}
                          type="button"
                          className={scaleRamGiB === ram ? 'active' : ''}
                          onClick={() => setScaleRamGiB(ram)}
                        >
                          {ram} GiB
                        </button>
                      ))}
                    </div>
                    <span>Optimized Reads</span>
                    <div className="segmented">
                      <button
                        type="button"
                        className={!optimizedReads ? 'active' : ''}
                        onClick={() => setOptimizedReads(false)}
                      >
                        off
                      </button>
                      <button
                        type="button"
                        className={optimizedReads ? 'active' : ''}
                        onClick={() => setOptimizedReads(true)}
                      >
                        on
                      </button>
                    </div>
                  </div>
                </section>

                <div className="scale-stats">
                  <div>
                    <span>Modeled HNSW</span>
                    <strong>{formatGiB(scaleIndexGiB)}</strong>
                    <small>1,024-d float32 + m=16 links</small>
                  </div>
                  <div>
                    <span>Build time</span>
                    <strong>{formatDuration(scaleBuildSeconds)}</strong>
                    <small>CONCURRENTLY ≈ {formatDuration(scaleBuildSeconds * 2)}</small>
                  </div>
                  <div className={scaleFits ? 'ok' : 'warn'}>
                    <span>{scaleFits ? 'Fits buffer pool' : 'Exceeds pool'}</span>
                    <strong>{scaleFits ? 'resident' : `×${scaleMissPenalty.toFixed(1)}`}</strong>
                    <small>{optimizedReads && !scaleFits ? 'NVMe tier model' : 'storage penalty model'}</small>
                  </div>
                  <div className={scaleSelectivity < 10 ? 'warn' : ''}>
                    <span>Overfetch</span>
                    <strong>×{scaleOverfetch.toFixed(1)}</strong>
                    <small>iterative_scan = relaxed_order</small>
                  </div>
                  <div className={scaleVectorMs > 50 ? 'warn' : ''}>
                    <span>Vector arm p50</span>
                    <strong>{scaleVectorMs.toFixed(1)} ms</strong>
                    <small>modeled · excludes lexical + fuzzy</small>
                  </div>
                </div>

                <div className="scale-detail-grid">
                  <section className="capacity-panel">
                    <header>
                      <span className="section-label">
                        Working set vs buffer pool
                      </span>
                      <span className={`status-pill ${scaleFits ? 'ready' : ''}`}>
                        {scaleFits
                          ? 'resident'
                          : optimizedReads
                            ? 'NVMe tier'
                            : 'storage reads'}
                      </span>
                    </header>
                    <div className="capacity-bar">
                      <i
                        style={{
                          width: `${Math.min(
                            (scaleIndexGiB / Math.max(scalePoolGiB, scaleIndexGiB)) *
                              100,
                            100,
                          )}%`,
                        }}
                      />
                    </div>
                    <div className="capacity-labels">
                      <span>HNSW {formatGiB(scaleIndexGiB)}</span>
                      <span>pool ≈ {formatGiB(scalePoolGiB)}</span>
                    </div>
                    <div className="capacity-advice">
                      <strong>
                        {scaleFits
                          ? 'The modeled index remains memory-resident.'
                          : optimizedReads
                            ? 'The modeled overflow lands on the NVMe tier.'
                            : 'The modeled index spills beyond the buffer pool.'}
                      </strong>
                      <span>
                        {scaleSelectivity < 10
                          ? 'Highly selective filters require repeated HNSW resumes; consider workload-specific partial indexes.'
                          : 'Current selectivity keeps iterative-scan overfetch bounded.'}
                      </span>
                    </div>
                  </section>

                  <section className="distribution-panel">
                    <header>
                      <span className="section-label">
                        Live corpus distribution
                      </span>
                      <span className="status-pill">
                        {baselineChunks.toLocaleString()} chunks
                      </span>
                    </header>
                    <div>
                      {(diagnostics?.distribution || []).map((row) => (
                        <div key={row.evidence_kind}>
                          <span>{KIND_LABELS[row.evidence_kind]}</span>
                          <strong>{row.documents.toLocaleString()}</strong>
                          <i
                            style={{
                              width: `${Math.max(
                                (row.documents /
                                  Math.max(
                                    ...(diagnostics?.distribution || []).map(
                                      (item) => item.documents,
                                    ),
                                    1,
                                  )) *
                                  100,
                                1,
                              )}%`,
                            }}
                          />
                        </div>
                      ))}
                    </div>
                  </section>
                </div>

                <section className="build-history-panel">
                  <header>
                    <div>
                      <span className="section-label">
                        Search-index build receipts
                      </span>
                      <h2>Build without blocking casework</h2>
                    </div>
                    <span className="status-pill ready">
                      {latestBuild?.status || 'checking'}
                    </span>
                  </header>
                  <div className="build-methods">
                    <div>
                      <strong>Ordinary CREATE INDEX</strong>
                      <span>SHARE lock permits reads while writes queue.</span>
                    </div>
                    <div>
                      <strong>CREATE INDEX CONCURRENTLY</strong>
                      <span>Two passes, no write blocking, INVALID cleanup on failure.</span>
                    </div>
                    <div>
                      <strong>Blue/green</strong>
                      <span>Build, evaluate, then switch once the window is too large.</span>
                    </div>
                  </div>
                  <div className="build-receipts">
                    {(diagnostics?.recent_builds || []).map((build) => (
                      <div key={build.build_id}>
                        <span
                          className={`status-pill ${
                            build.status === 'complete' ? 'ready' : ''
                          }`}
                        >
                          {build.status}
                        </span>
                        <code>{compactId(build.build_id)}</code>
                        <strong>
                          {build.document_count.toLocaleString()} docs ·{' '}
                          {build.cache_hit_count.toLocaleString()} cache hits
                        </strong>
                        <small>
                          {build.completed_at
                            ? dateTime(build.completed_at)
                            : 'incomplete'}
                          {build.error ? ` · ${build.error}` : ''}
                        </small>
                      </div>
                    ))}
                  </div>
                </section>

                <p className="model-disclaimer">
                  <strong>Capacity values are a model, not a benchmark.</strong>
                  {' '}
                  The corpus count and build receipts are live; memory, build
                  throughput, overfetch, and latency estimates must be replaced
                  by release-gate measurements on the target Aurora engine.
                </p>
              </>
            ) : null}
          </section>
        ) : null}

        {module === 'prove' ? (
          <section className="module-screen">
            <header className="module-heading prove-heading">
              <div>
                <span className="module-kicker">
                  {proveTab === 'answer' ? 'Step 2' : 'Deep dive'} ·{' '}
                  {proveTab === 'answer'
                    ? 'Build cited answer'
                    : proveTab === 'graph'
                      ? 'Evidence graph & verdicts'
                      : proveTab === 'receipt'
                        ? 'Run receipt'
                        : proveTab === 'replay'
                          ? 'Replay proof'
                          : 'Evaluation lab'}
                </span>
                <h1>
                  {proveTab === 'answer' ? (
                    <>One missing source means one <em>withheld claim.</em></>
                  ) : proveTab === 'graph' ? (
                    <>Retrieval finds it. <em>Edges decide it.</em></>
                  ) : proveTab === 'receipt' ? (
                    <>Every candidate and citation, <em>persisted.</em></>
                  ) : proveTab === 'replay' ? (
                    <>Replay the answer from its <em>database receipt.</em></>
                  ) : (
                    <>Evidence, <em>not anecdotes.</em></>
                  )}
                </h1>
                <p className="module-deck">
                  {proveTab === 'answer'
                    ? 'Watch a real Strands agent recover the missing runbook, make bounded evidence decisions, and stream only citation-validated prose.'
                    : proveTab === 'graph'
                      ? 'Inspect canonical and inferred relationships under bounded traversal depth.'
                      : proveTab === 'receipt'
                        ? 'Resolve the controls, candidate signals, answer, citations, and search-index state without another model call.'
                        : proveTab === 'replay'
                          ? 'Walk the persisted retrieval stages in chronological order, reconstructed with no further model call.'
                          : 'Measure retrieval modes and graph traversal with different metrics.'}
                </p>
              </div>
              <div className="run-loader">
                <input
                  value={runId}
                  onChange={(event) => setRunId(event.target.value)}
                  aria-label="Run ID"
                  placeholder="Run ID"
                />
                <button
                  type="button"
                  className="icon-command"
                  disabled={!runId}
                  onClick={async () => {
                    await navigator.clipboard.writeText(runId);
                    setCopied(true);
                    window.setTimeout(() => setCopied(false), 1200);
                  }}
                  title="Copy run ID"
                  aria-label="Copy run ID"
                >
                  {copied ? <Check size={15} /> : <Clipboard size={15} />}
                </button>
                <button
                  type="button"
                  className="run-button"
                  onClick={() => loadRun(runId)}
                  disabled={!runId || busy !== null}
                >
                  {busy === 'run' ? (
                    <LoaderCircle className="spin" size={15} />
                  ) : (
                    <RefreshCw size={14} />
                  )}
                  Load
                </button>
              </div>
            </header>

            {proveTab === 'answer' ? (
              <section className="threadline-answer-page">
                <header className="answer-story-head">
                  <div className="answer-story-eyebrow">
                    <span />
                    Strands agent · Aurora evidence · cited answer
                  </div>
                  <blockquote>“{controls.query}”</blockquote>
                  <div className="answer-story-meta">
                    <span
                      className={`answer-grounding-state ${agentStreamState}`}
                    >
                      {agentStreamState === 'complete' ? (
                        <ShieldCheck size={13} />
                      ) : agentStreamState === 'streaming' ? (
                        <LoaderCircle className="spin" size={13} />
                      ) : (
                        <AlertTriangle size={13} />
                      )}
                      {agentStreamState === 'complete'
                        ? 'grounded'
                        : agentStreamState === 'streaming'
                          ? 'agent working'
                          : 'answer withheld'}
                    </span>
                    <span>
                      run <b>{compactId(answer?.run_id || runId)}</b>
                    </span>
                    {agentLatencyMs !== null ? (
                      <span>
                        <b>{(agentLatencyMs / 1000).toFixed(1)} s</b> agent run
                      </span>
                    ) : null}
                  </div>
                </header>

                <div className="answer-story-layout">
                  <article className="answer-story-document">
                    {agentStreamState === 'blocked' ? (
                      <div className="answer-gate">
                        <span className="answer-gate-count">2 / 3 claims grounded</span>
                        <h2>Synthesis is deliberately withheld.</h2>
                        <p className="answer-gate-lead">
                          Cause and visible customer impact have evidence. The
                          safe-fix claim does not, because <code>RB-017</code>{' '}
                          never entered the cluster-scoped result set.
                        </p>
                        <div className="answer-claim-checklist">
                          <div className="covered">
                            <Check size={16} />
                            <span>
                              <strong>Why writes blocked</strong>
                              CHG-1842 + captured lock evidence
                            </span>
                          </div>
                          <div className="covered">
                            <Check size={16} />
                            <span>
                              <strong>Visible customer impact</strong>
                              CASE-7419 under the workshop principal
                            </span>
                          </div>
                          <div className="missing">
                            <AlertTriangle size={16} />
                            <span>
                              <strong>Safe remediation</strong>
                              Approved runbook absent; claim withheld
                            </span>
                          </div>
                        </div>
                        <section className="answer-participant-task">
                          <span className="section-label">
                            Participant exercise 2
                          </span>
                          <h3>Authorize one bounded recovery.</h3>
                          <p>
                            Let the Strands agent keep incident evidence scoped
                            to <code>{controls.clusterId}</code>, remove only the
                            cluster and incident filters from the reusable
                            runbook search, and preserve the caller principal.
                          </p>
                          <button
                            type="button"
                            className="agent-command"
                            onClick={askAgent}
                            disabled={busy !== null}
                          >
                            <Sparkles size={16} />
                            Recover RB-017 and stream the answer
                            <ArrowRight size={15} />
                          </button>
                        </section>
                      </div>
                    ) : null}

                    {agentStreamState === 'streaming' ? (
                      <div className="answer-streaming-prose" aria-live="polite">
                        <span className="section-label">
                          Citation-validated prose
                        </span>
                        {streamingAnswer ? (
                          <p>
                            <FormattedAnswer text={streamingAnswer} />
                            <span className="answer-type-cursor" />
                          </p>
                        ) : (
                          <div className="answer-stream-waiting">
                            <LoaderCircle className="spin" size={18} />
                            <span>
                              The agent is gathering evidence. Prose appears
                              only after the synthesis tool validates citations.
                            </span>
                          </div>
                        )}
                      </div>
                    ) : null}

                    {agentStreamState === 'complete' && answer ? (
                      <div className="answer-complete-prose">
                        <p className="answer-lead">
                          The safe-fix claim is now supported by the approved
                          runbook, so Verity can release the complete answer.
                        </p>
                        <div className="answer-prose">
                          <FormattedAnswer text={streamingAnswer || answer.answer_text} />
                        </div>
                        <div className="answer-proof-strip">
                          <span>
                            <b>{agentTrace.length}</b>
                            observable tool calls
                          </span>
                          <span>
                            <b>{runbookRecovered ? 'yes' : 'no'}</b>
                            RB-017 cited
                          </span>
                        </div>
                        {receipt?._verify_sql?.answer ? (
                          <VerifyAffordance
                            descriptor={receipt._verify_sql.answer}
                            label="verify answer in psql"
                          />
                        ) : null}
                      </div>
                    ) : null}

                    {agentStreamState === 'error' ? (
                      <div className="answer-gate error">
                        <span className="answer-gate-count">Answer withheld</span>
                        <h2>The evidence gate did not pass.</h2>
                        <p className="answer-gate-lead">
                          Verity will not present agent commentary as an answer
                          of record. Review the observable calls below, then retry
                          the bounded recovery.
                        </p>
                        <button
                          type="button"
                          className="agent-command"
                          onClick={askAgent}
                          disabled={busy !== null}
                        >
                          <RefreshCw size={15} />
                          Retry the Strands run
                        </button>
                      </div>
                    ) : null}
                  </article>

                  <aside className="answer-sources-rail">
                    <header>
                      <span className="section-label">
                        Sources · {answerCitations.length} cited
                      </span>
                    </header>
                    {answerCitations.length ? (
                      <div className="answer-source-list">
                        {answerCitations
                          .slice()
                          .sort(
                            (left, right) =>
                              (left.citation_number || left.n || 99) -
                              (right.citation_number || right.n || 99),
                          )
                          .map((citation) => (
                            <button
                              type="button"
                              className="answer-source"
                              key={`${citation.external_key}-${citation.citation_number || citation.n}`}
                              onClick={() => {
                                if (citation.evidence_id) {
                                  setSelectedEvidenceId(citation.evidence_id);
                                }
                              }}
                            >
                              <span className="answer-source-number">
                                {citation.citation_number || citation.n}
                              </span>
                              <span>
                                <strong>{citation.external_key}</strong>
                                <small>{citation.title}</small>
                                <code>{citation.source_revision}</code>
                                <em>{sourceRole(citation)}</em>
                              </span>
                            </button>
                          ))}
                      </div>
                    ) : (
                      <div className="answer-source-expected">
                        {['Cause', 'Visible impact', 'Safe remediation'].map(
                          (label) => (
                            <div className="pending" key={label}>
                              <LoaderCircle className="spin" size={14} />
                              <span>
                                <strong>Awaiting evidence</strong>
                                <small>{label}</small>
                              </span>
                            </div>
                          ),
                        )}
                      </div>
                    )}
                    <section className="answer-coverage-card">
                      <div>
                        <span>Claim coverage</span>
                        <b>{agentStreamState === 'complete' ? '3/3' : '2/3'}</b>
                      </div>
                      <div className="answer-coverage-meter">
                        <i
                          style={{
                            width:
                              agentStreamState === 'complete' ? '100%' : '66.67%',
                          }}
                        />
                      </div>
                      <p>
                        {agentStreamState === 'complete'
                          ? 'Every citation resolves to a source URI, revision, exact chunk, and supporting quote.'
                          : 'RB-017 must be present and cited before the answer can pass.'}
                      </p>
                    </section>
                  </aside>
                </div>

                {agentStreamState !== 'complete' ? (
                  <section className="agent-live-decision" aria-live="polite">
                    <div>
                      <span className="agent-live-indicator">
                        {agentStreamState === 'streaming' ? (
                          <i />
                        ) : (
                          <CircleDot size={12} />
                        )}
                        Observable agent activity
                      </span>
                      <strong>
                        {currentAgentEvent
                          ? readableToolName(currentAgentEvent.tool)
                          : agentStreamState === 'blocked'
                            ? 'waiting for participant authorization'
                            : 'no tool call recorded'}
                      </strong>
                      <p>
                        {currentAgentEvent
                          ? toolDecision(currentAgentEvent)
                          : 'Only tool calls, filter choices, result counts, and validated outcomes appear here. Hidden chain-of-thought is never exposed.'}
                      </p>
                    </div>
                    <span>
                      {currentAgentEvent
                        ? `${toolResult(currentAgentEvent)} · ${(currentAgentEvent.latency_ms || 0).toLocaleString()} ms`
                        : 'Strands event stream'}
                    </span>
                  </section>
                ) : null}

                <section className="answer-build-story">
                  <header>
                    <div>
                      <span className="section-label">
                        How this answer was built
                      </span>
                      <h2>
                        Decisions first. Prose only after the evidence gate.
                      </h2>
                    </div>
                    <span className="status-pill">
                      {agentTrace.length
                        ? `${agentTrace.length} observed calls`
                        : 'exercise not started'}
                    </span>
                  </header>
                  <div className="answer-build-timeline">
                    {agentTrace.length ? (
                      agentTrace.map((event, index) => (
                        <div key={`${event.sequence || index}-${event.tool}`}>
                          <span>{event.sequence || index + 1}</span>
                          <div>
                            <strong>{readableToolName(event.tool)}</strong>
                            <p>{toolDecision(event)}</p>
                            <small>
                              {toolResult(event)}
                              {event.run_id
                                ? ` · ${compactId(event.run_id)}`
                                : ''}
                            </small>
                          </div>
                          <time>
                            {(event.latency_ms || 0).toLocaleString()} ms
                          </time>
                        </div>
                      ))
                    ) : (
                      <>
                        <div className="complete">
                          <span>1</span>
                          <div>
                            <strong>Baseline retrieval</strong>
                            <p>
                              Production evidence is ranked and persisted; two
                              claims are covered.
                            </p>
                            <small>{compactId(runId)}</small>
                          </div>
                          <time>complete</time>
                        </div>
                        <div className="waiting">
                          <span>2</span>
                          <div>
                            <strong>Bounded runbook recovery</strong>
                            <p>
                              Waiting to relax only the scope that reusable
                              guidance does not carry.
                            </p>
                            <small>principal unchanged</small>
                          </div>
                          <time>waiting</time>
                        </div>
                        <div className="blocked">
                          <span>3</span>
                          <div>
                            <strong>Cited synthesis</strong>
                            <p>
                              Blocked until all required evidence kinds are
                              present.
                            </p>
                            <small>safe-fix claim withheld</small>
                          </div>
                          <time>blocked</time>
                        </div>
                      </>
                    )}
                  </div>
                </section>

                <section className="answer-decisions">
                  <header>
                    <span className="section-label">Evidence-boundary decisions</span>
                    <h2>What changed, and what did not.</h2>
                  </header>
                  <div>
                    <article>
                      <span>01</span>
                      <strong>Incident scope stays narrow</strong>
                      <p>
                        Cause, lock, and customer evidence remain filtered to{' '}
                        <code>{controls.clusterId}</code>.
                      </p>
                    </article>
                    <article className={boundedRecoveryObserved ? 'observed' : ''}>
                      <span>02</span>
                      <strong>Only reusable guidance widens</strong>
                      <p>
                        The runbook subquery removes cluster and incident scope;
                        other retrievals do not.
                      </p>
                    </article>
                    <article>
                      <span>03</span>
                      <strong>Authorization is unchanged</strong>
                      <p>
                        The principal remains{' '}
                        <code>
                          {controls.supportLead ? 'support-lead' : 'workshop'}
                        </code>{' '}
                        for every retrieval and relationship hop.
                      </p>
                    </article>
                    <article className={runbookRecovered ? 'observed' : ''}>
                      <span>04</span>
                      <strong>The answer gate is deterministic</strong>
                      <p>
                        Missing evidence returns a recovery instruction; only a
                        validated answer of record reaches the prose.
                      </p>
                    </article>
                  </div>
                </section>

                {agentCommentary ? (
                  <p className="agent-commentary">
                    <Sparkles size={14} />
                    <span>
                      <strong>Agent close:</strong> {agentCommentary}
                    </span>
                  </p>
                ) : null}

                {agentStreamState === 'complete' ? (
                  <div className="answer-next-actions">
                    <button
                      type="button"
                      className="run-button"
                      onClick={() => goTo('agent', 'graph')}
                    >
                      <Network size={15} />
                      Follow source relationships
                    </button>
                    <button
                      type="button"
                      className="text-command"
                      onClick={() => goTo('proof', 'replay')}
                    >
                      <Play size={15} />
                      Replay persisted proof
                    </button>
                    <span>
                      {agentMetadata?.framework || 'strands-agents'} ·{' '}
                      {agentMetadata?.synthesis_model || answer?.model_id || 'configured model'}
                      {agentUsage?.total_tokens
                        ? ` · ${agentUsage.total_tokens.toLocaleString()} tokens`
                        : ''}
                    </span>
                  </div>
                ) : null}
              </section>
            ) : null}

            {proveTab === 'graph' ? (
              <>
                <div className="graph-studio">
                  <aside className="graph-controls-panel">
                    <div className="graph-scope">
                      <span className="section-label">Investigation</span>
                      <p>{controls.query}</p>
                      <span className="graph-scope-principal">
                        principal{' '}
                        <strong>
                          {controls.supportLead ? 'support-lead' : 'workshop'}
                        </strong>
                      </span>
                    </div>
                    <label>
                      <span>Traversal depth</span>
                      <div className="segmented">
                        {[1, 2].map((depth) => (
                          <button
                            key={depth}
                            type="button"
                            className={graphDepth === depth ? 'active' : ''}
                            onClick={() => setGraphDepth(depth)}
                          >
                            {depth === 1 ? '1 hop' : '≤ 2 hops'}
                          </button>
                        ))}
                      </div>
                    </label>
                    <label>
                      <span>Edge origin</span>
                      <div className="segmented">
                        <button
                          type="button"
                          className={
                            graphEdgeMode === 'canonical' ? 'active' : ''
                          }
                          onClick={() => setGraphEdgeMode('canonical')}
                        >
                          canonical
                        </button>
                        <button
                          type="button"
                          className={graphEdgeMode === 'all' ? 'active' : ''}
                          onClick={() => setGraphEdgeMode('all')}
                        >
                          all
                        </button>
                      </div>
                    </label>
                    <div className="graph-kind-list">
                      <span>Evidence in view</span>
                      {Object.entries(
                        (visibleGraph?.nodes || []).reduce<
                          Partial<Record<EvidenceKind, number>>
                        >((counts, node) => {
                          counts[node.evidence_kind] =
                            (counts[node.evidence_kind] || 0) + 1;
                          return counts;
                        }, {}),
                      ).map(([kind, count]) => (
                        <div key={kind}>
                          <KindIcon kind={kind as EvidenceKind} size={14} />
                          <span>{KIND_LABELS[kind as EvidenceKind]}</span>
                          <strong>{count}</strong>
                        </div>
                      ))}
                    </div>
                    <div className="graph-policy-note">
                      <LockKeyhole size={16} />
                      <span>
                        Authorization is checked again at every relationship
                        hop. Hidden evidence never enters this canvas.
                      </span>
                    </div>
                  </aside>

                  <section className="graph-canvas-panel">
                    <header>
                      <div>
                        <span className="section-label">
                          Relationship proof
                        </span>
                        <h2>Canonical facts and labeled inference</h2>
                      </div>
                      <div className="graph-toolbar-status">
                        <span className="status-pill">
                          {visibleGraph?.node_count || 0} nodes
                        </span>
                        <span className="status-pill">
                          {visibleGraph?.edge_count || 0} edges
                        </span>
                      </div>
                    </header>
                    <div className="graph-legend">
                      <span>
                        <i className="solid-line" /> canonical
                      </span>
                      <span>
                        <i className="dashed-line" /> inferred
                      </span>
                    </div>
                    {visibleGraph?.nodes.length ? (
                      <EvidenceGraph
                        graph={visibleGraph}
                        onSelect={setSelectedEvidenceId}
                        selectedEvidenceId={selectedGraphNode?.evidence_id || null}
                      />
                    ) : (
                      <Empty
                        icon={<Network size={22} />}
                        title="No relationship proof"
                      />
                    )}
                  </section>

                  <aside className="graph-inspector-panel">
                    <header>
                      <span className="section-label">Selected evidence</span>
                      <span
                        className={`kind-glyph kind-${
                          selectedGraphNode?.evidence_kind || 'unknown'
                        }`}
                      >
                        <KindIcon kind={selectedGraphNode?.evidence_kind} />
                      </span>
                    </header>
                    {selectedGraphNode ? (
                      <>
                        <h2>{selectedGraphNode.external_key}</h2>
                        <p>
                          {evidenceDetail?.evidence.title ||
                            selectedGraphNode.title}
                        </p>
                        <dl className="graph-signal-list">
                          <div>
                            <dt>Full-text position</dt>
                            <dd>
                              {selectedGraphCandidate
                                ? position(selectedGraphCandidate, 'text') ||
                                  '—'
                                : '—'}
                            </dd>
                          </div>
                          <div>
                            <dt>Semantic position</dt>
                            <dd>
                              {selectedGraphCandidate
                                ? position(selectedGraphCandidate, 'vector') ||
                                  '—'
                                : '—'}
                            </dd>
                          </div>
                          <div>
                            <dt>Fuzzy position</dt>
                            <dd>
                              {selectedGraphCandidate
                                ? position(selectedGraphCandidate, 'fuzzy') ||
                                  '—'
                                : '—'}
                            </dd>
                          </div>
                          <div>
                            <dt>RRF score</dt>
                            <dd>
                              {score(selectedGraphCandidate?.rrf_score, 5)}
                            </dd>
                          </div>
                        </dl>
                        <div className="graph-edge-list">
                          <span className="section-label">
                            Connected relationships
                          </span>
                          {selectedGraphEdges.map((edge) => (
                            <div key={edge.edge_key}>
                              <strong>{edge.relation}</strong>
                              <span>
                                {edge.from_evidence_id ===
                                selectedGraphNode.evidence_id
                                  ? edge.to_external_key
                                  : edge.from_external_key}
                              </span>
                              <small>
                                {edge.origin} · {score(edge.confidence, 2)}
                              </small>
                              <VerifyAffordance
                                descriptor={edge._verify_sql}
                                label="verify edge in psql"
                              />
                            </div>
                          ))}
                          {!selectedGraphEdges.length ? (
                            <small>No visible relationships.</small>
                          ) : null}
                        </div>
                      </>
                    ) : (
                      <Empty
                        icon={<FileSearch size={18} />}
                        title="Select a graph node"
                      />
                    )}
                  </aside>
                </div>

                <section className="graph-verdict-strip">
                  <header>
                    <span className="section-label">
                      Relationship verdicts
                    </span>
                    <span>
                      Canonical foreign keys and governed inference remain
                      distinguishable in every row.
                    </span>
                  </header>
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>From</th>
                          <th>Relationship</th>
                          <th>Evidence</th>
                          <th>Origin</th>
                          <th>Confidence</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(visibleGraph?.edges || []).map((edge) => (
                          <tr key={edge.edge_key}>
                            <td>{edge.from_external_key}</td>
                            <td>
                              <span className="verdict-chip">
                                {edge.relation}
                              </span>
                            </td>
                            <td>{edge.to_external_key}</td>
                            <td>{edge.origin}</td>
                            <td>{score(edge.confidence, 2)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              </>
            ) : null}

            {proveTab === 'replay' ? (
              <>
                <section className="replay-stage-strip">
                  {(receipt?.stages || []).map((stage) => (
                    <div key={stage.stage_ordinal}>
                      <strong>
                        {stage.stage_ordinal} · {stage.stage_name}
                      </strong>
                      <span>{stage.duration_ms.toLocaleString()} ms</span>
                    </div>
                  ))}
                  {!receipt?.stages.length ? (
                    <Empty
                      icon={<GitMerge size={18} />}
                      title="No persisted stages"
                    />
                  ) : (
                    <VerifyAffordance
                      descriptor={receipt?._verify_sql?.stages}
                      label="verify stages in psql"
                    />
                  )}
                </section>

                <section className="replay-theater">
                  <header>
                    <div>
                      <span className="section-label">
                        Chronological run replay
                      </span>
                      <h2>{receipt?.run.query_text || controls.query}</h2>
                    </div>
                    <div className="replay-theater-head-meta">
                      <span
                        className={`status-pill ${
                          receipt?.run.status === 'complete' ? 'ready' : ''
                        }`}
                      >
                        {receipt?.run.status || 'not loaded'}
                      </span>
                      {receipt ? (
                        <VerifyAffordance
                          descriptor={receipt._verify_sql?.run}
                          label="verify run in psql"
                        />
                      ) : null}
                    </div>
                  </header>
                  {receipt ? (
                    <div className="replay-timeline">
                      <div>
                        <time>00:00.000</time>
                        <i />
                        <div>
                          <strong>Question accepted</strong>
                          <span>
                            Principal{' '}
                            {controls.supportLead
                              ? 'support-lead'
                              : 'workshop'}
                            ; cluster {controls.clusterId || 'all'}.
                          </span>
                        </div>
                        <b>OK</b>
                      </div>
                      {receipt.stages.map((stage, index) => (
                        <div key={stage.stage_ordinal}>
                          <time>
                            T+
                            {elapsedMilliseconds(
                              receipt.stages,
                              index,
                            ).toLocaleString()}{' '}
                            ms
                          </time>
                          <i />
                          <div>
                            <strong>{stage.stage_name}</strong>
                            <span>
                              {Object.entries(stage.details)
                                .slice(0, 2)
                                .map(
                                  ([key, value]) =>
                                    `${key.replace(/_/g, ' ')}: ${String(value)}`,
                                )
                                .join(' · ') || 'Stage persisted'}
                            </span>
                          </div>
                          <b>{stage.duration_ms.toLocaleString()} ms</b>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <Empty
                      icon={<FileCheck2 size={20} />}
                      title="No run loaded"
                    />
                  )}
                </section>
              </>
            ) : null}

            {proveTab === 'receipt' ? (
              <>
                <section className="replay-summary">
                  <div>
                    <strong>{compactId(receipt?.run.run_id)}</strong>
                    <span>run ID</span>
                  </div>
                  <div>
                    <strong>{receipt?.run.candidate_count ?? '—'}</strong>
                    <span>candidates</span>
                  </div>
                  <div>
                    <strong>{receipt?.answer?.citations.length ?? '—'}</strong>
                    <span>citations</span>
                  </div>
                  <div>
                    <strong>
                      {receipt?.run.latency_ms === null ||
                      receipt?.run.latency_ms === undefined
                        ? '—'
                        : `${receipt.run.latency_ms} ms`}
                    </strong>
                    <span>retrieval</span>
                  </div>
                </section>

                <div className="replay-detail-grid">
                  <section className="proof-receipt">
                    <header>
                      <div>
                        <span className="section-label">
                          Candidate-level receipt
                        </span>
                        <h2>Signals remain separate and replayable</h2>
                      </div>
                      <span className="status-pill">
                        {receipt?.run.retrieval_mode || '—'}
                      </span>
                    </header>
                    {receipt ? (
                      <>
                        <div className="table-scroll">
                          <table>
                            <thead>
                              <tr>
                                <th>#</th>
                                <th>Evidence</th>
                                <th>FTS</th>
                                <th>VEC</th>
                                <th>TRGM</th>
                                <th>RRF</th>
                                <th>Rerank</th>
                                <th>Source revision</th>
                              </tr>
                            </thead>
                            <tbody>
                              {receipt.candidates.map((candidate, index) => (
                                <tr key={`${candidate.evidence_id}-${index}`}>
                                  <td>{candidate.result_rank || index + 1}</td>
                                  <td>
                                    <strong>{candidate.external_key}</strong>
                                    <span>{candidate.title}</span>
                                  </td>
                                  <td>{position(candidate, 'text') || '—'}</td>
                                  <td>
                                    {position(candidate, 'vector') || '—'}
                                  </td>
                                  <td>{position(candidate, 'fuzzy') || '—'}</td>
                                  <td>{score(candidate.rrf_score, 5)}</td>
                                  <td>{score(candidate.rerank_score, 3)}</td>
                                  <td>
                                    {snapshot(candidate).source_revision || '—'}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                        <div className="replay-endpoints">
                          <strong>Replay without model calls</strong>
                          <code>
                            GET /v1/runs/{compactId(receipt.run.run_id)}
                          </code>
                          <code>/candidates</code>
                          <code>/timeline</code>
                          <code>/graph</code>
                        </div>
                        <VerifyAffordance
                          descriptor={receipt._verify_sql?.candidates}
                          label="verify candidates in psql"
                        />
                      </>
                    ) : null}
                  </section>

                  <aside className="health-panel">
                    <header>
                      <span className="section-label">Search index health</span>
                      <span
                        className={`status-pill ${
                          health?.drift_issues === 0 ? 'ready' : ''
                        }`}
                      >
                        {health?.drift_issues ?? '—'} drift
                      </span>
                    </header>
                    <dl>
                    <div>
                      <dt>Source documents</dt>
                      <dd>{health?.source_documents.toLocaleString() || '—'}</dd>
                    </div>
                    <div>
                      <dt>Ready documents</dt>
                      <dd>
                        {health?.current_documents.toLocaleString() || '—'}
                      </dd>
                    </div>
                    <div>
                      <dt>Ready embeddings</dt>
                      <dd>
                        {health?.ready_embeddings.toLocaleString() || '—'}
                      </dd>
                    </div>
                    <div>
                      <dt>Embedding model</dt>
                      <dd>{embeddingModel}</dd>
                    </div>
                    <div>
                      <dt>Latest build</dt>
                      <dd>{compactId(latestBuild?.build_id)}</dd>
                    </div>
                    <div>
                      <dt>Indexed</dt>
                      <dd>{dateTime(health?.last_indexed_at)}</dd>
                    </div>
                    </dl>
                    <div className="receipt-builds">
                      <span className="section-label">Recent builds</span>
                      {(diagnostics?.recent_builds || []).map((build) => (
                        <div key={build.build_id}>
                          <span
                            className={`status-pill ${
                              build.status === 'complete' ? 'ready' : ''
                            }`}
                          >
                            {build.status}
                          </span>
                          <code>{compactId(build.build_id)}</code>
                          <small>
                            {build.document_count.toLocaleString()} docs ·{' '}
                            {build.cache_hit_count.toLocaleString()} cache hits
                          </small>
                        </div>
                      ))}
                    </div>
                  </aside>
                </div>
              </>
            ) : null}

            {proveTab === 'evaluation' ? (
              <>
                <section className="benchmark-runbar">
                  <div>
                    <span className="section-label">Evaluation readiness</span>
                    <strong>
                      {health?.ready_embeddings.toLocaleString() || '—'} ready
                      embeddings
                    </strong>
                    <span>{health?.drift_issues ?? '—'} search-index drift</span>
                  </div>
                  <div>
                    <span className="section-label">Judged set</span>
                    <strong>
                      {evaluation
                        ? evaluation.query_count
                        : 'retrieval + traversal'}
                    </strong>
                    <span>metrics remain separate by evaluation type</span>
                  </div>
                  <button
                    type="button"
                    className="run-button"
                    onClick={runEvaluation}
                    disabled={busy !== null}
                  >
                    {busy === 'evaluation' ? (
                      <LoaderCircle className="spin" size={15} />
                    ) : (
                      <Play size={14} />
                    )}
                    Run evaluation
                  </button>
                </section>

                {evaluation ? (
                  <>
                    <div className="benchmark-summary">
                      <div className="benchmark-mode-cards">
                        {evaluation.leaderboard.map((row) => (
                          <article
                            key={row.mode}
                            className={
                              row.mode === evaluationLeader?.mode
                                ? 'winner'
                                : ''
                            }
                          >
                            <span>{row.mode}</span>
                            <strong>{score(row.ndcg_at_10, 3)}</strong>
                            <small>mean nDCG@10</small>
                            <dl>
                              <div>
                                <dt>Recall@10</dt>
                                <dd>{score(row.recall_at_10, 3)}</dd>
                              </div>
                              <div>
                                <dt>MRR</dt>
                                <dd>{score(row.mrr, 3)}</dd>
                              </div>
                            </dl>
                          </article>
                        ))}
                      </div>
                      <aside className="benchmark-finding">
                        <span className="section-label">Finding</span>
                        <p>
                          <strong>{evaluationLeader?.mode || '—'}</strong>{' '}
                          leads this judged set at{' '}
                          {score(evaluationLeader?.ndcg_at_10, 3)} mean
                          nDCG@10.
                        </p>
                        <small>
                          Compare the rows below before attributing the mean to
                          any single retrieval arm.
                        </small>
                      </aside>
                    </div>

                    <section className="benchmark-matrix">
                      <header>
                        <div>
                          <span className="section-label">
                            Query-by-mode matrix · nDCG@10
                          </span>
                          <h2>Each query exposes a different failure mode</h2>
                        </div>
                        <span className="status-pill">
                          {evaluation.retrieval_query_count} retrieval queries
                        </span>
                      </header>
                      <div className="table-scroll">
                        <table>
                          <thead>
                            <tr>
                              <th>Archetype</th>
                              <th>Expected behavior</th>
                              {(['lexical', 'semantic', 'fuzzy', 'hybrid'] as const).map(
                                (mode) => (
                                  <th key={mode}>{mode}</th>
                                ),
                              )}
                            </tr>
                          </thead>
                          <tbody>
                            {evaluation.queries
                              .filter(
                                (query) =>
                                  query.evaluation_type === 'retrieval',
                              )
                              .map((query) => (
                                <tr key={query.query_id}>
                                  <td>
                                    <strong>{query.query_id}</strong>
                                  </td>
                                  <td className="evaluation-note">
                                    {query.notes}
                                  </td>
                                  {(
                                    [
                                      'lexical',
                                      'semantic',
                                      'fuzzy',
                                      'hybrid',
                                    ] as const
                                  ).map((mode) => {
                                    const result = query.results.find(
                                      (row) => row.mode === mode,
                                    );
                                    return (
                                      <td
                                        key={mode}
                                        className={`metric-${metricBand(
                                          result?.metrics?.ndcg_at_10,
                                        )}`}
                                      >
                                        {result?.error
                                          ? 'error'
                                          : score(
                                              result?.metrics?.ndcg_at_10,
                                              3,
                                            )}
                                      </td>
                                    );
                                  })}
                                </tr>
                              ))}
                          </tbody>
                        </table>
                      </div>
                      <p>{evaluation.metric_note}</p>
                      <VerifyAffordance descriptor={evaluation._verify_sql} />
                    </section>

                    <section className="benchmark-traversal">
                      <header>
                        <div>
                          <span className="section-label">
                            Relationship traversal
                          </span>
                          <h2>Judged as a relationship set, not a ranked list</h2>
                        </div>
                        <span className="status-pill">
                          {evaluation.traversal_query_count} traversal queries
                        </span>
                      </header>
                      <div>
                        {evaluation.queries
                          .filter(
                            (query) => query.evaluation_type === 'traversal',
                          )
                          .map((query) => {
                            const result = query.results[0];
                            return (
                              <article key={query.query_id}>
                                <strong>{query.query_id}</strong>
                                <p>{query.notes}</p>
                                <span>
                                  <b>{score(result?.metrics?.recall, 3)}</b>
                                  relationship recall
                                </span>
                                <span>
                                  <b>{score(result?.metrics?.precision, 3)}</b>
                                  relationship precision
                                </span>
                                <small>
                                  {result?.reached_count ?? '—'} evidence nodes
                                  reached
                                </small>
                              </article>
                            );
                          })}
                      </div>
                    </section>
                  </>
                ) : (
                  <section className="evaluation-empty">
                    <Empty
                      icon={<Gauge size={22} />}
                      title="Evaluation has not run"
                      detail="Run the deterministic judged set against all four retrieval modes."
                    />
                  </section>
                )}
              </>
            ) : null}
          </section>
        ) : null}

        {module === 'tools' ? (
          <section className="module-screen">
            <header className="module-heading">
              <div>
                <span className="module-kicker">Module 3</span>
                <h1>
                  Invoke the managed <em>tool contract.</em>
                </h1>
              </div>
              <span
                className={`status-pill ${receipt ? 'ready' : 'pending'}`}
              >
                {receipt ? <Check size={13} /> : <LoaderCircle size={13} />}
                {receipt ? 'HTTP receipt loaded' : 'awaiting run'}
              </span>
            </header>

            <div className="transport-grid">
              <section className="transport-card">
                <span className="transport-number">01</span>
                <Database size={20} />
                <h2>HTTP / FastAPI</h2>
                <code>POST /v1/search</code>
                <span className="status-pill ready">local API</span>
              </section>
              <section className="transport-card">
                <span className="transport-number">02</span>
                <Code2 size={20} />
                <h2>stdio MCP</h2>
                <code>verity.search_evidence</code>
                <span className="status-pill">local adapter</span>
              </section>
              <section className="transport-card">
                <span className="transport-number">03</span>
                <Server size={20} />
                <h2>AgentCore Gateway</h2>
                <code>search_evidence</code>
                <span className="status-pill">pre-provisioned</span>
              </section>
            </div>

            <div className="tool-contract-layout">
              <section className="tool-selector">
                <header>
                  <span className="section-label">Canonical tools</span>
                  <span>v1</span>
                </header>
                <div>
                  {TOOL_NAMES.map((tool) => (
                    <button
                      key={tool}
                      type="button"
                      className={selectedTool === tool ? 'active' : ''}
                      onClick={() => setSelectedTool(tool)}
                    >
                      <span>{tool}</span>
                      <ChevronRight size={14} />
                    </button>
                  ))}
                </div>
              </section>

              <section className="sql-panel contract-panel">
                <header>
                  <span>{selectedTool}</span>
                  <span>normalized request</span>
                </header>
                <pre>
                  <code>{JSON.stringify(
                    selectedTool === 'search_evidence'
                      ? {
                          query: controls.query,
                          cluster_id: controls.clusterId || null,
                          principal: controls.supportLead
                            ? 'support-lead'
                            : 'workshop',
                          limit: controls.limit,
                        }
                      : {
                          run_id: runId || '<run_id>',
                          principal: controls.supportLead
                            ? 'support-lead'
                            : 'workshop',
                        },
                    null,
                    2,
                  )}</code>
                </pre>
              </section>

              <section className="normalized-result">
                <header>
                  <span className="section-label">Normalized result</span>
                </header>
                <dl>
                  <div>
                    <dt>run_id</dt>
                    <dd>{compactId(runId)}</dd>
                  </div>
                  <div>
                    <dt>evidence order</dt>
                    <dd>
                      {candidates
                        .slice(0, 3)
                        .map((candidate) => candidate.external_key)
                        .filter(Boolean)
                        .join(' → ') || '—'}
                    </dd>
                  </div>
                  <div>
                    <dt>visible set</dt>
                    <dd>{candidates.length} candidates</dd>
                  </div>
                  <div>
                    <dt>proof reference</dt>
                    <dd>{receipt ? 'persisted' : '—'}</dd>
                  </div>
                </dl>
              </section>
            </div>

            <section className="parity-panel">
              <header>
                <div>
                  <span className="section-label">Transport parity</span>
                  <h2>Runtime observation matrix</h2>
                </div>
                <span className="status-pill ready">
                  <ShieldCheck size={13} />
                  Aurora remains authoritative
                </span>
              </header>
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Assertion</th>
                      <th>HTTP</th>
                      <th>stdio MCP</th>
                      <th>AgentCore</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[
                      'Contract version',
                      'Evidence order',
                      'Arm positions',
                      'ACL-visible set',
                      'Citations',
                      'Proof reference',
                    ].map((assertion) => (
                      <tr key={assertion}>
                        <td>{assertion}</td>
                        <td className={receipt ? 'parity-ok' : 'parity-pending'}>
                          {receipt ? 'observed' : 'pending'}
                        </td>
                        <td className="parity-pending">not invoked</td>
                        <td className="parity-pending">not invoked</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </section>
        ) : null}
        </main>

        <footer className="verity-footer">
          <span>
            <Database size={13} />
            Aurora PostgreSQL
          </span>
          <span>
            <LockKeyhole size={13} />
            synthetic incident evidence
          </span>
          <span>
            <FileCheck2 size={13} />
            {runId ? compactId(runId) : 'no active run'}
          </span>
        </footer>
      </div>
    </div>
  );
}
