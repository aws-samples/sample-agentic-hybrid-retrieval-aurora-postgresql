ARG POSTGRES_IMAGE_VERSION=18.3
FROM postgres:${POSTGRES_IMAGE_VERSION}-bookworm

ARG PGVECTOR_VERSION=v0.8.2
ARG POSTGRES_MAJOR=18

RUN apt-get update \
  && apt-get install -y --no-install-recommends build-essential ca-certificates git postgresql-server-dev-${POSTGRES_MAJOR} \
  && git clone --depth 1 --branch "${PGVECTOR_VERSION}" https://github.com/pgvector/pgvector.git /tmp/pgvector \
  && make -C /tmp/pgvector \
  && make -C /tmp/pgvector install \
  && rm -rf /tmp/pgvector \
  && apt-get purge -y --auto-remove build-essential git postgresql-server-dev-${POSTGRES_MAJOR} \
  && rm -rf /var/lib/apt/lists/*
