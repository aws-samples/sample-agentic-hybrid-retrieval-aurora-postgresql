import {
  Activity,
  ArrowRight,
  CheckCircle2,
  FileSearch,
  GitCompareArrows,
  ScanSearch,
  ShieldCheck,
  Sparkles,
  Wrench,
} from "lucide-react";
import { Link } from "wouter";
import {
  coreMosaicLabs,
  mosaicLabManifest,
  retrievalExampleHref,
  supportingMosaicChecks,
  type MosaicLabMission,
  type MosaicLabStage,
} from "../labMissions";

type StageDetail = {
  label: string;
  title: string;
  detail: string;
  Icon: typeof ScanSearch;
};

const stageDetails: Record<MosaicLabStage, StageDetail> = {
  retrieve: {
    label: "Retrieve",
    title: "Build hybrid retrieval",
    detail: "FTS, pg_trgm, and HNSW construct an inspectable candidate universe while SQL keeps hard constraints authoritative.",
    Icon: ScanSearch,
  },
  rank: {
    label: "Rank",
    title: "Make the final order reviewable",
    detail: "RRF fuses independent candidate ranks. Cohere Rerank then orders only the bounded pool without erasing provenance.",
    Icon: GitCompareArrows,
  },
  reason: {
    label: "Reason",
    title: "Answer only from bounded evidence",
    detail: "The agent uses typed, read-only retrieval tools and returns cited catalog sources that can be challenged.",
    Icon: ShieldCheck,
  },
  optimize: {
    label: "Optimize",
    title: "Measure the operating point",
    detail: "Treat index choice as a workload decision, with recalled results and measured latency carried beside the configuration.",
    Icon: Activity,
  },
};

function checkpointLabel(check: MosaicLabMission) {
  switch (check.checkpoint) {
    case "repair":
      return "Repair checkpoint";
    case "comparison":
      return "Comparison checkpoint";
    case "advanced":
      return "Advanced lane";
    default:
      return "Baseline";
  }
}

