# Build agentic hybrid retrieval with Amazon Aurora PostgreSQL

Retrieval correctness is a pipeline property, not a top-1 result. In this
hands-on session, use Amazon Aurora PostgreSQL as the search and context engine
for a 500,000-product catalog, then diagnose three production-shaped failures
whose individual components still work. Restore a disconnected fuzzy candidate
arm, repair reciprocal-rank fusion that a model reranker masks, and reconnect
product-owned evidence to the citation scope of a bounded Strands agent.

Along the way, inspect PostgreSQL full-text search, `pg_trgm`, pgvector HNSW,
SQL and JSONB eligibility filters, reciprocal-rank fusion, Cohere Rerank on
Amazon Bedrock, source-addressable evidence, and persisted retrieval receipts.
The agent can request typed, read-only tools, but application code decides what
executes and which evidence may reach synthesis. Leave with working code,
ranking and evidence contracts, and a repeatable method for proving retrieval
quality across Retrieve, Rank, and Reason.
