# Retrieval evaluation

## Why measure the change?

The workshop uses checks to answer a database engineering question: did the SQL
repair change the intended behavior without breaking eligibility or evidence?
A plausible-looking first result cannot answer that question.

| Step | Participant question | Evidence to inspect |
|---|---|---|
| Retrieve | Did a known suitable headphone enter the results after the typo repair? | The target's presence and contributing search method in the saved search |
| Rank | Does fusion use each search method's actual position? | Positions and reciprocal-rank arithmetic before model reranking |
| Reason | Do the recommendation's claims have supporting records? | Product specifications, reviews and resolvable source references |

Use the existing lab mission queries in this order; their single source is
`data/evals/mosaic_labs_missions.json`. Keep the before/after query and filters
identical. These are three checks within Alex's task, not a separate exercise in
benchmark terminology. The broader generated cases stay in release validation.

The active local catalog is `reviews-2023-500k-v1`. The synthetic-catalog
scorecard and generated filter fixtures below are historical engineering checks;
their results do not certify the imported products. Current worked-example
evidence is recorded in [the hybrid-search review](hybrid-search-design.md).

### Compare methods without changing the question

For a new judged request, inspect word search, close spelling, meaning search,
the RRF combined list, then model reranking, in that order. Keep the source
selection, query vector, filters and configured per-method limits fixed.

- **Find:** did each method return any independently reviewed suitable products?
- **Combine:** which suitable rows survived the combined-list cutoff?
- **Reorder:** did suitable rows move up, and did unsuitable rows move down?
- **Decide:** which claims are supported by specifications or reviews?

Keep unchanged winners and regressions. Record request latency and model usage
beside quality; a single warm timing is not a performance benchmark. Review
more than the first result, include multiple acceptable products, and separate
development examples from held-out evaluation requests. Unjudged does not mean
irrelevant. Do not transfer another engine's benchmark gains to Aurora.

RRF combines **positions**, not normalized raw scores. Its constant and list
limits still affect the result. PostgreSQL's `ts_rank_cd` is cover-density
ranking, not BM25; neither BM25 nor SPLADE is added to this workshop.

The following check sets have different purposes. None is evidence of general
production accuracy or representative customer traffic.

## Catalog vocabulary controls

The 12 cases in `data/evals/coverage_queries.jsonl` test a separate decision:
should a request remain searchable, or does it name an absent catalog term?
They pair unknown models and SKUs with existing identifiers and recoverable
misspellings. These are maintainer regression checks, not extra participant tasks.
Vocabulary acceptance does not prove product eligibility or semantic relevance.

After changing catalog text, refresh its vocabulary with
`make db-seed-corpus-lexeme`, then run:

```bash
python scripts/measure_query_coverage.py --write
make test-aurora-invariants
```

The measurement command calls production coverage, records current term counts
and close-spelling matches, and refuses to overwrite a changed expected decision.
Queries, expected decisions and the configured threshold remain unchanged. Review
those expectations separately before altering any of them.

## Canonical retrieval-quality scorecard

`data/evals/canonical_queries.jsonl` is the authoritative curated set:

- 21 workshop cases with documented teaching concepts;
- graded judgments from 0 (irrelevant) through 3 (ideal);
- explicit hard negatives, expected channels, and ranking behavior;
- 20 single-request product-retrieval cases;
- one agent-contract case, `G-021`, validated through Lab 3 rather than
  mis-scored as one product search.

Run the measured release scorecard against Aurora:

```bash
make score-evals
```

This invokes the served retrieval path: indexed PostgreSQL FTS, `pg_trgm`,
pgvector HNSW, pre-fusion SQL filters, unweighted RRF, Cohere Rerank 3.5, and
exact-identity preservation. It measures:

- Recall@10, using judgments graded 2 or 3 as relevant;
- mean reciprocal rank;
- nDCG@10 with graded gain;
- deterministic top-rank or top-k checks for repaired fixtures.

