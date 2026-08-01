# Controlled database-incident corpus

`seed/corpus.py` creates a deterministic, synthetic operational corpus for the
DAT410 builders' session. It is realistic enough to exercise PostgreSQL
retrieval and relationship traversal, but it is not customer data and must not
be presented as an actual AWS Support case.

The canonical evidence thread is:

- `INC-2047`: checkout writes stalled on `checkout-prod-cluster-01`.
- `CHG-1842`: ordinary `CREATE INDEX` blocked writes.
- `LOCK-2047-001` and `LOCK-2047-002`: controlled lock snapshots.
- `CASE-7419`: visible customer impact and response commitment.
- `CASE-7421`: relevant evidence classified `restricted`, plus a six-object
  restricted cohort (`CASE-8102`, `CASE-8137`, `INC-3162`, `INC-4117`,
  `CHG-6213`, `CHG-3309`) spanning three evidence kinds. Visibility is decided by
  `acl.visibility` and the `can_see_restricted` clearance, never by a
  caller-supplied identity.
- `RB-017`: the `CREATE INDEX CONCURRENTLY` recovery guidance and caveats.

`casework.*` is the normalized source-of-record fixture. The search-index builder
renders versioned `retrieval.documents` and `retrieval.chunks`, reuses cached
embeddings by content hash, and records each build. `proof.*` stores retrieval,
ranking, answer, citation, and evaluation receipts.

For an offline local corpus:

```bash
make schema
make seed-local
```

The workshop path uses a precomputed Cohere Embed 4 cache and a packaged
PostgreSQL restore artifact. Regenerate those release artifacts only after the
corpus and target Aurora PostgreSQL engine version are frozen.

## Embedding cache

`seed/artifacts/casework-embeddings.jsonl` holds one vector per unique chunk,
keyed by `sha256(model_id \0 chunk_text_hash)`. The builder never embeds
implicitly: a cache miss raises unless `--embed-missing` is passed. Every
workshop account therefore loads the same vectors instead of paying for its own
Bedrock embedding pass, and identical vectors are what make ranking identical
across accounts.

`casework-embeddings.jsonl.manifest.json` records the entry count, dimensions,
and a content digest taken over every key and vector in sorted key order. The
digest ignores JSON formatting and line order, so it only changes when a vector
changes. `make seed-casework` passes `--verify-cache`, which fails the build if
the cache and manifest disagree — a truncated download would otherwise degrade
ranking for one account with no visible error.

The cache holds exactly the vectors the release corpus needs, one per unique
chunk. `make seed-local` uses `--provider hash`, whose vectors are not real
embeddings, so it defaults to a separate scratch cache under `data/generated/`.
Test seeding must never write to the release artifact: passing `--embed-missing`
at the release path without `--write-cache-manifest` is refused, because it
would leave the shipped manifest stale.

Regenerate after the corpus changes:

```bash
# 1. Embed the new chunks. Billable, and only new content hashes are sent.
backend/scripts/build_search_index.py --load-casework \
  --capture-bundle <bundle> --require-release-capture \
  --embed-missing --write-cache-manifest

# 2. Confirm the manifest matches on a clean load.
backend/scripts/build_search_index.py --load-casework \
  --capture-bundle <bundle> --require-release-capture --verify-cache
```

The two steps cannot be collapsed: verification runs before indexing, so a run
that also embeds would only verify the file it was about to change.

Commit the cache and its manifest together. A manifest that does not match its
cache fails every account's load, which is the intended outcome.

## Packaged restore artifact

The Workshop Studio stack does not run `make seed-casework`. It restores a
`pg_dump` artifact so no participant account calls an embedding model at
provision time and every account ranks identically.

Produce the artifact from a disposable database, never the live cluster:

```bash
# 1. Seed a throwaway database from the frozen corpus and embedding cache.
DATABASE_URL=postgresql://.../scratch_db make schema
DATABASE_URL=postgresql://.../scratch_db make seed-casework CAPTURE_BUNDLE=<bundle>

# 2. Dump it. Refuses if the index is not ready or sql/, seed/, or
#    backend/app/ has uncommitted changes.
DATABASE_URL=postgresql://.../scratch_db make seed-dump
```

`seed/dump.sh` writes `seed/artifacts/hybrid-retrieval-seed-v2.dump` plus a
`.revision` sidecar naming the commit that produced it. Both are gitignored:
they travel in the Workshop Studio source archive, not in git.

`seed/load.sh` (`make seed-restore`) is the consumer, and it is what the CFN
`SeedDatabase` step invokes. It restores tables and data from the dump, then
re-applies `sql/02` through `sql/10` from the checkout, because the retrieval
functions and views are the contract and the checkout owns them. It
deliberately does not re-run `sql/01_schema.sql`: replaying table DDL over
restored rows patches column drift silently instead of surfacing it. When the
dump's revision does not match the checkout, it warns; when readiness fails
after restore, it exits non-zero and stops provisioning.

Rebuild the artifact whenever `sql/01_schema.sql`, the corpus, or the embedding
cache changes. An artifact from an older schema generation restores tables the
current functions do not match.
