import type { ReadinessResponse } from "../types";

/**
 * Nine facts about the room, in one line, before anybody blames the lab.
 *
 * Every failure this workshop can hit at the wrong moment looks the same on
 * screen: an arm returns nothing. A trigram index that never got built, a corpus
 * that stopped at 400,000 rows, an expired Bedrock session and an unrepaired CTE
 * all produce an empty column, and only one of them is the lab. A participant
 * with no way to tell them apart edits SQL for ten minutes against a database
 * that was never going to answer.
 *
 * `not checked` is a first-class value here rather than a dash or an empty cell.
 * The strip is read as evidence, so it has to distinguish "this was measured and
 * it is fine" from "nothing measured this", and it may never print the first
 * when it means the second.
 */

/** What a row prints when nothing on this page reports its value. */
const NOT_CHECKED = "not checked";

interface ReadinessRow {
  label: string;
  value: string;
}

function readinessRows(readiness: ReadinessResponse | null): ReadinessRow[] {
  const database = readiness?.database;
  const models = readiness?.configured_models;
  const missingIndexes = database?.missing_retrieval_indexes ?? null;
  return [
    {
      label: "Aurora",
      value: database ? `PostgreSQL ${database.server_version}` : NOT_CHECKED,
    },
    {
      label: "Data",
      value: database
        ? `${database.product_count.toLocaleString("en-US")} products, ${
          database.embedded_product_count.toLocaleString("en-US")
        } embedded`
        : NOT_CHECKED,
    },
    {
      label: "Indexes",
      value: !database
        ? NOT_CHECKED
        : missingIndexes && missingIndexes.length > 0
          ? `missing: ${missingIndexes.join(", ")}`
          : "all present",
    },
    {
      // Absent rather than "missing" when the service does not report it: the
      // two mean opposite things to whoever would go and reseed the table.
      label: "Ground truth",
      value: database?.exact_neighbor_ground_truth ?? NOT_CHECKED,
    },
    { label: "Embed", value: models?.embedding ?? NOT_CHECKED },
    { label: "Rerank", value: models?.rerank ?? NOT_CHECKED },
    { label: "Agent", value: models?.agent ?? NOT_CHECKED },
    // `/api/readiness` and `/api/health` report neither, and a live search
    // response does not carry them either: they reach this browser only on a
    // persisted run's receipt, which this surface does not read. Printing the
    // running service's revision from anywhere else would be a guess with a
    // hash on it, so the row says what it knows, which is nothing.
    { label: "Source revision", value: NOT_CHECKED },
    { label: "Dataset manifest", value: NOT_CHECKED },
  ];
}

export function ReadinessStrip({
  readiness,
}: {
  /** Null while the readiness read is outstanding, and after one that failed. */
  readiness: ReadinessResponse | null;
}) {
  return (
    <section aria-label="Environment readiness" className="labs-readiness">
      <dl>
        {readinessRows(readiness).map((row) => (
          <div
            className={
              row.value === NOT_CHECKED
                ? "labs-readiness-row is-unknown"
                : "labs-readiness-row"
            }
            key={row.label}
          >
            <dt>{row.label}</dt>
            <dd>{row.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
