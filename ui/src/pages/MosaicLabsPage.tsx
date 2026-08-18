import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Database,
  FileText,
  GitCompareArrows,
  Play,
  Search,
  ScanSearch,
  ShieldCheck,
  Sparkles,
  Wrench,
} from "lucide-react";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Link } from "wouter";
import { api } from "../api";
import { MosaicLabsMasthead } from "../components/MosaicLabsMasthead";
import { MosaicLabsTabs } from "../components/MosaicLabsTabs";
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
    title: "Fuse, rerank, and inspect",
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

function requiredCoreLab(id: string): MosaicLabMission {
  const lab = coreMosaicLabs.find((candidate) => candidate.id === id);
  if (!lab) {
    throw new Error(`Mosaic Labs replay requires core lab ${id}.`);
  }
  return lab;
}

const engineTraceMission = requiredCoreLab("typo-recovery");

const engineProductIds = [2, 3, 4, 5, 1, 17001];
const engineReplayStepDurationMs = 1650;
const engineQueryCharacterDelayMs = 50;

/**
 * One catalog photograph per system lens, chosen for the row rather than taken
 * from the lab's own targets.
 *
 * Taking each mission's first target put an `ergonomic-office-chairs` product in
 * two of the three lenses, and Lab 3 has no third category to reach for: its
 * mission and its supporting check target only the Forma chair and the Keysmith
 * keyboard. So the photograph is picked for the row instead, and the caption
 * reads "Pictured" rather than claiming the product anchors the lab beside it.
 *
 * Every id here is a real merchandised product with its own commissioned
 * photography, so the model name under each frame is still a catalog fact. Keyed
 * by stage, and falling back to the mission's first target, so a new stage
 * renders something real without an entry.
 */
const labIllustrationByStage: Partial<Record<MosaicLabStage, number>> = {
  retrieve: 2, // Sonora WH-C720, over-ear headphones
  rank: 370002, // PostureWorks Pro Mesh, ergonomic chair
  reason: 234001, // AeroStride Carbon Pro 3, the flagship carbon racing shoe
};

function labIllustrationId(lab: MosaicLabMission): number {
  return labIllustrationByStage[lab.stage] ?? lab.target_product_ids[0];
}

const labThumbnailIds = coreMosaicLabs.map(labIllustrationId);

type EngineVisual = {
  title: string;
  copy: string;
  productLabel: string;
  visibleProductIds: number[];
  productOrder: number[];
};

type EngineScenario = {
  id: string;
  label: string;
  mission: MosaicLabMission;
  candidateOrder: number[];
  eligibleProductIds: number[];
  fusedOrder: number[];
  rerankedOrder: number[];
};

function requiredSupportingCheck(id: string): MosaicLabMission {
  const check = supportingMosaicChecks.find((candidate) => candidate.id === id);
  if (!check) {
    throw new Error(`Mosaic Labs replay requires supporting check ${id}.`);
  }
  return check;
}

const engineScenarios: EngineScenario[] = [
  {
    id: "exact-identity",
    label: "Exact identity",
    mission: requiredSupportingCheck("exact-identity"),
    candidateOrder: [17001, 2, 3, 5, 4, 1],
    eligibleProductIds: [17001, 2, 3, 5, 4, 1],
    fusedOrder: [17001, 2, 3, 5, 4, 1],
    rerankedOrder: [17001, 2, 3, 5, 4, 1],
  },
  {
    id: "typo-recovery",
    label: "Typo recovery",
    mission: engineTraceMission,
    candidateOrder: [2, 3, 4, 5, 1, 17001],
    eligibleProductIds: [2, 3, 4, 5],
    fusedOrder: [2, 4, 3, 5, 1, 17001],
    rerankedOrder: [2, 4, 3, 5, 1, 17001],
  },
  {
    id: "semantic-intent-contrast",
    label: "Semantic intent",
    mission: requiredSupportingCheck("semantic-intent-contrast"),
    candidateOrder: [3, 5, 2, 4, 1, 17001],
    eligibleProductIds: [2, 3, 4, 5],
    fusedOrder: [3, 2, 5, 4, 1, 17001],
    rerankedOrder: [3, 5, 2, 4, 1, 17001],
  },
];

