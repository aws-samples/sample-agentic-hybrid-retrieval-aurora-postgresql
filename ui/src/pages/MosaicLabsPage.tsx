import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Database,
  FileText,
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
  type MosaicLabPlacement,
  type MosaicLabStage,
} from "../labMissions";

type StageDetail = {
  label: string;
  verb: string;
  title: string;
  detail: string;
  Icon: typeof ScanSearch;
};

const stageDetails: Record<MosaicLabStage, StageDetail> = {
  retrieve: {
    label: "Retrieve",
    verb: "Build the candidate universe",
    title: "Build hybrid retrieval",
    detail: "FTS, pg_trgm, HNSW, and SQL filters recover different kinds of relevance while preserving candidate provenance.",
    Icon: ScanSearch,
  },
  rank: {
    label: "Rank",
    verb: "Put candidates in order",
    title: "Fuse, rerank, and explain",
    detail: "RRF combines ordinal evidence, then Cohere Rerank reorders only a bounded pool without erasing where each candidate came from.",
    Icon: GitCompareArrows,
  },
  reason: {
    label: "Reason",
    verb: "Ground the recommendation",
    title: "Build the retrieval agent",
    detail: "Typed tools decompose the request, compare retrieved products, resolve evidence records, and compose citations that can be checked.",
    Icon: ShieldCheck,
  },
  optimize: {
    label: "Advanced",
    verb: "Measure the operating point",
    title: "Tune HNSW",
    detail: "Compare recall, latency, plans, and index configuration outside the required 60-minute path.",
    Icon: Activity,
  },
};

const placementByStage: Partial<Record<MosaicLabStage, MosaicLabPlacement>> = {
  retrieve: "lab-1",
  rank: "lab-2",
  reason: "lab-3",
};

function checksFor(lab: MosaicLabMission) {
  const placement = placementByStage[lab.stage];
  return supportingMosaicChecks.filter((check) => check.core && check.placement === placement);
}

function StageVisual({ stage }: { stage: MosaicLabStage }) {
  if (stage === "retrieve") {
    return (
      <div className="labs-retrieve-visual" aria-label="Hybrid candidate sources">
        <span>FTS</span>
        <span>pg_trgm</span>
        <span>pgvector</span>
        <strong>Eligible candidates</strong>
      </div>
    );
  }

  if (stage === "rank") {
    return (
      <div className="labs-rank-visual" aria-label="Ranking movement">
        <span>Lexical</span><i>01</i><b>RRF</b><i>02</i>
        <span>Semantic</span><i>04</i><b>Rerank</b><i>01</i>
      </div>
    );
  }

  return (
    <div className="labs-reason-visual" aria-label="Agent tool flow">
      <span>search_products()</span>
      <span>compare_products()</span>
      <span>get_product_evidence()</span>
      <strong>Cited answer</strong>
    </div>
  );
}

