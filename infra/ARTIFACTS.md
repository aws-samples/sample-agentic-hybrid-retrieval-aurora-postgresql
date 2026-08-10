# Canonical build artifacts

Single source of truth for the environment the workshop restores and the
embedding cache that fills it. The Phase 1–4 specs and both agents reference
this file rather than restating any value.

Every number here was verified locally on 2026-08-09, not transcribed from a
report. The verification commands are given so any reader can reproduce them.

## Aurora snapshot

| Field | Value |
|---|---|
| Snapshot ID | `mosaic-catalog-500k-cohere-v4-20260809` |
| Status | available |
| Visibility | private |
| Encryption | **unencrypted** — see the decision below |
| Engine | Aurora PostgreSQL 18.3 |
| Schemas | `mosaic`, `mosaic_search` only |
| Corpus | 500,000 products, 1,024-dimensional Cohere Embed v4 vectors |
| Shared with | no accounts yet |

The snapshot is the canonical environment. Measurements that depend on plan
choice, index behavior, or latency must run against a snapshot-restored
database, never against partially loaded local data. Local PostgreSQL is for
unit-level SQL checks only.

`catalog.*` no longer exists on Aurora. Anything still targeting it
(`tests/test_sql_integration.py`, `scripts/run_eval.py`,
`scripts/benchmark_hnsw.py`, `sql/*.sql`) is legacy and scheduled for deletion
in Phase 2; see `docs/superpowers/specs/2026-08-09-phase1-stop-the-bleeding-design.md`
item 1.4.

## Embedding cache

| Field | Value |
|---|---|
| Manifest | `build/embedding-cache/manifest.json` |
| Manifest SHA-256 | `134d255b14d72bcf955d5e1bde93bf4982543506464844f91291e1c84b22fc8c` |
| Schema version | 1 |
| Embedding model | `us.cohere.embed-v4:0` |
| Dimensions | 1024 |
| dtype | float32 |
| Shards | 50 × `embeddings-000NN.npz` |
| Vectors | 500,000 |
| Size | 1.94 GiB |
| Catalog content digest | `63ad5fda987b9a743d63a2ccff77b8dd8650d01133e1f5e9b3f0d29f8bebb7ae` |
| Generated | 2026-08-10T02:12:14Z |
| S3 destination | **not yet set** — `EMBEDDING_CACHE_URI` is unassigned |

Per-shard records carry `path`, `count`, `first_product_id`, `last_product_id`,
`size_bytes`, and `sha256`. The field is named `sha256` and holds a 64-character
SHA-256 digest.

The cache exists so a workshop environment can be built without calling Bedrock.
`make db-bootstrap-cached` installs the schema, loads the catalog, imports these
vectors, and builds the HNSW indexes.

### Verification

Independent re-verification, 2026-08-09:

```
CACHE INTEGRITY: shards ok=50 mismatched=0 missing=0
vectors=500,000 (manifest claims 500,000)  bytes=1.94 GiB
```

Every shard's SHA-256 and `size_bytes` matched. Reproduce with:

```bash
python - <<'PY'
import json, hashlib, pathlib
d = json.load(open("build/embedding-cache/manifest.json"))
base = pathlib.Path("build/embedding-cache")
ok = bad = miss = 0
for s in d["shards"]:
    p = base / s["path"]
    if not p.is_file():
        miss += 1
        continue
    matched = (
        hashlib.sha256(p.read_bytes()).hexdigest() == s["sha256"]
        and p.stat().st_size == s["size_bytes"]
    )
    ok += matched
    bad += not matched
print(f"ok={ok} mismatched={bad} missing={miss}")
PY
```

A 10,000-vector restore probe passed as part of the cache build.

## Decision: the snapshot is unencrypted

Conscious choice, not an oversight. An unencrypted snapshot can be shared
across accounts without also sharing a KMS key and granting key-usage grants to
every recipient, which is what makes event-scale Workshop Studio distribution
tractable.

Acceptable because the corpus carries no secret: all 500,000 products are
synthetic, generated from seed `20260806`, and contain no customer data,
credentials, or PII. The only sensitive material in the workshop is a
participant's own AWS credentials, which never enter the snapshot.

**[VERIFY]** Event-scale sharing mechanics for unencrypted snapshots in the
Workshop Studio template are unconfirmed. Open questions: the per-snapshot
account-share limit against expected event size, whether Workshop Studio
provisioning copies or references the shared snapshot, and the restore-time cost
per participant account. Resolve before the first event; do not assume the
mechanism scales because a two-account test succeeded.

## Ownership lanes

| Lane | Owner | Paths |
|---|---|---|
| Infrastructure | Codex | `Makefile` bootstrap targets, snapshot, S3, `build/embedding-cache/` |
| Application | Claude | `service/`, `ui/`, `db/sql/`, `docs/`, `data/evals/` missions, labs |

Cross-lane changes stop and ask. Rebase before every work session.

## Main-is-always-bootable invariant

Before any push: the snapshot bootstrap path succeeds and the full gate suite is
green locally. Never push red; fix forward immediately if main breaks.

The bootstrap target is `make db-bootstrap-cached` (`Makefile:136`). It requires
`EMBEDDING_CACHE_MANIFEST` to resolve to the manifest above, and fails with a
named error when it does not. There is no target literally named `bootstrap`;
references to "make bootstrap" mean this target.
