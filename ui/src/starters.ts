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
 * rather than a question to press.
 */
const starterPaths = ["exact", "plain"] as const;

/** How many starters the entry state shows. */
const STARTER_COUNT = 3;

export type StarterPath = (typeof starterPaths)[number] | "misspelled";

export const starterPathLabels: Record<StarterPath, string> = {
  exact: "Exact terms",
  misspelled: "Close spelling",
  plain: "Plain language",
};

/**
 * The retrieval path a validated eval query is written to exercise.
 *
 * A total function of `expected_techniques`, which every `demo_queries.jsonl`
 * row carries, so the label is read from the eval set rather than guessed from
 * the wording. `pg_trgm` outranks `fts` because a misspelled query names both
 * and the trigram arm is the one under test.
 */
export function starterPath(example: RetrievalExample): StarterPath {
  if (example.expected_techniques.includes("pg_trgm")) return "misspelled";
  if (example.expected_techniques.includes("fts")) return "exact";
  return "plain";
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
 * Up to three starters, preferring a domain no earlier pick used and then the
 * shortest query available.
 *
 * Shortest rather than first: within a path the eval set's opening query is its
 * most elaborate, and three long sentences are what made this block unreadable.
 * The domain preference comes first so the starters still span consumer
 * electronics, running and fitness, and home office. Once each admitted path has
 * contributed one, the remaining slots are filled the same way, which is what
 * keeps the count at three now that one path is excluded.
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
 * Shortest of the lane, on the same rule the three run-on-click cards use, so
 * what lands in the composer is short enough to read the misspellings in before
 * pressing send — which is the whole point of putting it there rather than on a
 * button. The entry state had a lexical path and two plain-language ones and no
 * way to reach the third arm without knowing to mistype something.
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
