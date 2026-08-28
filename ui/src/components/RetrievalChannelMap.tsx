import { Check, CircleAlert, Minus } from "lucide-react";
import { armLanguage, armPoolKey, type RetrievalArm } from "../retrievalLanguage";
import type { ReadinessResponse, SearchResponse } from "../types";

/**
 * The bridge from what a shopper reads to what PostgreSQL ran, and the one place
 * Lab 1's distinction is drawn.
 *
 * Lab 1's whole lesson is that a component can be healthy while the composition
 * that uses it is broken. `make reset-lab-1` deletes the `typo` CTE from
 * `mosaic_search.search_hybrid_rrf` and deliberately leaves
 * `mosaic_search.search_trigram` installed and callable, so a surface that only
 * reports "pg_trgm: 0 candidates" teaches the wrong thing — a participant reads it
 * as a missing extension and goes looking for `CREATE EXTENSION`.
 *
 * So two independent measurements, side by side:
 *
 *   1. Is the component installed? `/api/readiness` reports
 *      `missing_retrieval_indexes` and `missing_retrieval_functions` from
 *      `pg_class` and `pg_proc`. A trigram GIN index that is present, valid and
 *      ready is a fact about the deployment, and it stays true across the repair.
 *   2. Did it contribute to the pool this query was served from?
 *      `candidate_counts.trigram_in_pool`, which the service computes by counting
 *      rows in the fused pool carrying a `trigram_rank`. That is the figure the
 *      `trigram_signal_present` assertion reads, and it is the one that flips.
 *
 * "Disconnected" is only asserted when the scenario requires that arm.
 * `trigram_in_pool = 0` on a query with no near-miss spellings is the arm having
 * nothing to say, not the arm being unwired, and calling that disconnected would
 * be a claim this response cannot support. When the scenario's
 * `expected_techniques` names the arm and the count is still zero, the arm was
 * required and absent, which is exactly the repair state.
 *
 * The index name and the one-line purpose below print for every arm, not only a
 * broken one. Before this, `indexName` only ever appeared inside `ChannelSplit`,
 * so a participant learned to associate "index" with "something is wrong" and a
 * healthy run never said which Postgres index served which arm, or why the arm
 * exists at all. The ordinary render says both, whether or not anything here is
 * broken.
 */

export type ChannelState = "contributing" | "disconnected" | "silent";

export interface ChannelReading {
  arm: RetrievalArm;
  label: string;
  mechanism: string;
  /** Candidates in the served pool that this arm ranked. */
  inPool: number;
  pool: number;
  state: ChannelState;
  /** False only when readiness reports this arm's index missing or invalid. */
  indexHealthy: boolean | null;
  indexName: string;
  /** What this arm is for, one line, independent of any particular run. */
  purpose: string;
}

const armIndexName: Record<RetrievalArm, string> = {
  fts: "product_document_fts_gin_idx",
  trigram: "product_document_trigram_gin_idx",
  semantic: "product_document_embedding_hnsw_cosine_idx",
};

/**
 * What each arm is for, in the shopper's own input rather than the algorithm.
 * Three names and three counts do not say why there are three of them; this
 * does. Written once here, keyed off the same `RetrievalArm` that names the
 * index above, so the ordinary render and `ChannelSplit` cannot describe one
 * arm two different ways.
 */
const armPurpose: Record<RetrievalArm, string> = {
  fts: "Wins when the words a shopper typed already appear in the catalog, such as a model name or a brand.",
  trigram: "Earns its place when those words are misspelled or a variant, so character overlap finds what exact matching missed.",
  semantic: "Answers a described benefit or intent that shares no words with the product text at all.",
};

/** Which `expected_techniques` tokens name each arm in the eval fixtures. */
const armTechniques: Record<RetrievalArm, string[]> = {
  fts: ["fts", "lexical"],
  trigram: ["pg_trgm", "trigram"],
  semantic: ["vector", "semantic"],
};

