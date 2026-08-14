# Retrieval evaluation

Mosaic has two evaluation assets with different jobs. They are not
interchangeable.

## Canonical retrieval-quality scorecard

`data/evals/canonical_queries.jsonl` is the authoritative curated set:

- 20 workshop queries with documented teaching concepts;
- graded judgments from 0 (irrelevant) through 3 (ideal);
- explicit hard negatives, expected channels, and ranking behavior;
- 19 single-request product-retrieval cases;
- one agent-contract case, `G-010`, validated through Lab 3 rather than
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
positions, excluding volatile event IDs and latency. It fails if the query set,
ranked result identity, model IDs, retrieval strategy, deterministic checks, or
metrics drift. Use `--write-baseline` only after reviewing the Aurora ranks and
intentionally accepting a new measured baseline.

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
