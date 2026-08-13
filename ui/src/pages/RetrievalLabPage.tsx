import { ArrowDown, CircleCheck, Play, SlidersHorizontal } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { api } from "../api";
import { CodeBlock } from "../components/CodeBlock";
import { LabOutcomeBanner } from "../components/LabOutcomeBanner";
import { RetrievalDiagnosticsStrip } from "../components/RetrievalDiagnosticsStrip";
import { ErrorState, LoadingState } from "../components/States";
import { WorkshopProgress } from "../components/WorkshopProgress";
import { retrievalLabOutcome } from "../labOutcome";
import { mosaicRetrievalExamples } from "../labMissions";
import { productImageMap } from "../media";
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

type ContrastArm = {
  id: "fts" | "semantic" | "hybrid";
  label: string;
  status: "present" | "missing";
  summary: string;
  detail: string;
};

function contrastForTarget(
  example: typeof mosaicRetrievalExamples[number],
  response: SearchResponse,
): { target: ProductSummary; arms: ContrastArm[]; contributingArms: string[] } | null {
  const targetId = example.target_product_ids[0];
  const target = response.results.find((product) => product.product_id === targetId);
  if (!target?.signals) return null;

  const ftsRank = target.signals.fts.rank;
  const semanticRank = target.signals.semantic.rank;
  const contributingArms = [
    target.signals.fts.rank !== null ? "FTS" : null,
    target.signals.trigram.rank !== null ? "pg_trgm" : null,
    target.signals.semantic.rank !== null ? "vector" : null,
  ].filter((arm): arm is string => arm !== null);

  return {
    target,
    arms: [
      {
        id: "fts",
        label: "FTS only",
        status: ftsRank === null ? "missing" : "present",
        summary: ftsRank === null
          ? "Break: target absent from the lexical candidate list."
          : `Target enters the lexical candidate list at #${ftsRank}.`,
        detail: ftsRank === null
          ? "The terms in this request do not produce a sufficiently specific text match."
          : "PostgreSQL full-text search preserves exact words, identifiers, and indexed aliases.",
      },
      {
        id: "semantic",
        label: "Vector only",
        status: semanticRank === null ? "missing" : "present",
        summary: semanticRank === null
          ? "Break: target absent from the vector candidate list."
          : `Target enters the HNSW candidate list at #${semanticRank}.`,
        detail: semanticRank === null
          ? "Embedding similarity did not preserve this exact identity in the bounded vector pool."
          : "pgvector recovers nearby meaning, but its score is not an identity guarantee.",
      },
      {
        id: "hybrid",
        label: "Hybrid retrieval",
        status: "present",
        summary: `Target returns at final rank #${target.signals.final_rank}.`,
        detail: contributingArms.length > 0
          ? `RRF retains ${contributingArms.join(" + ")} provenance before bounded reranking.`
          : "No candidate arm contributed this target, so this result requires investigation.",
      },
    ],
    contributingArms,
  };
}

