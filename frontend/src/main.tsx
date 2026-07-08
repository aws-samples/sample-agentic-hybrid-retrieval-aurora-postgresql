import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Search, Sparkles, GitPullRequest, FileText, MessageCircle, Cloud, Ticket, Database } from 'lucide-react';
import './styles.css';

type Result = {
  source_system: string;
  source_type?: string;
  external_id: string;
  title: string;
  snippet: string;
  status?: string;
  priority?: string;
  final_score?: number;
  url?: string;
};

const API_URL = import.meta.env.VITE_RETRIEVAL_API_URL || 'http://localhost:8000';
const APP_NAME = import.meta.env.VITE_APP_DISPLAY_NAME || 'Evidence Trail';

const mockResults: Result[] = [
  { source_system: 'slack', external_id: 'SLACK-000271', title: 'Release thread: hold cutover until soak results are clean', snippet: 'Priya: Replica lag is still above threshold; hold cutover until soak results are clean. Alex: Customer Engineering says Acme needs an update before EOD.', status: 'Decision', priority: 'P1', final_score: 0.94 },
  { source_system: 'jira', external_id: 'ORION-1473', title: 'Read replica lag causing delayed cutover', snippet: 'Elevated replica lag observed during peak load is delaying Blue/Green deployment validation and customer timeline.', status: 'Open', priority: 'P1', final_score: 0.92 },
  { source_system: 'confluence', external_id: 'PAGE-2112', title: 'Orion release readiness — architecture and risks', snippet: 'Known risks include database failover, rollback decision points, customer commitments, and runbook validation.', status: 'Published', final_score: 0.89 },
  { source_system: 'salesforce', external_id: 'CASE-0012345', title: 'Customer escalation: report generation delays', snippet: 'Acme Corp reports customer-visible report delays affecting monthly close commitments.', status: 'Escalated', priority: 'Sev1', final_score: 0.86 },
  { source_system: 'github', external_id: 'PR-1287', title: 'Improve connection pool failover behavior', snippet: 'Enhances pool rebalancing and reduces failover time under replica promotion. Linked to remediation.', status: 'Merged', final_score: 0.74 }
];

function icon(system: string) {
  if (system === 'slack') return <MessageCircle size={16}/>;
  if (system === 'jira') return <Ticket size={16}/>;
  if (system === 'confluence') return <FileText size={16}/>;
  if (system === 'salesforce') return <Cloud size={16}/>;
  if (system === 'github') return <GitPullRequest size={16}/>;
  return <Database size={16}/>;
}

