import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  ArrowLeft,
  Bell,
  Bookmark,
  Clock3,
  Database,
  Download,
  ExternalLink,
  HelpCircle,
  Home,
  LayoutDashboard,
  Link2,
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
  Zap
} from 'lucide-react';
import { FaGithub } from 'react-icons/fa6';
import confluenceLogoUrl from './assets/confluence-2017.svg';
import jiraLogoUrl from './assets/jira-streamline.svg';
import salesforceLogoUrl from './assets/salesforce-logo.jpeg';
import slackIconUrl from './assets/slack-icon-2019.svg';
import serviceNowLogoUrl from './assets/servicenow-logo.png';
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
const queryDefault =
  'Why is Project Orion delayed, what did the team decide in Slack, and what customer commitments are impacted?';

const searchSuggestions = [
  {
    label: 'Orion delay root cause',
    query: queryDefault,
    sources: ['slack', 'jira', 'salesforce']
  },
  {
    label: 'Slack decision trail',
    query: 'What did the Project Orion team decide in Slack and which tickets changed after that decision?',
    sources: ['slack', 'jira']
  },
  {
    label: 'Customer impact',
    query: 'Which Salesforce customer commitments are impacted by the Project Orion delay?',
    sources: ['salesforce', 'slack']
  },
  {
    label: 'Incident linkage',
    query: 'Show incidents and Jira blockers connected to Project Orion replication lag.',
    sources: ['servicenow', 'jira']
  },
  {
    label: 'Hybrid rank diagnostics',
    query: 'Explain why the top Project Orion evidence ranked highest across full text, vector, and trigram signals.',
    sources: ['jira', 'confluence', 'github']
  }
];

const coreSources = [
  { key: 'slack', label: 'Slack' },
  { key: 'jira', label: 'Jira' },
  { key: 'confluence', label: 'Confluence' },
  { key: 'salesforce', label: 'Salesforce' },
  { key: 'servicenow', label: 'ServiceNow' },
  { key: 'github', label: 'GitHub' }
];

const landingSources = [
  { key: 'slack', label: 'Slack' },
  { key: 'jira', label: 'Jira' },
  { key: 'confluence', label: 'Confluence' },
  { key: 'salesforce', label: 'Salesforce' },
  { key: 'servicenow', label: 'ServiceNow' },
  { key: 'github', label: 'GitHub' }
];

