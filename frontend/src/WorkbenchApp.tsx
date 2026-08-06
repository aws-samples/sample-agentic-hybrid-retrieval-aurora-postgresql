import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Check,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Clipboard,
  Code2,
  Database,
  ExternalLink,
  FileCheck2,
  FileSearch,
  Gauge,
  GitMerge,
  House,
  LoaderCircle,
  LockKeyhole,
  Menu,
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
  UserCheck,
  Wrench,
  X,
} from 'lucide-react';
import {
  Fragment,
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
  type PersonaKey,
  type Route,
  type RouteSurface,
} from './route';
import {
  DEFAULT_PERSONA,
  PERSONA_KEYS,
  PERSONA_LABELS,
  personaLabel,
} from './persona';
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
  | 'supervision'
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

type JourneySurface = 'overview' | 'retrieval' | 'agent' | 'proof';
type JourneyState = 'available' | 'active' | 'waiting' | 'blocked';

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
  { surface: 'overview', label: 'Incident', Icon: House, lenses: [] },
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
    label: 'Hybrid Retrieval Agent',
    Icon: Sparkles,
    lenses: [{ key: 'answer', label: 'Answer', Icon: FileCheck2 }],
  },
  {
    surface: 'proof',
    label: 'Proof',
    Icon: ShieldCheck,
    lenses: [
      { key: 'evidence', label: 'Evidence record', Icon: Clipboard },
      { key: 'action', label: 'Action review', Icon: UserCheck },
    ],
  },
];

const UTILITY_NAV: NavSurface[] = [
  { surface: 'corpus', label: 'Corpus', Icon: Database, lenses: [] },
  { surface: 'evaluation', label: 'Evaluation', Icon: Gauge, lenses: [] },
  { surface: 'health', label: 'Health', Icon: Activity, lenses: [] },
];

interface JourneyStep {
  surface: JourneySurface;
  label: string;
  caption: string;
  state: JourneyState;
}

const JOURNEY_SURFACES: JourneySurface[] = [
  'overview',
  'retrieval',
  'agent',
  'proof',
];

type RetrievalMode = 'hybrid' | 'semantic' | 'lexical' | 'fuzzy';
type EvidenceKind =
  | 'incident'
  | 'change'
  | 'lock_evidence'
  | 'telemetry';
type JsonRecord = Record<string, unknown>;

// The exact statement the endpoint executed, bound to the visible run, so a
// participant can reproduce a rendered number in psql (Law 2 / gate G-13).
interface VerifySql {
  statement: string;
  binds: Record<string, unknown>;
  rendered?: string;
  set_role?: string | null;
}

// Panels whose value is a live capture or a harness aggregate cannot be replayed
// from a run_id; they say so honestly instead of publishing a decorative query.
interface VerifySqlUnavailable {
  reproducible: false;
  reason: string;
}

interface LiveRun {
  capture_id: string;
  capture_key: string;
  cluster_id: string;
  capture_started_at: string;
  capture_ended_at: string;
  validation_capture_id: string | null;
  validation_capture_key: string | null;
  validation_capture_started_at: string | null;
  validation_capture_ended_at: string | null;
  incident_key: string;
  unsafe_change_key: string;
  analyze_change_key: string;
  validation_change_key: string | null;
  lock_key: string;
  source_documents: number;
  telemetry_documents: number;
  raw_telemetry_rows: number;
}

interface Health {
  status: string;
  security_mode: 'core' | 'persona';
  drift_issues: number;
  current_chunks: number;
  ready_embeddings: number;
  source_documents: number;
  current_documents: number;
  last_indexed_at: string | null;
  cluster_id: string | null;
  engine_version: string;
  pgvector_version: string | null;
  embedding_spaces: Array<{
    embedding_model: string;
    dimensions: number;
    chunks: number;
  }>;
  run: LiveRun | null;
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
    embedding_model?: string;
    note?: string;
    positions?: Record<string, number | null>;
  };
  evidence_snapshot?: EvidenceSnapshot;
}

interface SearchResponse {
  run_id: string;
  results: Candidate[];
}

interface Citation {
  n?: number;
  citation_number?: number;
  evidence_id?: string;
  document_version_id?: string;
  chunk_version_id?: string;
  external_key: string;
  title: string;
  source_uri: string;
  source_revision: string;
  quote_text?: string;
  claim?: string | null;
}

type AgentStreamState =
  | 'idle'
  | 'streaming'
  | 'complete'
  | 'error';
type ConnectionState = 'checking' | 'ready' | 'unavailable';

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
  validation_status?: string;
  created_at?: string;
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
  hnsw_iterative_scan: IterativeScanMode | null;
  status: string;
  latency_ms: number | null;
  candidate_count: number;
  reranked_count: number;
  started_at: string;
  completed_at?: string | null;
  identifier_tokens?: string[];
  fuzzy_probe_tokens?: string[];
  candidate_pool?: number;
  role?: string;
}

interface Stage {
  stage_ordinal: number;
  stage_name: string;
  duration_ms: number;
  details: JsonRecord;
}

type ObservabilityLink = {
  kind: 'lock_analysis';
  label: string;
  url: string;
};

interface ObservabilityRef {
  run_id: string;
  ref: {
    db_resource_id: string | null;
    window_start: string;
    window_end: string | null;
    wait_event: string | null;
    sql_digest: string | null;
    captured_at: string;
  } | null;
  links: ObservabilityLink[];
  _verify_sql?: VerifySql;
}

interface RunReceipt {
  run: RunSummary;
  candidates: Candidate[];
  stages: Stage[];
  answer: AnswerReceipt | null;
  score_note: string;
  observability_ref?: ObservabilityRef;
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
    wave: 'A' | 'B' | null;
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
  run: LiveRun | null;
  _verify_sql?: {
    distribution: VerifySql;
  };
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

interface ActionProposal {
  proposal_id: string;
  agent_run_id: string;
  run_id: string;
  action_type: string;
  target_schema: string;
  target_table: string;
  index_method: string;
  is_unique: boolean;
  key_columns: string[];
  included_columns: string[];
  predicate: string | null;
  proposed_fingerprint: string;
  proposed_sql: string;
  proposed_sql_sha256: string;
  preconditions: Array<{
    check: string;
    satisfied: boolean;
    detail?: string;
  }>;
  expected_effect: string;
  rollback_sql: string | null;
  rollback_guidance: string | null;
  statement_timeout: string | null;
  lock_timeout: string | null;
  created_at: string;
}

interface ActionExecution {
  execution_id: string;
  proposal_id: string;
  run_id: string;
  approved_by: string;
  approved_at: string;
  observed_index_definition: string | null;
  observed_fingerprint: string | null;
  fingerprint_matches: boolean | null;
  outcome: string;
  outcome_detail: string | null;
  started_at: string | null;
  completed_at: string | null;
  plan_before_checkpoint: string | null;
  plan_after_checkpoint: string | null;
  wave_b_capture_id: string | null;
  wave_b_ingest_id: string | null;
}

interface AutonomyVerdict {
  proposal_id: string;
  pre_execution_eligible: boolean;
  pre_execution_reasons: string[];
  post_execution_validated: boolean;
  post_execution_reasons: string[];
}

interface SupervisionReceipt {
  run_id: string;
  proposal: ActionProposal | null;
  citations: Array<{
    citation_number: number;
    claim: string;
    source_uri: string | null;
    source_revision: string | null;
    quote_text: string | null;
    is_valid: boolean | null;
    issue: string | null;
  }>;
  execution: ActionExecution | null;
  verdict: AutonomyVerdict | null;
  _verify_sql?: Record<string, VerifySql>;
}

interface QueryPlanResponse {
  arm: 'semantic' | 'lexical' | 'fuzzy';
  query: string;
  cluster_id: string | null;
  captured_at: string;
  plan: {
    Plan?: JsonRecord;
    'Planning Time'?: number;
    'Execution Time'?: number;
  };
  scans: Array<{
    node_type: string;
    schema: string | null;
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
  iterativeScan: IterativeScanMode;
  rerank: boolean;
  role: PersonaKey;
}

type IterativeScanMode = 'off' | 'strict_order' | 'relaxed_order';

const ITERATIVE_SCAN_LABELS: Record<IterativeScanMode, string> = {
  off: 'Off',
  strict_order: 'Strict order',
  relaxed_order: 'Relaxed order',
};

const API_BASE = (
  import.meta.env.VITE_RETRIEVAL_API_URL || 'http://127.0.0.1:8000'
).replace(/\/$/, '');
const APP_NAME = import.meta.env.VITE_APP_DISPLAY_NAME || 'Hybrid Retrieval Workbench';
const PARTICIPANT_SOURCE_SYSTEMS = ['pg_incident_capture'] as const;
const DEFAULT_QUERY = '';

function liveQuestion(run: LiveRun | null | undefined): string {
  if (!run) return '';
  const validation = run.validation_change_key
    ? ` What did ${run.validation_change_key} validate after the participant approved the recommendation?`
    : '';
  return (
    `What evidence explains the queued write timeouts in ${run.incident_key}, ` +
    `how did ${run.unsafe_change_key} and ${run.lock_key} connect the online ` +
    `schema and data migration to pool exhaustion, why did connected writes ` +
    `recover after commit, and why did ${run.analyze_change_key} show that ` +
    `ANALYZE did not change the slow query's access path?${validation}`
  );
}

const DEFAULT_CONTROLS: Controls = {
  query: DEFAULT_QUERY,
  mode: 'hybrid',
  kind: 'all',
  clusterId: '',
  environment: '',
  limit: 8,
  candidatePool: 24,
  rrfK: 60,
  textWeight: 2,
  vectorWeight: 1,
  fuzzyWeight: 1,
  fuzzyThreshold: 0.3,
  efSearch: 40,
  iterativeScan: 'strict_order',
  rerank: false,
  role: DEFAULT_PERSONA,
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
    iterativeScan: controls.iterativeScan,
    rerank: controls.rerank,
    role: controls.role,
  });
}

// presetKey ties a preset to the SPEC 6.0 route vocabulary
// (?preset={exact|fuzzy|semantic}). The typo preset intentionally uses the
// fuzzy arm by itself: its exercise proves pg_trgm recovery, while the Fusion
// lens separately demonstrates how weighted RRF rewards agreement across arms.
// The remaining examples stay UI-reachable but are not URL-addressable.
function livePresets(run: LiveRun | null | undefined): {
  label: string;
  query: string;
  mode: RetrievalMode;
  kind: EvidenceKind | 'all';
  clusterId: string;
  rerank?: boolean;
  presetKey?: PresetKey;
}[] {
  if (!run) return [];
  return [
  {
    label: 'Measured incident',
    query: liveQuestion(run),
    mode: 'hybrid' as RetrievalMode,
    kind: 'all' as const,
    clusterId: '',
  },
  {
    label: 'Exact ID',
    query: run.unsafe_change_key,
    mode: 'hybrid' as RetrievalMode,
    kind: 'all' as const,
    clusterId: '',
    presetKey: 'exact',
  },
  {
    label: 'Semantic question',
    query:
      'Why did one unbatched priority_tier backfill exhaust the 10-connection application pool, why did connected writes drain after commit, and why did ANALYZE leave the orders query on a sequential scan?',
    mode: 'hybrid' as RetrievalMode,
    kind: 'all' as const,
    clusterId: '',
    presetKey: 'semantic',
  },
  {
    label: 'Typo recovery',
    query: run.unsafe_change_key.replace(/^CHG-/, 'CGH-'),
    mode: 'fuzzy' as RetrievalMode,
    kind: 'all' as const,
    clusterId: '',
    rerank: false,
    presetKey: 'fuzzy',
  },
  {
    label: 'Lock observation',
    query: run.lock_key,
    mode: 'hybrid' as RetrievalMode,
    kind: 'lock_evidence' as const,
    clusterId: '',
  },
  {
    label: 'Access-path finding',
    query:
      'What did the before- and after-ANALYZE plans prove about the missing composite index on orders?',
    mode: 'hybrid' as RetrievalMode,
    kind: 'change' as const,
    clusterId: '',
  },
  ];
}

function liveAgentExamples(run: LiveRun | null | undefined): {
  label: string;
  question: string;
}[] {
  if (!run) return [];
  const fuzzyChangeKey = run.unsafe_change_key.replace(/^CHG-/, 'CGH-');

  return [
    {
      label: 'Incident diagnosis',
      question: liveQuestion(run),
    },
    {
      label: 'Exact change',
      question: `What does ${run.unsafe_change_key} record, and how did it contribute to ${run.incident_key}?`,
    },
    {
      label: 'Typo recovery',
      question: `The identifier ${fuzzyChangeKey} is misspelled. Search that typo exactly, recover the intended CHG record, and explain how that change contributed to ${run.incident_key}. Cite the recovered change record.`,
    },
    {
      label: 'Pool boundary',
      question: `Why did some writes time out before reaching PostgreSQL during ${run.incident_key}, while connected writers recovered after commit?`,
    },
    {
      label: 'Access path',
      question: `Why did the priority reference query remain slow after ANALYZE in ${run.incident_key}?`,
    },
  ];
}

const KIND_LABELS: Record<EvidenceKind, string> = {
  incident: 'Incident',
  change: 'Change',
  lock_evidence: 'Lock evidence',
  telemetry: 'Telemetry',
};

type CorpusDistribution = SearchIndexDiagnostics['distribution'][number];
type CorpusDistributionGroup = {
  wave: CorpusDistribution['wave'];
  rows: CorpusDistribution[];
};

function corpusWaveLabel(wave: CorpusDistribution['wave']): string {
  if (wave === 'A') return 'Investigation Evidence: captured before the recommendation';
  if (wave === 'B') {
    return 'Validation Evidence: captured after the participant validated the recommendation';
  }
  return 'Not capture-scoped: provenance does not map this record to a capture';
}

function corpusWaveClassName(wave: CorpusDistribution['wave']): string {
  if (wave === null) return 'distribution-wave--unscoped';
  return `distribution-wave--${wave.toLowerCase()}`;
}

function corpusWaveRank(wave: CorpusDistribution['wave']): number {
  return wave === 'A' ? 0 : wave === 'B' ? 1 : 2;
}

function groupCorpusDistribution(
  rows: readonly CorpusDistribution[],
): CorpusDistributionGroup[] {
  const groups = new Map<string, CorpusDistributionGroup>();
  for (const row of rows) {
    const key = row.wave ?? 'unscoped';
    const group = groups.get(key);
    if (group) {
      group.rows.push(row);
    } else {
      groups.set(key, { wave: row.wave, rows: [row] });
    }
  }
  return [...groups.values()].sort(
    (left, right) => corpusWaveRank(left.wave) - corpusWaveRank(right.wave),
  );
}

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
  'M310 163 C310 137 310 105 310 76',
  'M402 230 C416 226 429 221 443 216',
  'M368 338 C395 374 420 410 446 444',
  'M252 338 C225 374 200 410 174 444',
  'M218 230 C204 226 191 221 177 216',
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

