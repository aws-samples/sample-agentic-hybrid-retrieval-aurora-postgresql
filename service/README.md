# Catalog retrieval service

Run from the repository root after loading and embedding the catalog:

```bash
export DATABASE_URL='postgresql://...'
uvicorn service.main:app --reload --port 8000
```

The API exposes catalog, search, agent, retrieval-run, tool-contract, and
benchmark routes under `/api`. Indexing and live queries use the same
1,024-dimensional Cohere Embed v4 model space. Cohere Rerank orders the bounded
post-fusion pool while PostgreSQL retains the individual arm and RRF signals.