/**
 * The engine, end to end, before a participant opens a single lab.
 *
 * Every mechanic named here is one the service actually runs. Product orders
 * are explicit replay fixtures, not measurements; measured ranks belong on a
 * surface that has executed the query.
 */
const engineSteps = [
  {
    step: "01",
    title: "Query",
    caption: "Identity, lexical form, intent, and constraints start here.",
    owner: null as MosaicLabStage | null,
    mechanics: [],
    visual: {
      title: "Start with one request",
      copy: "Each fixture begins with one query. Retrieval and ranking stay inspectable as the system normalizes it and builds candidates.",
      productLabel: "Premium cohort ready",
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
    },
  },
];

function engineVisualForScenario(
  scenario: EngineScenario,
  stepIndex: number,
): EngineVisual {
  const visual = engineSteps[stepIndex].visual;
  if (stepIndex === 0) {
    return {
      ...visual,
      visibleProductIds: engineProductIds,
      productOrder: engineProductIds,
    };
  }
  if (stepIndex === 1) {
    return {
      ...visual,
      visibleProductIds: engineProductIds,
      productOrder: scenario.candidateOrder,
    };
  }
  if (stepIndex === 2) {
    return {
      ...visual,
      visibleProductIds: scenario.eligibleProductIds,
      productOrder: scenario.candidateOrder,
    };
  }
  if (stepIndex === 3) {
    return {
      ...visual,
      visibleProductIds: scenario.eligibleProductIds,
      productOrder: scenario.fusedOrder,
    };
  }
  return {
    ...visual,
    visibleProductIds: scenario.rerankedOrder.slice(0, 3),
    productOrder: scenario.rerankedOrder,
  };
}