The command writes an ignored per-run CSV and compares the measured result with
`data/evals/canonical_scorecard.json`. The committed scorecard retains all 20
per-query metrics and a SHA-256 identity of the exact ranked product IDs and
positions, excluding volatile event IDs and latency. It also records the clean
source revision, dataset-manifest hash, complete retrieval profile, HNSW
settings, model IDs, Aurora instance identity/class/version, pgvector version,
and measurement timestamp. It fails if any of those inputs, the ranked result
identity, deterministic checks, or metrics drift. Baseline writes refuse a dirty
worktree. Validation requires the measured revision to equal the baseline
revision, except for later commits containing only the generated scorecard, ranked
results and stage-comparison files; that narrow allowance avoids a
self-referential commit while still rejecting intervening code changes. Use `--write-baseline` only after
committing the reviewed source, reviewing the Aurora ranks, and intentionally
accepting a new measured baseline.

The release sequence is therefore:

1. Commit the reviewed code and configuration.
2. Export the live writer class, for example
   `export AURORA_INSTANCE_CLASS=db.r8g.2xlarge`.
3. Run `make score-evals SCORE_EVAL_ARGS="--restart --write-baseline"`.
4. Review the ranks and commit both
   `data/evals/canonical_scorecard.json` and
   `data/evals/canonical_ranked_results.csv`.
5. From that clean commit, run `make ablation-evals`, review the result, and
   commit `data/evals/canonical_stage_ablation.json`.

The runner retries only transient psycopg connection failures for the affected
query. After each completed query it atomically writes an ignored checkpoint
next to the result CSV. A later invocation resumes only when the query set,
source, models, retrieval profile, and Aurora environment still match exactly.
Use `make score-evals SCORE_EVAL_ARGS=--restart` to discard a stale partial run.

## Filter-contract corpus

`data/evals/queries.jsonl` contains 720 generated cases. It tests that each
target exists and satisfies the exact production `SearchFilters` contract,
including integer-cent price bounds and explicit refurbished or sponsored
overrides:

```bash
make validate-evals
```

This is a broad deterministic filter gate, not curated retrieval-quality ground
truth. Do not pass its result CSV to `scripts/evaluate.py` with the canonical
judgments. The evaluator rejects missing or unexpected query IDs so such a
cross-corpus score cannot silently produce zero-valued metrics.

## Typo corpus

`data/evals/typo_cases.csv` contains 5,000 deterministic transformations for
focused fuzzy-retrieval experiments. The required workshop claim remains
narrower: the canonical typo fixture proves that strict FTS misses the
misspelled terms and `pg_trgm` recovers a known suitable product with a visible
search-method contribution. Other eligible headphones are valid alternatives;
this controlled example does not establish that semantic search always fails on
typos.

## Independent relevance corpus

`data/evals/independent_relevance_queries.jsonl` ("IRC") is a third, separately
named corpus. It exists because neither of the corpora above establishes
relevance on unfamiliar queries: the canonical 21-query set is a teaching
fixture pinned to lab missions, and the 720-case filter corpus asserts filter
eligibility, never relevance. Run it with:

```bash
uv run python scripts/independent_relevance_eval.py --validate-only   # no model calls
uv run python scripts/independent_relevance_eval.py                    # measured run
```

The runner reuses production machinery unchanged: `service.retrieval.get_retrieval_service()`
for every search (the same entry point `scripts/score_evals.py` measures),
`scripts.run_eval.validate_query_contract` and `require_single_served_catalog`
for pre-flight eligibility, `scripts.evaluate.evaluate` for Recall/MRR/nDCG
arithmetic, and `scripts.score_evals.search_with_db_retry` for transient
connection retry. It never reimplements retrieval or scoring.

### Split from the canonical set and from the ESCI tuning sweep

`data/evals/esci_judged_subset.json`'s 141 queries are already fully spent:
`scripts/evaluate_esci_k.py` swept RRF's `k` over every one of them, and
`db/config/retrieval.yaml`'s `rrf_k: 60` reflects that sweep. Scoring final
relevance quality on the same queries used to pick a retrieval parameter would
be optimistic by construction, so this corpus does not reuse them, and does not
reuse any canonical-scorecard query text or query_id either. `tests/test_independent_relevance_corpus.py::test_corpus_is_disjoint_from_the_canonical_and_esci_query_sets`
pins this as a permanent check.

