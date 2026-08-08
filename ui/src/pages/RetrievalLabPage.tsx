import { ArrowDown, CircleCheck, Play, SlidersHorizontal } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { CodeBlock } from "../components/CodeBlock";
import { ErrorState, LoadingState } from "../components/States";
import type { ProductSummary, RetrievalExample, SearchResponse } from "../types";

type Stage = "lexical" | "trigram" | "semantic" | "fusion" | "rerank";

const stages: Array<{ id: Stage; label: string; detail: string }> = [
  { id: "lexical", label: "Full-text", detail: "Exact product language and identifiers" },
  { id: "trigram", label: "pg_trgm", detail: "Misspellings and nearby strings" },
  { id: "semantic", label: "Vector", detail: "Intent and paraphrase" },
  { id: "fusion", label: "RRF", detail: "Ordinal agreement across candidate arms" },
  { id: "rerank", label: "Rerank", detail: "Nuanced ordering of the fused pool" },
];

const sql: Record<Stage, string> = {
  lexical: `SELECT product_id, lexical_rank, lexical_score
FROM catalog.search_lexical(
  :query,
  :filters::jsonb,
  100
)
ORDER BY lexical_rank;`,
  trigram: `SELECT product_id, trigram_rank, trigram_score
FROM catalog.search_trigram(
  :query,
  :filters::jsonb,
  75,
  0.24
)
ORDER BY trigram_rank;`,
  semantic: `SET LOCAL hnsw.ef_search = 128;

SELECT product_id, semantic_rank, semantic_score
FROM catalog.search_semantic(
  :query_embedding::vector(1024),
  :filters::jsonb,
  100
)
ORDER BY semantic_rank;`,
  fusion: `SELECT *
FROM catalog.search_hybrid_rrf(
  :query,
  :query_embedding::vector(1024),
  :filters::jsonb,
  60, 100, 75, 100, 50,
  0.30, 0.10, 0.45
);`,
  rerank: `-- PostgreSQL RRF remains the candidate source.
-- Cohere Rerank 3.5 receives only the bounded top 50.
-- Persist rerank_score separately from rrf_score.
SELECT product_id, rrf_score, pre_rerank_rank,
       rerank_score, final_rank
FROM catalog.retrieval_candidate
WHERE run_id = :run_id
ORDER BY final_rank;`,
};

function stageRank(product: ProductSummary, stage: Stage): number {
  const signals = product.signals;
  if (!signals) return Number.MAX_SAFE_INTEGER;
  if (stage === "lexical") return signals.lexical.rank ?? Number.MAX_SAFE_INTEGER;
  if (stage === "trigram") return signals.trigram.rank ?? Number.MAX_SAFE_INTEGER;
  if (stage === "semantic") return signals.semantic.rank ?? Number.MAX_SAFE_INTEGER;
  if (stage === "fusion") return signals.pre_rerank_rank;
  return signals.final_rank;
}

function stageScore(product: ProductSummary, stage: Stage): string {
  const signals = product.signals;
  if (!signals) return "-";
  const score =
    stage === "lexical" ? signals.lexical.raw_score :
    stage === "trigram" ? signals.trigram.raw_score :
    stage === "semantic" ? signals.semantic.raw_score :
    stage === "fusion" ? signals.rrf_score :
    signals.rerank_score;
  return score == null ? "-" : score.toFixed(5);
}

