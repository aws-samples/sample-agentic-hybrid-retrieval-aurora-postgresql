# What DAT410 Builds

DAT410 builds a live incident-evidence retrieval system on Aurora PostgreSQL.
It is not a chatbot shell, fixture walkthrough, or HNSW performance benchmark.

Participants run one guided orchestrator that creates a genuine PostgreSQL
write stall, captures PostgreSQL, CloudWatch, and Database Insights evidence,
measures a concurrent-index repair, builds searchable evidence from the
observations, and generates Cohere embeddings through Amazon Bedrock.
Workshop bootstrap has already generated 5,000 disposable customers and 25,000
related orders to make that database workload real; those rows never enter
retrieval.

The resulting indexing receipt supplies run-derived IDs. Participants then:

1. compare exact, full-text, semantic, and fuzzy retrieval;
2. apply a database-side evidence-kind filter before fusion;
3. edit and independently recompute PostgreSQL weighted RRF;
4. inspect optional Cohere reranking as a separate score;
5. decompose the incident question into evidence requirements;
6. traverse and compare authoritative run relationships;
7. synthesize only from retrieved live evidence; and
8. validate and replay the cited answer from persisted proof.

The expected volume ladder is 5,000 operational customers plus 25,000 related
orders, about 735 measured telemetry rows, about 110 searchable documents, and
100-250 chunks. That is sufficient to teach retrieval mechanics and proof. It
is not represented as
production HNSW scale.

Aurora owns ranking, relationships, citations, evaluation, and replay.
Operational systems remain authoritative for mutable state, current
authorization, workflow, and actions.

No authored, fictional, offline, demo, fixture, prior-run, or canned evidence is
allowed. The Overview main graphic is the only illustrative exception and never
feeds the data path.
