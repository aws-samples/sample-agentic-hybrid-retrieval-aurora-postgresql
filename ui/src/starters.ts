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
 * queries, which are all long, filter-laden and all FTS-led, so the two
 * retrieval paths the workshop exists to teach - trigram recovery and
 * vector-only intent - never appeared. Picking one query per retrieval path
 * instead puts the contrast in the first thing anyone sees.
 */

/** Display order. It matches the retrieval primer in the lab guides. */
const starterPaths = ["exact", "misspelled", "plain"] as const;

export type StarterPath = (typeof starterPaths)[number];

export const starterPathLabels: Record<StarterPath, string> = {
  exact: "Exact terms",
  misspelled: "Misspelled",
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
 * One starter per retrieval path, preferring a domain no earlier pick used and
 * then the shortest query available.
 *
 * Shortest rather than first: within a path the eval set's opening query is its
 * most elaborate, and three long sentences are what made this block unreadable.
 * The domain preference comes first so the three starters still span consumer
 * electronics, running and fitness, and home office.
 */
export function starterExamples(
  examples: RetrievalExample[],
): RetrievalExample[] {
  const usedDomains = new Set<Domain>();
  const picks: RetrievalExample[] = [];
  for (const path of starterPaths) {
    const lane = examples.filter((example) => starterPath(example) === path);
    const unusedDomain = lane.filter(
      (example) => !usedDomains.has(example.domain),
    );
    const pool = unusedDomain.length ? unusedDomain : lane;
    if (!pool.length) continue;
    const pick = pool.reduce((shortest, example) =>
      example.query.length < shortest.query.length ? example : shortest,
    );
    picks.push(pick);
    usedDomains.add(pick.domain);
  }
  return picks;
}
