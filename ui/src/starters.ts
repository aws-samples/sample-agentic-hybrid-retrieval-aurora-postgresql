import { armLabel, type RetrievalArm } from "./retrievalLanguage";
import type { Domain, RetrievalExample } from "./types";

/**
 * Which starter questions the Ask Mosaic entry state offers, and what each one
 * is for.
 *
 * `/api/retrieval/examples` serves `data/evals/demo_queries.jsonl` deduplicated
 * in file order, so every participant sees the same starters and every starter
 * is a question the eval suite actually scores rather than copy written for the
 * panel.
 *
 * The panel used to take the first query of each domain. That is deterministic
 * but it fills the entry state with the eval set's three most elaborate
 * queries, which are all long and filter-laden, so the retrieval paths the
 * workshop exists to teach never appeared. Picking one query per retrieval path
 * instead puts the contrast in the first thing anyone sees.
 */

/**
 * Display order for the cards that run on click, and the reason the trigram lane
 * is not among them.
 *
 * The eval set's misspelled queries are misspelled on purpose — "noice canceling
 * hedphones for long fligts under 200" is one of them — and these cards print a
 * starter's text verbatim on a button in Mosaic's own voice. Offering one meant
 * the store shipped a spelling mistake as its own suggestion, which is the one
 * thing the typo lesson must not do: the imperfect query is the shopper's, and
 * Mosaic's job is to handle it, not to author it.
 *
 * The lane is still offered, by `misspelledExample` below, as a box to fill
 * rather than a question to press. That makes this exactly the two arms a
 * click can safely run: one card per clickable arm, no arm skipped and none
 * doubled.
 */
const starterPaths = ["exact", "semantic"] as const;

/**
 * How many starters run on click.
 *
 * Equal to `starterPaths.length` by construction: with two clickable arms and
 * one pick per arm, two is the whole count, not a target the fill-remaining
 * loop in `starterExamples` has to reach by raiding an arm a second time.
 */
const STARTER_COUNT = starterPaths.length;

export type StarterPath = (typeof starterPaths)[number] | "misspelled";

/**
 * The one shopper-facing name for each path, pinned to `armLabel` so this file
 * cannot carry its own copy of a string `retrievalLanguage.ts` already owns.
 * Two independent copies of "Exact terms" is how a label and its arm drift
 * apart; there is deliberately no local string literal here to drift.
 */
export const starterPathLabels: Record<StarterPath, string> = {
  exact: armLabel.fts,
  misspelled: armLabel.trigram,
  semantic: armLabel.semantic,
};

/**
 * The retrieval arm a validated eval query is written to exercise.
 *
 * A total function of `expected_techniques`, which every `demo_queries.jsonl`
 * row carries, so the label is read from the eval set rather than guessed from
 * the wording. Precedence matters because a query can name more than one arm:
 * `pg_trgm` outranks everything else because a misspelled query names the
 * trigram arm alongside others and the trigram arm is the one under test;
 * `fts` outranks `semantic` for the same reason among the queries that name
 * both. `semantic` and `vector` both name the semantic arm, matching the
 * `vector`/`semantic` pair `TECHNIQUE_ARMS` below already carries.
 *
 * Throws rather than falling back to an invented path. Every row in
 * `data/evals/demo_queries.jsonl` names at least one of `pg_trgm`, `fts`,
 * `semantic`, or `vector` — checked against the fixture, not assumed — so a
 * row reaching neither branch is the fixture breaking its own contract, and
 * mislabeling it "plain" is the exact bug this function is being fixed to
 * stop committing. A loud failure here is honest; a silent fourth path is not.
 */
export function starterPath(example: RetrievalExample): StarterPath {
  if (example.expected_techniques.includes("pg_trgm")) return "misspelled";
  if (example.expected_techniques.includes("fts")) return "exact";
  if (
    example.expected_techniques.includes("semantic") ||
    example.expected_techniques.includes("vector")
  ) {
    return "semantic";
  }
  throw new Error(
    `starterPath: query_id ${example.query_id} names no known retrieval arm ` +
      `(expected one of pg_trgm, fts, semantic, vector in expected_techniques, ` +
      `got ${JSON.stringify(example.expected_techniques)})`,
  );
}

