# Catalog retrieval service

Start the API from the repository root after loading and embedding the catalog, with the
environment from `.env` loaded, as [the development guide](../docs/development.md)
describes:

```bash
set -a
source .env
set +a
make api-serve
```

The API exposes catalog, search, agent, retrieval-run, tool-contract, and
benchmark routes under `/api`. Indexing and live queries use the same
1,024-dimensional Cohere Embed v4 model space. Cohere Rerank orders the bounded
post-fusion pool while PostgreSQL retains the individual arm and RRF signals.
