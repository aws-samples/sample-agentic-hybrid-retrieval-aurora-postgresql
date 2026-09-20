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

There are three distinct engineering check sets. None is evidence of general
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
products. Unjudged products may be suitable, and the catalog and queries share
synthetic authoring assumptions. A higher score alone does not establish better
customer outcomes. Inspect each changed ordering and its source records.

A workshop repair may improve the intended stage while leaving the final answer
unchanged: Lab 2 deliberately demonstrates this when reranking masks broken
fusion. Check the intermediate positions, not just the final score.

For a production adaptation, collect independent user requests, label multiple
suitable and unsuitable results, hold out cases from tuning, and retain explicit
checks for empty results, unsupported claims and filter violations. Agent answer
quality needs separate claim/evidence checks; a retrieval score cannot certify it.

The 720 generated fixtures assert product existence and exact filter eligibility.
Their text names the filter values, including false booleans and exact numeric
values. They are useful for detecting schema and filter regressions, but do not
measure natural-language understanding, ranking quality or realistic demand.

## Judgment review for this catalog revision

The reviewed cases distinguish filter eligibility from satisfying the request.
The broad headphone typo query accepts several ANC models; its lab target is a
known suitable option used to expose the disconnected spelling-search path.
A scissor-switch keyboard is only a partial match for a mechanical-keyboard
request. Ten-hour chair recommendations fall short of an explicit twelve-hour
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