function toolDecision(
  event: AgentTraceEvent,
  personaMode = true,
): string {
  const args = event.arguments || {};
  if (event.tool === 'decompose_question') {
    return `Split the compound question into ${event.subquestion_count || 'its'} evidence requirements.`;
  }
  if (event.tool === 'search_evidence') {
    const kinds = Array.isArray(args.kinds)
      ? (args.kinds as string[]).join(', ')
      : 'all evidence';
    return `Searched ${kinds} with ${args.cluster_id || args.incident_id || 'no scope filter'}${
      personaMode ? '; the persona stayed fixed' : ''
    }.`;
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

function citationContext(citation: Citation): string {
  const persistedText = citation.claim?.trim() || citation.quote_text?.trim();
  return persistedText
    ? persistedText.replace(/\s+/g, ' ')
    : citation.title;
}

function toolContract(
  tool: (typeof TOOL_NAMES)[number],
  personaMode: boolean,
) {
  const contract = TOOL_CONTRACTS[tool];
  if (personaMode) return contract;
  if (tool === 'search_evidence') {
    return {
      ...contract,
      purpose: 'Run canonical hybrid retrieval with metadata filters.',
    };
  }
  if (tool === 'follow_evidence_links') {
    return {
      ...contract,
      proof: 'Every relationship hop retains its evidence provenance.',
    };
  }
  return contract;
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

function rankLabel(value: number | null): string {
  return value === null ? '—' : `#${value}`;
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

const RETRIEVAL_MODE_LABELS: Record<RetrievalMode, string> = {
  hybrid: 'Hybrid',
  semantic: 'Semantic',
  lexical: 'Full-text',
  fuzzy: 'Fuzzy',
};

function rankingScore(candidate: Candidate, mode: RetrievalMode): number | null {
  if (mode === 'hybrid') {
    return numberValue(candidate.rrf_score ?? candidate.final_score);
  }
  if (mode === 'semantic') return numberValue(candidate.vector_score);
  if (mode === 'lexical') return numberValue(candidate.text_rank);
  return numberValue(candidate.trigram_score);
}

function rankingScoreLabel(mode: RetrievalMode): string {
  if (mode === 'hybrid') return 'PostgreSQL RRF';
  if (mode === 'semantic') return 'Vector similarity';
  if (mode === 'lexical') return 'Full-text score';
  return 'Trigram similarity';
}

function rankingScorePrecision(mode: RetrievalMode): number {
  return mode === 'fuzzy' ? 3 : mode === 'hybrid' ? 5 : 4;
}

function finalOrderRule(mode: RetrievalMode, reranked: boolean): {
  rule: string;
  note: string;
} {
  if (mode === 'hybrid') {
    return reranked
      ? {
          rule:
            'Exact identifier matches first; Cohere orders candidates within each tier.',
          note:
            'PostgreSQL RRF remains the pre-rerank order. RRF and Cohere scores explain relative rank; neither is a confidence probability.',
        }
      : {
          rule:
            'Exact identifier matches first; PostgreSQL weighted RRF orders every other candidate.',
          note:
            'Arm positions, not raw arm scores, enter RRF. The resulting score explains relative rank, not confidence.',
        };
  }

  const signalRule: Record<Exclude<RetrievalMode, 'hybrid'>, string> = {
    semantic:
      'Vector similarity orders evidence by distance in the configured embedding space.',
    lexical:
      'PostgreSQL full-text relevance orders the evidence returned by the lexical arm.',
    fuzzy:
      'pg_trgm similarity orders identifier and title matches above the active threshold.',
  };
  return {
    rule: reranked
      ? `Cohere reranks the ${RETRIEVAL_MODE_LABELS[mode].toLowerCase()} candidate set.`
      : signalRule[mode],
    note: reranked
      ? `The original ${RETRIEVAL_MODE_LABELS[mode].toLowerCase()} score remains persisted separately from the Cohere score.`
      : 'The displayed score is a relative ranking signal, not a confidence probability.',
  };
}

function topRankExplanation(
  candidate: Candidate,
  evidence: EvidenceSnapshot,
  mode: RetrievalMode,
  reranked: boolean,
  baseRank: number,
): string {
  const key = evidence.external_key || 'This evidence';
  const textPosition = position(candidate, 'text');
  const vectorPosition = position(candidate, 'vector');
  const fuzzyPosition = position(candidate, 'fuzzy');
  const primaryScore = rankingScore(candidate, mode);

  let base: string;
  if (mode === 'hybrid') {
    if (candidate.explanation?.exact_identifier) {
      base = `${key} matched an identifier in the query and entered the exact-identifier tier before fused candidates.`;
    } else {
      const positions = [
        textPosition === null ? null : `full-text #${textPosition}`,
        vectorPosition === null ? null : `semantic #${vectorPosition}`,
        fuzzyPosition === null ? null : `fuzzy #${fuzzyPosition}`,
      ].filter((value): value is string => Boolean(value));
      base = positions.length
        ? `${key} entered through ${positions.join(', ')}; weighted RRF combined those positions into ${score(primaryScore, 5)}.`
        : `${key} entered the fused candidate set; weighted RRF placed it first with ${score(primaryScore, 5)}.`;
    }
  } else if (mode === 'semantic') {
    base = `The semantic arm placed ${key} at ${rankLabel(vectorPosition)} by vector similarity in the configured embedding space.`;
  } else if (mode === 'lexical') {
    base = candidate.explanation?.exact_identifier
      ? `${key} matched an identifier in the query and ranked first in PostgreSQL full-text retrieval.`
      : `PostgreSQL full-text retrieval placed ${key} at ${rankLabel(textPosition)} from lexical relevance.`;
  } else {
    base = `pg_trgm placed ${key} at ${rankLabel(fuzzyPosition)} as the closest identifier or title match above the active threshold.`;
  }

  if (!reranked || candidate.rerank_score == null) return base;
  const baseLabel =
    mode === 'hybrid' ? 'Aurora rank' : `${RETRIEVAL_MODE_LABELS[mode]} rank`;
  return baseRank === 1
    ? `${base} Cohere kept it at final rank 1; the ${baseLabel.toLowerCase()} remains persisted separately.`
    : `${base} Cohere moved it from ${baseLabel.toLowerCase()} ${baseRank} to final rank 1.`;
}

// Read-only reconstruction of the canonical Aurora order from persisted fields.
// The comparator mirrors retrieval.hybrid_search's total ORDER BY.
function fusedOrder(candidates: Candidate[]): Candidate[] {
  return [...candidates].sort((a, b) => {
    const tierGap = matchTier(a) - matchTier(b);
    if (tierGap !== 0) return tierGap;

    const aExact =
      a.exact_identifier_position ?? Number.POSITIVE_INFINITY;
    const bExact =
      b.exact_identifier_position ?? Number.POSITIVE_INFINITY;
    if (aExact !== bExact) return aExact - bExact;

    const scoreGap =
      (b.rrf_score ?? b.final_score ?? 0) -
      (a.rrf_score ?? a.final_score ?? 0);
    if (scoreGap !== 0) return scoreGap;

    const aEvidence = snapshot(a);
    const bEvidence = snapshot(b);
    if (aEvidence.occurred_at !== bEvidence.occurred_at) {
      if (!aEvidence.occurred_at) return -1;
      if (!bEvidence.occurred_at) return 1;
      const occurredGap = bEvidence.occurred_at.localeCompare(
        aEvidence.occurred_at,
      );
      if (occurredGap !== 0) return occurredGap;
    }

    return (aEvidence.external_key || '').localeCompare(
      bEvidence.external_key || '',
    );
  });
}

// With rerank off, final order must equal fused order. A mismatch is a defect
// and is surfaced rather than hidden.
function isFusedOrder(candidates: Candidate[]): boolean {
  const expected = fusedOrder(candidates);
  return candidates.every(
    (candidate, index) => candidate.evidence_id === expected[index].evidence_id,
  );
}

function buildJourneySteps({
  activeSurface,
  activeLens,
  retrievalAvailable,
  agentAvailable,
  proofAvailable,
  agentWithheld,
  proofWithheld,
}: {
  activeSurface: Surface;
  activeLens: string;
  retrievalAvailable: boolean;
  agentAvailable: boolean;
  proofAvailable: boolean;
  agentWithheld: boolean;
  proofWithheld: boolean;
}): JourneyStep[] {
  const availability: Record<JourneySurface, boolean> = {
    overview: true,
    retrieval: retrievalAvailable,
    agent: agentAvailable,
    proof: proofAvailable,
  };
  const blocked: Record<JourneySurface, boolean> = {
    overview: false,
    retrieval: false,
    agent: agentWithheld,
    proof: proofWithheld,
  };

  return JOURNEY_SURFACES.map((surface) => {
    const nav = PRIMARY_NAV.find((item) => item.surface === surface);
    const current = activeSurface === surface;
    const lensLabel = nav?.lenses.find((lens) => lens.key === activeLens)?.label;
    const defaultLensLabel = nav?.lenses[0]?.label || nav?.label || surface;
    const state: JourneyState = current
      ? blocked[surface]
        ? 'blocked'
        : 'active'
      : availability[surface]
        ? 'available'
        : blocked[surface]
          ? 'blocked'
          : 'waiting';
    const caption =
      current
        ? lensLabel || nav?.label || 'Active'
        : state === 'available'
          ? `${defaultLensLabel} available`
          : state === 'blocked'
            ? `${defaultLensLabel} withheld`
            : `${defaultLensLabel} unavailable`;

    return {
      surface,
      label: nav?.label || surface,
      caption,
      state,
    };
  });
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
  if (kind === 'lock_evidence') return <Activity size={size} />;
  return <FileSearch size={size} />;
}

function WorkbenchMark({ className = '' }: { className?: string }) {
  return (
    <svg
      className={`workbench-mark ${className}`.trim()}
      viewBox="0 0 32 32"
      aria-hidden="true"
      focusable="false"
    >
      <rect className="workbench-mark-frame" x="0.75" y="0.75" width="30.5" height="30.5" rx="8" />
      <path
        className="workbench-mark-thread"
        d="M7.5 8.5 16 20.5 24.5 8.5M16 6.25v14.25"
      />
      <circle className="workbench-mark-source" cx="7.5" cy="8.5" r="2.25" />
      <circle className="workbench-mark-source" cx="16" cy="6.25" r="2.25" />
      <circle className="workbench-mark-source" cx="24.5" cy="8.5" r="2.25" />
      <circle className="workbench-mark-answer" cx="16" cy="23" r="5" />
      <path className="workbench-mark-check" d="m13.7 22.9 1.65 1.65 3.1-3.45" />
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

function LiveBanner({
  health,
  connectionState,
}: {
  health: Health | null;
  connectionState: ConnectionState;
}) {
  const indexState =
    connectionState === 'checking'
      ? 'connecting'
      : connectionState === 'unavailable'
        ? 'not connected'
        : health?.status === 'ready'
          ? 'ready'
          : health?.status || 'available';
  return (
    <div
      className={`live-banner ${connectionState}`}
      role="status"
      aria-label="Live cluster status"
    >
      <span className="live-banner-dot" aria-hidden="true" />
      <span className="live-banner-cluster">
        {health?.cluster_id ||
          (connectionState === 'checking' ? 'Connecting' : 'Local API')}
      </span>
      <span className="live-banner-sep">·</span>
      <span>search index {indexState}</span>
      {health ? (
        <>
          <span className="live-banner-sep">·</span>
          <span>{health.current_documents.toLocaleString()} docs</span>
          <span className="live-banner-sep">·</span>
          <span>engine {engineRelease(health.engine_version)}</span>
          <span className="live-banner-sep">·</span>
          <span>pgvector {health.pgvector_version || 'unreported'}</span>
        </>
      ) : (
        <>
          <span className="live-banner-sep">·</span>
          <span>
            {connectionState === 'checking'
              ? 'loading live corpus details'
              : 'start the API to inspect live data'}
          </span>
        </>
      )}
    </div>
  );
}

// Older descriptors may omit the server-rendered envelope. Retain this fallback
// for compatibility, but new descriptors include BEGIN/ROLLBACK and any required
// persona role so the copied query mirrors the read-only API request exactly.
function toPsql(descriptor: VerifySql): string {
  if (descriptor.rendered) return descriptor.rendered;
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

// The observed window is always shown with its verify affordance (Law 2). The
// lock-analysis link renders only when the deployment configured a resolvable
// console URL template, so no button points at an unverified URL.
function ObservabilityHandoff({ handoff }: { handoff?: ObservabilityRef }) {
  if (!handoff?.ref) return null;
  const { ref, links } = handoff;
  return (
    <span className="observability-handoff">
      <span className="observability-window">
        <Database size={12} aria-hidden="true" />
        observed window · {dateTime(ref.window_start)}
        {ref.window_end ? ` → ${dateTime(ref.window_end)}` : ' → open'}
      </span>
      {links.map((link) => (
        <a
          key={link.kind}
          className="observability-link"
          href={link.url}
          target="_blank"
          rel="noreferrer"
        >
          <ExternalLink size={12} aria-hidden="true" />
          {link.label}
        </a>
      ))}
      <VerifyAffordance
        descriptor={handoff._verify_sql}
        label="verify window in psql"
      />
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

function answerParagraphs(text: string): string[] {
  const Segmenter = (
    Intl as unknown as {
      Segmenter: new (
        locale: string,
        options: { granularity: 'sentence' },
      ) => {
        segment: (input: string) => Iterable<{ segment: string }>;
      };
    }
  ).Segmenter;
  const blocks = text
    .trim()
    .split(/\n{2,}/)
    .map((block) => block.replace(/\s+/g, ' ').trim())
    .filter(Boolean);
  if (blocks.length > 1) return blocks;

  const paragraphs: string[] = [];

  blocks.forEach((block) => {
    const segmented = Array.from(
      new Segmenter('en', { granularity: 'sentence' }).segment(block),
      ({ segment }) => segment.trim(),
    ).filter(Boolean);
    const sentences = segmented.reduce<string[]>((merged, sentence) => {
      const previous = merged[merged.length - 1];
      if (previous && /\b(?:vs|e\.g|i\.e)\.$/i.test(previous)) {
        merged[merged.length - 1] = `${previous} ${sentence}`;
      } else {
        merged.push(sentence);
      }
      return merged;
    }, []);
    let current = '';
    let sentenceCount = 0;

    sentences.forEach((sentence) => {
      const next = current ? `${current} ${sentence}` : sentence;
      if (current && (sentenceCount >= 2 || next.length > 760)) {
        paragraphs.push(current);
        current = sentence;
        sentenceCount = 1;
        return;
      }
      current = next;
      sentenceCount += 1;
    });
    if (current) paragraphs.push(current);
  });

  return paragraphs.length ? paragraphs : [text];
}

const INCIDENT_ANSWER_SECTIONS = [
  { label: 'Root cause', title: 'Why the incident happened' },
  { label: 'Inside PostgreSQL', title: 'Blocked writes and recovery' },
  { label: 'Application pool', title: 'Why some callers timed out' },
  { label: 'Query performance', title: 'Why ANALYZE did not help' },
] as const;

const LEGACY_INCIDENT_ANSWER_SECTIONS = [
  { label: 'Root cause', title: 'Why the incident happened' },
  { label: 'Inside PostgreSQL', title: 'Blocked writes and recovery' },
  {
    label: 'Application and query impact',
    title: 'Timeouts and the slow query',
  },
] as const;

function streamingAnswerParagraphs(text: string): string[] {
  return text
    .split(/\n{2,}/)
    .map((paragraph) => paragraph.replace(/\s+/g, ' ').trim())
    .filter(Boolean);
}

function AnswerNarrative({
  text,
  streaming = false,
  structured = false,
}: {
  text: string;
  streaming?: boolean;
  structured?: boolean;
}) {
  const paragraphs =
    streaming && structured
      ? streamingAnswerParagraphs(text)
      : answerParagraphs(text);
  const headings =
    streaming && structured
      ? INCIDENT_ANSWER_SECTIONS
      : paragraphs.length >= 4
        ? INCIDENT_ANSWER_SECTIONS
      : paragraphs.length === 3
        ? LEGACY_INCIDENT_ANSWER_SECTIONS
        : [];
  const sectionCount =
    streaming && structured
      ? Math.max(headings.length, paragraphs.length)
      : paragraphs.length;

  return (
    <div className={`answer-prose${streaming ? ' is-streaming' : ''}`}>
      {Array.from({ length: sectionCount }, (_, index) => {
        const paragraph = paragraphs[index] || '';
        const heading = structured ? headings[index] : undefined;
        const prose = paragraph ? (
          <p>
            <FormattedAnswer text={paragraph} />
            {streaming && index === paragraphs.length - 1 ? (
              <span className="answer-type-cursor" />
            ) : null}
          </p>
        ) : null;
        return heading ? (
          <section
            key={heading.label}
            className="answer-prose-section"
          >
            <header>
              <span className="section-label">{heading.label}</span>
              <h3>{heading.title}</h3>
            </header>
            {prose}
          </section>
        ) : (
          <div
            key={`${index}-${paragraph.slice(0, 24)}`}
            className="answer-prose-paragraph"
          >
            {prose}
          </div>
        );
      })}
    </div>
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

function RerankImpact({
  baseRank,
  finalRank,
  baseLabel,
}: {
  baseRank: number;
  finalRank: number;
  baseLabel: string;
}) {
  const delta = baseRank - finalRank;
  const direction = delta > 0 ? 'up' : delta < 0 ? 'down' : 'unchanged';
  const count = Math.abs(delta);
  const movement =
    direction === 'up'
      ? `Moved up ${count} ${count === 1 ? 'rank' : 'ranks'}`
      : direction === 'down'
        ? `Moved down ${count} ${count === 1 ? 'rank' : 'ranks'}`
        : 'Rank unchanged';
  const label = `${movement}: ${baseLabel} rank ${baseRank}, final rank ${finalRank}`;

  return (
    <span
      className={`rerank-impact impact-${direction}`}
      aria-label={label}
      title={label}
    >
      <strong aria-hidden="true">
        {direction === 'up' ? '▲' : direction === 'down' ? '▼' : '—'}
        {count || ''}
      </strong>
      <small>
        {direction === 'unchanged'
          ? `#${finalRank} unchanged`
          : `#${baseRank} → #${finalRank}`}
      </small>
    </span>
  );
}

function FinalRankedEvidence({
  candidates,
  rankingCandidates,
  selectedEvidenceId,
  reranked,
  retrievalMode,
  runId,
  verifySql,
  onSelect,
}: {
  candidates: Candidate[];
  rankingCandidates: Candidate[];
  selectedEvidenceId: string | null;
  reranked: boolean;
  retrievalMode: RetrievalMode;
  runId: string;
  verifySql?: RunReceipt["_verify_sql"];
  onSelect: (candidate: Candidate) => void;
}) {
  const isHybrid = retrievalMode === 'hybrid';
  const showText = isHybrid || retrievalMode === 'lexical';
  const showVector = isHybrid || retrievalMode === 'semantic';
  const showFuzzy = isHybrid || retrievalMode === 'fuzzy';
  const baseOrder = isHybrid
    ? fusedOrder(rankingCandidates)
    : rankingCandidates;
  const baseRanks = new Map(
    baseOrder.map((candidate, index) => [
      candidate,
      index + 1,
    ]),
  );
  const baseRankLabel =
    retrievalMode === 'hybrid'
      ? 'Aurora'
      : RETRIEVAL_MODE_LABELS[retrievalMode];
  const orderRule = finalOrderRule(retrievalMode, reranked);
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
  const topPrimaryScore = topCandidate
    ? rankingScore(topCandidate, retrievalMode)
    : null;
  const topBaseRank = topCandidate
    ? baseRanks.get(topCandidate) || 1
    : 1;
  const inspectedCandidate =
    candidates.find((candidate) => candidate.evidence_id === selectedEvidenceId) ||
    topCandidate;
  const inspectedEvidence = inspectedCandidate
    ? snapshot(inspectedCandidate)
    : null;

  return (
    <section className="final-ranked-evidence">
      <header>
        <div>
          <span className="section-label">Final ranked evidence</span>
          <h2 className="final-ranked-results-title">Search results</h2>
          <p>
            Start with the best matching evidence and why it ranked first.
            The persisted order and arm diagnostics remain available below.
          </p>
        </div>
        <span className={`status-pill ${runId ? 'ready' : 'pending'}`}>
          {runId ? `run ${compactId(runId)}` : 'awaiting retrieval'}
        </span>
      </header>

      {topCandidate && topEvidence ? (
        <>
          <div className="final-ranked-story final-ranked-what">
            <div className="final-ranked-story-heading">
              <span className="section-label">Top evidence excerpt</span>
              <h3 className="retrieval-story-title">
                Best <em>matching evidence</em>
              </h3>
            </div>
            <div className="final-ranked-outcome">
              <h4>{topEvidence.title || 'Untitled evidence'}</h4>
              <p>{topEvidence.snippet || 'No visible evidence excerpt.'}</p>
              <div className="final-ranked-outcome-meta">
                <code>{topEvidence.external_key || 'Unknown evidence'}</code>
                <span>
                  {KIND_LABELS[topEvidence.evidence_kind || 'incident']}
                </span>
                <span>{systemLabel(topEvidence.source_system)}</span>
              </div>
            </div>
          </div>

          <div className="final-ranked-story final-ranked-why">
            <div className="final-ranked-story-heading">
              <span className="section-label">Rank explanation</span>
              <h3 className="retrieval-story-title">
                <em>Why</em> this evidence ranked first
              </h3>
            </div>
            <p>
              {topRankExplanation(
                topCandidate,
                topEvidence,
                retrievalMode,
                reranked,
                topBaseRank,
              )}
            </p>
            <div className="final-ranked-why-signals">
              {topCandidate.explanation?.exact_identifier ? (
                <span>
                  <CircleDot size={11} />
                  exact match
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
              <span>
                {rankingScoreLabel(retrievalMode)}{' '}
                {score(
                  topPrimaryScore,
                  rankingScorePrecision(retrievalMode),
                )}
              </span>
              {reranked && topCandidate.rerank_score != null ? (
                <span>Cohere {score(topCandidate.rerank_score, 3)}</span>
              ) : null}
            </div>
          </div>

          <aside className="rank-order-note" aria-label="Final ranking rule">
            <span className="rank-order-icon" aria-hidden="true">
              <GitMerge size={19} />
            </span>
            <span className="rank-order-copy">
              <span className="rank-order-label">Final-order rule</span>
              <strong>{orderRule.rule}</strong>
              <small>{orderRule.note}</small>
            </span>
          </aside>
          <div className="ranked-results-workspace">
            <div className="ranked-results-table-wrap">
              <table
                className={`ranked-results-table ${
                  isHybrid ? 'hybrid' : 'single-signal'
                } ${reranked ? 'reranked' : ''}`}
              >
                <thead>
                  <tr>
                    <th className="result-rank-column">
                      <span>Final</span>
                      <small>rank</small>
                    </th>
                    {reranked ? (
                      <th className="result-impact-column">
                        <span>Rank</span>
                        <small>impact</small>
                      </th>
                    ) : null}
                    <th className="result-evidence-column">Evidence</th>
                    <th className="result-type-column">Type</th>
                    {showText ? (
                      <th className="arm-rank-column group-start">
                        <span>Full-text</span>
                        <small>rank</small>
                      </th>
                    ) : null}
                    {showVector ? (
                      <th className="arm-rank-column group-start">
                        <span>Semantic</span>
                        <small>rank</small>
                      </th>
                    ) : null}
                    {showFuzzy ? (
                      <th className="arm-rank-column group-start">
                        <span>Fuzzy</span>
                        <small>rank</small>
                      </th>
                    ) : null}
                    <th className="result-score-column primary-score-column group-start">
                      {rankingScoreLabel(retrievalMode)}
                    </th>
                    {reranked ? (
                      <th className="result-score-column cohere-score-column">
                        Cohere score
                      </th>
                    ) : null}
                    <th
                      className="result-open-column"
                      aria-label="Open evidence"
                    />
                  </tr>
                </thead>
                <tbody>
                  {candidates.map((candidate, index) => {
                    const item = snapshot(candidate);
                    const finalRank = candidate.result_rank || index + 1;
                    const baseRank =
                      baseRanks.get(candidate) || finalRank;
                    const selected =
                      candidate.evidence_id === inspectedCandidate?.evidence_id;
                    return (
                      <tr
                        key={`${candidate.evidence_id}-${index}`}
                        className={selected ? 'selected' : ''}
                        tabIndex={0}
                        aria-selected={selected}
                        onClick={() => onSelect(candidate)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault();
                            onSelect(candidate);
                          }
                        }}
                      >
                        <td className="result-rank-column">
                          {finalRank}
                        </td>
                        {reranked ? (
                          <td className="result-impact-column">
                            <RerankImpact
                              baseRank={baseRank}
                              finalRank={finalRank}
                              baseLabel={baseRankLabel}
                            />
                          </td>
                        ) : null}
                        <td className="result-evidence-column">
                          <strong>{item.external_key || 'Unknown evidence'}</strong>
                          <span>{item.title || 'Untitled evidence'}</span>
                        </td>
                        <td className="result-type-column">
                          {KIND_LABELS[item.evidence_kind || 'incident']}
                        </td>
                        {showText ? (
                          <td className="arm-rank-column group-start">
                            {rankLabel(position(candidate, 'text'))}
                          </td>
                        ) : null}
                        {showVector ? (
                          <td className="arm-rank-column group-start">
                            {rankLabel(position(candidate, 'vector'))}
                          </td>
                        ) : null}
                        {showFuzzy ? (
                          <td className="arm-rank-column group-start">
                            {rankLabel(position(candidate, 'fuzzy'))}
                          </td>
                        ) : null}
                        <td className="result-score-column primary-score-column group-start">
                          <code>
                            {score(
                              rankingScore(candidate, retrievalMode),
                              rankingScorePrecision(retrievalMode),
                            )}
                          </code>
                        </td>
                        {reranked ? (
                          <td className="result-score-column cohere-score-column">
                            <code>{score(candidate.rerank_score, 3)}</code>
                          </td>
                        ) : null}
                        <td className="result-open-column">
                          <ChevronRight size={15} aria-hidden="true" />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {inspectedCandidate && inspectedEvidence ? (
              <aside className="ranked-result-inspector">
                <span className="section-label">Selected evidence</span>
                <h3>{inspectedEvidence.external_key}</h3>
                <strong>{inspectedEvidence.title}</strong>
                <p>
                  {inspectedEvidence.snippet || 'No visible evidence excerpt.'}
                </p>
                <dl>
                  {showText ? (
                    <div>
                      <dt>Full-text</dt>
                      <dd>{rankLabel(position(inspectedCandidate, 'text'))}</dd>
                    </div>
                  ) : null}
                  {showVector ? (
                    <div>
                      <dt>Semantic</dt>
                      <dd>{rankLabel(position(inspectedCandidate, 'vector'))}</dd>
                    </div>
                  ) : null}
                  {showFuzzy ? (
                    <div>
                      <dt>Fuzzy</dt>
                      <dd>{rankLabel(position(inspectedCandidate, 'fuzzy'))}</dd>
                    </div>
                  ) : null}
                  <div>
                    <dt>{rankingScoreLabel(retrievalMode)}</dt>
                    <dd>
                      {score(
                        rankingScore(inspectedCandidate, retrievalMode),
                        rankingScorePrecision(retrievalMode),
                      )}
                    </dd>
                  </div>
                  {reranked ? (
                    <>
                      <div>
                        <dt>Cohere</dt>
                        <dd>{score(inspectedCandidate.rerank_score, 3)}</dd>
                      </div>
                      <div>
                        <dt>Rank impact</dt>
                        <dd>
                          <RerankImpact
                            baseRank={
                              baseRanks.get(inspectedCandidate) ||
                              inspectedCandidate.result_rank ||
                              1
                            }
                            finalRank={inspectedCandidate.result_rank || 1}
                            baseLabel={baseRankLabel}
                          />
                        </dd>
                      </div>
                    </>
                  ) : null}
                </dl>
                <footer>
                  <span>
                    {isHybrid
                      ? tierLabel(matchTier(inspectedCandidate))
                      : `${RETRIEVAL_MODE_LABELS[retrievalMode]} retrieval`}
                  </span>
                  <code>{compactId(inspectedCandidate.evidence_id || '')}</code>
                </footer>
              </aside>
            ) : null}
          </div>
          {verifySql ? (
            <section className="retrieval-code-editor">
              <div>
                <span className="section-label">Code Editor queries</span>
                <h3>Reproduce this retrieval</h3>
                <p>
                  Copy the exact read-only statements for this persisted run.
                  Each transaction rolls back after it reads the recorded result.
                </p>
              </div>
              <div className="retrieval-code-editor-actions">
                <VerifyAffordance
                  descriptor={verifySql.run}
                  label="retrieval run in psql"
                />
                <VerifyAffordance
                  descriptor={verifySql.candidates}
                  label="ranked evidence in psql"
                />
              </div>
            </section>
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
}) {
  return (
    <section className="retrieval-arm">
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
        {current?.captured_at ? (
          <span className="query-plan-context">
            <b>Captured on this cluster</b>
            {dateTime(current.captured_at)}
          </span>
        ) : null}
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
                  const planRelation =
                    scan.schema && scan.relation
                      ? `${scan.schema}.${scan.relation}`
                      : scan.relation || '';
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
                        <small>{planRelation || 'working set'}</small>
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
                      {scan.node_type === 'Seq Scan' &&
                      planRelation.startsWith('retrieval.') ? (
                        <p className="plan-note">
                          A sequential scan here is the planner making the right
                          call. At this corpus size, scanning every chunk costs
                          less than descending an index.
                        </p>
                      ) : null}
                      {scan.node_type === 'Seq Scan' &&
                      planRelation === 'workbench_lab.orders' ? (
                        <p className="plan-note plan-note--incident">
                          This sequential scan is the incident: the filter
                          discards most rows it reads. ANALYZE cannot add the
                          missing access path.
                        </p>
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

function SignalPosition({ positionValue }: { positionValue: number | null }) {
  return positionValue === null ? (
    <span className="signal-empty">absent</span>
  ) : (
    <strong className="signal-position">#{positionValue}</strong>
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
  const [expandedCandidate, setExpandedCandidate] = useState<string | null>(
    null,
  );
  const auroraRanks = new Map(
    fusedOrder(candidates).map((candidate, index) => [candidate, index + 1]),
  );

  return (
    <>
      <div className="table-scroll fusion-table fusion-table-desktop">
        <table>
          <thead>
            <tr>
              <th>
                Order
                <small>{rerankVisible ? 'Aurora → final' : 'final rank'}</small>
              </th>
              <th>Tier</th>
              <th>Evidence</th>
              <th>
                Full-text
                <small>position</small>
              </th>
              <th>
                Semantic
                <small>position</small>
              </th>
              <th>
                Fuzzy
                <small>position</small>
              </th>
              <th>
                PostgreSQL RRF
                <small>arm subtotal</small>
              </th>
              <th>
                <span className="visually-hidden">Raw diagnostics</span>
              </th>
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
              const candidateKey =
                candidate.evidence_id || `fusion-candidate-${index}`;
              const expanded = expandedCandidate === candidateKey;
              const finalRank = candidate.result_rank || index + 1;
              const auroraRank = auroraRanks.get(candidate) || finalRank;
              return (
                <Fragment key={candidateKey}>
                  <tr
                    className="selectable-row"
                    onClick={() => onSelect(candidate)}
                  >
                    <td className="fusion-order-cell">
                      {rerankVisible ? (
                        <RerankImpact
                          baseRank={auroraRank}
                          finalRank={finalRank}
                          baseLabel="Aurora"
                        />
                      ) : (
                        <strong>#{finalRank}</strong>
                      )}
                    </td>
                    <td>
                      <span className={`tier-chip tier-${tier}`}>
                        {tier === 1 ? <CircleDot size={10} /> : null}
                        {tier === 1 ? 'exact' : 'fused'}
                      </span>
                    </td>
                    <td className="fusion-evidence-cell">
                      <strong>{item.external_key}</strong>
                      <span>{item.title}</span>
                    </td>
                    <td>
                      <SignalPosition
                        positionValue={position(candidate, 'text')}
                      />
                    </td>
                    <td>
                      <SignalPosition
                        positionValue={position(candidate, 'vector')}
                      />
                    </td>
                    <td>
                      <SignalPosition
                        positionValue={position(candidate, 'fuzzy')}
                      />
                    </td>
                    <td>
                      <div className="fusion-rrf-cell">
                        <strong>
                          {score(candidate.rrf_score ?? total, 5)}
                        </strong>
                        <div
                          className="contribution-bar"
                          style={{
                            width: `${Math.max((total / maximum) * 100, 4)}%`,
                          }}
                          aria-label={`Text ${text.toFixed(
                            5,
                          )}, semantic ${vector.toFixed(
                            5,
                          )}, fuzzy ${fuzzy.toFixed(5)}`}
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
                      </div>
                    </td>
                    <td className="fusion-details-cell">
                      <button
                        type="button"
                        className="fusion-row-toggle"
                        aria-label={`${
                          expanded ? 'Hide' : 'Show'
                        } raw diagnostics for ${
                          item.external_key || 'candidate'
                        }`}
                        aria-expanded={expanded}
                        onClick={(event) => {
                          event.stopPropagation();
                          setExpandedCandidate(expanded ? null : candidateKey);
                        }}
                      >
                        <ChevronRight size={16} aria-hidden="true" />
                      </button>
                    </td>
                  </tr>
                  {expanded ? (
                    <tr className="fusion-diagnostic-row">
                      <td colSpan={8}>
                        <FusionCandidateDiagnostics
                          candidate={candidate}
                          controls={controls}
                          rerankVisible={rerankVisible}
                        />
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="fusion-mobile-candidates">
        {candidates.map((candidate, index) => {
          const item = snapshot(candidate);
          const tier = matchTier(candidate);
          const candidateKey =
            candidate.evidence_id || `fusion-mobile-candidate-${index}`;
          const expanded = expandedCandidate === candidateKey;
          const finalRank = candidate.result_rank || index + 1;
          const auroraRank = auroraRanks.get(candidate) || finalRank;
          return (
            <article key={candidateKey} className="fusion-mobile-candidate">
              <button
                type="button"
                className="fusion-mobile-summary"
                aria-expanded={expanded}
                onClick={() =>
                  setExpandedCandidate(expanded ? null : candidateKey)
                }
              >
                <span className="fusion-mobile-order">
                  {rerankVisible ? (
                    <RerankImpact
                      baseRank={auroraRank}
                      finalRank={finalRank}
                      baseLabel="Aurora"
                    />
                  ) : (
                    <strong>#{finalRank}</strong>
                  )}
                </span>
                <span className="fusion-mobile-copy">
                  <strong>{item.external_key}</strong>
                  <small>{item.title}</small>
                </span>
                <span className={`tier-chip tier-${tier}`}>
                  {tier === 1 ? <CircleDot size={10} /> : null}
                  {tier === 1 ? 'exact' : 'fused'}
                </span>
                <ChevronRight
                  className={expanded ? 'open' : ''}
                  size={17}
                  aria-hidden="true"
                />
              </button>
              <div className="fusion-mobile-positions">
                <span>
                  Full-text
                  <SignalPosition
                    positionValue={position(candidate, 'text')}
                  />
                </span>
                <span>
                  Semantic
                  <SignalPosition
                    positionValue={position(candidate, 'vector')}
                  />
                </span>
                <span>
                  Fuzzy
                  <SignalPosition
                    positionValue={position(candidate, 'fuzzy')}
                  />
                </span>
                <span>
                  PostgreSQL RRF
                  <strong>
                    {score(
                      candidate.rrf_score ??
                        armContribution(candidate, 'text', controls) +
                          armContribution(candidate, 'vector', controls) +
                          armContribution(candidate, 'fuzzy', controls),
                      5,
                    )}
                  </strong>
                </span>
              </div>
              {expanded ? (
                <div className="fusion-mobile-details">
                  <FusionCandidateDiagnostics
                    candidate={candidate}
                    controls={controls}
                    rerankVisible={rerankVisible}
                  />
                  <button
                    type="button"
                    className="text-command"
                    onClick={() => onSelect(candidate)}
                  >
                    <FileSearch size={14} />
                    Inspect evidence
                  </button>
                </div>
              ) : null}
            </article>
          );
        })}
      </div>
    </>
  );
}

function FusionCandidateDiagnostics({
  candidate,
  controls,
  rerankVisible,
}: {
  candidate: Candidate;
  controls: Controls;
  rerankVisible: boolean;
}) {
  const evidence = snapshot(candidate);
  const diagnostics = [
    {
      label: 'Full-text diagnostic',
      raw: candidate.text_rank,
      contribution: armContribution(candidate, 'text', controls),
      present: position(candidate, 'text') !== null,
    },
    {
      label: 'Semantic diagnostic',
      raw: candidate.vector_score,
      contribution: armContribution(candidate, 'vector', controls),
      present: position(candidate, 'vector') !== null,
    },
    {
      label: 'Fuzzy diagnostic',
      raw: candidate.trigram_score,
      contribution: armContribution(candidate, 'fuzzy', controls),
      present: position(candidate, 'fuzzy') !== null,
    },
  ];

  return (
    <div className="fusion-diagnostic-grid">
      {diagnostics.map((diagnostic) => (
        <span key={diagnostic.label}>
          <small>{diagnostic.label}</small>
          <strong>
            {diagnostic.present ? score(diagnostic.raw, 3) : 'absent'}
          </strong>
          <code>
            {diagnostic.present
              ? `+${diagnostic.contribution.toFixed(5)}`
              : '+0 to RRF'}
          </code>
        </span>
      ))}
      <span>
        <small>PostgreSQL RRF</small>
        <strong>
          {score(candidate.rrf_score ?? candidate.final_score, 5)}
        </strong>
        <code>relative rank</code>
      </span>
      <span>
        <small>Source system</small>
        <strong>{evidence.source_system || 'unavailable'}</strong>
        <code>authoritative scope</code>
      </span>
      <span>
        <small>Source URI</small>
        <strong title={evidence.source_uri}>{evidence.source_uri || 'unavailable'}</strong>
        <code>captured record</code>
      </span>
      <span>
        <small>Source revision</small>
        <strong title={evidence.source_revision}>
          {evidence.source_revision || 'unavailable'}
        </strong>
        <code>persisted version</code>
      </span>
      {rerankVisible ? (
        <span>
          <small>Cohere rerank</small>
          <strong>{score(candidate.rerank_score, 3)}</strong>
          <code>post-fusion diagnostic</code>
        </span>
      ) : null}
    </div>
  );
}

function FusionBacktrace({
  candidates,
  selectedEvidenceId,
  controls,
  reranked,
  onSelect,
}: {
  candidates: Candidate[];
  selectedEvidenceId: string | null;
  controls: Controls;
  reranked: boolean;
  onSelect: (candidate: Candidate) => void;
}) {
  const selected =
    candidates.find(
      (candidate) => candidate.evidence_id === selectedEvidenceId,
    ) || candidates[0];
  if (!selected) return null;
  const selectedFinalRank =
    selected.result_rank || candidates.indexOf(selected) + 1;
  const selectedAuroraRank = fusedOrder(candidates).indexOf(selected) + 1;
  const item = snapshot(selected);
  const signals = [
    {
      key: 'text',
      label: 'Full-text',
      position: position(selected, 'text'),
      raw: selected.text_rank,
      contribution: armContribution(selected, 'text', controls),
    },
    {
      key: 'vector',
      label: 'Semantic',
      position: position(selected, 'vector'),
      raw: selected.vector_score,
      contribution: armContribution(selected, 'vector', controls),
    },
    {
      key: 'fuzzy',
      label: 'Fuzzy',
      position: position(selected, 'fuzzy'),
      raw: selected.trigram_score,
      contribution: armContribution(selected, 'fuzzy', controls),
    },
  ] as const;

  return (
    <section className="fusion-backtrace">
      <header>
        <div>
          <span className="section-label">Read-only backward trace</span>
          <h3>Trace one final result back to its ranked arms</h3>
        </div>
        <span className="status-pill">persisted signals</span>
      </header>
      <div className="fusion-trace-picker" aria-label="Final ranked candidates">
        {candidates.slice(0, 6).map((candidate, index) => {
          const candidateItem = snapshot(candidate);
          const active = candidate.evidence_id === selected.evidence_id;
          return (
            <button
              type="button"
              key={candidate.evidence_id || index}
              className={active ? 'active' : ''}
              aria-pressed={active}
              onClick={() => onSelect(candidate)}
            >
              <span>#{candidate.result_rank || index + 1}</span>
              <strong>{candidateItem.external_key}</strong>
            </button>
          );
        })}
      </div>
      <div className="fusion-trace-path">
        <div className="fusion-trace-signals">
          {signals.map((signal) => (
            <article
              key={signal.key}
              className={`trace-signal trace-${signal.key} ${
                signal.position === null ? 'absent' : ''
              }`}
            >
              <span>{signal.label}</span>
              <strong>
                {signal.position === null ? 'Absent' : `#${signal.position}`}
              </strong>
              <small>
                {signal.position === null
                  ? '+0 to RRF'
                  : `raw ${score(signal.raw, 3)} · +${signal.contribution.toFixed(
                      5,
                    )}`}
              </small>
            </article>
          ))}
        </div>
        <ArrowRight size={18} aria-hidden="true" />
        <article className="fusion-trace-rrf">
          <GitMerge size={17} />
          <span>Weighted RRF</span>
          <strong>{score(selected.rrf_score ?? selected.final_score, 5)}</strong>
          <small>
            {controls.textWeight}:{controls.vectorWeight}:{controls.fuzzyWeight}{' '}
            · k={controls.rrfK}
          </small>
        </article>
        <ArrowRight size={18} aria-hidden="true" />
        <article className="fusion-trace-final">
          <FileCheck2 size={17} />
          <span>Final rank {selectedFinalRank}</span>
          <strong>{item.external_key}</strong>
          <small>
            {reranked && selected.rerank_score != null
              ? `Aurora #${selectedAuroraRank} → final #${selectedFinalRank} · Cohere ${score(
                  selected.rerank_score,
                  3,
                )}`
              : 'Aurora order retained'}
          </small>
        </article>
      </div>
      <footer>
        {selected.explanation?.exact_identifier ? (
          <span>
            <CircleDot size={12} />
            Exact-identifier tier precedes fused candidates
          </span>
        ) : (
          <span>Only persisted integer positions feed this trace.</span>
        )}
        <code>{compactId(selected.evidence_id)}</code>
      </footer>
    </section>
  );
}

function FusionImplementationDetails({
  controls,
  runId,
}: {
  controls: Controls;
  runId: string;
}) {
  return (
    <details className="fusion-implementation-details">
      <summary>
        <span className="fusion-implementation-icon">
          <Code2 size={17} />
        </span>
        <span>
          <small>Implementation details</small>
          <strong>Weighted RRF formula and applied SQL</strong>
        </span>
        <ChevronRight size={18} aria-hidden="true" />
      </summary>
      <div className="fusion-implementation-body">
        <div className="rrf-formula-panel">
          <div className="rrf-formula-intro">
            <span className="section-label">Weighted RRF formula</span>
            <small>For each evidence item d</small>
          </div>
          <div
            className="rrf-formula-expression"
            aria-label={`RRF of d equals ${controls.textWeight} over ${controls.rrfK} plus text rank, plus ${controls.vectorWeight} over ${controls.rrfK} plus semantic rank, plus ${controls.fuzzyWeight} over ${controls.rrfK} plus fuzzy rank`}
          >
            <strong>RRF(d)</strong>
            <b>=</b>
            <span className="rrf-fraction">
              <i>{controls.textWeight}</i>
              <small>
                {controls.rrfK} + r<sub>text</sub>(d)
              </small>
            </span>
            <b>+</b>
            <span className="rrf-fraction">
              <i>{controls.vectorWeight}</i>
              <small>
                {controls.rrfK} + r<sub>semantic</sub>(d)
              </small>
            </span>
            <b>+</b>
            <span className="rrf-fraction">
              <i>{controls.fuzzyWeight}</i>
              <small>
                {controls.rrfK} + r<sub>fuzzy</sub>(d)
              </small>
            </span>
          </div>
          <div className="rrf-formula-notes">
            <span>
              <b>k={controls.rrfK}</b> dampens rank outliers
            </span>
            <span>missing arm = 0</span>
            <span>Cohere is not part of this formula</span>
          </div>
        </div>
        <section className="sql-panel">
          <header>
            <span>Applied ranking rule</span>
            <span>run {compactId(runId)}</span>
          </header>
          <pre>
            <code>{`rrf_score =
  ${controls.textWeight} / (${controls.rrfK} + text_position)
+ ${controls.vectorWeight} / (${controls.rrfK} + vector_position)
+ ${controls.fuzzyWeight} / (${controls.rrfK} + trigram_position)

-- a missing arm contributes zero
-- exact identifiers form a deterministic tier above fused rows
ORDER BY
  match_tier,
  exact_identifier_position,
  rrf_score DESC
LIMIT ${controls.limit};`}</code>
          </pre>
        </section>
      </div>
    </details>
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
            Optional post-fusion ordering; PostgreSQL RRF remains persisted
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
            <span>HNSW iterative scan</span>
            <select
              value={controls.iterativeScan}
              onChange={(event) =>
                onChange(
                  'iterativeScan',
                  event.target.value as IterativeScanMode,
                )
              }
            >
              {(
                Object.entries(ITERATIVE_SCAN_LABELS) as Array<
                  [IterativeScanMode, string]
                >
              ).map(([mode, label]) => (
                <option key={mode} value={mode}>
                  {label}
                </option>
              ))}
            </select>
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
    telemetry: 610,
  };
  const byKind: Record<EvidenceKind, GraphNode[]> = {
    incident: [],
    change: [],
    lock_evidence: [],
    telemetry: [],
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

function ProofChainOfCustody({
  receipt,
  personaMode,
  selectedCitationNumber,
  onSelectCitation,
}: {
  receipt: RunReceipt | null;
  personaMode: boolean;
  selectedCitationNumber: number;
  onSelectCitation: (citationNumber: number) => void;
}) {
  const citations = receipt?.answer?.citations || [];
  if (!receipt || !citations.length) {
    return (
      <section className="custody-section empty">
        <Empty
          icon={<ShieldCheck size={20} />}
          title="No cited proof is loaded"
          detail="Load a completed answer run to trace a claim through its persisted citation."
        />
      </section>
    );
  }
  const citation =
    citations.find(
      (item) =>
        (item.citation_number || item.n || 1) === selectedCitationNumber,
    ) || citations[0];
  const citationNumber = citation.citation_number || citation.n || 1;
  const candidate = receipt.candidates.find(
    (item) => item.evidence_id === citation.evidence_id,
  );
  const item = candidate ? snapshot(candidate) : null;
  const validationStatus = receipt.answer?.validation_status || 'persisted';
  const persona = personaLabel(receipt.run.role);
  const persistedClaim = citation.claim?.trim();
  const claim = persistedClaim || citationContext(citation);
  const claimLabel = persistedClaim ? 'Claim' : 'Source context';

  const steps: Array<{
    label: string;
    value: string;
    meta: string;
    Icon: typeof FileCheck2;
  }> = [
    {
      label: claimLabel,
      value: claim,
      meta: `${claimLabel} ${citationNumber} of ${citations.length}`,
      Icon: FileCheck2,
    },
    {
      label: 'Evidence',
      value: citation.external_key,
      meta: `${citation.title} · revision ${citation.source_revision}`,
      Icon: FileSearch,
    },
    {
      label: 'Retrieved by',
      value: receipt.run.retrieval_mode,
      meta: candidate
        ? `Final rank ${candidate.result_rank || '—'} · ${
            receipt.run.retrieval_mode === 'hybrid'
              ? `RRF ${score(candidate.rrf_score, 5)}`
              : `raw ${score(candidate.final_score, 3)}`
          }`
        : 'Cited from a supporting retrieval run',
      Icon: SlidersHorizontal,
    },
    {
      label: 'Verified by',
      value: personaMode ? 'Citation + ACL' : 'Citation validation',
      meta: personaMode
        ? `${validationStatus} · viewing as ${persona}`
        : validationStatus,
      Icon: ShieldCheck,
    },
    {
      label: 'Persisted in',
      value: compactId(receipt.run.run_id),
      meta: `${dateTime(receipt.run.completed_at)} · proof schema`,
      Icon: Database,
    },
    {
      label: 'Used in answer',
      value: `Citation ${citationNumber}`,
      meta: `${citations.length} citation${citations.length === 1 ? '' : 's'} in answer record`,
      Icon: Check,
    },
  ];

  return (
    <section className="custody-section">
      <header>
        <div>
          <span className="section-label">Persisted chain of custody</span>
          <h2>
            {persistedClaim
              ? 'Follow a claim to its exact source span'
              : 'Follow source context to its exact source span'}
          </h2>
        </div>
        <span
          className={`status-pill ${
            validationStatus === 'valid' ? 'ready' : ''
          }`}
        >
          {validationStatus}
        </span>
      </header>
      <div className="custody-claims" aria-label="Cited sources">
        {citations.map((itemCitation, index) => {
          const number = itemCitation.citation_number || itemCitation.n || index + 1;
          return (
            <button
              type="button"
              key={`${itemCitation.evidence_id}-${number}`}
              className={number === citationNumber ? 'active' : ''}
              aria-pressed={number === citationNumber}
              onClick={() => onSelectCitation(number)}
            >
              <span>{number}</span>
              <strong>{itemCitation.external_key}</strong>
              <small>
                {itemCitation.claim?.trim()
                  ? itemCitation.claim
                  : `Source context: ${citationContext(itemCitation)}`}
              </small>
            </button>
          );
        })}
      </div>
      <div className="custody-chain">
        {steps.map(({ label, value, meta, Icon }, index) => (
          <article key={label}>
            <span className="custody-step-label">
              <Icon size={12} />
              {label}
            </span>
            <strong>{value}</strong>
            <small>{meta}</small>
            <i aria-hidden="true">
              <Check size={10} />
            </i>
            {index < steps.length - 1 ? (
              <ArrowRight
                className="custody-arrow"
                size={15}
                aria-hidden="true"
              />
            ) : null}
          </article>
        ))}
      </div>
      <div className="custody-source">
        <div>
          <span className="section-label">Evidence identity</span>
          <dl>
            <div>
              <dt>Evidence</dt>
              <dd>{citation.external_key}</dd>
            </div>
            <div>
              <dt>Kind</dt>
              <dd>{item?.evidence_kind || 'cited evidence'}</dd>
            </div>
            <div>
              <dt>Revision</dt>
              <dd>{citation.source_revision}</dd>
            </div>
            {personaMode ? (
              <div>
                <dt>Viewing as</dt>
                <dd>{persona}</dd>
              </div>
            ) : null}
            <div>
              <dt>Document version</dt>
              <dd title={citation.document_version_id}>
                {compactId(citation.document_version_id)}
              </dd>
            </div>
            <div>
              <dt>Chunk version</dt>
              <dd title={citation.chunk_version_id}>
                {compactId(citation.chunk_version_id)}
              </dd>
            </div>
          </dl>
          <code>{citation.source_uri}</code>
        </div>
        <blockquote>
          <span className="section-label">Exact cited quote</span>
          <p>{citation.quote_text || 'No quote text was returned.'}</p>
          <footer>
            citation {citationNumber} · {compactId(citation.chunk_version_id)}
          </footer>
        </blockquote>
      </div>
    </section>
  );
}

export default function WorkbenchApp() {
  const [module, setModule] = useState<ModuleName>('home');
  const [diagnoseTab, setDiagnoseTab] =
    useState<DiagnoseTab>('results');
  const [proveTab, setProveTab] = useState<ProveTab>('answer');
  const [controls, setControls] = useState<Controls>(DEFAULT_CONTROLS);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const runQuestion = liveQuestion(health?.run);
  const presets = useMemo(() => livePresets(health?.run), [health?.run]);
  const agentExamples = useMemo(
    () => liveAgentExamples(health?.run),
    [health?.run],
  );
  const retrievalReady = health?.status === 'ready' && health?.run != null;
  const personaMode = health?.security_mode === 'persona';
  const [connectionState, setConnectionState] =
    useState<ConnectionState>('checking');
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
  const [supervision, setSupervision] =
    useState<SupervisionReceipt | null>(null);
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
  const [proofRunDraft, setProofRunDraft] = useState('');
  const [selectedProofCitation, setSelectedProofCitation] = useState(1);
  const [replayKey, setReplayKey] = useState(0);
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
    useState<AgentStreamState>('idle');
  const [streamingAnswer, setStreamingAnswer] = useState('');
  const [agentTrace, setAgentTrace] = useState<AgentTraceEvent[]>([]);
  const [agentTraceExpanded, setAgentTraceExpanded] = useState(false);
  const [streamCitations, setStreamCitations] = useState<Citation[]>([]);
  const [visibleCitationCount, setVisibleCitationCount] = useState(0);
  const [agentCommentary, setAgentCommentary] = useState('');
  const [agentLatencyMs, setAgentLatencyMs] = useState<number | null>(null);
  const [homeQueryText, setHomeQueryText] = useState('');
  const [homeTyping, setHomeTyping] = useState(true);
  const [homeReceiptLoading, setHomeReceiptLoading] = useState(true);
  const [fusionRunRequest, setFusionRunRequest] = useState(0);
  const [navCollapsed, setNavCollapsed] = useState(
    () => window.localStorage.getItem('workbench-nav-collapsed') === 'true',
  );
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [referenceOpen, setReferenceOpen] = useState(false);
  const homeTypingInterrupted = useRef(false);
  const lastCompletedSearchKey = useRef<string | null>(null);
  const processedFusionRunRequest = useRef(0);
  const roleTransitionVersion = useRef(0);

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
    window.localStorage.setItem('workbench-nav-collapsed', String(navCollapsed));
  }, [navCollapsed]);

  useEffect(() => {
    if (!runQuestion) {
      setHomeQueryText('');
      setHomeTyping(false);
      return;
    }
    homeTypingInterrupted.current = false;
    setHomeTyping(true);
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setHomeQueryText(runQuestion);
      setHomeTyping(false);
      return;
    }

    let character = 0;
    let timer = 0;
    const typeNext = () => {
      if (homeTypingInterrupted.current) return;
      character += 1;
      setHomeQueryText(runQuestion.slice(0, character));
      if (character >= runQuestion.length) {
        setHomeTyping(false);
        return;
      }
      const typed = runQuestion[character - 1];
      timer = window.setTimeout(
        typeNext,
        typed === ',' || typed === '?' ? 80 : typed === ' ' ? 24 : 14,
      );
    };

    timer = window.setTimeout(typeNext, 220);
    return () => window.clearTimeout(timer);
  }, [runQuestion]);

  useEffect(() => {
    let cancelled = false;
    api<Health>('/ready')
      .then((ready) => {
        if (!cancelled) {
          setHealth(ready);
          setConnectionState('ready');
          const readyPresets = livePresets(ready.run);
          const routePreset =
            initialRoute.surface === 'retrieval' && initialRoute.preset
              ? readyPresets.find(
                  (entry) => entry.presetKey === initialRoute.preset,
                )
              : undefined;
          const query = routePreset?.query || liveQuestion(ready.run);
          setControls((current) => ({
            ...current,
            query,
            mode: routePreset?.mode || current.mode,
            kind: routePreset?.kind || current.kind,
            clusterId: routePreset?.clusterId || current.clusterId,
            rerank: routePreset?.rerank ?? current.rerank,
          }));
        }
      })
      .catch(() => {
        if (!cancelled) setConnectionState('unavailable');
      });
    api<SearchIndexDiagnostics>('/v1/diagnostics/search-index')
      .then((searchIndex) => {
        if (!cancelled) setDiagnostics(searchIndex);
      })
      .catch(() => undefined);
    // Apply the initial deep link (SPEC 6.0). Navigation is synchronous; the run
    // to load is chosen below so a /proof/{run_id} link wins over latest-run.
    const initialRoute = parseRoute(window.location.hash);
    if (initialRoute.surface === 'agent' && initialRoute.role) {
      setPersona(initialRoute.role);
    }
    const initialRole =
      initialRoute.surface === 'agent' && initialRoute.role
        ? initialRoute.role
        : controls.role;
    goTo(initialRoute.surface as Surface, initialRoute.lens);
    const deepLinkedRun =
      initialRoute.surface === 'proof' ? initialRoute.runId : undefined;
    const initialLoadVersion = roleTransitionVersion.current;
    void (async () => {
      try {
        const targetRun =
          deepLinkedRun ??
          (
            await api<{ run_id: string }>(
              `/v1/runs/latest?role=${encodeURIComponent(initialRole)}`,
            )
          ).run_id;
        if (
          !cancelled &&
          initialLoadVersion === roleTransitionVersion.current
        ) {
          await loadRun(targetRun, undefined, false, initialRole);
        }
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
    if (health?.security_mode !== 'core' || controls.role === DEFAULT_PERSONA) {
      return;
    }
    setPersona(DEFAULT_PERSONA);
  }, [health?.security_mode, controls.role]);

  useEffect(() => {
    if (!selectedEvidenceId) {
      setEvidenceDetail(null);
      return;
    }
    let cancelled = false;
    const transitionVersion = roleTransitionVersion.current;
    api<EvidenceDetail>(
      `/v1/evidence/${selectedEvidenceId}?role=${encodeURIComponent(controls.role)}`,
    )
      .then((detail) => {
        if (
          !cancelled &&
          transitionVersion === roleTransitionVersion.current
        ) {
          setEvidenceDetail(detail);
        }
      })
      .catch(() => {
        if (
          !cancelled &&
          transitionVersion === roleTransitionVersion.current
        ) {
          setEvidenceDetail(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedEvidenceId, controls.role]);

  function setControl<K extends keyof Controls>(key: K, value: Controls[K]) {
    setControls((current) => ({ ...current, [key]: value }));
  }

  function clearLoadedProofState() {
    setCandidates([]);
    setSelectedEvidenceId(null);
    setEvidenceDetail(null);
    setReceipt(null);
    setGraph(null);
    setTimeline(null);
    setSupervision(null);
    setAnswer(null);
    setRunId('');
    setSelectedProofCitation(1);
  }

  function clearAgentState() {
    setAgentStreamState('idle');
    setStreamingAnswer('');
    setAgentTrace([]);
    setAgentTraceExpanded(false);
    setStreamCitations([]);
    setVisibleCitationCount(0);
    setAgentCommentary('');
    setAgentLatencyMs(null);
  }

  function setAgentQuestion(question: string) {
    setControl('query', question);
    if (question === answer?.question) return;
    setAnswer(null);
    clearAgentState();
  }

  function clearRoleBoundState() {
    clearLoadedProofState();
    clearAgentState();
    setProofRunDraft('');
    setEvaluation(null);
    setQueryPlan(null);
    setPlanOpen(false);
    setCandidateReceiptOpen(false);
    lastCompletedSearchKey.current = null;
    setError(null);
    setBusy(null);
  }

  function invalidateRoleBoundState() {
    roleTransitionVersion.current += 1;
    clearRoleBoundState();
  }

  function setPersona(next: PersonaKey) {
    if (next === controls.role) return;
    invalidateRoleBoundState();
    setControls((current) => ({ ...current, role: next }));
  }

  // Single navigation writer (SPEC 6.0). Every nav item, entry card, and
  // inline hand-off routes through here so the (surface, lens) selection stays
  // the source of truth; PR-5's URL router will drive the same helper.
  function goTo(surface: Surface, lens?: string) {
    setMobileNavOpen(false);
    switch (surface) {
      case 'overview':
        setModule('home');
        break;
      case 'retrieval': {
        const tab: DiagnoseTab = lens === 'fusion' ? 'fusion' : 'results';
        setModule('retrieve');
        setDiagnoseTab(tab);
        setPersona(DEFAULT_PERSONA);
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
          lens === 'action' || lens === 'supervision'
            ? 'supervision'
            : lens === 'graph'
              ? 'graph'
            : lens === 'replay'
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
                : proveTab === 'graph' ||
                    proveTab === 'receipt' ||
                    proveTab === 'replay' ||
                    proveTab === 'timeline' ||
                    proveTab === 'supervision'
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
  const activeNavigationLens =
    activeSurface === 'proof'
      ? proveTab === 'supervision'
        ? 'action'
        : 'evidence'
      : activeLens;

  // Route params derived from live state so the URL reflects them (SPEC 6.0).
  // A preset is active only while its query and retrieval behavior still match.
  // This prevents a hybrid query with the typo text from advertising itself as
  // the fuzzy-only exercise.
  const activePreset: PresetKey | undefined =
    activeSurface === 'retrieval'
      ? presets.find(
          (preset) =>
            preset.presetKey !== undefined &&
            preset.query === controls.query &&
            preset.mode === controls.mode &&
            (preset.rerank === undefined ||
              preset.rerank === controls.rerank),
        )?.presetKey
      : undefined;
  const activePersona: PersonaKey = controls.role;
  const activeSurfaceNav = [...PRIMARY_NAV, ...UTILITY_NAV].find(
    (item) => item.surface === activeSurface,
  );

  useEffect(() => {
    if (!mobileNavOpen) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') setMobileNavOpen(false);
    }
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [mobileNavOpen]);

  // Apply a parsed route to live state. surface/lens go through goTo (the single
  // navigation writer); preset/role set controls; a /proof/{run_id} loads
  // that run. Called on mount, on back/forward, and never during state->URL sync.
  function applyRoute(route: Route) {
    if (route.surface === 'retrieval' && route.preset) {
      const preset = presets.find((entry) => entry.presetKey === route.preset);
      if (preset) {
        setControls((current) => ({
          ...current,
          query: preset.query,
          mode: preset.mode,
          kind: preset.kind,
          clusterId: preset.clusterId,
          rerank: preset.rerank ?? current.rerank,
        }));
      }
    }
    if (personaMode && route.surface === 'agent' && route.role) {
      setPersona(route.role);
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
    if (personaMode && activeSurface === 'agent') {
      route.role = activePersona;
    }
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
    activePersona,
    personaMode,
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

  function searchPayload(sourceControls: Controls = controls) {
    return {
      query: sourceControls.query,
      mode: sourceControls.mode,
      source_systems: PARTICIPANT_SOURCE_SYSTEMS,
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
      iterative_scan: sourceControls.iterativeScan,
      rerank: sourceControls.rerank,
      role: sourceControls.role,
    };
  }

  function finishHomeTyping() {
    if (!homeTyping) return;
    homeTypingInterrupted.current = true;
    setHomeQueryText(runQuestion);
    setHomeTyping(false);
  }

  async function loadRun(
    id: string | undefined,
    requestKey?: string,
    preserveAgentState = false,
    requestedRole: PersonaKey = controls.role,
  ): Promise<boolean> {
    const requestedRunId = (id || '').trim();
    const runKey = encodeURIComponent(requestedRunId);
    if (!runKey) return false;
    const transitionVersion = roleTransitionVersion.current;
    if (!requestKey) lastCompletedSearchKey.current = null;
    setProofRunDraft(requestedRunId);
    clearLoadedProofState();
    if (!preserveAgentState) clearAgentState();
    setBusy('run');
    setError(null);
    try {
      const roleQuery = `role=${encodeURIComponent(requestedRole)}`;
      const [runReceipt, runGraph, runTimeline, runSupervision] =
        await Promise.all([
        api<RunReceipt>(`/v1/runs/${runKey}?${roleQuery}`),
        api<RunGraph>(`/v1/runs/${runKey}/graph?${roleQuery}`),
        api<RunTimeline>(`/v1/runs/${runKey}/timeline?${roleQuery}`),
        api<SupervisionReceipt>(
          `/v1/runs/${runKey}/supervision?${roleQuery}`,
        ),
      ]);
      const ranked = runReceipt.candidates.map((candidate, index) => ({
        ...candidate,
        result_rank: candidate.result_rank || index + 1,
      }));
      if (transitionVersion !== roleTransitionVersion.current) return false;
      setReceipt(runReceipt);
      setGraph(runGraph);
      setTimeline(runTimeline);
      setSupervision(runSupervision);
      setCandidates(ranked);
      setAnswer(runReceipt.answer);
      setRunId(runReceipt.run.run_id);
      setProofRunDraft(runReceipt.run.run_id);
      if (requestKey) lastCompletedSearchKey.current = requestKey;
      setSelectedEvidenceId((current) =>
        ranked.some((candidate) => candidate.evidence_id === current)
          ? current
          : ranked[0]?.evidence_id || null,
      );
      return true;
    } catch (reason) {
      if (transitionVersion !== roleTransitionVersion.current) return false;
      clearLoadedProofState();
      setError(reason instanceof Error ? reason.message : 'Run unavailable');
      return false;
    } finally {
      if (transitionVersion === roleTransitionVersion.current) setBusy(null);
    }
  }

  async function loadQueryPlan(arm = planArm) {
    if (!retrievalReady || !controls.query.trim()) return;
    const transitionVersion = roleTransitionVersion.current;
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
          source_systems: PARTICIPANT_SOURCE_SYSTEMS,
          cluster_id: controls.clusterId || null,
          kinds: controls.kind === 'all' ? null : [controls.kind],
          role: controls.role,
        }),
      });
      if (transitionVersion !== roleTransitionVersion.current) return;
      setPlanArm(arm);
      setQueryPlan(result);
    } catch (reason) {
      if (transitionVersion !== roleTransitionVersion.current) return;
      setError(
        reason instanceof Error ? reason.message : 'Query plan unavailable',
      );
    } finally {
      if (transitionVersion === roleTransitionVersion.current) setBusy(null);
    }
  }

  function openQueryPlan(arm: QueryPlanResponse['arm']) {
    setModule('retrieve');
    setDiagnoseTab('results');
    setArmsOpen(true);
    setPlanOpen(true);
    void loadQueryPlan(arm);
  }

  async function runSearch(
    event?: FormEvent,
    requestedControls: Controls = controls,
  ) {
    event?.preventDefault();
    if (!retrievalReady || !requestedControls.query.trim()) return;
    const transitionVersion = roleTransitionVersion.current;
    const requestKey = retrievalRequestKey(requestedControls);
    clearLoadedProofState();
    clearAgentState();
    setProofRunDraft('');
    setBusy('search');
    setError(null);
    setPlanOpen(false);
    setArmsOpen(false);
    setCandidateReceiptOpen(false);
    try {
      const response = await api<SearchResponse>('/v1/search', {
        method: 'POST',
        body: JSON.stringify(searchPayload(requestedControls)),
      });
      if (transitionVersion !== roleTransitionVersion.current) return;
      await loadRun(
        response.run_id,
        requestKey,
        false,
        requestedControls.role,
      );
    } catch (reason) {
      if (transitionVersion !== roleTransitionVersion.current) return;
      setError(reason instanceof Error ? reason.message : 'Search unavailable');
    } finally {
      if (transitionVersion === roleTransitionVersion.current) setBusy(null);
    }
  }

  async function beginInvestigation() {
    if (!retrievalReady) return;
    const baselineQuery = homeQueryText.trim();
    if (!baselineQuery) return;
    const baselineControls = {
      ...controls,
      query: baselineQuery,
      role: DEFAULT_PERSONA,
    };
    if (controls.role === DEFAULT_PERSONA) {
      invalidateRoleBoundState();
    } else {
      setPersona(DEFAULT_PERSONA);
    }
    setControls(baselineControls);
    setModule('retrieve');
    setDiagnoseTab('results');
    await runSearch(undefined, baselineControls);
  }

  async function askAgent() {
    if (!retrievalReady || !controls.query.trim()) return;
    const transitionVersion = roleTransitionVersion.current;
    const requestControls = controls;
    setModule('prove');
    setProveTab('answer');
    window.scrollTo({ top: 0, behavior: 'smooth' });
    setBusy('answer');
    setError(null);
    setAgentStreamState('streaming');
    setStreamingAnswer('');
    setAgentTrace([]);
    setAgentTraceExpanded(false);
    setStreamCitations([]);
    setVisibleCitationCount(0);
    setAgentCommentary('');
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
            question: requestControls.query,
            source_systems: PARTICIPANT_SOURCE_SYSTEMS,
            max_tool_calls: 12,
            iterative_scan: requestControls.iterativeScan,
            role: requestControls.role,
          }),
        },
      );
      if (transitionVersion !== roleTransitionVersion.current) return;
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
        if (transitionVersion !== roleTransitionVersion.current) return;
        if (event.type === 'meta') return;
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
              if (transitionVersion !== roleTransitionVersion.current) return;
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
        setAgentCommentary(event.agent_commentary || '');
        setAgentLatencyMs(event.total_latency_ms ?? null);
        setStreamCitations(event.citations || []);
        if (event.answer) setStreamingAnswer(event.answer);

        if (
          event.status !== 'complete' ||
          !event.answer ||
          !completedRunId ||
          !(event.citations || []).length
        ) {
          setAgentStreamState('error');
          setError(
            event.error ||
              'The agent stopped before a citation-validated answer was persisted.',
          );
          return;
        }

      };

      while (true) {
        const { value, done } = await reader.read();
        if (transitionVersion !== roleTransitionVersion.current) {
          await reader.cancel();
          return;
        }
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
        const loaded = await loadRun(
          completedRunId,
          undefined,
          true,
          requestControls.role,
        );
        if (transitionVersion === roleTransitionVersion.current) {
          setAgentStreamState(loaded ? 'complete' : 'error');
        }
      }
    } catch (reason) {
      if (transitionVersion !== roleTransitionVersion.current) return;
      setAgentStreamState('error');
      setError(reason instanceof Error ? reason.message : 'Answer unavailable');
    } finally {
      if (transitionVersion === roleTransitionVersion.current) setBusy(null);
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
  const rerankUnavailable =
    Boolean(receipt) && receiptRerankRequested && !finalReranked;
  const finalOrderIsFused = candidates.length ? isFusedOrder(candidates) : true;
  const exactTierCount = candidates.filter(
    (candidate) => matchTier(candidate) === 1,
  ).length;
  const activeFusionArmCount = [
    textCandidates.length,
    vectorCandidates.length,
    fuzzyCandidates.length,
  ].filter((count) => count > 0).length;
  const appliedControls: Controls = {
    ...controls,
    query: receipt?.run.query_text || controls.query,
    mode: receipt?.run.retrieval_mode || controls.mode,
    candidatePool: receipt?.run.candidate_pool || controls.candidatePool,
    rrfK: receipt?.run.rrf_k ?? controls.rrfK,
    textWeight: receipt?.run.text_weight ?? controls.textWeight,
    vectorWeight: receipt?.run.vector_weight ?? controls.vectorWeight,
    fuzzyWeight: receipt?.run.fuzzy_weight ?? controls.fuzzyWeight,
    fuzzyThreshold:
      receipt?.run.fuzzy_threshold ?? controls.fuzzyThreshold,
    efSearch: receipt?.run.hnsw_ef_search ?? controls.efSearch,
    iterativeScan:
      receipt?.run.hnsw_iterative_scan ?? controls.iterativeScan,
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
        controls.iterativeScan !==
          (receipt.run.hnsw_iterative_scan ?? controls.iterativeScan) ||
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
  const homeCitations = (answer?.citations || []).slice(0, 5);
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
    agentStreamState === 'idle' &&
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
  const resolvedCitationCount = answerCitations.filter(
    (citation) =>
      citation.evidence_id &&
      citation.document_version_id &&
      citation.chunk_version_id &&
      citation.source_uri &&
      citation.source_revision &&
      citation.quote_text,
  ).length;
  const citationCoverageComplete = Boolean(
    answerCitations.length &&
      resolvedCitationCount === answerCitations.length &&
      answer?.validation_status === 'valid',
  );
  const currentAgentEvent = agentTrace[agentTrace.length - 1] || null;
  const visibleAgentTrace = agentTraceExpanded
    ? agentTrace
    : currentAgentEvent
      ? [currentAgentEvent]
      : [];
  const retrievalAvailable = Boolean(
    receipt?.run.status === 'complete' &&
      receipt.candidates.length,
  );
  const agentAvailable = Boolean(receipt?.answer?.answer_text);
  const proofAvailable = Boolean(
    receipt?.answer?.citations.length &&
      receipt.answer.validation_status === 'valid',
  );
  const agentWithheld =
    !agentAvailable &&
    agentDisplayState === 'error';
  const proofWithheld =
    !proofAvailable &&
    (agentDisplayState === 'error' || activeSurface === 'proof');
  const journeySteps = buildJourneySteps({
    activeSurface,
    activeLens: activeNavigationLens,
    retrievalAvailable,
    agentAvailable,
    proofAvailable,
    agentWithheld,
    proofWithheld,
  });
  const persistedPersona = receipt?.run.role || controls.role;
  const persistedPersonaLabel = personaLabel(persistedPersona);
  const selectedToolContract = toolContract(selectedTool, personaMode);

  useEffect(() => {
    const citations = receipt?.answer?.citations || [];
    if (!citations.length) {
      setSelectedProofCitation(1);
      return;
    }
    setSelectedProofCitation((current) =>
      citations.some(
        (citation, index) =>
          (citation.citation_number || citation.n || index + 1) === current,
      )
        ? current
        : citations[0].citation_number || citations[0].n || 1,
    );
  }, [receipt?.run.run_id]);

  return (
    <div
      className={`workbench-shell ${navCollapsed ? 'nav-collapsed' : ''} ${
        mobileNavOpen ? 'mobile-nav-open' : ''
      }`}
    >
      <aside className="side-rail">
        <div className="side-rail-head">
          <button
            className="brand"
            type="button"
            onClick={() => goTo('overview')}
            aria-label="Open Hybrid Retrieval Workbench overview"
            title={navCollapsed ? 'Open Hybrid Retrieval Workbench overview' : undefined}
          >
            <WorkbenchMark />
            <span className="brand-copy">
              <strong>{APP_NAME}</strong>
              <small>Aurora PostgreSQL</small>
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

        <button
          type="button"
          className="mobile-nav-trigger"
          aria-expanded={mobileNavOpen}
          aria-controls="workbench-navigation"
          onClick={() => setMobileNavOpen((current) => !current)}
        >
          {mobileNavOpen ? <X size={17} /> : <Menu size={17} />}
          <span>{activeSurfaceNav?.label || 'Overview'}</span>
          <ChevronRight size={15} aria-hidden="true" />
        </button>

        <nav
          id="workbench-navigation"
          className={`side-nav journey-side-nav ${
            mobileNavOpen ? 'mobile-open' : ''
          }`}
          aria-label="Workbench surfaces"
        >
          {PRIMARY_NAV.map(({ surface, label, Icon, lenses }) => {
            const surfaceActive = activeSurface === surface;
            const journeyStep = journeySteps.find(
              (step) => step.surface === surface,
            );
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
                  <span className="side-nav-label">{label}</span>
                  <i
                    className={`nav-journey-dot journey-state-${
                      journeyStep?.state || 'waiting'
                    }`}
                    title={`${journeyStep?.caption || label} · ${
                      journeyStep?.state || 'waiting'
                    }`}
                    aria-label={`${label}: ${
                      journeyStep?.caption || label
                    }; ${journeyStep?.state || 'waiting'}`}
                  >
                    {journeyStep?.state === 'blocked' ? (
                      <X size={7} />
                    ) : null}
                  </i>
                </button>
                {surfaceActive && lenses.length ? (
                  <div className="side-subnav" aria-label={`${label} views`}>
                    {lenses.map((lens) => (
                      <button
                        type="button"
                        key={lens.key}
                        className={
                          activeNavigationLens === lens.key ? 'active' : ''
                        }
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
          <div className="side-reference">
            <button
              type="button"
              className="side-reference-toggle"
              aria-expanded={referenceOpen}
              aria-controls="reference-navigation"
              onClick={() => setReferenceOpen((open) => !open)}
              title={navCollapsed ? 'Open reference surfaces' : undefined}
            >
              <Code2 size={15} />
              <span className="side-nav-label">Reference</span>
              <ChevronDown size={14} aria-hidden="true" />
            </button>
            {referenceOpen ? (
              <div id="reference-navigation" className="side-reference-links">
                {UTILITY_NAV.map(({ surface, label, Icon }) => (
                  <button
                    type="button"
                    key={surface}
                    className={activeSurface === surface ? 'active' : ''}
                    onClick={() => goTo(surface)}
                  >
                    <Icon size={14} />
                    <span>{label}</span>
                  </button>
                ))}
                {personaMode ? (
                  <div className="side-persona-control">
                    <span className="section-label">Viewing as</span>
                    <div className="segmented" role="group" aria-label="Viewing as">
                      {PERSONA_KEYS.map((key) => (
                        <button
                          key={key}
                          type="button"
                          className={key === controls.role ? 'active' : ''}
                          aria-pressed={key === controls.role}
                          onClick={() => setPersona(key)}
                        >
                          {PERSONA_LABELS[key]}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        </nav>

        <div className="side-rail-details">
          {runId ? (
            <button
              type="button"
              className="side-run-state"
              onClick={() => goTo('proof', 'receipt')}
              title="Open evidence record"
            >
              <span className="section-label">Current run</span>
              <strong>{compactId(runId)}</strong>
              <small>Open evidence record</small>
            </button>
          ) : (
            <div className="side-run-state quiet">
              <span className="section-label">Current run</span>
              <strong>Not started</strong>
              <small>Run retrieval to create a record</small>
            </div>
          )}
        </div>
      </aside>

      <div className="app-column">
        {module === 'home' ? (
          <LiveBanner health={health} connectionState={connectionState} />
        ) : null}
        {module !== 'home' &&
        module !== 'retrieve' &&
        activeSurface !== 'agent' &&
        activeSurface !== 'proof' ? (
        <header className="chrome">
          <div className="chrome-inner">
          <button
              className="mobile-brand"
              type="button"
              onClick={() => setModule('home')}
              aria-label="Open Hybrid Retrieval Workbench overview"
            >
              <WorkbenchMark />
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

        {error &&
        !(activeSurface === 'agent' && agentDisplayState === 'error') ? (
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
          <section className="workbench-home">
            <header className="home-hero">
              <div className="home-hero-inner">
              <div className="home-copy">
                <span className="home-eyebrow">
                  Connected incident evidence
                </span>
                <h1>
                  Trace retrieval <em className="home-proof">to cited proof.</em>
                </h1>
                <p>
                  Ask the incident question, then inspect the retrieval signals,
                  authoritative relationships, and persisted citations behind
                  the answer.
                </p>
              </div>

              <form
                className={`investigation-query home-query ${
                  homeTyping ? 'typing' : ''
                }`}
                onSubmit={(event) => {
                  event.preventDefault();
                  void beginInvestigation();
                }}
              >
                <span className="home-query-icon" aria-hidden="true">
                  <Search size={20} />
                </span>
                <span className="investigation-query-field">
                  <label htmlFor="home-investigation-question">
                    Investigation question
                  </label>
                  <textarea
                    id="home-investigation-question"
                    rows={4}
                    value={homeQueryText}
                    readOnly={homeTyping}
                    title={homeQueryText}
                    onFocus={finishHomeTyping}
                    onChange={(event) => {
                      const query = event.target.value;
                      setHomeQueryText(query);
                      setControl('query', query);
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
                </button>
              </form>

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
                  <WorkbenchMark className="home-answer-mark" />
                  <strong className="home-answer-title">
                    Evidence thread
                  </strong>
                  <small className="home-answer-model">
                    {homeEvidenceState === 'ready'
                      ? 'persisted run'
                      : homeEvidenceState === 'loading'
                        ? 'connecting'
                        : 'awaiting run'}
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
                      ? 'weighted reciprocal rank'
                      : 'run an investigation to assemble evidence'}
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
                        ? 'Connecting to latest proof'
                        : 'No proof run yet'}
                    </div>
                  ) : null}
                </div>
              </div>

              <div className="home-live-stats" aria-label="Live system status">
                <div>
                  <span>search index</span>
                  <strong className={health?.status === 'ready' ? 'ready' : ''}>
                    {connectionState === 'checking'
                      ? 'connecting'
                      : connectionState === 'unavailable'
                        ? 'not connected'
                        : health?.status || 'available'}
                  </strong>
                </div>
                <div>
                  <span>corpus</span>
                  <strong>
                    {health
                      ? `${health.current_documents.toLocaleString()} docs`
                      : 'live data pending'}
                  </strong>
                </div>
                <div>
                  <span>latest proof</span>
                  <strong>{runId ? compactId(runId) : 'none yet'}</strong>
                </div>
              </div>
              </div>
            </header>

            <section className="home-workspaces">
              <header>
                <div>
                  <span className="section-label">Continue investigation</span>
                  <h2>Search the evidence, ground the answer, review the action.</h2>
                </div>
                <span className="home-workspace-status">
                  <ShieldCheck size={14} />
                  {health
                    ? `${health.drift_issues} search-index drift`
                    : 'Live status pending'}
                </span>
              </header>
              <div className="home-workspace-grid">
                <button
                  type="button"
                  onClick={() => goTo('retrieval', 'results')}
                >
                  <FileSearch size={20} />
                  <span>
                    <strong>Search evidence</strong>
                    <small>
                      {runId
                        ? 'Inspect the current ranked record'
                        : 'Run an incident question'}
                    </small>
                  </span>
                  <ArrowRight size={15} />
                </button>
                <button type="button" onClick={() => goTo('agent', 'answer')}>
                  <Sparkles size={20} />
                  <span>
                    <strong>Ask the agent</strong>
                    <small>
                      {answer?.citations.length
                        ? `${answer.citations.length} cited sources in the latest answer`
                        : 'Build a citation-validated answer'}
                    </small>
                  </span>
                  <ArrowRight size={15} />
                </button>
                <button type="button" onClick={() => goTo('proof', 'action')}>
                  <UserCheck size={20} />
                  <span>
                    <strong>Review the action</strong>
                    <small>
                      {supervision?.proposal
                        ? 'Inspect the supervised proposal'
                        : 'Inspect the human decision record'}
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
                  <strong>Full text</strong>
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
                  <strong>Exact tier + RRF</strong>
                  <small>
                    IDs first · {controls.textWeight}:{controls.vectorWeight}:
                    {controls.fuzzyWeight} · k={controls.rrfK}
                  </small>
                </span>
                <ArrowRight size={18} />
                <span>
                  <strong>Cited run record</strong>
                  <small>{runId ? compactId(runId) : 'No run yet'}</small>
                </span>
              </div>
            </section>
          </section>
        ) : null}
        {module === 'retrieve' ? (
          <section className="module-screen retrieval-screen">
            <header className="module-heading module-heading-compact">
              <div>
                <span className="module-kicker">
                  {diagnoseTab === 'results'
                    ? 'Retrieval'
                    : 'Ranking diagnostics'}
                </span>
                <h1>
                  {diagnoseTab === 'results' ? (
                    <>
                      Search <em>incident evidence.</em>
                    </>
                  ) : (
                    <>
                      Inspect the <em>fused rank.</em>
                    </>
                  )}
                </h1>
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
                        setAgentStreamState('idle');
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
                    <div
                      className="retrieval-query-options"
                      aria-label="Example queries"
                    >
                      <span>Examples</span>
                      {presets.map((preset) => (
                        <button
                          key={preset.label}
                          type="button"
                          className={
                            controls.query === preset.query &&
                            controls.mode === preset.mode &&
                            (preset.rerank === undefined ||
                              preset.rerank === controls.rerank)
                              ? 'active'
                              : ''
                          }
                          onClick={() =>
                            setControls((current) => ({
                              ...current,
                              query: preset.query,
                              mode: preset.mode,
                              kind: preset.kind,
                              clusterId: preset.clusterId,
                              rerank: preset.rerank ?? current.rerank,
                            }))
                          }
                        >
                          {preset.label}
                        </button>
                      ))}
                    </div>
                    <div className="retrieval-query-status">
                      <span
                        className={`query-receipt-state ${
                          retrievalDraftDirty
                            ? 'pending'
                            : rerankUnavailable
                              ? 'warning'
                              : ''
                        }`}
                      >
                        {retrievalDraftDirty
                          ? 'Run retrieval to apply'
                          : rerankUnavailable
                            ? 'Rerank unavailable · RRF shown'
                          : runId
                            ? 'Run current'
                            : 'Ready to run'}
                      </span>
                    </div>
                  </div>
                </form>

                <FinalRankedEvidence
                  candidates={finalResultCandidates}
                  rankingCandidates={candidates}
                  selectedEvidenceId={selectedEvidenceId}
                  reranked={finalReranked}
                  retrievalMode={appliedControls.mode}
                  runId={runId}
                  verifySql={receipt?._verify_sql}
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
                      <strong className="retrieval-story-title">
                        Inspect ranking <em>diagnostics</em>
                      </strong>
                      <b>
                        Arm positions, query plans, and ranking policy stay
                        available when you need them.
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
                          {personaMode
                            ? 'Filters and ACLs execute before ranking.'
                            : 'Metadata filters execute before ranking.'}{' '}
                          Only positions enter fusion; raw values remain
                          diagnostics.
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
                          subtitle={`pgvector HNSW · ${embeddingModel} · ef ${appliedControls.efSearch} · ${ITERATIVE_SCAN_LABELS[appliedControls.iterativeScan]}`}
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
                          {personaMode
                            ? 'filters + ACL before ranking'
                            : 'filters before ranking'}
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
                      <h2>Exact IDs first; active rankings fuse the rest</h2>
                      <p>
                        Exact identifier matches enter a deterministic first
                        tier. {activeFusionArmCount} active ranked{' '}
                        {activeFusionArmCount === 1 ? 'arm contributes' : 'arms contribute'}{' '}
                        persisted positions to weighted RRF.
                      </p>
                    </div>
                    <span className="status-pill ready">
                      {candidates.length} persisted candidates
                    </span>
                  </header>
                  <div className="fusion-flow">
                    <div className="fusion-flow-inputs">
                      <span className="fusion-flow-exact">
                        <CircleDot size={17} />
                        <small>Exact tier</small>
                        <strong>{exactTierCount}</strong>
                        <b>ordered first</b>
                      </span>
                      <div className="fusion-flow-arms">
                        <span>
                          <b>Text</b>
                          <strong>{textCandidates.length}</strong>
                          <small>
                            {textCandidates.length
                              ? `weight ${appliedControls.textWeight}`
                              : 'abstained'}
                          </small>
                        </span>
                        <span>
                          <b>Semantic</b>
                          <strong>{vectorCandidates.length}</strong>
                          <small>
                            {vectorCandidates.length
                              ? `weight ${appliedControls.vectorWeight}`
                              : 'abstained'}
                          </small>
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
                        {finalReranked ? 'Cohere final' : 'Final order'}
                      </small>
                      <strong>
                        {candidates[0]
                          ? snapshot(candidates[0]).external_key
                          : 'awaiting run'}
                      </strong>
                    </span>
                  </div>
                  <FusionBacktrace
                    candidates={candidates}
                    selectedEvidenceId={selectedEvidenceId}
                    controls={appliedControls}
                    reranked={finalReranked}
                    onSelect={(candidate) =>
                      setSelectedEvidenceId(candidate.evidence_id || null)
                    }
                  />
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
                  <FusionImplementationDetails
                    controls={appliedControls}
                    runId={runId}
                  />
                </div>

                {candidates.length ? (
                  <section className="fusion-candidate-panel">
                    <header>
                      <div>
                        <span className="section-label">Candidate pool</span>
                        <h2>Compare positions and final order</h2>
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
                  <span className="section-label">Reading guide</span>
                  <p>
                    Open a candidate row to inspect raw arm diagnostics and
                    contribution math. PostgreSQL RRF and Cohere rerank scores
                    explain relative order; neither is a confidence probability.
                  </p>
                </section>
              </div>
            ) : null}

            {diagnoseTab === 'fusion' &&
            candidateReceiptOpen &&
            activeEvidence ? (
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
            <header
              className={`module-heading prove-heading ${
                proveTab === 'answer' ? 'module-heading-compact' : ''
              }`}
            >
              <div>
                <span className="module-kicker">
                  {proveTab === 'answer'
                    ? 'Hybrid Retrieval Agent'
                    : proveTab === 'evaluation'
                      ? 'Reference · Evaluation'
                      : proveTab === 'supervision'
                        ? 'Proof · Action review'
                        : 'Proof · Evidence record'}
                </span>
                <h1>
                  {proveTab === 'answer' ? (
                    <>Ground an answer in <em>incident evidence.</em></>
                  ) : proveTab === 'supervision' ? (
                    <>Review the <em>human decision.</em></>
                  ) : proveTab === 'evaluation' ? (
                    <>Evidence, <em>not anecdotes.</em></>
                  ) : (
                    <>Inspect the <em>evidence record.</em></>
                  )}
                </h1>
                {proveTab !== 'answer' ? (
                  <p className="module-deck">
                    {proveTab === 'supervision'
                      ? 'Proposal, approval, execution, and validation remain separate.'
                      : proveTab === 'evaluation'
                        ? 'Measure retrieval modes and relationship traversal with separate metrics.'
                        : 'Inspect the persisted record without another model call.'}
                  </p>
                ) : null}
              </div>
              {proveTab !== 'answer' && proveTab !== 'evaluation' ? (
                <div className="run-loader">
                  <input
                    value={proofRunDraft}
                    onChange={(event) => setProofRunDraft(event.target.value)}
                    aria-label="Run ID"
                    placeholder="Run ID"
                  />
                  <button
                    type="button"
                    className="icon-command"
                    disabled={!proofRunDraft}
                    onClick={async () => {
                      await navigator.clipboard.writeText(proofRunDraft);
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
                    onClick={() => loadRun(proofRunDraft)}
                    disabled={!proofRunDraft || busy !== null}
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

            {proveTab !== 'answer' && proveTab !== 'evaluation' ? (
              <div className="proof-viewbar">
                <div
                  className="segmented"
                  role="group"
                  aria-label="Proof section"
                >
                  <button
                    type="button"
                    className={proveTab === 'supervision' ? '' : 'active'}
                    aria-pressed={proveTab !== 'supervision'}
                    onClick={() => goTo('proof', 'receipt')}
                  >
                    Evidence record
                  </button>
                  <button
                    type="button"
                    className={proveTab === 'supervision' ? 'active' : ''}
                    aria-pressed={proveTab === 'supervision'}
                    onClick={() => goTo('proof', 'action')}
                  >
                    Action review
                  </button>
                </div>
                {proveTab !== 'supervision' ? (
                  <label className="proof-view-select">
                    <span>Evidence view</span>
                    <select
                      value={proveTab}
                      onChange={(event) => goTo('proof', event.target.value)}
                    >
                      <option value="receipt">Record</option>
                      <option value="graph">Relationships</option>
                      <option value="replay">Replay</option>
                      <option value="timeline">Timeline</option>
                    </select>
                  </label>
                ) : null}
              </div>
            ) : null}

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
                    onChange={setAgentQuestion}
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
                      : 'Ask Hybrid Retrieval Agent'}
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
                        <CircleDot size={13} />
                      )}
                      {agentDisplayState === 'complete'
                        ? persistedAnswerLoaded
                          ? 'persisted answer loaded'
                          : 'citation gate passed'
                        : agentDisplayState === 'streaming'
                          ? 'Hybrid Retrieval Agent running'
                          : 'ready to investigate'}
                    </span>
                    {answer?.run_id || runId ? (
                      <span>
                        run <b>{compactId(answer?.run_id || runId)}</b>
                      </span>
                    ) : null}
                    {agentLatencyMs !== null ? (
                      <span>
                        <b>{(agentLatencyMs / 1000).toFixed(1)} s</b> agent run
                      </span>
                    ) : null}
                    {personaMode ? (
                      <span className="agent-query-boundary">
                        <ShieldCheck size={12} />
                        {agentDisplayState === 'complete'
                          ? 'ACL enforced'
                          : `${personaLabel(controls.role)} selected`}
                      </span>
                    ) : null}
                  </div>
                  {agentExamples.length ? (
                    <div
                      className="agent-query-examples"
                      aria-label="Example agent investigations"
                    >
                      <span>Examples</span>
                      {agentExamples.map((example) => (
                        <button
                          key={example.label}
                          type="button"
                          className={
                            controls.query === example.question ? 'active' : ''
                          }
                          onClick={() => setAgentQuestion(example.question)}
                        >
                          {example.label}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </form>

                <div
                  className={`answer-story-layout ${
                    agentDisplayState === 'idle' ||
                    agentDisplayState === 'error'
                      ? 'single-column'
                      : ''
                  }`}
                >
                  <article className="answer-story-document">
                    {agentDisplayState === 'idle' ? (
                      <div className="answer-gate">
                        <span className="answer-gate-count">
                          Hybrid Retrieval Agent idle
                        </span>
                        <h2>No Hybrid Retrieval Agent run is loaded.</h2>
                        <p className="answer-gate-lead">
                          No persisted or live agent evidence is available for this
                          {personaMode ? ' persona.' : ' investigation.'}
                        </p>
                      </div>
                    ) : null}

                    {agentDisplayState === 'streaming' ? (
                      <section className="agent-working-panel" aria-live="polite">
                        <header>
                          <span className="agent-live-indicator">
                            <i />
                            Investigating evidence
                          </span>
                          {agentTrace.length ? (
                            <button
                              type="button"
                              className="agent-trace-toggle"
                              aria-controls="agent-live-trace"
                              aria-expanded={agentTraceExpanded}
                              aria-label={
                                agentTraceExpanded
                                  ? 'Collapse agent trace'
                                  : 'Expand agent trace'
                              }
                              onClick={() =>
                                setAgentTraceExpanded((expanded) => !expanded)
                              }
                            >
                              <span>
                                {agentTrace.length} decision
                                {agentTrace.length === 1 ? '' : 's'} observed
                              </span>
                              <ChevronDown size={14} aria-hidden="true" />
                            </button>
                          ) : (
                            <b>starting Strands loop</b>
                          )}
                        </header>
                        <ol id="agent-live-trace" className="agent-trace-tree">
                          {visibleAgentTrace.length ? (
                            visibleAgentTrace.map((event, index) => (
                              <li
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
                                  <p>{toolDecision(event, personaMode)}</p>
                                </div>
                                <small>{toolResult(event)}</small>
                              </li>
                            ))
                          ) : (
                            <li className="current">
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
                            </li>
                          )}
                        </ol>
                      </section>
                    ) : null}

                    {agentStreamState === 'streaming' ? (
                      <div className="answer-streaming-prose" aria-live="polite">
                        <span className="section-label">
                          Citation-validated prose
                        </span>
                        {streamingAnswer ? (
                          <AnswerNarrative
                            text={streamingAnswer}
                            streaming
                            structured
                          />
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
                        <div className="answer-narrative-heading">
                          <div>
                            <span className="section-label">
                              Answer of record
                            </span>
                            <h2>Citation-validated incident synthesis</h2>
                          </div>
                          <span
                            className={`status-pill ${
                              answer.validation_status === 'valid'
                                ? 'ready'
                                : ''
                            }`}
                          >
                            <ShieldCheck size={12} />
                            {answer.validation_status || 'persisted'}
                          </span>
                        </div>
                        <AnswerNarrative
                          text={streamingAnswer || answer.answer_text}
                          structured={answer.synthesis_mode === 'bedrock'}
                        />
                        <div className="answer-proof-strip">
                          <span>
                            <b>{answerCitations.length}</b>
                            validated citations
                          </span>
                          <span>
                            <b>{resolvedCitationCount}</b>
                            resolved source spans
                          </span>
                          <span>
                            <b>{answer.validation_status || 'persisted'}</b>
                            citation gate
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
                          Hybrid Retrieval Workbench will not present agent
                          commentary as an answer of record. Review the observable
                          calls below, then retry the bounded recovery.
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

                  {agentDisplayState === 'streaming' ||
                  answerCitations.length ? (
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
                                <em>
                                  {citation.claim?.trim()
                                    ? citation.claim
                                    : `Source context: ${citationContext(citation)}`}
                                </em>
                              </span>
                            </button>
                          ))}
                      </div>
                    ) : (
                      <div className="answer-source-pending">
                        <LoaderCircle className="spin" size={15} />
                        <span>
                          <strong>Validating citations</strong>
                          Sources appear here as their exact chunks pass the
                          evidence gate.
                        </span>
                      </div>
                    )}
                    {answerCitations.length ? (
                      <section className="answer-coverage-card">
                        <div>
                          <span>Citation resolution</span>
                          <b>
                            {resolvedCitationCount}/{answerCitations.length}
                          </b>
                        </div>
                        <div className="answer-coverage-meter">
                          <i
                            style={{
                              width: `${answerCitations.length ? (resolvedCitationCount / answerCitations.length) * 100 : 0}%`,
                            }}
                          />
                        </div>
                        <p>
                          {citationCoverageComplete
                            ? 'Every citation resolves to a source URI, revision, exact chunk, and supporting quote.'
                            : 'The persisted citation record is incomplete or has not passed validation.'}
                        </p>
                      </section>
                    ) : null}
                    </aside>
                  ) : null}
                </div>

                <details className="agent-technical-details">
                  <summary>
                    <span>
                      <strong>Technical record</strong>
                      <small>Tool trace, guardrails, and agent contract</small>
                    </span>
                    <ChevronDown size={16} aria-hidden="true" />
                  </summary>
                  <div className="agent-technical-details-body">
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
                            <p>{toolDecision(event, personaMode)}</p>
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
                              The persisted supporting runs supplied every
                              evidence kind required by the decomposed question.
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
                      <Empty
                        icon={<Sparkles size={20} />}
                        title="No agent execution recorded"
                      />
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
                      <strong>Participant evidence stays isolated</strong>
                      <p>
                        Every retrieval arm is filtered to{' '}
                        <code>{PARTICIPANT_SOURCE_SYSTEMS.join(', ')}</code>.
                      </p>
                    </article>
                    <article className={agentDisplayState === 'complete' ? 'observed' : ''}>
                      <span>02</span>
                      <strong>Canonical relationships stay measured</strong>
                      <p>
                        Displayed edges come from persisted relationship reads;
                        the frontend does not invent links between evidence.
                      </p>
                    </article>
                    <article
                      className={
                        agentDisplayState === 'complete' ? 'observed' : ''
                      }
                    >
                      <span>03</span>
                      <strong>
                        {personaMode
                          ? 'Authorization and validation stay fixed'
                          : 'Retrieval scope and validation stay fixed'}
                      </strong>
                      <p>
                        {personaMode
                          ? 'ACL checks apply to every retrieval and hop; '
                          : 'Source and metadata filters apply to retrieval; '}
                        missing or invalid citations keep the answer withheld.
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
                        <p>{selectedToolContract.purpose}</p>
                        <dl>
                          <div>
                            <dt>Returns</dt>
                            <dd>{selectedToolContract.result}</dd>
                          </div>
                          <div>
                            <dt>Proof boundary</dt>
                            <dd>{selectedToolContract.proof}</dd>
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
                  </div>
                </details>

                {agentDisplayState === 'complete' ? (
                  <div className="answer-next-actions">
                    <button
                      type="button"
                      className="run-button"
                      onClick={() => goTo('proof', 'receipt')}
                    >
                      <Clipboard size={15} />
                      Open evidence record
                    </button>
                  </div>
                ) : null}
              </section>
            ) : null}

            {proveTab === 'graph' ? (
              <>
                {personaMode ? (
                  <section className="graph-persona-boundary">
                    <ShieldCheck size={18} />
                    <div>
                      <span className="section-label">Entitlement boundary</span>
                      <strong>{persistedPersonaLabel}</strong>
                    </div>
                    <span>applied before every retrieval arm</span>
                    <ArrowRight size={15} aria-hidden="true" />
                    <span>rechecked at every relationship hop</span>
                    <code>run {compactId(receipt?.run.run_id)}</code>
                  </section>
                ) : null}
                <div className="graph-studio">
                  <aside className="graph-controls-panel">
                    <div className="graph-scope">
                      <span className="section-label">Investigation</span>
                      <p>{receipt?.run.query_text || controls.query}</p>
                      {personaMode ? (
                        <span className="graph-scope-persona">
                          persisted persona{' '}
                          <strong>{persistedPersonaLabel}</strong>
                        </span>
                      ) : null}
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
                    {personaMode ? (
                      <div className="graph-policy-note">
                        <LockKeyhole size={16} />
                        <span>
                          Authorization is checked again at every relationship
                          hop. Hidden evidence never enters this canvas.
                        </span>
                      </div>
                    ) : null}
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
                  <div
                    className="graph-verdict-mobile"
                    aria-label="Relationship verdicts"
                  >
                    {(visibleGraph?.edges || []).map((edge) => (
                      <article key={edge.edge_key}>
                        <div>
                          <span>{edge.from_external_key}</span>
                          <ArrowRight size={13} aria-hidden="true" />
                          <span>{edge.to_external_key}</span>
                        </div>
                        <strong>{edge.relation}</strong>
                        <small>
                          {edge.origin} · {score(edge.confidence, 2)}
                        </small>
                      </article>
                    ))}
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
                      <button
                        type="button"
                        className="text-command replay-transition-trigger"
                        onClick={() => setReplayKey((current) => current + 1)}
                        disabled={!receipt?.stages.length}
                      >
                        <Play size={13} />
                        Replay stages
                      </button>
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
                      <ObservabilityHandoff
                        handoff={receipt?.observability_ref}
                      />
                    </div>
                  </header>
                  {receipt ? (
                    <div
                      className="replay-timeline replay-transition"
                      key={replayKey}
                      aria-live="polite"
                    >
                      <div style={{ animationDelay: '0ms' }}>
                        <time>00:00.000</time>
                        <i />
                        <div>
                          <strong>Question accepted</strong>
                          <span>
                            cluster {controls.clusterId || 'all'}.
                          </span>
                        </div>
                        <b>OK</b>
                      </div>
                      {receipt.stages.map((stage, index) => (
                        <div
                          key={stage.stage_ordinal}
                          style={{ animationDelay: `${(index + 1) * 70}ms` }}
                        >
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
                <ProofChainOfCustody
                  receipt={receipt}
                  personaMode={personaMode}
                  selectedCitationNumber={selectedProofCitation}
                  onSelectCitation={setSelectedProofCitation}
                />
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

            {proveTab === 'supervision' ? (
              <section className="supervision-theater">
                <header>
                  <div>
                    <span className="section-label">
                      Proposed, approved, executed, assessed
                    </span>
                    <h2>{receipt?.run.query_text || controls.query}</h2>
                  </div>
                  <div className="supervision-theater-meta">
                    <span className="status-pill">
                      {supervision?.proposal ? 'latest proposal' : 'no proposal'}
                    </span>
                    <span className="status-pill">
                      {supervision?.execution
                        ? `executed: ${supervision.execution.outcome}`
                        : 'not executed'}
                    </span>
                    <span className="status-pill">
                      {supervision?.citations.length || 0} supporting citations
                    </span>
                  </div>
                </header>

                {!supervision?.proposal ? (
                  <Empty
                    icon={<UserCheck size={20} />}
                    title="No proposal recorded for this run"
                    detail="A proposal is written through the agent answer path. Runs answered another way, or before supervised execution shipped, have none."
                  />
                ) : (
                  <>
                    <article className="supervision-panel">
                      <h3>What the agent proposed</h3>
                      <dl>
                        <dt>Action</dt>
                        <dd>{supervision.proposal.action_type}</dd>
                        <dt>Target</dt>
                        <dd>
                          {supervision.proposal.target_schema}.
                          {supervision.proposal.target_table}
                        </dd>
                        <dt>Keys, in index order</dt>
                        <dd>{supervision.proposal.key_columns.join(', ')}</dd>
                        <dt>Expected effect</dt>
                        <dd>{supervision.proposal.expected_effect}</dd>
                        <dt>Rollback</dt>
                        <dd>
                          <code>
                            {supervision.proposal.rollback_sql ||
                              supervision.proposal.rollback_guidance ||
                              '-'}
                          </code>
                        </dd>
                        <dt>Bounds</dt>
                        <dd>
                          statement_timeout{' '}
                          {supervision.proposal.statement_timeout || '-'},
                          lock_timeout {supervision.proposal.lock_timeout || '-'}
                        </dd>
                      </dl>
                      <pre className="supervision-sql">
                        {supervision.proposal.proposed_sql}
                      </pre>
                      <p className="supervision-note">
                        The agent holds no DDL privilege and no execution path.
                        This statement is a recommendation a human runs.
                      </p>
                      <VerifyAffordance
                        descriptor={supervision._verify_sql?.proposal}
                      />
                    </article>

                    <article className="supervision-panel">
                      <h3>Supporting citations</h3>
                      {supervision.citations.length ? (
                        <ol className="supervision-citations">
                          {supervision.citations.map((citation) => (
                            <li key={citation.citation_number}>
                              <header>
                                <strong>
                                  Citation {citation.citation_number}
                                </strong>
                                <span
                                  className={
                                    citation.is_valid === true
                                      ? 'is-valid'
                                      : citation.is_valid === false
                                        ? 'is-invalid'
                                        : 'is-unavailable'
                                  }
                                >
                                  {citation.is_valid === true
                                    ? 'valid'
                                    : citation.is_valid === false
                                      ? citation.issue || 'invalid'
                                      : 'not visible for this persona'}
                                </span>
                              </header>
                              <p>{citation.claim}</p>
                              <blockquote>
                                {citation.quote_text ||
                                  'The linked citation is not visible for this persona.'}
                              </blockquote>
                              <code>
                                {citation.source_uri ||
                                  'source unavailable for this persona'}
                              </code>
                              {citation.source_revision ? (
                                <small>
                                  revision {citation.source_revision}
                                </small>
                              ) : null}
                            </li>
                          ))}
                        </ol>
                      ) : (
                        <Empty
                          icon={<FileCheck2 size={20} />}
                          title="No supporting citations recorded"
                          detail="The proposal is persisted, but it has no visible citation links."
                        />
                      )}
                      <VerifyAffordance
                        descriptor={supervision._verify_sql?.citations}
                      />
                    </article>

                    <article className="supervision-panel">
                      <h3>Preconditions, as measured</h3>
                      <ul className="supervision-checks">
                        {supervision.proposal.preconditions.map((check) => (
                          <li
                            key={check.check}
                            className={
                              check.satisfied
                                ? 'is-satisfied'
                                : 'is-unsatisfied'
                            }
                          >
                            <strong>{check.check}</strong>
                            <span>
                              {check.satisfied
                                ? 'satisfied'
                                : 'not satisfied'}
                            </span>
                            {check.detail ? <em>{check.detail}</em> : null}
                          </li>
                        ))}
                      </ul>
                    </article>

                    <article className="supervision-panel">
                      <h3>What was executed</h3>
                      {!supervision.execution ? (
                        <Empty
                          icon={<UserCheck size={20} />}
                          title="No execution recorded"
                          detail="The proposal is waiting on a human. Nothing has been run."
                        />
                      ) : (
                        <>
                          <dl>
                            <dt>Approved by</dt>
                            <dd>{supervision.execution.approved_by}</dd>
                            <dt>Outcome</dt>
                            <dd>{supervision.execution.outcome}</dd>
                            <dt>Observed index</dt>
                            <dd>
                              <code>
                                {supervision.execution
                                  .observed_index_definition || '-'}
                              </code>
                            </dd>
                            <dt>Matches the proposal</dt>
                            <dd>
                              {supervision.execution.fingerprint_matches
                                ? 'yes'
                                : 'no'}
                            </dd>
                            <dt>Plan evidence</dt>
                            <dd>
                              {supervision.execution.plan_before_checkpoint ||
                                '-'}{' '}
                              to{' '}
                              {supervision.execution.plan_after_checkpoint ||
                                '-'}
                            </dd>
                          </dl>
                          <VerifyAffordance
                            descriptor={supervision._verify_sql?.execution}
                          />
                        </>
                      )}
                    </article>

                    <article className="supervision-panel supervision-verdict">
                      <h3>Autonomy readiness</h3>
                      <p
                        className={
                          supervision.verdict?.pre_execution_eligible
                            ? 'is-eligible'
                            : 'is-blocked'
                        }
                      >
                        Before execution:{' '}
                        {supervision.verdict?.pre_execution_eligible
                          ? 'every pre-execution requirement was met'
                          : 'not eligible'}
                      </p>
                      <ul className="supervision-reasons">
                        {(
                          supervision.verdict?.pre_execution_reasons ?? []
                        ).map((reason) => (
                          <li key={reason}>{reason}</li>
                        ))}
                      </ul>
                      <p
                        className={
                          supervision.verdict?.post_execution_validated
                            ? 'is-validated'
                            : 'is-unvalidated'
                        }
                      >
                        After execution:{' '}
                        {supervision.verdict?.post_execution_validated
                          ? 'the executed action matched the proposal and Validation Evidence confirmed the result'
                          : 'not validated'}
                      </p>
                      <ul className="supervision-reasons">
                        {(
                          supervision.verdict?.post_execution_reasons ?? []
                        ).map((reason) => (
                          <li key={reason}>{reason}</li>
                        ))}
                      </ul>
                      <p className="supervision-note">
                        This is an autonomy-readiness assessment, not autonomous
                        execution. A human approved and executed this action. A
                        validated result afterwards does not mean the action was
                        safe to take unattended. The two verdicts are computed
                        separately and neither rewrites the other.
                      </p>
                      <VerifyAffordance
                        descriptor={supervision._verify_sql?.verdict}
                      />
                    </article>
                  </>
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
                  index on this cluster, grouped by evidence kind and admission
                  capture stage, read live from Aurora.
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
                <div className="distribution-groups">
                  {groupCorpusDistribution(
                    diagnostics?.distribution || [],
                  ).map((group) => {
                    const totalDocuments = group.rows.reduce(
                      (total, row) => total + row.documents,
                      0,
                    );
                    const totalChunks = group.rows.reduce(
                      (total, row) => total + row.chunks,
                      0,
                    );
                    const maximumDocuments = Math.max(
                      ...(diagnostics?.distribution || []).map(
                        (row) => row.documents,
                      ),
                      1,
                    );
                    return (
                      <section
                        className={`distribution-wave ${corpusWaveClassName(
                          group.wave,
                        )}`}
                        key={group.wave ?? 'unscoped'}
                      >
                        <header>
                          <strong>{corpusWaveLabel(group.wave)}</strong>
                          <span>
                            {totalDocuments.toLocaleString()} docs ·{' '}
                            {totalChunks.toLocaleString()} chunks
                          </span>
                        </header>
                        <div className="distribution-rows">
                          {group.rows.map((row) => (
                            <div key={row.evidence_kind}>
                              <span>{KIND_LABELS[row.evidence_kind]}</span>
                              <strong>{row.documents.toLocaleString()}</strong>
                              <i
                                style={{
                                  width: `${Math.max(
                                    (row.documents / maximumDocuments) * 100,
                                    1,
                                  )}%`,
                                }}
                              />
                            </div>
                          ))}
                        </div>
                      </section>
                    );
                  })}
                </div>
                <VerifyAffordance
                  descriptor={diagnostics?._verify_sql?.distribution}
                  label="verify distribution in psql"
                />
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
                  evidence, all read live from Aurora.
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
                    Four-phase live evidence path
                  </span>
                  <h2>Capture the evidence before the recommendation</h2>
                </div>
                <span className="status-pill ready">
                  {latestBuild?.status || 'checking'}
                </span>
              </header>
              <div className="evidence-phases">
                <div>
                  <strong>Online schema and data migration</strong>
                  <span>
                    Add a nullable priority_tier column, then backfill the
                    orders table in one unbatched transaction.
                  </span>
                </div>
                <div>
                  <strong>Pool exhaustion</strong>
                  <span>
                    Twelve hot writes meet the ten-slot application pool: ten
                    block in PostgreSQL and two time out before checkout.
                  </span>
                </div>
                <div>
                  <strong>Measured recovery</strong>
                  <span>
                    Commit the backfill and watch the ten connected writes
                    drain while the two checkout timeouts remain evidence.
                  </span>
                </div>
                <div>
                  <strong>Access-path finding</strong>
                  <span>
                    ANALYZE leaves the sequential scan in place; the missing
                    composite index is validated only after participant approval.
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

        <footer className="workbench-footer">
          <span>
            <Database size={13} />
            Aurora PostgreSQL
          </span>
          <span>
            <LockKeyhole size={13} />
            participant-generated incident evidence
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
