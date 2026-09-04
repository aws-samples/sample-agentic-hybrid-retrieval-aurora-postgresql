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

/** Enough of a sha to name a commit or a manifest, and no more. */
function short(hash: string): string {
  return hash.slice(0, 12);
}

/**
 * The build that answered, and whether the file tree it ran from matched it.
 *
 * `worktree_dirty` is not a footnote here. A facilitator holding a measured
 * artifact against the running service reads the sha to decide whether the two
 * agree, and a service serving uncommitted changes on top of that sha can hold
 * the very edit that explains a difference.
 */
function sourceRevisionValue(
  source: NonNullable<ReadinessResponse["source"]>,
): string {
  // The service falls back to `unknown` with `worktree_dirty` true when it could
  // not read git at all, so the flag there describes nothing it inspected.
  if (source.revision === "unknown") return "unknown";
  const revision = short(source.revision);
  return source.worktree_dirty ? `${revision} (uncommitted changes)` : revision;
}

interface ReadinessRow {
  label: string;
  value: string;
}

function readinessRows(readiness: ReadinessResponse | null): ReadinessRow[] {
  const database = readiness?.database;
  const models = readiness?.configured_models;
  const source = readiness?.source;
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
    // Which build answered and which corpus it answered from, both straight off
    // `/api/readiness`. A service too old to report them leaves `source` absent,
    // and that reads as not checked rather than as a revision.
    {
      label: "Source revision",
      value: source ? sourceRevisionValue(source) : NOT_CHECKED,
    },
    {
      label: "Dataset manifest",
      value: source ? short(source.dataset_manifest_sha256) : NOT_CHECKED,
    },
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