function App() {
  const [page, setPage] = useState<'landing'|'results'|'trail'|'answer'|'sources'>('landing');
  const [query, setQuery] = useState('Why is Project Orion delayed, what did the team decide in Slack, and what customer commitments are impacted?');
  const [results, setResults] = useState<Result[]>(mockResults);
  const [answer, setAnswer] = useState('');
  const [selected, setSelected] = useState<Result>(mockResults[0]);

  async function runSearch() {
    setPage('results');
    try {
      const resp = await fetch(`${API_URL}/v1/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, source_systems: ['slack','jira','confluence','salesforce','github'], project_key: 'ORION', limit: 8 })
      });
      const json = await resp.json();
      const rows = json.results?.length ? json.results : mockResults;
      setResults(rows);
      setSelected(rows[0]);
    } catch {
      setResults(mockResults);
      setSelected(mockResults[0]);
    }
  }

  async function runAgent() {
    setPage('answer');
    try {
      const resp = await fetch(`${API_URL}/v1/agent/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: query, limit: 8 })
      });
      const json = await resp.json();
      setAnswer(json.answer || '');
    } catch {
      setAnswer('The strongest evidence points to a decision in Slack to hold the Orion cutover because replica lag remained above threshold. Jira confirms the technical blocker, Salesforce shows customer commitments at risk, and GitHub contains remediation evidence.');
    }
  }

  return <main>
    <header className="top">
      <div className="brand"><span className="mark">⌁</span>{APP_NAME}</div>
      <nav>
        <button onClick={() => setPage('landing')}>Search</button>
        <button onClick={() => setPage('results')}>Results</button>
        <button onClick={() => setPage('trail')}>Source trail</button>
        <button onClick={() => setPage('answer')}>Agent answer</button>
        <button onClick={() => setPage('sources')}>Sources</button>
      </nav>
      <kbd>⌘K</kbd>
    </header>

    {page === 'landing' && <section className="hero">
      <p className="eyebrow">Operational evidence search</p>
      <h1>Follow the evidence across conversations, tickets, docs, cases, and code.</h1>
      <p className="sub">Aurora PostgreSQL-backed hybrid retrieval for agentic workflows.</p>
      <div className="searchbox">
        <Search size={20}/>
        <input value={query} onChange={e => setQuery(e.target.value)} />
        <button onClick={runSearch}>Search</button>
        <button className="secondary" onClick={runAgent}><Sparkles size={16}/> Ask agent</button>
      </div>
      <div className="systems">
        {['Slack threads','Jira issues','Confluence pages','Salesforce cases','GitHub PRs'].map((x,i) => <div className="system" key={x}><strong>{['12.6K','8.3K','6.2K','4.1K','4.5K'][i]}</strong><span>{x}</span></div>)}
      </div>
      <p className="tech">Indexed in Aurora PostgreSQL · FTS + pgvector + pg_trgm · RRF + rerank</p>
    </section>}

    {page === 'results' && <section className="layout">
      <div className="results">
        <div className="filters"><span>All systems</span><span>Last 90 days</span><span>Project: ORION</span><span>hybrid: fts + vector + trgm → rrf → rerank</span></div>
        {results.map((r, i) => <article key={r.external_id} onClick={() => setSelected(r)} className={selected.external_id === r.external_id ? 'result selected' : 'result'}>
          <span className="rank">{String(i+1).padStart(2,'0')}</span>
          <span className={`source ${r.source_system}`}>{icon(r.source_system)}</span>
          <div><h3>{r.title}</h3><p>{r.snippet}</p><div className="tags"><span>{r.source_system}</span><span>{r.status}</span><span>{r.priority}</span></div></div>
          <b>{Number(r.final_score || 0.8).toFixed(2)}</b>
        </article>)}
      </div>
      <aside className="detail">
        <p className="eyebrow">Why this matched</p>
        <h2>{selected.title}</h2>
        <p>{selected.snippet}</p>
        <div className="signal"><span>Semantic similarity</span><b>0.93</b></div>
        <div className="signal"><span>Exact keyword match</span><b>ts_rank 0.42</b></div>
        <div className="signal"><span>Metadata match</span><b>ORION · P1</b></div>
        <div className="signal"><span>Recency boost</span><b>+0.08</b></div>
      </aside>
    </section>}

    {page === 'trail' && <section className="page"><h2>Source trail</h2><p>The evidence path follows citation links between Slack, Jira, Confluence, Salesforce, and GitHub.</p><div className="timeline">{mockResults.map((r,i)=><div className="node" key={r.external_id}><span>{i+1}</span><b>{r.source_system}</b><p>{r.title}</p></div>)}</div></section>}

    {page === 'answer' && <section className="answer"><div><p className="eyebrow">Agent answer · 18 sources · 3 retrieval passes</p><h2>The strongest evidence points to a held cutover after replica lag remained above threshold.</h2><p>{answer || 'Run Ask agent to generate an evidence-grounded answer.'}</p><ul><li>Slack contains the decision to hold cutover.</li><li>Jira confirms the technical blocker.</li><li>Salesforce identifies customer commitments at risk.</li><li>GitHub shows remediation evidence.</li></ul></div><aside><h3>How this answer was assembled</h3>{['decompose_question()','search_evidence()','traverse_links()','compare_sources()','synthesize_with_citations()'].map((x,i)=><div className="step" key={x}><span>{i+1}</span>{x}</div>)}</aside></section>}

    {page === 'sources' && <section className="page"><h2>Sources and ingestion</h2><p>Point source bundles at the ingestion API. The pipeline normalizes, chunks, embeds, cites, and indexes data in Aurora PostgreSQL.</p><div className="cards">{['Slack federated search','GitHub live connector','Jira export','Confluence export','Salesforce AppFlow','Files / S3'].map(x=><div className="card" key={x}><h3>{x}</h3><p>Optional stretch connector path. Synthetic data remains the default lab path.</p><button>Configure</button></div>)}</div></section>}
  </main>;
}

createRoot(document.getElementById('root')!).render(<App />);
