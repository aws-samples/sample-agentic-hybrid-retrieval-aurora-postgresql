import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Database,
  FileSearch,
  GitCompareArrows,
  Network,
  ScanSearch,
  ShieldCheck,
  Sparkles,
  Wrench,
} from "lucide-react";
import { Link } from "wouter";
import {
  mosaicLabManifest,
  selfPacedMosaicLabMissions,
  timedMosaicLabMissions,
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
  recover: {
    label: "Recover",
    title: "Protect exact names and imperfect input",
    detail: "Keep identity precise with full-text search, then make typo recovery an explicit, inspectable candidate source.",
    Icon: ScanSearch,
  },
  retrieve: {
    label: "Retrieve",
    title: "Understand the request without relaxing constraints",
    detail: "HNSW expands semantic intent while SQL keeps price, stock, category, and decisive attributes authoritative.",
    Icon: Database,
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

function missionHref(mission: MosaicLabMission) {
  return `/labs/retrieval?mission=${encodeURIComponent(mission.id)}`;
}

function checkpointLabel(mission: MosaicLabMission) {
  switch (mission.checkpoint) {
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
  const coreMissions = timedMosaicLabMissions;
  const selfPacedMissions = selfPacedMosaicLabMissions;

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
            <Link className="primary-button" href={missionHref(coreMissions[0])}>
              Inspect a golden query <ArrowRight size={17} />
            </Link>
            <Link className="text-link" href="/labs/performance">
              Open performance lane <Activity size={16} />
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

      <section className="mosaic-labs-journey" aria-labelledby="mosaic-labs-journey-title">
        <div className="mosaic-labs-section-heading">
          <div>
            <p className="eyebrow">Core path</p>
            <h2 id="mosaic-labs-journey-title">One story from request to cited answer.</h2>
          </div>
          <p>
            The Workshop Studio owns the guided steps and code editor. This
            surface holds the shared mission contract and the evidence each
            stage must produce.
          </p>
        </div>

        <ol className="mosaic-lab-mission-list">
          {coreMissions.map((mission, index) => {
            const stage = stageDetails[mission.stage];
            const Icon = stage.Icon;

            return (
              <li key={mission.id}>
                <div className="mosaic-lab-mission-step">0{index + 1}</div>
                <div className="mosaic-lab-mission-stage">
                  <Icon size={19} aria-hidden="true" />
                  <span>{stage.label}</span>
                </div>
                <div className="mosaic-lab-mission-body">
                  <div>
                    <p className="mosaic-lab-mission-meta">
                      {mission.duration_minutes} min <span>{checkpointLabel(mission)}</span>
                    </p>
                    <h3>{mission.title}</h3>
                    <p>{mission.expected_outcome}</p>
                  </div>
                  <code>{mission.query}</code>
                </div>
                <div className="mosaic-lab-mission-proof">
                  <strong>Evidence to retain</strong>
                  <span>{mission.assertions.map((assertion) => assertion.replaceAll("_", " ")).join(" · ")}</span>
                </div>
                <Link className="mosaic-lab-mission-link" href={missionHref(mission)}>
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

      <section className="mosaic-labs-portable-contract" aria-label="Portable MCP tool contract">
        <div>
          <p className="eyebrow">Portable tool contract</p>
          <h2>One retrieval system, available to another agent host.</h2>
          <p>
            The instructor can expose the same bounded product discovery
            contract through stateless MCP after the cited answer is complete.
            It reuses the canonical API and retains every retrieval-run ID.
          </p>
        </div>
        <dl>
          <div>
            <dt><Network size={18} /> MCP 2026-07-28</dt>
            <dd>Stateless discovery and header-routable tool calls without transport sessions.</dd>
          </div>
          <div>
            <dt><FileSearch size={18} /> Three typed tools</dt>
            <dd>Search products, inspect product evidence, and replay the retrieval run.</dd>
          </div>
          <div>
            <dt><ShieldCheck size={18} /> Same trust boundary</dt>
            <dd>Read-only tools call the canonical API. Strands remains the Mosaic agent harness.</dd>
          </div>
        </dl>
      </section>

      {selfPacedMissions.length > 0 ? (
        <section className="mosaic-labs-advanced">
          <div>
            <p className="eyebrow">Self-paced lane</p>
            <h2>Run these on your own cluster, after the session.</h2>
            <p>
              Each one is a complete mission with the same contract and the same
              assertions as the timed three. They are off the clock, not out of
              the workshop: the operating point is measured here, not guessed.
            </p>
          </div>
          <ol className="mosaic-labs-self-paced-list">
            {selfPacedMissions.map((mission) => (
              <li key={mission.id}>
                <div>
                  <p className="mosaic-lab-mission-meta">
                    {mission.duration_minutes} min <span>{stageDetails[mission.stage].label}</span>
                  </p>
                  <h3>{mission.title}</h3>
                  <p>{mission.expected_outcome}</p>
                </div>
                <Link className="mosaic-lab-mission-link" href={missionHref(mission)}>
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
