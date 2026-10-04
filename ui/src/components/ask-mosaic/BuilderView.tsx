import { useMemo } from "react";
import type { AgentResponse } from "../../types";
import { NOT_RECORDED, runFacts, stepsFor, type BuilderStep, type StepTag } from "./builderModel";
import { phaseFinding, type RunData } from "./findings";
import { HowItRanked, rankedSearches } from "./HowItRanked";
import { pickName } from "./comparison";
import { stagesFor } from "./types";
import { useRankReceipts } from "./useRankReceipts";

function Tag({ tag }: { tag: StepTag }) {
  return (
    <span className="ask-pill ask-pill-quiet">
      <i className="ask-dot" data-stage={tag.stage ?? "none"} aria-hidden="true" />
      {tag.label}
    </span>
  );
}

function StepRow({ step }: { step: BuilderStep }) {
  return (
    <li className="ask-step">
      <div className="ask-step-head">
        <span className="ask-mono ask-step-tool">{step.tool}</span>
        {step.tags.map((tag) => <Tag key={tag.label} tag={tag} />)}
        <span className="ask-mono ask-step-meta">{step.meta}</span>
      </div>
      {step.args ? <p className="ask-mono ask-step-args">{step.args}</p> : null}
      {step.detail ? <p className="ask-step-detail">{step.detail}</p> : null}
    </li>
  );
}

/**
 * Everything the run recorded, in the order it happened: the run's own facts,
 * what the response does not carry, each phase with its steps, and how every
 * search ranked its products. Built from `plan`, `trace` and saved searches;
 * nothing here is composed in advance.
 */
export function BuilderView({
  response,
  run,
  durationMs,
}: {
  response: AgentResponse;
  run: RunData;
  durationMs?: number;
}) {
  const known = useMemo(
    () => new Map(response.recommendations.map((product) => [product.product_id, pickName(product)])),
    [response.recommendations],
  );
  const runIds = useMemo(
    () => run.trace.flatMap((step) => (step.tool === "search_products" && step.retrieval_run_id ? [step.retrieval_run_id] : [])),
    [run.trace],
  );
  const { receipts, names } = useRankReceipts(runIds, true, known);
  const searches = rankedSearches(run.trace, receipts);
  return (
    <section className="ask-builder" aria-label="Builder view">
      <div className="ask-builder-facts">
        <h3>How this answer was built</h3>
        {runFacts(response, durationMs).map((fact) => (
          <span className="ask-pill ask-pill-solid ask-mono" key={fact}>{fact}</span>
        ))}
      </div>
      <div className="ask-builder-missing">
        <span>Not recorded on this run</span>
        {NOT_RECORDED.map((field) => <span className="ask-pill ask-pill-dashed" key={field}>{field}</span>)}
      </div>
      <ol className="ask-timeline">
        {stagesFor(run.path).map((stage) => {
          const steps = stepsFor(stage.id, run.plan, run.trace);
          const finding = phaseFinding(stage.id, run);
          return (
            <li key={stage.id} className="ask-phase" data-stage={stage.id}>
              <span className="ask-phase-node" aria-hidden="true" />
              <div className="ask-phase-body">
                <p className="ask-phase-title">
                  <strong>{stage.done}</strong>
                  {finding ? <span>{finding}</span> : null}
                </p>
                {steps.length ? <ul className="ask-steps">{steps.map((step) => <StepRow key={step.key} step={step} />)}</ul> : null}
                {stage.id === "retrieve" && searches.length ? (
                  <HowItRanked searches={searches} products={response.recommendations} names={names} />
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
