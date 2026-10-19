import type { CSSProperties, ReactNode } from "react";
import { Link } from "wouter";
import { playgroundQueryHref } from "../navigation";
import { armLanguage, armPoolKey, type RetrievalArm } from "../retrievalLanguage";
import type { SearchResponse } from "../types";
import "../pipeline-strip.css";

type Dot = "found" | "none" | "fault";

function Chip({ label, value, dot, order, title }: {
  label: string;
  value?: string | number;
  dot: Dot;
  order: number;
  title?: string;
}) {
  return (
    <li className="pipeline-chip" data-dot={dot} style={{ "--i": order } as CSSProperties} title={title}>
      <i aria-hidden="true" />
      <b>{label}</b>
      {value === undefined ? null : <span>{value}</span>}
    </li>
  );
}

function Arrow({ order }: { order: number }) {
  return <li className="pipeline-arrow" aria-hidden="true" style={{ "--i": order } as CSSProperties}>→</li>;
}

const ms = (value: number | undefined) => (value === undefined ? null : `${Math.round(value)} ms`);

/**
 * One search as a left-to-right pipeline: the three searches, the combining in
 * Aurora, the reranking, and how many products were shown.
 *
 * Every number is read from the response. The counts are candidates that
 * survived fusion into the combined pool, not what each search found on its
 * own, and the sentence below says so. `faultArm` is set only by a caller that
 * already holds a lab verdict for this run; the strip never decides a fault.
 */
export function PipelineStrip({ response, faultArm = null }: {
  response: SearchResponse;
  faultArm?: RetrievalArm | null;
}) {
  const diagnostics = response.diagnostics;
  const counts = diagnostics?.candidate_counts ?? {};
  const timings = diagnostics?.stage_timings_ms ?? {};
  const pool = counts.fused_pool;
  const reranked = diagnostics?.rerank_status === "applied";
  const rerankName = /cohere/i.test(diagnostics?.rerank_model_id ?? "") ? "Cohere Rerank" : "reranker";
  const searchTime = ms(timings.postgresql_retrieval);
  const rerankTime = ms(timings.rerank);

  const chips: ReactNode[] = [];
  armLanguage.forEach((arm, index) => {
    const count = counts[armPoolKey[arm.key]];
    const dot: Dot = faultArm === arm.key ? "fault" : count ? "found" : "none";
    chips.push(
      <Chip
        key={arm.key}
        label={arm.label}
        value={count ?? "—"}
        dot={dot}
        order={index}
        title={count === undefined ? undefined : `${count} in the combined pool`}
      />,
    );
  });
  chips.push(<Arrow key="a1" order={3} />);
  chips.push(
    <Chip key="rrf" label="Combined in Aurora (RRF)" value={pool ?? "—"} dot={pool ? "found" : "none"} order={4}
      title={pool === undefined ? undefined : `${pool} in the combined pool`} />,
  );
  chips.push(<Arrow key="a2" order={5} />);
  chips.push(
    reranked
      ? <Chip key="rr" label={`Reranked · ${rerankName}`} dot="found" order={6} />
      : <Chip key="rr" label="Not reranked" dot="none" order={6} />,
  );
  chips.push(<Arrow key="a3" order={7} />);
  chips.push(<Chip key="shown" label={`${response.results.length} shown`} dot="none" order={8} />);

  return (
    <section className="pipeline-strip" aria-label="How this search ran">
      <ol className="pipeline-chips">{chips}</ol>
      <p className="pipeline-note">
        Three searches ran inside Aurora PostgreSQL{searchTime ? ` in ${searchTime}` : ""}; the
        numbers are the candidates from each that reached the combined pool{pool === undefined ? "" : ` of ${pool}`}.
        Aurora combined their positions
        {reranked ? `, then a reranker reordered ${pool === undefined ? "the shortlist" : `the top ${pool}`}${rerankTime ? ` in ${rerankTime}` : ""}` : ""}.
      </p>
      <Link className="pipeline-link" href={playgroundQueryHref(response.query, response.applied_filters, response.search_event_id)}>
        Watch the ranking change in the Playground →
      </Link>
    </section>
  );
}
