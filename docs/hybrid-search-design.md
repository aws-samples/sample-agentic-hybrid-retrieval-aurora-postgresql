# Hybrid search: one question, three engineering checks

Mosaic helps Alex finish his office. The same request passes through three
checks: **find suitable products → put them in a useful order → justify the
recommendation from records**. A different dataset or a more elaborate model is
not a substitute for demonstrating those checks.

## What we adopted from the reading

The [Awesome Search overview](https://frutik.github.io/awesome-search/Concepts/Hybrid-Search)
and [Prem article](https://www.premai.io/blog/hybrid-search-for-rag-bm25-splade-and-vector-search-combined/)
are useful starting points for questions to test, not evidence of Mosaic's gains.
The implementation remains native PostgreSQL FTS, `pg_trgm`, pgvector, RRF and
bounded model reranking. There is no new search engine or embedding generation.

| Stage | Mechanism in this workshop | What participants inspect |
|---|---|---|
| Find by words | `websearch_to_tsquery`, GIN, `ts_rank_cd` | Matching indexed words, including normalized word forms |
| Find by spelling | `pg_trgm`, GIN | Whether a transposed listing identifier is recovered |
| Find by meaning | Cohere query embedding, pgvector HNSW | Related products found without identical wording |
| Combine | Sum `1 / (k + source_rank)` per product | Which rows survive the configured cutoff |
| Reorder | Cohere Rerank on the combined list | Whether product text addresses the complete request |
| Support the answer | Product-scoped specifications and reviews | What each cited record actually establishes |

Filters apply within every retrieval method. RRF uses positions because the
methods' raw scores have different meanings. It is not parameter-free and does
not guarantee an improvement. A reranker cannot recover a row excluded from its
input. A high score or a resolving citation does not prove every claim.

Primary references: [PostgreSQL ranking](https://www.postgresql.org/docs/current/textsearch-controls.html#TEXTSEARCH-RANKING),
[pg_trgm](https://www.postgresql.org/docs/current/pgtrgm.html),
[original RRF paper](https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf),
[pgvector filtered search](https://github.com/pgvector/pgvector#filtering).
PostgreSQL's built-in cover-density ranking is not BM25. The Prem article's
vendor benchmark percentages, automatic switch-to-weighted-fusion rule and
SPLADE architecture are not workshop results or requirements.

## Current evidence — 22 September 2026

See [the verification record](evidence/hybrid-search-review-2026-09-22.json).
It identifies the selected catalog, source SQL, models, settings and saved runs.

**Catalog repair.** Explicit source taxonomy leaves were missing from the
product-type mapping. The correction includes on-ear/earbud/open-ear headphones,
headsets, guest/drafting/stacking chairs and chair-mat subtypes. In Aurora,
13,906 derived category values changed. Every other search column on those rows
was checked unchanged, including vector values and source text. No embedding was
regenerated. A second pass changed zero rows; a stale plan was rejected.

| Filter | Before | After |
|---|---:|---:|
| Headphones | 2,591 | 15,894 |
| Chairs | 362 | 643 |
| Chair mats | 12 | 334 |
| Monitors | 2,876 | 2,876 |
| Headphone cases | 6,497 | 6,497 |

These are taxonomy counts, not an assertion that all source categories are
correct. For example, source `B07411X4HB` describes a cable/adapter but is filed
under headphones in the upstream metadata. Preserve that record; flag the
category conflict during relevance review. Source category membership alone
cannot establish suitability. Cases, pads and other explicit accessory leaves
remain separate; mixed or ambiguous categories are not inferred from compatible
product names.

**Twelve paired SQL observations.** Four unchanged requests were evaluated in
three states: repaired, spelling connection missing, and RRF contribution broken.
They used shipped SQL in rollback-only transactions in `mosaic_catalog_search`,
production HNSW settings and the managed reranker. The served
`mosaic_live_search` functions were not broken by this comparison. These probes
are not full API, agent, or participant-environment acceptance.

- The current Bose-ID request loses its known listing with spelling disconnected
  and recovers it after repair. This is an identity example, not a claim that all
  other headphones lack noise cancellation.
- The current monitor request loses the 90W Dell before reranking with the RRF
  defect. Corrected fusion admits it and the reranker puts it first. The exact
  combined position varies; inspect each run rather than memorizing a rank.
- Both wheel-free chair requests keep the same first result with broken and
  repaired fusion. They are useful controls, not replacements for the required
  before/after exercise.

**Six paired API runs.** Each required retrieval repair was also tested through
the running API: broken, repaired, then repaired again with the same request and
filters. The saved full lists contain 50 products each. The Bose is absent before
repair and returns in combined position 2, then final position 1. The Dell is
absent before repair and returns in combined position 24, then final position 1.
Both repaired runs repeat those positions. The live function definitions were
restored byte-identically after this controlled comparison. These observations
are distinct from the SQL probes, which used different condition filters.

**Completion checks.** All three lab validators passed through the running API,
including the independent retrieval controls and Lab 3's separate source-checking
request. The mission contract passed 110 checks against Aurora. A live connection
test also confirmed that an expired idle socket is replaced before the next
transaction; removing the checkout check reproduced the failure. Saved receipts
and test scopes are in the verification record.

This does not establish a new whole-catalog scorecard or a fresh-account
rehearsal. The Workshop Studio guide tests pass, but its full package validator
remains blocked by the pre-existing bootstrap asset hash mismatch. No source
commit, push or Workshop Studio publication was performed in this review.

## How the datasets help

Keep Amazon Reviews 2023 as the working corpus. It already supplies the product
text, photos and source identities in Aurora. No additional mass import is
justified by the present exercise evidence.

- **Full ESCI:** mine natural requests and human judgments, then join by exact
  product/locale identity and independently read the source. A judged product
  absent from this selected corpus cannot be counted as a retrieval miss.
  Parent-product and variant identities are not interchangeable. Contradictory
  labels are excluded from the teaching set with the reason retained.
- **WANDS:** useful for a separate furniture/compatibility evaluation. Its
  dual-monitor-stand versus single-monitor-stand example is visually understandable,
  but those records and images are not part of this Aurora catalog. Do not
  present its relevance labels as a demonstrated Mosaic ranking failure.
- **Home Depot:** useful for studying search judgments and specification wording.
  Its hardware focus is less aligned with the required office story; importing it
  would expand preparation without a validated improvement to these three labs.

Sources: [Amazon ESCI](https://github.com/amazon-science/esci-data),
[Wayfair WANDS](https://github.com/wayfair/WANDS),
[Home Depot competition](https://www.kaggle.com/competitions/home-depot-product-search-relevance).
These sources describe datasets, not redistribution clearance for all associated
retail text or images. Existing source/asset release review remains separate.

## Keep the hour focused

Keep the required mission requests and timing in
`data/evals/mosaic_labs_missions.json`. The guides and Playground use the same
stage order and place deeper explanation in expandable sections. No additional
mandatory defect is introduced. The optional comparison asks builders to hold
query, filters, text and per-method limits fixed, then compare word search,
meaning search, combined results and reranking. Retain unchanged winners and
regressions, and measure extra latency/model usage alongside relevance.

Before replacing any required example, prove its source facts, an observable
failure caused by that lab's code defect, recovery with the identical request,
and unaffected independent controls. Update the mission, guides, UI, slides
and notes together after that proof. Neither a better-looking top result nor
adding more products satisfies this acceptance rule.
