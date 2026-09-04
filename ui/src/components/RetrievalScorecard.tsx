import { AlertTriangle, Clock } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import { productBoundImage } from "../media";
import {
  PlaygroundDisclosure,
  PlaygroundFigure,
  PlaygroundFigures,
} from "./PlaygroundStage";
import type {
  RetrievalScorecardResponse,
  ScorecardAgentContracts,
  ScorecardEligibilityContracts,
  ScorecardProvenance,
  ScorecardRegressionAnchors,
  ScorecardRetrievalQuality,
  ScorecardStageAblation,
  ScorecardStageAblationQuery,
  ScorecardStageArm,
} from "../types";

/**
 * The Prove step: "did we fix the scenarios without weakening the system?"
 *
 * A system-quality artifact, not a participant grade -- one read of
 * `GET /api/scorecard`, rendered as five sections that are never conflated
 * (ruling in `docs/superpowers/specs/2026-08-27-prove-and-package-architecture.md`,
 * sections 7-10):
 *
 *   A. retrieval_quality       population Recall@10, MRR, nDCG@10
 *   B. regression_anchors      compact PASS/total over golden anchors
 *   C. eligibility_contracts   hard eligibility/filter fixtures
 *   D. agent_contracts         deterministic agent/evidence guarantees
 *   E. stage_ablation          what each retrieval stage contributes
 *
 * A and E are each gated on their own `attributed` flag -- two separate
 * committed artifacts, two separate measurements, so one can be pending
 * while the other is current. B, C, and D are deterministic pass/fail
 * contracts rather than population relevance judgments, so they render every
 * time this loads regardless of either artifact's attribution.
 */

//: The owner-specified, exact participant-facing pending string. Rendered
//: verbatim -- never paraphrased -- whenever `provenance.attributed` is false.
export const SCORECARD_PENDING_HEADLINE =
  "Metrics pending evaluation for this retrieval revision";

/**
 * Read a string field out of a loosely-typed scorecard row, never surfacing
 * `undefined`, `null`, or a non-string value as a label. The committed
 * artifact predates `query_text`/`concept_label`, so every caller of this
 * must be prepared for the field to be absent.
 */
