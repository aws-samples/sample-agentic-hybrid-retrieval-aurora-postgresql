#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  cat >&2 <<'USAGE'
Usage: scripts/aurora_database_url.sh <secret-arn> <cluster-endpoint> [database-name]

Prints a DATABASE_URL export command for the Aurora PostgreSQL cluster.
USAGE
  exit 1
fi

SECRET_ARN="$1"
HOST="$2"
DBNAME="${3:-retrieval}"

SECRET_JSON="$(aws secretsmanager get-secret-value --secret-id "$SECRET_ARN" --query SecretString --output text)"

python3 - "$SECRET_JSON" "$HOST" "$DBNAME" <<'PY'
import json
import sys
from urllib.parse import quote

secret = json.loads(sys.argv[1])
host = sys.argv[2]
dbname = sys.argv[3]
username = quote(secret["username"], safe="")
password = quote(secret["password"], safe="")
port = secret.get("port", 5432)

print(f"export DATABASE_URL=postgresql://{username}:{password}@{host}:{port}/{dbname}?sslmode=require")
PY
