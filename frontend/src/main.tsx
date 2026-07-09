import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowLeft, Database, ExternalLink, Search, ShieldCheck } from 'lucide-react';
import { FaGithub } from 'react-icons/fa6';
import confluenceLogoUrl from './assets/confluence-2017.svg';
import jiraLogoUrl from './assets/jira-streamline.svg';
import salesforceLogoUrl from './assets/salesforce-logo.jpeg';
import slackIconUrl from './assets/slack-icon-2019.svg';
import serviceNowLogoUrl from './assets/servicenow-logo.png';
import './styles.css';

type Page = 'landing' | 'results' | 'detail' | 'trail' | 'agent' | 'diagnostics';

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
  explanation?: { signals?: Signals; why?: string[] };
};

type SearchResponse = {
  run_id: string;
  query: string;
  results: Result[];
};

type AgentPayload = {
  question?: string;
  run_id?: string;
  plan?: string[];
  answer?: string;
  citations?: Array<{
    n: number;
    source_system: string;
    external_id: string;
    title: string;
    url?: string;
  }>;
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

const API_URL = import.meta.env.VITE_RETRIEVAL_API_URL || 'http://127.0.0.1:8000';
const APP_NAME = import.meta.env.VITE_APP_DISPLAY_NAME || 'Threadline';
const queryDefault = 'Why did Orion slip?';
const showcaseQuery = 'Why did Orion slip across Slack, Jira, Confluence, Salesforce, and GitHub?';
const rotatingQueries = [
  queryDefault,
  showcaseQuery,
  'What changed before INC-0012345, which Jira blocker caused it, and which PR fixed it?',
  'Which Salesforce commitments are at risk, and what Slack and Jira evidence explains why?',
  'How do the readiness runbook, Slack decision, ORION-1473, and PR-1287 connect?'
];

const searchSuggestions = [
  {
    label: 'Cross-system cause',
    query: 'Why did Orion slip across Slack, Jira, Confluence, Salesforce, and GitHub?',
    sources: ['slack', 'jira', 'confluence', 'salesforce', 'github']
  },
  {
    label: 'Incident to fix',
    query: 'What changed before INC-0012345, which Jira blocker caused it, and which PR fixed it?',
    sources: ['servicenow', 'jira', 'github']
  },
  {
    label: 'Customer impact',
    query: 'Which Salesforce commitments are at risk, and what Slack and Jira evidence explains why?',
    sources: ['salesforce', 'slack', 'jira']
  },
  {
    label: 'Decision trail',
    query: 'How do the readiness runbook, Slack decision, ORION-1473, and PR-1287 connect?',
    sources: ['confluence', 'slack', 'jira', 'github']
  },
  {
    label: 'Evidence chain',
    query: 'Show the evidence chain from the failed readiness gate to the customer commitment and merged GitHub fix.',
    sources: ['confluence', 'salesforce', 'github']
  },
  {
    label: 'Full audit trail',
    query: 'Explain the Orion delay using the Slack decision, Jira blocker, Confluence gate, Salesforce case, ServiceNow incident, and GitHub PR.',
    sources: ['slack', 'jira', 'confluence', 'salesforce', 'servicenow', 'github']
  }
];

const workspaceNavItems: Array<{ page: Page; label: string; eyebrow: string; summary: string }> = [
  { page: 'results', label: 'Evidence', eyebrow: '24 ranked results', summary: 'Hybrid-ranked sources and linked context' },
  { page: 'agent', label: 'Answer', eyebrow: '6 cited sources', summary: 'Synthesized answer with inline citations' },
  { page: 'trail', label: 'Trail', eyebrow: '8 linked objects', summary: 'Cross-system sequence and relationship path' },
  { page: 'diagnostics', label: 'Diagnostics', eyebrow: '341 ms run', summary: 'Fusion, rerank, latency, and SQL trace' }
];

const coreSources = [
  { key: 'slack', label: 'Slack', count: 34 },
  { key: 'jira', label: 'Jira', count: 41 },
  { key: 'confluence', label: 'Confluence', count: 22 },
  { key: 'salesforce', label: 'Salesforce', count: 18 },
  { key: 'github', label: 'GitHub', count: 27 },
  { key: 'servicenow', label: 'ServiceNow', count: 6 }
];

const evidenceOrder = ['slack', 'jira', 'salesforce', 'confluence', 'servicenow', 'github'];

const landingSources = [
  { key: 'slack', label: 'Slack' },
  { key: 'jira', label: 'Jira' },
  { key: 'confluence', label: 'Confluence' },
  { key: 'salesforce', label: 'Salesforce' },
  { key: 'github', label: 'GitHub' }
];

const heroSourceNodes = [
  { key: 'confluence', className: 'n-conf', title: 'Readiness runbook', meta: 'Release gates', role: 'Policy', score: '0.82', delay: '.6s' },
  { key: 'slack', className: 'n-slack', title: 'Slack decision', meta: '#proj-orion', role: 'Decision', score: '0.93', delay: '0s' },
  { key: 'jira', className: 'n-jira', title: 'ORION-1473', meta: 'P1 blocker', role: 'Blocker', score: '0.89', delay: '1.4s' },
  { key: 'salesforce', className: 'n-sf', title: 'CASE-0012345', meta: 'Acme commitment', role: 'Impact', score: '0.87', delay: '.9s' },
  { key: 'github', className: 'n-gh', title: 'PR-1287', meta: 'Merged fix', role: 'Change', score: '0.74', delay: '1.8s' }
];

const demoResults: Result[] = [
  {
    source_system: 'slack',
    source_type: 'Slack thread',
    external_id: 'SLACK-000271',
    title: 'Decision: Orion GA moves Jul 1 to Jul 15',
    snippet:
      "After the readiness review, we're making the call. Orion GA moves from July 1 to July 15. ORION-1473 replication lag is the sole gating item; hotfix path is partitioned WAL shipping. CS to notify Acme before EOD.",
    status: 'Decision',
    priority: 'P1',
    owner: 'Priya Mehta',
    project_key: 'ORION',
    component: '#proj-orion',
    updated_at: '2026-06-23T16:12:00-04:00',
    final_score: 0.93,
    text_rank: 0.02,
    vector_score: 0.98,
    rrf_score: 0.0325
  },
  {
    source_system: 'jira',
    source_type: 'Issue',
    external_id: 'ORION-1473',
    title: 'ORION-1473 - Cross-region replication lag exceeds 90s in events pipeline',
    snippet:
      'P1 blocker for ORION-1450 GA cutover. Consumers in eu-west-1 fall behind under peak write load; freshness SLO for the readiness gate is 15s. Root cause traced to single-stream WAL shipping; fix is regional partitioning.',
    status: 'Resolved Jul 3',
    priority: 'P1',
    owner: 'Rafael Ortiz',
    project_key: 'ORION',
    component: 'Events pipeline',
    updated_at: '2026-07-03T10:20:00-04:00',
    final_score: 0.89,
    text_rank: 0.96,
    vector_score: 0.88,
    trigram_score: 0.71,
    rrf_score: 0.0322
  },
  {
    source_system: 'salesforce',
    source_type: 'Case',
    external_id: 'CASE-0012345',
    title: 'CASE-0012345 - Acme Corp go-live commitment at risk',
    snippet:
      'Contractual go-live July 8 per MSA addendum. CSM note: informed champion of Orion slip; negotiating revised date of July 22 with success-plan credit. Renewal ARR $1.2M is flagged as commitment impact.',
    status: 'Mitigating',
    priority: 'Tier 1',
    owner: 'Dana Whitfield',
    account_name: 'Acme Corp',
    project_key: 'ORION',
    updated_at: '2026-06-26T11:05:00-04:00',
    final_score: 0.87,
    text_rank: 0.72,
    vector_score: 0.94,
    rrf_score: 0.031
  },
  {
    source_system: 'confluence',
    source_type: 'Runbook',
    external_id: 'PAGE-2112',
    title: 'Orion Release Readiness Runbook - gate criteria and sign-off',
    snippet:
      'Gate 3 data freshness requires replication lag p99 <= 15s across regions for 72h. Jun 18 check: FAILED - lag p99 at 94s in eu-west-1. Per policy, GA date slips until gate passes.',
    status: 'Published',
    priority: 'Policy',
    owner: 'Release Engineering',
    project_key: 'ORION',
    updated_at: '2026-06-18T14:00:00-04:00',
    final_score: 0.82,
    text_rank: 0.9,
    vector_score: 0.72,
    rrf_score: 0.0295
  },
  {
    source_system: 'servicenow',
    source_type: 'Incident',
    external_id: 'INC-0012345',
    title: 'INC-0012345 - Replication lag alerts, events pipeline',
    snippet:
      'Sev2 paging on replication_lag_seconds > 60 since Jun 20 02:10 UTC. Correlated with peak ingest from the Orion events pipeline. Linked problem record traced to ORION-1473 and resolved after PR #1287.',
    status: 'Resolved',
    priority: 'Sev2',
    owner: 'SRE on-call',
    account_name: 'Acme Corp',
    project_key: 'ORION',
    updated_at: '2026-06-20T02:10:00+00:00',
    final_score: 0.78,
    text_rank: 0.62,
    vector_score: 0.8,
    trigram_score: 0.64,
    rrf_score: 0.0271
  },
  {
    source_system: 'github',
    source_type: 'Pull request',
    external_id: 'PR-1287',
    title: 'PR #1287 - events: partition WAL shipping by region',
    snippet:
      'Merged Jul 2. Fixes ORION-1473. Splits the single WAL stream into per-region partitions with bounded consumer groups; soak test shows replication lag p99 8s, down from 94s.',
    status: 'Merged',
    priority: 'Change',
    owner: 'rafael-ortiz',
    project_key: 'ORION',
    component: 'orion/events-pipeline',
    updated_at: '2026-07-02T19:47:00-04:00',
    final_score: 0.74,
    text_rank: 0.48,
    vector_score: 0.76,
    rrf_score: 0.0253
  }
];

const resultSignals = [
  ['FTS #2', 'VECTOR #1', 'TRGM -', 'RRF 0.0325', 'RERANK 0.93', 'references -> ORION-1473', 'impacts -> CASE-0012345'],
  ['FTS #1', 'VECTOR #3', 'TRGM .71', 'RRF 0.0322', 'RERANK 0.89', 'blocks -> GA cutover', 'fixed-by -> PR #1287'],
  ['FTS #6', 'VECTOR #2', 'TRGM -', 'RRF 0.0310', 'RERANK 0.87', 'impacted-by -> GA delay'],
  ['FTS #3', 'VECTOR #7', 'TRGM -', 'RRF 0.0295', 'RERANK 0.82', 'gates -> GA cutover'],
  ['FTS #9', 'VECTOR #5', 'TRGM .64', 'RRF 0.0271', 'RERANK 0.78', 'caused-by -> ORION-1473'],
  ['FTS #11', 'VECTOR #6', 'TRGM -', 'RRF 0.0253', 'RERANK 0.74', 'fixes -> ORION-1473']
];

const sourceRoles: Record<string, { type: string; role: string }> = {
  slack: { type: 'Decision', role: 'Slack thread' },
  jira: { type: 'Blocker', role: 'Jira issue' },
  salesforce: { type: 'Impact', role: 'Salesforce case' },
  confluence: { type: 'Policy', role: 'Confluence page' },
  servicenow: { type: 'Incident', role: 'ServiceNow' },
  github: { type: 'Change', role: 'GitHub PR' }
};

const trailEvents = [
  {
    side: 'left',
    date: 'JUN 12 - 09:41',
    system: 'jira',
    type: 'Blocker filed - Jira',
    title: 'ORION-1473 - Cross-region replication lag exceeds 90s',
    body: 'P1 opened against the events pipeline. Consumers in eu-west-1 fall behind at peak write load; freshness SLO is 15s, observed 94s.',
    edges: ['blocks -> ORION-1450 - GA cutover'],
    hop: 'blocks'
  },
  {
    side: 'right',
    date: 'JUN 18 - 14:00',
    system: 'confluence',
    type: 'Gate check - Confluence',
    title: 'Release Readiness Runbook - Gate 3 FAILED',
    body: 'Data-freshness gate requires lag p99 <= 15s for 72h. Check recorded FAILED; per policy the GA date slips until the gate passes.',
    edges: ['gates -> GA cutover', 'references -> ORION-1473'],
    hop: 'caused-by'
  },
  {
    side: 'left',
    date: 'JUN 20 - 02:10 UTC',
    system: 'servicenow',
    type: 'Incident opened - ServiceNow',
    title: 'INC-0012345 - Replication lag alerts in prod',
    body: "Sev2 paging on replication_lag_seconds > 60 in eu-west-1. Problem record links the alert storm to ORION-1473's root cause.",
    edges: ['caused-by -> ORION-1473'],
    hop: 'decided-in'
  },
  {
    side: 'right',
    date: 'JUN 23 - 16:12',
    system: 'slack',
    type: 'Decision - Slack #proj-orion',
    title: 'Decision: Orion GA moves Jul 1 to Jul 15',
    body: 'Priya Mehta calls it after readiness review: GA slips two weeks; hotfix path is partitioned WAL shipping; CS to notify Acme same day.',
    edges: ['decided-in -> #proj-orion', 'impacts -> CASE-0012345'],
    hop: 'impacts'
  },
  {
    side: 'left',
    date: 'JUN 26 - 11:05',
    system: 'salesforce',
    type: 'Commitment at risk - Salesforce',
    title: 'CASE-0012345 - Acme Corp go-live',
    body: 'Contractual go-live was July 8. CSM negotiating revised date of July 22 with a success-plan credit; exec sponsor informed. $1.2M renewal ARR flagged.',
    edges: ['impacted-by -> GA delay', 'references -> Slack decision'],
    hop: 'fixes'
  },
  {
    side: 'right',
    date: 'JUL 2 - 19:47',
    system: 'github',
    type: 'Fix merged - GitHub',
    title: 'PR #1287 - events: partition WAL shipping by region',
    body: 'Soak test: replication lag p99 down to 8s from 94s. Rolled out behind events.partitioned_wal; two approvals, merged to release/2026.07.',
    edges: ['fixes -> ORION-1473', 'resolves -> INC-0012345'],
    hop: 'closes the loop'
  },
  {
    side: 'left',
    date: 'JUL 3 - 10:20',
    system: 'jira',
    type: 'Blocker resolved - Jira',
    title: 'ORION-1473 resolved - gate re-run PASSED',
    body: 'Gate re-run passes with lag p99 at 8s. July 15 GA remains on track and customer notification is updated with the new target.',
    edges: ['passes -> readiness gate', 'supports -> Jul 15 GA'],
    final: true
  }
];

const diagnosticsRows = [
  ['1', 'slack', 'Decision: GA moves Jul 1 to 15', '#2', '#1', '-', '.0325', '0.93', '[1]'],
  ['2', 'jira', 'ORION-1473 replication lag', '#1', '#3', '.71', '.0322', '0.89', '[2]'],
  ['3', 'salesforce', 'CASE-0012345 Acme go-live', '#6', '#2', '-', '.0310', '0.87', '[3]'],
  ['4', 'confluence', 'Release Readiness Runbook', '#3', '#7', '-', '.0295', '0.82', '[4]'],
  ['5', 'servicenow', 'INC-0012345 lag alerts', '#9', '#5', '.64', '.0271', '0.78', '[5]'],
  ['6', 'github', 'PR #1287 partition WAL shipping', '#11', '#6', '-', '.0253', '0.74', '[6]'],
  ['7', 'slack', 'Standup thread GA checklist', '#4', '#12', '-', '.0231', '0.58', 'unused'],
  ['8', 'confluence', 'Postmortem May backpressure', '#14', '#9', '-', '.0212', '0.51', 'below cut']
];

function cx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(' ');
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

function displayScore(result: Result, fallbackIndex = 0) {
  const value = score(result);
  if (value > 0 && value <= 1) return value;
  return demoResults[fallbackIndex]?.final_score || Math.min(0.99, Math.max(0.55, value / 2));
}

function sourceLabel(system: string) {
  const labels: Record<string, string> = {
    slack: 'Slack',
    jira: 'Jira',
    confluence: 'Confluence',
    salesforce: 'Salesforce',
    github: 'GitHub',
    servicenow: 'ServiceNow'
  };
  return labels[system] || system;
}

const brandLogoUrls: Record<string, string> = {
  slack: slackIconUrl,
  jira: jiraLogoUrl,
  confluence: confluenceLogoUrl,
  salesforce: salesforceLogoUrl,
  servicenow: serviceNowLogoUrl
};

function brandImageStyle(system: string, size: number): React.CSSProperties {
  if (system === 'servicenow') return { width: Math.round(size * 2.9), height: Math.round(size * 0.66) };
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

function resultRole(result: Result) {
  const role = sourceRoles[result.source_system] || { type: 'Evidence', role: result.source_type || 'Source object' };
  return `${role.type} - ${role.role}`;
}

function orderedEvidence(results: Result[]) {
  const normalized = results.map(normalizeResult);
  const seen = new Set<string>();
  const ordered = evidenceOrder
    .map((source) => normalized.find((result) => result.source_system === source) || demoResults.find((result) => result.source_system === source))
    .filter(Boolean) as Result[];
  const extras = normalized.filter((result) => !ordered.some((item) => item.source_system === result.source_system && item.external_id === result.external_id));
  return [...ordered, ...extras].filter((result) => {
    const key = `${result.source_system}:${result.external_id}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <div className={cx('wordmark', compact && 'compact')}>
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r="9.4" fill="none" stroke="currentColor" strokeWidth="1.7" />
        <path
          d="M4.2 13.4c2.6-3.8 5.4 1.6 8.2-1.6 1.9-2.2 4.4-2.4 7.4-.6"
          fill="none"
          stroke="var(--red)"
          strokeWidth="1.7"
          strokeLinecap="round"
        />
      </svg>
      {!compact && <span>{APP_NAME}</span>}
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
  onNavigate
}: {
  page: Page;
  query: string;
  setQuery: (value: string) => void;
  onSearch: () => void;
  onNavigate: (page: Page) => void;
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
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={queryDefault}
          aria-label="Search evidence"
        />
        <kbd>⌘K</kbd>
      </form>
      <nav className="appnav" aria-label="Threadline workspace">
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

function Landing({
  query,
  setQuery,
  onSearch,
  onNavigate,
  error
}: {
  query: string;
  setQuery: (value: string) => void;
  onSearch: (queryOverride?: string) => void;
  onNavigate: (page: Page) => void;
  error?: string;
}) {
  return (
    <div className="landing-page">
      <nav className="topnav">
        <button className="wordmark-button" onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}>
          <Logo />
        </button>
        <div className="navlinks">
          <a href="#overview">Overview</a>
          {workspaceNavItems.map((item) => (
            <button key={item.page} type="button" onClick={() => onNavigate(item.page)}>
              {item.label}
            </button>
          ))}
          <a href="#how">How it works</a>
          <a href="#stack">Retrieval stack</a>
        </div>
      </nav>

      <main className="shell" id="overview">
        <section className="hero">
          <div className="hero-copy">
            <div className="eyebrow mono-label">Connected evidence</div>
            <h1>
              Find the{' '}
              <span className="why">
                why
                <svg viewBox="0 0 120 14" preserveAspectRatio="none" aria-hidden="true">
                  <path d="M3 10 C 30 3, 60 13, 117 6" />
                </svg>
              </span>{' '}
              behind the work.
            </h1>
            <p className="sub">
              Connect scattered tickets, docs, cases, incidents, and code to surface the full context and deliver answers
              you can trust, with every source cited.
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
              <text className="edge-label" x="286" y="160" textAnchor="end">gates</text>
              <text className="edge-label" x="196" y="238" textAnchor="end">decided-in</text>
              <text className="edge-label" x="188" y="366" textAnchor="end">blocked-by</text>
              <text className="edge-label" x="448" y="228">impacts</text>
              <text className="edge-label" x="452" y="352">fixed-by</text>
            </svg>

            <div className="center-node">
              <Logo compact />
              <div className="a-title">Answer</div>
              <div className="a-sub">Hybrid fusion</div>
              <div className="a-score">0.92</div>
            </div>

            {heroSourceNodes.map((node) => (
              <article className={cx('hero-node', node.className)} key={node.key} style={{ '--d': node.delay } as React.CSSProperties}>
                <div className="tile">{sourceIcon(node.key, 24)}</div>
                <div className="node-copy">
                  <div className="nhead">
                    <span className="ntype">{node.role}</span>
                    <span className="nscore">{node.score}</span>
                  </div>
                  <div className="ntitle">{node.title}</div>
                  <div className="nmeta">{node.meta}</div>
                </div>
              </article>
            ))}
          </div>

          <div className="searchwrap">
            <SearchComposer query={query} setQuery={setQuery} onSearch={onSearch} autoType className="landing-composer" />
          </div>
        </section>

        <section className="demo-strip" aria-label="Populated Orion run">
          <div>
            <span className="mono-label">Populated Orion run</span>
            <p>Ranked evidence, cited answer, source trail, and diagnostics for the Orion run.</p>
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
              </button>
            ))}
          </div>
        </section>

        <ErrorBanner message={error} />

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
              ['04', 'Answer with receipts', 'Fused, reranked, and synthesized into a cited answer. Every claim points back to its source.', 'synthesize_with_citations()']
            ].map(([num, title, body, fn]) => (
              <article className="step" key={num}>
                <div className="num">{num}</div>
                <h3>{title}</h3>
                <p>{body}</p>
                <span className="fn">{fn}</span>
              </article>
            ))}
          </div>

          <div className="stack" id="stack">
            <span className="mono-label">The hybrid retrieval stack - one engine</span>
            <div className="formula">
              {['Full-text|ts_rank_cd', 'Semantic|pgvector', 'Fuzzy|pg_trgm', 'Fusion|RRF k=60', 'Rerank|Cohere rerank', 'Cited answer|citations'].map((item, index) => {
                const [title, body] = item.split('|');
                return (
                  <React.Fragment key={item}>
                    {index > 0 && <span className="f-op">{index < 3 ? '+' : '->'}</span>}
                    <div className={cx('f-chip', index >= 3 && index <= 4 && 'hot')}>
                      <b>{title}</b>
                      <span>{body}</span>
                    </div>
                  </React.Fragment>
                );
              })}
            </div>
            <div className="foot">
              Powered by <b>Amazon Aurora PostgreSQL</b> - retrieval runs, candidates, citations, and diagnostics stay queryable.
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

function HighlightedSnippet({ text }: { text: string }) {
  const pattern = /(Orion GA moves from July 1 to July 15|ORION-1473|partitioned WAL shipping|Acme|July 22|Gate 3|FAILED|replication_lag_seconds > 60|PR #1287|8s|94s|go-live July 8|commitment impact)/gi;
  const matcher = /^(Orion GA moves from July 1 to July 15|ORION-1473|partitioned WAL shipping|Acme|July 22|Gate 3|FAILED|replication_lag_seconds > 60|PR #1287|8s|94s|go-live July 8|commitment impact)$/i;
  const parts = text.split(pattern);
  return (
    <>
      {parts.map((part, index) => (
        matcher.test(part) ? <mark key={`${part}-${index}`}>{part}</mark> : <React.Fragment key={`${part}-${index}`}>{part}</React.Fragment>
      ))}
    </>
  );
}

function ResultCard({
  result,
  index,
  onOpen
}: {
  result: Result;
  index: number;
  onOpen: () => void;
}) {
  const signalSet = resultSignals[index % resultSignals.length] || [];
  return (
    <article className={cx('rcard', index > 5 && 'dim')}>
      <div className="rhead">
        <div className="tile">{sourceIcon(result.source_system, 22)}</div>
        <div>
          <div className="rtype">{resultRole(result)}</div>
          <button className="rtitle" onClick={onOpen}>{result.title}</button>
        </div>
        <div className="rscore">{displayScore(result, index).toFixed(2)}</div>
      </div>
      <p className="rsnippet"><HighlightedSnippet text={result.snippet || 'No snippet returned for this source.'} /></p>
      <div className="rmeta">
        <span>{result.component || result.project_key || sourceLabel(result.source_system)}</span>
        {result.owner && <span>{result.owner}</span>}
        <span>{formatDate(result.updated_at)}</span>
        {result.status && <span>{result.status}</span>}
      </div>
      <div className="rwhy">
        <span className="lbl">Why this matched</span>
        {signalSet.map((sig) => (
          <span key={sig} className={cx('sig', sig.includes('->') && 'link')}>{sig}</span>
        ))}
      </div>
    </article>
  );
}

function ResultsPage({
  page,
  query,
  setQuery,
  results,
  runId,
  error,
  loading,
  setSelected,
  onSearch,
  onNavigate
}: {
  page: Page;
  query: string;
  setQuery: (value: string) => void;
  results: Result[];
  selected: Result | null;
  runId?: string;
  error?: string;
  loading: boolean;
  setSelected: (value: Result) => void;
  onSearch: () => void;
  onNavigate: (page: Page) => void;
}) {
  const evidence = orderedEvidence(results);

  function openResult(result: Result) {
    setSelected(result);
    onNavigate('detail');
  }

  return (
    <section className="inner-screen">
      <AppHeader page={page} query={query || queryDefault} setQuery={setQuery} onSearch={onSearch} onNavigate={onNavigate} />
      <div className="filters">
        <button className="fchip on">All <span className="n">148</span></button>
        {coreSources.map((source) => (
          <button className="fchip" key={source.key}>
            <MiniBrand system={source.key} />
            {source.label} <span className="n">{source.count}</span>
          </button>
        ))}
        <span className="fdiv" />
        <button className="fsel">Window <b>Last 90 days</b></button>
        <button className="fsel">Rank by <b>Hybrid - RRF + rerank</b></button>
        <button className="fsel">Project <b>Orion</b></button>
      </div>

      <main className="results-layout">
        <section>
          <ErrorBanner message={error} />
          <div className="results-head">
            <div className="count">
              <b>24 results</b> - fused from 148 candidates across 3 rankers - 341 ms - run <b>{runId?.slice(0, 10) || 'rr_7f3a9c'}</b>
            </div>
            <button className="answer-ready" onClick={() => onNavigate('agent')}>
              <span className="dot" />
              Agent answer ready
            </button>
          </div>
          {loading ? (
            <EmptyState loading title="Searching evidence" body="Threadline is retrieving, fusing, and reranking source objects across connected systems." />
          ) : (
            <div className="thread-col">
              {evidence.slice(0, 7).map((result, index) => (
                <ResultCard
                  key={`${result.source_system}-${result.external_id}-${index}`}
                  result={result}
                  index={index}
                  onOpen={() => openResult(result)}
                />
              ))}
            </div>
          )}
        </section>

        <aside className="rail">
          <div className="railcard">
            <div className="mono-label with-dot"><span className="dot" />Agent answer - ready</div>
            <p className="ans-preview">
              Orion's GA slipped two weeks - July 1 to 15 - after replication lag <span className="cit">2</span> failed the readiness gate <span className="cit">4</span>; the team decided in #proj-orion <span className="cit">1</span> and Acme's go-live is being renegotiated <span className="cit">3</span>.
            </p>
            <div className="conf">
              <div className="row"><span>CONFIDENCE</span><b>0.92</b></div>
              <div className="meter"><i /></div>
              <div className="row"><span>COVERAGE</span><b>6 sources - 5 systems</b></div>
            </div>
            <button className="rail-cta" onClick={() => onNavigate('agent')}>Read the full answer</button>
          </div>

          <div className="railcard">
            <div className="mono-label">Evidence graph</div>
            <MiniGraph />
            <button className="rail-link" onClick={() => onNavigate('trail')}>View source trail</button>
          </div>

          <div className="railcard">
            <div className="mono-label">This retrieval</div>
            {[
              ['lexical - ts_rank_cd', '60 cand'],
              ['semantic - pgvector', '60 cand'],
              ['fuzzy - pg_trgm', '40 cand'],
              ['fused - RRF k=60', '92 -> 24'],
              ['reranked - cited', '6 cited'],
              ['latency', '341 ms']
            ].map(([label, value]) => (
              <div className="sumrow" key={label}><span>{label}</span><b>{value}</b></div>
            ))}
            <button className="rail-link" onClick={() => onNavigate('diagnostics')}>Open diagnostics</button>
          </div>
        </aside>
      </main>
    </section>
  );
}

function MiniGraph() {
  return (
    <svg className="minigraph" width="250" height="150" viewBox="0 0 250 150" aria-hidden="true">
      <line x1="125" y1="75" x2="52" y2="30" />
      <line x1="125" y1="75" x2="40" y2="106" />
      <line x1="125" y1="75" x2="198" y2="28" />
      <line x1="125" y1="75" x2="210" y2="102" />
      <line x1="125" y1="75" x2="125" y2="132" />
      <circle className="c" cx="125" cy="75" r="7" />
      <circle className="n" cx="52" cy="30" r="5.5" />
      <circle className="n" cx="40" cy="106" r="5.5" />
      <circle className="n" cx="198" cy="28" r="5.5" />
      <circle className="n" cx="210" cy="102" r="5.5" />
      <circle className="n" cx="125" cy="132" r="5.5" />
      <text x="46" y="20">SLACK</text>
      <text x="30" y="124">JIRA</text>
      <text x="184" y="18">SNOW</text>
      <text x="196" y="120">SFDC</text>
      <text x="112" y="148">GITHUB</text>
      <text x="136" y="70">ANSWER</text>
    </svg>
  );
}

function Citation({ n, onClick }: { n: number; onClick?: () => void }) {
  return <button className="cit" onClick={onClick}> {n} </button>;
}

function AgentPage({
  page,
  query,
  setQuery,
  agentPayload,
  error,
  loading,
  onSearch,
  onAgent,
  onNavigate,
  results
}: {
  page: Page;
  query: string;
  setQuery: (value: string) => void;
  agentPayload: AgentPayload;
  error?: string;
  loading: boolean;
  onSearch: () => void;
  onAgent: () => void;
  onNavigate: (page: Page) => void;
  results: Result[];
}) {
  const evidence = orderedEvidence(agentPayload.results?.map(normalizeResult) || results);
  const runLabel = agentPayload.run_id || 'rr_7f3a9c';

  return (
    <section className="inner-screen">
      <AppHeader page={page} query={query || queryDefault} setQuery={setQuery} onSearch={onSearch} onNavigate={onNavigate} />
      <main className="answer-layout">
        <article>
          <ErrorBanner message={error} />
          {loading ? (
            <EmptyState loading title="Assembling cited answer" body="The agent endpoint is collecting citations and checking the evidence trail." />
          ) : (
            <>
              <div className="eyebrow mono-label">Agent answer - synthesized with citations</div>
              <div className="question">"{query || queryDefault}"</div>
              <div className="answermeta">
                <span className="badge"><i />GROUNDED</span>
                <span>run <b>{runLabel.slice(0, 10)}</b></span>
                <span><b>6 sources</b> - 5 systems</span>
                <span>confidence <b>0.92</b></span>
                <span>Jul 9, 2026 - 09:14</span>
              </div>

              <p className="lead">
                Orion's GA slipped two weeks - <span className="hl">July 1 to July 15</span> - because a P1 replication-lag blocker failed the release-readiness gate. The team decided the slip in Slack on June 23, and one contractual customer commitment, Acme Corp, is being renegotiated.
              </p>

              <div className="prose">
                <p><b>Why it's delayed.</b> The events pipeline developed cross-region replication lag of up to 94 seconds against a 15-second freshness SLO, filed as P1 <b>ORION-1473</b> on June 12 <Citation n={2} />. The Release Readiness Runbook's Gate 3 formally failed on June 18, and policy requires the GA date to slip until the gate passes <Citation n={4} />. The same root cause triggered Sev2 incident <b>INC-0012345</b> in production two days later <Citation n={5} />.</p>
                <p><b>What the team decided.</b> After the readiness review, engineering lead Priya Mehta recorded the decision in <b>#proj-orion</b> on June 23: GA moves from July 1 to July 15, partitioned WAL shipping is the hotfix path, and CS notifies Acme the same day <Citation n={1} />. The fix, <b>PR #1287</b>, merged July 2 and cut lag p99 from 94s to 8s <Citation n={6} />.</p>
              </div>

              <div className="pull">
                <span className="mono-label">The decision, verbatim</span>
                <div className="quote">"We're making the call: Orion GA moves from July 1 to July 15. ORION-1473 is the sole gating item - hotfix path is partitioned WAL shipping. CS to notify Acme before EOD."</div>
                <div className="attr">Priya Mehta - #proj-orion - Jun 23, 2026 - 4:12 PM - cited as <b>[1]</b></div>
              </div>

              <div className="prose">
                <p><b>Which commitments are impacted.</b> One contractual commitment is directly affected: Acme Corp's go-live, promised for July 8 under an MSA addendum <Citation n={3} />. The CSM is renegotiating to July 22 with a success-plan credit; the $1.2M renewal is flagged but the exec sponsor is engaged.</p>
              </div>

              <table className="commit-table">
                <thead>
                  <tr><th>Customer commitment</th><th>Original date</th><th>Now</th><th>Status</th></tr>
                </thead>
                <tbody>
                  <tr>
                    <td><b>Acme Corp - production go-live</b><br />CASE-0012345 - MSA addendum - $1.2M ARR</td>
                    <td>Jul 8, 2026</td>
                    <td><b>Jul 22, 2026</b> proposed</td>
                    <td><span className="status risk">RENEGOTIATING</span></td>
                  </tr>
                  <tr>
                    <td><b>Northwind - pilot expansion</b><br />OPP-88412 - non-contractual target</td>
                    <td>mid-July</td>
                    <td>unchanged</td>
                    <td><span className="status ok">MONITORING</span></td>
                  </tr>
                </tbody>
              </table>

              <section className="plan">
                <h2>How this answer was built</h2>
                <p className="plan-sub">Six tool calls - 148 candidates considered - every step logged to <span>retrieval_runs</span></p>
                {[
                  ['1', 'search_evidence', 'orion delay root cause; systems: jira + slack + confluence', '12 strong candidates - top: ORION-1473'],
                  ['2', 'traverse_links', 'from ORION-1473; edges: blocks, fixes, caused-by, gates', '5 linked objects - 9 edges'],
                  ['3', 'search_evidence', 'orion customer commitments go-live; system: salesforce', '3 candidates - 1 contractual'],
                  ['4', 'compare_sources', 'slack decision against readiness runbook and Jira timeline', 'consistent - no conflicts found'],
                  ['5', 'explain_result', 'top 6 candidates with ranking signals', 'signals stored on retrieval_candidates'],
                  ['6', 'synthesize_with_citations', '6 sources; brief answer style', '9 claims - 9 citations - confidence 0.92']
                ].map(([num, fn, desc, res]) => (
                  <div className="pstep" key={num}>
                    <div className="pnum">{num}</div>
                    <div className="pbody">
                      <div className="fn">{fn}</div>
                      <div className="desc">{desc}</div>
                      <div className="res">{`-> ${res}`}</div>
                    </div>
                  </div>
                ))}
                <div className="actions">
                  <button className="btn primary" onClick={onAgent}>Regenerate answer</button>
                  <button className="btn ghost" onClick={() => onNavigate('trail')}>View source trail</button>
                  <button className="btn ghost" onClick={() => onNavigate('diagnostics')}>Open diagnostics</button>
                </div>
              </section>
            </>
          )}
        </article>

        <aside className="sources-rail">
          <span className="mono-label">Sources - 6 cited</span>
          {evidence.slice(0, 6).map((result, index) => (
            <button className="src" key={`${result.source_system}-${result.external_id}-${index}`}>
              <span className="srcnum">{index + 1}</span>
              <span className="srcbody">
                <span className="srchead">
                  {sourceIcon(result.source_system, 15)}
                  <span className="t">{result.title}</span>
                </span>
                <span className="srcmeta">{sourceLabel(result.source_system).toUpperCase()} - rerank {displayScore(result, index).toFixed(2)}</span>
                <span className="srcwhy">{sourceRoles[result.source_system]?.type || 'Evidence'} supporting the answer.</span>
              </span>
            </button>
          ))}
          <div className="coverage">
            <div className="covrow"><span>CONFIDENCE</span><b>0.92</b></div>
            <div className="meter"><i /></div>
            <p className="covnote"><b>Access-aware retrieval</b> preserved source permissions while assembling the cited answer.</p>
          </div>
        </aside>
      </main>
    </section>
  );
}

function TrailPage({
  page,
  query,
  setQuery,
  error,
  onSearch,
  onNavigate
}: {
  page: Page;
  query: string;
  setQuery: (value: string) => void;
  results: Result[];
  error?: string;
  onSearch: () => void;
  onNavigate: (page: Page) => void;
}) {
  return (
    <section className="inner-screen">
      <AppHeader page={page} query={query || queryDefault} setQuery={setQuery} onSearch={onSearch} onNavigate={onNavigate} />
      <div className="pagehead">
        <div className="eyebrow centered mono-label">Source trail</div>
        <h1>How the Orion delay <em>unfolded.</em></h1>
        <div className="pagesub"><b>8 linked objects - 5 systems</b> - Jun 12 to Jul 3, 2026 - assembled by <b>traverse_links()</b> over <b>object_links</b></div>
        <div className="legend">
          {['blocks', 'caused-by', 'gates', 'decided-in', 'impacts', 'fixes', 'references'].map((edge) => <span className="lg" key={edge}>{edge}</span>)}
        </div>
      </div>
      <ErrorBanner message={error} />
      <div className="trail">
        {trailEvents.map((event, index) => (
          <React.Fragment key={event.date}>
            <div className={cx('event', event.side, event.final && 'final')}>
              <span className="date">{event.date}</span>
              <span className="dot" />
              <div className="ecard">
                <div className="ehead">
                  <div className="tile">{sourceIcon(event.system, 21)}</div>
                  <div>
                    <div className="etype">{event.type}</div>
                    <div className="etitle">{event.title}</div>
                  </div>
                </div>
                <p className="ebody"><HighlightedSnippet text={event.body} /></p>
                <div className="edges">{event.edges.map((edge) => <span className="edge" key={edge}>{edge}</span>)}</div>
              </div>
            </div>
            {event.hop && index < trailEvents.length - 1 && <div className="hop"><span>{event.hop}</span></div>}
          </React.Fragment>
        ))}
        <div className="outcome">
          <span className="mono-label">Outcome</span>
          <div className="big">July 15 GA remains credible because the blocker is fixed, the gate re-run passed, and Acme has a revised commitment path.</div>
        </div>
      </div>
    </section>
  );
}

function DiagnosticsPage({
  page,
  query,
  setQuery,
  onSearch,
  onNavigate
}: {
  page: Page;
  query: string;
  setQuery: (value: string) => void;
  onSearch: () => void;
  onNavigate: (page: Page) => void;
}) {
  return (
    <section className="inner-screen">
      <AppHeader page={page} query={query || queryDefault} setQuery={setQuery} onSearch={onSearch} onNavigate={onNavigate} />
      <main className="diagnostics-layout">
        <div className="eyebrow mono-label">Retrieval diagnostics</div>
        <h1>Run <em>rr_7f3a9c</em> - every rank, explained.</h1>
        <div className="runmeta">
          <span>region <b>us-east-1</b></span>
          <span>answer model <b>global.anthropic.claude-opus-4-8</b></span>
          <span>router model <b>global.anthropic.claude-sonnet-5</b></span>
          <span>embedding <b>us.cohere.embed-v4:0</b></span>
          <span>rerank <b>cohere.rerank-v3-5:0</b></span>
        </div>

        <div className="tiles">
          {[
            ['Total latency', '341', 'ms', 'p50 this profile: 318 ms'],
            ['Candidate funnel', '148 -> 6', '', 'fetched -> cited - 4.1%'],
            ['Fusion', 'RRF', 'k=60', '3 rankers - weights 1 / 1 / 0.5'],
            ['Rerank', '0.55', 'cut', 'cross-encoder - 24 scored']
          ].map(([k, v, unit, d]) => (
            <div className="stile" key={k}>
              <div className="k">{k}</div>
              <div className="v">{v}<small>{unit}</small></div>
              <div className="d">{d}</div>
            </div>
          ))}
        </div>

        <div className="grid2">
          <BarPanel
            title="Where the time went"
            subtitle="MS PER STAGE - TOTAL 341"
            rows={[
              ['parse + plan', '12', 5.7],
              ['lexical - FTS', '38', 18.1],
              ['semantic - vector', '54', 25.7],
              ['fuzzy - trgm', '21', 10],
              ['fusion - RRF', '6', 2.9],
              ['rerank', '210', 100, true]
            ]}
            note="Rerank dominates at 62% of latency and is scoped to 24 fused candidates, not all 148 fetched rows."
          />
          <BarPanel
            title="Candidate funnel"
            subtitle="RETRIEVAL_CANDIDATES"
            rows={[
              ['fetched', '148', 100],
              ['deduped', '92', 62.2],
              ['fused - top-k', '24', 16.2],
              ['above cut >= .55', '12', 8.1],
              ['cited', '6', 4.1, true]
            ]}
            note="56 duplicates collapsed across rankers. Five of six cited objects were found by at least two retrieval modes."
          />
        </div>

        <div className="tablewrap">
          <div className="twhead">
            <div className="ptitle">Top candidates, signal by signal</div>
            <div className="psub">SHOWING 8 OF 24 - ORDER BY FINAL</div>
          </div>
          <table>
            <thead>
              <tr><th>#</th><th className="l">Source object</th><th>FTS</th><th>VEC</th><th>TRGM</th><th>RRF</th><th>RERANK</th><th>CITED</th></tr>
            </thead>
            <tbody>
              {diagnosticsRows.map(([rank, system, title, fts, vec, trgm, rrf, rerank, cited], index) => (
                <tr className={index < 6 ? 'cited' : ''} key={`${rank}-${title}`}>
                  <td className="rk">{rank}</td>
                  <td className="l"><span className="srcobj">{sourceIcon(system, 15)}{title}<span>{sourceLabel(system).toUpperCase()}</span></span></td>
                  <td>{fts}</td>
                  <td>{vec}</td>
                  <td>{trgm}</td>
                  <td>{rrf}</td>
                  <td><span className="scorebar"><span className="tr"><i style={{ width: `${Number(rerank) * 100}%` }} /></span>{rerank}</span></td>
                  <td className={index < 6 ? 'ck' : 'cut'}>{cited}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="tfoot">Every row is a persisted record in <b>retrieval_candidates</b>: rank positions, fused score, rerank score, and citation outcome.</div>
        </div>

        <div className="sql">
          <div className="sql-head">
            <div className="ptitle">RRF fusion query shape</div>
            <div className="psub">Aurora PostgreSQL</div>
          </div>
          <pre>{`WITH lexical AS (... ts_rank_cd(search_vector, plainto_tsquery($1)) ...),
semantic AS (... embedding <=> $query_embedding ...),
fuzzy AS (... similarity(title, $1) ...),
fused AS (
  SELECT object_id,
    SUM(weight / (60 + rank_position)) AS rrf_score
  FROM ranked_candidates
  GROUP BY object_id
)
SELECT * FROM fused
ORDER BY rrf_score DESC
LIMIT 24;`}</pre>
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
  note: string;
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
  onNavigate
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
}) {
  const citations = objectDetail?.citations || [];
  const chunks = objectDetail?.chunks || [];
  const links = objectDetail?.links || [];

  return (
    <section className="inner-screen">
      <AppHeader page={page} query={query || queryDefault} setQuery={setQuery} onSearch={onSearch} onNavigate={onNavigate} />
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
              <span>score {displayScore(selected).toFixed(2)}</span>
            </div>
            <section className="detail-section">
              <h2>Retrieved passage</h2>
              <p>{selected.snippet}</p>
            </section>
            {detailLoading && <p className="detail-loading">Loading source detail...</p>}
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
                  <p key={link.link_id || `${link.source_system}-${link.external_id}`}>{sourceLabel(link.source_system)} - {link.title}</p>
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
  const [selected, setSelected] = useState<Result | null>(null);
  const [runId, setRunId] = useState<string>();
  const [agentPayload, setAgentPayload] = useState<AgentPayload>({});
  const [objectDetail, setObjectDetail] = useState<ObjectDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(false);

  function navigate(pageTarget: Page) {
    setLoading(false);
    setError(undefined);
    if (pageTarget !== 'landing' && (page === 'landing' || !query.trim())) setQuery(showcaseQuery);
    if (pageTarget === 'detail' && !selected) setSelected(demoResults[0]);
    setPage(pageTarget);
  }

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

  async function runSearch(queryOverride?: string) {
    const searchQuery = (queryOverride ?? query).trim() || queryDefault;
    setQuery(searchQuery);
    setPage('results');
    setLoading(true);
    setError(undefined);
    try {
      const resp = await fetch(`${API_URL}/v1/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: searchQuery,
          source_systems: ['slack', 'jira', 'confluence', 'salesforce', 'servicenow', 'github'],
          project_key: searchQuery.toLowerCase().includes('orion') ? 'ORION' : undefined,
          limit: 8
        })
      });
      if (!resp.ok) throw new Error(`Search failed with HTTP ${resp.status}`);
      const json = (await resp.json()) as SearchResponse;
      const rows = (json.results || []).map(normalizeResult);
      setRunId(json.run_id);
      setResults(rows);
      setSelected(rows[0] || null);
    } catch (err) {
      setRunId(undefined);
      setResults([]);
      setSelected(null);
      setError(err instanceof Error ? err.message : 'Search failed. Check the API and local Postgres setup.');
    } finally {
      setLoading(false);
    }
  }

  async function runAgent() {
    const question = query.trim() || queryDefault;
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
      const rows = (json.results || []).map(normalizeResult);
      setAgentPayload(json);
      setResults(rows);
      setSelected(rows[0] || selected);
      setRunId(json.run_id);
    } catch (err) {
      setAgentPayload({});
      setError(err instanceof Error ? err.message : 'Agent answer failed. Check the API and local Postgres setup.');
    } finally {
      setLoading(false);
    }
  }

  if (page === 'landing') {
    return <Landing query={query} setQuery={setQuery} onSearch={runSearch} onNavigate={navigate} error={error} />;
  }

  if (page === 'detail') {
    return (
      <DetailPage
        page={page}
        query={query}
        setQuery={setQuery}
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
    return <TrailPage page={page} query={query} setQuery={setQuery} results={results} error={error} onSearch={runSearch} onNavigate={navigate} />;
  }

  if (page === 'agent') {
    return (
      <AgentPage
        page={page}
        query={query}
        setQuery={setQuery}
        agentPayload={agentPayload}
        error={error}
        loading={loading}
        onSearch={runSearch}
        onAgent={runAgent}
        onNavigate={navigate}
        results={results}
      />
    );
  }

  if (page === 'diagnostics') {
    return <DiagnosticsPage page={page} query={query} setQuery={setQuery} onSearch={runSearch} onNavigate={navigate} />;
  }

  return (
    <ResultsPage
      page={page}
      query={query}
      setQuery={setQuery}
      results={results}
      selected={selected}
      runId={runId}
      error={error}
      loading={loading}
      setSelected={setSelected}
      onSearch={runSearch}
      onNavigate={navigate}
    />
  );
}

createRoot(document.getElementById('root')!).render(<App />);