function stringField(row: Record<string, unknown>, key: string): string | null {
  const value = row[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}

function numberField(row: Record<string, unknown>, key: string): string {
  const value = row[key];
  return typeof value === "number" ? value.toFixed(4) : "unavailable";
}

function integerField(row: Record<string, unknown>, key: string): number | null {
  const value = row[key];
  return typeof value === "number" && Number.isInteger(value) ? value : null;
}

function ScorecardSectionHeading({
  id,
  index,
  question,
  technicalName,
}: {
  id: string;
  index: string;
  question: string;
  technicalName: string;
}) {
  return (
    <header className="labs-scorecard-heading">
      <h3 id={id}>{index}. {question}</h3>
      <p>{technicalName}</p>
    </header>
  );
}

function PerQueryMetricsList({
  rows,
}: {
  rows: Array<Record<string, unknown>>;
}) {
  return (
    <ul className="labs-scorecard-per-query">
      {rows.map((row, index) => {
        const queryId = stringField(row, "query_id") ?? `row-${index}`;
        const queryText = stringField(row, "query_text");
        const conceptLabel = stringField(row, "concept_label");
        const productId = integerField(row, "representative_product_id");
        const image = productId === null ? null : productBoundImage(productId);
        return (
          <li className={image ? "has-product-image" : undefined} key={queryId}>
            {image ? (
              <img
                alt={`Representative product for ${queryText ?? queryId}`}
                src={image}
              />
            ) : null}
            <div>
              <span className="labs-scorecard-per-query-label">
                <span className="labs-scorecard-per-query-text">
                  {queryText ?? queryId}
                </span>
                {conceptLabel ? (
                  <em className="labs-scorecard-per-query-concept">
                    {conceptLabel}
                  </em>
                ) : null}
                {queryText ? (
                  <code className="labs-scorecard-per-query-id">{queryId}</code>
                ) : null}
              </span>
              <small>
                relevant found {numberField(row, "recall@10")} &middot; ordering{" "}
                {numberField(row, "ndcg@10")} &middot; first hit{" "}
                {numberField(row, "reciprocal_rank")}
              </small>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function RetrievalQualitySection({
  quality,
  provenance,
}: {
  quality: ScorecardRetrievalQuality;
  provenance: ScorecardProvenance;
}) {
  const explanationRows = Object.entries(quality.metric_explanations);
  return (
    <section
      className="labs-scorecard-section"
      aria-labelledby="scorecard-quality-title"
    >
      <ScorecardSectionHeading
        id="scorecard-quality-title"
        index="A"
        question="Can search find the right products?"
        technicalName="Release baseline"
      />
      {/* Whose measurement this is, before any number from it. The section used
          to open on the sample description alone, which let a participant read
          three release metrics as a verdict on the repair they had just made. */}
      <p
        className="labs-scorecard-sample"
        data-testid="scorecard-release-baseline-lead"
      >
        Measured by the maintainers at fingerprint{" "}
        <code>
          {provenance.retrieval_fingerprint
            ? provenance.retrieval_fingerprint.slice(0, 12)
            : "none recorded"}
        </code>
        , not a record of your repairs.
      </p>
      <p className="labs-scorecard-sample">{quality.sample_description}</p>

      {provenance.attributed ? (
        <PlaygroundFigures label="Retrieval quality metrics">
          <PlaygroundFigure
            label="Relevant products found (Recall@10)"
            value={quality.recall_at_10.toFixed(4)}
            detail={quality.metric_explanations["recall@10"]}
          />
          <PlaygroundFigure
            label="First relevant result (MRR)"
            value={quality.mrr.toFixed(4)}
            detail={quality.metric_explanations.mrr}
          />
          <PlaygroundFigure
            label="Top-10 ordering quality (nDCG@10)"
            value={quality.ndcg_at_10.toFixed(4)}
            detail={quality.metric_explanations["ndcg@10"]}
          />
        </PlaygroundFigures>
      ) : (
        <div
          className="labs-scorecard-pending"
          role="status"
          data-testid="scorecard-metrics-pending"
        >
          <Clock aria-hidden="true" size={18} />
          <div>
            <strong>{SCORECARD_PENDING_HEADLINE}</strong>
            <p>
              The three search-quality scores are held back until they are
              measured again on the code that is running now.
            </p>
          </div>
        </div>
      )}

      {!provenance.attributed ? (
        <dl
          className="labs-scorecard-metric-explanations"
          aria-label="What each withheld metric means"
        >
          {explanationRows.map(([name, text]) => (
            <div key={name}>
              <dt>{name}</dt>
              <dd>{text}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      <PlaygroundDisclosure
        label="Where these numbers come from"
        hint={
          provenance.attributed
            ? "measured on the code running now"
            : "why they are held back"
        }
      >
        <p data-testid="scorecard-attribution-note">
          {provenance.attribution_note}
        </p>
        <dl className="labs-profile">
          <div>
            <dt>measured on code version</dt>
            <dd className="mono">
              {provenance.source_revision ?? "none recorded"}
            </dd>
          </div>
          <div>
            <dt>uncommitted changes when measured</dt>
            <dd className="mono">{String(provenance.source_worktree_dirty)}</dd>
          </div>
          <div>
            <dt>code version running now</dt>
            <dd className="mono">
              {provenance.current_source_revision ?? "unresolved"}
            </dd>
          </div>
          <div>
            <dt>measured at</dt>
            <dd className="mono">{provenance.measured_at}</dd>
          </div>
          {/* Two facts a baseline has to keep apart: when it was measured, and
              when this page read it. A baseline rendered months later must not
              read as a measurement taken now. */}
          <div>
            <dt>served at</dt>
            <dd className="mono">{provenance.served_at}</dd>
          </div>
          <div>
            <dt>artifact kind</dt>
            <dd className="mono">{provenance.artifact_kind}</dd>
          </div>
        </dl>
      </PlaygroundDisclosure>

      {quality.per_query_metrics.length ? (
        <PlaygroundDisclosure
          label="See every search"
          hint={`${quality.per_query_metrics.length} searches`}
        >
          <PerQueryMetricsList rows={quality.per_query_metrics} />
        </PlaygroundDisclosure>
      ) : null}

      {quality.excluded_agent_contract_query_ids.length ? (
        <p className="labs-scorecard-exclusion">
          {quality.sample_size} of the {quality.canonical_query_count} test
          searches are scored below.{" "}
          <code>{quality.excluded_agent_contract_query_ids.join(", ")}</code>{" "}
          {quality.excluded_agent_contract_query_ids.length === 1 ? "is" : "are"}{" "}
          not: {quality.excluded_agent_contract_query_ids.length === 1
            ? "it is an agent conversation"
            : "they are agent conversations"}{" "}
          with several steps (planning, comparing, looking up evidence, and
          writing a cited answer) rather than one search, so a search score
          would measure the wrong thing. Section D checks{" "}
          {quality.excluded_agent_contract_query_ids.length === 1 ? "it" : "them"}{" "}
          instead.
        </p>
      ) : null}
    </section>
  );
}

function RegressionAnchorsSection({
  anchors,
}: {
  anchors: ScorecardRegressionAnchors;
}) {
  // A complete N/N is only "good" while it describes the running revision.
  // The harness never writes a failing check, so N/N alone proves nothing about
  // now -- it reports what held at the revision that was measured.
  const allPassed =
    anchors.total > 0 &&
    anchors.passed === anchors.total &&
    anchors.verified_for_running_revision;
  return (
    <section
      className="labs-scorecard-section"
      aria-labelledby="scorecard-anchors-title"
    >
      <ScorecardSectionHeading
        id="scorecard-anchors-title"
        index="B"
        question="Did known critical examples still pass?"
        technicalName="Known-good checks"
      />
      <PlaygroundFigures label="Known-good checks">
        <PlaygroundFigure
          label="Critical checks passed"
          value={`${anchors.passed} / ${anchors.total}`}
          tone={allPassed ? "good" : "warn"}
          detail={
            anchors.verified_for_running_revision
              ? "Did a behavior the labs depend on stop working? Counted separately from the search-quality scores."
              : "Checked on the code version that was measured, not the one running now. Measure again to make this current."
          }
        />
      </PlaygroundFigures>
      <PlaygroundDisclosure
        label="See the checks"
        hint={`${anchors.anchors.length} checks`}
      >
        <ul className="labs-contracts">
          {anchors.anchors.map((anchor) => (
            <li key={`${anchor.query_id}-${anchor.product_id}-${anchor.type}`}>
              <span className="labs-scorecard-anchor-label">
                <span className="labs-scorecard-anchor-text">
                  {anchor.query_text ?? anchor.query_id}
                </span>
                {anchor.concept_label ? (
                  <em className="labs-scorecard-anchor-concept">
                    {anchor.concept_label}
                  </em>
                ) : null}
                {anchor.query_text ? (
                  <code className="labs-scorecard-anchor-id">
                    {anchor.query_id}
                  </code>
                ) : null}
              </span>
              <b>{anchor.type.replaceAll("_", " ")}</b>
              <small>
                product {anchor.product_id}
                {anchor.k ? `, top ${anchor.k}` : ""}
              </small>
            </li>
          ))}
        </ul>
      </PlaygroundDisclosure>
    </section>
  );
}

function EligibilityContractsSection({
  contracts,
}: {
  contracts: ScorecardEligibilityContracts;
}) {
  return (
    <section
      className="labs-scorecard-section"
      aria-labelledby="scorecard-eligibility-title"
    >
      <ScorecardSectionHeading
        id="scorecard-eligibility-title"
        index="C"
        question="Did hard filters stay enforced?"
        technicalName="Filter guarantees"
      />
      <PlaygroundFigures label="Filter guarantees">
        <PlaygroundFigure
          label={contracts.held === null ? "Filter checks (unverified)" : "Filter checks held"}
          value={String(contracts.fixture_count)}
          tone={contracts.held === true ? "good" : "warn"}
          detail={
            contracts.held === null
              ? "Not yet checked on the code running now. The count is real; the pass or fail needs a fresh measurement."
              : "Did any result slip past a hard filter such as price, stock, or model? A pass-or-fail check, kept separate from the search-quality scores."
          }
        />
      </PlaygroundFigures>
      <PlaygroundDisclosure
        label="See the filter checks"
        hint={`${contracts.fixture_query_ids.length} searches`}
      >
        <p className="labs-contract-note">{contracts.description}</p>
        <p>
          <code>{contracts.fixture_query_ids.join(", ")}</code>
        </p>
      </PlaygroundDisclosure>
    </section>
  );
}

function AgentContractsSection({
  contracts,
}: {
  contracts: ScorecardAgentContracts;
}) {
  const assertionCount = contracts.guarantees.reduce(
    (total, guarantee) => total + guarantee.assertion_names.length,
    0,
  );
  return (
    <section
      className="labs-scorecard-section"
      aria-labelledby="scorecard-agent-title"
    >
      <ScorecardSectionHeading
        id="scorecard-agent-title"
        index="D"
        question="Did the agent stay inside its evidence boundaries?"
        technicalName="Evidence rules the agent follows"
      />
      <p className="labs-contract-note">
        Rules the agent must follow on every run. Each rule and its failure
        condition is read from the code that enforces it, not written for this
        page. No search score and no AI judge is used here.
      </p>
      <ul className="labs-contracts">
        {contracts.guarantees.map((guarantee) => (
          <li key={guarantee.key}>
            <code>{guarantee.label}</code>
            <b>
              {guarantee.fixture_count != null
                ? `${guarantee.fixture_count} tools`
                : `${guarantee.assertion_names.length} checks`}
            </b>
            <small>{guarantee.description}</small>
          </li>
        ))}
      </ul>
      <PlaygroundDisclosure
        label="View what would make each guarantee fail"
        hint={`${assertionCount} failure conditions`}
      >
        <ul className="labs-contracts">
          {contracts.guarantees.flatMap((guarantee) =>
            guarantee.assertion_names.map((name, index) => (
              <li key={`${guarantee.key}-${name}`}>
                <code>{name}</code>
                <small>{guarantee.falsifiers[index]}</small>
              </li>
            )),
          )}
        </ul>
      </PlaygroundDisclosure>
    </section>
  );
}

function StageArmList({
  arms,
  totalQueries,
}: {
  arms: ScorecardStageArm[];
  totalQueries: number;
}) {
  const armLanguage: Record<
    ScorecardStageArm["key"],
    { title: string; purpose: string }
  > = {
    semantic_only: {
      title: "Meaning match only",
      purpose: "What meaning match finds on its own, with no exact terms, close spelling, combining, or reranking.",
    },
    rrf_fused_no_rerank: {
      title: "All three search methods combined",
      purpose: "The order produced once exact terms, close spelling, and meaning match are combined.",
    },
    rrf_fused_reranked: {
      title: "Combined, then reranked",
      purpose: "The order shoppers actually see: the reranker reorders the same combined candidate pool.",
    },
  };

  return (
    <ul className="labs-ablation-arms">
      {arms.map((arm) => {
        const language = armLanguage[arm.key];
        return (
          <li key={arm.key}>
            <header>
              <h4>{language.title}</h4>
              <code>{arm.label}</code>
              <p>{language.purpose}</p>
            </header>
            <dl>
              <div>
                <dt>
                  <span>Relevant products in the top 10</span>
                  <small>Recall@10</small>
                </dt>
                <dd>{arm.recall_at_10.toFixed(4)}</dd>
              </div>
              <div>
                <dt>
                  <span>First relevant result</span>
                  <small>MRR</small>
                </dt>
                <dd>{arm.mrr.toFixed(4)}</dd>
              </div>
              <div>
                <dt>
                  <span>Top-10 ordering quality</span>
                  <small>nDCG@10</small>
                </dt>
                <dd>{arm.ndcg_at_10.toFixed(4)}</dd>
              </div>
            </dl>
            <p className="labs-ablation-spread">
              Across individual searches, the top-10 ordering score ran from{" "}
              {arm.ndcg_at_10_min.toFixed(4)} to {arm.ndcg_at_10_max.toFixed(4)}, with a
              spread of {arm.ndcg_at_10_stdev.toFixed(4)}. Best ordering on{" "}
              {arm.ndcg_at_10_query_wins} of {totalQueries} searches.
            </p>
            <p className="labs-ablation-source">{arm.description}</p>
          </li>
        );
      })}
    </ul>
  );
}

function StageAblationPerQueryList({
  rows,
  arms,
}: {
  rows: ScorecardStageAblationQuery[];
  arms: ScorecardStageArm[];
}) {
  const armTitles: Record<ScorecardStageArm["key"], string> = {
    semantic_only: "Meaning match only",
    rrf_fused_no_rerank: "All three search methods combined",
    rrf_fused_reranked: "Combined, then reranked",
  };

  return (
    <ul className="labs-scorecard-per-query">
      {rows.map((row) => (
        <li key={row.query_id}>
          <span className="labs-scorecard-per-query-label">
            <span className="labs-scorecard-per-query-text">{row.query_text}</span>
            <code className="labs-scorecard-per-query-id">{row.query_id}</code>
          </span>
          <div className="labs-ablation-query-metrics">
            {arms
              .map((arm) => {
                const value = row.ndcg_at_10[arm.key];
                return `${armTitles[arm.key]}: ${
                  typeof value === "number" ? value.toFixed(4) : "unavailable"
                } ordering score`;
              })
              .map((label) => <span key={label}>{label}</span>)}
          </div>
          <small>
            Relevant products in the candidate pool: {row.found_in_pool} of{" "}
            {row.relevant_count}
          </small>
        </li>
      ))}
    </ul>
  );
}

function StageAblationSection({ ablation }: { ablation: ScorecardStageAblation }) {
  const totalQueries = ablation.per_query.length;
  return (
    <section
      className="labs-scorecard-section"
      aria-labelledby="scorecard-ablation-title"
    >
      <ScorecardSectionHeading
        id="scorecard-ablation-title"
        index="E"
        question="What did each ranking step add?"
        technicalName="Step-by-step comparison"
      />
      <p className="labs-scorecard-intro">
        The same test searches are scored three ways so that one step changes at
        a time: meaning match on its own, all three search methods combined, and
        the combined list after reranking.
      </p>
      <p className="labs-scorecard-sample">
        <strong>Small sample:</strong> {ablation.spread_note}
      </p>

      {ablation.attributed ? (
        <>
          <PlaygroundFigures label="Candidate pool limits before reranking">
            <PlaygroundFigure
              label="Relevant products available to rerank"
              value={ablation.candidate_recall_ceiling.pool_recall_ceiling.toFixed(4)}
              detail={ablation.candidate_recall_ceiling.description}
            />
            <PlaygroundFigure
              label="Relevant products retrieval missed"
              value={String(
                ablation.candidate_recall_ceiling.judged_relevant_never_fetched,
              )}
              tone={
                ablation.candidate_recall_ceiling.judged_relevant_never_fetched === 0
                  ? "good"
                  : "warn"
              }
              detail="Summed across every scored search: products graded relevant that never entered the candidate pool, so reranking could never surface them."
            />
          </PlaygroundFigures>

          <StageArmList arms={ablation.arms} totalQueries={totalQueries} />

          {totalQueries ? (
            <PlaygroundDisclosure
              label="Compare every search across the three versions"
              hint={`${totalQueries} searches, ordering score shown`}
            >
              <StageAblationPerQueryList rows={ablation.per_query} arms={ablation.arms} />
            </PlaygroundDisclosure>
          ) : null}
        </>
      ) : (
        <div
          className="labs-scorecard-pending"
          role="status"
          data-testid="stage-ablation-pending"
        >
          <Clock aria-hidden="true" size={18} />
          <div>
            <strong>{SCORECARD_PENDING_HEADLINE}</strong>
            <p>
              This comparison changes one ranking step at a time to show what it
              added, but the numbers stay hidden until the code running now is
              measured.
            </p>
          </div>
        </div>
      )}

      <PlaygroundDisclosure
        label="How this comparison was measured"
        hint={ablation.attributed ? "measured on the code running now" : "why this is held back"}
      >
        <p data-testid="stage-ablation-attribution-note">{ablation.attribution_note}</p>
        <dl className="labs-profile">
          <div>
            <dt>measured at</dt>
            <dd className="mono">{ablation.measured_at}</dd>
          </div>
          <div>
            <dt>scored searches</dt>
            <dd className="mono">{ablation.scored_query_count}</dd>
          </div>
        </dl>
      </PlaygroundDisclosure>
    </section>
  );
}

interface RetrievalScorecardProps {
  /**
   * Bumped by the caller when something upstream may have changed what this
   * baseline is being read against -- a completion proof finishing, which runs
   * the mission through the served path. Every other parent render leaves it
   * alone, so an unrelated re-render costs no request.
   */
  refreshKey?: number;
}

export function RetrievalScorecard({ refreshKey = 0 }: RetrievalScorecardProps) {
  const [data, setData] = useState<RetrievalScorecardResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    api
      .scorecard()
      .then((response) => {
        if (active) setData(response);
      })
      .catch((cause: unknown) => {
        if (active) {
          setError(
            cause instanceof Error ? cause.message : "The scorecard is unavailable",
          );
        }
      });
    return () => {
      active = false;
    };
  }, [refreshKey]);

  if (error) {
    return (
      <p className="labs-disclosure-error" role="alert">
        <AlertTriangle aria-hidden="true" size={16} />
        {error}
      </p>
    );
  }
  if (!data) {
    return <p role="status">Loading the saved evaluation results.</p>;
  }

  return (
    <div className="labs-scorecard">
      <RetrievalQualitySection
        quality={data.retrieval_quality}
        provenance={data.provenance}
      />
      <RegressionAnchorsSection anchors={data.regression_anchors} />
      <EligibilityContractsSection contracts={data.eligibility_contracts} />
      <AgentContractsSection contracts={data.agent_contracts} />
      <StageAblationSection ablation={data.stage_ablation} />
    </div>
  );
}
