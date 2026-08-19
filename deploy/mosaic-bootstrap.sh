#!/bin/bash
set -Eeuo pipefail
exec > >(tee /var/log/mosaic-bootstrap.log | logger -t mosaic-bootstrap -s 2>/dev/console) 2>&1

signal_failure() {
  rc="$1"
  trap - ERR
  if [[ -n "${BOOTSTRAP_WAIT_HANDLE:-}" ]]; then
    curl --silent --show-error --fail -X PUT -H 'Content-Type:' \
      --data-binary '{"Status":"FAILURE","Reason":"Mosaic bootstrap failed; inspect /var/log/mosaic-bootstrap.log","UniqueId":"userdata","Data":"failed"}' \
      "$BOOTSTRAP_WAIT_HANDLE" || true
  else
    echo "Mosaic bootstrap cannot signal failure: BOOTSTRAP_WAIT_HANDLE is unset"
  fi
  exit "$rc"
}
trap 'signal_failure "$?"' ERR

required_environment=(
  BOOTSTRAP_WAIT_HANDLE
  CODE_EDITOR_USER
  HOME_FOLDER
  REPO_URL
  SOURCE_REVISION
  AWS_REGION
  DB_SECRET_ARN
  DB_CLUSTER_ENDPOINT
  DB_NAME
  ASSETS_BUCKET
  EMBEDDING_CACHE_MANIFEST_SHA256
  CODE_EDITOR_PASSWORD
  DB_INSTANCE_CLASS
)
for variable in "${required_environment[@]}"; do
  if [[ -z "${!variable:-}" ]]; then
    echo "Mosaic bootstrap requires $variable"
    signal_failure 2
  fi
done

REPO="$HOME_FOLDER/sample-agentic-hybrid-retrieval-aurora-postgresql"

dnf install -y git jq nginx nodejs20 npm python3.13 python3.13-pip \
  python3.13-setuptools gcc gcc-c++ make sudo tar gzip unzip
command -v aws >/dev/null 2>&1 || \
  (dnf install -y awscli2 || dnf install -y awscli)
python3.13 -m pip install --no-cache-dir uv==0.11.21
uv --version

PGDG_BASE='https://download.postgresql.org/pub/repos/yum/18/redhat/rhel-9-aarch64'
PG_CLIENT_RPM='postgresql18-18.3-1PGDG.rhel9.7.aarch64.rpm'
PG_LIBS_RPM='postgresql18-libs-18.3-1PGDG.rhel9.7.aarch64.rpm'
curl -fsSL "$PGDG_BASE/$PG_CLIENT_RPM" -o "/tmp/$PG_CLIENT_RPM"
curl -fsSL "$PGDG_BASE/$PG_LIBS_RPM" -o "/tmp/$PG_LIBS_RPM"
printf '%s  %s\n' \
  '250137c5e0ca30a59871a9e1356009b8fa6fdf34f178cf849b2eb77e1d71839d' \
  "/tmp/$PG_CLIENT_RPM" \
  '4d6d69d43a4cba9fe417dc355ecda6386e69b79fdbc8509ef365c50d3d05b9af' \
  "/tmp/$PG_LIBS_RPM" | sha256sum -c -
dnf install -y "/tmp/$PG_LIBS_RPM" "/tmp/$PG_CLIENT_RPM"
ln -sf /usr/pgsql-18/bin/psql /usr/local/bin/psql
psql --version | grep -q ' 18.3'

if ! id "$CODE_EDITOR_USER" >/dev/null 2>&1; then
  useradd -m -s /bin/bash "$CODE_EDITOR_USER"
fi
echo "$CODE_EDITOR_USER:$CODE_EDITOR_PASSWORD" | chpasswd
usermod -aG wheel "$CODE_EDITOR_USER"
printf '%s\n' '%wheel ALL=(ALL) NOPASSWD: ALL' \
  >/etc/sudoers.d/90-workshop
chmod 440 /etc/sudoers.d/90-workshop

mkdir -p "$HOME_FOLDER"
chown "$CODE_EDITOR_USER:$CODE_EDITOR_USER" "$HOME_FOLDER"

