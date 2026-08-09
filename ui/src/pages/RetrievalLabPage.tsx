import { ArrowDown, CircleCheck, Play, SlidersHorizontal } from "lucide-react";
import { useMemo, useState } from "react";
import { api } from "../api";
import { CodeBlock } from "../components/CodeBlock";
import { ErrorState, LoadingState } from "../components/States";
import { mosaicLabMissions } from "../labMissions";
import { useSearchParams } from "../navigation";
import type { ProductSummary, SearchResponse } from "../types";

type Stage = "lexical" | "trigram" | "semantic" | "fusion" | "rerank";

const stages: Array<{ id: Stage; label: string; detail: string }> = [
  { id: "lexical", label: "Full-text", detail: "Exact product language and identifiers" },
  { id: "trigram", label: "pg_trgm", detail: "Misspellings and nearby strings" },
  { id: "semantic", label: "Vector", detail: "Intent and paraphrase" },
  { id: "fusion", label: "RRF", detail: "Ordinal agreement across candidate arms" },
  { id: "rerank", label: "Rerank", detail: "Nuanced ordering of the fused pool" },
];

const psqlByStage: Record<Stage, string> = {
  lexical: `mosaic=> SELECT product_id, fts_rank, fts_score
FROM mosaic_search.search_fts(
  :query, :filters::jsonb, 120
)
ORDER BY fts_rank;`,
  trigram: `mosaic=> SELECT product_id, trigram_rank, trigram_score
FROM mosaic_search.search_trigram(
  :query, :filters::jsonb, 80, 0.20
)
ORDER BY trigram_rank;`,
  semantic: `mosaic=> SELECT product_id, semantic_rank, semantic_score
FROM mosaic_search.search_vector(
  :query_embedding::vector(1024),
  :filters::jsonb, 150
)
ORDER BY semantic_rank;`,
  fusion: `mosaic=> SELECT product_id, rrf_score, pre_rerank_score
FROM mosaic_search.search_hybrid_rrf(
  :query, :query_embedding::vector(1024), :filters::jsonb
)
ORDER BY pre_rerank_score DESC;`,
  rerank: `mosaic=> SELECT product_id, pre_rerank_rank,
       rerank_score, final_rank
FROM mosaic.search_result_event
WHERE search_event_id = :search_event_id
ORDER BY final_rank;`,
};

function stageRank(product: ProductSummary, stage: Stage): number {
  const signals = product.signals;
  if (!signals) return Number.MAX_SAFE_INTEGER;
  if (stage === "lexical") return signals.fts.rank ?? Number.MAX_SAFE_INTEGER;
  if (stage === "trigram") return signals.trigram.rank ?? Number.MAX_SAFE_INTEGER;
  if (stage === "semantic") return signals.semantic.rank ?? Number.MAX_SAFE_INTEGER;
  if (stage === "fusion") return signals.pre_rerank_rank;
  return signals.final_rank;
}

function stageScore(product: ProductSummary, stage: Stage): string {
  const signals = product.signals;
  if (!signals) return "-";
  const score =
    stage === "lexical" ? signals.fts.raw_score :
    stage === "trigram" ? signals.trigram.raw_score :
    stage === "semantic" ? signals.semantic.raw_score :
    stage === "fusion" ? signals.rrf_score :
    signals.rerank_score;
  return score == null ? "-" : score.toFixed(5);
}

export function RetrievalLabPage() {
  const [params] = useSearchParams();
  const requestedMission = params.get("mission");
  const requestedIndex = mosaicLabMissions.findIndex((mission) => mission.id === requestedMission);
  const [selected, setSelected] = useState(requestedIndex >= 0 ? requestedIndex : 0);
  const [stage, setStage] = useState<Stage>("lexical");
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const mission = mosaicLabMissions[selected];
  const rows = useMemo(
    () => [...(response?.results ?? [])].sort((a, b) => stageRank(a, stage) - stageRank(b, stage)),
    [response, stage],
  );

  async function run() {
    if (!mission) return;
    setLoading(true);
    setError("");
    try {
      setResponse(await api.search(mission.query, mission.filters, { limit: 12, rerank: true }));
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
          <p className="eyebrow">Mosaic Labs</p>
          <h1>Inspect a retrieval run</h1>
          <p>Follow one golden query from candidate source through fuzzy recovery, semantic intent, fusion, and Cohere Rerank.</p>
        </div>
        <button className="primary-button" type="button" disabled={!mission || loading} onClick={() => void run()}>
          <Play size={17} fill="currentColor" /> Run pipeline
        </button>
      </header>

      <section className="lab-query-bar">
        <label>
          <span>Golden query</span>
          <select value={selected} onChange={(event) => { setSelected(Number(event.target.value)); setResponse(null); }}>
            {mosaicLabMissions.map((item, index) => <option value={index} key={item.id}>{item.title}</option>)}
          </select>
        </label>
        <div className="technique-list">
          {mission?.expected_techniques.map((item) => <span key={item}>{item.replaceAll("_", " ")}</span>)}
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
            {response ? <span className="run-id">Run {response.search_event_id.slice(0, 8)}</span> : null}
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
                          <i className={product.signals?.fts.rank ? "on" : ""} />
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
        <aside className="lab-code-panel lab-inspection-panel">
          <p className="eyebrow">Mosaic psql</p>
          <h2>Approved query replay</h2>
          <p>
            {stages.find((item) => item.id === stage)?.detail}. The Run pipeline
            action executes the approved retrieval request; this panel never
            opens an arbitrary browser-to-database console.
          </p>
          <CodeBlock code={psqlByStage[stage]} label={`${stage}.psql`} />
          <dl className="inspection-list">
            <div>
              <dt>Golden target</dt>
              <dd>{mission?.target_product_ids.map((id) => `#${id}`).join(", ") ?? "-"}</dd>
            </div>
            <div>
              <dt>Success checks</dt>
              <dd>{mission?.assertions.map((item) => item.replaceAll("_", " ")).join(" · ") ?? "-"}</dd>
            </div>
            <div>
              <dt>Rank fields</dt>
              <dd>RRF rank · Cohere Rerank score · final rank</dd>
            </div>
          </dl>
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
