# DAT410 Build Brief

**Session:** Build agentic hybrid retrieval with Amazon Aurora PostgreSQL
**Format:** L400 builders' session, 60 minutes
**Application:** Hybrid Retrieval Workbench

## Objective

Participants generate a measured Aurora PostgreSQL online-migration failure,
turn its live signals into a searchable evidence corpus, build hybrid retrieval
in SQL, and ground a read-only Hybrid Retrieval Agent in citations. They then
review and execute a structured recommendation themselves, add fresh validation
evidence, and inspect the persisted proof of both the diagnosis and the human
decision.

## Evidence Contract

- Bootstrap creates exactly 5,000 operational customers and 3,000,000
  operational orders while `evidence`, `retrieval`, and `proof` remain empty.
- `make live-workshop` is the only participant ingestion path.
- Investigation Evidence records a separate nullable-column commit, an unbatched backfill, ten
  transaction-ID lock waiters, at least two pool-boundary timeouts, recovery,
  and two sequential plan checkpoints.
- Validation Evidence is a new, additive capture of the participant-approved index outcome.
  It does not replace any Investigation Evidence records.
- PostgreSQL catalog evidence proves connected blockers and plans;
  `psycopg_pool` statistics and request outcomes prove queued callers; and
  CloudWatch remains supplemental.
- Every participant-facing record uses
  `source_system=pg_incident_capture` and capture-derived `INC-*`, `CHG-*`,
  `LOCK-*`, and `TEL-*` identifiers.
- Distinct state changes and plan checkpoints produce an honest 50-80 document
  guidance range. Coverage and diversity gates, not a padded count, decide
  corpus adequacy.
- Cohere Embed 4 vectors are generated through Bedrock during each admission.
- No authored, fictional, demo, offline, fixture, prior-run, or canned record
  is permitted. The Overview main graphic is the sole illustrative exception.

## Participant Path

| Time | Build |
|---:|---|
| 0-5 | Access the environment and prove the evidence store is empty |
| 5-10 | Establish the online-migration scenario and source-to-fact map |
| 10-18 | Capture and admit Investigation Evidence |
| 18-38 | Build exact, full-text, semantic, fuzzy, filtered, fused, and reranked retrieval in SQL |
| 38-50 | Build the Hybrid Retrieval Agent, cited diagnosis, and structured proposal |
| 50-56 | Review, approve, execute, validate in Validation Evidence, and replay |
| 56-58 | Transfer the retrieval and supervision patterns |
| 58-60 | Summary and cleanup |

## Retrieval and Action Contract

Aurora PostgreSQL owns exact and full-text retrieval, pgvector semantic search,
pg_trgm typo recovery, metadata filters, weighted reciprocal rank fusion,
relationship reads, citations, evaluation, and replay. Raw arm scores,
PostgreSQL RRF, and model rerank scores remain distinct. Filters run inside
each arm before fusion.

The Hybrid Retrieval Agent is read-only. It can retrieve, traverse, compare,
and synthesize cited evidence, then persist one structured proposal. Code
renders the allowed DDL from validated fields. The participant approves and
runs it; Aurora records the observed catalog fingerprint, Validation Evidence receipt, and
pre/post autonomy-readiness verdicts.

## Acceptance

A fresh target account must prove:

- empty evidence before Investigation Evidence and the exact preloaded operational workload;
- a combined pool/lock hold with ten blocked database sessions and at least two
  pool-boundary timeouts;
- full recovery after commit, including ten drained writers and a fresh write;
- pre- and post-`ANALYZE` sequential plans in Investigation Evidence and a post-index plan in
  Validation Evidence;
- all six Investigation Evidence signal types, four phases, and passing corpus-diversity
  criteria;
- runtime embeddings, one model space, and zero search-index drift;
- differentiated exact, full-text, semantic, fuzzy, fusion, and rerank
  receipts;
- a cited Investigation Evidence agent answer, proposal, participant-owned matching execution,
  and additive Validation Evidence;
- citation validation and replay with no model call; and
- a Workshop Studio archive containing committed source only, never
  participant evidence or database state.
