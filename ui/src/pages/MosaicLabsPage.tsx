import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Database,
  FileText,
  GitCompareArrows,
  Play,
  ScanSearch,
  ShieldCheck,
  Sparkles,
  Wrench,
} from "lucide-react";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Link } from "wouter";
import { api } from "../api";
import { LabsIntroFlow } from "../components/LabsIntroFlow";
import {
  coreMosaicLabs,
  mosaicLabManifest,
  retrievalExampleHref,
  supportingMosaicChecks,
  type MosaicLabMission,
  type MosaicLabPlacement,
  type MosaicLabStage,
} from "../labMissions";
import { productImage } from "../media";
import type { ProductSummary } from "../types";

type StageDetail = {
  label: string;
  verb: string;
  title: string;
  observation: string;
  question: string;
  detail: string;
  Icon: typeof ScanSearch;
};

const stageDetails: Record<MosaicLabStage, StageDetail> = {
  retrieve: {
    label: "Retrieve",
    verb: "Build the candidate universe",
    title: "Build hybrid retrieval",
    observation: "Candidate provenance",
    question: "Where did this candidate come from?",
    detail: "Recover the right eligible candidates across lexical, fuzzy, semantic, and structured retrieval.",
    Icon: ScanSearch,
  },
  rank: {
    label: "Rank",
    verb: "Put candidates in order",
    title: "Fuse, rerank, and explain",
    observation: "Rank movement",
    question: "Why did #1 beat #2?",
    detail: "Make ordinal fusion and bounded model reranking visible without hiding candidate provenance.",
    Icon: GitCompareArrows,
  },
  reason: {
    label: "Reason",
    verb: "Ground the recommendation",
    title: "Build the retrieval agent",
    observation: "Grounded evidence",
    question: "What did the agent reason about?",
    detail: "Compose typed retrieval, comparison, evidence, and citation tools into one grounded decision.",
    Icon: ShieldCheck,
  },
  optimize: {
    label: "Advanced",
    verb: "Measure the operating point",
    title: "Tune HNSW",
    observation: "Operating-point evidence",
    question: "What operating point meets the workload?",
    detail: "Compare recall, latency, plans, and index configuration outside the required path.",
    Icon: Activity,
  },
};

const placementByStage: Partial<Record<MosaicLabStage, MosaicLabPlacement>> = {
  retrieve: "lab-1",
  rank: "lab-2",
  reason: "lab-3",
};

const techniqueLabels: Record<string, string> = {
  fts: "FTS",
  full_text_search: "FTS",
  trigram: "pg_trgm",
  pg_trgm: "pg_trgm",
  semantic: "pgvector",
  vector: "pgvector",
  pgvector: "pgvector",
  filters: "SQL filters",
  structured_filters: "SQL filters",
  exact_identity: "Exact identity",
  rrf: "RRF",
  rerank: "Rerank",
  evidence: "Evidence",
  agent: "Agent tools",
};

function checksFor(lab: MosaicLabMission) {
  const placement = placementByStage[lab.stage];
  return supportingMosaicChecks.filter(
    (check) => check.core && check.placement === placement,
  );
}

function labelTechnique(technique: string) {
  return techniqueLabels[technique] ?? technique.replaceAll("_", " ");
}

function shopScenarioHref(example: MosaicLabMission) {
  const params = new URLSearchParams({ q: example.query });
  Object.entries(example.filters).forEach(([key, value]) => {
    if (
      value !== undefined
      && value !== null
      && (
        typeof value === "string"
        || typeof value === "number"
        || typeof value === "boolean"
      )
    ) {
      params.set(key, String(value));
    }
  });

  if (example.stage === "reason") {
    params.set("ask", "1");
    params.set("mission", example.id);
  }

  return `/catalog?${params.toString()}`;
}

function contrastLens(example: MosaicLabMission) {
  if (example.id === "exact-identity") {
    return {
      label: "Exact identity",
      title: "An identifier is not an intent",
      detail: "FTS owns deterministic product and catalog-code recall.",
    };
  }
  return {
    label: "Intent language",
    title: "A benefit is not a product term",
    detail: "Vector retrieval can recover intent that the lexical arm does not name.",
  };
}

const engineTraceMission = coreMosaicLabs[0];

const engineProductIds = [2, 3, 4, 5, 1, 17001];

type EngineVisual = {
  title: string;
  copy: string;
  productLabel: string;
  visibleProductIds: number[];
  productOrder: number[];
};

