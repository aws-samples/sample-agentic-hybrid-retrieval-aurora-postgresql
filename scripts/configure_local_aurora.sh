#!/usr/bin/env bash
set -euo pipefail

STACK_NAME="${1:-${AURORA_STACK_NAME:-agentic-hybrid-retrieval}}"
REGION="${2:-${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}}"
API_URL="${VITE_RETRIEVAL_API_URL:-http://127.0.0.1:8000}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AWS_ARGS=(--region "$REGION")

stack_output() {
  local key="$1"
  aws "${AWS_ARGS[@]}" cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --query "Stacks[0].Outputs[?OutputKey=='${key}'].OutputValue | [0]" \
    --output text
}

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI is required to resolve the Workshop Studio stack outputs." >&2
  exit 1
fi

SECRET_ARN="$(stack_output DatabaseSecretArn)"
if [[ -z "$SECRET_ARN" || "$SECRET_ARN" == "None" ]]; then
  SECRET_ARN="$(stack_output AuroraSecretArn)"
fi

ENDPOINT_VALUE="$(stack_output DatabaseEndpoint)"
if [[ -z "$ENDPOINT_VALUE" || "$ENDPOINT_VALUE" == "None" ]]; then
  ENDPOINT_VALUE="$(stack_output AuroraEndpoint)"
fi

DB_NAME="$(stack_output AuroraDatabaseName)"

if [[ -z "$SECRET_ARN" || "$SECRET_ARN" == "None" || -z "$ENDPOINT_VALUE" || "$ENDPOINT_VALUE" == "None" ]]; then
  echo "Could not resolve DatabaseSecretArn/DatabaseEndpoint from Workshop Studio stack $STACK_NAME in $REGION." >&2
  exit 1
fi

DB_NAME="${DB_NAME:-workshop_db}"
DB_NAME="${DB_NAME/None/workshop_db}"
HOST="${ENDPOINT_VALUE%:*}"

export AWS_REGION="$REGION"
export AWS_DEFAULT_REGION="$REGION"
eval "$("$ROOT_DIR/scripts/aurora_database_url.sh" "$SECRET_ARN" "$HOST" "$DB_NAME")"

umask 077
cat > "$ROOT_DIR/.env" <<EOF
DATABASE_URL=$DATABASE_URL
AWS_REGION=$REGION
AWS_DEFAULT_REGION=$REGION
APP_DISPLAY_NAME=AuraLens
CORS_ALLOW_ORIGIN_REGEX=https?://(localhost|127\\.0\\.0\\.1):[0-9]+
EMBED_PROVIDER=bedrock
EMBED_DIM=1024
BEDROCK_OPUS_MODEL=global.anthropic.claude-opus-4-8
BEDROCK_SONNET_MODEL=global.anthropic.claude-sonnet-5
BEDROCK_ROUTER_MODEL=global.anthropic.claude-sonnet-5
BEDROCK_REPORTING_MODEL=global.anthropic.claude-sonnet-5
BEDROCK_CHAT_MODEL=global.anthropic.claude-opus-4-8
BEDROCK_EMBEDDING_MODEL=us.cohere.embed-v4:0
EOF

mkdir -p "$ROOT_DIR/frontend"
cat > "$ROOT_DIR/frontend/.env" <<EOF
VITE_RETRIEVAL_API_URL=$API_URL
VITE_APP_DISPLAY_NAME=AuraLens
VITE_ENABLE_ANSWER_STREAMING=1
EOF

if command -v nc >/dev/null 2>&1; then
  if nc -z -w 5 "$HOST" 5432 >/dev/null 2>&1; then
    NETWORK_STATUS="reachable"
  else
    NETWORK_STATUS="not reachable from this machine"
  fi
else
  NETWORK_STATUS="not checked; nc is unavailable"
fi

cat <<EOF
Configured local workshop runtime from Workshop Studio stack $STACK_NAME in $REGION.
Aurora endpoint: $HOST:5432
Database: $DB_NAME
Network check: $NETWORK_STATUS

Wrote ignored local files:
- .env
- frontend/.env

Next:
  make aurora-verify
  make seed-load
  make api
  cd frontend && npm install && npm run dev
EOF
