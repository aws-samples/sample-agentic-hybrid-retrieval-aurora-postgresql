# Reference architecture

## Runtime flow

```mermaid
flowchart LR
    U[Buyer / builder] --> UI[Mosaic discovery UI]
    H[MCP-compatible host] --> MCP[Stateless MCP 2.0 adapter]
    MCP --> API
    UI --> API[Search orchestration API]
    API --> Q[Query understanding]
    Q --> FTS[PostgreSQL FTS]
    Q --> TRI[pg_trgm]
    Q --> EMB[Query embedding]
    EMB --> HNSW[pgvector HNSW]
    Q --> FIL[SQL / JSONB filters]
    FTS --> FUSE[RRF candidate fusion]
    TRI --> FUSE
    HNSW --> FUSE
    FIL --> FUSE
    FUSE --> RR[Reranker]
    RR --> EV[Evidence + explanation]
    EV --> UI
    API --> LOG[Query / eval telemetry]
```

## Data plane

Aurora PostgreSQL holds:

- canonical product and inventory metadata
- weighted FTS document
- trigram-normalized text
- structured JSONB attributes
- product embeddings
- HNSW index
- reviews/evidence
- evaluation judgments and query telemetry

The design intentionally demonstrates that relational filters and vector retrieval can participate in one transactionally consistent data plane.

## Agent and interoperability plane

Strands Agents calls the read-only product tools in-process. The MCP
`2026-07-28` service runs in an isolated dependency environment and calls the
same typed FastAPI routes over HTTP. Neither adapter owns retrieval logic:
filters, candidate generation, weighted RRF, reranking provenance, and
retrieval-run persistence remain behind the API in Aurora PostgreSQL.

## Offline pipeline

```mermaid
flowchart LR
    G[Synthetic catalog generator] --> C[500K catalog in three CSV.gz shards]
    C --> LOAD[PostgreSQL COPY loader]
    LOAD --> P[catalog.product]
    P --> E[Embedding batches]
    E --> V[Vector column]
    V --> I[HNSW build]
    P --> X[FTS / trigram / JSONB indexes]
    Q[Eval queries + judgments] --> RUN[Eval runner]
    RUN --> M[Recall / MRR / nDCG]
    I --> B[HNSW benchmark harness]
    B --> R[Measured JSON results]
```

## Separation of responsibilities

| Concern | Owner |
|---|---|
| exact words and identifiers | PostgreSQL FTS / B-tree |
| typo and near-string recovery | `pg_trgm` |
| intent and paraphrase | embedding + pgvector |
| hard product eligibility | SQL columns / JSONB |
| heterogeneous rank combination | RRF |
| nuanced final ordering | reranker |
| trust and auditability | evidence + component diagnostics |
| performance truth | measured harness and preserved run metadata |
