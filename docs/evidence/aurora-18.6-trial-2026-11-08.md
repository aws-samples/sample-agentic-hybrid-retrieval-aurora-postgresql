# Aurora PostgreSQL 18.6 trial, 8 November 2026

These checks ran against an **uncommitted working tree** based on
`c75ed938`: the database template pins `EngineVersion: '18.6'`, the vocabulary contract
records `server_version_num` 180006, `InfrastructureRevision` is `fcfa9ff0fd4cc520`, and
`tests/test_aurora_engine_pin.py` holds the pin and the contract together. This record is
not a Workshop Studio build, a fresh-cluster CloudFormation create or a fresh-event walk.

## Trial database

`mosaic-pg186-trial` was a copy-on-write clone of the development cluster (553,911 products,
all embedded) with one `db.r8g.2xlarge` writer and its own temporary security group. It was
deleted after the checks.

| | Before | After |
|---|---|---|
| `server_version`, `server_version_num` | 18.3, 180003 | 18.6, 180006 |
| `aurora_version()` | 18.3.5 | 18.6.1 |
| pgvector `extversion` (`default_version`) | 0.8.1 (0.8.1) | 0.8.1 (0.8.2), then 0.8.2 after `ALTER EXTENSION vector UPDATE TO '0.8.2'` |
| pg_trgm | 1.6 | 1.6 |
| HNSW indexes valid | 3 of 3 | 3 of 3 |

Aurora does not update extensions during an engine upgrade. A fresh 18.6 cluster's
`CREATE EXTENSION vector` takes the default, 0.8.2.

## Vocabulary cache

- `corpus_vocabulary.py export` on 18.6 took 971.5 s and found 0 row differences:
  `corpus_lexeme` 2,200,149 rows and `corpus_surface_lexeme` 2,251,580 rows.
- Decompressed, both files are byte-identical to the published 18.3 files (SHA-256
  `938ed6d8...` and `a6d74095...`). The compressed files have the same sizes; their hashes
  differ only because gzip records the write time.
- Only the contract's `server_version_num` changes. The published files stay, because
  `real-catalog/vocabulary/` is one prefix that every Workshop Studio build reads; new files
  would fail the 18.3 build's hash check.
- The bootstrap's restore path (`refresh` with `MOSAIC_VOCABULARY_CACHE_DIR` set to the
  published files) passed on 18.6 in cache mode in 39.8 s.

## Gates on 18.6

| Gate | Result |
|---|---|
| `MISSION_GATE_REQUIRE_DB=1 make validate-missions` | 126 checks passed |
| `make validate-evals` | 17, 65 and 2,081 judged targets pass `matches_filters`; 24- and 404-query corpora valid |
| `make test-aurora-contracts` | 180 passed |
| `make test-aurora-invariants` | 99 passed |
| `make test` | 3,426 passed, 0 skipped |
| `FUNCTION_CENSUS_REQUIRE_DB=1 make validate-functions` | 15 functions, one live signature each |
| `make db-verify-bootstrap` | 553,911 products, 553,911 embedded, 0 foreign, 0 synthetic |
| `make check-shop-collection`, `check-hnsw-anchors`, `check-exact-neighbors` | 40/40/40; 73 anchors; 438 of 438 pairs |
| `make validate`, `validate-db`, `validate-release-workflow` | passed |
| `make score-evals` | see below |

## Retrieval compared with 18.3

Each of the 19 searches the gates ran on 18.6 was paired with the latest development-cluster
search on 18.3 with the same query, filters, retrieval profile, strategy and HNSW settings.

- 11 pairs whose 18.3 search ran after the semantic-sort fix (`14109005`, 7 November,
  16:45 UTC) are identical in all 50 stored rows and every channel rank.
- 8 pairs whose 18.3 search ran before that fix (the latest on 1 November) differ in
  semantic and fused ranks. Their final order does not change: "noise cancelling
  headphones" has one final order across all 22 runs, and "... under $300" shows the same
  two final orders on both versions.
- With the live query vector, all 31 shared semantic scores are equal on both versions.
  Against exact filtered nearest neighbours on 18.6, every differing product's 18.6 rank is
  within one place of exact, while the pre-fix 18.3 ranks were off by up to 39 (product
  1528839: exact 58, 18.6 58, 18.3 97). The 18.6 HNSW channel returned 145 of the exact
  150.

## Canonical scorecard

`score-evals` refuses a dirty tree, so it ran from a clean worktree at `c75ed938` against the
clone. Eight of the nine scored queries rank identically to the committed baseline. The
baseline was measured on 7 November at 18:45 UTC on a fresh event's writer
(`hybrid-retrieval-main-databasesta-dbinstancewriter-7ekb3f54mwyb`). G-022 differs: the
baseline has product 1523070 at rank 4, and 18.6 has 1540594 at rank 10. The development
cluster's own three 18.3 runs of G-022 on 7 November (16:46 to 16:57 UTC) match the 18.6
run in all 50 rows, channel ranks and rerank scores. The difference is between the fresh
event's HNSW graph and the development cluster's, not between engines, and the development
cluster on 18.3 already differs from that baseline the same way. A new baseline belongs to
the fresh-event walk of the 18.6 build.

## Not proven here

- A fresh cluster created by the CloudFormation template at 18.6, and the full bootstrap on it.
- An HNSW build on pgvector 0.8.2, including `mosaic-hnsw-prepare`; the clone kept its index.
- A Workshop Studio build, the own-account deploy and a fresh-event walk.
