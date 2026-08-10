# Local PostgreSQL environment

The Docker Compose file is a convenience environment for functional development. It is not an Aurora performance substitute.

```bash
docker compose -f infra/docker-compose.yml up -d
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/mosaic_catalog
make db-install
make db-prepare-mosaic
make db-load-mosaic
make db-embed
make db-index-concurrent
make db-load-cohort
make db-smoke
```

The default embedding path calls Cohere Embed v4 through Amazon Bedrock. Use
the reusable embedding cache for repeat workshop provisions. Local PostgreSQL
is for functional development; use Aurora and the measured benchmark harness
for session performance claims.
