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
  PanelLeftClose,
  PanelLeftOpen,
  Play,
  RefreshCw,
  Search,
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
  type RefObject,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  formatRoute,
  parseRoute,
  type PresetKey,
  type PrincipalKey,
  type Route,
  type RouteSurface,
} from './route';
import {
  buildTimelineGrid,
  systemLabel,
  type TimelineGrid,
} from './timeline';

type ModuleName =
  | 'home'
  | 'retrieve'
  | 'prove'
  | 'corpus'
  | 'health';
type DiagnoseTab = 'results' | 'fusion';
type ProveTab =
  | 'answer'
  | 'graph'
  | 'receipt'
  | 'replay'
  | 'timeline'
  | 'evaluation';

// Overview-first IA (D16 / SPEC 6.0). Primary nav mirrors the lab ladder;
// each surface is a lens over the same run. The legacy module/proveTab/
// diagnoseTab state is derived from a (surface, subtab) selection so the
// existing panel render tree stays unchanged.
type Surface =
  | 'overview'
  | 'retrieval'
  | 'agent'
  | 'proof'
  | 'corpus'
  | 'evaluation'
  | 'health';

type NavLens = { key: string; label: string; Icon: typeof House };
type NavSurface = {
  surface: Surface;
  label: string;
  Icon: typeof House;
  lenses: NavLens[];
};

// Nav labels are Law-1 nouns (SPEC 6.0). Lens keys map to legacy state in
// goTo(); order is the lab ladder. Utility surfaces (Corpus / Evaluation /
// Health) never appear in the primary ladder.
const PRIMARY_NAV: NavSurface[] = [
  { surface: 'overview', label: 'Overview', Icon: House, lenses: [] },
  {
    surface: 'retrieval',
    label: 'Retrieval',
    Icon: FileSearch,
    lenses: [
      { key: 'results', label: 'Results', Icon: CircleDot },
      { key: 'fusion', label: 'Fusion', Icon: SlidersHorizontal },
    ],
  },
  {
    surface: 'agent',
    label: 'Agent',
    Icon: Sparkles,
    lenses: [
      { key: 'answer', label: 'Answer', Icon: FileCheck2 },
      { key: 'graph', label: 'Relationships', Icon: Network },
    ],
  },
  {
    surface: 'proof',
    label: 'Proof',
    Icon: ShieldCheck,
    lenses: [
      { key: 'receipt', label: 'Run record', Icon: Clipboard },
      { key: 'replay', label: 'Replay', Icon: Play },
      { key: 'timeline', label: 'Timeline', Icon: GitMerge },
    ],
  },
];

