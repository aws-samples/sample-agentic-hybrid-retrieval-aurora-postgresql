/**
 * The one customer-facing vocabulary for the retrieval pipeline, and the one
 * place it is bridged to the Postgres mechanism behind it.
 *
 * Six surfaces printed their own words for the same five things. A product card
 * said "Exact terms", the Ask Mosaic shortlist said "Your exact words", its
 * ranking disclosure said "FTS", the search receipt said "FTS" or "Exact terms"
 * depending on a boolean, the agent receipt always said "FTS n / TRGM n / HNSW
 * n", and the Playground matrix said "Exact words". A shopper met four names for
 * one retriever and an engineer could not tell which of them was the mechanism.
 *
 * Shop and Discover print `label`. The Playground prints `label` and `mechanism`
 * together, which is the whole bridge it exists to make. Nothing else invents a
 * third form.
 */

export type RetrievalArm = "fts" | "trigram" | "semantic";

export interface ArmLanguage {
  key: RetrievalArm;
  /** What a shopper reads. */
  label: string;
  /** The PostgreSQL feature, named for an engineer. Playground only. */
  mechanism: string;
}

export const armLanguage: ArmLanguage[] = [
  {
    key: "fts",
    label: "Exact terms",
    mechanism: "PostgreSQL Full-Text Search",
  },
  {
    key: "trigram",
    label: "Close spelling",
    mechanism: "pg_trgm",
  },
  {
    key: "semantic",
    label: "Meaning match",
    mechanism: "pgvector / HNSW",
  },
];

export const armLabel: Record<RetrievalArm, string> = {
  fts: "Exact terms",
  trigram: "Close spelling",
  semantic: "Meaning match",
};

/** The two ordering stages, in the same customer vocabulary. */
export const FUSED_LABEL = "Before reranking";
export const FINAL_LABEL = "Final position";

/**
 * The `candidate_counts` keys each arm reports, so a caller reading counts and a
 * caller reading per-row ranks cannot disagree about which arm is which.
 */
export const armPoolKey: Record<RetrievalArm, string> = {
  fts: "fts_in_pool",
  trigram: "trigram_in_pool",
  semantic: "semantic_in_pool",
};

/**
 * The PostgreSQL index each arm reads, named once.
 *
 * Two surfaces need this map for different questions -- the channel map asks
 * "is this arm's index healthy", the lab outcome asks "is the index this lab
 * needs missing" -- and a second copy is how one of them would come to name an
 * index the deployment does not have.
 */
export const armIndexName: Record<RetrievalArm, string> = {
  fts: "product_document_fts_gin_idx",
  trigram: "product_document_trigram_gin_idx",
  semantic: "product_document_embedding_hnsw_cosine_idx",
};

/**
 * Which `expected_techniques` tokens name each arm in the eval fixtures.
 *
 * `hnsw` belongs to the semantic arm: the fixtures name that arm after the index
 * it reads rather than after the retriever, and Labs 2 and 3 use only that
 * spelling. Without it those two labs required no semantic arm at all, so the
 * one index they cannot run without was never checked and a meaning-match arm
 * that contributed nothing to their pool read as an arm with nothing to say.
 */
export const armTechniques: Record<RetrievalArm, string[]> = {
  fts: ["fts", "lexical"],
  trigram: ["pg_trgm", "trigram"],
  semantic: ["vector", "semantic", "hnsw"],
};

/** The arms a scenario's `expected_techniques` says the run had to produce. */
export function requiredArms(expectedTechniques: string[]): RetrievalArm[] {
  return armLanguage
    .map((entry) => entry.key)
    .filter((arm) =>
      armTechniques[arm].some((technique) => expectedTechniques.includes(technique)),
    );
}