/**
 * The engine, end to end, before a participant opens a single lab.
 *
 * Every mechanic named here is the one the service actually runs, and every
 * value comes from the mission manifest. Nothing in this diagram is a
 * measurement: measured numbers belong on a surface that has run a query.
 */
const engineSteps = [
  {
    step: "01",
    title: "Natural language query",
    caption: "Typos, intent, and hard constraints arrive in one request.",
    owner: null as MosaicLabStage | null,
    mechanics: [`"${engineTraceMission.query}"`],
    visual: {
      title: "Parse one request before searching",
      copy: "The fixture starts as a single imperfect request. Retrieval and ranking stay inspectable after the query is normalized.",
      productLabel: "Premium cohort ready",
      visibleProductIds: engineProductIds,
      productOrder: engineProductIds,
    },
  },
  {
    step: "02",
    title: "Candidate generation",
    caption: "Three arms run independently over one retrieval projection.",
    owner: "retrieve" as MosaicLabStage,
    mechanics: [
      "tsvector + ts_rank_cd",
      "pg_trgm similarity",
      `pgvector HNSW · ${mosaicLabManifest.corpus.embedding_dimensions}d cosine`,
    ],
    visual: {
      title: "Build a candidate universe",
      copy: "Independent lexical, fuzzy, and semantic arms make the candidate set tangible before any final ordering exists.",
      productLabel: "Candidate set",
      visibleProductIds: engineProductIds,
      productOrder: engineProductIds,
    },
  },
  {
    step: "03",
    title: "Structured filters",
    caption: "Hard constraints stay authoritative, never a soft signal.",
    owner: "retrieve" as MosaicLabStage,
    mechanics: ["price", "category", "availability", "rating"],
    visual: {
      title: "Apply deterministic eligibility",
      copy: "Only candidates that satisfy the fixture's structured constraints continue. Filters are not model suggestions.",
      productLabel: "Eligible candidate",
      visibleProductIds: [2, 3, 4, 5],
      productOrder: [2, 3, 4, 5, 1, 17001],
    },
  },
  {
    step: "04",
    title: "Reciprocal rank fusion",
    caption: "One ordering from rank positions, not from rescaled scores.",
    owner: "rank" as MosaicLabStage,
    mechanics: ["1 / (k + rank) per channel", "candidate provenance preserved"],
    visual: {
      title: "Fuse rank lists without hiding provenance",
      copy: "RRF combines ordinal positions from each channel while the original retrieval evidence remains available for inspection.",
      productLabel: "Fused candidate",
      visibleProductIds: [2, 3, 4, 5],
      productOrder: [2, 4, 3, 5, 1, 17001],
    },
  },
  {
    step: "05",
    title: "Cross-encoder rerank",
    caption: "A bounded model pass over the fused shortlist only.",
    owner: "rank" as MosaicLabStage,
    mechanics: [mosaicLabManifest.corpus.reranker],
    visual: {
      title: "Rerank a bounded shortlist",
      copy: "The model sees only the fused shortlist. It can change the order, but it cannot quietly expand the eligible candidate universe.",
      productLabel: "Reranked candidate",
      visibleProductIds: [2, 4, 3],
      productOrder: [2, 4, 3, 5, 1, 17001],
    },
  },
  {
    step: "06",
    title: "Grounded recommendation",
    caption: "Typed tool calls with citations that resolve to rows.",
    owner: "reason" as MosaicLabStage,
    mechanics: ["search_products()", "compare_products()", "get_product_evidence()"],
    visual: {
      title: "Ground the recommendation in evidence",
      copy: "Typed tool calls compare shortlisted products, retrieve supporting evidence, and return citation IDs that resolve to real records.",
      productLabel: "Grounded shortlist",
      visibleProductIds: [2, 4, 3],
      productOrder: [2, 4, 3, 5, 1, 17001],
    },
  },
];

function engineProductState(
  product: ProductSummary,
  visual: EngineVisual,
  stepIndex: number,
) {
  const visible = visual.visibleProductIds.includes(product.product_id);
  const rank = visual.productOrder.indexOf(product.product_id) + 1;

  if (!visible) return { label: "Outside current set", state: "muted", rank };
  if (stepIndex === 0) return { label: "Catalog record", state: "prepared", rank };
  if (stepIndex === 1) return { label: "Candidate", state: "candidate", rank };
  if (stepIndex === 2) return { label: "Eligible", state: "eligible", rank };
  if (stepIndex === 3) return { label: "Fused shortlist", state: "shortlist", rank };
  if (stepIndex === 4) return { label: "Rerank shortlist", state: "shortlist", rank };
  return {
    label: product.product_id === engineTraceMission.target_product_ids[0]
      ? "Evidence trace"
      : "Compared product",
    state: product.product_id === engineTraceMission.target_product_ids[0]
      ? "featured"
      : "shortlist",
    rank,
  };
}

