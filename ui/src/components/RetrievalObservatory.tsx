import { ArrowRight, Play, Search } from "lucide-react";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { api } from "../api";
import {
  coreMosaicLabs,
  mosaicLabManifest,
  supportingMosaicChecks,
  type MosaicLabMission,
  type MosaicLabStage,
} from "../labMissions";
import { productImage } from "../media";
import type { ProductSummary } from "../types";

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

type EngineStep = {
  step: string;
  title: string;
  owner: MosaicLabStage | null;
  mechanics: string[];
  visual: Omit<EngineVisual, "visibleProductIds" | "productOrder">;
};

type RepairView = "before" | "after";

type FixtureOutcome = {
  eyebrow: string;
  title: string;
  detail: string;
  tags: string[];
};

const stageLabels: Record<MosaicLabStage, string> = {
  retrieve: "Retrieve",
  rank: "Rank",
  reason: "Reason",
  optimize: "Advanced",
};

const engineProductIds = [2, 3, 4, 5, 1, 17001];
const engineReplayStepDurationMs = 1650;

function requiredCoreLab(id: string): MosaicLabMission {
  const lab = coreMosaicLabs.find((candidate) => candidate.id === id);
  if (!lab) throw new Error(`Retrieval Observatory requires core lab ${id}.`);
  return lab;
}

