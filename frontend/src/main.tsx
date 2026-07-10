import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ArrowLeft, Database, ExternalLink, Search, ShieldCheck } from 'lucide-react';
import { FaGithub } from 'react-icons/fa6';
import confluenceLogoUrl from './assets/confluence-2017.svg';
import jiraLogoUrl from './assets/jira-streamline.svg';
import salesforceLogoUrl from './assets/salesforce-logo.jpeg';
import slackIconUrl from './assets/slack-icon-2019.svg';
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
  confidence?: number;
  source_count?: number;
  system_count?: number;
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
const APP_NAME = import.meta.env.VITE_APP_DISPLAY_NAME || 'AuraLens';
const ENABLE_ANSWER_STREAMING = import.meta.env.VITE_ENABLE_ANSWER_STREAMING !== '0';
const queryDefault = 'Why did Orion slip?';
const showcaseQuery = 'Why did Orion slip, and which customer commitments are at risk?';
const rotatingQueries = [
  queryDefault,
  showcaseQuery,
  'Why did ORION-1489 page in prod, and what fixed it?',
  'Which customer commitments are at risk from the Orion slip?',
  'What blocked Orion’s release, and how did the fix ship?'
];

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
    query: 'Explain the Orion delay end to end — cause, impact, and resolution.',
    sources: ['slack', 'jira', 'confluence', 'salesforce', 'github']
  }
];

const workspaceNavItems: Array<{ page: Page; label: string; eyebrow: string; summary: string }> = [
  { page: 'results', label: 'Evidence', eyebrow: '24 ranked results', summary: 'Hybrid-ranked sources and linked context' },
  { page: 'agent', label: 'Answer', eyebrow: '6 cited sources', summary: 'Synthesized answer with inline citations' },
  { page: 'trail', label: 'Timeline', eyebrow: '8 linked events', summary: 'Time-ordered cross-system sequence' },
  { page: 'diagnostics', label: 'Diagnostics', eyebrow: '341 ms run', summary: 'Fusion, scoring, latency, and SQL trace' }
];

const coreSources = [
  { key: 'slack', label: 'Slack', count: 30 },
  { key: 'jira', label: 'Jira', count: 30 },
  { key: 'confluence', label: 'Confluence', count: 30 },
  { key: 'salesforce', label: 'Salesforce', count: 30 },
  { key: 'github', label: 'GitHub', count: 30 }
];

// Total corpus size and cited-object order are the single source of truth for
// every count shown in the UI. 150 objects, symmetric 30 per system across the
// five connected systems (Slack, Jira, Confluence, Salesforce, GitHub).
const corpusTotal = coreSources.reduce((sum, source) => sum + source.count, 0);
// Canonical cited order by external_id — two Jira citations (the blocker and
// the full-text-surfaced ops ticket), so citations are keyed by external_id.
// Canonical citation order, by external_id — the exact sequence the answer prose
// cites as [1]..[6]. The evidence rail is ordered by THIS, not by source system:
// two Jira objects are cited (the blocker ORION-1473 at [2] and the full-text-
// surfaced ops ticket ORION-1489 at [5]), so grouping by system would collapse
// them into one slot and misalign every citation marker after it.
const citedOrder = ['SLACK-000271', 'ORION-1473', 'CASE-0012345', 'PAGE-2112', 'ORION-1489', 'PR-1287'];

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

const evidenceGraphEdges = [
  {
    from: { system: 'slack', title: 'Slack decision', meta: 'SLACK-000271' },
    relation: 'impacts',
    to: { system: 'salesforce', title: 'Acme go-live', meta: 'CASE-0012345' },
    why: 'Shows the customer commitment that moved to July 22.'
  },
  {
    from: { system: 'jira', title: 'ORION-1473', meta: 'P1 blocker' },
    relation: 'gated by',
    to: { system: 'confluence', title: 'Gate 3 runbook', meta: 'PAGE-2112' },
    why: 'Explains why GA could not ship on July 1.'
  },
  {
    from: { system: 'github', title: 'PR #1287', meta: 'merged fix' },
    relation: 'fixes',
    to: { system: 'jira', title: 'ORION-1473', meta: 'resolved Jul 3' },
    why: 'Closes the blocker and supports the July 15 target.'
  }
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
    title: 'ORION-1473 — Cross-region replication lag exceeds 90s in events pipeline',
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
    title: 'CASE-0012345 — Acme Corp go-live commitment at risk',
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
    title: 'Orion Release Readiness Runbook — gate criteria and sign-off',
    snippet:
      'Gate 3 data freshness requires replication lag p99 ≤ 15s across regions for 72h. Jun 18 check: FAILED — lag p99 at 94s in eu-west-1. Per policy, GA date slips until gate passes.',
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
    source_system: 'jira',
    source_type: 'Ops ticket',
    external_id: 'ORION-1489',
    title: 'ORION-1489 — replication_lag_seconds > 60 paging in prod (eu-west-1)',
    snippet:
      'Ops ticket auto-filed by the alerting bot: replication_lag_seconds > 60 paging since Jun 20 02:10 UTC in eu-west-1. Full-text match on the exact metric name and region. Linked to ORION-1473 as the root cause; mitigated by consumer scale-out, resolved after PR #1287.',
    status: 'Resolved',
    priority: 'Sev2',
    owner: 'SRE on-call',
    account_name: 'Acme Corp',
    project_key: 'ORION',
    component: 'Events pipeline',
    updated_at: '2026-06-20T02:10:00+00:00',
    final_score: 0.78,
    text_rank: 0.94,
    vector_score: 0.66,
    trigram_score: 0.64,
    rrf_score: 0.0271
  },
  {
    source_system: 'github',
    source_type: 'Pull request',
    external_id: 'PR-1287',
    title: 'PR #1287 — events: partition WAL shipping by region',
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
  ['FTS #2', 'VECTOR #1', 'TRGM —', 'RRF 0.0325', 'FINAL 0.93', 'references → ORION-1473', 'impacts → CASE-0012345'],
  ['FTS #1', 'VECTOR #3', 'TRGM .71', 'RRF 0.0322', 'FINAL 0.89', 'blocks → GA cutover', 'fixed-by → PR #1287'],
  ['FTS #6', 'VECTOR #2', 'TRGM —', 'RRF 0.0310', 'FINAL 0.87', 'impacted-by → GA delay'],
  ['FTS #3', 'VECTOR #7', 'TRGM —', 'RRF 0.0295', 'FINAL 0.82', 'gates → GA cutover'],
  ['FTS #4', 'VECTOR #14', 'TRGM .64', 'RRF 0.0271', 'FINAL 0.78', 'caused-by → ORION-1473'],
  ['FTS #11', 'VECTOR #6', 'TRGM —', 'RRF 0.0253', 'FINAL 0.74', 'fixes → ORION-1473']
];

