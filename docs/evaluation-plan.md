# Retrieval evaluation

Mosaic has two evaluation assets with different jobs. They are not
interchangeable.

## Canonical retrieval-quality scorecard

`data/evals/canonical_queries.jsonl` is the authoritative curated set:

- 20 workshop queries with documented teaching concepts;
- graded judgments from 0 (irrelevant) through 3 (ideal);
- explicit hard negatives, expected channels, and ranking behavior;
- 19 single-request product-retrieval cases;
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
`data/evals/canonical_scorecard.json`. The committed scorecard retains all 19
per-query metrics and a SHA-256 identity of the exact ranked product IDs and
positions, excluding volatile event IDs and latency. It also records the clean
source revision, dataset-manifest hash, complete retrieval profile, HNSW
settings, model IDs, Aurora instance identity/class/version, pgvector version,
and measurement timestamp. It fails if any of those inputs, the ranked result
identity, deterministic checks, or metrics drift. Baseline writes refuse a dirty
worktree. Validation requires the measured revision to equal the baseline
revision, except for one later commit whose only changed file is the canonical
scorecard itself; that narrow allowance avoids a self-referential commit while
still rejecting intervening code changes. Use `--write-baseline` only after
committing the reviewed source, reviewing the Aurora ranks, and intentionally
accepting a new measured baseline.

The release sequence is therefore:

1. Commit the reviewed code and configuration.
2. Run `make score-evals SCORE_EVAL_ARGS="--restart --write-baseline"`.
3. Review the ranks and commit only `data/evals/canonical_scorecard.json`.

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
misspelled identity and `pg_trgm` restores it with visible provenance.

## Reproducibility record

For every published scorecard, retain:

- source revision and canonical query-set SHA-256;
- embedding and reranker model IDs;
- retrieval profile and SQL strategy;
- Aurora engine and instance configuration;
- HNSW settings;
- result CSV and measured scorecard JSON.

Latency percentiles, ablation tables, cohort breakdowns, freshness, diversity,
and explanation-completeness rates are useful future production studies. They
are not implemented release metrics and must not be presented as measured
workshop results.