const UTILITY_NAV: NavSurface[] = [
  { surface: 'corpus', label: 'Corpus', Icon: Database, lenses: [] },
  { surface: 'evaluation', label: 'Evaluation', Icon: Gauge, lenses: [] },
  { surface: 'health', label: 'Health', Icon: Activity, lenses: [] },
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

interface TimelineEvent extends EvidenceSnapshot {
  evidence_id: string;
  external_key: string;
  evidence_kind: EvidenceKind;
  title: string;
  occurred_at: string | null;
  _verify_sql?: VerifySql;
}

interface RunTimeline {
  run_id: string;
  edge_count: number;
  events: TimelineEvent[];
}

interface QueryPlanResponse {
  arm: 'semantic' | 'lexical' | 'fuzzy';
  query: string;
  cluster_id: string | null;
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
    actual_startup_time_ms: number | null;
    actual_total_time_ms: number | null;
    shared_hit_blocks: number;
    shared_read_blocks: number;
    rows_removed_by_filter: number;
    filter: string | null;
    index_cond: string | null;
    recheck_cond: string | null;
  }>;
  runtime_sql: string;
  planner_summary: string;
  uses_hnsw: boolean | null;
  note: string;
  fuzzy_probe_tokens?: string[];
  abstained?: boolean;
  abstain_reason?: string;
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

function retrievalRequestKey(controls: Controls): string {
  return JSON.stringify({
    query: controls.query,
    mode: controls.mode,
    kind: controls.kind,
    clusterId: controls.clusterId,
    environment: controls.environment,
    limit: controls.limit,
    candidatePool: controls.candidatePool,
    rrfK: controls.rrfK,
    textWeight: controls.textWeight,
    vectorWeight: controls.vectorWeight,
    fuzzyWeight: controls.fuzzyWeight,
    fuzzyThreshold: controls.fuzzyThreshold,
    efSearch: controls.efSearch,
    rerank: controls.rerank,
    supportLead: controls.supportLead,
  });
}

// presetKey ties a preset to the SPEC 6.0 route vocabulary
// (?preset={exact|fuzzy|semantic}). The three tagged entries are the workshop's
// query-shape triad — exact identifier, paraphrase (semantic recall), and typo
// (fuzzy match) — all mode:'hybrid' because the teaching point is one fusion
// handling every query shape. The remaining examples stay UI-reachable but are
// not URL-addressable: the route contract names only the three shapes.
const PRESETS: {
  label: string;
  query: string;
  mode: RetrievalMode;
  kind: EvidenceKind | 'all';
  clusterId: string;
  presetKey?: PresetKey;
}[] = [
  {
    label: 'Production block',
    query: DEFAULT_QUERY,
    mode: 'hybrid' as RetrievalMode,
    kind: 'all' as const,
    clusterId: 'checkout-prod-cluster-01',
  },
  {
    label: 'Exact ID',
    query: 'CHG-1842',
    mode: 'hybrid' as RetrievalMode,
    kind: 'all' as const,
    clusterId: '',
    presetKey: 'exact',
  },
  {
    label: 'Semantic question',
    query:
      'Why could customers still read order history while new checkout writes timed out after maintenance?',
    mode: 'hybrid' as RetrievalMode,
    kind: 'all' as const,
    clusterId: '',
    presetKey: 'semantic',
  },
  {
    label: 'Typo recovery',
    query: 'CGH-1842',
    mode: 'hybrid' as RetrievalMode,
    kind: 'all' as const,
    clusterId: '',
    presetKey: 'fuzzy',
  },
  {
    label: 'Support filter',
    query:
      'Which visible customer reported checkout timeouts during the production write block?',
    mode: 'hybrid' as RetrievalMode,
    kind: 'support_case' as const,
    clusterId: 'checkout-prod-cluster-01',
  },
  {
    label: 'Runbook filter',
    query:
      'What index build method lets checkout writes continue during production maintenance?',
    mode: 'hybrid' as RetrievalMode,
    kind: 'runbook' as const,
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

const TOOL_CONTRACTS: Record<
  (typeof TOOL_NAMES)[number],
  { purpose: string; result: string; proof: string }
> = {
  decompose_question: {
    purpose: 'Extract identifiers, filters, and evidence requirements.',
    result: 'Ordered subquestions and inferred scope.',
    proof: 'The plan is inspectable before retrieval begins.',
  },
  search_evidence: {
    purpose: 'Run canonical hybrid retrieval with ACL and metadata filters.',
    result: 'Ranked evidence plus a persisted run ID.',
    proof: 'Candidate positions and scores are stored before synthesis.',
  },
  follow_evidence_links: {
    purpose: 'Traverse declared evidence relationships from retrieved seeds.',
    result: 'Reached records, relation labels, depth, and origin.',
    proof: 'Authorization is checked again at every hop.',
  },
  compare_sources: {
    purpose: 'Compare scope, revision, timing, and explicit relationships.',
    result: 'Evidence that rules records in or out.',
    proof: 'Comparison context becomes synthesis input.',
  },
  explain_ranking: {
    purpose: 'Read the persisted candidate order and arm diagnostics.',
    result: 'Match tier, arm positions, RRF, rerank, and stage timing.',
    proof: 'No score is recomputed and no model is called.',
  },
  synthesize_cited_answer: {
    purpose: 'Write only from evidence persisted by the supporting runs.',
    result: 'A cited answer or a deterministic recovery instruction.',
    proof: 'Every citation is validated against its exact stored chunk.',
  },
};

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
    return 'Read the persisted retrieval run without recomputing scores.';
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

// Read-only verification, never a client-side re-rank. Ranking lives in Aurora
// (canonical SQL); this recomputes the fused order from the backend-persisted
// match_tier / exact_identifier_position / rrf_score and checks the delivered
// candidate order already reproduces it. With rerank off, final order must equal
// fused order (the identity the rerank:false parity captures rely on); a
// mismatch is a defect and is surfaced, not hidden.
function isFusedOrder(candidates: Candidate[]): boolean {
  const expected = [...candidates].sort((a, b) => {
    const tierGap = matchTier(a) - matchTier(b);
    if (tierGap !== 0) return tierGap;
    const exactGap =
      (a.exact_identifier_position ?? Number.POSITIVE_INFINITY) -
      (b.exact_identifier_position ?? Number.POSITIVE_INFINITY);
    if (exactGap !== 0) return exactGap;
    return (
      (b.rrf_score ?? b.final_score ?? 0) - (a.rrf_score ?? a.final_score ?? 0)
    );
  });
  return candidates.every(
    (candidate, index) => candidate.evidence_id === expected[index].evidence_id,
  );
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

function InvestigationQueryField({
  value,
  onChange,
  ariaLabel,
  inputRef,
  readOnly = false,
  title,
  onFocus,
}: {
  value: string;
  onChange: (value: string) => void;
  ariaLabel: string;
  inputRef?: RefObject<HTMLInputElement>;
  readOnly?: boolean;
  title?: string;
  onFocus?: () => void;
}) {
  return (
    <>
      <Search size={20} aria-hidden="true" />
      <span className="investigation-query-field">
        <input
          ref={inputRef}
          value={value}
          readOnly={readOnly}
          title={title}
          onFocus={onFocus}
          onChange={(event) => onChange(event.target.value)}
          aria-label={ariaLabel}
        />
      </span>
    </>
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

// Measure the plotted event cells and connect their centers, in chronological
// (seq) order, into an SVG polyline anchored to the grid element. Coordinates
// are in the grid's own pixel space so the returned path maps 1:1 onto an
// overlay sized to the grid; the draw-in animation is pure CSS and collapses to
// instant under the global prefers-reduced-motion rule. Re-measures on grid
// resize (ResizeObserver) and whenever the placement signature changes, so
// loading a different run with the same event count but a different lane/day
// layout still re-stitches to the new cell positions.
function useStitchThread(
  gridRef: RefObject<HTMLDivElement | null>,
  signature: string,
  seqCount: number,
): { path: string; width: number; height: number } {
  const [thread, setThread] = useState({ path: '', width: 0, height: 0 });

  useLayoutEffect(() => {
    const grid = gridRef.current;
    if (!grid) return;

    const measure = () => {
      const frame = grid.getBoundingClientRect();
      const points: string[] = [];
      for (let seq = 1; seq <= seqCount; seq += 1) {
        const cell = grid.querySelector(`[data-seq="${seq}"]`);
        if (!cell) continue;
        const rect = (cell as HTMLElement).getBoundingClientRect();
        const x = rect.left - frame.left + rect.width / 2;
        const y = rect.top - frame.top + rect.height / 2;
        points.push(`${points.length ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`);
      }
      setThread({
        path: points.length > 1 ? points.join(' ') : '',
        width: frame.width,
        height: frame.height,
      });
    };

    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(grid);
    return () => observer.disconnect();
  }, [gridRef, signature, seqCount]);

  return thread;
}

// Proof > Timeline lens (SPEC 6.0). Plots the run's cited evidence on a
// source-system x calendar-day grid and stitches it in chronological order, so
// the same set the retrieval arms ranked reads as the incident's actual
// sequence. Every value is derived from the live /timeline payload; nothing is
// hardcoded and no cited event is dropped.
function TimelineGridView({ grid }: { grid: TimelineGrid<TimelineEvent> }) {
  const gridRef = useRef<HTMLDivElement>(null);

  const cells = new Map<string, typeof grid.placed>();
  for (const placed of grid.placed) {
    const key = `${placed.row}:${placed.col}`;
    const group = cells.get(key);
    if (group) group.push(placed);
    else cells.set(key, [placed]);
  }

  // Re-stitch whenever any event's cell position changes, even if the event
  // count is unchanged (a different run with the same number of citations).
  const placement = grid.placed
    .map((placed) => `${placed.seq}@${placed.row}:${placed.col}`)
    .join('|');
  const { path, width, height } = useStitchThread(
    gridRef,
    placement,
    grid.placed.length,
  );

  const hotColumn = grid.days.findIndex((day) => day.hot);
  const listOrder = [
    ...grid.placed.slice().sort((left, right) => left.seq - right.seq),
    ...grid.undated.map((event) => ({ event, seq: null as number | null })),
  ];

  return (
    <section className="tgrid-panel">
      {grid.placed.length ? (
        <div
          ref={gridRef}
          className="tgrid"
          style={{
            gridTemplateColumns: `minmax(118px, auto) repeat(${grid.days.length}, minmax(66px, 1fr))`,
            gridTemplateRows: `auto repeat(${grid.lanes.length}, minmax(58px, auto))`,
          }}
        >
          {hotColumn >= 0 ? (
            <div
              className="tgrid-hot-column"
              style={{
                gridColumn: hotColumn + 2,
                gridRow: `2 / ${grid.lanes.length + 2}`,
              }}
              aria-hidden="true"
            />
          ) : null}

          <div className="tgrid-corner" aria-hidden="true" />
          {grid.days.map((day, index) => (
            <div
              key={day.key}
              className={`tgrid-day-head ${day.hot ? 'hot' : ''}`}
              style={{ gridColumn: index + 2, gridRow: 1 }}
            >
              <span className="tgrid-day-label">{day.label}</span>
              <span className="tgrid-day-count">
                {day.count} {day.count === 1 ? 'event' : 'events'}
                {day.hot ? ' · busiest' : ''}
              </span>
            </div>
          ))}

          {grid.lanes.map((lane, index) => (
            <div
              key={lane.system}
              className="tgrid-lane-label"
              style={{ gridColumn: 1, gridRow: index + 2 }}
            >
              {lane.label}
            </div>
          ))}

          {path ? (
            <svg
              className="tgrid-thread"
              width={width}
              height={height}
              viewBox={`0 0 ${width} ${height}`}
              preserveAspectRatio="none"
              aria-hidden="true"
            >
              <path key={path} d={path} pathLength={1} />
            </svg>
          ) : null}

          {[...cells.entries()].map(([key, group]) => {
            const [{ row, col }] = group;
            return (
              <div
                key={key}
                className="tgrid-cell"
                style={{ gridColumn: col, gridRow: row }}
              >
                {group.map(({ event, seq }) => (
                  <div
                    key={event.evidence_id}
                    className="tgrid-node"
                    data-seq={seq}
                  >
                    <span className="tgrid-node-seq">{seq}</span>
                    <KindIcon kind={event.evidence_kind} size={13} />
                    <span className="tgrid-node-key">{event.external_key}</span>
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      ) : (
        <Empty
          icon={<GitMerge size={20} />}
          title="No dated evidence to plot"
          detail="Every cited item in this run is missing a timestamp; see the list below."
        />
      )}

      <ol className="tgrid-legend">
        {listOrder.map(({ event, seq }) => (
          <li key={event.evidence_id}>
            <span className={`tgrid-legend-seq ${seq === null ? 'undated' : ''}`}>
              {seq === null ? '—' : seq}
            </span>
            <span className="tgrid-legend-kind">
              <KindIcon kind={event.evidence_kind} size={14} />
              {KIND_LABELS[event.evidence_kind]}
            </span>
            <span className="tgrid-legend-body">
              <strong>
                {event.external_key} · {event.title}
              </strong>
              <span>
                {systemLabel(event.source_system)} ·{' '}
                {event.occurred_at ? dateTime(event.occurred_at) : 'no timestamp — not plotted'}
              </span>
            </span>
            <VerifyAffordance
              descriptor={event._verify_sql}
              label="verify event"
            />
          </li>
        ))}
      </ol>
    </section>
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
      data-kind={item.evidence_kind || 'unknown'}
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

function FinalRankedEvidence({
  candidates,
  selectedEvidenceId,
  reranked,
  runId,
  onSelect,
}: {
  candidates: Candidate[];
  selectedEvidenceId: string | null;
  reranked: boolean;
  runId: string;
  onSelect: (candidate: Candidate) => void;
}) {
  const topCandidate = candidates[0];
  const topEvidence = topCandidate ? snapshot(topCandidate) : null;
  const topTextPosition = topCandidate
    ? position(topCandidate, 'text')
    : null;
  const topVectorPosition = topCandidate
    ? position(topCandidate, 'vector')
    : null;
  const topFuzzyPosition = topCandidate
    ? position(topCandidate, 'fuzzy')
    : null;
  const topRrf = topCandidate
    ? topCandidate.rrf_score ?? topCandidate.final_score
    : null;

  return (
    <section className="final-ranked-evidence">
      <header>
        <div>
          <span className="section-label">Final ranked evidence</span>
          <h2>What this retrieval returned first</h2>
          <p>
            The persisted final order is the retrieval outcome. The Agent uses
            this evidence to produce a separate cited answer.
          </p>
        </div>
        <span className={`status-pill ${runId ? 'ready' : 'pending'}`}>
          {runId ? `run ${compactId(runId)}` : 'awaiting retrieval'}
        </span>
      </header>

      {topCandidate && topEvidence ? (
        <>
          <button
            type="button"
            className={`final-ranked-primary ${
              topCandidate.evidence_id === selectedEvidenceId ? 'selected' : ''
            }`}
            data-kind={topEvidence.evidence_kind || 'unknown'}
            onClick={() => onSelect(topCandidate)}
          >
            <span className="final-rank-marker">
              <small>Rank</small>
              <strong>1</strong>
            </span>
            <span
              className={`kind-glyph kind-${
                topEvidence.evidence_kind || 'unknown'
              }`}
            >
              <KindIcon kind={topEvidence.evidence_kind} size={19} />
            </span>
            <span className="final-ranked-copy">
              <span className="final-ranked-identity">
                <strong>{topEvidence.external_key || 'Unknown evidence'}</strong>
                <span className={`tier-chip tier-${matchTier(topCandidate)}`}>
                  {tierLabel(matchTier(topCandidate))}
                </span>
              </span>
              <b>{topEvidence.title || 'Untitled evidence'}</b>
              <span>
                {topEvidence.snippet || 'No visible evidence excerpt.'}
              </span>
            </span>
            <span className="final-ranked-scores">
              <span>
                {reranked ? 'Model rerank' : 'Aurora RRF'}
                <b>
                  {reranked
                    ? score(topCandidate.rerank_score, 3)
                    : score(
                        topCandidate.rrf_score ?? topCandidate.final_score,
                        5,
                      )}
                </b>
              </span>
              {reranked ? (
                <span>
                  Aurora RRF
                  <b>
                    {score(
                      topCandidate.rrf_score ?? topCandidate.final_score,
                      5,
                    )}
                  </b>
                </span>
              ) : null}
              <ChevronRight size={17} aria-hidden="true" />
            </span>
          </button>

          <div className="final-ranked-why">
            <span className="section-label">Why this ranked first</span>
            <p>
              {topCandidate.explanation?.exact_identifier
                ? `${topEvidence.external_key} entered the exact-identifier tier before fused candidates.`
                : 'This evidence entered the fused candidate set from the active retrieval arms.'}{' '}
              {reranked && topCandidate.rerank_score != null
                ? `Cohere kept it at final rank 1; Aurora RRF ${score(topRrf, 5)} remains persisted separately.`
                : `Weighted RRF combined its arm positions into ${score(topRrf, 5)}.`}
            </p>
            <div className="final-ranked-why-signals">
              {topCandidate.explanation?.exact_identifier ? (
                <span>
                  <CircleDot size={11} />
                  exact tier
                </span>
              ) : null}
              {topTextPosition !== null ? (
                <span>text #{topTextPosition}</span>
              ) : null}
              {topVectorPosition !== null ? (
                <span>semantic #{topVectorPosition}</span>
              ) : null}
              {topFuzzyPosition !== null ? (
                <span>fuzzy #{topFuzzyPosition}</span>
              ) : null}
              <span>RRF {score(topRrf, 5)}</span>
              {reranked && topCandidate.rerank_score != null ? (
                <span>Cohere {score(topCandidate.rerank_score, 3)}</span>
              ) : null}
            </div>
          </div>

          {candidates.length > 1 ? (
            <div className="final-ranked-rest">
              <div className="final-ranked-rest-head">
                <span>Next in final order</span>
                <small>{candidates.length - 1} additional candidates</small>
              </div>
              <div className="final-ranked-rest-list">
                {candidates.slice(1).map((candidate, index) => (
                  <CandidateRow
                    key={`${candidate.evidence_id}-${index}`}
                    candidate={candidate}
                    rank={candidate.result_rank || index + 2}
                    selected={candidate.evidence_id === selectedEvidenceId}
                    diagnostic={
                      reranked
                        ? score(candidate.rerank_score, 3)
                        : score(
                            candidate.rrf_score ?? candidate.final_score,
                            5,
                          )
                    }
                    onSelect={() => onSelect(candidate)}
                  />
                ))}
              </div>
            </div>
          ) : null}
        </>
      ) : (
        <Empty
          icon={<FileSearch size={20} />}
          title="Run retrieval to rank evidence"
          detail="The final persisted order will appear here before the arm diagnostics."
        />
      )}
    </section>
  );
}

function RetrievalArm({
  title,
  subtitle,
  candidates,
  selectedEvidenceId,
  diagnostic,
  onSelect,
  planArm,
  onInspectPlan,
  planBusy = false,
  emptyTitle = 'No candidates',
  emptyDetail = 'The arm returned an empty set.',
  fused = false,
}: {
  title: string;
  subtitle: string;
  candidates: Candidate[];
  selectedEvidenceId: string | null;
  diagnostic: (candidate: Candidate) => ReactNode;
  onSelect: (candidate: Candidate) => void;
  planArm?: QueryPlanResponse['arm'];
  onInspectPlan?: (arm: QueryPlanResponse['arm']) => void;
  planBusy?: boolean;
  emptyTitle?: string;
  emptyDetail?: string;
  fused?: boolean;
}) {
  return (
    <section className={`retrieval-arm ${fused ? 'fused' : ''}`}>
      <header>
        <div>
          <span className="section-label">{title}</span>
          <p>{subtitle}</p>
        </div>
        <div className="arm-header-actions">
          {planArm && onInspectPlan ? (
            <button
              type="button"
              className="arm-plan-button"
              onClick={() => onInspectPlan(planArm)}
              disabled={planBusy}
              title={`Inspect the ${title.toLowerCase()} query plan`}
            >
              {planBusy ? (
                <LoaderCircle className="spin" size={12} />
              ) : (
                <Code2 size={12} />
              )}
              Plan
            </button>
          ) : null}
          <span className="count-badge">{candidates.length}</span>
        </div>
      </header>
      <div className="arm-list">
        {!candidates.length ? (
          <Empty
            icon={<FileSearch size={18} />}
            title={emptyTitle}
            detail={emptyDetail}
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

const PLAN_ARM_LABELS: Record<QueryPlanResponse['arm'], string> = {
  lexical: 'Text',
  semantic: 'Semantic',
  fuzzy: 'Fuzzy',
};

function QueryPlanDrawer({
  plan,
  arm,
  busy,
  engineVersion,
  onSelectArm,
  onRefresh,
  onClose,
}: {
  plan: QueryPlanResponse | null;
  arm: QueryPlanResponse['arm'];
  busy: boolean;
  engineVersion?: string;
  onSelectArm: (arm: QueryPlanResponse['arm']) => void;
  onRefresh: () => void;
  onClose: () => void;
}) {
  const current = plan?.arm === arm ? plan : null;
  const hnswState =
    current?.uses_hnsw === true
      ? 'HNSW selected'
      : current?.uses_hnsw === false
        ? 'HNSW bypassed'
        : 'Not applicable';

  return (
    <section
      className="query-plan-drawer"
      aria-label={`${PLAN_ARM_LABELS[arm]} query plan`}
    >
      <header className="query-plan-head">
        <div>
          <span className="section-label">Live query plan</span>
          <h2>{PLAN_ARM_LABELS[arm]} arm execution</h2>
          <p>
            EXPLAIN (ANALYZE, BUFFERS) over the canonical arm SQL under the
            active query and filters.
          </p>
        </div>
        <div className="query-plan-head-actions">
          <span className="status-pill ready">
            {engineRelease(engineVersion) || 'live database'}
          </span>
          <button
            type="button"
            className="icon-close"
            onClick={onClose}
            title="Close query plan"
            aria-label="Close query plan"
          >
            <X size={16} />
          </button>
        </div>
      </header>

      <div className="query-plan-toolbar">
        <div className="segmented" aria-label="Retrieval arm plan">
          {(['lexical', 'semantic', 'fuzzy'] as const).map((candidateArm) => (
            <button
              key={candidateArm}
              type="button"
              className={arm === candidateArm ? 'active' : ''}
              onClick={() => onSelectArm(candidateArm)}
              disabled={busy}
            >
              {PLAN_ARM_LABELS[candidateArm]}
            </button>
          ))}
        </div>
        <span className="query-plan-context">
          <b>Scope</b>
          {current?.cluster_id || 'all clusters'}
        </span>
        <button
          type="button"
          className="text-command"
          onClick={onRefresh}
          disabled={busy}
        >
          {busy ? (
            <LoaderCircle className="spin" size={14} />
          ) : (
            <RefreshCw size={14} />
          )}
          Refresh plan
        </button>
      </div>

      {busy || !current ? (
        <Empty
          icon={<LoaderCircle className={busy ? 'spin' : ''} size={20} />}
          title={busy ? 'Explaining the live arm' : 'Plan unavailable'}
          detail="The drawer will render only observed database output."
        />
      ) : (
        <>
          <div className="query-plan-runtime">
            <span>
              Planning
              <strong>{score(current.plan['Planning Time'], 3)} ms</strong>
            </span>
            <span>
              Execution
              <strong>{score(current.plan['Execution Time'], 3)} ms</strong>
            </span>
            <span>
              Scan nodes
              <strong>{current.scans.length}</strong>
            </span>
            <span>
              Semantic path
              <strong>{hnswState}</strong>
            </span>
          </div>

          {current.abstained ? (
            <div className="plan-abstention" role="note">
              <CircleDot size={16} />
              <span>
                <strong>Arm abstained</strong>
                {current.abstain_reason}
              </span>
            </div>
          ) : null}

          <div className="query-plan-body">
            <section className="query-plan-scans">
              <header>
                <span className="section-label">Observed scan path</span>
                <small>actual values per loop</small>
              </header>
              <div className="plan-scan-head" aria-hidden="true">
                <span>Node / relation</span>
                <span>Index</span>
                <span>Rows · loops</span>
                <span>Time</span>
                <span>Buffers</span>
              </div>
              {current.scans.length ? (
                current.scans.map((scan, index) => {
                  const conditions = [
                    scan.index_cond ? `Index: ${scan.index_cond}` : '',
                    scan.recheck_cond ? `Recheck: ${scan.recheck_cond}` : '',
                    scan.filter ? `Filter: ${scan.filter}` : '',
                  ].filter(Boolean);
                  return (
                    <div
                      className="plan-scan-row"
                      key={`${scan.node_type}-${scan.index}-${index}`}
                    >
                      <span className="plan-node-index">{index + 1}</span>
                      <span className="plan-node-name">
                        <strong>{scan.node_type}</strong>
                        <small>{scan.relation || 'working set'}</small>
                      </span>
                      <code>{scan.index || '—'}</code>
                      <span>
                        {scan.actual_rows} · {scan.loops}
                      </span>
                      <span>{score(scan.actual_total_time_ms, 3)} ms</span>
                      <span>
                        {scan.shared_hit_blocks} hit · {scan.shared_read_blocks}{' '}
                        read
                      </span>
                      {conditions.length ? (
                        <small className="plan-node-conditions">
                          {conditions.join(' · ')}
                          {scan.rows_removed_by_filter
                            ? ` · ${scan.rows_removed_by_filter} rows removed`
                            : ''}
                        </small>
                      ) : null}
                    </div>
                  );
                })
              ) : (
                <Empty
                  icon={<Activity size={18} />}
                  title="No scan nodes executed"
                  detail={
                    current.abstained
                      ? 'The arm exited before an indexed probe was required.'
                      : 'The live plan returned no scan nodes.'
                  }
                />
              )}
            </section>

            <aside className="query-plan-inspector">
              <section>
                <span className="section-label">Planner observation</span>
                <p>{current.planner_summary}</p>
                <VerifyAffordance descriptor={current._verify_sql} />
              </section>
              <section className="plan-runtime-sql">
                <header>
                  <span>Executed SQL shape</span>
                  <small>backend generated</small>
                </header>
                <pre>{current.runtime_sql}</pre>
              </section>
            </aside>
          </div>
        </>
      )}
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
  const rerankVisible = candidates.some(
    (candidate) => candidate.rerank_score != null,
  );

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
            {rerankVisible ? (
              <th>
                Cohere rerank
                <small>post-fusion diagnostic</small>
              </th>
            ) : null}
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
                {rerankVisible ? (
                  <td className="score-value">
                    {score(candidate.rerank_score, 3)}
                  </td>
                ) : null}
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
  dirty,
  advancedOpen,
  onToggleAdvanced,
  onChange,
  onRun,
  busy,
}: {
  controls: Controls;
  dirty: boolean;
  advancedOpen: boolean;
  onToggleAdvanced: () => void;
  onChange: <K extends keyof Controls>(key: K, value: Controls[K]) => void;
  onRun: () => void;
  busy: boolean;
}) {
  return (
    <section className="fusion-controls">
      <header>
        <div className="fusion-control-title">
          <span className="section-label">Fusion controls</span>
          <small className={`control-state ${dirty ? 'pending' : ''}`}>
            {dirty ? 'Draft differs from run' : 'Matches current run'}
          </small>
        </div>
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
      <label className="fusion-rerank-control">
        <span className="rerank-control-copy">
          <strong>Cohere rerank</strong>
          <small>
            Optional post-fusion ordering; Aurora RRF remains persisted
          </small>
        </span>
        <span className="toggle-control">
          <span>{controls.rerank ? 'On' : 'Off'}</span>
          <input
            type="checkbox"
            checked={controls.rerank}
            disabled={busy}
            onChange={(event) => onChange('rerank', event.target.checked)}
          />
          <i aria-hidden="true" />
        </span>
      </label>
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
    useState<DiagnoseTab>('results');
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
  const [planOpen, setPlanOpen] = useState(false);
  const [armsOpen, setArmsOpen] = useState(false);
  const [candidateReceiptOpen, setCandidateReceiptOpen] = useState(false);
  const [graphDepth, setGraphDepth] = useState(2);
  const [graphEdgeMode, setGraphEdgeMode] =
    useState<'canonical' | 'all'>('all');
  const [runId, setRunId] = useState('');
  // Gate the URL-sync effect until the initial hash has been applied, so the
  // first render cannot overwrite a /proof/{run_id} deep link before it loads.
  const [routerHydrated, setRouterHydrated] = useState(false);
  const [selectedTool, setSelectedTool] =
    useState<(typeof TOOL_NAMES)[number]>('search_evidence');
  const [agentContractOpen, setAgentContractOpen] = useState(false);
  const [busy, setBusy] = useState<
    'search' | 'answer' | 'run' | 'evaluation' | 'plan' | null
  >(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [agentStreamState, setAgentStreamState] =
    useState<AgentStreamState>('blocked');
  const [streamingAnswer, setStreamingAnswer] = useState('');
  const [agentTrace, setAgentTrace] = useState<AgentTraceEvent[]>([]);
  const [streamCitations, setStreamCitations] = useState<Citation[]>([]);
  const [visibleCitationCount, setVisibleCitationCount] = useState(0);
  const [agentMetadata, setAgentMetadata] = useState<AgentMetadata | null>(null);
  const [agentCommentary, setAgentCommentary] = useState('');
  const [agentUsage, setAgentUsage] = useState<AgentUsage | null>(null);
  const [agentLatencyMs, setAgentLatencyMs] = useState<number | null>(null);
  const [homeQueryText, setHomeQueryText] = useState('');
  const [homeTyping, setHomeTyping] = useState(true);
  const [homeReceiptLoading, setHomeReceiptLoading] = useState(true);
  const [fusionRunRequest, setFusionRunRequest] = useState(0);
  const [navCollapsed, setNavCollapsed] = useState(
    () => window.localStorage.getItem('verity-nav-collapsed') === 'true',
  );
  const homeTypingInterrupted = useRef(false);
  const homeQueryInput = useRef<HTMLInputElement>(null);
  const lastCompletedSearchKey = useRef<string | null>(null);
  const processedFusionRunRequest = useRef(0);

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
    window.localStorage.setItem('verity-nav-collapsed', String(navCollapsed));
  }, [navCollapsed]);

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
    // Apply the initial deep link (SPEC 6.0). Navigation is synchronous; the run
    // to load is chosen below so a /proof/{run_id} link wins over latest-run.
    const initialRoute = parseRoute(window.location.hash);
    if (initialRoute.surface === 'retrieval' && initialRoute.preset) {
      const preset = PRESETS.find(
        (entry) => entry.presetKey === initialRoute.preset,
      );
      if (preset) {
        setControls((current) => ({
          ...current,
          query: preset.query,
          mode: preset.mode,
          kind: preset.kind,
          clusterId: preset.clusterId,
        }));
      }
    }
    if (initialRoute.surface === 'agent' && initialRoute.principal) {
      setControl('supportLead', initialRoute.principal === 'support-lead');
    }
    goTo(initialRoute.surface as Surface, initialRoute.lens);
    const deepLinkedRun =
      initialRoute.surface === 'proof' ? initialRoute.runId : undefined;
    void (async () => {
      try {
        const targetRun =
          deepLinkedRun ??
          (await api<{ run_id: string }>('/v1/runs/latest')).run_id;
        if (!cancelled) await loadRun(targetRun);
      } catch {
        // A new environment can be ready before it has a cited receipt.
      } finally {
        if (!cancelled) {
          setHomeReceiptLoading(false);
          setRouterHydrated(true);
        }
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
      case 'retrieval': {
        const tab: DiagnoseTab = lens === 'fusion' ? 'fusion' : 'results';
        setModule('retrieve');
        setDiagnoseTab(tab);
        setControl('supportLead', false);
        if (tab === 'fusion') {
          setPlanOpen(false);
          setFusionRunRequest((current) => current + 1);
        }
        break;
      }
      case 'agent':
        setModule('prove');
        setProveTab(lens === 'graph' ? 'graph' : 'answer');
        break;
      case 'proof':
        setModule('prove');
        setProveTab(
          lens === 'replay'
            ? 'replay'
            : lens === 'timeline'
              ? 'timeline'
              : 'receipt',
        );
        break;
      case 'corpus':
        setModule('corpus');
        break;
      case 'evaluation':
        setModule('prove');
        setProveTab('evaluation');
        break;
      case 'health':
        setModule('health');
        break;
    }
  }

  // Which primary surface + lens is live, derived from legacy state so the nav
  // highlight and the render tree never disagree.
  const activeSurface: Surface =
    module === 'home'
      ? 'overview'
      : module === 'retrieve'
        ? 'retrieval'
        : module === 'corpus'
            ? 'corpus'
            : module === 'health'
              ? 'health'
              : proveTab === 'evaluation'
                ? 'evaluation'
                : proveTab === 'receipt' ||
                    proveTab === 'replay' ||
                    proveTab === 'timeline'
                  ? 'proof'
                  : 'agent';
  const activeLens: string =
    activeSurface === 'retrieval'
      ? diagnoseTab
      : activeSurface === 'agent'
        ? proveTab
        : activeSurface === 'proof'
          ? proveTab
          : '';

  // Route params derived from live state so the URL reflects them (SPEC 6.0).
  // preset is inferred by exact query match — lossy the instant a user edits the
  // query, which is correct: an edited query is no longer a named preset.
  const activePreset: PresetKey | undefined =
    activeSurface === 'retrieval'
      ? PRESETS.find(
          (preset) =>
            preset.presetKey !== undefined && preset.query === controls.query,
        )?.presetKey
      : undefined;
  const activePrincipal: PrincipalKey =
    controls.supportLead ? 'support-lead' : 'workshop';

  // Apply a parsed route to live state. surface/lens go through goTo (the single
  // navigation writer); preset/principal set controls; a /proof/{run_id} loads
  // that run. Called on mount, on back/forward, and never during state->URL sync.
  function applyRoute(route: Route) {
    if (route.surface === 'retrieval' && route.preset) {
      const preset = PRESETS.find((entry) => entry.presetKey === route.preset);
      if (preset) {
        setControls((current) => ({
          ...current,
          query: preset.query,
          mode: preset.mode,
          kind: preset.kind,
          clusterId: preset.clusterId,
        }));
      }
    }
    if (route.surface === 'agent' && route.principal) {
      setControl('supportLead', route.principal === 'support-lead');
    }
    if (route.surface === 'proof' && route.runId && route.runId !== runId) {
      void loadRun(route.runId);
    }
    goTo(route.surface as Surface, route.lens);
  }

  // State -> URL sync (SPEC 6.0). Once hydrated, mirror the live surface, lens,
  // and route params into the hash via replaceState (which does not fire
  // hashchange, so this cannot feedback-loop with the hashchange listener).
  useEffect(() => {
    if (!routerHydrated) return;
    const route: Route = { surface: activeSurface as RouteSurface };
    if (activeLens) route.lens = activeLens;
    if (activeSurface === 'retrieval' && activePreset) {
      route.preset = activePreset;
    }
    if (activeSurface === 'agent') route.principal = activePrincipal;
    if (activeSurface === 'proof' && runId) route.runId = runId;
    const nextHash = formatRoute(route);
    if (window.location.hash !== nextHash) {
      window.history.replaceState(null, '', nextHash);
    }
  }, [
    routerHydrated,
    activeSurface,
    activeLens,
    activePreset,
    activePrincipal,
    runId,
  ]);

  // URL -> state on back/forward. hashchange fires only on user navigation and
  // manual edits, never on our own replaceState, so applying the parsed route
  // here is safe. The listener reads applyRoute through a ref so it always sees
  // current state (runId, queryPlan) instead of a stale mount-time closure.
  const applyRouteRef = useRef(applyRoute);
  applyRouteRef.current = applyRoute;
  useEffect(() => {
    function onHashChange() {
      applyRouteRef.current(parseRoute(window.location.hash));
    }
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);

  function interruptHomeTypewriter() {
    if (!homeTyping) return;
    homeTypingInterrupted.current = true;
    setHomeTyping(false);
    setControl('query', homeQueryText);
  }

  function searchPayload(sourceControls: Controls = controls) {
    return {
      query: sourceControls.query,
      mode: sourceControls.mode,
      kinds:
        sourceControls.kind === 'all' ? null : [sourceControls.kind],
      cluster_id: sourceControls.clusterId || null,
      incident_id: null,
      environment: sourceControls.environment || null,
      limit: sourceControls.limit,
      candidate_pool: sourceControls.candidatePool,
      rrf_k: sourceControls.rrfK,
      w_text: sourceControls.textWeight,
      w_vector: sourceControls.vectorWeight,
      w_trgm: sourceControls.fuzzyWeight,
      fuzzy_threshold: sourceControls.fuzzyThreshold,
      ef_search: sourceControls.efSearch,
      iterative_scan: 'relaxed_order',
      rerank: sourceControls.rerank,
      principal: {
        scopes: ['workshop'],
        principals: sourceControls.supportLead ? ['support-lead'] : [],
      },
    };
  }

  async function loadRun(id: string | undefined, requestKey?: string) {
    const runKey = encodeURIComponent((id || '').trim());
    if (!runKey) return;
    if (!requestKey) lastCompletedSearchKey.current = null;
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
      if (requestKey) lastCompletedSearchKey.current = requestKey;
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
    setPlanOpen(true);
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

  function openQueryPlan(arm: QueryPlanResponse['arm']) {
    setModule('retrieve');
    setDiagnoseTab('results');
    setControl('supportLead', false);
    setArmsOpen(true);
    setPlanOpen(true);
    void loadQueryPlan(arm);
  }

  async function runSearch(
    event?: FormEvent,
    requestedControls: Controls = controls,
  ) {
    event?.preventDefault();
    if (!requestedControls.query.trim()) return;
    const requestKey = retrievalRequestKey(requestedControls);
    setBusy('search');
    setError(null);
    setAnswer(null);
    setPlanOpen(false);
    setArmsOpen(false);
    setCandidateReceiptOpen(false);
    try {
      const response = await api<SearchResponse>('/v1/search', {
        method: 'POST',
        body: JSON.stringify(searchPayload(requestedControls)),
      });
      const ranked = response.results.map((candidate, index) => ({
        ...candidate,
        result_rank: index + 1,
      }));
      setCandidates(ranked);
      setRunId(response.run_id);
      setSelectedEvidenceId(ranked[0]?.evidence_id || null);
      await loadRun(response.run_id, requestKey);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Search unavailable');
    } finally {
      setBusy(null);
    }
  }

  async function beginInvestigation() {
    const baselineQuery = homeQueryText.trim();
    if (!baselineQuery) return;
    const baselineControls = {
      ...controls,
      query: baselineQuery,
      supportLead: false,
    };
    setControls(baselineControls);
    setAgentStreamState('blocked');
    setStreamingAnswer('');
    setAgentTrace([]);
    setStreamCitations([]);
    setVisibleCitationCount(0);
    setAgentMetadata(null);
    setAgentCommentary('');
    setAgentUsage(null);
    setAgentLatencyMs(null);
    setModule('retrieve');
    setDiagnoseTab('results');
    await runSearch(undefined, baselineControls);
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
    setVisibleCitationCount(0);
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
          const text = event.text || '';
          if (reducedMotion) {
            setStreamingAnswer((current) => current + text);
          } else {
            for (let offset = 0; offset < text.length; offset += 3) {
              const fragment = text.slice(offset, offset + 3);
              setStreamingAnswer((current) => current + fragment);
              await new Promise<void>((resolve) =>
                window.setTimeout(resolve, 14),
              );
            }
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
        throw new Error('The Strands event stream ended before a final run record.');
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
    setCandidateReceiptOpen(true);
  }

  const activeEvidence = selectedCandidate
    ? snapshot(selectedCandidate)
    : evidenceDetail?.evidence || null;
  const latestBuild = diagnostics?.recent_builds[0];
  const embeddingModel =
    health?.embedding_spaces[0]?.embedding_model || 'checking';
  // The final outcome describes the run that produced the displayed candidates,
  // so its state reads from the persisted receipt, not the pending toggle.
  // Rerank is a post-fusion ordering stage: with it off, final order == fused.
  const finalReranked = Boolean(receipt?.run.rerank_applied);
  const receiptRerankRequested = Boolean(receipt?.run.rerank_model);
  const finalOrderIsFused = candidates.length ? isFusedOrder(candidates) : true;
  const appliedControls: Controls = {
    ...controls,
    query: receipt?.run.query_text || controls.query,
    candidatePool: receipt?.run.candidate_pool || controls.candidatePool,
    rrfK: receipt?.run.rrf_k ?? controls.rrfK,
    textWeight: receipt?.run.text_weight ?? controls.textWeight,
    vectorWeight: receipt?.run.vector_weight ?? controls.vectorWeight,
    fuzzyWeight: receipt?.run.fuzzy_weight ?? controls.fuzzyWeight,
    fuzzyThreshold:
      receipt?.run.fuzzy_threshold ?? controls.fuzzyThreshold,
    efSearch: receipt?.run.hnsw_ef_search ?? controls.efSearch,
    rerank: receipt ? receiptRerankRequested : controls.rerank,
  };
  const finalResultCandidates = candidates.slice(0, appliedControls.limit);
  const queryDraftDirty = Boolean(
    receipt && controls.query !== receipt.run.query_text,
  );
  const fusionDraftDirty = Boolean(
    receipt &&
      (controls.rrfK !== receipt.run.rrf_k ||
        controls.textWeight !== receipt.run.text_weight ||
        controls.vectorWeight !== receipt.run.vector_weight ||
        controls.fuzzyWeight !== receipt.run.fuzzy_weight ||
        controls.fuzzyThreshold !== receipt.run.fuzzy_threshold ||
        controls.candidatePool !== receipt.run.candidate_pool ||
        controls.efSearch !==
          (receipt.run.hnsw_ef_search ?? controls.efSearch) ||
        controls.rerank !== receiptRerankRequested),
  );
  const retrievalDraftDirty = queryDraftDirty || fusionDraftDirty;

  useEffect(() => {
    if (
      !routerHydrated ||
      module !== 'retrieve' ||
      diagnoseTab !== 'fusion' ||
      !controls.query.trim() ||
      busy !== null ||
      processedFusionRunRequest.current >= fusionRunRequest
    ) {
      return;
    }

    processedFusionRunRequest.current = fusionRunRequest;
    const requestKey = retrievalRequestKey(controls);
    if (lastCompletedSearchKey.current === requestKey) return;
    void runSearch(undefined, controls);
  }, [
    routerHydrated,
    module,
    diagnoseTab,
    controls,
    busy,
    fusionRunRequest,
  ]);

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
  // The /timeline payload is already scoped to this run's graph nodes (the
  // traverse_links closed component of the cited set) and ordered by
  // (occurred_at, external_key), so the array index is the true chronological
  // sequence. Build the lane x day grid straight from it — no client-side
  // re-filter or cap that would silently drop cited evidence.
  const timelineGrid = useMemo(
    () => buildTimelineGrid(timeline?.events || []),
    [timeline],
  );
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
  const persistedAnswerLoaded = Boolean(
    agentStreamState === 'blocked' &&
      answer?.answer_text &&
      answer.citations.length,
  );
  const agentDisplayState: AgentStreamState = persistedAnswerLoaded
    ? 'complete'
    : agentStreamState;
  const answerCitations =
    agentDisplayState === 'complete'
      ? streamCitations.length
        ? streamCitations
        : answer?.citations || []
      : agentStreamState === 'streaming'
        ? streamCitations
        : [];
  const visibleAnswerCitations = persistedAnswerLoaded
    ? answerCitations
    : answerCitations.slice(0, visibleCitationCount);
  useEffect(() => {
    if (persistedAnswerLoaded) {
      setVisibleCitationCount(answerCitations.length);
      return;
    }
    if (!streamCitations.length) {
      setVisibleCitationCount(0);
      return;
    }
    if (visibleCitationCount >= streamCitations.length) return;
    const delay = window.setTimeout(
      () =>
        setVisibleCitationCount((current) =>
          Math.min(current + 1, streamCitations.length),
        ),
      visibleCitationCount === 0 ? 120 : 260,
    );
    return () => window.clearTimeout(delay);
  }, [
    answerCitations.length,
    persistedAnswerLoaded,
    streamCitations.length,
    visibleCitationCount,
  ]);
  const runbookRecovered = answerCitations.some(
    (citation) => citation.external_key === 'RB-017',
  );
  const citedEvidenceKeys = new Set(
    answerCitations.map((citation) => citation.external_key),
  );
  const answerCoverageComplete =
    [...citedEvidenceKeys].some((key) => key.startsWith('CHG-')) &&
    [...citedEvidenceKeys].some((key) => key.startsWith('LOCK-')) &&
    [...citedEvidenceKeys].some((key) => key.startsWith('CASE-')) &&
    citedEvidenceKeys.has('RB-017');
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
  return (
    <div className={`verity-shell ${navCollapsed ? 'nav-collapsed' : ''}`}>
      <aside className="side-rail">
        <div className="side-rail-head">
          <button
            className="brand"
            type="button"
            onClick={() => setModule('home')}
            aria-label="Open Verity overview"
            title={navCollapsed ? 'Open Verity overview' : undefined}
          >
            <VerityMark />
            <span className="brand-copy">
              <strong>{APP_NAME}</strong>
              <small>incident-evidence workbench</small>
            </span>
          </button>
          <button
            type="button"
            className="side-rail-toggle"
            onClick={() => setNavCollapsed((current) => !current)}
            aria-label={navCollapsed ? 'Expand navigation' : 'Collapse navigation'}
            title={navCollapsed ? 'Expand navigation' : 'Collapse navigation'}
          >
            {navCollapsed ? (
              <PanelLeftOpen size={17} />
            ) : (
              <PanelLeftClose size={17} />
            )}
          </button>
        </div>

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
                  title={navCollapsed ? label : undefined}
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
              title={navCollapsed ? label : undefined}
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
            <span className="section-label">Active retrieval run</span>
            {runId ? (
              <button
                type="button"
                className="run-breadcrumb"
                onClick={() => goTo('proof', 'receipt')}
                title="Open this run record"
              >
                {compactId(runId)}
              </button>
            ) : (
              <strong>Not started</strong>
            )}
            <code>
              {health?.current_documents?.toLocaleString() || '—'} documents ·{' '}
              {health?.drift_issues ?? '—'} drift
            </code>
          </section>
        </div>
      </aside>

      <div className="app-column">
        {module === 'home' ? <LiveBanner health={health} /> : null}
        {module !== 'home' &&
        module !== 'retrieve' &&
        activeSurface !== 'agent' ? (
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
                  {' '}traces retrieval
                  <em className="home-proof">to cited proof.</em>
                </h1>
                <p>
                  Inspect exact and full-text, semantic, and fuzzy candidates;
                  weighted RRF; authoritative relationship traversal; and the
                  persisted run record behind every citation.
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
                      : 'No cited run record is available'
                }
              >
                <svg
                  className="home-threads"
                  viewBox="0 0 620 520"
                  role="img"
                  aria-label={
                    homeEvidenceState === 'ready'
                      ? `${homeCitations.length} citations connected to the latest answer`
                      : 'Evidence-thread frame awaiting a cited run'
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
                        ? 'loading run'
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
                      : 'no active run'}
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
                                ? 'Cited evidence without a score in the active run'
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
                        ? 'Loading latest cited run'
                        : 'No cited run yet'}
                    </div>
                  ) : null}
                </div>
              </div>

              <form
                className="investigation-query home-query"
                onSubmit={(event) => {
                  event.preventDefault();
                  void beginInvestigation();
                }}
              >
                <InvestigationQueryField
                  inputRef={homeQueryInput}
                  value={homeQueryText}
                  readOnly={homeTyping}
                  title={homeQueryText}
                  onFocus={interruptHomeTypewriter}
                  onChange={(query) => {
                    setHomeQueryText(query);
                    setControl('query', query);
                  }}
                  ariaLabel="Incident question"
                />
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
                  onClick={() => openQueryPlan('semantic')}
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
                  <strong>Cited run record</strong>
                  <small>{runId ? compactId(runId) : 'awaiting run'}</small>
                </span>
              </div>
            </section>
          </section>
        ) : null}
        {module === 'retrieve' ? (
          <section className="module-screen retrieval-screen">
            <header className="module-heading">
              <div>
                <span className="module-kicker">
                  Retrieval · {diagnoseTab === 'results' ? 'Results' : 'Fusion'}
                </span>
                <h1>
                  {diagnoseTab === 'results' ? (
                    <>
                      Inspect the final rank, <em>then each signal.</em>
                    </>
                  ) : (
                    <>
                      Weighted reciprocal <em>rank fusion.</em>
                    </>
                  )}
                </h1>
                <p className="module-deck">
                  {diagnoseTab === 'results'
                    ? 'Start with the persisted retrieval outcome. Open the ranking diagnostics only when you need to trace how each arm contributed.'
                    : 'Only integer positions enter weighted RRF. Raw arm values stay diagnostic, and optional Cohere reranking is a separate downstream stage.'}
                </p>
              </div>
            </header>

            {diagnoseTab === 'results' ? (
              <>
                <form
                  className="investigation-query retrieval-query-panel"
                  onSubmit={runSearch}
                >
                  <InvestigationQueryField
                    value={controls.query}
                    onChange={(query) => {
                      setControl('query', query);
                      if (query !== answer?.question) {
                        setAnswer(null);
                        setAgentStreamState('blocked');
                        setStreamingAnswer('');
                        setAgentTrace([]);
                        setStreamCitations([]);
                        setVisibleCitationCount(0);
                      }
                    }}
                    ariaLabel="Evidence query"
                  />
                  <button
                    type="submit"
                    className="run-button retrieval-run-button"
                    disabled={busy !== null || !controls.query.trim()}
                  >
                    {busy === 'search' || busy === 'run' ? (
                      <LoaderCircle className="spin" size={17} />
                    ) : (
                      <Play size={16} />
                    )}
                    Run retrieval
                  </button>
                  <div className="retrieval-query-footer">
                    <div className="retrieval-query-options">
                      <span>Examples</span>
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
                    <div className="retrieval-query-status">
                      <label className="results-rerank-control">
                        <strong>Cohere rerank</strong>
                        <span className="toggle-control">
                          <span>{controls.rerank ? 'On' : 'Off'}</span>
                          <input
                            type="checkbox"
                            checked={controls.rerank}
                            disabled={busy !== null}
                            aria-label="Use Cohere rerank for the next retrieval run"
                            onChange={(event) =>
                              setControl('rerank', event.target.checked)
                            }
                          />
                          <i aria-hidden="true" />
                        </span>
                      </label>
                      <span
                        className={`query-receipt-state ${
                          retrievalDraftDirty ? 'pending' : ''
                        }`}
                      >
                        {retrievalDraftDirty
                          ? 'Not run'
                          : runId
                            ? 'Current'
                            : 'No run'}
                      </span>
                    </div>
                  </div>
                </form>

                <FinalRankedEvidence
                  candidates={finalResultCandidates}
                  selectedEvidenceId={selectedEvidenceId}
                  reranked={finalReranked}
                  runId={runId}
                  onSelect={selectCandidate}
                />

                <section
                  className={`ranking-breakdown ${armsOpen ? 'open' : ''}`}
                >
                  <button
                    type="button"
                    className="ranking-breakdown-toggle"
                    aria-expanded={armsOpen}
                    onClick={() => {
                      const nextOpen = !armsOpen;
                      setArmsOpen(nextOpen);
                      if (!nextOpen) setPlanOpen(false);
                    }}
                  >
                    <span className="ranking-breakdown-icon">
                      <SlidersHorizontal size={18} />
                    </span>
                    <span>
                      <small>Ranking diagnostics</small>
                      <strong>How this ranking was built</strong>
                      <b>
                        Inspect text, semantic, and fuzzy positions before
                        weighted RRF and optional rerank.
                      </b>
                    </span>
                    <span className="ranking-breakdown-summary">
                      <b>
                        {textCandidates.length} text · {vectorCandidates.length}{' '}
                        semantic · {fuzzyCandidates.length} fuzzy
                      </b>
                      <ChevronRight size={18} aria-hidden="true" />
                    </span>
                  </button>

                  {armsOpen ? (
                    <div className="ranking-breakdown-body">
                      <div className="lab-note">
                        <strong>Read each arm independently.</strong>
                        <span>
                          Filters and ACLs execute before ranking. Only positions
                          enter fusion; raw values remain diagnostics.
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
                          planArm="lexical"
                          onInspectPlan={openQueryPlan}
                          planBusy={busy === 'plan' && planArm === 'lexical'}
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
                          planArm="semantic"
                          onInspectPlan={openQueryPlan}
                          planBusy={busy === 'plan' && planArm === 'semantic'}
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
                          planArm="fuzzy"
                          onInspectPlan={openQueryPlan}
                          planBusy={busy === 'plan' && planArm === 'fuzzy'}
                          emptyTitle={
                            receipt?.run.fuzzy_probe_tokens?.length
                              ? 'No trigram match passed'
                              : 'No unresolved identifier'
                          }
                          emptyDetail={
                            receipt?.run.fuzzy_probe_tokens?.length
                              ? 'The fuzzy probe returned no candidate above the active threshold.'
                              : 'This query needs no typo recovery, so the arm correctly contributes zero.'
                          }
                        />
                      </div>

                      <div className="retrieval-reading-line">
                        <span>
                          <ShieldCheck size={14} />
                          filters + ACL before ranking
                        </span>
                        <span>
                          <SlidersHorizontal size={14} />
                          positions enter RRF
                        </span>
                        <span
                          className={
                            candidates.length && !finalOrderIsFused
                              ? 'footnote-alert'
                              : ''
                          }
                        >
                          <FileCheck2 size={14} />
                          {finalReranked
                            ? 'rerank and RRF persisted separately'
                            : finalOrderIsFused
                              ? 'final order matches fused order'
                              : 'final order diverges from fused order'}
                        </span>
                      </div>

                      {planOpen ? (
                        <QueryPlanDrawer
                          plan={queryPlan}
                          arm={planArm}
                          busy={busy === 'plan'}
                          engineVersion={health?.engine_version}
                          onSelectArm={(arm) => void loadQueryPlan(arm)}
                          onRefresh={() => void loadQueryPlan(planArm)}
                          onClose={() => setPlanOpen(false)}
                        />
                      ) : null}
                    </div>
                  ) : null}
                </section>
              </>
            ) : null}

            {diagnoseTab === 'fusion' ? (
              <div className="fusion-page">
                <section className="fusion-query-context">
                  <div>
                    <span className="section-label">Selected retrieval query</span>
                    <p>{controls.query}</p>
                  </div>
                  <div>
                    <span
                      className={`status-pill ${
                        busy === 'search' || busy === 'run'
                          ? 'pending'
                          : retrievalDraftDirty
                            ? 'pending'
                            : 'ready'
                      }`}
                    >
                      {busy === 'search' || busy === 'run' ? (
                        <>
                          <LoaderCircle className="spin" size={12} />
                          running selected query
                        </>
                      ) : retrievalDraftDirty ? (
                        'selected query awaiting run'
                      ) : runId ? (
                        `run ${compactId(runId)}`
                      ) : (
                        'no retrieval run'
                      )}
                    </span>
                    <button
                      type="button"
                      className="text-command"
                      onClick={() => goTo('retrieval', 'results')}
                    >
                      <Search size={14} />
                      Edit query
                    </button>
                  </div>
                </section>

                <section className="fusion-overview">
                  <header>
                    <div>
                      <span className="section-label">Applied retrieval run</span>
                      <h2>Three rankings become one final order</h2>
                      <p>
                        Each arm contributes a position, not its raw score.
                        Weighted RRF converts those positions onto one comparable
                        scale.
                      </p>
                    </div>
                    <span className="status-pill ready">
                      {candidates.length} persisted candidates
                    </span>
                  </header>
                  <div className="fusion-flow">
                    <div className="fusion-flow-arms">
                      <span>
                        <b>Text</b>
                        <strong>{textCandidates.length}</strong>
                        <small>weight {appliedControls.textWeight}</small>
                      </span>
                      <span>
                        <b>Semantic</b>
                        <strong>{vectorCandidates.length}</strong>
                        <small>weight {appliedControls.vectorWeight}</small>
                      </span>
                      <span>
                        <b>Fuzzy</b>
                        <strong>{fuzzyCandidates.length}</strong>
                        <small>
                          {fuzzyCandidates.length
                            ? `weight ${appliedControls.fuzzyWeight}`
                            : 'abstained'}
                        </small>
                      </span>
                    </div>
                    <ArrowRight size={19} aria-hidden="true" />
                    <span className="fusion-flow-rrf">
                      <GitMerge size={18} />
                      <small>Weighted RRF</small>
                      <strong>k={appliedControls.rrfK}</strong>
                    </span>
                    <ArrowRight size={19} aria-hidden="true" />
                    <span className="fusion-flow-final">
                      <FileCheck2 size={18} />
                      <small>
                        {finalReranked ? 'Model-reranked final' : 'Aurora final'}
                      </small>
                      <strong>
                        {candidates[0]
                          ? snapshot(candidates[0]).external_key
                          : 'awaiting run'}
                      </strong>
                    </span>
                  </div>
                  <div className="rrf-formula-panel">
                    <div className="rrf-formula-intro">
                      <span className="section-label">Weighted RRF formula</span>
                      <small>For each evidence item d</small>
                    </div>
                    <div
                      className="rrf-formula-expression"
                      aria-label={`RRF of d equals ${appliedControls.textWeight} over ${appliedControls.rrfK} plus text rank, plus ${appliedControls.vectorWeight} over ${appliedControls.rrfK} plus semantic rank, plus ${appliedControls.fuzzyWeight} over ${appliedControls.rrfK} plus fuzzy rank`}
                    >
                      <strong>RRF(d)</strong>
                      <b>=</b>
                      <span className="rrf-fraction">
                        <i>{appliedControls.textWeight}</i>
                        <small>
                          {appliedControls.rrfK} + r<sub>text</sub>(d)
                        </small>
                      </span>
                      <b>+</b>
                      <span className="rrf-fraction">
                        <i>{appliedControls.vectorWeight}</i>
                        <small>
                          {appliedControls.rrfK} + r<sub>semantic</sub>(d)
                        </small>
                      </span>
                      <b>+</b>
                      <span className="rrf-fraction">
                        <i>{appliedControls.fuzzyWeight}</i>
                        <small>
                          {appliedControls.rrfK} + r<sub>fuzzy</sub>(d)
                        </small>
                      </span>
                    </div>
                    <div className="rrf-formula-notes">
                      <span>
                        <b>k={appliedControls.rrfK}</b> dampens rank outliers
                      </span>
                      <span>missing arm = 0</span>
                      <span>Cohere is not part of this formula</span>
                    </div>
                  </div>
                  <div className="applied-fusion-strip">
                    <span>
                      Applied weights
                      <b>
                        {appliedControls.textWeight}:
                        {appliedControls.vectorWeight}:
                        {appliedControls.fuzzyWeight}
                      </b>
                    </span>
                    <span>
                      RRF constant
                      <b>k={appliedControls.rrfK}</b>
                    </span>
                    <span>
                      Post-fusion rerank
                      <b>{finalReranked ? 'Cohere on' : 'off · RRF only'}</b>
                    </span>
                    <span>
                      Candidate pool
                      <b>{appliedControls.candidatePool}</b>
                    </span>
                  </div>
                </section>

                <div className="fusion-workspace">
                  <header className="fusion-tuning-head">
                    <div>
                      <span className="section-label">Tuning and implementation</span>
                      <h2>Change the policy, then create a new retrieval run</h2>
                    </div>
                    <small>
                      Draft controls never rewrite the displayed run.
                    </small>
                  </header>
                  <div className="fusion-workspace-controls">
                    <FusionControlPanel
                      controls={controls}
                      dirty={fusionDraftDirty}
                      advancedOpen={advancedOpen}
                      onToggleAdvanced={() =>
                        setAdvancedOpen((open) => !open)
                      }
                      onChange={setControl}
                      onRun={() => runSearch()}
                      busy={busy !== null}
                    />
                  </div>
                  <section className="sql-panel">
                    <header>
                      <span>Applied ranking rule</span>
                      <span>run {compactId(runId)}</span>
                    </header>
                    <pre>
                      <code>{`rrf_score =
  ${appliedControls.textWeight} / (${appliedControls.rrfK} + text_position)
+ ${appliedControls.vectorWeight} / (${appliedControls.rrfK} + vector_position)
+ ${appliedControls.fuzzyWeight} / (${appliedControls.rrfK} + trigram_position)

-- a missing arm contributes zero
-- exact identifiers form a deterministic tier above fused rows
ORDER BY
  match_tier,
  exact_identifier_position,
  rrf_score DESC
LIMIT ${appliedControls.limit};`}</code>
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
                        <span>
                          <i className="legend-text" /> full-text
                        </span>
                        <span>
                          <i className="legend-vector" /> semantic
                        </span>
                        <span>
                          <i className="legend-fuzzy" /> fuzzy
                        </span>
                      </div>
                    </header>
                    <FusionAnatomyTable
                      candidates={candidates}
                      controls={appliedControls}
                      onSelect={selectCandidate}
                    />
                  </section>
                ) : (
                  <div className="fusion-empty">
                    <Empty
                      icon={<GitMerge size={20} />}
                      title="Run retrieval to inspect fusion"
                    />
                  </div>
                )}

                <section className="fusion-reading-note">
                  <span className="section-label">How to read this table</span>
                  <p>
                    `ts_rank`, vector similarity, and trigram similarity use
                    unrelated scales, so RRF combines only integer positions.
                    Exact identifiers remain in a deterministic tier above fused
                    rows. Optional Cohere reranking may reorder the final pool
                    afterward, but it never overwrites Aurora&apos;s persisted
                    RRF score.
                  </p>
                </section>
              </div>
            ) : null}

            {candidateReceiptOpen && activeEvidence ? (
              <section className="candidate-drawer">
                <header>
                  <div>
                    <span className="section-label">Candidate details</span>
                    <h2>
                      {activeEvidence.external_key} · {activeEvidence.title}
                    </h2>
                  </div>
                  <button
                    type="button"
                    className="icon-close"
                    onClick={() => setCandidateReceiptOpen(false)}
                    title="Close candidate details"
                    aria-label="Close candidate details"
                  >
                    <X size={16} />
                  </button>
                </header>
                <div className="candidate-drawer-grid">
                  <div>
                    <p className="receipt-snippet">
                      {activeEvidence.snippet ||
                        evidenceDetail?.chunks[0]?.chunk_text ||
                        evidenceDetail?.evidence.body ||
                        'No visible chunk text.'}
                    </p>
                    <div className="signal-row">
                      <span>
                        TEXT
                        <b>
                          {selectedCandidate
                            ? position(selectedCandidate, 'text') || '—'
                            : '—'}
                        </b>
                      </span>
                      <span>
                        VECTOR
                        <b>
                          {selectedCandidate
                            ? position(selectedCandidate, 'vector') || '—'
                            : '—'}
                        </b>
                      </span>
                      <span>
                        FUZZY
                        <b>
                          {selectedCandidate
                            ? position(selectedCandidate, 'fuzzy') || '—'
                            : '—'}
                        </b>
                      </span>
                      <span>
                        AURORA RRF
                        <b>
                          {score(
                            selectedCandidate?.rrf_score ??
                              selectedCandidate?.final_score,
                            5,
                          )}
                        </b>
                      </span>
                      <span>
                        RERANK
                        <b>
                          {selectedCandidate?.rerank_score != null
                            ? score(selectedCandidate.rerank_score, 3)
                            : 'off'}
                        </b>
                      </span>
                    </div>
                  </div>
                  <div>
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
                        <dd>{selectedCandidate?.document_version_id || '—'}</dd>
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
                    </dl>
                    <VerifyAffordance
                      descriptor={receipt?._verify_sql?.candidates}
                      label="verify candidate in psql"
                    />
                  </div>
                </div>
              </section>
            ) : null}
          </section>
        ) : null}

        {module === 'prove' ? (
          <section className="module-screen">
            <header className="module-heading prove-heading">
              <div>
                <span className="module-kicker">
                  {proveTab === 'answer'
                    ? 'Agent · Answer'
                    : proveTab === 'graph'
                      ? 'Agent · Relationships'
                    : proveTab === 'receipt'
                      ? 'Proof · Run record'
                        : proveTab === 'replay'
                          ? 'Proof · Replay'
                          : proveTab === 'timeline'
                            ? 'Proof · Timeline'
                            : 'Evaluation'}
                </span>
                <h1>
                  {proveTab === 'answer' ? (
                    <>Build the answer from <em>persisted evidence.</em></>
                  ) : proveTab === 'graph' ? (
                    <>Inspect declared <em>evidence relationships.</em></>
                  ) : proveTab === 'receipt' ? (
                    <>Every candidate and citation, <em>persisted.</em></>
                  ) : proveTab === 'replay' ? (
                    <>Replay the answer from its <em>database run record.</em></>
                  ) : proveTab === 'timeline' ? (
                    <>Same evidence, <em>ordered by when it happened.</em></>
                  ) : (
                    <>Evidence, <em>not anecdotes.</em></>
                  )}
                </h1>
                <p className="module-deck">
                  {proveTab === 'answer'
                    ? 'Observe the model-selected tool sequence, bounded recovery, and citation gate behind the incident answer.'
                    : proveTab === 'graph'
                      ? 'Traverse foreign-key-derived facts and separately labeled inference without relaxing evidence authorization.'
                      : proveTab === 'receipt'
                        ? 'Resolve the controls, candidate signals, answer, citations, and search-index state without another model call.'
                        : proveTab === 'replay'
                          ? 'Walk the persisted retrieval stages in chronological order, reconstructed with no further model call.'
                          : proveTab === 'timeline'
                            ? 'Plot the cited evidence by source system and calendar day. Retrieval ranks it; the incident happened in order.'
                            : 'Measure retrieval modes and graph traversal with different metrics.'}
                </p>
              </div>
              {proveTab !== 'answer' ? (
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
              ) : null}
            </header>

            {proveTab === 'answer' ? (
              <section className="threadline-answer-page">
                <form
                  className="investigation-query agent-query-panel"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void askAgent();
                  }}
                >
                  <InvestigationQueryField
                    value={controls.query}
                    onChange={(query) => setControl('query', query)}
                    ariaLabel="Incident question"
                  />
                  <button
                    type="submit"
                    className="agent-query-run agent-command"
                    disabled={busy !== null || !controls.query.trim()}
                  >
                    {busy === 'answer' ? (
                      <LoaderCircle className="spin" size={17} />
                    ) : (
                      <Sparkles size={17} />
                    )}
                    {agentDisplayState === 'complete'
                      ? 'Investigate again'
                      : 'Investigate with agent'}
                  </button>
                  <div className="agent-query-meta">
                    <span
                      className={`answer-grounding-state ${agentDisplayState}`}
                    >
                      {agentDisplayState === 'complete' ? (
                        <ShieldCheck size={13} />
                      ) : agentDisplayState === 'streaming' ? (
                        <LoaderCircle className="spin" size={13} />
                      ) : (
                        <AlertTriangle size={13} />
                      )}
                      {agentDisplayState === 'complete'
                        ? persistedAnswerLoaded
                          ? 'persisted answer loaded'
                          : 'citation gate passed'
                        : agentDisplayState === 'streaming'
                          ? 'agent running'
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
                    <span className="agent-query-boundary">
                      ACL checked on retrieval and every relationship hop
                    </span>
                  </div>
                </form>

                <div className="answer-story-layout">
                  <article className="answer-story-document">
                    {agentDisplayState === 'blocked' ? (
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

                    {agentDisplayState === 'streaming' ? (
                      <section className="agent-working-panel" aria-live="polite">
                        <header>
                          <span className="agent-live-indicator">
                            <i />
                            Investigating evidence
                          </span>
                          <b>
                            {agentTrace.length
                              ? `${agentTrace.length} decisions observed`
                              : 'starting Strands loop'}
                          </b>
                        </header>
                        <div>
                          {agentTrace.length ? (
                            agentTrace.slice(-5).map((event, index) => (
                              <article
                                key={`${event.sequence || index}-${event.tool}`}
                                className={
                                  event === currentAgentEvent ? 'current' : ''
                                }
                              >
                                <span>
                                  <Check size={13} />
                                </span>
                                <div>
                                  <strong>
                                    {readableToolName(event.tool)}
                                  </strong>
                                  <p>{toolDecision(event)}</p>
                                </div>
                                <small>{toolResult(event)}</small>
                              </article>
                            ))
                          ) : (
                            <article className="current">
                              <span>
                                <LoaderCircle className="spin" size={13} />
                              </span>
                              <div>
                                <strong>Preparing evidence plan</strong>
                                <p>
                                  Reading the question and selecting the first
                                  bounded tool call.
                                </p>
                              </div>
                              <small>live</small>
                            </article>
                          )}
                        </div>
                      </section>
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

                    {agentDisplayState === 'complete' && answer ? (
                      <div className="answer-complete-prose">
                        <p className="answer-lead">
                          Cause, visible impact, and safe remediation all have
                          citation-validated evidence.
                        </p>
                        <div className="answer-prose">
                          <FormattedAnswer text={streamingAnswer || answer.answer_text} />
                        </div>
                        <div className="answer-proof-strip">
                          <span>
                            <b>{answerCitations.length}</b>
                            validated citations
                          </span>
                          <span>
                            <b>{runbookRecovered ? 'yes' : 'no'}</b>
                            RB-017 cited
                          </span>
                          <span>
                            <b>{agentTrace.length || 'persisted'}</b>
                            {agentTrace.length
                              ? 'observed tool calls'
                              : 'answer record loaded'}
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

                    {agentDisplayState === 'error' ? (
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
                        {answerCitations.length
                          ? visibleAnswerCitations.length ===
                            answerCitations.length
                            ? `Sources · ${answerCitations.length} cited`
                            : `Sources · ${visibleAnswerCitations.length} of ${answerCitations.length}`
                          : 'Required evidence'}
                      </span>
                    </header>
                    {answerCitations.length ? (
                      <div className="answer-source-list">
                        {visibleAnswerCitations
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
                        {[
                          ['Cause', true],
                          ['Visible impact', true],
                          ['Safe remediation', false],
                        ].map(([label, covered]) => (
                            <div
                              className={
                                agentDisplayState === 'streaming'
                                  ? 'pending'
                                  : covered
                                    ? 'covered'
                                    : 'missing'
                              }
                              key={String(label)}
                            >
                              {agentDisplayState === 'streaming' ? (
                                <LoaderCircle className="spin" size={14} />
                              ) : covered ? (
                                <Check size={14} />
                              ) : (
                                <AlertTriangle size={14} />
                              )}
                              <span>
                                <strong>
                                  {agentDisplayState === 'streaming'
                                    ? 'Checking evidence'
                                    : covered
                                      ? 'Covered by baseline'
                                      : 'Recovery required'}
                                </strong>
                                <small>{label}</small>
                              </span>
                            </div>
                          ))}
                      </div>
                    )}
                    <section className="answer-coverage-card">
                      <div>
                        <span>Claim coverage</span>
                        <b>{answerCoverageComplete ? '3/3' : '2/3'}</b>
                      </div>
                      <div className="answer-coverage-meter">
                        <i
                          style={{
                            width:
                              answerCoverageComplete ? '100%' : '66.67%',
                          }}
                        />
                      </div>
                      <p>
                        {answerCoverageComplete
                          ? 'Every citation resolves to a source URI, revision, exact chunk, and supporting quote.'
                          : 'RB-017 must be present and cited before the answer can pass.'}
                      </p>
                    </section>
                  </aside>
                </div>

                <section className="answer-build-story">
                  <header>
                    <div>
                      <span className="section-label">
                        Observable execution
                      </span>
                      <h2>
                        Tool decisions first; prose after the evidence gate.
                      </h2>
                    </div>
                    <span className="status-pill">
                      {agentTrace.length
                        ? `${agentTrace.length} observed calls`
                        : agentDisplayState === 'complete'
                          ? 'persisted answer'
                          : 'recovery not started'}
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
                    ) : agentDisplayState === 'complete' ? (
                      <>
                        <div className="complete">
                          <span>1</span>
                          <div>
                            <strong>Supporting runs persisted</strong>
                            <p>
                              Ranked evidence and candidate diagnostics were
                              stored before synthesis.
                            </p>
                            <small>{compactId(answer?.run_id || runId)}</small>
                          </div>
                          <time>complete</time>
                        </div>
                        <div className="complete">
                          <span>2</span>
                          <div>
                            <strong>Required evidence covered</strong>
                            <p>
                              Cause, visible customer impact, and approved
                              remediation were present in the visible set.
                            </p>
                            <small>{answerCitations.length} cited sources</small>
                          </div>
                          <time>complete</time>
                        </div>
                        <div className="complete">
                          <span>3</span>
                          <div>
                            <strong>Citations validated</strong>
                            <p>
                              Source URI, revision, chunk, and quote resolved
                              against the persisted evidence versions.
                            </p>
                            <small>answer released</small>
                          </div>
                          <time>passed</time>
                        </div>
                      </>
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
                    <span className="section-label">Why this stays bounded</span>
                    <h2>Recovery changes scope, not authority.</h2>
                  </header>
                  <div>
                    <article>
                      <span>01</span>
                      <strong>Incident evidence stays filtered</strong>
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
                    <article
                      className={
                        agentDisplayState === 'complete' ? 'observed' : ''
                      }
                    >
                      <span>03</span>
                      <strong>Authorization and validation stay fixed</strong>
                      <p>
                        ACL checks apply to every retrieval and hop; missing or
                        invalid citations keep the answer withheld.
                      </p>
                    </article>
                  </div>
                </section>

                <section
                  className={`agent-contract-drawer ${
                    agentContractOpen ? 'open' : ''
                  }`}
                >
                  <button
                    type="button"
                    className="agent-contract-summary"
                    onClick={() =>
                      setAgentContractOpen((current) => !current)
                    }
                    aria-expanded={agentContractOpen}
                  >
                    <span className="agent-contract-icon">
                      <Code2 size={18} />
                    </span>
                    <span>
                      <b>Agent contract</b>
                      <small>
                        Six model-selectable tools share one Aurora-owned
                        retrieval and proof path.
                      </small>
                    </span>
                    <span className="agent-contract-summary-meta">
                      Strands · {TOOL_NAMES.length} tools
                      <ChevronRight size={17} />
                    </span>
                  </button>
                  {agentContractOpen ? (
                    <div className="agent-contract-body">
                      <nav aria-label="Agent tools">
                        {TOOL_NAMES.map((tool, index) => (
                          <button
                            key={tool}
                            type="button"
                            className={selectedTool === tool ? 'active' : ''}
                            onClick={() => setSelectedTool(tool)}
                          >
                            <span>{String(index + 1).padStart(2, '0')}</span>
                            {readableToolName(tool)}
                          </button>
                        ))}
                      </nav>
                      <article>
                        <span className="section-label">Selected tool</span>
                        <h3>{readableToolName(selectedTool)}</h3>
                        <p>{TOOL_CONTRACTS[selectedTool].purpose}</p>
                        <dl>
                          <div>
                            <dt>Returns</dt>
                            <dd>{TOOL_CONTRACTS[selectedTool].result}</dd>
                          </div>
                          <div>
                            <dt>Proof boundary</dt>
                            <dd>{TOOL_CONTRACTS[selectedTool].proof}</dd>
                          </div>
                        </dl>
                      </article>
                      <aside>
                        <span className="section-label">Current context</span>
                        <dl>
                          <div>
                            <dt>Run</dt>
                            <dd>{compactId(answer?.run_id || runId)}</dd>
                          </div>
                          <div>
                            <dt>Visible candidates</dt>
                            <dd>{candidates.length || '—'}</dd>
                          </div>
                          <div>
                            <dt>Answer citations</dt>
                            <dd>{answerCitations.length || '—'}</dd>
                          </div>
                          <div>
                            <dt>Ranking owner</dt>
                            <dd>Aurora SQL</dd>
                          </div>
                        </dl>
                      </aside>
                    </div>
                  ) : null}
                </section>

                {agentCommentary ? (
                  <p className="agent-commentary">
                    <Sparkles size={14} />
                    <span>
                      <strong>Agent close:</strong> {agentCommentary}
                    </span>
                  </p>
                ) : null}

                {agentDisplayState === 'complete' ? (
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
                          Candidate-level run record
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

            {proveTab === 'timeline' ? (
              <section className="tgrid-theater">
                <header>
                  <div>
                    <span className="section-label">
                      Cited evidence, in order
                    </span>
                    <h2>{receipt?.run.query_text || controls.query}</h2>
                  </div>
                  <div className="tgrid-theater-meta">
                    <span className="status-pill">
                      {timeline?.events.length || 0} events
                    </span>
                    <span className="status-pill">
                      {timelineGrid.lanes.length} systems
                    </span>
                    <span className="status-pill">
                      {timelineGrid.days.length} days
                    </span>
                  </div>
                </header>
                {timeline?.events.length ? (
                  <TimelineGridView grid={timelineGrid} />
                ) : (
                  <Empty
                    icon={<GitMerge size={20} />}
                    title="No timeline loaded"
                    detail="Load a run to plot its cited evidence by system and day."
                  />
                )}
              </section>
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

        {module === 'corpus' ? (
          <section className="module-screen">
            <header className="module-heading">
              <div>
                <span className="module-kicker">Utility · Corpus</span>
                <h1>
                  What the index <em>actually holds.</em>
                </h1>
                <p className="module-deck">
                  Evidence documents and chunks materialized into the search
                  index on this cluster, grouped by kind, read live from Aurora.
                </p>
              </div>
              <div className="heading-status">
                <span className="status-pill">
                  {health?.current_documents?.toLocaleString() || '—'} docs
                </span>
                <span className="status-pill">
                  {health?.current_chunks?.toLocaleString() || '—'} chunks
                </span>
              </div>
            </header>

            <div className="scale-detail-grid">
              <section className="distribution-panel">
                <header>
                  <span className="section-label">Live corpus distribution</span>
                  <span className="status-pill">
                    {health?.current_chunks?.toLocaleString() || '—'} chunks
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

              <section className="capacity-panel">
                <header>
                  <span className="section-label">Embedding spaces</span>
                  <span className="status-pill">{embeddingModel}</span>
                </header>
                <dl>
                  {(health?.embedding_spaces || []).map((space) => (
                    <div key={space.embedding_model}>
                      <dt>{space.embedding_model}</dt>
                      <dd>
                        {space.chunks.toLocaleString()} chunks ·{' '}
                        {space.dimensions.toLocaleString()} dimensions
                      </dd>
                    </div>
                  ))}
                </dl>
              </section>
            </div>
          </section>
        ) : null}

        {module === 'health' ? (
          <section className="module-screen">
            <header className="module-heading">
              <div>
                <span className="module-kicker">Utility · Health</span>
                <h1>
                  Is the index <em>current and drift-free?</em>
                </h1>
                <p className="module-deck">
                  Search-index readiness, embedding coverage, and the build
                  records that prove the index was rebuilt without blocking
                  casework, all read live from Aurora.
                </p>
              </div>
              <div className="heading-status">
                <span
                  className={`status-pill ${
                    health?.drift_issues === 0 ? 'ready' : ''
                  }`}
                >
                  {health?.drift_issues ?? '—'} drift
                </span>
                <span className="status-pill">
                  {engineRelease(health?.engine_version)}
                </span>
                <span className="status-pill">
                  pgvector {health?.pgvector_version || '—'}
                </span>
              </div>
            </header>

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
                  <dd>{health?.current_documents.toLocaleString() || '—'}</dd>
                </div>
                <div>
                  <dt>Ready embeddings</dt>
                  <dd>{health?.ready_embeddings.toLocaleString() || '—'}</dd>
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
            </aside>

            <section className="build-history-panel">
              <header>
                <div>
                  <span className="section-label">
                    Search-index build history
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
                  <span>
                    Two passes, no write blocking, INVALID cleanup on failure.
                  </span>
                </div>
                <div>
                  <strong>Blue/green</strong>
                  <span>
                    Build, evaluate, then switch once the window is too large.
                  </span>
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