const sourceRoles: Record<string, { type: string; role: string }> = {
  slack: { type: 'Decision', role: 'Slack thread' },
  jira: { type: 'Blocker', role: 'Jira issue' },
  salesforce: { type: 'Impact', role: 'Salesforce case' },
  confluence: { type: 'Policy', role: 'Confluence page' },
  github: { type: 'Change', role: 'GitHub PR' }
};

// Per-citation strings, keyed by external_id (two Jira citations: the blocker
// ORION-1473 and the full-text-surfaced ops ticket ORION-1489).
const sourceCitations: Record<string, { meta: string; why: string }> = {
  'SLACK-000271': {
    meta: 'SLACK · #proj-orion · JUN 23 · score 0.93',
    why: 'The decision itself — answers "what did the team decide."'
  },
  'ORION-1473': {
    meta: 'JIRA · P1 · JUN 12 – JUL 3 · score 0.89',
    why: 'Root cause and timeline; blocks the GA cutover story.'
  },
  'CASE-0012345': {
    meta: 'SALESFORCE · TIER 1 · JUN 26 · score 0.87',
    why: 'The impacted contractual commitment and its mitigation.'
  },
  'PAGE-2112': {
    meta: 'CONFLUENCE · GATE 3 · JUN 18 · score 0.82',
    why: 'The policy mechanism that forced the date slip.'
  },
  'ORION-1489': {
    meta: 'JIRA · SEV2 · JUN 20 · score 0.78',
    why: 'Production paging that corroborates the root cause — surfaced by full-text search.'
  },
  'PR-1287': {
    meta: 'GITHUB · MERGED JUL 2 · score 0.74',
    why: 'The fix that unblocked the gate re-run.'
  }
};

// Canonical Orion answer, verbatim from the Answer mockup. This is the single
// source of truth the UI streams; the seed generator emits the same strings
// into ops.agent_answers so the API returns byte-identical content.
const canonicalAnswer = {
  lead: [
    { text: "Orion's GA slipped two weeks — " },
    { hl: 'July 1 to July 15' },
    { text: ' — because a P1 replication-lag blocker failed the release-readiness gate. The team decided the slip in Slack on June 23, and one contractual customer commitment, Acme Corp, is being renegotiated.' }
  ] as RichToken[],
  why: [
    { b: "Why it's delayed." },
    { text: ' The events pipeline developed cross-region replication lag of up to 94 seconds against a 15-second freshness SLO, filed as P1 ' },
    { b: 'ORION-1473' },
    { text: ' on June 12 ' },
    { cite: 2 },
    { text: ". The Release Readiness Runbook's Gate 3 formally failed on June 18, and policy requires the GA date to slip until the gate passes " },
    { cite: 4 },
    { text: '. The same root cause set off Sev2 paging ticket ' },
    { b: 'ORION-1489' },
    { text: ' in production two days later ' },
    { cite: 5 },
    { text: '.' }
  ] as RichToken[],
  decided: [
    { b: 'What the team decided.' },
    { text: ' After the readiness review, engineering lead Priya Mehta recorded the decision in ' },
    { b: '#proj-orion' },
    { text: ' on June 23: GA moves from July 1 to July 15, partitioned WAL shipping is the hotfix path, and CS notifies Acme the same day ' },
    { cite: 1 },
    { text: '. The fix, ' },
    { b: 'PR #1287' },
    { text: ', merged July 2 and cut lag p99 from 94s to 8s ' },
    { cite: 6 },
    { text: '.' }
  ] as RichToken[],
  impacted: [
    { b: 'Which commitments are impacted.' },
    { text: " One contractual commitment is directly affected: Acme Corp's go-live, promised for July 8 under an MSA addendum " },
    { cite: 3 },
    { text: '. The CSM is renegotiating to July 22 with a success-plan credit; the $1.2M renewal is flagged but the exec sponsor is engaged.' }
  ] as RichToken[],
  quote: {
    text: '"We\'re making the call: Orion GA moves from July 1 to July 15. ORION-1473 is the sole gating item — hotfix path is partitioned WAL shipping. CS to notify Acme before EOD."',
    attr: 'Priya Mehta · #proj-orion · Jun 23, 2026 · 4:12 PM · cited as [1]'
  }
};

