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

/**
 * What a row is telling the reader, which is not the same as what it prints.
 *
 * `problem` is reserved for something a participant or facilitator can act on
 * right now. `unchecked` is the distinction this component was built around and
 * must never collapse into `ok`: nothing measured the row, which is not the
 * same as measuring it and finding it fine.
 */
type RowState = "ok" | "problem" | "unchecked";

interface ReadinessRow {
  label: string;
  value: string;
  state: RowState;
}

/** `ok` when the read landed, `unchecked` when nothing reported it. */
function reported(present: boolean): RowState {
  return present ? "ok" : "unchecked";
}

function readinessRows(readiness: ReadinessResponse | null): ReadinessRow[] {
  const database = readiness?.database;
  const models = readiness?.configured_models;
  const source = readiness?.source;
  const missingIndexes = database?.missing_retrieval_indexes ?? null;
  const groundTruth = database?.exact_neighbor_ground_truth;
  return [
    {
      label: "Aurora",
      value: database ? `PostgreSQL ${database.server_version}` : NOT_CHECKED,
      state: reported(Boolean(database)),
    },
    {
      label: "Data",
      value: database
        ? `${database.product_count.toLocaleString("en-US")} products, ${
          database.embedded_product_count.toLocaleString("en-US")
        } embedded`
        : NOT_CHECKED,
      // A corpus with products the embedder never reached is the quietest
      // failure in the room: the semantic arm just returns less, and the two
      // numbers printed side by side are the only thing that says so.
      state: !database
        ? "unchecked"
        : database.embedded_product_count < database.product_count
          ? "problem"
          : "ok",
    },
    {
      label: "Indexes",
      value: !database
        ? NOT_CHECKED
        : missingIndexes && missingIndexes.length > 0
          ? `missing: ${missingIndexes.join(", ")}`
          : "all present",
      state: !database
        ? "unchecked"
        : missingIndexes && missingIndexes.length > 0
          ? "problem"
          : "ok",
    },
    {
      // Absent rather than "missing" when the service does not report it: the
      // two mean opposite things to whoever would go and reseed the table.
      label: "Ground truth",
      value: groundTruth ?? NOT_CHECKED,
      // `missing` is a facilitator preflight step, so it is actionable.
      // `unknown` means the read itself failed, which is not the same claim.
      state: groundTruth === "seeded"
        ? "ok"
        : groundTruth === "missing"
          ? "problem"
          : "unchecked",
    },
    {
      label: "Embed",
      value: models?.embedding ?? NOT_CHECKED,
      state: reported(Boolean(models)),
    },
    {
      label: "Rerank",
      value: models?.rerank ?? NOT_CHECKED,
      state: reported(Boolean(models)),
    },
    {
      label: "Agent",
      value: models?.agent ?? NOT_CHECKED,
      state: reported(Boolean(models)),
    },
    // Which build answered and which corpus it answered from, both straight off
    // `/api/readiness`. A service too old to report them leaves `source` absent,
    // and that reads as not checked rather than as a revision.
    {
      label: "Source revision",
      value: source ? sourceRevisionValue(source) : NOT_CHECKED,
      state: reported(Boolean(source)),
    },
    {
      label: "Dataset manifest",
      value: source ? short(source.dataset_manifest_sha256) : NOT_CHECKED,
      state: reported(Boolean(source)),
    },
  ];
}

/**
 * One line for the whole environment, derived from the rows themselves.
 *
 * Deliberately not `ReadinessResponse.status`. A headline computed from a second
 * source can disagree with the list printed under it, and a participant reading
 * "ready" above a missing index would trust the wrong one. This summarises
 * exactly what is listed and nothing else.
 */
export function readinessVerdict(rows: ReadinessRow[]): {
  text: string;
  state: RowState;
  open: boolean;
} {
  const problems = rows.filter((row) => row.state === "problem").length;
  const unchecked = rows.filter((row) => row.state === "unchecked").length;
  if (problems > 0) {
    return {
      text: `Environment: ${problems} ${problems === 1 ? "problem" : "problems"}`,
      state: "problem",
      open: true,
    };
  }
  if (unchecked > 0) {
    return { text: `Environment: ${unchecked} not checked`, state: "unchecked", open: true };
  }
  return { text: "Environment ready", state: "ok", open: false };
}

/** Problems first when something is wrong; declaration order when nothing is. */
function ordered(rows: ReadinessRow[]): ReadinessRow[] {
  const rank: Record<RowState, number> = { problem: 0, unchecked: 1, ok: 2 };
  return [...rows].sort((a, b) => rank[a.state] - rank[b.state]);
}

export function ReadinessStrip({
  readiness,
}: {
  /** Null while the readiness read is outstanding, and after one that failed. */
  readiness: ReadinessResponse | null;
}) {
  const rows = readinessRows(readiness);
  const verdict = readinessVerdict(rows);
  return (
    <section aria-label="Environment readiness" className="labs-readiness">
      {/* Nine facts are what a stuck participant needs and what everybody else
          reads past. `open` is not state here: it is derived, so the strip is a
          single line while the room is fine and is already expanded, problems
          first, the moment it is the thing worth reading. */}
      <details className="labs-readiness-disclosure" open={verdict.open}>
        <summary>
          <span className="labs-readiness-verdict" data-state={verdict.state}>
            {verdict.text}
          </span>
        </summary>
        <dl>
          {ordered(rows).map((row) => (
            <div
              className={
                row.state === "ok"
                  ? "labs-readiness-row"
                  : `labs-readiness-row is-${row.state}`
              }
              key={row.label}
            >
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
      </details>
    </section>
  );
}