function engineProductState(
  product: ProductSummary,
  visual: EngineVisual,
  stepIndex: number,
  scenario: EngineScenario,
) {
  const visible = visual.visibleProductIds.includes(product.product_id);
  const rank = visual.productOrder.indexOf(product.product_id) + 1;
  const isTarget = product.product_id === scenario.mission.target_product_ids[0];
  const isExactIdentity = scenario.id === "exact-identity" && isTarget;

  if (!visible) return { label: "Outside current set", state: "muted", rank };
  if (stepIndex === 0) return { label: "Catalog record", state: "prepared", rank };
  if (isExactIdentity && stepIndex === 1) {
    return { label: "Exact FTS identity", state: "candidate", rank };
  }
  if (stepIndex === 1) return { label: "Candidate", state: "candidate", rank };
  if (stepIndex === 2) return { label: "Eligible", state: "eligible", rank };
  if (isExactIdentity && stepIndex === 3) {
    return { label: "Identity fused at #1", state: "shortlist", rank };
  }
  if (stepIndex === 3) return { label: "Fused shortlist", state: "shortlist", rank };
  if (isExactIdentity && stepIndex === 4) {
    return { label: "Exact model remains #1", state: "shortlist", rank };
  }
  if (stepIndex === 4) return { label: "Rerank shortlist", state: "shortlist", rank };
  return {
    label: isTarget
      ? "Evidence trace"
      : "Compared product",
    state: isTarget
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
  const [activeEngineStep, setActiveEngineStep] = useState(0);
  const [activeEngineScenarioIndex, setActiveEngineScenarioIndex] = useState(0);
  const [isEnginePlaying, setIsEnginePlaying] = useState(false);
  const [visibleEngineQueryLength, setVisibleEngineQueryLength] = useState(0);
  const [engineProducts, setEngineProducts] = useState<ProductSummary[]>([]);
  const [engineProductsError, setEngineProductsError] = useState("");
  const [labThumbnails, setLabThumbnails] = useState<Map<number, ProductSummary>>(new Map());
  const replayTimers = useRef<number[]>([]);
  const hasHnswAdvancedLab = supportingMosaicChecks.some(
    (check) => (
      check.id === "hnsw-performance"
      && check.placement === "advanced-labs"
    ),
  );
  const retrievalContrasts = [
    ...supportingMosaicChecks.filter(
      (check) => check.id === "exact-identity" || check.id === "semantic-intent-contrast",
    ),
  ];
  const activeEngineScenario = engineScenarios[activeEngineScenarioIndex];
  const activeEngine = engineSteps[activeEngineStep];
  const activeEngineQuery = activeEngineScenario.mission.query;
  const activeEngineVisual = engineVisualForScenario(
    activeEngineScenario,
    activeEngineStep,
  );
  const activeEngineMechanics = activeEngineStep === 0
    ? [`"${activeEngineQuery}"`]
    : activeEngine.mechanics;
  const isEngineQueryComplete = visibleEngineQueryLength >= activeEngineQuery.length;
  const engineEntries = engineProducts.map((product) => ({
    product,
    state: engineProductState(
      product,
      activeEngineVisual,
      activeEngineStep,
      activeEngineScenario,
    ),
  }));
  const visibleEngineEntries = engineEntries
    .filter(({ state }) => state.state !== "muted")
    .sort((left, right) => left.state.rank - right.state.rank);
  const leadingEngineEntry = visibleEngineEntries[0] ?? null;

  useEffect(() => () => {
    replayTimers.current.forEach((timer) => window.clearTimeout(timer));
  }, []);

  useEffect(() => {
    setVisibleEngineQueryLength(0);
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      setVisibleEngineQueryLength(activeEngineQuery.length);
      return;
    }

    let visibleCharacters = 0;
    const timer = window.setInterval(() => {
      visibleCharacters += 1;
      setVisibleEngineQueryLength(visibleCharacters);
      if (visibleCharacters >= activeEngineQuery.length) {
        window.clearInterval(timer);
      }
    }, engineQueryCharacterDelayMs);
    return () => window.clearInterval(timer);
  }, [activeEngineQuery]);

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

  useEffect(() => {
    let cancelled = false;
    Promise.all(labThumbnailIds.map((productId) => api.product(productId)))
      .then((products) => {
        if (!cancelled) {
          setLabThumbnails(new Map(products.map((product) => [product.product_id, product])));
        }
      })
      .catch(() => {
        // A missing photograph is decorative; the card still carries its full
        // text contract without one.
        if (!cancelled) setLabThumbnails(new Map());
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

  const selectEngineScenario = (index: number) => {
    replayTimers.current.forEach((timer) => window.clearTimeout(timer));
    replayTimers.current = [];
    setIsEnginePlaying(false);
    setVisibleEngineQueryLength(0);
    setActiveEngineScenarioIndex(index);
    setActiveEngineStep(0);
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
      }, (index + 1) * engineReplayStepDurationMs);
      replayTimers.current.push(timer);
    });
    replayTimers.current.push(window.setTimeout(() => {
      setIsEnginePlaying(false);
    }, engineSteps.length * engineReplayStepDurationMs));
  };

  return (
    <div className="page mosaic-labs-page labs-premium">
      <MosaicLabsTabs active="explore" />

      <MosaicLabsMasthead
        action={(
          <Link className="primary-button" href={shopScenarioHref(engineTraceMission)}>
            Open a Shop scenario <ArrowRight size={17} />
          </Link>
        )}
        deck="Follow a real request as it moves from intent to an evidence-backed recommendation."
        supportingText="Replay the system after a Code Editor repair."
        title={<>Retrieval observatory. <em>Grounded answers.</em></>}
      />

      <section
        className={`labs-engine labs-engine-board${isEnginePlaying ? " is-replaying" : ""}`}
        aria-busy={isEnginePlaying}
        aria-labelledby="labs-engine-title"
      >
        <header className="labs-engine-heading">
          <div>
            <h2 id="labs-engine-title">From request to grounded output.</h2>
            <p className="labs-engine-description">
              Select a stage or replay a validated fixture. Product records come
              from the catalog; the replay explains the system without claiming
              a fresh measured run.
            </p>
          </div>
        </header>

        <ol
          className={`labs-engine-rail${isEnginePlaying ? " is-replaying" : ""}`}
          aria-label="Retrieval and ranking stages"
        >
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

        <div className="labs-observatory-workspace" aria-live="polite">
          <aside className="labs-observatory-request">
            <header>
              <span>Request</span>
              <strong>Validated fixture</strong>
            </header>
            <div
              className={`labs-engine-query${isEngineQueryComplete ? " is-complete" : ""}`}
              aria-label="Replay query"
            >
              <Search size={17} aria-hidden="true" />
              <code aria-label={activeEngineQuery}>
                <span className="labs-engine-query-measure" aria-hidden="true">
                  {activeEngineQuery}
                </span>
                <span className="labs-engine-query-typed" aria-hidden="true">
                  {activeEngineQuery.slice(0, visibleEngineQueryLength)}
                  {!isEngineQueryComplete ? <i className="labs-engine-query-caret" /> : null}
                </span>
              </code>
            </div>
            <div
              className="labs-engine-query-presets"
              role="group"
              aria-label="Replay query examples"
            >
              {engineScenarios.map((scenario, index) => (
                <button
                  aria-label={`Use ${scenario.label} query: ${scenario.mission.query}`}
                  aria-pressed={index === activeEngineScenarioIndex}
                  className={index === activeEngineScenarioIndex ? "active" : ""}
                  key={scenario.id}
                  onClick={() => selectEngineScenario(index)}
                  type="button"
                >
                  {scenario.label}
                </button>
              ))}
            </div>
            <dl className="labs-observatory-request-facts">
              <div>
                <dt>Fixture</dt>
                <dd>{activeEngineScenario.mission.id}</dd>
              </div>
              <div>
                <dt>Target</dt>
                <dd>#{activeEngineScenario.mission.target_product_ids[0]}</dd>
              </div>
              <div>
                <dt>Expected techniques</dt>
                <dd>{activeEngineScenario.mission.expected_techniques.length}</dd>
              </div>
            </dl>
            <button
              className={`labs-engine-replay${
                isEngineQueryComplete && !isEnginePlaying ? " query-ready" : ""
              }`}
              disabled={isEnginePlaying}
              onClick={replayEngineJourney}
              type="button"
            >
              <Play size={15} fill="currentColor" />
              {isEnginePlaying
                ? `Replaying ${activeEngineStep + 1} of ${engineSteps.length}`
                : "Replay fixture"}
            </button>
          </aside>

          <section className="labs-observatory-candidates">
            <header className="labs-engine-products-heading">
              <span>{activeEngineVisual.productLabel}</span>
              <small>Canonical catalog fixture</small>
            </header>
            {engineEntries.length ? (
              <>
                <div className="labs-engine-products" aria-label="Candidate cohort">
                  {engineEntries.map(({ product, state }, index) => (
                    <figure
                      className={`labs-engine-product ${state.state}`}
                      data-product-id={product.product_id}
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
                  ))}
                </div>
                <div className="labs-observatory-shortlist">
                  <header>
                    <h3>Ranked shortlist</h3>
                    <span>{visibleEngineEntries.length} visible</span>
                  </header>
                  <ol>
                    {visibleEngineEntries.slice(0, 4).map(({ product, state }) => (
                      <li key={product.product_id}>
                        <span>{String(state.rank).padStart(2, "0")}</span>
                        <img src={productImage(product)} alt="" width={72} height={48} />
                        <div>
                          <strong>{product.model}</strong>
                          <small>{product.brand}</small>
                        </div>
                        <em>{state.label}</em>
                      </li>
                    ))}
                  </ol>
                </div>
              </>
            ) : (
              <p className="labs-engine-products-unavailable" role="status">
                {engineProductsError
                  ? `Catalog product records are unavailable: ${engineProductsError}`
                  : "Loading catalog product records..."}
              </p>
            )}
          </section>

          <aside
            className="labs-engine-spotlight labs-observatory-evidence"
            data-stage={activeEngine.step}
          >
            <header>
              <span>Evidence &amp; rationale</span>
              <small>{activeEngine.title}</small>
            </header>
            {leadingEngineEntry ? (
              <figure>
                <img
                  src={productImage(leadingEngineEntry.product)}
                  alt={leadingEngineEntry.product.title}
                  width={1200}
                  height={800}
                />
                <figcaption>
                  <small>Current leader</small>
                  <strong>{leadingEngineEntry.product.model}</strong>
                  <span>{leadingEngineEntry.state.label}</span>
                </figcaption>
              </figure>
            ) : null}
            <div className="labs-engine-spotlight-copy">
              {activeEngine.owner ? (
                <p className="labs-engine-stage-owner">
                  {stageDetails[activeEngine.owner].label}
                </p>
              ) : null}
              <h3>{activeEngineVisual.title}</h3>
              <p>{activeEngineVisual.copy}</p>
              <ul aria-label={`${activeEngine.title} implementation details`}>
                {activeEngineMechanics.map((mechanic) => (
                  <li key={mechanic}><code>{mechanic}</code></li>
                ))}
              </ul>
            </div>
            <Link href={retrievalExampleHref(activeEngineScenario.mission)}>
              Inspect the trace <ArrowRight size={15} />
            </Link>
          </aside>
        </div>

        <footer className="labs-observatory-telemetry" aria-label="Replay telemetry">
          <div>
            <span>Pipeline state</span>
            <strong>{isEnginePlaying ? "Replay in progress" : activeEngine.title}</strong>
          </div>
          <div>
            <span>Visible cohort</span>
            <strong>{visibleEngineEntries.length} of {engineEntries.length || engineProductIds.length}</strong>
          </div>
          <div>
            <span>Active stage</span>
            <strong>{activeEngineStep + 1} / {engineSteps.length}</strong>
          </div>
          <div>
            <span>Top signal</span>
            <strong>{activeEngineMechanics[0] ?? "Catalog request"}</strong>
          </div>
          <Link href={retrievalExampleHref(activeEngineScenario.mission)}>
            Open trace <ArrowRight size={14} />
          </Link>
        </footer>
      </section>

      <section
        className="labs-retrieval-contrasts"
        aria-labelledby="labs-retrieval-contrasts-title"
      >
        <header className="labs-retrieval-contrasts-heading">
          <div>
            <h2 id="labs-retrieval-contrasts-title">Where one retrieval method stops being enough.</h2>
          </div>
          <p>
            These are optional, read-only traces. They expose the candidate
            evidence behind the same Shop scenarios participants validate.
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
                  Inspect the trace <ArrowRight size={15} />
                </Link>
              </article>
            );
          })}
        </div>
      </section>

      <section className="labs-core" aria-labelledby="labs-core-title">
        <header className="labs-section-heading">
          <div>
            <h2 id="labs-core-title">Three lenses on the same system.</h2>
          </div>
          <p>
            Author the repair in Code Editor. Validate its customer-visible
            effect in Shop. Return here only to inspect the system evidence.
          </p>
        </header>

        <div className="labs-stage-grid">
          {coreMosaicLabs.map((lab) => {
            const stage = stageDetails[lab.stage];
            const Icon = stage.Icon;
            const runs = [lab, ...checksFor(lab)];
            const thumbnail = labThumbnails.get(labIllustrationId(lab));
            return (
              <article className={`labs-stage-card ${lab.stage}`} id={lab.id} key={lab.id}>
                {thumbnail ? (
                  <figure className="labs-stage-thumbnail">
                    <img
                      src={productImage(thumbnail)}
                      alt={thumbnail.title}
                      width={640}
                      height={280}
                      loading="lazy"
                      decoding="async"
                    />
                    <figcaption>
                      <small>Pictured</small>
                      <strong>{thumbnail.model}</strong>
                    </figcaption>
                  </figure>
                ) : null}
                <div className="labs-stage-content">
                  <header className="labs-stage-heading">
                    <Icon size={21} />
                    <div>
                      <p>{stage.label}</p>
                      <h3>{stage.observation}</h3>
                    </div>
                  </header>

                  <div className="labs-stage-question">
                    <span>Inspect this</span>
                    <strong>{stage.question}</strong>
                  </div>

                  <p className="labs-stage-shop-proof">
                    <span>Shop evidence</span>
                    {lab.expected_outcome}
                  </p>

                  <p className="labs-stage-techniques">
                    {lab.expected_techniques.map((technique) => (
                      <span key={technique}>{labelTechnique(technique)}</span>
                    ))}
                  </p>

                  <details className="labs-scenario-menu">
                    <summary>{runs.length} related Shop scenarios</summary>
                    <div>
                      {runs.map((run) => (
                        <Link href={shopScenarioHref(run)} key={run.id}>
                          <code>{run.query}</code>
                          <ArrowRight size={15} />
                        </Link>
                      ))}
                    </div>
                  </details>

                  <footer>
                    <Link href={shopScenarioHref(lab)}>
                      Open in Shop <ArrowRight size={16} />
                    </Link>
                  </footer>
                </div>
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

      {hasHnswAdvancedLab ? (
        <details className="labs-advanced">
          <summary>
            <span>
              <Activity size={18} />
              <strong>Advanced diagnostics</strong>
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
            <Link className="secondary-button" href="/mosaic-labs/hnsw">
              Open HNSW at scale <ArrowRight size={16} />
            </Link>
          </div>
        </details>
      ) : null}
    </div>
  );
}
