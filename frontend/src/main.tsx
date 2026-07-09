import React, { useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Bell,
  Bookmark,
  Clock3,
  Cloud,
  Database,
  Download,
  ExternalLink,
  FileText,
  GitPullRequest,
  HelpCircle,
  Home,
  LayoutDashboard,
  Link2,
  MessageCircle,
  Network,
  Plus,
  Search,
  Send,
  Settings,
  Share2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Star,
  Table2,
  Ticket,
  Zap
} from 'lucide-react';
import './styles.css';

type Page = 'landing' | 'results' | 'detail' | 'trail' | 'agent';

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

const API_URL = import.meta.env.VITE_RETRIEVAL_API_URL || 'http://localhost:8000';
const APP_NAME = import.meta.env.VITE_APP_DISPLAY_NAME || 'Evidence Trail';
const queryDefault =
  'Why is Project Orion delayed, what did the team decide in Slack, and what customer commitments are impacted?';

const coreSources = [
  { key: 'slack', label: 'Slack threads' },
  { key: 'jira', label: 'Jira issues' },
  { key: 'confluence', label: 'Confluence pages' },
  { key: 'salesforce', label: 'Salesforce cases' },
  { key: 'github', label: 'GitHub PRs' }
];

const graphPositions = [
  { lane: 2, col: 2 },
  { lane: 4, col: 3 },
  { lane: 1, col: 5 },
  { lane: 3, col: 5 },
  { lane: 5, col: 5 },
  { lane: 2, col: 6 },
  { lane: 4, col: 7 }
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

function sourceIcon(system: string, size = 16) {
  if (system === 'slack') return <MessageCircle size={size} />;
  if (system === 'jira') return <Ticket size={size} />;
  if (system === 'confluence') return <FileText size={size} />;
  if (system === 'salesforce') return <Cloud size={size} />;
  if (system === 'github') return <GitPullRequest size={size} />;
  return <Database size={size} />;
}

function formatDate(value?: string) {
  if (!value) return 'recently';
  if (/ago$/i.test(value)) return value;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

function sourceCounts(results: Result[]) {
  const counts = new Map<string, number>();
  for (const result of results) counts.set(result.source_system, (counts.get(result.source_system) || 0) + 1);
  return coreSources.map((source) => ({ ...source, count: counts.get(source.key) || 0 })).filter((source) => source.count > 0);
}

function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <div className={cx('wordmark', compact && 'compact')}>
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="12" cy="12" r="9.5" fill="none" stroke="currentColor" strokeWidth="1.7" />
        <path
          d="M4.3 13.8 C 8.2 8.8, 14.3 15, 19.6 9.2"
          fill="none"
          stroke="var(--thread)"
          strokeWidth="2"
          strokeLinecap="round"
        />
      </svg>
      {!compact && <span>{APP_NAME}</span>}
    </div>
  );
}

function Dot({ system }: { system: string }) {
  return <span className={cx('dot', `dot-${system}`)} />;
}