/**
 * The arms a starter is written to exercise, in the shopper's words.
 *
 * The chips used to print `expected_techniques` verbatim, so a shopping panel
 * showed `pg_trgm`, `vector` and `rrf` as tags on a question. Only the three
 * candidate arms map to something a shopper can read; `filters`, `rrf` and
 * `rerank` name stages rather than ways of finding a product, and they are what
 * the Playground exists to show. Order follows the pipeline, not the fixture.
 */
const TECHNIQUE_ARMS: Record<string, RetrievalArm> = {
  fts: "fts",
  lexical: "fts",
  pg_trgm: "trigram",
  trigram: "trigram",
  vector: "semantic",
  semantic: "semantic",
};

const ARM_ORDER: RetrievalArm[] = ["fts", "trigram", "semantic"];

export function starterArmLabels(example: RetrievalExample): string[] {
  const arms = new Set(
    example.expected_techniques
      .map((technique) => TECHNIQUE_ARMS[technique])
      .filter((arm): arm is RetrievalArm => Boolean(arm)),
  );
  return ARM_ORDER.filter((arm) => arms.has(arm)).map((arm) => armLabel[arm]);
}

/**
 * Up to two starters, one per clickable retrieval arm, preferring a domain no
 * earlier pick used and then the shortest query available.
 *
 * Shortest rather than first: within a path the eval set's opening query is its
 * most elaborate, and long sentences are what made this block unreadable. The
 * domain preference comes first so the starters still span different product
 * domains rather than converging on one. Once each admitted path — `exact` and
 * `semantic` — has contributed one pick, `picks.length` already equals
 * `STARTER_COUNT`, so the remaining-slots loop below does not run in ordinary
 * operation; it exists only so a path with zero admitted examples cannot leave
 * a slot silently empty, drawing from whatever remains instead.
 */
export function starterExamples(
  examples: RetrievalExample[],
): RetrievalExample[] {
  const admitted = examples.filter((example) => {
    const path = starterPath(example);
    return path !== "misspelled";
  });
  const usedDomains = new Set<Domain>();
  const picks: RetrievalExample[] = [];

  const takeShortest = (pool: RetrievalExample[]) => {
    const unusedDomain = pool.filter(
      (example) => !usedDomains.has(example.domain),
    );
    const candidates = unusedDomain.length ? unusedDomain : pool;
    if (!candidates.length) return;
    const pick = candidates.reduce((shortest, example) =>
      example.query.length < shortest.query.length ? example : shortest,
    );
    picks.push(pick);
    usedDomains.add(pick.domain);
  };

  for (const path of starterPaths) {
    takeShortest(admitted.filter((example) => starterPath(example) === path));
  }
  while (picks.length < STARTER_COUNT) {
    const remaining = admitted.filter((example) => !picks.includes(example));
    if (!remaining.length) break;
    takeShortest(remaining);
  }
  return picks.slice(0, STARTER_COUNT);
}

/**
 * The close-spelling query the entry state offers, or null if the eval set has
 * none.
 *
 * Shortest of the lane, on the same rule the two run-on-click cards use, so
 * what lands in the composer is short enough to read the misspellings in before
 * pressing send — which is the whole point of putting it there rather than on a
 * button.
 *
 * The invariant this and `starterExamples` together maintain: one card per
 * retrieval arm, no arm skipped and none doubled. `exact` and `semantic` each
 * get a clickable card; `misspelled` gets this box-to-fill instead of a third
 * click target, because a clickable card would have Mosaic print a typo in its
 * own voice. Three arms, three cards, two shapes.
 */
export function misspelledExample(
  examples: RetrievalExample[],
): RetrievalExample | null {
  const lane = examples.filter(
    (example) => starterPath(example) === "misspelled",
  );
  if (!lane.length) return null;
  return lane.reduce((shortest, example) =>
    example.query.length < shortest.query.length ? example : shortest,
  );
}