CODE_EDITOR_VERSION='v1.101.2'
CODE_EDITOR_DISTRIBUTION='code-editor-server-v1.101.2-1785233990.076216280-linux-arm64.tar.gz'
CODE_EDITOR_SHA256='1965ca15854f1faa8907e6e91c0e87ee887b24d458771b352a71e08fb41d6d60'
CODE_EDITOR_ROOT="/home/$CODE_EDITOR_USER/.local/lib/code-editor-$CODE_EDITOR_VERSION-linux-arm64"
CODE_EDITOR_ARCHIVE="/tmp/$CODE_EDITOR_DISTRIBUTION"
install -d -o "$CODE_EDITOR_USER" -g "$CODE_EDITOR_USER" \
  "$CODE_EDITOR_ROOT" "/home/$CODE_EDITOR_USER/.local/bin"
curl -fsSL \
  "https://code-editor.amazonaws.com/content/code-editor-server/dist/$CODE_EDITOR_VERSION/$CODE_EDITOR_DISTRIBUTION" \
  -o "$CODE_EDITOR_ARCHIVE"
printf '%s  %s\n' "$CODE_EDITOR_SHA256" "$CODE_EDITOR_ARCHIVE" \
  | sha256sum -c -
sudo -u "$CODE_EDITOR_USER" -H tar -xzf "$CODE_EDITOR_ARCHIVE" \
  -C "$CODE_EDITOR_ROOT"
ln -sf "$CODE_EDITOR_ROOT/dist/bin/code-editor-server" \
  "/home/$CODE_EDITOR_USER/.local/bin/code-editor-server"
CODE_EDITOR_CMD="/home/$CODE_EDITOR_USER/.local/bin/code-editor-server"
test -x "$CODE_EDITOR_CMD"
sudo -u "$CODE_EDITOR_USER" mkdir -p \
  "/home/$CODE_EDITOR_USER/.code-editor-server/data"
printf '%s' "$CODE_EDITOR_PASSWORD" \
  >"/home/$CODE_EDITOR_USER/.code-editor-server/data/token"
chown "$CODE_EDITOR_USER:$CODE_EDITOR_USER" \
  "/home/$CODE_EDITOR_USER/.code-editor-server/data/token"
chmod 600 "/home/$CODE_EDITOR_USER/.code-editor-server/data/token"

cat >/etc/systemd/system/code-editor.service <<EOF
[Unit]
Description=Mosaic Code Editor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$CODE_EDITOR_USER
Group=$CODE_EDITOR_USER
WorkingDirectory=$HOME_FOLDER
Environment=HOME=/home/$CODE_EDITOR_USER
Environment=PATH=/usr/local/bin:/usr/bin:/bin:/home/$CODE_EDITOR_USER/.local/bin
ExecStart=$CODE_EDITOR_CMD --accept-server-license-terms --host 127.0.0.1 --port 8080 --default-folder $REPO --connection-token $CODE_EDITOR_PASSWORD
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat >/etc/nginx/nginx.conf <<'NGINX_MAIN'
user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log notice;
pid /run/nginx.pid;

