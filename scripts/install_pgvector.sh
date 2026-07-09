#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PGVECTOR_VERSION="${PGVECTOR_VERSION:-v0.8.2}"
BUILD_DIR="${PGVECTOR_BUILD_DIR:-$ROOT_DIR/.build/pgvector-$PGVECTOR_VERSION}"
POSTGRES_HOME="${POSTGRES_HOME:-/usr/local/opt/postgresql@18}"
if [[ -z "${PG_CONFIG:-}" && -x "$POSTGRES_HOME/bin/pg_config" ]]; then
  PG_CONFIG_BIN="$POSTGRES_HOME/bin/pg_config"
else
  PG_CONFIG_BIN="${PG_CONFIG:-$(command -v pg_config)}"
fi

if [[ -z "$PG_CONFIG_BIN" ]]; then
  echo "pg_config was not found. Install local Postgres first." >&2
  exit 1
fi

mkdir -p "$(dirname "$BUILD_DIR")"

if [[ ! -d "$BUILD_DIR/.git" ]]; then
  git clone --depth 1 --branch "$PGVECTOR_VERSION" https://github.com/pgvector/pgvector.git "$BUILD_DIR"
else
  git -C "$BUILD_DIR" fetch --tags --depth 1 origin "$PGVECTOR_VERSION"
  git -C "$BUILD_DIR" checkout "$PGVECTOR_VERSION"
fi

make -C "$BUILD_DIR" clean
make -C "$BUILD_DIR" PG_CONFIG="$PG_CONFIG_BIN"
make -C "$BUILD_DIR" PG_CONFIG="$PG_CONFIG_BIN" install

PG_VERSION_LABEL="$("$PG_CONFIG_BIN" --version)"
PG_SHARE_DIR="$("$PG_CONFIG_BIN" --sharedir)"

echo "Installed pgvector $PGVECTOR_VERSION for $PG_VERSION_LABEL"
echo "Extension directory: $PG_SHARE_DIR/extension"
