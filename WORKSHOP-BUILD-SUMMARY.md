# What DAT410 Builds

DAT410 builds a live evidence and hybrid-retrieval system on Aurora PostgreSQL.
It is not a chatbot shell, a fixture walkthrough, an autonomous-remediation
demo, or an HNSW performance benchmark.

Participants begin with 5,000 customers and 3,000,000 orders that have been
provisioned as disposable operational workload. They create the corpus by
running an online migration that goes wrong: a separately committed nullable
column is followed by one unbatched `priority_tier` backfill. Twelve writes use
the real ten-connection FastAPI pool. Ten reach PostgreSQL and wait on the
backfill transaction; at least two queue outside PostgreSQL and demonstrate
that a timed-out request can leave no database footprint. Commit releases the
backfill, the writers drain, and a named query remains sequential after
`ANALYZE` because it lacks a composite index.

Wave A turns these measured lock, pool, request, statement, WAL, and plan
signals into a small, diverse live corpus. Participants then:

1. compare exact, full-text, semantic, and fuzzy retrieval;
2. apply database-side evidence filters before fusion;
3. edit and recompute PostgreSQL weighted RRF;
4. inspect Cohere reranking as a distinct model signal;
5. decompose the three-part question, traverse relationships, and compare
   sources;
6. synthesize only from retrieved live evidence; and
7. inspect citations, candidate signals, relationships, and replay receipts.

The Hybrid Retrieval Agent recommends but does not execute the missing
composite index. The participant reviews a stored, cited proposal and runs the
rendered DDL in Code Editor. Aurora records the approval and catalog
fingerprint, then Wave B admits only the post-index validation evidence.
Participants can therefore compare what was proposed, what was executed, and
what the database observed without rewriting the original diagnosis.

Aurora owns retrieval, rankings, relationships, citations, supervised-action
proof, evaluation, and replay. PostgreSQL catalog views prove connected
blockers and plans; application-pool statistics prove callers that never
reached PostgreSQL; CloudWatch is supplemental. Operational systems remain
authoritative for workflow, current authorization, and actions.

No authored, fictional, offline, demo, fixture, prior-run, or canned evidence
is allowed. The Overview main graphic is the only illustrative exception and
never feeds retrieval or proof.