export function readChannels(
  response: SearchResponse,
  expectedTechniques: string[],
  readiness: ReadinessResponse | null,
): ChannelReading[] {
  const counts = response.diagnostics?.candidate_counts ?? {};
  const pool = counts.fused_pool ?? 0;
  const missingIndexes = readiness?.database.missing_retrieval_indexes ?? null;
  return armLanguage.map((entry) => {
    const inPool = counts[armPoolKey[entry.key]] ?? 0;
    const required = armTechniques[entry.key].some((technique) =>
      expectedTechniques.includes(technique),
    );
    const indexName = armIndexName[entry.key];
    return {
      arm: entry.key,
      label: entry.label,
      mechanism: entry.mechanism,
      inPool,
      pool,
      state: inPool > 0
        ? "contributing"
        : required
          ? "disconnected"
          : "silent",
      indexHealthy: readiness
        ? !(missingIndexes ?? []).includes(indexName)
        : null,
      indexName,
      purpose: armPurpose[entry.key],
    };
  });
}

function StateMark({ state }: { state: ChannelState }) {
  if (state === "contributing") {
    return <Check aria-hidden="true" className="labs-channel-mark is-good" size={15} />;
  }
  if (state === "disconnected") {
    return (
      <CircleAlert aria-hidden="true" className="labs-channel-mark is-warn" size={15} />
    );
  }
  return <Minus aria-hidden="true" className="labs-channel-mark" size={15} />;
}

function stateWord(reading: ChannelReading): string {
  if (reading.state === "contributing") {
    return `${reading.inPool} of ${reading.pool} candidates`;
  }
  if (reading.state === "disconnected") return "not in this pool";
  return "no candidates for this query";
}

/**
 * The healthy / broken split for one arm, spelled out.
 *
 * Rendered only for an arm the scenario required and did not get, because it is
 * the only case where the two facts disagree and the disagreement is the lesson.
 */
function ChannelSplit({ reading }: { reading: ChannelReading }) {
  return (
    <div className="labs-channel-split" role="note">
      <p>
        <strong>{reading.mechanism} function:</strong>{" "}
        {reading.indexHealthy === null ? (
          <em>not checked — /api/readiness did not answer</em>
        ) : reading.indexHealthy ? (
          <b className="is-good">HEALTHY</b>
        ) : (
          <b className="is-warn">index missing or invalid</b>
        )}
        <small>
          {reading.indexHealthy === null
            ? "Index health comes from pg_class, through /api/readiness."
            : reading.indexHealthy
              ? `${reading.indexName} is present, valid and ready.`
              : `${reading.indexName} is absent from mosaic_search, or not valid.`}
        </small>
      </p>
      <p>
        <strong>{reading.mechanism} contribution to the served pool:</strong>{" "}
        <b className="is-warn">DISCONNECTED</b>
        <small>
          This scenario is written to require the {reading.label.toLowerCase()} arm,
          and no candidate in the pool of {reading.pool} carries a rank from it.
        </small>
      </p>
      <p className="labs-channel-split-lesson">
        The component works. The composition does not. An answer can look right
        while the retrieval pipeline behind it is wrong.
      </p>
    </div>
  );
}

export function RetrievalChannelMap({
  readings,
}: {
  readings: ChannelReading[];
}) {
  const broken = readings.filter((reading) => reading.state === "disconnected");
  return (
    <section className="labs-channels" aria-labelledby="labs-channels-title">
      <h3 id="labs-channels-title">Three ways of finding one product</h3>
      <ul className="labs-channel-list">
        {readings.map((reading) => (
          <li className={`is-${reading.state}`} key={reading.arm}>
            <StateMark state={reading.state} />
            <strong>{reading.label}</strong>
            <div className="labs-channel-mechanism">
              <code>{reading.mechanism}</code>
              <small>{reading.indexName}</small>
            </div>
            <span>{stateWord(reading)}</span>
            <p className="labs-channel-purpose">{reading.purpose}</p>
          </li>
        ))}
      </ul>
      {broken.map((reading) => (
        <ChannelSplit key={reading.arm} reading={reading} />
      ))}
    </section>
  );
}
