import { AlertTriangle, Clock } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
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
} from "../types";

/**
 * The Prove step: "did we fix the scenarios without weakening the system?"
 *
 * A system-quality artifact, not a participant grade -- one read of
 * `GET /api/scorecard`, rendered as four sections that are never conflated
 * (ruling in `docs/superpowers/specs/2026-08-27-prove-and-package-architecture.md`,
 * sections 7-10):
 *
 *   A. retrieval_quality       population Recall@10, MRR, nDCG@10
 *   B. regression_anchors      compact PASS/total over golden anchors
 *   C. eligibility_contracts   hard eligibility/filter fixtures
 *   D. agent_contracts         deterministic agent/evidence guarantees
 *
 * Only A is gated on `provenance.attributed`. B, C, and D are deterministic
 * pass/fail contracts rather than population relevance judgments, so they
 * render every time this loads, whether or not A's numbers are attributable
 * to the revision currently running.
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
        return (
          <li key={queryId}>
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
              recall@10 {numberField(row, "recall@10")} &middot; ndcg@10{" "}
              {numberField(row, "ndcg@10")} &middot; reciprocal rank{" "}
              {numberField(row, "reciprocal_rank")}
            </small>
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
      <h3 id="scorecard-quality-title">A. Retrieval quality</h3>
      <p className="labs-scorecard-sample">{quality.sample_description}</p>

      {provenance.attributed ? (
        <PlaygroundFigures label="Retrieval quality metrics">
          <PlaygroundFigure
            label="Recall@10"
            value={quality.recall_at_10.toFixed(4)}
            detail={quality.metric_explanations["recall@10"]}
          />
          <PlaygroundFigure
            label="MRR"
            value={quality.mrr.toFixed(4)}
            detail={quality.metric_explanations.mrr}
          />
          <PlaygroundFigure
            label="nDCG@10"
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
              Recall@10, MRR, and nDCG@10 measure retrieval quality across the
              scored sample below, but are withheld here until the canonical
              scorecard is remeasured at the revision currently running.
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
        label="View provenance"
        hint={
          provenance.attributed
            ? "measured at the revision currently running"
            : "why these numbers are withheld"
        }
      >
        <p data-testid="scorecard-attribution-note">
          {provenance.attribution_note}
        </p>
        <dl className="labs-profile">
          <div>
            <dt>measured revision</dt>
            <dd className="mono">
              {provenance.source_revision ?? "none recorded"}
            </dd>
          </div>
          <div>
            <dt>measured worktree dirty</dt>
            <dd className="mono">{String(provenance.source_worktree_dirty)}</dd>
          </div>
          <div>
            <dt>running revision</dt>
            <dd className="mono">
              {provenance.current_source_revision ?? "unresolved"}
            </dd>
          </div>
          <div>
            <dt>measured at</dt>
            <dd className="mono">{provenance.measured_at}</dd>
          </div>
        </dl>
      </PlaygroundDisclosure>

      {quality.per_query_metrics.length ? (
        <PlaygroundDisclosure
          label="View per-query results"
          hint={`${quality.per_query_metrics.length} queries`}
        >
          <PerQueryMetricsList rows={quality.per_query_metrics} />
        </PlaygroundDisclosure>
      ) : null}

      {quality.excluded_agent_contract_query_ids.length ? (
        <p className="labs-scorecard-exclusion">
          {quality.sample_size} of the {quality.canonical_query_count} canonical
          queries are scored for search relevance below.{" "}
          <code>{quality.excluded_agent_contract_query_ids.join(", ")}</code>{" "}
          {quality.excluded_agent_contract_query_ids.length === 1 ? "is" : "are"}{" "}
          not: {quality.excluded_agent_contract_query_ids.length === 1
            ? "it exercises"
            : "they exercise"}{" "}
          multi-step agent tool orchestration -- planning, comparison, evidence
          retrieval, and cited synthesis -- rather than a single search
          request, so grading with Recall, MRR, or nDCG would measure the
          wrong thing. See section D for the agent-specific contracts checked
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
  const allPassed = anchors.total > 0 && anchors.passed === anchors.total;
  return (
    <section
      className="labs-scorecard-section"
      aria-labelledby="scorecard-anchors-title"
    >
      <h3 id="scorecard-anchors-title">B. Golden regression anchors</h3>
      <PlaygroundFigures label="Golden regression anchors">
        <PlaygroundFigure
          label="PASS / total"
          value={`${anchors.passed} / ${anchors.total}`}
          tone={allPassed ? "good" : "warn"}
          detail="Did a known critical behavior regress? Never mixed into Recall, MRR, or nDCG."
        />
      </PlaygroundFigures>
      <PlaygroundDisclosure
        label="View anchors"
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
      <h3 id="scorecard-eligibility-title">C. Eligibility and filter contracts</h3>
      <PlaygroundFigures label="Eligibility and filter contracts">
        <PlaygroundFigure
          label="Fixtures held"
          value={String(contracts.fixture_count)}
          tone={contracts.held ? "good" : "warn"}
          detail="Did retrieval violate a hard contract? Not a relevance judgment: no Recall, MRR, or nDCG is computed over these."
        />
      </PlaygroundFigures>
      <PlaygroundDisclosure
        label="View fixture queries"
        hint={`${contracts.fixture_query_ids.length} queries`}
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
      <h3 id="scorecard-agent-title">D. Agent and evidence contracts</h3>
      <p className="labs-contract-note">
        Deterministic guarantees the agent is held to. Real validation data:
        every name and falsifier below is read from
        service.assertions.ASSERTIONS, not typed fresh for this surface. No IR
        metric and no LLM judge appears here.
      </p>
      <ul className="labs-contracts">
        {contracts.guarantees.map((guarantee) => (
          <li key={guarantee.key}>
            <code>{guarantee.label}</code>
            <b>
              {guarantee.fixture_count != null
                ? `${guarantee.fixture_count} registered`
                : `${guarantee.assertion_names.length} assertions`}
            </b>
            <small>{guarantee.description}</small>
          </li>
        ))}
      </ul>
      <PlaygroundDisclosure
        label="View assertion falsifiers"
        hint={`${assertionCount} assertions`}
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

export function RetrievalScorecard() {
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
  }, []);

  if (error) {
    return (
      <p className="labs-disclosure-error" role="alert">
        <AlertTriangle aria-hidden="true" size={16} />
        {error}
      </p>
    );
  }
  if (!data) {
    return <p role="status">Loading the canonical evaluation artifact.</p>;
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
    </div>
  );
}