/** The substrate each step above runs on, named the way the SQL names it. */
const substrate = [
  {
    Icon: Database,
    label: "Aurora PostgreSQL",
    detail: `${mosaicLabManifest.corpus.catalog_products.toLocaleString()} products, one projection`,
  },
  {
    Icon: FileText,
    label: "Full-text search",
    detail: "tsvector, OR-combined tsquery, ts_rank_cd",
  },
  {
    Icon: ScanSearch,
    label: "pg_trgm",
    detail: "Trigram similarity for misspelled input",
  },
  {
    Icon: Sparkles,
    label: "pgvector HNSW",
    detail: `${mosaicLabManifest.corpus.embedding_model_id}, cosine`,
  },
  {
    Icon: GitCompareArrows,
    label: "Hybrid ranking",
    detail: "RRF, then a bounded reranker, both inspectable",
  },
];

export function MosaicLabsPage() {
  const [activeEngineStep, setActiveEngineStep] = useState(1);
  const [isEnginePlaying, setIsEnginePlaying] = useState(false);
  const [engineProducts, setEngineProducts] = useState<ProductSummary[]>([]);
  const [engineProductsError, setEngineProductsError] = useState("");
  const replayTimers = useRef<number[]>([]);
  const advancedLabs = supportingMosaicChecks.filter(
    (check) => check.placement === "advanced-labs",
  );
  const retrievalContrasts = [
    ...supportingMosaicChecks.filter(
      (check) => check.id === "exact-identity" || check.id === "semantic-intent-contrast",
    ),
  ];
  const participantRunCount = coreMosaicLabs.reduce(
    (count, lab) => count + 1 + checksFor(lab).length,
    0,
  );
  const activeEngine = engineSteps[activeEngineStep];

  useEffect(() => () => {
    replayTimers.current.forEach((timer) => window.clearTimeout(timer));
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.all(engineProductIds.map((productId) => api.product(productId)))
      .then((products) => {
        if (!cancelled) {
          setEngineProducts(products);
          setEngineProductsError("");
        }
      })
      .catch((cause) => {
        if (!cancelled) {
          setEngineProducts([]);
          setEngineProductsError(
            cause instanceof Error
              ? cause.message
              : "Catalog product records are unavailable",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const selectEngineStep = (index: number) => {
    replayTimers.current.forEach((timer) => window.clearTimeout(timer));
    replayTimers.current = [];
    setIsEnginePlaying(false);
    setActiveEngineStep(index);
  };

  const replayEngineJourney = () => {
    replayTimers.current.forEach((timer) => window.clearTimeout(timer));
    replayTimers.current = [];

    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setIsEnginePlaying(false);
      setActiveEngineStep(engineSteps.length - 1);
      return;
    }

    setActiveEngineStep(0);
    setIsEnginePlaying(true);
    engineSteps.slice(1).forEach((_, index) => {
      const timer = window.setTimeout(() => {
        setActiveEngineStep(index + 1);
        if (index === engineSteps.length - 2) setIsEnginePlaying(false);
      }, (index + 1) * 620);
      replayTimers.current.push(timer);
    });
  };

  return (
    <div className="page mosaic-labs-page labs-premium">
      <header className="labs-intro">
        <div className="labs-intro-copy">
          <p className="eyebrow">DAT410 · Aurora PostgreSQL · Level 400</p>
          <h1>Explore. Ask. Understand.</h1>
          <p className="labs-intro-deck">
            Agentic retrieval. Intelligent ranking. Recommendations grounded in
            evidence you can inspect.
          </p>
          <p className="labs-intro-thesis">
            Build the retrieval system first. Then give it to the agent.
          </p>
          <div className="labs-intro-actions">
            <Link className="primary-button" href={shopScenarioHref(coreMosaicLabs[0])}>
              View Lab 1 in Shop <ArrowRight size={17} />
            </Link>
            <span>3 labs · {participantRunCount} Shop proof scenarios · 40-45 minutes</span>
          </div>
        </div>
        <div className="labs-intro-flow-wrap">
          <LabsIntroFlow />
        </div>
      </header>

      <section className="labs-engine labs-engine-board" aria-labelledby="labs-engine-title">
        <header className="labs-engine-heading">
          <div>
            <p className="eyebrow">Retrieval and ranking engine</p>
            <h2 id="labs-engine-title">From one sentence to a cited recommendation.</h2>
            <p>
              Replay the architecture path to see a real Mosaic product cohort
              enter, narrow, reorder, and resolve into grounded evidence.
            </p>
          </div>
          <button
            className="labs-engine-replay"
            disabled={isEnginePlaying}
            onClick={replayEngineJourney}
            type="button"
          >
            <Play size={15} fill="currentColor" />
            {isEnginePlaying ? "Tracing the path" : "Replay the path"}
          </button>
        </header>

        <ol className="labs-engine-rail" aria-label="Retrieval and ranking stages">
          {engineSteps.map((step, index) => (
            <li
              className={
                index < activeEngineStep
                  ? "complete"
                  : index === activeEngineStep
                    ? "active"
                    : ""
              }
              key={step.step}
            >
              <button
                aria-current={index === activeEngineStep ? "step" : undefined}
                onClick={() => selectEngineStep(index)}
                type="button"
              >
                <span>{step.step}</span>
                <strong>{step.title}</strong>
                {step.owner ? <small>{stageDetails[step.owner].label}</small> : null}
              </button>
            </li>
          ))}
        </ol>

        <section
          className="labs-engine-spotlight"
          data-stage={activeEngine.step}
          aria-live="polite"
        >
          <div className="labs-engine-spotlight-copy">
            <p className="eyebrow">
              Step {activeEngine.step}
              {activeEngine.owner ? ` · ${stageDetails[activeEngine.owner].label}` : ""}
            </p>
            <h3>{activeEngine.visual.title}</h3>
            <p>{activeEngine.visual.copy}</p>
            <ul aria-label={`${activeEngine.title} implementation details`}>
              {activeEngine.mechanics.map((mechanic) => (
                <li key={mechanic}><code>{mechanic}</code></li>
              ))}
            </ul>
          </div>

          <div className="labs-engine-products-wrap">
            <div className="labs-engine-products-heading">
              <span>{activeEngine.visual.productLabel}</span>
              <small>Live premium catalog records</small>
            </div>
            {engineProducts.length ? (
              <div className="labs-engine-products" key={activeEngine.step}>
                {engineProducts.map((product, index) => {
                  const state = engineProductState(product, activeEngine.visual, activeEngineStep);
                  return (
                    <figure
                      className={`labs-engine-product ${state.state}`}
                      key={product.product_id}
                      style={{
                        "--product-order": state.rank,
                        "--product-index": index,
                      } as CSSProperties}
                    >
                      <div className="labs-engine-product-media">
                        <img
                          src={productImage(product)}
                          alt={product.title}
                          width={1200}
                          height={800}
                        />
                      </div>
                      <figcaption>
                        <strong>{product.model}</strong>
                        <small>{state.label}</small>
                      </figcaption>
                    </figure>
                  );
                })}
              </div>
            ) : (
              <p className="labs-engine-products-unavailable" role="status">
                {engineProductsError
                  ? `Catalog product records are unavailable: ${engineProductsError}`
                  : "Loading catalog product records..."}
              </p>
            )}
          </div>
        </section>
      </section>

      <section
        className="labs-retrieval-contrasts"
        aria-labelledby="labs-retrieval-contrasts-title"
      >
        <header className="labs-retrieval-contrasts-heading">
          <div>
            <p className="eyebrow">Retriever contrast</p>
            <h2 id="labs-retrieval-contrasts-title">One request, three retrieval outcomes.</h2>
          </div>
          <p>
            Run these read-only traces to see where a single retriever stops being
            sufficient, then inspect exactly which candidates hybrid retrieval keeps.
          </p>
        </header>
        <div className="labs-retrieval-contrast-grid">
          {retrievalContrasts.map((example) => {
            const lens = contrastLens(example);
            return (
              <article className="labs-retrieval-contrast" key={example.id}>
                <div>
                  <span>{lens.label}</span>
                  <h3>{lens.title}</h3>
                  <p>{lens.detail}</p>
                </div>
                <code>{example.query}</code>
                <p className="labs-retrieval-contrast-outcome">
                  {example.expected_outcome}
                </p>
                <Link href={retrievalExampleHref(example)}>
                  Inspect FTS, vector, and hybrid <ArrowRight size={15} />
                </Link>
              </article>
            );
          })}
        </div>
      </section>

      <section className="labs-core" aria-labelledby="labs-core-title">
        <header className="labs-section-heading">
          <div>
            <p className="eyebrow">Read-only observability</p>
            <h2 id="labs-core-title">See what each Code Editor repair changes.</h2>
          </div>
          <p>
            Workshop Studio owns the broken snippet, hint, and repair. Mosaic Labs
            explains the system state; Shop is the customer-facing proof.
          </p>
        </header>

        <div className="labs-stage-grid">
          {coreMosaicLabs.map((lab, index) => {
            const stage = stageDetails[lab.stage];
            const Icon = stage.Icon;
            const runs = [lab, ...checksFor(lab)];
            return (
              <article className={`labs-stage-card ${lab.stage}`} id={lab.id} key={lab.id}>
                <header className="labs-stage-heading">
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <Icon size={20} />
                  <div>
                    <p>Lab {index + 1} · {stage.label}</p>
                    <h3>{stage.observation}</h3>
                  </div>
                  <small>{lab.duration_minutes} min</small>
                </header>

                <div className="labs-stage-question">
                  <span>What to inspect</span>
                  <strong>{stage.question}</strong>
                </div>

                <p className="labs-stage-techniques">
                  {lab.expected_techniques.map((technique) => (
                    <span key={technique}>{labelTechnique(technique)}</span>
                  ))}
                </p>

                <dl className="labs-observation-sequence">
                  <div>
                    <dt>Before</dt>
                    <dd>{lab.participant_edit?.broken_state ?? "The stage fails its retrieval contract."}</dd>
                  </div>
                  <div>
                    <dt>After</dt>
                    <dd>{lab.participant_edit?.fixed_state ?? lab.expected_outcome}</dd>
                  </div>
                  <div>
                    <dt>Shop proof</dt>
                    <dd>{lab.expected_outcome}</dd>
                  </div>
                </dl>

                <div className="labs-shop-proofs" aria-label={`${stage.label} Shop proof scenarios`}>
                  <p>{runs.length} Shop proof {runs.length === 1 ? "scenario" : "scenarios"}</p>
                  {runs.map((run, runIndex) => (
                    <Link
                      href={shopScenarioHref(run)}
                      key={run.id}
                    >
                      <span>{String(runIndex + 1).padStart(2, "0")}</span>
                      <div>
                        <strong>{run.checkpoint === "repair" ? "Core scenario" : "Control scenario"}</strong>
                        <code>{run.query}</code>
                      </div>
                      <small>Shop</small>
                      <ArrowRight size={15} />
                    </Link>
                  ))}
                </div>

                <footer>
                  <Link href={shopScenarioHref(lab)}>
                    Open Shop scenario <ArrowRight size={15} />
                  </Link>
                  <span>{lab.canonical_query_id}</span>
                </footer>
              </article>
            );
          })}
        </div>
      </section>

      <section className="labs-substrate" aria-label="What the engine runs on">
        {substrate.map(({ Icon, label, detail }) => (
          <div key={label}>
            <Icon size={19} />
            <span>
              <strong>{label}</strong>
              <small>{detail}</small>
            </span>
          </div>
        ))}
      </section>

      {advancedLabs.length > 0 ? (
        <details className="labs-advanced" open>
          <summary>
            <span>
              <Activity size={18} />
              <strong>Advanced observability</strong>
              <small>Optional HNSW operating point and retrieval evaluation</small>
            </span>
            <Wrench size={17} />
          </summary>
          <div>
            <p>
              Outside the required path, vary query-time candidate breadth with
              <code>hnsw.ef_search</code>, compare it to exact-neighbor ground
              truth, and retain the plan that explains the measured trade-off.
            </p>
            <div>
              <span><CheckCircle2 size={16} /> Build: <code>m</code> and <code>ef_construction</code></span>
              <span><CheckCircle2 size={16} /> Query: <code>hnsw.ef_search</code> and iterative scan</span>
              <span><CheckCircle2 size={16} /> Evidence: Recall@K, p50/p95, and <code>EXPLAIN (ANALYZE, BUFFERS)</code></span>
            </div>
            <Link className="secondary-button" href="/labs/performance">
              Open HNSW diagnostics <ArrowRight size={16} />
            </Link>
          </div>
        </details>
      ) : null}
    </div>
  );
}