const heroSourceNodes = [
  { key: 'confluence', title: 'Readiness runbook', meta: 'Release gates', role: 'Policy', score: '0.82', left: '50%', top: '12%', delay: '0s' },
  { key: 'slack', title: 'Slack decision', meta: '#proj-orion', role: 'Decision', score: '0.93', left: '22%', top: '36%', delay: '0.15s' },
  { key: 'servicenow', title: 'INC-0012345', meta: 'Replication lag', role: 'Incident', score: '0.78', left: '78%', top: '36%', delay: '0.3s' },
  { key: 'jira', title: 'ORION-1473', meta: 'P1 blocker', role: 'Blocker', score: '0.89', left: '22%', top: '62%', delay: '0.45s' },
  { key: 'salesforce', title: 'CASE-0012345', meta: 'Acme commitment', role: 'Impact', score: '0.87', left: '78%', top: '62%', delay: '0.6s' },
  { key: 'github', title: 'PR-1287', meta: 'Merged fix', role: 'Change', score: '0.74', left: '50%', top: '86%', delay: '0.75s' }
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
  if (system === 'servicenow') return { width: Math.round(size * 2.7), height: Math.round(size * 0.52) };
  if (system === 'salesforce') return { width: Math.round(size * 1.75), height: Math.round(size * 1.05) };
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

function MiniBrand({ system }: { system: string }) {
  return <span className={cx('mini-brand', system)}>{sourceIcon(system, 21)}</span>;
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

function SkeletonRows({ count = 4 }: { count?: number }) {
  return (
    <>
      {Array.from({ length: count }, (_, index) => (
        <div className="skeleton-row" key={index} aria-hidden="true">
          <span />
          <span className="sk sk-mark" />
          <div>
            <span className="sk sk-line" style={{ display: 'block', width: '30%' }} />
            <span className="sk sk-line wide" style={{ display: 'block' }} />
            <span className="sk sk-line dim" style={{ display: 'block' }} />
          </div>
          <span />
        </div>
      ))}
    </>
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

function SearchComposer({
  query,
  setQuery,
  onSearch,
  autoType = false,
  className
}: {
  query: string;
  setQuery: (value: string) => void;
  onSearch: () => void;
  autoType?: boolean;
  className?: string;
}) {
  const userEditedRef = useRef(false);
  const [isTypingDefault, setIsTypingDefault] = useState(autoType && query.length === 0);
  const [suggestionsOpen, setSuggestionsOpen] = useState(false);
  const [activeSuggestion, setActiveSuggestion] = useState(-1);

  useEffect(() => {
    if (!autoType || query.length > 0) return;

    let index = 0;
    let timeoutId: number | undefined;

    function tick() {
      if (userEditedRef.current) return;
      index += 1;
      setQuery(queryDefault.slice(0, index));
      if (index >= queryDefault.length) {
        setIsTypingDefault(false);
        return;
      }
      timeoutId = window.setTimeout(tick, index < 14 ? 34 : 16);
    }

    timeoutId = window.setTimeout(tick, 420);
    return () => {
      if (timeoutId) window.clearTimeout(timeoutId);
    };
  }, [autoType, setQuery]);

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
      .slice(0, 4);
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
      return;
    }

    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setSuggestionsOpen(true);
      setActiveSuggestion((current) => (current <= 0 ? visibleSuggestions.length - 1 : current - 1));
      return;
    }

    if (event.key === 'Tab' && suggestionsOpen) {
      event.preventDefault();
      selectSuggestion(activeSuggestion >= 0 ? activeSuggestion : 0);
      return;
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
        onSearch();
      }}
    >
      <Search size={18} />
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
        />
        {isTypingDefault && (
          <span className="typewriter-overlay" aria-hidden="true">
            <span>{query}</span>
            <i />
          </span>
        )}
      </div>
      <button className="ink-button" type="submit">Search</button>
      {suggestionsOpen && (
        <div className="search-suggestions" role="listbox">
          <span>Suggested queries</span>
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
                {suggestion.sources.map((source) => (
                  <MiniBrand key={source} system={source} />
                ))}
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
      </header>

      <div className="hero-panel">
        <div className="hero-copy">
          <p className="eyebrow">Connected evidence</p>
          <h1>
            Find the <em>why</em>
            <br />
            behind the work.
          </h1>
          <p className="hero-sub">
            Connect scattered tickets, docs, cases, incidents, and code to surface the full context and deliver answers you can trust.
          </p>
          <div className="system-strip">
            <span>Works with your systems</span>
            {landingSources.map((source) => (
              <span key={source.key} className="system-mini">
                <MiniBrand system={source.key} />
                {source.label}
              </span>
            ))}
            <span className="system-mini">and more</span>
          </div>
        </div>

        <div className="hero-stage" aria-hidden="true">
        <div className="hero-visual">
          <svg className="hero-thread-map" viewBox="0 0 100 100" preserveAspectRatio="none">
            <defs>
              <linearGradient id="threadGradient" x1="18" y1="68" x2="88" y2="24" gradientUnits="userSpaceOnUse">
                <stop offset="0" stopColor="#c4493b" stopOpacity="0.1" />
                <stop offset="0.46" stopColor="#c4493b" stopOpacity="0.9" />
                <stop offset="1" stopColor="#17181c" stopOpacity="0.38" />
              </linearGradient>
              <filter id="threadGlow" x="-20%" y="-20%" width="140%" height="140%">
                <feGaussianBlur stdDeviation="1.2" result="blur" />
                <feMerge>
                  <feMergeNode in="blur" />
                  <feMergeNode in="SourceGraphic" />
                </feMerge>
              </filter>
              <marker id="threadArrow" viewBox="0 0 8 8" refX="6" refY="4" markerWidth="3.2" markerHeight="3.2" orient="auto">
                <path d="M0 1 L7 4 L0 7 Z" fill="#c4493b" />
              </marker>
            </defs>
            <path className="thread-orbit orbit-outer" d="M11 60 C 24 17, 74 8, 93 37 C 88 74, 45 88, 11 60 Z" />
            <path className="thread-orbit orbit-inner" d="M25 55 C 34 31, 69 26, 81 42 C 73 64, 43 72, 25 55 Z" />
            <path className="thread-rail" d="M50 12 C 50 28, 50 40, 50 50 C 50 62, 50 74, 50 86" />
            <path className="thread-rail rail-secondary" d="M22 36 C 36 39, 44 45, 50 50 C 56 45, 64 39, 78 36" />
            <path className="thread-rail rail-tertiary" d="M22 62 C 36 60, 44 55, 50 50 C 56 55, 64 60, 78 62" />
            <path className="thread-link link-confluence" d="M50 12 C 50 28, 50 40, 50 50" />
            <path className="thread-link link-slack" d="M22 36 C 36 39, 44 45, 50 50" />
            <path className="thread-link link-servicenow" d="M78 36 C 64 39, 56 45, 50 50" />
            <path className="thread-link link-jira" d="M22 62 C 36 60, 44 55, 50 50" />
            <path className="thread-link link-salesforce" d="M78 62 C 64 60, 56 55, 50 50" />
            <path className="thread-link link-github" d="M50 86 C 50 74, 50 62, 50 50" />
            <circle className="thread-point point-core" cx="50" cy="50" r="1.2" />
            <circle className="thread-point" cx="50" cy="12" r="0.9" />
            <circle className="thread-point" cx="22" cy="36" r="0.9" />
            <circle className="thread-point" cx="78" cy="36" r="0.9" />
            <circle className="thread-point" cx="22" cy="62" r="0.9" />
            <circle className="thread-point" cx="78" cy="62" r="0.9" />
            <circle className="thread-point" cx="50" cy="86" r="0.9" />
          </svg>
          <div className="thread-core">
            <Logo compact />
            <b>Answer</b>
            <span className="core-metric">
              <small>hybrid fusion</small>
              <span className="core-score">0.92</span>
            </span>
          </div>
          {heroSourceNodes.map((source) => (
            <article
              key={source.key}
              className={cx('source-node', source.key)}
              style={{ left: source.left, top: source.top, animationDelay: source.delay }}
            >
              <span className={cx('source-badge', source.key)}>{sourceIcon(source.key, 34)}</span>
              <span className="source-node-copy">
                <span className="node-role">{source.role}</span>
                <b>{source.title}</b>
                <small>{source.meta}</small>
              </span>
              <span className="node-score">{source.score}</span>
            </article>
          ))}
        </div>
        </div>
      </div>

      <div className="landing-composer-shell">
        <SearchComposer query={query} setQuery={setQuery} onSearch={onSearch} autoType className="landing-composer" />
      </div>

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
    <article
      className={cx('result-row', selected && 'selected')}
      style={{ '--row-index': index } as React.CSSProperties}
      onClick={onSelect}
    >
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

function CitationRef({ result, n, onOpen }: { result?: Result; n: number; onOpen: () => void }) {
  if (!result) return null;
  return (
    <button className={cx('inline-citation', result.source_system)} onClick={onOpen}>
      <span>{n}</span>
      {sourceLabel(result.source_system)}
    </button>
  );
}

function SourceAttributionCard({
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
  return (
    <article className={cx('source-card', selected && 'selected')} onClick={onSelect}>
      <div className="source-card-top">
        <span className={cx('source-mark', result.source_system)}>{sourceIcon(result.source_system)}</span>
        <div>
          <span>{sourceLabel(result.source_system)}</span>
          <b>{result.external_id}</b>
        </div>
        <strong>{index + 1}</strong>
      </div>
      <button
        className="source-card-title"
        onClick={(event) => {
          event.stopPropagation();
          onOpen();
        }}
      >
        {result.title}
      </button>
      <p>{result.snippet || 'No snippet returned for this source.'}</p>
      <div className="source-card-meta">
        <span>{score(result).toFixed(2)}</span>
        {result.priority && <span>{result.priority}</span>}
        {result.status && <span>{result.status}</span>}
        {result.url && (
          <a href={result.url} onClick={(event) => event.stopPropagation()} target="_blank" rel="noreferrer">
            Open <ExternalLink size={11} />
          </a>
        )}
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
  const topResults = results.slice(0, 6);
  const firstBySource = (system: string) => results.find((result) => result.source_system === system);
  const slack = firstBySource('slack') || topResults[0];
  const jira = firstBySource('jira') || topResults[1];
  const salesforce = firstBySource('salesforce') || topResults[2];
  const servicenow = firstBySource('servicenow') || topResults[3];
  const confluence = firstBySource('confluence') || topResults[4];
  const github = firstBySource('github') || topResults[5];
  const selectedResult = selected || results[0] || null;
  const signals = selectedResult?.explanation?.signals;

  function openResult(result?: Result) {
    if (!result) return;
    setSelected(result);
    onNavigate('detail');
  }

  function citationNumber(result?: Result) {
    if (!result) return 0;
    const index = topResults.findIndex(
      (item) => item.source_system === result.source_system && item.external_id === result.external_id
    );
    return index >= 0 ? index + 1 : 0;
  }

  function scrollToSection(id: string) {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  return (
    <section className="answer-shell">
      <header className="answer-nav">
        <div className="answer-nav-left">
          <button className="logo-button" onClick={() => onNavigate('landing')} aria-label="Go home">
            <Logo />
          </button>
          <button className="answer-back-button" onClick={() => onNavigate('landing')}>
            <ArrowLeft size={14} />
            Edit search
          </button>
        </div>
        <nav className="answer-tabs" aria-label="Answer workspace">
          <button className="active" onClick={() => scrollToSection('answer-response')}>
            <Sparkles size={14} />
            Answer
          </button>
          <button onClick={() => scrollToSection('answer-sources')}>
            <Bookmark size={14} />
            Sources
          </button>
          <button onClick={() => onNavigate('trail')}>
            <Network size={14} />
            Evidence trail
          </button>
          <button onClick={() => scrollToSection('answer-diagnostics')}>
            <Table2 size={14} />
            Diagnostics
          </button>
        </nav>
        <nav className="answer-actions" aria-label="Answer actions">
          <button onClick={onAgent}>
            <Zap size={14} />
            Agent answer
          </button>
        </nav>
      </header>

      <main className="answer-main">
        <ErrorBanner message={error} />
        <section className="answer-question">
          <span>Question</span>
          <h1>{query}</h1>
          <div>
            <b>{results.length || 0} sources</b>
            {runId && <b>run {runId.slice(0, 8)}</b>}
            <b>hybrid retrieval</b>
          </div>
        </section>

        {loading && (
          <section className="ai-response-card">
            <EmptyState
              loading
              title="Searching evidence"
              body="Threadline is retrieving source objects, ranking evidence, and preparing cited context."
            />
            <SkeletonRows count={3} />
          </section>
        )}

        {!loading && !error && results.length === 0 && (
          <EmptyState
            title="No evidence returned"
            body="Run the local Postgres bootstrap, ingest a source bundle, embed chunks, and search again."
            action={<button className="ink-button" onClick={onSearch}>Search again</button>}
          />
        )}

        {!loading && results.length > 0 && (
          <>
            <section className="ai-response-card" id="answer-response">
              <p className="answer-label">
                <Sparkles size={15} />
                Retrieval-grounded answer
              </p>
              <h2>Project Orion appears delayed by a linked blocker, incident signal, and customer commitment chain.</h2>
              <p>
                The strongest evidence ties the delay to the active Jira blocker
                {' '}<CitationRef result={jira} n={citationNumber(jira)} onOpen={() => openResult(jira)} />
                {' '}and a related ServiceNow incident
                {' '}<CitationRef result={servicenow} n={citationNumber(servicenow)} onOpen={() => openResult(servicenow)} />.
                The decision context is captured in Slack
                {' '}<CitationRef result={slack} n={citationNumber(slack)} onOpen={() => openResult(slack)} />,
                while customer impact is visible in Salesforce
                {' '}<CitationRef result={salesforce} n={citationNumber(salesforce)} onOpen={() => openResult(salesforce)} />.
              </p>
              <p>
                Release-readiness guidance from Confluence
                {' '}<CitationRef result={confluence} n={citationNumber(confluence)} onOpen={() => openResult(confluence)} />
                {' '}and implementation evidence from GitHub
                {' '}<CitationRef result={github} n={citationNumber(github)} onOpen={() => openResult(github)} />
                {' '}complete the thread, so the answer can cite the operational path instead of summarizing isolated search hits.
              </p>
              <div className="answer-attribution-strip">
                {topResults.slice(0, 5).map((result, index) => (
                  <button key={`${result.source_system}-${result.external_id}-${index}`} onClick={() => openResult(result)}>
                    <span className={cx('source-mark', result.source_system)}>{sourceIcon(result.source_system, 18)}</span>
                    <span>{index + 1}</span>
                    {result.external_id}
                  </button>
                ))}
              </div>
            </section>

            <section className="answer-source-section" id="answer-sources">
              <div className="answer-section-head">
                <div>
                  <span>Sources</span>
                  <h3>Retrieved evidence</h3>
                </div>
                <button className="quiet-button" onClick={() => onNavigate('trail')}>
                  <Network size={14} />
                  View trail
                </button>
              </div>
              <div className="source-attribution-grid">
                {topResults.map((result, index) => (
                  <SourceAttributionCard
                    key={`${result.source_system}-${result.external_id}-${result.chunk_id || index}`}
                    result={result}
                    index={index}
                    selected={selectedResult?.external_id === result.external_id && selectedResult?.source_system === result.source_system}
                    onSelect={() => setSelected(result)}
                    onOpen={() => openResult(result)}
                  />
                ))}
              </div>
            </section>

            <section className="answer-diagnostics-panel" id="answer-diagnostics">
              <div>
                <span>Why this ranked</span>
                <h3>{selectedResult ? selectedResult.title : 'Hybrid retrieval signals'}</h3>
                <p>
                  Threadline combines full text, vector similarity, trigram matching, metadata filters, recency, and reciprocal rank fusion.
                </p>
              </div>
              <div className="answer-signal-grid">
                {selectedResult ? [
                  ['Keyword', signals?.full_text ?? selectedResult.text_rank ?? 0],
                  ['Semantic', signals?.semantic ?? selectedResult.vector_score ?? 0],
                  ['Fuzzy', signals?.fuzzy ?? selectedResult.trigram_score ?? 0],
                  ['Metadata', signals?.metadata ?? selectedResult.metadata_score ?? 0],
                  ['Recency', signals?.recency ?? selectedResult.recency_score ?? 0],
                  ['RRF', signals?.rrf ?? selectedResult.rrf_score ?? 0]
                ].map(([label, value]) => (
                  <div className="signal-meter" key={label}>
                    <span>{label}</span>
                    <b>{Number(value).toFixed(2)}</b>
                    <i>
                      <em style={{ width: `${Math.min(100, Math.max(0, Number(value) * 100))}%` }} />
                    </i>
                  </div>
                )) : <p>Select a source to inspect ranking signals.</p>}
              </div>
            </section>
          </>
        )}
      </main>

      <div className="answer-composer-shell">
        <SearchComposer query={query} setQuery={setQuery} onSearch={onSearch} className="answer-composer" />
      </div>
    </section>
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
  const chunks = objectDetail?.chunks || [];
  const citations = objectDetail?.citations || [];
  const links = objectDetail?.links || [];

  return (
    <section className="app-shell">
      <TopBar query={query} setQuery={setQuery} onSearch={onSearch} onNavigate={onNavigate} />
      <div className="workspace">
        <SideNav page={page} onNavigate={onNavigate} />
        <main className="detail-main">
          <button className="back-button" onClick={() => onNavigate('results')}>
            <ArrowLeft size={13} />
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
                  <button>Citations {citations.length ? citations.length : ''}</button>
                  <button>Linked objects {links.length ? links.length : ''}</button>
                  <button>Diagnostics</button>
                </div>
                <section className="detail-section">
                  <h3>Retrieved passage</h3>
                  <p>{selected.snippet}</p>
                </section>
                {detailLoading && <p className="detail-loading">Loading source detail...</p>}
                {citations.length > 0 && (
                  <section className="detail-section">
                    <h3>Citations</h3>
                    <div className="citation-list">
                      {citations.slice(0, 3).map((citation) => (
                        <article key={citation.citation_id}>
                          <span>{citation.locator || citation.source_label}</span>
                          <p>{citation.quote_text || 'Citation quote unavailable.'}</p>
                        </article>
                      ))}
                    </div>
                  </section>
                )}
                {chunks.length > 1 && (
                  <section className="detail-section">
                    <h3>Object chunks</h3>
                    <div className="chunk-list">
                      {chunks.slice(0, 3).map((chunk) => (
                        <article key={chunk.chunk_id}>
                          <b>{chunk.section_title || `Chunk ${chunk.chunk_index}`}</b>
                          <p>{chunk.chunk_summary || chunk.chunk_text.slice(0, 260)}</p>
                        </article>
                      ))}
                    </div>
                  </section>
                )}
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
                <section>
                  <h3>Linked evidence</h3>
                  <div className="linked-evidence">
                    {links.length ? links.slice(0, 4).map((link) => (
                      <article key={link.link_id || `${link.source_system}-${link.external_id}`}>
                        <span>
                          <MiniBrand system={link.source_system} />
                          {sourceLabel(link.source_system)}
                        </span>
                        <b>{link.title}</b>
                        <small>{link.link_type || 'related'} · {Number(link.confidence || 0).toFixed(2)}</small>
                      </article>
                    )) : <p>No linked source objects returned for this evidence item.</p>}
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
                  <MiniBrand system={source.key} />
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
                      <MiniBrand system={node.source_system} />
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
            {loading && (
              <EmptyState
                loading
                title="Assembling cited answer"
                body="The agent endpoint is searching evidence and collecting citations."
              />
            )}
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
                      <MiniBrand system={citation.source_system} />
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
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Result[]>([]);
  const [selected, setSelected] = useState<Result | null>(null);
  const [runId, setRunId] = useState<string>();
  const [agentPayload, setAgentPayload] = useState<AgentPayload>({});
  const [objectDetail, setObjectDetail] = useState<ObjectDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(false);

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

  async function runSearch() {
    const searchQuery = query.trim() || queryDefault;
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
        onNavigate={setPage}
      />
    );
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