// The agent's tool calls, in execution order. Streamed as the "how it was
// built" deconstruction. Also the canonical content for ops.retrieval_runs.
const canonicalPlan: Array<{ num: string; fn: string; args: string; desc: string; res: string }> = [
  { num: '1', fn: 'search_evidence', args: '("orion delay root cause", systems: jira+slack+confluence, window: 60d)', desc: 'Question decomposed; lexical + semantic + fuzzy retrieval run in parallel inside Aurora.', res: '12 strong candidates · top: ORION-1473' },
  { num: '2', fn: 'traverse_links', args: '(from: ORION-1473, edges: blocks · fixes · caused-by · gates)', desc: 'Followed stored object_links across systems to the gate check, the incident, and the fix.', res: '5 linked objects · 9 edges' },
  { num: '3', fn: 'search_evidence', args: '("orion customer commitments go-live", systems: salesforce)', desc: 'Targeted pass for commitment language scoped to accounts referencing Orion.', res: '3 candidates · 1 contractual' },
  { num: '4', fn: 'compare_sources', args: '(slack decision ↔ readiness runbook ↔ jira timeline)', desc: 'Checked the decision against gate policy and issue history for contradictions.', res: 'consistent · no conflicts found' },
  { num: '5', fn: 'explain_result', args: '(top 6)', desc: 'Captured per-candidate ranking signals for the diagnostics view.', res: 'signals stored on retrieval_candidates' },
  { num: '6', fn: 'synthesize_with_citations', args: '(6 sources, style: brief)', desc: 'Composed the answer; every claim bound to a citation row in Aurora.', res: '9 claims · 9 citations · confidence 0.92' }
];

// The agent's live reasoning, shown as a single updating line (Claude.ai style)
// before the answer types itself. Each line mirrors a real step of the run that
// just executed in Aurora: embed the query with Cohere, run the three retrievers,
// fuse with RRF, score final candidates, follow links, check for contradictions, then cite.
const thinkingTrace = [
  'Decomposing the question into retrieval intents',
  'Embedding the query with Cohere embed-v4 (1024-d)',
  'Running lexical, semantic, and fuzzy retrieval across Aurora',
  'Fusing candidates with reciprocal rank fusion (k=60)',
  'Scoring fused candidates with SQL ranking signals',
  'Following object links to the gate check, incident, and fix',
  'Checking the decision against gate policy for contradictions',
  'Binding every claim to a citation'
];

const trailEvents = [
  {
    side: 'left',
    date: 'JUN 12 · 09:41',
    system: 'jira',
    type: 'Blocker filed · Jira',
    title: 'ORION-1473 — Cross-region replication lag exceeds 90s',
    body: 'P1 opened against the events pipeline. Consumers in eu-west-1 fall behind at peak write load; freshness SLO is 15s, observed 94s.',
    edges: ['blocks → ORION-1450 · GA cutover'],
    hop: 'blocks'
  },
  {
    side: 'right',
    date: 'JUN 18 · 14:00',
    system: 'confluence',
    type: 'Gate check · Confluence',
    title: 'Release Readiness Runbook — Gate 3 FAILED',
    body: 'Data-freshness gate requires lag p99 ≤ 15s for 72h. Check recorded FAILED; per policy the GA date slips until the gate passes.',
    edges: ['gates → GA cutover', 'references → ORION-1473'],
    hop: 'caused-by'
  },
  {
    side: 'left',
    date: 'JUN 20 · 02:10 UTC',
    system: 'jira',
    type: 'Ops ticket paged · Jira',
    title: 'ORION-1489 — replication_lag_seconds > 60 paging in prod',
    body: "Sev2 paging ticket auto-filed in eu-west-1 on the exact metric name — a clean full-text hit. Links the alert storm to ORION-1473's root cause.",
    edges: ['caused-by → ORION-1473'],
    hop: 'decided-in'
  },
  {
    side: 'right',
    date: 'JUN 23 · 16:12',
    system: 'slack',
    type: 'Decision · Slack #proj-orion',
    title: '"Decision: Orion GA moves Jul 1 → Jul 15"',
    body: 'Priya Mehta calls it after readiness review: GA slips two weeks; hotfix path is partitioned WAL shipping; CS to notify Acme same day.',
    edges: ['decided-in → #proj-orion', 'impacts → CASE-0012345'],
    hop: 'impacts'
  },
  {
    side: 'left',
    date: 'JUN 26 · 11:05',
    system: 'salesforce',
    type: 'Commitment at risk · Salesforce',
    title: 'CASE-0012345 — Acme Corp go-live',
    body: 'Contractual go-live was July 8. CSM negotiating revised date of July 22 with a success-plan credit; exec sponsor informed. $1.2M renewal ARR flagged.',
    edges: ['impacted-by → GA delay', 'references → Slack decision'],
    hop: 'fixes'
  },
  {
    side: 'right',
    date: 'JUL 2 · 19:47',
    system: 'github',
    type: 'Fix merged · GitHub',
    title: 'PR #1287 — events: partition WAL shipping by region',
    body: 'Soak test: replication lag p99 down to 8s from 94s. Rolled out behind events.partitioned_wal; two approvals, merged to release/2026.07.',
    edges: ['fixes → ORION-1473', 'resolves → ORION-1489'],
    hop: 'closes the loop'
  },
  {
    side: 'left',
    date: 'JUL 3 · 10:20',
    system: 'jira',
    type: 'Blocker resolved · Jira',
    title: 'ORION-1473 resolved — gate re-run PASSED',
    body: 'Gate re-run passes with lag p99 at 8s. July 15 GA remains on track and customer notification is updated with the new target.',
    edges: ['passes → readiness gate', 'supports → Jul 15 GA'],
    final: true
  }
];