events {
    worker_connections 1024;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    sendfile on;
    keepalive_timeout 65;
    include /etc/nginx/conf.d/*.conf;
}
NGINX_MAIN

cat >/etc/nginx/conf.d/mosaic.conf <<'NGINX'
map $http_upgrade $connection_upgrade {
    default upgrade;
    '' close;
}

server {
    listen 80;
    listen [::]:80;
    server_name _;

    if ($http_x_mosaic_origin_verify != "__CODE_EDITOR_PASSWORD__") {
        return 403;
    }

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_read_timeout 300;
    }
}

server {
    listen 8081;
    listen [::]:8081;
    server_name _;

    if ($http_x_mosaic_origin_verify != "__CODE_EDITOR_PASSWORD__") {
        return 403;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_buffering off;
        proxy_read_timeout 300;
        gzip off;
    }

    location / {
        proxy_pass http://127.0.0.1:5173;
        proxy_http_version 1.1;
        proxy_set_header Host 127.0.0.1:5173;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_buffering off;
        proxy_read_timeout 300;
    }
}
NGINX

sed -i "s/__CODE_EDITOR_PASSWORD__/$CODE_EDITOR_PASSWORD/g" \
  /etc/nginx/conf.d/mosaic.conf
nginx -t
systemctl enable nginx code-editor
systemctl restart nginx code-editor

npm install -g @anthropic-ai/claude-code@2.1.232
CLAUDE_BIN=$(command -v claude)
test -n "$CLAUDE_BIN"
if [ "$CLAUDE_BIN" != /usr/local/bin/claude ]; then
  ln -sf "$CLAUDE_BIN" /usr/local/bin/claude
fi
claude --version | grep -q '^2.1.232 '

cat >/etc/profile.d/mosaic-claude.sh <<'EOF'
export AWS_REGION=us-east-1
export AWS_DEFAULT_REGION=us-east-1
export CLAUDE_CODE_USE_BEDROCK=1
export ANTHROPIC_MODEL=global.anthropic.claude-sonnet-5
export CLAUDE_CODE_MODEL=global.anthropic.claude-sonnet-5
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
EOF
chmod 644 /etc/profile.d/mosaic-claude.sh
cat >>"/home/$CODE_EDITOR_USER/.bashrc" <<EOF
source /etc/profile.d/mosaic-claude.sh
cd $HOME_FOLDER/sample-agentic-hybrid-retrieval-aurora-postgresql
EOF

# The first global-inference invoke in a cold account can throttle or
# time out transiently; one failed attempt must not cost the full
# two-hour stack. Real access blockers (use-case requirement, Private
# Marketplace, SCP) still fail after the bounded retries.
CLAUDE_PREFLIGHT_OK=''
for preflight_attempt in 1 2 3; do
  if (
    cd "$HOME_FOLDER"
    sudo -u "$CODE_EDITOR_USER" -H env \
      AWS_REGION="$AWS_REGION" \
      AWS_DEFAULT_REGION="$AWS_REGION" \
      CLAUDE_CODE_USE_BEDROCK=1 \
      ANTHROPIC_MODEL=global.anthropic.claude-sonnet-5 \
      CLAUDE_CODE_MODEL=global.anthropic.claude-sonnet-5 \
      CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
      timeout 180 "$CLAUDE_BIN" \
        --bare \
        --tools "" \
        --model global.anthropic.claude-sonnet-5 \
        --no-session-persistence \
        --output-format text \
        --print \
        "Reply with exactly MOSAIC_CLAUDE_READY."
  ) >/var/log/mosaic-claude-code-preflight.log 2>&1 &&
    grep -q 'MOSAIC_CLAUDE_READY' \
      /var/log/mosaic-claude-code-preflight.log; then
    CLAUDE_PREFLIGHT_OK=1
    break
  fi
  echo "Claude Code preflight attempt $preflight_attempt failed; retrying in 30s"
  sleep 30
done
test -n "$CLAUDE_PREFLIGHT_OK"

rm -rf "$REPO"
sudo -u "$CODE_EDITOR_USER" -H git init "$REPO"
sudo -u "$CODE_EDITOR_USER" -H git -C "$REPO" remote add origin "$REPO_URL"
sudo -u "$CODE_EDITOR_USER" -H git -C "$REPO" fetch --depth 1 origin "$SOURCE_REVISION"
sudo -u "$CODE_EDITOR_USER" -H git -C "$REPO" checkout --detach FETCH_HEAD
test "$(sudo -u "$CODE_EDITOR_USER" -H git -C "$REPO" rev-parse HEAD)" = "$SOURCE_REVISION"

install -d -o "$CODE_EDITOR_USER" -g "$CODE_EDITOR_USER" \
  "/home/$CODE_EDITOR_USER/.claude"
cat >"/home/$CODE_EDITOR_USER/.claude/CLAUDE.md" <<'EOF'
# Mosaic workshop guidance

Help the participant diagnose and repair one controlled retrieval
defect at a time. Explain the observed mechanism before editing.

## Safety boundaries

- Aurora PostgreSQL is the only database. Never create or suggest a
  local database, fixture database, or alternate catalog.
- Never drop, rebuild, disable, or replace catalog indexes.
- Never weaken structured filters, citation checks, fail-closed
  behavior, or the read-only agent tool boundary.
- Treat db/config/retrieval.yaml and
  data/evals/mosaic_labs_missions.json as single sources of truth.

## Exercise boundaries

- Run uv run python scripts/lab_state.py status and inspect the saved
  response and git diff before proposing a repair.
- Change only the current marked LAB1, LAB2, or LAB3 seam and make
  the smallest possible diff.
- Do not edit unrelated files, retrieval limits, weights, thresholds,
  model IDs, indexes, prompts, or tool schemas.
- Do not run uv run python scripts/lab_state.py solution --lab N
  unless the participant explicitly asks for the full recovery path.
- After editing, run git diff --check, apply SQL changes directly
  with psql, repeat the identical request, and run the lab-specific
  uv production validator shown in the guide.
- If Aurora, Bedrock, the API, or the storefront is unhealthy, stop
  and identify it as an environment failure rather than changing code
  to work around it.
EOF
chown "$CODE_EDITOR_USER:$CODE_EDITOR_USER" \
  "/home/$CODE_EDITOR_USER/.claude/CLAUDE.md"
chmod 644 "/home/$CODE_EDITOR_USER/.claude/CLAUDE.md"

SECRET_JSON=$(aws secretsmanager get-secret-value \
  --secret-id "$DB_SECRET_ARN" \
  --region "$AWS_REGION" \
  --query SecretString \
  --output text)
DB_USER=$(jq -r '.username' <<<"$SECRET_JSON")
DB_PASSWORD=$(jq -r '.password' <<<"$SECRET_JSON")
DB_PORT=$(jq -r '.port // 5432' <<<"$SECRET_JSON")
DATABASE_URL=$(python3.13 - "$DB_USER" "$DB_PASSWORD" \
  "$DB_CLUSTER_ENDPOINT" "$DB_PORT" "$DB_NAME" <<'PY'
import sys
from urllib.parse import quote

user, password, host, port, database = sys.argv[1:6]
print(
    f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}"
    f"@{host}:{port}/{database}"
    "?sslmode=require&sslnegotiation=direct"
)
PY
)

cat >"$REPO/.env" <<EOF
DATABASE_URL='$DATABASE_URL'
AWS_REGION=$AWS_REGION
AWS_DEFAULT_REGION=$AWS_REGION
BEDROCK_REGION=$AWS_REGION
EMBEDDING_PROVIDER=bedrock
BEDROCK_EMBED_MODEL_ID=us.cohere.embed-v4:0
RERANK_PROVIDER=bedrock
BEDROCK_RERANK_MODEL_ID=cohere.rerank-v3-5:0
RERANK_REQUIRED=true
BEDROCK_CHAT_MODEL_ID=global.anthropic.claude-sonnet-5
BEDROCK_AGENT_MODEL_ID=global.anthropic.claude-sonnet-5
BEDROCK_SYNTHESIS_MODEL_ID=global.anthropic.claude-sonnet-5
ALLOW_DEVELOPMENT_EMBEDDINGS=false
BEDROCK_MAX_ATTEMPTS=5
MOSAIC_SOURCE_REVISION=$SOURCE_REVISION
AURORA_INSTANCE_CLASS=$DB_INSTANCE_CLASS
DB_SECRET_ARN=$DB_SECRET_ARN
EOF
chown "$CODE_EDITOR_USER:$CODE_EDITOR_USER" "$REPO/.env"
chmod 600 "$REPO/.env"

sudo -u "$CODE_EDITOR_USER" -H bash -lc \
  "cd '$REPO' && uv sync --frozen && uv pip check"
sudo -u "$CODE_EDITOR_USER" -H bash -lc \
  "cd '$REPO/ui' && npm ci && npm run build"

EMBEDDING_CACHE_URI=$(printf 's3://%s/%sembedding-cache/' \
  "$ASSETS_BUCKET" "$ASSETS_PREFIX")
sudo -u "$CODE_EDITOR_USER" -H bash -lc "
  set -Eeuo pipefail
  cd '$REPO'
  set -a
  source .env
  set +a
  cache_started=\$(date +%s)
  aws s3 sync '$EMBEDDING_CACHE_URI' build/embedding-cache \
    --only-show-errors
  uv run python scripts/embedding_cache.py verify \
    build/embedding-cache/manifest.json \
    --contract db/config/embedding-cache.json
  cache_finished=\$(date +%s)
  printf 'embedding_cache_download\t%s\n' \
    \"\$((cache_finished - cache_started))\" \
    >build/embedding-cache-download-timing.tsv
  test \"\$(sha256sum build/embedding-cache/manifest.json | awk '{print \$1}')\" = \
    '$EMBEDDING_CACHE_MANIFEST_SHA256'
  make db-bootstrap-cached
  cat build/embedding-cache-download-timing.tsv
  cat build/bootstrap-timings.tsv
  MISSION_GATE_REQUIRE_DB=1 DATABASE_URL=\"\$DATABASE_URL\" \
    uv run python scripts/mission_contract.py
  DATABASE_URL=\"\$DATABASE_URL\" \
    uv run python scripts/run_eval.py --validate-only
  DATABASE_URL=\"\$DATABASE_URL\" \
    uv run python scripts/run_eval.py \
      --queries data/evals/canonical_queries.jsonl --validate-only
  uv run python scripts/retrieval_profile.py --check
  uv run python scripts/config_tripwire.py
  uv run python scripts/tool_contracts.py --check
  FUNCTION_CENSUS_REQUIRE_DB=1 DATABASE_URL=\"\$DATABASE_URL\" \
    uv run python scripts/function_census.py
  psql \"\$DATABASE_URL\" -X -v ON_ERROR_STOP=1 \
    -f db/sql/99_smoke_test.sql
"

APP_DB_USER='mosaic_runtime'
APP_DB_PASSWORD=$(python3.13 -c \
  'import secrets; print(secrets.token_urlsafe(32))')
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 \
  --set=app_user="$APP_DB_USER" \
  --set=app_password="$APP_DB_PASSWORD" \
  --set=db_name="$DB_NAME" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN', :'app_user')
WHERE NOT EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname = :'app_user'
)
\gexec
SELECT format(
    'ALTER ROLE %I PASSWORD %L',
    :'app_user',
    :'app_password'
)
\gexec
SELECT format(
    'GRANT CONNECT ON DATABASE %I TO %I',
    :'db_name',
    :'app_user'
)
\gexec
GRANT USAGE ON SCHEMA mosaic, mosaic_search TO :"app_user";
GRANT SELECT ON ALL TABLES IN SCHEMA mosaic, mosaic_search
    TO :"app_user";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA mosaic, mosaic_search
    TO :"app_user";
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA mosaic_search
    TO :"app_user";
GRANT INSERT, UPDATE ON TABLE
    mosaic.agent_session,
    mosaic.agent_turn,
    mosaic.search_event
    TO :"app_user";
GRANT INSERT ON TABLE
    mosaic.agent_tool_event,
    mosaic.fusion_comparison,
    mosaic.fusion_comparison_candidate,
    mosaic.search_result_event
    TO :"app_user";
SQL

APP_DATABASE_URL=$(python3.13 - "$APP_DB_USER" "$APP_DB_PASSWORD" \
  "$DB_CLUSTER_ENDPOINT" "$DB_PORT" "$DB_NAME" <<'PY'
import sys
from urllib.parse import quote

user, password, host, port, database = sys.argv[1:6]
print(
    f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}"
    f"@{host}:{port}/{database}"
    "?sslmode=require&sslnegotiation=direct"
)
PY
)
{
  printf "DATABASE_URL='%s'\n" "$APP_DATABASE_URL"
  grep -Ev '^(DATABASE_URL|DB_SECRET_ARN)=' "$REPO/.env"
} >/etc/mosaic-api.env
chown root:root /etc/mosaic-api.env
chmod 600 /etc/mosaic-api.env

mkdir -p /opt/mosaic-workshop
sudo -u "$CODE_EDITOR_USER" -H bash -lc "
  set -Eeuo pipefail
  cd '$REPO'
  set -a
  source .env
  set +a
  uv run python scripts/lab_state.py reset --lab 1
  psql \"\$DATABASE_URL\" -X -v ON_ERROR_STOP=1 \
    -f db/sql/09_search_functions.sql
  DATABASE_URL=\"\$DATABASE_URL\" \
    uv run python scripts/configure_retrieval_database.py
  uv run python scripts/lab_state.py status
  DATABASE_URL=\"\$DATABASE_URL\" \
    uv run python scripts/lab_state.py validate --lab 2 \
      --database-url \"\$DATABASE_URL\"
  uv run python scripts/lab_state.py validate --lab 3
" | tee /opt/mosaic-workshop/initial-lab-state.txt
chmod 444 /opt/mosaic-workshop/initial-lab-state.txt
grep -Fxq 'Lab 1: BROKEN' \
  /opt/mosaic-workshop/initial-lab-state.txt
grep -Fxq 'Lab 2: SOLVED' \
  /opt/mosaic-workshop/initial-lab-state.txt
grep -Fxq 'Lab 3: SOLVED' \
  /opt/mosaic-workshop/initial-lab-state.txt

ACTUAL_DIFF=$(sudo -u "$CODE_EDITOR_USER" -H \
  git -C "$REPO" diff --name-only | sort)
EXPECTED_DIFF='db/sql/09_search_functions.sql'
test "$ACTUAL_DIFF" = "$EXPECTED_DIFF"
sudo -u "$CODE_EDITOR_USER" -H git -C "$REPO" diff --check

set -a
source "$REPO/.env"
set +a

FUNCTION_DEFINITION=$(psql "$DATABASE_URL" -X -Atc \
  "SELECT pg_get_functiondef('mosaic_search.search_hybrid_rrf(text,vector,jsonb,integer,integer,integer,integer,integer,real)'::regprocedure)")
if grep -q "FROM typo" <<<"$FUNCTION_DEFINITION"; then
  echo "GAP-1 failed: trigram is still wired into unweighted fusion"
  exit 1
fi

cat >/etc/systemd/system/mosaic-api.service <<EOF
[Unit]
Description=Mosaic FastAPI service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$CODE_EDITOR_USER
Group=$CODE_EDITOR_USER
WorkingDirectory=$REPO
EnvironmentFile=/etc/mosaic-api.env
Environment=PATH=$REPO/.venv/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=$REPO/.venv/bin/python -m uvicorn service.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat >/etc/systemd/system/mosaic-ui.service <<EOF
[Unit]
Description=Mosaic Vite application
After=network-online.target mosaic-api.service
Wants=network-online.target

[Service]
Type=simple
User=$CODE_EDITOR_USER
Group=$CODE_EDITOR_USER
WorkingDirectory=$REPO/ui
Environment=PATH=/usr/local/bin:/usr/bin:/bin
Environment=CATALOG_API_PROXY=http://127.0.0.1:8000
ExecStart=/usr/bin/npm run dev -- --host 127.0.0.1 --port 5173
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable mosaic-api mosaic-ui
systemctl restart mosaic-api mosaic-ui

for attempt in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8000/api/health >/tmp/health.json &&
     curl -fsS http://127.0.0.1:8000/api/readiness >/tmp/readiness.json &&
     curl -fsS http://127.0.0.1:5173/ >/dev/null &&
     curl -fsS \
       -H "X-Mosaic-Origin-Verify: $CODE_EDITOR_PASSWORD" \
       http://127.0.0.1:8081/ >/dev/null &&
     curl -fsS \
       -H "X-Mosaic-Origin-Verify: $CODE_EDITOR_PASSWORD" \
       http://127.0.0.1:8081/api/readiness \
       >/tmp/proxy-readiness.json; then
    break
  fi
  if [ "$attempt" -eq 60 ]; then
    systemctl status mosaic-api mosaic-ui --no-pager || true
    exit 1
  fi
  sleep 5
done

jq -e '
  .status == "ready" and
  .database.database_name == "mosaic_catalog" and
  .database.product_count == 500000 and
  .database.embedded_product_count == 500000 and
  .database.embedding_model_ids == ["us.cohere.embed-v4:0"]
' /tmp/readiness.json

curl -fsS -X POST http://127.0.0.1:8000/api/search \
  -H 'Content-Type: application/json' \
  --data '{
    "query": "EchoBud S2",
    "filters": {"domain": "consumer_electronics"},
    "limit": 3,
    "include_diagnostics": true,
    "rerank": true
  }' >/tmp/model-access-search.json
jq -e '
  .diagnostics.rerank_status == "applied" and
  (.results | length) > 0
' /tmp/model-access-search.json

curl -fsS -X POST http://127.0.0.1:8000/api/search \
  -H 'Content-Type: application/json' \
  --data '{
    "query": "wirless noice canceling hedphones under $200 with long batery life",
    "filters": {
      "domain": "consumer_electronics",
      "max_price_cents": 20000,
      "in_stock_only": true
    },
    "limit": 10,
    "include_diagnostics": true,
    "rerank": true
  }' >/tmp/lab1-broken-proof.json
jq -e '
  .diagnostics.candidate_counts.trigram_in_pool == 0 and
  all(.results[]; .product_id != 2)
' /tmp/lab1-broken-proof.json

trap - ERR
curl --silent --show-error --fail -X PUT -H 'Content-Type:' \
  --data-binary '{"Status":"SUCCESS","Reason":"Mosaic bootstrap complete","UniqueId":"userdata","Data":"ready"}' \
  "$BOOTSTRAP_WAIT_HANDLE"