export function MosaicLabsPage() {
  const coreChecks = supportingMosaicChecks.filter((check) => check.core);
  const advancedLabs = supportingMosaicChecks.filter((check) => check.placement === "advanced-labs");
  const participantRuns = coreMosaicLabs.flatMap((lab) => [lab, ...checksFor(lab)]);

  return (
    <div className="page mosaic-labs-page labs-premium">
      <header className="labs-command-hero">
        <div className="labs-command-copy">
          <p className="eyebrow">DAT410 · Aurora PostgreSQL · Level 400</p>
          <h1>Mosaic Labs</h1>
          <p className="labs-command-lede">
            Build the retrieval system first. Then give its inspectable
            capabilities and evidence to the agent.
          </p>
          <div className="labs-command-actions">
            <Link className="primary-button" href={retrievalExampleHref(coreMosaicLabs[0])}>
              Start Lab 1 <ArrowRight size={17} />
            </Link>
            <span>3 labs · 8 participant runs · 40-45 minutes hands-on</span>
          </div>
          <dl className="labs-command-facts">
            <div>
              <dt>Catalog</dt>
              <dd>{mosaicLabManifest.corpus.catalog_products.toLocaleString()}</dd>
              <small>embedded products</small>
            </div>
            <div>
              <dt>Search engine</dt>
              <dd>Aurora</dd>
              <small>PostgreSQL + pgvector</small>
            </div>
            <div>
              <dt>Visual cohort</dt>
              <dd>{mosaicLabManifest.corpus.premium_visual_anchors}</dd>
              <small>premium products</small>
            </div>
          </dl>
        </div>

        <figure className="labs-command-media">
          <img
            src="/assets/images/mosaic/forma-ergonomic-studio.webp"
            alt="Mosaic ergonomic task chair in a warm studio"
            width={1200}
            height={1200}
          />
          <figcaption>
            <span><Database size={16} /> Production path</span>
            <strong>Candidate source → rank movement → evidence → citation</strong>
          </figcaption>
        </figure>
      </header>

      <nav className="labs-stage-switcher" aria-label="Mosaic lab stages">
        {coreMosaicLabs.map((lab, index) => {
          const stage = stageDetails[lab.stage];
          const Icon = stage.Icon;
          return (
            <a key={lab.id} href={`#${lab.id}`}>
              <span>0{index + 1}</span>
              <Icon size={19} />
              <strong>{stage.label}</strong>
              <small>{stage.verb}</small>
              <ArrowRight size={16} />
            </a>
          );
        })}
        <Link href="/labs/performance">
          <span>+</span>
          <Activity size={19} />
          <strong>Advanced</strong>
          <small>HNSW and evaluation</small>
          <ArrowRight size={16} />
        </Link>
      </nav>

      <section className="labs-core" aria-labelledby="labs-core-title">
        <header className="labs-section-heading">
          <div>
            <p className="eyebrow">Retrieve → Rank → Reason</p>
            <h2 id="labs-core-title">Progressively engineer one system.</h2>
          </div>
          <p>
            Every lab starts with a controlled failure, asks for one focused
            participant edit, and finishes with inspectable proof.
          </p>
        </header>

        <div className="labs-stage-grid">
          {coreMosaicLabs.map((lab, index) => {
            const stage = stageDetails[lab.stage];
            const Icon = stage.Icon;
            const controls = checksFor(lab);
            return (
              <article className={`labs-stage-card ${lab.stage}`} id={lab.id} key={lab.id}>
                <header>
                  <span>0{index + 1}</span>
                  <div>
                    <p><Icon size={15} /> {stage.label}</p>
                    <small>{lab.duration_minutes} min · {1 + controls.length} runs</small>
                  </div>
                </header>
                <div className="labs-stage-card-copy">
                  <h3>{stage.title}</h3>
                  <p>{stage.detail}</p>
                </div>
                <StageVisual stage={lab.stage} />
                <dl className="labs-repair-sequence">
                  <div>
                    <dt>Broken</dt>
                    <dd>{lab.participant_edit?.broken_state ?? "The stage does not satisfy its retrieval contract."}</dd>
                  </div>
                  <div>
                    <dt>Fix</dt>
                    <dd>{lab.participant_edit?.task ?? "Complete the focused participant edit."}</dd>
                  </div>
                  <div>
                    <dt>Prove</dt>
                    <dd>{lab.expected_outcome}</dd>
                  </div>
                </dl>
                <code>{lab.query}</code>
                <footer>
                  <Link href={retrievalExampleHref(lab)}>
                    Open Lab {index + 1} <ArrowRight size={15} />
                  </Link>
                  <span>{lab.canonical_query_id}</span>
                </footer>
              </article>
            );
          })}
        </div>
      </section>

      <section className="labs-query-deck" aria-labelledby="labs-query-title">
        <header className="labs-section-heading">
          <div>
            <p className="eyebrow">Eight participant runs</p>
            <h2 id="labs-query-title">Run the failure. Make the fix. Challenge it.</h2>
          </div>
          <p>
            Three repair anchors and five controls keep the session interactive
            while testing identity, eligibility, rank movement, and grounding.
          </p>
        </header>

        <ol>
          {participantRuns.map((run, index) => {
            const stage = stageDetails[run.stage];
            return (
              <li className={run.checkpoint === "repair" ? "repair" : ""} key={run.id}>
                <Link href={retrievalExampleHref(run)}>
                  <span className="labs-query-number">{String(index + 1).padStart(2, "0")}</span>
                  <div className="labs-query-copy">
                    <p>
                      {stage.label}
                      <small>{run.checkpoint === "repair" ? "Participant fix" : "Control"}</small>
                    </p>
                    <h3>{run.title}</h3>
                    <code>{run.query}</code>
                  </div>
                  <div className="labs-query-proof">
                    <strong>{run.canonical_query_id}</strong>
                    <span>{run.expected_outcome}</span>
                  </div>
                  <ArrowRight size={17} />
                </Link>
              </li>
            );
          })}
        </ol>
      </section>

      <section className="labs-architecture" aria-label="Inspectable architecture">
        <div>
          <Sparkles size={18} />
          <span>
            <strong>Candidate provenance</strong>
            <small>FTS, trigram, vector, and filters stay visible.</small>
          </span>
        </div>
        <div>
          <GitCompareArrows size={18} />
          <span>
            <strong>Ranking movement</strong>
            <small>RRF, reranker score, and final rank remain distinct.</small>
          </span>
        </div>
        <div>
          <FileText size={18} />
          <span>
            <strong>Resolvable evidence</strong>
            <small>Every final citation maps to a real evidence record.</small>
          </span>
        </div>
      </section>

      {advancedLabs.length > 0 ? (
        <section className="labs-advanced">
          <div>
            <p className="eyebrow">Advanced extension · optional</p>
            <h2>Tune the HNSW operating point with measured evidence.</h2>
            <p>
              Measure Recall@K, p50/p95 latency, plans, and index configuration
              without placing a benchmark on the required session path.
            </p>
          </div>
          <div className="labs-advanced-proof">
            <span><CheckCircle2 size={16} /> Exact-neighbor recall baseline</span>
            <span><CheckCircle2 size={16} /> Latency and plan evidence</span>
            <span><CheckCircle2 size={16} /> Corpus and index configuration</span>
          </div>
          <Link className="secondary-button" href="/labs/performance">
            Open advanced extension <Wrench size={16} />
          </Link>
        </section>
      ) : null}
    </div>
  );
}