const diagnosticsRows: Array<[string, string, string, string, string, string, string, string, string]> = [
  ['1', 'slack', 'Decision: GA moves Jul 1 → 15', '#2', '#1', '—', '.0325', '0.93', '✓ [1]'],
  ['2', 'jira', 'ORION-1473 replication lag', '#1', '#3', '.71', '.0322', '0.89', '✓ [2]'],
  ['3', 'salesforce', 'CASE-0012345 Acme go-live', '#6', '#2', '—', '.0310', '0.87', '✓ [3]'],
  ['4', 'confluence', 'Release Readiness Runbook', '#3', '#7', '—', '.0295', '0.82', '✓ [4]'],
  ['5', 'jira', 'ORION-1489 lag paging (FTS hit)', '#4', '#14', '.64', '.0271', '0.78', '✓ [5]'],
  ['6', 'github', 'PR #1287 partition WAL shipping', '#11', '#6', '—', '.0253', '0.74', '✓ [6]'],
  ['7', 'slack', 'Standup thread "GA checklist"', '#7', '#12', '—', '.0231', '0.58', 'above cut · unused'],
  ['8', 'confluence', 'Postmortem: May backpressure', '#14', '#9', '—', '.0212', '0.51', 'below cut'],
  ['9', 'jira', 'ORION-1502 dashboards polish', '#8', '#15', '.58', '.0198', '0.38', 'below cut'],
  ['10', 'github', 'PR #1244 consumer scale-out (reverted)', '—', '#8', '.66', '.0186', '0.34', 'below cut']
];

// Verbatim fusion query from the diagnostics mockup (developer-authored, no user input).
// Rendered via dangerouslySetInnerHTML to preserve the .kw/.fn/.cm/.st syntax spans and
// raw SQL operators (<=>, @@, %, ->) exactly as designed.
const fusionQueryHtml = `<span class="kw">WITH</span> lexical <span class="kw">AS</span> (
  <span class="kw">SELECT</span> chunk_id, <span class="fn">ROW_NUMBER</span>() <span class="kw">OVER</span> (<span class="kw">ORDER BY</span> <span class="fn">ts_rank_cd</span>(tsv, q) <span class="kw">DESC</span>) <span class="kw">AS</span> r
  <span class="kw">FROM</span> object_chunks, <span class="fn">websearch_to_tsquery</span>(<span class="st">'orion delay decision commitments'</span>) q
  <span class="kw">WHERE</span> tsv @@ q <span class="kw">AND</span> project = <span class="st">'orion'</span> <span class="kw">AND</span> created_at &gt; now() - <span class="kw">INTERVAL</span> <span class="st">'90 days'</span>
  <span class="kw">LIMIT</span> 60
), semantic <span class="kw">AS</span> (
  <span class="kw">SELECT</span> chunk_id, <span class="fn">ROW_NUMBER</span>() <span class="kw">OVER</span> (<span class="kw">ORDER BY</span> embedding &lt;=&gt; <span class="st">:query_vec</span>) <span class="kw">AS</span> r
  <span class="kw">FROM</span> object_chunks <span class="kw">WHERE</span> project = <span class="st">'orion'</span>          <span class="cm">-- HNSW index scan</span>
  <span class="kw">ORDER BY</span> embedding &lt;=&gt; <span class="st">:query_vec</span> <span class="kw">LIMIT</span> 60
), fuzzy <span class="kw">AS</span> (
  <span class="kw">SELECT</span> chunk_id, <span class="fn">ROW_NUMBER</span>() <span class="kw">OVER</span> (<span class="kw">ORDER BY</span> <span class="fn">similarity</span>(title, <span class="st">'ORION-1473'</span>) <span class="kw">DESC</span>) <span class="kw">AS</span> r
  <span class="kw">FROM</span> source_objects <span class="kw">WHERE</span> title % <span class="st">'ORION-1473'</span>       <span class="cm">-- pg_trgm entity match</span>
  <span class="kw">LIMIT</span> 40
)
<span class="kw">SELECT</span> chunk_id, <span class="fn">SUM</span>(w / (60 + r)) <span class="kw">AS</span> rrf_score        <span class="cm">-- RRF · k = 60 · w = 1/1/0.5</span>
<span class="kw">FROM</span> (
  <span class="kw">SELECT</span> chunk_id, r, 1.0 <span class="kw">AS</span> w <span class="kw">FROM</span> lexical
  <span class="kw">UNION ALL SELECT</span> chunk_id, r, 1.0 <span class="kw">FROM</span> semantic
  <span class="kw">UNION ALL SELECT</span> chunk_id, r, 0.5 <span class="kw">FROM</span> fuzzy
) fused
<span class="kw">GROUP BY</span> chunk_id <span class="kw">ORDER BY</span> rrf_score <span class="kw">DESC</span> <span class="kw">LIMIT</span> 24;   <span class="cm">-- → final SQL score</span>`;

function cx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(' ');
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
    github: 'GitHub'
  };
  return labels[system] || system;
}