export function RetrievalLabPage() {
  const [params] = useSearchParams();
  const requestedExample = params.get("example") ?? params.get("mission");
  const requestedIndex = mosaicRetrievalExamples.findIndex(
    (example) => example.id === requestedExample,
  );
  const [selected, setSelected] = useState(requestedIndex >= 0 ? requestedIndex : 0);
  const [stage, setStage] = useState<Stage>("lexical");
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const requestVersion = useRef(0);
  const example = mosaicRetrievalExamples[selected];
  const rows = useMemo(
    () => [...(response?.results ?? [])].sort((a, b) => stageRank(a, stage) - stageRank(b, stage)),
    [response, stage],
  );
  // Assigned over the whole response, so re-sorting by stage does not reshuffle
  // which photograph a row carries.
  const rowImages = useMemo(() => productImageMap(response?.results ?? []), [response]);
  const movementRows = useMemo(
    () => [...(response?.results ?? [])]
      .sort((a, b) => (a.signals?.final_rank ?? 999) - (b.signals?.final_rank ?? 999))
      .slice(0, 4),
    [response],
  );
  const outcome = useMemo(
    () => retrievalLabOutcome(example, response),
    [example, response],
  );
  const targetContrast = useMemo(
    () => (example && response ? contrastForTarget(example, response) : null),
    [example, response],
  );

  async function run() {
    if (!example) return;
    const requestedExample = example;
    const version = requestVersion.current + 1;
    requestVersion.current = version;
    setLoading(true);
    setError("");
    try {
      const nextResponse = await api.search(
        requestedExample.query,
        requestedExample.filters,
        { limit: 12, rerank: true },
      );
      if (version === requestVersion.current) setResponse(nextResponse);
    } catch (cause) {
      if (version === requestVersion.current) {
        setError(cause instanceof Error ? cause.message : "Retrieval failed");
      }
    } finally {
      if (version === requestVersion.current) setLoading(false);
    }
  }

  return (
    <div className="page lab-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">Mosaic Labs</p>
          <h1>Inspect a retrieval run</h1>
          <p>Follow one validated query from candidate source through fuzzy recovery, semantic intent, fusion, and Cohere Rerank.</p>
        </div>
        <button className="primary-button" type="button" disabled={!example || loading} onClick={() => void run()}>
          <Play size={17} fill="currentColor" /> Run pipeline
        </button>
      </header>

      <WorkshopProgress
        active={example?.stage === "reason" ? "reason" : example?.stage === "rank" ? "rank" : "retrieve"}
      />

      <section className="lab-query-bar">
        <label>
          <span>Lab or checkpoint query</span>
          <select value={selected} onChange={(event) => {
            requestVersion.current += 1;
            setSelected(Number(event.target.value));
            setResponse(null);
            setError("");
            setLoading(false);
          }}>
            {mosaicRetrievalExamples.map((item, index) => <option value={index} key={item.id}>{item.title}</option>)}
          </select>
        </label>
        <div className="technique-list">
          {example?.expected_techniques.map((item) => <span key={item}>{item.replaceAll("_", " ")}</span>)}
        </div>
      </section>

      <LabOutcomeBanner outcome={outcome} />

      {response ? <RetrievalDiagnosticsStrip response={response} /> : null}

      {targetContrast ? (
        <section className="retrieval-method-contrast" aria-labelledby="retrieval-method-contrast-title">
          <header>
            <div>
              <p className="eyebrow">Measured retriever contrast</p>
              <h2 id="retrieval-method-contrast-title">Where does this target enter?</h2>
            </div>
            <p>
              Target #{targetContrast.target.product_id} · {targetContrast.target.model}
            </p>
          </header>
          <div className="retrieval-method-contrast-grid">
            {targetContrast.arms.map((arm) => (
              <article className={arm.status} key={arm.id}>
                <span>{arm.label}</span>
                <strong>{arm.summary}</strong>
                <p>{arm.detail}</p>
              </article>
            ))}
          </div>
          <footer>
            Structured filters are applied inside every candidate arm. A missing
            rank means that arm did not contribute this product; it does not mean
            the product became ineligible after fusion.
          </footer>
        </section>
      ) : null}

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
                      <td>
                        <div className="ranking-product">
                          <img className="ranking-product-image" src={rowImages.get(product.product_id)} alt="" />
                          <span>
                            <strong>{product.title}</strong>
                            <small>{product.brand} / {product.model}</small>
                          </span>
                        </div>
                      </td>
                      <td className="mono">{stageScore(product, stage)}</td>
                      <td>
                        <span className="arm-provenance" aria-label="Candidate provenance">
                          <i className={product.signals?.fts.rank ? "on" : ""}>FTS</i>
                          <i className={product.signals?.trigram.rank ? "on" : ""}>TRGM</i>
                          <i className={product.signals?.semantic.rank ? "on" : ""}>VEC</i>
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
              <dt>Validated target</dt>
              <dd>{example?.target_product_ids.map((id) => `#${id}`).join(", ") ?? "-"}</dd>
            </div>
            <div>
              <dt>Success checks</dt>
              <dd>{example?.assertions.map((item) => item.replaceAll("_", " ")).join(" · ") ?? "-"}</dd>
            </div>
            <div>
              <dt>Rank fields</dt>
              <dd>RRF rank · Cohere Rerank score · final rank</dd>
            </div>
            {response?.diagnostics ? (
              <div>
                <dt>Embedding</dt>
                <dd>
                  {response.diagnostics.embedding_model_id} ·{" "}
                  {response.diagnostics.embedding_dimensions}d
                </dd>
              </div>
            ) : null}
          </dl>
        </aside>
      </div>

      {response ? (
        <section className="rank-movement-panel" aria-labelledby="rank-movement-title">
          <header>
            <div>
              <p className="eyebrow">Why #1?</p>
              <h2 id="rank-movement-title">Ranking movement</h2>
            </div>
            <p>Missing arm ranks mean that retriever did not contribute the candidate.</p>
          </header>
          <div className="rank-movement-wrap">
            <table>
              <thead>
                <tr>
                  <th>Product</th>
                  <th>FTS</th>
                  <th>pg_trgm</th>
                  <th>Vector</th>
                  <th>RRF</th>
                  <th>Rerank score</th>
                  <th>Final</th>
                </tr>
              </thead>
              <tbody>
                {movementRows.map((product) => (
                  <tr className={product.signals?.final_rank === 1 ? "winner" : ""} key={product.product_id}>
                    <td><strong>{product.model}</strong><small>#{product.product_id}</small></td>
                    <td>{product.signals?.fts.rank ?? "-"}</td>
                    <td>{product.signals?.trigram.rank ?? "-"}</td>
                    <td>{product.signals?.semantic.rank ?? "-"}</td>
                    <td>{product.signals?.pre_rerank_rank ?? "-"}</td>
                    <td>{product.signals?.rerank_score?.toFixed(4) ?? "-"}</td>
                    <td><strong>{product.signals?.final_rank ?? "-"}</strong></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}
