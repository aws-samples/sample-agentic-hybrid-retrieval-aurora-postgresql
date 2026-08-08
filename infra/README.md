# Local PostgreSQL environment

The Docker Compose file is a convenience environment for functional development. It is not an Aurora performance substitute.

```bash
docker compose -f infra/docker-compose.yml up -d
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/catalog
make db-init db-load embed-hash db-index
```

Use the Aurora deployment guide and measured benchmark harness for session performance claims.