### Coverage design: 24 queries, one per cell, and why

The corpus crosses 4 catalog cohorts (`headphones`, `monitor`, `chair`, and
`general` for genuinely cross-category requests) with 6 request-shape cohorts
(`semantic_intent`, `ambiguous_language`, `typo_or_exact_identity`,
`selective_filters`, `competing_preferences`, `unsatisfiable`), one query per
cell, for 4 x 6 = 24 queries. This is a coverage probe, not a statistically
powered sample: per-cohort N is 4 or 6 depending on which axis is aggregated,
far too small for a confidence interval, and the report computes none. Growing
this corpus should add cells -- a new intent shape, a new catalog cohort, or a
second reviewed query per existing cell once Aurora and Bedrock access exist
inside the authoring environment -- rather than duplicating cells for a larger
N with no new coverage.

### The judged-item universe overlaps existing anchors, disclosed by product id

`data/evals/real_catalog_lab_products.json` supplies the 12 real-catalog
products this corpus's judgments are grounded in. Seven of those twelve are
**already judged** somewhere in `canonical_queries.jsonl`, and four of those
seven are the actual `target_product_ids` of a live lab mission
(`data/evals/mosaic_labs_missions.json`):

| Product id | Overlap | Where |
|---|---|---|
| 1208825, 1221817, 1277987, 1408222 | `mission` | Live lab mission target |
| 1138035, 1162128, 1168700 | `canonical` | Judged in `canonical_queries.jsonl`, not a mission target |
| 1248512, 1379290, 1389794, 1481815, 1490476 | `none` | Outside both |

Every judgment carries `"anchor_overlap"` set to one of these three values,
validated at load time against a fresh cross-reference of both source files
(`scripts/independent_relevance_eval.py::compute_anchor_overlap`), so this
table cannot silently drift out of sync with the data. A query whose only
relevant judgments sit on `mission`/`canonical` products is not independent
evidence about this repository's retrieval quality -- those products were
selected for the canonical set or a lab mission *because* they already rank
well for a related query, so a corpus resting on them can pass by construction
rather than by measuring anything new. The `anchor_free` relevance tier (below)
scores only the `none` subset. This is a fact about the judgments themselves,
not about any ranking: **the headphones cohort has zero `anchor_free`-eligible
queries** (pinned by
`tests/test_independent_relevance_corpus.py::test_headphones_cohort_has_no_anchor_free_coverage`) --
all three headphones products with review evidence in this checkout (1138035,
1162128, 1277987) are canonical- or mission-anchored, so every headphones
query's positive evidence rests on an overlapping product. `monitor`, `chair`, and
`general` retain partial `anchor_free` coverage because five of the twelve
products fall outside both anchor sets. Building fresh headphones evidence
(a 13th product with full review text, outside both anchor sets) is the
concrete next step to close this specific gap.

### Judgment status vocabulary, and what a relevance claim requires

Every judgment in this corpus was authored by an automated session, not by a
human or an independent second party. Calling that "reviewed" would misstate
its provenance. The vocabulary is:

- `"agent_grounded"`: the grade is directly traceable to a quoted or
  paraphrased fact in `data/evals/real_catalog_lab_products.json` (the same
  file's `source` field names the exact product). Grounded in evidence, not
  reviewed by a person.
- `"agent_inferred"`: the grade depends on something this authoring
  environment cannot verify offline -- current Aurora-served price or stock
  state, or a brand-tier/price inference rather than a quoted catalog fact.
- `"reviewed"`: reserved for a status a human or an independent second party
  actually sets, recorded with non-empty `"reviewed_by"` and `"reviewed_on"`
  fields that the loader requires whenever a judgment claims this status. **No
  judgment in the committed corpus carries it today.**
- `"esci_human"`: a human-labelled judgment carried over from the licensed
  ESCI Shopping Queries Dataset (Apache-2.0), for the held-out corpus
  described below. Distinct from `"reviewed"` because the reviewer is ESCI's
  original annotation process, not a review of this project's retrieval
  output.

**A relevance claim requires both a measured Aurora run and a `certified`
judgment** (status `"reviewed"` or `"esci_human"`). The runner reports four
tiers side by side:

- `all_inclusive`: every judgment, any status, any anchor overlap.
- `agent_grounded_only`: status `"agent_grounded"` only -- the agent's directly
  quoted claims, excluding its own inferences. Useful as a quality diagnostic,
  **not** a relevance claim, since it is still agent-authored. On the committed
  corpus this tier scores **0 of 4 `competing_preferences` queries** and
  **1 of 4 `selective_filters` queries** -- every `competing_preferences`
  judgment and three of four `selective_filters` judgments rest on an
  unverified price, stock, or brand-tier inference (`"agent_inferred"`), so two
  of the six request shapes have essentially no directly-quoted-fact coverage
  today.
- `certified`: status `"reviewed"` or `"esci_human"` only. **Empty for all six
  request shapes** -- 0 of 24 queries -- because no judgment yet carries either
  status. This is the only tier a relevance claim may cite.
- `anchor_free`: every judgment, any status, but truth restricted to
  `anchor_overlap == "none"` products. See the overlap table above; this is
  what makes an overlap-heavy cohort like `headphones` visibly, separately
  weaker instead of blended into one optimistic number.

A `--validate-only` run, an `all_inclusive` number, an `agent_grounded_only`
number, or any number produced without `DATABASE_URL` and Bedrock access is
code completion over fixture data, not a relevance measurement, and must be
labeled as such. A genuine relevance claim needs a `certified`-tier score from
a measured Aurora run -- which requires either a human reviewing existing
judgments (setting `"reviewed"`/`reviewed_by`/`reviewed_on`) or the held-out
ESCI corpus described next.

### No-relevant-item and incomplete-judgment treatment

A query with `"expect_no_relevant_results": true` is `unsatisfiable`: nothing
in the reviewed evidence satisfies it, so Recall/MRR/nDCG are mathematically
undefined for it (there is no relevant item to rank) and the runner never
computes them there. It is instead scored on whether the service's own
declared hard negatives leaked into the returned window, and on its result
count, reported under `empty_result_behavior`, separate from the relevance
metrics.

A query that is *not* unsatisfiable but carries no judgment graded 2 or 3 is a
`judgment_gap`: the corpus does not yet have enough review to score it. It is
excluded from every relevance metric, and its `query_id` is printed under
`denominator.judgment_gap_query_ids` in the report -- never silently absorbed
into a shrinking "relevant found" count. A query that fails to run (a raised
exception after retry) is likewise excluded from every metric it would have
contributed to, listed by name under that tier's `excluded_due_to_failure`, and
counted in `denominator.queries_failed`. The report always prints
`queries_attempted` beside every scored count, so a shrunken denominator is
always visible, per the house rule that a check must never hide a failure by
narrowing what it counts.

### Held-out ESCI corpus (file contract; not generated by this repository)

The `certified` tier can also be populated without waiting on a human
reviewer: a maintainer who holds the ESCI `examples.parquet` locally, working
against the `reviews-2023-v2` catalog (which admits more judged queries than
the 141 already spent on `scripts/evaluate_esci_k.py`'s tuning sweep), can
build a second corpus this runner is already able to score. This repository
does not generate that file -- doing so needs the parquet file and Aurora
access this checkout does not have -- but `scripts/independent_relevance_eval.py`
is ready for it today:

```bash
uv run python scripts/independent_relevance_eval.py \
  --queries data/evals/esci_held_out_queries.jsonl --validate-only
uv run python scripts/independent_relevance_eval.py \
  --queries data/evals/esci_held_out_queries.jsonl
```

File contract for `data/evals/esci_held_out_queries.jsonl`:

- Same record shape as `independent_relevance_queries.jsonl` (see
  `REQUIRED_QUERY_FIELDS`).
- Each **record** additionally carries `"esci_query_id"`: the raw integer
  query id from the ESCI source dataset, distinct from this corpus's own
  namespaced `"query_id"` (for example `"ESCI-HELDOUT-9001"`).
- Each judgment: `"status": "esci_human"`, `"grade"` mapped from the ESCI
  label via `esci_grade()` (`E`=3, `S`=2, `C`=1, `I`=0 -- a grading scale
  distinct from `scripts.evaluate_esci_k.GAINS`'s continuous nDCG gains, which
  serve RRF-`k` tuning, not this corpus's grading), `"source": "esci"`,
  `"license": "Apache-2.0"`, and `"anchor_overlap"` computed the same way as
  every other judgment (almost always `"none"`, since ESCI-judged products are
  not drawn from the mission/canonical anchor set named above).
- Before scoring, run
  `require_disjoint_from_tuning_sources(records)` (imported from
  `scripts.independent_relevance_eval`) against the loaded records: it fails
  loudly if any `esci_query_id` was already spent by `esci_judged_subset.json`'s
  141 tuning queries, or if any `query_id` collides with the canonical
  scorecard's `G-*` ids.
  `tests/test_independent_relevance_eval.py` proves this check, and the
  `esci_grade` mapping, against small synthetic fixtures -- never against real
  ESCI data.

### Licensing and provenance

Every judgment traces to `data/evals/real_catalog_lab_products.json`, which
itself carries **unmodified source fields** from the served
`reviews-2023-500k-v1` catalog (Amazon Reviews 2023). No ESCI or WANDS record
is copied into `independent_relevance_queries.jsonl`; both remain confined to
their existing, separately licensed uses
(`data/evals/references/README.md`, `scripts/prepare_esci_judged_subset.py`)
until a maintainer builds the held-out ESCI corpus described above, which
would carry its own `"source": "esci"` / `"license": "Apache-2.0"` tags per
judgment.

## Reproducibility record

For every published scorecard, retain:

- source revision and canonical query-set SHA-256;
- embedding and reranker model IDs;
- retrieval profile and SQL strategy;
- Aurora engine and instance configuration;
- HNSW settings;
- result CSV and measured scorecard JSON.

Latency percentiles, cohort breakdowns, freshness, diversity,
and explanation-completeness rates are useful future production studies. They
are not implemented release metrics and must not be presented as measured
workshop results.

## Limits of the current judgments

The curated scorecard checks intentionally selected cases and a small set of
judged products. It is a regression suite, not a blind benchmark of all 500,000
products. Unjudged products may be suitable. The historical catalog and queries
shared synthetic authoring assumptions; importing real records does not by itself
make new queries representative. A higher score alone does not establish better
customer outcomes. Inspect each changed ordering and its source records.

A workshop repair may improve the intended stage while leaving the first result
unchanged. The wheel-free chair controls in the current review demonstrate this.
The required monitor request instead loses its documented fit before reranking
when fusion is broken. Inspect the actual intermediate rows in both cases.

For a production adaptation, collect independent user requests, label multiple
suitable and unsuitable results, hold out cases from tuning, and retain explicit
checks for empty results, unsupported claims and filter violations. Agent answer
quality needs separate claim/evidence checks; a retrieval score cannot certify it.

The 720 generated fixtures assert product existence and exact filter eligibility.
Their text names the filter values, including false booleans and exact numeric
values. They are useful for detecting schema and filter regressions, but do not
measure natural-language understanding, ranking quality or realistic demand.

## Historical synthetic-catalog judgment review

The reviewed cases distinguish filter eligibility from satisfying the request.
The broad headphone typo query accepts several ANC models; its lab target is a
known suitable option used to expose the disconnected spelling-search path.
A cheaper 4K monitor without USB-C charging is a comparison option, not an
equivalent match for a request that requires laptop charging. Ten-hour chair recommendations fall short of an explicit twelve-hour
request. Armrest count and price do not break ties when the request never asks
for them. Watch battery language names smartwatch mode, and the webcam case no
longer assumes platform certifications that the description disclaims.

These judgment and query changes require a new measured baseline. Scores from
before and after this revision are not a controlled comparison of the retrieval
algorithm: both the catalog and the definitions of relevance changed.

A hard requirement needs an explicit supported SQL predicate. A preference in
free text can influence ordering without becoming an eligibility guarantee.
For example, a twelve-hour chair request with only a seat-depth filter can still
retrieve a ten-hour alternative; its lower relevance grade does not make that
row a SQL-filter violation. This distinction is part of the workshop's database
lesson, not something a model score can enforce on the database's behalf.