function requiredSupportingCheck(id: string): MosaicLabMission {
  const check = supportingMosaicChecks.find((candidate) => candidate.id === id);
  if (!check) throw new Error(`Retrieval Observatory requires supporting check ${id}.`);
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
    mission: requiredCoreLab("typo-recovery"),
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

const engineSteps: EngineStep[] = [
  {
    step: "01",
    title: "Query",
    owner: null,
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
    owner: "retrieve",
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
    owner: "retrieve",
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
    owner: "rank",
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
    owner: "rank",
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
    owner: "reason",
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
  repairView: RepairView,
): EngineVisual {
  const visual = engineSteps[stepIndex].visual;
  let result: EngineVisual;
  if (stepIndex === 0) {
    result = { ...visual, visibleProductIds: engineProductIds, productOrder: engineProductIds };
  } else if (stepIndex === 1) {
    result = {
      ...visual,
      visibleProductIds: engineProductIds,
      productOrder: scenario.candidateOrder,
    };
  } else if (stepIndex === 2) {
    result = {
      ...visual,
      visibleProductIds: scenario.eligibleProductIds,
      productOrder: scenario.candidateOrder,
    };
  } else if (stepIndex === 3) {
    result = {
      ...visual,
      visibleProductIds: scenario.eligibleProductIds,
      productOrder: scenario.fusedOrder,
    };
  } else {
    result = {
      ...visual,
      visibleProductIds: scenario.rerankedOrder.slice(0, 3),
      productOrder: scenario.rerankedOrder,
    };
  }

  if (repairView !== "before" || !scenario.mission.participant_edit || stepIndex === 0) {
    return result;
  }

  const targetId = scenario.mission.target_product_ids[0];
  return {
    ...result,
    visibleProductIds: result.visibleProductIds.filter((id) => id !== targetId),
    productOrder: result.productOrder.filter((id) => id !== targetId),
  };
}

function engineProductState(
  product: ProductSummary,
  visual: EngineVisual,
  stepIndex: number,
  scenario: EngineScenario,
  repairView: RepairView,
) {
  const visible = visual.visibleProductIds.includes(product.product_id);
  const rank = visual.productOrder.indexOf(product.product_id) + 1;
  const isTarget = product.product_id === scenario.mission.target_product_ids[0];
  const isExactIdentity = scenario.id === "exact-identity" && isTarget;

  if (!visible && repairView === "before" && scenario.mission.participant_edit && isTarget) {
    return { label: "Target not recovered", state: "muted target-missed", rank };
  }
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
    label: isTarget ? "Evidence trace" : "Compared product",
    state: isTarget ? "featured" : "shortlist",
    rank,
  };
}

function fixtureOutcome(
  scenario: EngineScenario,
  repairView: RepairView,
  targetName: string,
): FixtureOutcome {
  const edit = scenario.mission.participant_edit;
  if (!edit) {
    return {
      eyebrow: "Illustrated fixture",
      title: "This replay explains the retrieval flow, not a measured run.",
      detail: "Choose Typo recovery to compare the disconnected and restored pg_trgm candidate path.",
      tags: ["No live result", `Target: ${targetName}`],
    };
  }

  if (repairView === "before") {
    return {
      eyebrow: "What this proves",
      title: `Before repair: ${targetName} is not recovered.`,
      detail: edit.broken_state,
      tags: ["Target absent", "pg_trgm pool: 0", "No trigram contribution"],
    };
  }

  return {
    eyebrow: "What this proves",
    title: `After repair: ${targetName} is recovered.`,
    detail: edit.fixed_state,
    tags: ["Target returned", "pg_trgm rank present", "RRF contribution present"],
  };
}

type RetrievalObservatoryProps = {
  onSelectExample: (id: string) => void;
};

export function RetrievalObservatory({ onSelectExample }: RetrievalObservatoryProps) {
  const [activeEngineStep, setActiveEngineStep] = useState(0);
  const [activeEngineScenarioIndex, setActiveEngineScenarioIndex] = useState(0);
  const [repairView, setRepairView] = useState<RepairView>("after");
  const [hasRunFixture, setHasRunFixture] = useState(false);
  const [isEnginePlaying, setIsEnginePlaying] = useState(false);
  const [engineProducts, setEngineProducts] = useState<ProductSummary[]>([]);
  const [engineProductsError, setEngineProductsError] = useState("");
  const replayTimers = useRef<number[]>([]);
  const activeEngineScenario = engineScenarios[activeEngineScenarioIndex];
  const activeEngine = engineSteps[activeEngineStep];
  const activeEngineVisual = engineVisualForScenario(
    activeEngineScenario,
    activeEngineStep,
    repairView,
  );
  const activeEngineMechanics = activeEngineStep === 0
    ? [`"${activeEngineScenario.mission.query}"`]
    : activeEngine.mechanics;
  const engineEntries = engineProducts.map((product) => ({
    product,
    state: engineProductState(
      product,
      activeEngineVisual,
      activeEngineStep,
      activeEngineScenario,
      repairView,
    ),
  }));
  const visibleEngineEntries = engineEntries
    .filter(({ state }) => state.state !== "muted")
    .sort((left, right) => left.state.rank - right.state.rank);
  const leadingEngineEntry = visibleEngineEntries[0] ?? null;
  const targetProduct = engineProducts.find(
    (product) => product.product_id === activeEngineScenario.mission.target_product_ids[0],
  );
  const targetName = targetProduct?.model
    ?? `Product #${activeEngineScenario.mission.target_product_ids[0]}`;
  const outcome = fixtureOutcome(activeEngineScenario, repairView, targetName);

  useEffect(() => () => {
    replayTimers.current.forEach((timer) => window.clearTimeout(timer));
  }, []);

  useEffect(() => {
    if (!hasRunFixture) return;
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
            cause instanceof Error ? cause.message : "Catalog product records are unavailable",
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [hasRunFixture]);

  const cancelReplay = () => {
    replayTimers.current.forEach((timer) => window.clearTimeout(timer));
    replayTimers.current = [];
    setIsEnginePlaying(false);
  };

  const selectEngineStep = (index: number) => {
    cancelReplay();
    setActiveEngineStep(index);
  };

  const selectEngineScenario = (index: number) => {
    cancelReplay();
    const scenario = engineScenarios[index];
    setActiveEngineScenarioIndex(index);
    setRepairView(scenario.mission.participant_edit ? "before" : "after");
    setActiveEngineStep(0);
    setHasRunFixture(false);
  };

  const replayEngineJourney = () => {
    cancelReplay();
    setHasRunFixture(true);
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
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

  const inspectLiveTrace = (id: string) => {
    onSelectExample(id);
    if (typeof window.requestAnimationFrame !== "function") return;
    window.requestAnimationFrame(() => {
      const trace = document.getElementById("retrieval-run");
      if (typeof trace?.scrollIntoView === "function") {
        trace.scrollIntoView({ block: "start" });
      }
    });
  };

  return (
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
              index < activeEngineStep ? "complete" : index === activeEngineStep ? "active" : ""
            }
            key={step.step}
          >
            <button
              aria-current={index === activeEngineStep ? "step" : undefined}
              disabled={!hasRunFixture}
              onClick={() => selectEngineStep(index)}
              type="button"
            >
              <span>{step.step}</span>
              <strong>{step.title}</strong>
              {step.owner ? <small>{stageLabels[step.owner]}</small> : null}
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
          <div className="labs-engine-query is-complete" aria-label="Replay query">
            <Search size={17} aria-hidden="true" />
            <code>{activeEngineScenario.mission.query}</code>
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
          {activeEngineScenario.mission.participant_edit ? (
            <div
              className="labs-observatory-repair-toggle"
              role="group"
              aria-label={`${activeEngineScenario.label} repair state`}
            >
              <span>Show</span>
              <button
                aria-pressed={repairView === "before"}
                className={repairView === "before" ? "active" : ""}
                onClick={() => setRepairView("before")}
                type="button"
              >
                Before repair
              </button>
              <button
                aria-pressed={repairView === "after"}
                className={repairView === "after" ? "active" : ""}
                onClick={() => setRepairView("after")}
                type="button"
              >
                After repair
              </button>
            </div>
          ) : null}
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
            className={`labs-engine-replay${!isEnginePlaying ? " query-ready" : ""}`}
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
          {!hasRunFixture ? (
            <p className="labs-observatory-candidates-empty" role="status">
              Awaiting fixture replay.
            </p>
          ) : engineEntries.length ? (
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
              <p className="labs-engine-stage-owner">{stageLabels[activeEngine.owner]}</p>
            ) : null}
            <h3>{activeEngineVisual.title}</h3>
            <p>{activeEngineVisual.copy}</p>
            <ul aria-label={`${activeEngine.title} implementation details`}>
              {activeEngineMechanics.map((mechanic) => (
                <li key={mechanic}><code>{mechanic}</code></li>
              ))}
            </ul>
          </div>
          <button
            className="labs-observatory-trace"
            onClick={() => inspectLiveTrace(activeEngineScenario.mission.id)}
            type="button"
          >
            Inspect live trace <ArrowRight size={15} />
          </button>
        </aside>
      </div>

      <footer className="labs-observatory-outcome" aria-live="polite">
        <div className="labs-observatory-outcome-copy">
          <span>{outcome.eyebrow}</span>
          <strong>{outcome.title}</strong>
          <p>{outcome.detail}</p>
        </div>
        <ul aria-label="Fixture outcome">
          {outcome.tags.map((tag) => <li key={tag}>{tag}</li>)}
        </ul>
        <button
          className="labs-observatory-trace"
          onClick={() => inspectLiveTrace(activeEngineScenario.mission.id)}
          type="button"
        >
          Open live trace <ArrowRight size={14} />
        </button>
      </footer>
    </section>
  );
}