export function MosaicLabsPage() {
  const labOneChecks = supportingMosaicChecks.filter((check) => check.placement === "lab-1");
  const advancedLabs = supportingMosaicChecks.filter((check) => check.placement === "advanced-labs");

  return (
    <div className="page mosaic-labs-page">
      <header className="mosaic-labs-hero">
        <div>
          <p className="eyebrow">Aurora PostgreSQL</p>
          <h1>Mosaic Labs</h1>
          <p className="mosaic-labs-lede">
            Build an agentic retrieval system that earns confidence one
            inspectable decision at a time.
          </p>
          <dl className="mosaic-labs-facts">
            <div>
              <dt>Session</dt>
              <dd>{mosaicLabManifest.session.total_minutes} minutes</dd>
            </div>
            <div>
              <dt>Catalog</dt>
              <dd>{mosaicLabManifest.corpus.catalog_products.toLocaleString()} products</dd>
            </div>
            <div>
              <dt>Visual anchors</dt>
              <dd>{mosaicLabManifest.corpus.premium_visual_anchors} premium products</dd>
            </div>
          </dl>
          <div className="mosaic-labs-actions">
            <Link className="primary-button" href={retrievalExampleHref(coreMosaicLabs[0])}>
              Start Lab 1 <ArrowRight size={17} />
            </Link>
            <Link className="text-link" href="/labs/performance">
              Open optional HNSW lab <Activity size={16} />
            </Link>
          </div>
        </div>

        <figure>
          <img
            src="/assets/images/mosaic/forma-ergonomic-studio.webp"
            alt="Mosaic ergonomic task chair in a warm studio"
          />
          <figcaption>
            <FileSearch size={15} />
            <span>Candidate source, rank, rerank score, final order, and source revision remain visible.</span>
          </figcaption>
        </figure>
      </header>

      <nav className="mosaic-labs-stage-progress" aria-label="Workshop stages">
        <ol>
          {coreMosaicLabs.map((lab, index) => (
            <li key={lab.id}>
              <span>0{index + 1}</span>
              <strong>{stageDetails[lab.stage].label}</strong>
              <small>{lab.title.replace(/^Lab \d - /, "")}</small>
            </li>
          ))}
        </ol>
      </nav>

      <section className="mosaic-labs-journey" aria-labelledby="mosaic-labs-journey-title">
        <div className="mosaic-labs-section-heading">
          <div>
            <p className="eyebrow">Core path</p>
            <h2 id="mosaic-labs-journey-title">One story from request to cited answer.</h2>
          </div>
          <p>
            The Workshop Studio owns the guided steps and code editor. This
            surface holds the shared lab contract and the evidence each
            stage must produce.
          </p>
        </div>

        <ol className="mosaic-lab-mission-list">
          {coreMosaicLabs.map((lab, index) => {
            const stage = stageDetails[lab.stage];
            const Icon = stage.Icon;

            return (
              <li key={lab.id}>
                <div className="mosaic-lab-mission-step">0{index + 1}</div>
                <div className="mosaic-lab-mission-stage">
                  <Icon size={19} aria-hidden="true" />
                  <span>{stage.label}</span>
                </div>
                <div className="mosaic-lab-mission-body">
                  <div>
                    <p className="mosaic-lab-mission-meta">
                      {lab.duration_minutes} min <span>{stage.label}</span>
                    </p>
                    <h3>{lab.title}</h3>
                    <p>{stage.detail}</p>
                  </div>
                  <code>{lab.query}</code>
                </div>
                <div className="mosaic-lab-mission-proof">
                  <strong>Evidence to retain</strong>
                  <span>{lab.assertions.map((assertion) => assertion.replaceAll("_", " ")).join(" · ")}</span>
                </div>
                <Link className="mosaic-lab-mission-link" href={retrievalExampleHref(lab)}>
                  Inspect <ArrowRight size={15} />
                </Link>
              </li>
            );
          })}
        </ol>
      </section>

      <section className="mosaic-labs-rank-contract" aria-label="Ranking contract">
        <div>
          <p className="eyebrow">Ranking contract</p>
          <h2>Candidate generation and final order are different decisions.</h2>
          <p>
            Aurora PostgreSQL owns full-text, fuzzy, semantic, and filtered
            candidate generation. RRF combines rank positions. Cohere Rerank
            compares only the bounded fused pool, and the agent reasons over
            those source-backed results.
          </p>
        </div>
        <dl>
          <div>
            <dt><Sparkles size={18} /> Candidate signals</dt>
            <dd>FTS, pg_trgm, and HNSW rank and score remain independent.</dd>
          </div>
          <div>
            <dt><GitCompareArrows size={18} /> Ordering evidence</dt>
            <dd>RRF rank, Cohere Rerank score, and final rank stay distinct.</dd>
          </div>
          <div>
            <dt><ShieldCheck size={18} /> Answer boundary</dt>
            <dd>Citations include a catalog source URI and its source revision.</dd>
          </div>
        </dl>
      </section>

      <section className="mosaic-labs-checkpoints" aria-labelledby="mosaic-labs-checkpoints-title">
        <div>
          <p className="eyebrow">Lab 1 checkpoints</p>
          <h2 id="mosaic-labs-checkpoints-title">Candidate quality has more than one failure mode.</h2>
          <p>
            Typo recovery is the implementation repair. Exact identity and
            semantic eligibility are fast controls inside the same required
            lab, not separate workshop destinations.
          </p>
        </div>
        <ol className="mosaic-labs-checkpoint-list">
          {labOneChecks.map((check) => (
            <li key={check.id}>
              <div>
                <p className="mosaic-lab-mission-meta">
                  {checkpointLabel(check)} <span>{check.duration_minutes} min within Lab 1</span>
                </p>
                <h3>{check.title}</h3>
                <p>{check.expected_outcome}</p>
              </div>
              <Link className="mosaic-lab-mission-link" href={retrievalExampleHref(check)}>
                Inspect <ArrowRight size={15} />
              </Link>
            </li>
          ))}
        </ol>
      </section>

      {advancedLabs.length > 0 ? (
        <section className="mosaic-labs-advanced">
          <div>
            <p className="eyebrow">Advanced Labs (Optional)</p>
            <h2>Tune the HNSW operating point with measured evidence.</h2>
            <p>
              The required path proves the retrieval architecture. The optional
              performance lab measures recall, latency, plans, and configuration
              without consuming the 60-minute session.
            </p>
          </div>
          <ol className="mosaic-labs-checkpoint-list">
            {advancedLabs.map((check) => (
              <li key={check.id}>
                <div>
                  <p className="mosaic-lab-mission-meta">
                    Optional <span>{check.duration_minutes}+ min</span>
                  </p>
                  <h3>{check.title}</h3>
                  <p>{check.expected_outcome}</p>
                </div>
                <Link className="mosaic-lab-mission-link" href={retrievalExampleHref(check)}>
                  Inspect <ArrowRight size={15} />
                </Link>
              </li>
            ))}
          </ol>
          <div className="mosaic-labs-advanced-footer">
            <div className="mosaic-labs-advanced-checks">
              <span><CheckCircle2 size={16} /> Recall@K against exact neighbors</span>
              <span><CheckCircle2 size={16} /> p50, p95, index size, and build time</span>
              <span><CheckCircle2 size={16} /> Corpus, model, index, and filter configuration</span>
            </div>
            <Link className="secondary-button" href="/labs/performance">
              Inspect the advanced lane <Wrench size={16} />
            </Link>
          </div>
        </section>
      ) : null}
    </div>
  );
}
