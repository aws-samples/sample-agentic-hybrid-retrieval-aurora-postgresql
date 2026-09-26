# Historical synthetic fixtures

The three product shards and `manifest.json` in this directory describe the
historical 500,000-product synthetic catalog. They are regression fixtures;
they are not the products served by Mosaic or loaded into fresh workshops.
The sample products, generated reviews, taxonomy and premium-cohort media used
by those fixtures have the same historical scope.

Mosaic restores **553,911 real source products and their saved Cohere vectors**
from the archive pinned in
[`db/config/real-catalog-cache.json`](../../db/config/real-catalog-cache.json).
Follow [the restore contract](../../ARTIFACTS.md). Do not run a generator,
synthetic loader or embedding job to prepare a participant environment.

## Why these files remain

`scripts/validate_package.py`, `tests/test_dataset.py` and catalog-semantics
tests still validate these fixtures and their hashes. Removing the shards
requires retiring those dependencies and their historical contracts together.
Moving or deleting them alone would break offline validation.

## Historical maintenance only

The Make targets for generation, normalization, synthetic product/review/cohort
loading, and the historical embedding cache require
`ALLOW_HISTORICAL_CATALOG=1`. They also reject a nonempty
`MOSAIC_CATALOG_DATASET`. This is an explicit operator opt-in, not database
isolation: use a separate historical Aurora database and review `.env` before
running scripts directly. Direct Python or SQL invocations do not pass through
the Make guard.

Read-only fixture validation needs no opt-in. The workshop path
`make db-bootstrap-schema` followed by the pinned real-catalog restore needs
no historical catalog, vocabulary, reviews or embeddings.