function shortRunId(value: string) {
  const compact = value.replace(/[^a-zA-Z0-9]/g, '');
  if (compact.length > 12) return compact.slice(-8);
  return value;
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

function resultRole(result: Result) {
  const role = sourceRoles[result.source_system] || { type: 'Evidence', role: result.source_type || 'Source object' };
  return `${role.type} · ${role.role}`;
}

function orderedEvidence(results: Result[]) {
  // Order the rail by the canonical citation sequence (by external_id), matching
  // live API rows and falling back to the canonical row when a cited object
  // doesn't surface in the live top-k (e.g. the Salesforce case). This keeps the
  // inline [1]..[6] prose markers aligned with the rail cards.
  const normalized = results.map(normalizeResult);
  const seen = new Set<string>();
  const ordered = citedOrder
    .map((ext) => normalized.find((result) => result.external_id === ext) || demoResults.find((result) => result.external_id === ext))
    .filter(Boolean) as Result[];
  const extras = normalized.filter((result) => !citedOrder.includes(result.external_id));
  return [...ordered, ...extras].filter((result) => {
    const key = `${result.source_system}:${result.external_id}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
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
              Connect scattered tickets, docs, cases, incidents, and code to surface the full context — and deliver answers{' '}
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
              {['Full-text|ts_rank_cd', 'Semantic|pgvector', 'Fuzzy|pg_trgm', 'Fusion|RRF k=60', 'Final score|SQL scoring', 'Cited answer|citations'].map((item, index) => {
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
              Powered by <b>Amazon Aurora PostgreSQL</b> — the durable retrieval index. Source systems remain authoritative; every run is logged and every candidate explained.
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
          <span key={sig} className={cx('sig', sig.includes('→') && 'link')}>{sig}</span>
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
  onAgent,
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
  onAgent: () => void;
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
        <button className="fchip on">All <span className="n">{corpusTotal}</span></button>
        {coreSources.map((source) => (
          <button className="fchip" key={source.key}>
            <MiniBrand system={source.key} />
            {source.label} <span className="n">{source.count}</span>
          </button>
        ))}
        <span className="fdiv" />
        <button className="fsel">Window <b>Last 90 days</b></button>
        <button className="fsel">Rank by <b>Hybrid · RRF + score</b></button>
        <button className="fsel">Project <b>Orion</b></button>
      </div>

      <main className="results-layout">
        <section>
          <ErrorBanner message={error} />
          <div className="results-head">
            <div className="count">
              <b>24 results</b> · fused from {corpusTotal} candidates across 3 rankers · 341 ms · run <b>{runId?.slice(0, 10) || 'rr_7f3a9c'}</b>
            </div>
            <button className="answer-ready" onClick={() => onAgent()}>
              <span className="dot" />
              Agent answer ready →
            </button>
          </div>
          {loading ? (
            <EmptyState loading title="Searching evidence" body={`${APP_NAME} is retrieving, fusing, and scoring source objects across connected systems.`} />
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
            <div className="mono-label with-dot"><span className="dot" />Agent answer · ready</div>
            <p className="ans-preview">
              Orion's GA slipped two weeks — July 1 to 15 — after replication lag <span className="cit">2</span> failed the readiness gate <span className="cit">4</span>; the team decided in #proj-orion <span className="cit">1</span> and Acme's go-live is being renegotiated <span className="cit">3</span>.
            </p>
            <div className="conf">
              <div className="row"><span>CONFIDENCE</span><b>0.92</b></div>
              <div className="meter"><i /></div>
              <div className="row"><span>COVERAGE</span><b>6 sources · 5 systems</b></div>
            </div>
            <button className="rail-cta" onClick={() => onAgent()}>Read the full answer</button>
          </div>

          <div className="railcard">
            <div className="mono-label">Evidence graph</div>
            <MiniGraph />
            <button className="rail-link" onClick={() => onNavigate('trail')}>View timeline →</button>
          </div>

          <div className="railcard">
            <div className="mono-label">This retrieval run</div>
            <div className="retrieval-run">
              <div className="run-intent">
                <span>Intent</span>
                <b>Orion delay + customer risk</b>
                <small>Project ORION · last 90 days · 5 systems</small>
              </div>

              <div className="run-funnel" aria-label="Candidate funnel">
                {[
                  ['Corpus', corpusTotal],
                  ['Raw', 160],
                  ['Deduped', 92],
                  ['Returned', 24],
                  ['Cited', 6]
                ].map(([label, value], index) => (
                  <React.Fragment key={String(label)}>
                    {index > 0 && <span className="funnel-arrow">→</span>}
                    <span className={cx('funnel-step', index === 4 && 'hot')}><b>{value}</b><small>{label}</small></span>
                  </React.Fragment>
                ))}
              </div>

              <div className="ranker-mix">
                {[
                  ['lexical', 'ts_rank_cd', 60, 38],
                  ['semantic', 'pgvector', 60, 42],
                  ['fuzzy', 'pg_trgm', 40, 12]
                ].map(([name, method, count, width]) => (
                  <div className="ranker-row" key={String(name)}>
                    <span><b>{name}</b><small>{method}</small></span>
                    <i><em style={{ width: `${width}%` }} /></i>
                    <strong>{count}</strong>
                  </div>
                ))}
              </div>

              <div className="run-proof">
                <span><b>RRF k=60</b> fused 92 candidates to the top 24.</span>
                <span><b>SQL scoring</b> selected 6 cited objects above the 0.55 cut.</span>
                <span><b>Persisted</b> in retrieval_runs, retrieval_candidates, and citations.</span>
              </div>

              <div className="run-latency">
                <span>Latency</span>
                <b>341 ms</b>
              </div>
            </div>
            <button className="rail-link" onClick={() => onNavigate('diagnostics')}>Open diagnostics →</button>
          </div>
        </aside>
      </main>
    </section>
  );
}

function MiniGraph() {
  return (
    <div className="evidence-graph" aria-label="Evidence relationship graph">
      <div className="graph-summary">
        <span><b>6</b> cited objects</span>
        <span><b>5</b> systems</span>
        <span><b>9</b> object_links</span>
      </div>
      <div className="graph-edge-list">
        {evidenceGraphEdges.map((edge) => (
          <div className="graph-edge" key={`${edge.from.meta}-${edge.relation}-${edge.to.meta}`}>
            <div className="graph-node">
              <span className="graph-icon">{sourceIcon(edge.from.system, 15)}</span>
              <span className="graph-copy">
                <b>{edge.from.title}</b>
                <small>{sourceLabel(edge.from.system)} · {edge.from.meta}</small>
              </span>
            </div>
            <div className="graph-relation"><span>{edge.relation}</span></div>
            <div className="graph-node target">
              <span className="graph-icon">{sourceIcon(edge.to.system, 15)}</span>
              <span className="graph-copy">
                <b>{edge.to.title}</b>
                <small>{sourceLabel(edge.to.system)} · {edge.to.meta}</small>
              </span>
            </div>
            <p>{edge.why}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function Citation({ n, onClick }: { n: number; onClick?: () => void }) {
  return <button className="cit" onClick={onClick}> {n} </button>;
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
  agentPayload,
  runId,
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
  runId?: string;
  error?: string;
  loading: boolean;
  onSearch: () => void;
  onAgent: () => void;
  onNavigate: (page: Page) => void;
  results: Result[];
}) {
  const evidence = orderedEvidence(agentPayload.results?.map(normalizeResult) || results);
  const runLabel = agentPayload.run_id || runId || 'rr_7f3a9c';
  const confidenceValue = typeof agentPayload.confidence === 'number' ? agentPayload.confidence : 0.92;
  const confidenceLabel = confidenceValue.toFixed(2);
  const confidencePercent = Math.round(Math.max(0, Math.min(1, confidenceValue)) * 100);
  const citedSourceCount = agentPayload.source_count || 6;
  const citedSystemCount = agentPayload.system_count || 5;

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
    setBeat(1);
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
  const railReady = !streaming || thinking || beat >= 1;
  const planStage = useStageSequence(canonicalPlan.length + 1, {
    enabled: streaming,
    beatMs: 480,
    startMs: beat >= planStart ? 0 : 999999
  });
  const beatClass = (n: number) => cx('beat', (!streaming || beat >= n) && 'is-in');
  const jumpToCitation = (n: number) => {
    const el = document.querySelector(`.sources-rail .src:nth-of-type(${n})`);
    el?.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'center' });
    el?.classList.add('flash');
    window.setTimeout(() => el?.classList.remove('flash'), 900);
  };

  return (
    <section className="inner-screen">
      <AppHeader page={page} query={query || queryDefault} setQuery={setQuery} onSearch={onSearch} onNavigate={onNavigate} />
      <main className="answer-layout">
        <article>
          <ErrorBanner message={error} />
          {loading ? (
            <EmptyState loading title="Assembling cited answer" body="The agent endpoint is collecting citations and checking the evidence timeline." />
          ) : (
            <>
              <div className="eyebrow mono-label">
                {streaming && thinking
                  ? 'Agent answer · thinking'
                  : streaming && beat < planStart + canonicalPlan.length
                    ? 'Agent answer · streaming with citations'
                    : 'Agent answer · synthesized with citations'}
              </div>
              <div className="question">"{query || queryDefault}"</div>
              <div className="answermeta">
                <span className="badge"><i />GROUNDED</span>
                <span title={runLabel}>run <b>{shortRunId(runLabel)}</b></span>
                <span><b>{citedSourceCount} sources</b> · {citedSystemCount} systems</span>
                <span>Jul 9, 2026 · 09:14</span>
              </div>

              {streaming && thinking && (
                <ThinkingLine steps={thinkingTrace} enabled={streaming} onDone={onThinkingDone} />
              )}

              {(!streaming || (!thinking && beat >= 1)) && (
                <StreamRich
                  className="lead"
                  tokens={canonicalAnswer.lead}
                  enabled={streaming && beat === 1}
                  speed={4}
                  onCite={jumpToCitation}
                  onDone={advance}
                />
              )}

              {(!streaming || beat >= 2) && (
                <div className="prose">
                  {(!streaming || beat >= 2) && (
                    <StreamRich tokens={canonicalAnswer.why} enabled={streaming && beat === 2} onCite={jumpToCitation} onDone={advance} />
                  )}
                  {(!streaming || beat >= 3) && (
                    <StreamRich tokens={canonicalAnswer.decided} enabled={streaming && beat === 3} onCite={jumpToCitation} onDone={advance} />
                  )}
                </div>
              )}

              {(!streaming || beat >= 4) && (
                <div className={cx('pull', beatClass(4))}>
                  <span className="mono-label">The decision, verbatim</span>
                  <div className="quote">{canonicalAnswer.quote.text}</div>
                  <div className="attr">Priya Mehta · #proj-orion · Jun 23, 2026 · 4:12 PM · cited as <b>[1]</b></div>
                </div>
              )}

              {(!streaming || beat >= 5) && (
                <div className="prose">
                  <StreamRich tokens={canonicalAnswer.impacted} enabled={streaming && beat === 5} onCite={jumpToCitation} onDone={advance} />
                </div>
              )}

              {(!streaming || beat >= 6) && (
                <table className={cx('commit-table', beatClass(6))}>
                  <thead>
                    <tr><th>Customer commitment</th><th>Original date</th><th>Now</th><th>Status</th></tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td><b>Acme Corp · production go-live</b><br />CASE-0012345 · MSA addendum · $1.2M ARR</td>
                      <td>Jul 8, 2026</td>
                      <td><b>Jul 22, 2026</b> proposed</td>
                      <td><span className="status risk">RENEGOTIATING</span></td>
                    </tr>
                    <tr>
                      <td><b>Northwind · pilot expansion</b><br />OPP-88412 · non-contractual target</td>
                      <td>mid-July</td>
                      <td>unchanged</td>
                      <td><span className="status ok">MONITORING</span></td>
                    </tr>
                  </tbody>
                </table>
              )}

              {(!streaming || beat >= 7) && (
                <section className={cx('plan', beatClass(7))}>
                  <h2>How this answer was built</h2>
                  <p className="plan-sub">Six tool calls · {corpusTotal} candidates considered · every step logged to <span>retrieval_runs</span></p>
                  {canonicalPlan.map((step, i) => {
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
                  })}
                  {(!streaming || planStage >= canonicalPlan.length) && (
                    <div className="actions beat is-in">
                      <button className="btn primary" onClick={() => onAgent()}>Regenerate answer</button>
                      <button className="btn ghost" onClick={() => onNavigate('trail')}>View timeline</button>
                      <button className="btn ghost" onClick={() => onNavigate('diagnostics')}>Open diagnostics</button>
                    </div>
                  )}
                </section>
              )}

              {(!streaming || planStage >= canonicalPlan.length) && (
                <section className="coverage answer-confidence beat is-in" aria-label="Confidence calculation">
                  <div className="covrow"><span>Confidence</span><b>{confidenceLabel}</b></div>
                  <div className="meter"><i style={{ width: `${confidencePercent}%` }} /></div>
                  <p className="covnote">
                    <b>How it was calculated:</b> the score combines final retrieval strength, citation coverage, cross-source agreement, and contradiction checks for the cited evidence set.
                  </p>
                  <div className="confidence-grid">
                    <div><span>Rank strength</span><b>{citedSourceCount} cited objects above the score cut</b></div>
                    <div><span>Coverage</span><b>9 answer claims bound to citations</b></div>
                    <div><span>Agreement</span><b>{citedSystemCount} systems support the same timeline</b></div>
                  </div>
                  <p className="covnote"><b>✓ No contradictions</b> found by compare_sources across the {citedSourceCount} cited objects. 1 candidate excluded below the 0.55 score cut.</p>
                </section>
              )}
            </>
          )}
        </article>

        <aside className="sources-rail">
          <span className="mono-label">Sources · 6 cited</span>
          {evidence.slice(0, 6).map((result, index) => {
            const citation = sourceCitations[result.external_id] || sourceCitations[result.source_system];
            const meta = citation?.meta || `${sourceLabel(result.source_system).toUpperCase()} · score ${displayScore(result, index).toFixed(2)}`;
            const why = citation?.why || `${sourceRoles[result.source_system]?.type || 'Evidence'} supporting the answer.`;
            const shown = railReady && (!streaming || thinking || beat >= 1 + index);
            return (
              <button
                className={cx('src', 'beat', shown && 'is-in')}
                style={streaming ? { transitionDelay: `${index * 40}ms` } : undefined}
                key={`${result.source_system}-${result.external_id}-${index}`}
              >
                <span className="srcnum">{index + 1}</span>
                <span className="srcbody">
                  <span className="srchead">
                    {sourceIcon(result.source_system, 15)}
                    <span className="t">{result.title}</span>
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

function TimelinePage({
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
  // The timeline assembles itself node-by-node, as if traverse_links() were
  // walking object_links live. One stage per event, plus the outcome card.
  const reducedMotion = useReducedMotion();
  const streaming = !reducedMotion;
  const stage = useStageSequence(trailEvents.length + 1, { enabled: streaming, beatMs: 520, startMs: 320 });
  const walking = streaming && stage < trailEvents.length;

  return (
    <section className="inner-screen">
      <AppHeader page={page} query={query || queryDefault} setQuery={setQuery} onSearch={onSearch} onNavigate={onNavigate} />
      <div className="pagehead">
        <div className="eyebrow centered mono-label">Timeline</div>
        <h1>How the Orion delay <em>unfolded.</em></h1>
        <div className="pagesub"><b>8 linked objects · 5 systems</b> · Jun 12 — Jul 3, 2026 · assembled by <b>traverse_links()</b> over <b>object_links</b> · 9 edges followed</div>
        <div className="legend">
          {['blocks', 'caused-by', 'gates', 'decided-in', 'impacts', 'fixes', 'references'].map((edge) => (
            <span className={cx('lg', edge === 'references' && 'n')} key={edge}>{edge}</span>
          ))}
        </div>
        {walking && (
          <div className="walking mono-label">traverse_links() building timeline<span className="caret" aria-hidden="true" /></div>
        )}
      </div>
      <ErrorBanner message={error} />
      <div className="trail">
        {trailEvents.map((event, index) => {
          const shown = !streaming || stage >= index;
          if (!shown) return null;
          const hopShown = !streaming || stage >= index + 1;
          return (
            <React.Fragment key={event.date}>
              <div className={cx('event', event.side, event.final && 'final', 'beat', 'is-in')}>
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
                  <div className="edges">{event.edges.map((edge) => (
                    <span className={cx('edge', /^(references|resolves) /.test(edge) && 'n')} key={edge}>{edge}</span>
                  ))}</div>
                </div>
              </div>
              {event.hop && index < trailEvents.length - 1 && hopShown && (
                <div className="hop beat is-in"><span>{event.hop}</span></div>
              )}
            </React.Fragment>
          );
        })}
        {(!streaming || stage >= trailEvents.length) && (
          <div className="outcome beat is-in">
            <span className="mono-label">Outcome</span>
            <div className="big">GA lands <span className="date-accent">July 15</span> — blocker fixed, gate passed, and Acme's commitment renegotiated to <span className="date-accent">July 22</span> with the evidence path to prove it.</div>
          </div>
        )}
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
        <h1>Run <em>rr_7f3a9c</em> — every rank, explained.</h1>
        <div className="runmeta">
          <span>profile <b>hybrid-rrf-final-v1</b></span>
          <span>embedding <b>cohere.embed-v4 · 1024d</b></span>
          <span>index <b>HNSW m=16 ef=64</b></span>
          <span>fired <b>Jul 9, 2026 · 09:14:07</b></span>
          <span>stored in <b>retrieval_runs</b></span>
        </div>

        <section className="diagnostics-audit" aria-label="Run audit summary">
          <div className="audit-verdict">
            <span className="tech-pill">Run complete</span>
            <h2>Grounded answer path accepted.</h2>
            <p>Hybrid retrieval produced six cited objects across five systems. The final answer passed source agreement checks, excluded weak candidates below the 0.55 cut, and persisted every candidate signal for inspection.</p>
          </div>
          <div className="audit-checks">
            {[
              ['6 / 6', 'cited objects above cut'],
              ['5', 'systems represented'],
              ['9', 'object_links traversed'],
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
            ['Total latency', '341', 'ms', <>p50 this profile: <b>318 ms</b></>],
            ['Candidate funnel', <>{corpusTotal} <small>→</small> 6</>, '', <>fetched → cited · <b>4.0%</b></>],
            ['Fusion', 'RRF', 'k = 60', <>3 rankers · weights <b>1 / 1 / 0.5</b></>],
            ['Final score', '0.55', 'cut', <>SQL scoring · <b>24 candidates</b></>]
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
            ['03', 'Fuse', 'Collapse ranker overlap with RRF k=60 and keep the top 24 candidates.'],
            ['04', 'Score', 'Apply SQL final scoring, source authority, recency, and the 0.55 cut.'],
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
            subtitle="MS PER STAGE · TOTAL 341"
            rows={[
              ['parse + plan', '12', 5.7],
              ['lexical · FTS', '38', 18.1],
              ['semantic · vector', '54', 25.7],
              ['fuzzy · trgm', '21', 10],
              ['fusion · RRF', '6', 2.9],
              ['answer assembly', '210', 100, true]
            ]}
            note={<>Answer assembly dominates at <b>62%</b> of latency after the top 24 fused candidates are selected. The three retrievals run concurrently in Aurora.</>}
          />
          <BarPanel
            title="Candidate funnel"
            subtitle="RETRIEVAL_CANDIDATES"
            rows={[
              ['fetched', String(corpusTotal), 100],
              ['deduped', '92', 61.3],
              ['fused · top-k', '24', 16],
              ['above cut ≥.55', '12', 8],
              ['cited', '6', 4, true]
            ]}
            note={<>58 duplicates collapsed across rankers — <b>overlap is a good sign</b>: 5 of 6 cited objects were found by ≥2 retrieval modes.</>}
          />
        </div>

        <div className="tablewrap">
          <div className="twhead">
            <div className="ptitle">Top candidates, signal by signal</div>
            <div className="psub">SHOWING 10 OF 24 · ORDER BY FINAL</div>
          </div>
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
                const cited6 = index < 6;
                return (
                  <tr className={cited6 ? 'cited' : ''} key={`${rank}-${title}`}>
                    <td className={cited6 ? 'rk' : ''}>{rank}</td>
                    <td className="l"><span className="srcobj">{sourceIcon(system, 15)}{title}<span>{sourceLabel(system).toUpperCase()}</span></span></td>
                    <td className={rankCellClass(fts)}>{fts}</td>
                    <td className={rankCellClass(vec)}>{vec}</td>
                    <td className={rankCellClass(trgm)}>{trgm}</td>
                    <td>{rrf}</td>
                    <td><span className="scorebar"><span className="tr"><i style={{ width: `${Number(finalScore) * 100}%` }} /></span>{finalScore}</span></td>
                    <td className={cited6 ? 'ck' : 'cut'}>{cited}</td>
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
            <div className="psub">EXPLAIN THE RANKING · AURORA POSTGRESQL</div>
          </div>
          <pre dangerouslySetInnerHTML={{ __html: fusionQueryHtml }} />
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
          source_systems: ['slack', 'jira', 'confluence', 'salesforce', 'github'],
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

  async function runAgent(queryOverride?: string) {
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
      const rows = (json.results || []).map(normalizeResult);
      setAgentPayload(json);
      setResults(rows);
      setSelected(rows[0] || selected);
      setRunId((current) => json.run_id || current);
    } catch (err) {
      // On stage the API may be offline; the canonical Orion narrative is the
      // fallback so the demo always streams. Keep results empty so the rail
      // falls back to the ordered demo evidence.
      setAgentPayload({});
      setError(err instanceof Error ? err.message : 'Agent answer failed. Check the API and local Postgres setup.');
    } finally {
      setLoading(false);
    }
  }

  if (page === 'landing') {
    // A question from the landing page opens Evidence first. The workshop
    // teaches retrieval before synthesis, then lets participants move to Answer.
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
    return <TimelinePage page={page} query={query} setQuery={setQuery} results={results} error={error} onSearch={runSearch} onNavigate={navigate} />;
  }

  if (page === 'agent') {
    return (
      <AgentPage
        page={page}
        query={query}
        setQuery={setQuery}
        agentPayload={agentPayload}
        runId={runId}
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
      onAgent={runAgent}
      onNavigate={navigate}
    />
  );
}

createRoot(document.getElementById('root')!).render(<App />);