export function RetrievalLabPage() {
  const [examples, setExamples] = useState<RetrievalExample[]>([]);
  const [selected, setSelected] = useState(0);
  const [stage, setStage] = useState<Stage>("lexical");
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.examples().then((rows) => {
      const unique = rows.filter((row, index, all) =>
        all.findIndex((candidate) => candidate.query === row.query) === index,
      );
      setExamples(unique);
    }).catch(() => setExamples([]));
  }, []);

  const example = examples[selected];
  const rows = useMemo(
    () => [...(response?.results ?? [])].sort((a, b) => stageRank(a, stage) - stageRank(b, stage)),
    [response, stage],
  );

  async function run() {
    if (!example) return;
    setLoading(true);
    setError("");
    try {
      setResponse(await api.search(example.query, { domain: example.domain }, { limit: 12, rerank: true }));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Retrieval failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page lab-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">Build and inspect</p>
          <h1>Retrieval Lab</h1>
          <p>Follow one candidate set from exact terms through fuzzy recovery, semantic intent, fusion, and reranking.</p>
        </div>
        <button className="primary-button" type="button" disabled={!example || loading} onClick={() => void run()}>
          <Play size={17} fill="currentColor" /> Run pipeline
        </button>
      </header>

      <section className="lab-query-bar">
        <label>
          <span>Workshop query</span>
          <select value={selected} onChange={(event) => { setSelected(Number(event.target.value)); setResponse(null); }}>
            {examples.map((item, index) => <option value={index} key={item.query_id}>{item.query}</option>)}
          </select>
        </label>
        <div className="technique-list">
          {example?.expected_techniques.map((item) => <span key={item}>{item}</span>)}
        </div>
      </section>

      <nav className="stage-nav" aria-label="Retrieval stage">
        {stages.map((item, index) => (
          <div key={item.id} className="stage-nav-item">
            <button type="button" className={stage === item.id ? "active" : ""} onClick={() => setStage(item.id)}>
              <span>{index + 1}</span>
              <strong>{item.label}</strong>
              <small>{item.detail}</small>
            </button>
            {index < stages.length - 1 ? <ArrowDown size={16} /> : null}
          </div>
        ))}
      </nav>

      {loading ? <LoadingState label="Embedding, retrieving, fusing, and reranking" /> : null}
      {error ? <ErrorState message={error} onRetry={() => void run()} /> : null}

      <div className="lab-workspace">
        <section className="ranking-panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">{stages.find((item) => item.id === stage)?.label} view</p>
              <h2>Candidate order</h2>
            </div>
            {response ? <span className="run-id">Run {response.run_id.slice(0, 8)}</span> : null}
          </div>
          {!response && !loading ? (
            <div className="empty-ranking"><SlidersHorizontal size={24} /><p>Run the selected query to populate stage-level ranks and scores.</p></div>
          ) : null}
          {response ? (
            <div className="ranking-table-wrap">
              <table className="ranking-table">
                <thead><tr><th>Rank</th><th>Product</th><th>Stage score</th><th>Arm agreement</th><th>Eligible</th></tr></thead>
                <tbody>
                  {rows.map((product) => (
                    <tr key={product.product_id}>
                      <td><strong>{stageRank(product, stage) === Number.MAX_SAFE_INTEGER ? "-" : stageRank(product, stage)}</strong></td>
                      <td><strong>{product.title}</strong><small>{product.brand} / {product.model}</small></td>
                      <td className="mono">{stageScore(product, stage)}</td>
                      <td>
                        <span className="arm-dots" title="Lexical, trigram, semantic">
                          <i className={product.signals?.lexical.rank ? "on" : ""} />
                          <i className={product.signals?.trigram.rank ? "on" : ""} />
                          <i className={product.signals?.semantic.rank ? "on" : ""} />
                        </span>
                      </td>
                      <td><CircleCheck className="success-icon" size={17} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </section>
        <aside className="lab-code-panel">
          <p className="eyebrow">Code Editor checkpoint</p>
          <h2>Canonical SQL</h2>
          <p>{stages.find((item) => item.id === stage)?.detail}. Copy this shape into the workshop editor.</p>
          <CodeBlock code={sql[stage]} label={`${stage}.sql`} />
          {response?.diagnostics ? (
            <dl className="metric-list">
              <div><dt>Total latency</dt><dd>{response.diagnostics.total_latency_ms} ms</dd></div>
              <div><dt>Fused pool</dt><dd>{response.diagnostics.candidate_counts.fused_pool}</dd></div>
              <div><dt>Reranker</dt><dd>{response.diagnostics.rerank_status}</dd></div>
            </dl>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