function EmptyState({ title, body, action }: { title: string; body: string; action?: React.ReactNode }) {
  return (
    <section className="empty-state">
      <h3>{title}</h3>
      <p>{body}</p>
      {action}
    </section>
  );
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

function TopBar({
  query,
  setQuery,
  onSearch,
  onNavigate
}: {
  query: string;
  setQuery: (value: string) => void;
  onSearch: () => void;
  onNavigate: (page: Page) => void;
}) {
  return (
    <header className="topbar">
      <button className="logo-button" onClick={() => onNavigate('landing')} aria-label="Go home">
        <Logo />
      </button>
      <form
        className="top-search"
        onSubmit={(event) => {
          event.preventDefault();
          onSearch();
        }}
      >
        <Search size={16} />
        <input value={query} onChange={(event) => setQuery(event.target.value)} />
        <kbd>Enter</kbd>
      </form>
      <nav className="top-actions" aria-label="Primary">
        <button onClick={() => onNavigate('trail')} title="Open source trail">
          <Network size={16} />
          Trail
        </button>
        <button onClick={() => onNavigate('agent')} title="Open agent answer">
          <Sparkles size={16} />
          Answer
        </button>
        <button title="Notifications">
          <Bell size={16} />
        </button>
        <span className="avatar">AR</span>
      </nav>
    </header>
  );
}

function SideNav({ page, onNavigate }: { page: Page; onNavigate: (page: Page) => void }) {
  const items: Array<{ page: Page; label: string; icon: React.ReactNode }> = [
    { page: 'landing', label: 'Home', icon: <Home size={15} /> },
    { page: 'results', label: 'Search history', icon: <Clock3 size={15} /> },
    { page: 'detail', label: 'Starred', icon: <Star size={15} /> },
    { page: 'trail', label: 'Dashboards', icon: <LayoutDashboard size={15} /> }
  ];

  return (
    <aside className="sidenav">
      <button className="new-search" onClick={() => onNavigate('landing')}>
        <Plus size={14} />
        New search
      </button>
      <div className="nav-list">
        {items.map((item) => (
          <button key={item.label} className={cx(page === item.page && 'active')} onClick={() => onNavigate(item.page)}>
            {item.icon}
            {item.label}
          </button>
        ))}
      </div>
      <div className="nav-list nav-bottom">
        <button>
          <Settings size={15} />
          Settings
        </button>
        <button>
          <HelpCircle size={15} />
          Help and feedback
        </button>
      </div>
    </aside>
  );
}

function Landing({
  query,
  setQuery,
  onSearch,
  onAgent,
  error
}: {
  query: string;
  setQuery: (value: string) => void;
  onSearch: () => void;
  onAgent: () => void;
  error?: string;
}) {
  return (
    <section className="landing-screen">
      <header className="landing-nav">
        <Logo />
        <nav aria-label="Product">
          <button>Product</button>
          <button>How it works</button>
          <button>Resources</button>
          <button>Pricing</button>
          <button>Company</button>
        </nav>
        <div className="landing-auth">
          <button className="text-button">Sign in</button>
          <button className="ink-button">Get started</button>
        </div>
      </header>

      <div className="hero-panel">
        <div className="hero-copy">
          <p className="eyebrow">The red thread</p>
          <h1>
            Find the <em>why</em>
            <br />
            behind the work.
          </h1>
          <p className="hero-sub">
            Connect scattered tickets, docs, cases, incidents, and code to surface the full context and deliver answers you can trust.
          </p>
          <div className="hero-actions">
            <button className="ink-button" onClick={onSearch}>
              Start searching
            </button>
            <button className="quiet-button" onClick={onAgent}>
              <Sparkles size={15} />
              Ask agent
            </button>
          </div>
          <div className="system-strip">
            <span>Works with your systems</span>
            {coreSources.map((source) => (
              <span key={source.key} className="system-mini">
                <Dot system={source.key} />
                {source.label.split(' ')[0]}
              </span>
            ))}
          </div>
        </div>

        <div className="hero-visual" aria-hidden="true">
          <div className="thread-core">
            <Logo compact />
          </div>
          {coreSources.map((source, index) => (
            <div key={source.key} className={cx('orb', `orb-${index + 1}`)}>
              <span className={cx('source-badge', source.key)}>{sourceIcon(source.key, 23)}</span>
            </div>
          ))}
          <span className="thread-line line-1" />
          <span className="thread-line line-2" />
          <span className="thread-line line-3" />
          <span className="thread-line line-4" />
          <span className="thread-line line-5" />
        </div>
      </div>

      <form
        className="landing-search"
        onSubmit={(event) => {
          event.preventDefault();
          onSearch();
        }}
      >
        <Search size={18} />
        <input value={query} onChange={(event) => setQuery(event.target.value)} />
        <button className="ink-button">Search</button>
      </form>
      <ErrorBanner message={error} />
    </section>
  );
}

function ResultRow({
  result,
  index,
  selected,
  onSelect,
  onOpen
}: {
  result: Result;
  index: number;
  selected: boolean;
  onSelect: () => void;
  onOpen: () => void;
}) {
  const rowScore = score(result);
  return (
    <article className={cx('result-row', selected && 'selected')} onClick={onSelect}>
      <span className="rank">{String(index + 1).padStart(2, '0')}</span>
      <span className={cx('source-mark', result.source_system)}>{sourceIcon(result.source_system)}</span>
      <div className="result-body">
        <div className="source-line">
          <span>{sourceLabel(result.source_system)}</span>
          <span>{result.external_id}</span>
          {result.priority && <b>{result.priority}</b>}
          {result.status && <span>{result.status}</span>}
        </div>
        <button
          className="result-title"
          onClick={(event) => {
            event.stopPropagation();
            onOpen();
          }}
        >
          {result.title}
        </button>
        <p>{result.snippet}</p>
        <div className="result-meta">
          {result.project_key && <span>Project: {result.project_key}</span>}
          {result.component && <span>{result.component}</span>}
          <span>Updated {formatDate(result.updated_at)}</span>
        </div>
      </div>
      <div className="score">
        <b>{rowScore.toFixed(2)}</b>
        <span>
          <i style={{ width: `${Math.min(100, Math.max(0, Math.round(rowScore * 100)))}%` }} />
        </span>
      </div>
    </article>
  );
}

function ResultsPage({
  page,
  query,
  setQuery,
  results,
  selected,
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
  const counts = sourceCounts(results);
  const signals = selected?.explanation?.signals;

  return (
    <section className="app-shell">
      <TopBar query={query} setQuery={setQuery} onSearch={onSearch} onNavigate={onNavigate} />
      <div className="workspace">
        <SideNav page={page} onNavigate={onNavigate} />
        <main className="results-main">
          <div className="query-head">
            <h2>{query}</h2>
            <div className="filter-row">
              <span>Project: Orion</span>
              <span>Time: Last 90 days</span>
              <span>Sources: All</span>
              <button>
                <SlidersHorizontal size={14} />
                More filters
              </button>
              <button>
                <Bookmark size={14} />
                Save search
              </button>
              <button className="share">
                <Share2 size={14} />
                Share
              </button>
              <button className="ink-compact">
                <Download size={14} />
                Export
              </button>
            </div>
          </div>

          <div className="results-grid">
            <div className="result-list">
              <ErrorBanner message={error} />
              <div className="result-summary">
                <b>{results.length} results</b>
                <span>Hybrid search</span>
                {runId && <span>run: {runId.slice(0, 8)}</span>}
                <span>{'fts + vector + trgm -> rrf'}</span>
              </div>
              {loading && <EmptyState title="Searching evidence" body="The API is querying local Postgres and writing retrieval diagnostics." />}
              {!loading && !error && results.length === 0 && (
                <EmptyState
                  title="No evidence returned"
                  body="Run the local Postgres bootstrap, ingest a source bundle, embed chunks, and search again."
                  action={<button className="ink-button" onClick={onSearch}>Search again</button>}
                />
              )}
              {results.map((result, index) => (
                <ResultRow
                  key={`${result.source_system}-${result.external_id}-${result.chunk_id || index}`}
                  result={result}
                  index={index}
                  selected={selected?.external_id === result.external_id && selected?.source_system === result.source_system}
                  onSelect={() => setSelected(result)}
                  onOpen={() => {
                    setSelected(result);
                    onNavigate('detail');
                  }}
                />
              ))}
            </div>

            <aside className="insight-panel">
              <h3>Why these results</h3>
              <p>
                The API stores every run in local Postgres, then returns ranked evidence from full-text, vector, trigram, filter, recency, and RRF signals.
              </p>
              <h4>Selected result signals</h4>
              {selected ? (
                [
                  ['Keyword match', signals?.full_text ?? selected.text_rank ?? 0],
                  ['Semantic similarity', signals?.semantic ?? selected.vector_score ?? 0],
                  ['Fuzzy match', signals?.fuzzy ?? selected.trigram_score ?? 0],
                  ['Metadata filters', signals?.metadata ?? selected.metadata_score ?? 0],
                  ['Recency', signals?.recency ?? selected.recency_score ?? 0],
                  ['RRF', signals?.rrf ?? selected.rrf_score ?? 0]
                ].map(([label, value]) => (
                  <div className="signal-meter" key={label}>
                    <span>{label}</span>
                    <b>{Number(value).toFixed(2)}</b>
                    <i>
                      <em style={{ width: `${Math.min(100, Math.max(0, Number(value) * 100))}%` }} />
                    </i>
                  </div>
                ))
              ) : (
                <p>Select a result to inspect ranking signals.</p>
              )}
              <h4>Sources in this run</h4>
              {counts.length ? counts.map((source) => (
                <div className="source-count" key={source.key}>
                  <Dot system={source.key} />
                  <span>{source.label.split(' ')[0]}</span>
                  <b>{source.count}</b>
                </div>
              )) : <p>No source distribution yet.</p>}
              <button className="wide-quiet" onClick={onAgent}>
                <Sparkles size={15} />
                Generate cited answer
              </button>
            </aside>
          </div>
        </main>
      </div>
    </section>
  );
}

function DetailPage({
  page,
  query,
  setQuery,
  selected,
  error,
  onSearch,
  onNavigate
}: {
  page: Page;
  query: string;
  setQuery: (value: string) => void;
  selected: Result | null;
  error?: string;
  onSearch: () => void;
  onNavigate: (page: Page) => void;
}) {
  return (
    <section className="app-shell">
      <TopBar query={query} setQuery={setQuery} onSearch={onSearch} onNavigate={onNavigate} />
      <div className="workspace">
        <SideNav page={page} onNavigate={onNavigate} />
        <main className="detail-main">
          <button className="back-button" onClick={() => onNavigate('results')}>
            Back to results
          </button>
          <ErrorBanner message={error} />
          {!selected ? (
            <EmptyState title="No source selected" body="Run a search and open a result to inspect source detail." />
          ) : (
            <div className="detail-layout">
              <article className="source-detail">
                <div className="detail-kicker">
                  <span className={cx('source-mark', selected.source_system)}>{sourceIcon(selected.source_system)}</span>
                  <span>{selected.external_id}</span>
                  {selected.priority && <b>{selected.priority}</b>}
                  {selected.status && <span>{selected.status}</span>}
                </div>
                <h2>{selected.title}</h2>
                <div className="detail-byline">
                  <span>{sourceLabel(selected.source_system)}</span>
                  <span>Updated {formatDate(selected.updated_at)}</span>
                  {selected.project_key && <span>Project: {selected.project_key}</span>}
                </div>
                <div className="tabs">
                  <button className="active">Overview</button>
                  <button>Citations</button>
                  <button>Linked objects</button>
                  <button>Diagnostics</button>
                </div>
                <section className="detail-section">
                  <h3>Retrieved passage</h3>
                  <p>{selected.snippet}</p>
                </section>
                <section className="detail-section two-col">
                  <div>
                    <h3>Metadata</h3>
                    <p>
                      {selected.component || 'No component'} {selected.account_name ? `- ${selected.account_name}` : ''}
                    </p>
                  </div>
                  <div>
                    <h3>Owner</h3>
                    <p>{selected.owner || 'Not set'}</p>
                  </div>
                </section>
                <div className="field-grid">
                  <div><span>Status</span><b>{selected.status || 'None'}</b></div>
                  <div><span>Priority</span><b>{selected.priority || 'None'}</b></div>
                  <div><span>Source type</span><b>{selected.source_type || 'Object'}</b></div>
                  <div><span>Score</span><b>{score(selected).toFixed(2)}</b></div>
                </div>
              </article>

              <aside className="detail-rail">
                <section>
                  <h3>Why this matched</h3>
                  <div className="check-list">
                    {(selected.explanation?.why || ['Matched through the hybrid search function in local Postgres.']).map((why) => (
                      <p key={why}><Zap size={14} /> {why}</p>
                    ))}
                    {selected.project_key && <p><Link2 size={14} /> Project match: {selected.project_key}</p>}
                    {selected.updated_at && <p><Clock3 size={14} /> Updated {formatDate(selected.updated_at)}</p>}
                  </div>
                </section>
                <section className="score-card">
                  <span>Score</span>
                  <b>{score(selected).toFixed(2)}</b>
                  <button>Stored in retrieval_candidates</button>
                </section>
                <section>
                  <h3>Source link</h3>
                  <div className="link-list">
                    {selected.url ? (
                      <a href={selected.url} target="_blank" rel="noreferrer">
                        <ExternalLink size={13} />
                        Open source object
                      </a>
                    ) : (
                      <p>No source URL was provided during ingestion.</p>
                    )}
                  </div>
                </section>
              </aside>
            </div>
          )}
        </main>
      </div>
    </section>
  );
}

function TrailPage({
  page,
  query,
  setQuery,
  results,
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
  const nodes = results.slice(0, graphPositions.length).map((result, index) => ({ ...result, ...graphPositions[index], seq: index + 1 }));
  const path = useMemo(() => {
    if (nodes.length < 2) return '';
    const coords = nodes.map((node) => ({ x: 9 + node.col * 12.3, y: 9 + node.lane * 15.4 }));
    return coords.reduce((d, point, index) => {
      if (index === 0) return `M ${point.x} ${point.y}`;
      const prev = coords[index - 1];
      const mid = (prev.x + point.x) / 2;
      return `${d} C ${mid} ${prev.y}, ${mid} ${point.y}, ${point.x} ${point.y}`;
    }, '');
  }, [nodes]);

  return (
    <section className="app-shell">
      <TopBar query={query} setQuery={setQuery} onSearch={onSearch} onNavigate={onNavigate} />
      <div className="workspace">
        <SideNav page={page} onNavigate={onNavigate} />
        <main className="trail-main">
          <div className="trail-toolbar">
            <div>
              <h2>Source trail</h2>
              <p>Connected evidence from the current retrieval run</p>
            </div>
            <div className="legend">
              {sourceCounts(results).map((source) => (
                <span key={source.key}>
                  <Dot system={source.key} />
                  {source.label.split(' ')[0]}
                </span>
              ))}
            </div>
            <button className="quiet-button" onClick={onSearch}>
              <Search size={15} />
              Refresh
            </button>
          </div>
          <ErrorBanner message={error} />
          {!nodes.length ? (
            <EmptyState title="No trail available" body="Run a search first. The graph is built from live retrieved evidence." />
          ) : (
            <>
              <div className="graph-wrap">
                <svg className="thread-svg" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
                  <path d={path} />
                </svg>
                {nodes.map((node) => (
                  <article
                    key={`${node.source_system}-${node.external_id}-${node.seq}`}
                    className={cx('graph-node', `node-${node.seq}`)}
                    style={{ gridColumn: `${node.col} / span 2`, gridRow: `${node.lane} / span 1` }}
                  >
                    <span className="node-source">
                      <Dot system={node.source_system} />
                      {node.external_id}
                    </span>
                    <b>{node.title}</b>
                    <small>{sourceLabel(node.source_system)} - {formatDate(node.updated_at)}</small>
                  </article>
                ))}
                <div className="graph-center">
                  <Logo compact />
                </div>
              </div>
              <div className="trail-key">
                <span><i className="solid-line" /> Current run order</span>
                <span><i className="dashed-line" /> Link traversal ready</span>
                <span><i className="pale-line" /> Source citations</span>
              </div>
            </>
          )}
        </main>
      </div>
    </section>
  );
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
  onNavigate
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
}) {
  const citations = agentPayload.citations || [];
  const results = (agentPayload.results || []).map(normalizeResult);

  return (
    <section className="app-shell">
      <TopBar query={query} setQuery={setQuery} onSearch={onSearch} onNavigate={onNavigate} />
      <div className="workspace">
        <SideNav page={page} onNavigate={onNavigate} />
        <main className="agent-main">
          <section className="answer-body">
            <p className="answer-kicker"><Sparkles size={15} /> Answer</p>
            <ErrorBanner message={error} />
            {loading && <EmptyState title="Assembling cited answer" body="The agent endpoint is searching evidence and collecting citations." />}
            {!loading && !agentPayload.answer ? (
              <EmptyState
                title="No agent answer yet"
                body="Call the agent endpoint after local Postgres has been bootstrapped and evidence has been ingested."
                action={<button className="ink-button" onClick={onAgent}>Ask agent</button>}
              />
            ) : (
              <>
                <h2>{agentPayload.answer ? 'Cited operational answer' : 'Answer unavailable'}</h2>
                <p className="answer-copy">{agentPayload.answer}</p>
                <h3>Plan</h3>
                <ul className="key-points">
                  {(agentPayload.plan || []).map((step) => <li key={step}>{step}</li>)}
                </ul>
                <h3>Citations</h3>
                <div className="citation-row">
                  {citations.map((citation) => (
                    <button key={`${citation.source_system}-${citation.external_id}`}>
                      <Dot system={citation.source_system} />
                      {citation.external_id}
                    </button>
                  ))}
                </div>
              </>
            )}
          </section>

          <aside className="answer-rail">
            <section>
              <h3>Retrieval summary</h3>
              <div className="summary-row"><span>Run ID</span><b>{agentPayload.run_id?.slice(0, 8) || '-'}</b></div>
              <div className="summary-row"><span>Results returned</span><b>{results.length}</b></div>
              <div className="summary-row"><span>Citations</span><b>{citations.length}</b></div>
              <div className="summary-row"><span>Answer state</span><b>{agentPayload.answer ? 'Ready' : 'Pending'}</b></div>
              <button className="wide-quiet" onClick={onAgent}>
                <Table2 size={15} />
                Regenerate
              </button>
            </section>
            <section>
              <h3>Next steps you can take</h3>
              {['Open retrieval diagnostics', 'Inspect source trail', 'Review source detail', 'Share this answer'].map((item) => (
                <button className="next-step" key={item}>
                  <ExternalLink size={13} />
                  {item}
                </button>
              ))}
            </section>
          </aside>

          <section className="diagnostics">
            <h3>Retrieval diagnostics</h3>
            {results.length === 0 ? (
              <EmptyState title="No diagnostics returned" body="The agent response did not include ranked evidence rows." />
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Result</th>
                    <th>Source</th>
                    <th>FTS</th>
                    <th>Vector</th>
                    <th>Meta</th>
                    <th>Recency</th>
                    <th>RRF</th>
                    <th>Final</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((result) => (
                    <tr key={`${result.source_system}-${result.external_id}`}>
                      <td>{result.external_id}</td>
                      <td>{sourceLabel(result.source_system)}</td>
                      <td>{Number(result.text_rank || result.explanation?.signals?.full_text || 0).toFixed(2)}</td>
                      <td>{Number(result.vector_score || result.explanation?.signals?.semantic || 0).toFixed(2)}</td>
                      <td>{Number(result.metadata_score || result.explanation?.signals?.metadata || 0).toFixed(2)}</td>
                      <td>{Number(result.recency_score || result.explanation?.signals?.recency || 0).toFixed(2)}</td>
                      <td>{Number(result.rrf_score || result.explanation?.signals?.rrf || 0).toFixed(2)}</td>
                      <td className="final-cell">{score(result).toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <form className="followup" onSubmit={(event) => event.preventDefault()}>
            <input placeholder="Ask a follow-up..." />
            <button>
              <Send size={16} />
            </button>
          </form>
          <p className="fine-print">{APP_NAME} can make mistakes. Verify important information.</p>
        </main>
      </div>
    </section>
  );
}

function App() {
  const [page, setPage] = useState<Page>('landing');
  const [query, setQuery] = useState(queryDefault);
  const [results, setResults] = useState<Result[]>([]);
  const [selected, setSelected] = useState<Result | null>(null);
  const [runId, setRunId] = useState<string>();
  const [agentPayload, setAgentPayload] = useState<AgentPayload>({});
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(false);

  async function runSearch() {
    setPage('results');
    setLoading(true);
    setError(undefined);
    try {
      const resp = await fetch(`${API_URL}/v1/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query,
          source_systems: ['slack', 'jira', 'confluence', 'salesforce', 'github'],
          project_key: query.toLowerCase().includes('orion') ? 'ORION' : undefined,
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
    setPage('agent');
    setLoading(true);
    setError(undefined);
    try {
      const resp = await fetch(`${API_URL}/v1/agent/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: query, limit: 8 })
      });
      if (!resp.ok) throw new Error(`Agent answer failed with HTTP ${resp.status}`);
      const json = (await resp.json()) as AgentPayload;
      setAgentPayload(json);
      setResults((json.results || []).map(normalizeResult));
      setSelected(json.results?.[0] ? normalizeResult(json.results[0]) : selected);
      setRunId(json.run_id);
    } catch (err) {
      setAgentPayload({});
      setError(err instanceof Error ? err.message : 'Agent answer failed. Check the API and local Postgres setup.');
    } finally {
      setLoading(false);
    }
  }

  if (page === 'landing') {
    return <Landing query={query} setQuery={setQuery} onSearch={runSearch} onAgent={runAgent} error={error} />;
  }

  if (page === 'detail') {
    return <DetailPage page={page} query={query} setQuery={setQuery} selected={selected} error={error} onSearch={runSearch} onNavigate={setPage} />;
  }

  if (page === 'trail') {
    return <TrailPage page={page} query={query} setQuery={setQuery} results={results} error={error} onSearch={runSearch} onNavigate={setPage} />;
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
        onNavigate={setPage}
      />
    );
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
      onNavigate={setPage}
    />
  );
}

createRoot(document.getElementById('root')!).render(<App />);
