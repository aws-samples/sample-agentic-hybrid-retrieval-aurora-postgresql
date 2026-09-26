#!/bin/bash
set -Eeuo pipefail
exec > >(tee /var/log/mosaic-bootstrap.log | logger -t mosaic-bootstrap -s 2>/dev/console) 2>&1

# The tail of this log, JSON-escaped for a wait-condition Reason.
#
# A failed provision is rolled back, which terminates this instance, so
# /var/log/mosaic-bootstrap.log and the console output both vanish before anyone
# reads the stack events. A Reason that says "inspect the log" names a file that
# no longer exists; diagnosing one cost a redeployment with rollback disabled and
# an SSM session. The signal is the only channel that outlives the host, so the
# evidence travels in it. It goes to the wait-condition handle because
# `aws cloudformation signal-resource` accepts no reason at all.
#
# Redaction is not optional: this log captures every command's output, a failing
# psql can echo a DSN, and stack events are readable by the participant. The
# secrets are passed through the environment rather than interpolated into a sed script,
# because building a delimited expression around an unescaped secret is the exact
# class of bug that `pgpass_escape` below exists to fix.
failure_reason() {
  local prefix='Mosaic bootstrap failed. Tail of /var/log/mosaic-bootstrap.log: '
  local encoded=''
  if command -v python3 >/dev/null 2>&1; then
    encoded=$(MOSAIC_REDACT_DB="${DB_PASSWORD:-}" \
      MOSAIC_REDACT_EDITOR_OS="${CODE_EDITOR_OS_PASSWORD:-}" \
      MOSAIC_REDACT_EDITOR_TOKEN="${CODE_EDITOR_CONNECTION_TOKEN:-}" \
      MOSAIC_REDACT_ORIGIN="${ORIGIN_VERIFY_SECRET:-}" \
      MOSAIC_REDACT_APP="${APP_DB_PASSWORD:-}" \
      MOSAIC_REDACT_URL="${DATABASE_URL:-}" python3 -c '
import json, os, sys
from urllib.parse import quote, quote_plus

prefix = sys.argv[1]
secrets = [v for k, v in os.environ.items() if k.startswith("MOSAIC_REDACT_") and v]
flat = " ".join(sys.stdin.read().split())
variants = {form for secret in secrets for form in (secret, quote(secret, safe=""), quote_plus(secret))}
for secret in sorted(variants, key=len, reverse=True):
    flat = flat.replace(secret, "[REDACTED]")
if not flat:
    sys.stdout.write(json.dumps(prefix + "empty; it failed before writing")[1:-1])
    raise SystemExit(0)
keep = len(flat)
while True:
    encoded = json.dumps(prefix + flat[-keep:])[1:-1]
    if len(encoded) <= 900 or keep <= 0:
        break
    keep -= 64
sys.stdout.write(encoded)
' "$prefix" </var/log/mosaic-bootstrap.log 2>/dev/null) || encoded=''
  fi
  if [[ -n "$encoded" ]]; then
    printf '%s' "$encoded"
  else
    printf '%s' "${prefix}unavailable"
  fi
}

signal_failure() {
  rc="$1"
  trap - ERR
  if [[ -n "${BOOTSTRAP_WAIT_HANDLE:-}" ]]; then
    curl --silent --show-error --fail -X PUT -H 'Content-Type:' \
      --data-binary \
      "{\"Status\":\"FAILURE\",\"Reason\":\"$(failure_reason)\",\"UniqueId\":\"userdata\",\"Data\":\"failed\"}" \
      "$BOOTSTRAP_WAIT_HANDLE" || true
  else
    echo "Mosaic bootstrap cannot signal failure: BOOTSTRAP_WAIT_HANDLE is unset"
  fi
  exit "$rc"
}
trap 'signal_failure "$?"' ERR

# Retry only repeatable network installs/downloads. SQL repair and cache import
# remain separate so a retry cannot conceal partially applied database work.
network_retry() {
  local attempt rc=1
  for attempt in 1 2 3 4 5; do
    if "$@"; then
      return 0
    else
      rc=$?
    fi
    if (( attempt < 5 )); then
      echo "Network step $1 failed (attempt $attempt/5); retrying"
      sleep "$((attempt * 5))"
    fi
  done
  return "$rc"
}

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
  CODE_EDITOR_CONNECTION_TOKEN
  ORIGIN_VERIFY_SECRET
  DB_INSTANCE_CLASS
)
for variable in "${required_environment[@]}"; do
  if [[ -z "${!variable:-}" ]]; then
    echo "Mosaic bootstrap requires $variable"
    signal_failure 2
  fi
done

# Must be *defined*, but may legitimately be empty. ASSETS_PREFIX is empty when
# the assets live at the bucket root: `s3://bucket/real-catalog/` is a valid
# URI, and hybrid-retrieval-code-editor.yml declares `AssetsBucketPrefix` with
# `Default: ''`. Requiring it non-empty would reject a supported configuration.
#
# It still needs its own check, because it is consumed unguarded when the cache
# URI is built. Under `set -u` an unset value aborts the shell, and bash does NOT
# run the ERR trap for an unbound variable -- verified directly -- so
# `signal_failure` never fires, no reason reaches the wait condition,
# CloudFormation waits out its full timeout, and rollback then terminates the
# instance carrying the only log. `${var+x}` distinguishes unset from empty.
required_defined_environment=(
  ASSETS_PREFIX
)
for variable in "${required_defined_environment[@]}"; do
  if [[ -z ${!variable+x} ]]; then
    echo "Mosaic bootstrap requires $variable to be set (it may be empty)"
    signal_failure 2
  fi
done

REPO="$HOME_FOLDER/sample-agentic-hybrid-retrieval-aurora-postgresql"

# nodejs22, not nodejs20, and never the bare `npm`. AL2023 registers each Node
# through `alternatives`, and the unversioned `npm` package is Node 18's: asking
# for it silently installs nodejs-18 as a dependency, which then wins the
# alternatives link. A box provisioned that way ran Node 18 while the package
# list said 20, and @anthropic-ai/claude-code declares `node >=22`, so npm
# reported EBADENGINE at install time and the tool ran outside its supported
# engine. Installing one Node family leaves nothing to arbitrate.
network_retry dnf install -y git jq nginx nodejs22 nodejs22-npm postgresql15 python3.13 \
  python3.13-pip python3.13-setuptools gcc gcc-c++ make sudo tar gzip unzip
command -v aws >/dev/null 2>&1 || \
  (network_retry dnf install -y awscli2 || network_retry dnf install -y awscli)
network_retry python3.13 -m pip install --no-cache-dir uv==0.11.21
uv --version

# The RHEL 9 PGDG client RPM depends on libldap.so.2, which AL2023 does not
# provide. PostgreSQL 15's packaged psql uses the compatible standard TLS
# negotiation path against the Aurora PostgreSQL 18 server.
psql --version | grep -Eq '^psql \(PostgreSQL\) 15\.'
node --version | grep -Eq '^v22\.'
npm --version >/dev/null

# Vestigial for actual login: NOPASSWD sudo below means this account never
# authenticates with it, and the participant reaches this box exclusively
# through the Code Editor's own connection token, never an OS login prompt.
# It still has to be *some* value, because a locked account can refuse other
# things PAM checks (su, some session managers). Generated locally, the same
# way as APP_DB_PASSWORD below: nothing outside this script ever reads it, so
# it does not need to be a CFN-supplied secret shared with anything else.
CODE_EDITOR_OS_PASSWORD=$(python3.13 -c \
  'import secrets; print(secrets.token_urlsafe(32))')
if ! id "$CODE_EDITOR_USER" >/dev/null 2>&1; then
  useradd -m -s /bin/bash "$CODE_EDITOR_USER"
fi
echo "$CODE_EDITOR_USER:$CODE_EDITOR_OS_PASSWORD" | chpasswd
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
# install only assigns ownership to named paths; root-owned parents block uv's
# later creation of ~/.local/share/uv/python as the participant.
install -d -o "$CODE_EDITOR_USER" -g "$CODE_EDITOR_USER" \
  "/home/$CODE_EDITOR_USER/.local" "/home/$CODE_EDITOR_USER/.local/lib" \
  "$CODE_EDITOR_ROOT" "/home/$CODE_EDITOR_USER/.local/bin"
curl --retry 4 --retry-all-errors --connect-timeout 15 --max-time 180 -fsSL \
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
printf '%s' "$CODE_EDITOR_CONNECTION_TOKEN" \
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
ExecStart=$CODE_EDITOR_CMD --accept-server-license-terms --host 127.0.0.1 --port 8080 --default-folder "$REPO" --connection-token "$CODE_EDITOR_CONNECTION_TOKEN"
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

# Rate- and connection-limit zones for the /api/ location below. Declared here
# because `limit_req_zone`/`limit_conn_zone` are only valid in the `http {}`
# context, which this file is included into, not inside a `server {}` block.
limit_req_zone $binary_remote_addr zone=mosaic_api_perip:10m rate=5r/s;
limit_req_zone $server_name zone=mosaic_api_room:10m rate=30r/s;
limit_conn_zone $binary_remote_addr zone=mosaic_api_conn:10m;

server {
    listen 80;
    listen [::]:80;
    server_name _;

    if ($http_x_mosaic_origin_verify != "__ORIGIN_VERIFY_SECRET__") {
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

    if ($http_x_mosaic_origin_verify != "__ORIGIN_VERIFY_SECRET__") {
        return 403;
    }

    location /api/ {
        # Two independent budgets, both sized for a full room of attendees
        # rather than one reader:
        #
        # - `mosaic_api_perip` bounds one client IP at 5 req/s (burst 20,
        #   nodelay) so a single misbehaving script or tab cannot starve
        #   everyone else. Interactive use -- typing a search, polling lab
        #   state -- runs at well under 1 req/s.
        # - `mosaic_api_room` is keyed on the constant `$server_name`, so it is
        #   one shared bucket for every caller reaching this instance: 30 req/s
        #   (burst 60, nodelay) covers roughly thirty attendees each issuing
        #   about a request a second at once, several times the realistic peak
        #   for a workshop room, while still bounding a runaway flood.
        # - `mosaic_api_conn` bounds simultaneous open connections per client
        #   IP at 20, generous for one browser's parallel fetches plus one open
        #   SSE stream, well short of exhausting nginx's own worker_connections.
        #
        # These are this nginx process's own counters -- one per attendee
        # stack in this deployment, not shared across instances. The
        # application's own admission control (service/access_control.py)
        # enforces its process-local budget independently, behind this one.
        limit_req zone=mosaic_api_perip burst=20 nodelay;
        limit_req zone=mosaic_api_room burst=60 nodelay;
        limit_conn mosaic_api_conn 20;

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

# A secret crossing a format boundary must be escaped for that format, and a
# `sed s///` replacement is the worst of them: `/` ends the expression, `&`
# inserts the whole match, and `\1` interpolates. None of those would fail
# loudly -- nginx would still parse, the origin-verify header would simply never
# match, and every participant request would 403 with nothing naming why.
#
# `[A-Za-z0-9_-]` covers both a Secrets-Manager-style `ExcludePunctuation: true`
# generator (pure alphanumeric, the historical case) and `secrets.token_urlsafe`
# (adds only `-` and `_`, as APP_DB_PASSWORD below uses): neither can produce a
# `"`, `\`, or `$`, the three characters that would break out of this nginx
# double-quoted string or its own variable interpolation. That coupling to
# whatever generates ORIGIN_VERIFY_SECRET is invisible from here, so it is
# asserted rather than assumed: if the generator ever changes to admit one of
# those three characters, this fails by name instead of producing a host that
# looks healthy and rejects everyone.
if [[ ! $ORIGIN_VERIFY_SECRET =~ ^[A-Za-z0-9_-]+$ ]]; then
  echo "Mosaic bootstrap requires an ORIGIN_VERIFY_SECRET made only of" \
    "letters, digits, '-', and '_'; the nginx origin-verify substitution" \
    "below is only representation-safe for that character set. If the" \
    "generator changed, exclude punctuation there or add explicit escaping" \
    "here."
  signal_failure 2
fi
# Literal, not pattern-based: python replaces the placeholder as an exact string,
# so no character in the value is interpreted. Kept alongside the assertion above
# rather than instead of it, because the nginx quoted string has its own grammar
# this substitution cannot fix.
ORIGIN_VERIFY_SECRET="$ORIGIN_VERIFY_SECRET" python3.13 - \
  /etc/nginx/conf.d/mosaic.conf <<'PYTHON'
import os
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
secret = os.environ["ORIGIN_VERIFY_SECRET"]
body = path.read_text(encoding="utf-8")
placeholder = "__ORIGIN_VERIFY_SECRET__"
if placeholder not in body:
    raise SystemExit(f"{path} carries no {placeholder} to replace")
path.write_text(body.replace(placeholder, secret), encoding="utf-8")
PYTHON
nginx -t
systemctl enable nginx code-editor
systemctl restart nginx code-editor

CLAUDE_CODE_VERSION=2.1.233
network_retry npm install -g "@anthropic-ai/claude-code@$CLAUDE_CODE_VERSION"
CLAUDE_BIN=$(command -v claude)
test -n "$CLAUDE_BIN"
if [ "$CLAUDE_BIN" != /usr/local/bin/claude ]; then
  ln -sf "$CLAUDE_BIN" /usr/local/bin/claude
fi
claude --version | grep -q "^$CLAUDE_CODE_VERSION "

cat >/etc/profile.d/mosaic-claude.sh <<'EOF'
export AWS_REGION=us-east-1
export AWS_DEFAULT_REGION=us-east-1
export CLAUDE_CODE_USE_BEDROCK=1
export ANTHROPIC_MODEL=global.anthropic.claude-sonnet-5
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

# The Claude Code preflight above only proves the chat model is reachable.
# Cohere Embed v4 and Cohere Rerank v3.5 (see .env below) are not otherwise
# exercised until the acceptance search near the end of this script, roughly
# many minutes after `make db-bootstrap-base` starts. An account missing
# either entitlement would burn that entire window - and the participant's
# full 45-minute hands-on budget - before rolling back. Probe both here,
# immediately after the chat-model preflight and before any of that work
# begins, so a missing entitlement fails in seconds instead of in minutes.
EMBED_CANARY_OK=''
for canary_attempt in 1 2 3; do
  if timeout 60 aws bedrock-runtime invoke-model --region "$AWS_REGION" \
      --model-id us.cohere.embed-v4:0 --content-type application/json \
      --accept application/json \
      --body "$(printf '{"texts":["mosaic canary"],"input_type":"search_query","embedding_types":["float"]}' | base64)" \
      /tmp/mosaic-embed-canary.json >/dev/null 2>&1; then
    EMBED_CANARY_OK=1
    break
  fi
  echo "Cohere Embed v4 canary attempt $canary_attempt failed; retrying in 30s"
  sleep 30
done
if [ -z "$EMBED_CANARY_OK" ]; then
  echo "Cohere Embed v4 (us.cohere.embed-v4:0) is not invocable in this account; enable the model or run scripts/check_model_access.py"
fi
test -n "$EMBED_CANARY_OK"

RERANK_CANARY_OK=''
for canary_attempt in 1 2 3; do
  if timeout 60 aws bedrock-agent-runtime rerank --region "$AWS_REGION" \
      --queries '[{"textQuery":{"text":"mosaic canary"},"type":"TEXT"}]' \
      --sources '[
        {"inlineDocumentSource":{"textDocument":{"text":"mosaic canary source one"},"type":"TEXT"},"type":"INLINE"},
        {"inlineDocumentSource":{"textDocument":{"text":"mosaic canary source two"},"type":"TEXT"},"type":"INLINE"}
      ]' \
      --reranking-configuration "{\"type\":\"BEDROCK_RERANKING_MODEL\",\"bedrockRerankingConfiguration\":{\"modelConfiguration\":{\"modelArn\":\"arn:aws:bedrock:$AWS_REGION::foundation-model/cohere.rerank-v3-5:0\"}}}" \
      >/tmp/mosaic-rerank-canary.json 2>&1; then
    RERANK_CANARY_OK=1
    break
  fi
  echo "Cohere Rerank v3.5 canary attempt $canary_attempt failed; retrying in 30s"
  sleep 30
done
if [ -z "$RERANK_CANARY_OK" ]; then
  echo "Cohere Rerank v3.5 (cohere.rerank-v3-5:0) is not invocable in this account; enable the model or run scripts/check_model_access.py"
fi
test -n "$RERANK_CANARY_OK"

rm -rf "$REPO"
sudo -u "$CODE_EDITOR_USER" -H git init "$REPO"
sudo -u "$CODE_EDITOR_USER" -H git -C "$REPO" remote add origin "$REPO_URL"
network_retry sudo -u "$CODE_EDITOR_USER" -H git -C "$REPO" fetch --depth 1 origin "$SOURCE_REVISION"
sudo -u "$CODE_EDITOR_USER" -H git -C "$REPO" checkout --detach FETCH_HEAD
test "$(sudo -u "$CODE_EDITOR_USER" -H git -C "$REPO" rev-parse HEAD)" = "$SOURCE_REVISION"

# Refuse commits in the participant checkout. Reading the tree stays untouched,
# because every lab instructs `git diff` to inspect its seam and the API records
# `source_worktree_dirty` from the same state. Committing is the part nothing in
# the session needs: it would fold a lab edit into history, leave `git diff`
# empty, and hide the very seam the exercise asks a participant to look at.
# The hook lives outside the checkout on purpose. Inside it, the directory would
# show up as untracked in `git status` and in the Code Editor source-control
# panel, adding a second piece of clutter to the tree this is meant to keep tidy.
install -d -m 0755 /opt/mosaic-workshop/git-hooks
cat >/opt/mosaic-workshop/git-hooks/pre-commit <<'HOOK'
#!/bin/sh
echo "Commits are disabled in this workshop checkout." >&2
echo "Your edits are already live - the API reads the files directly." >&2
echo "Each lab inspects its own change with:  git diff" >&2
echo "Committing would empty that diff and hide the seam you are working on." >&2
exit 1
HOOK
chmod 0755 /opt/mosaic-workshop/git-hooks/pre-commit
sudo -u "$CODE_EDITOR_USER" -H git -C "$REPO" config \
  core.hooksPath /opt/mosaic-workshop/git-hooks

# Code Editor opens $REPO (see --default-folder in its unit), and a folderOpen
# task only fires from the .vscode/ of the folder that is actually opened, so both
# files go there rather than in the parent. task.allowAutomaticTasks must be "on"
# or Code Editor prompts instead of running the task, and the workspace-trust keys
# are what suppress the "do you trust the authors" dialog on first open. The
# sibling Pellier bootstrap established this shape after writing the task to the
# unopened parent, where it silently never ran.
#
# Keep the application and its steering files discoverable. Hide generated
# artifacts and instructor answer sheets, not the code participants are learning.
CODE_EDITOR_SETTINGS="/home/$CODE_EDITOR_USER/.code-editor-server/data/User"
install -d -o "$CODE_EDITOR_USER" -g "$CODE_EDITOR_USER" "$CODE_EDITOR_SETTINGS"
cat >"$CODE_EDITOR_SETTINGS/settings.json" <<'EOF'
{
  "security.workspace.trust.enabled": false,
  "security.workspace.trust.startupPrompt": "never",
  "security.workspace.trust.banner": "never",
  "security.workspace.trust.emptyWindow": false,
  "task.allowAutomaticTasks": "on",
  "git.enabled": false,
  "editor.fontSize": 16,
  "terminal.integrated.fontSize": 18,
  "window.zoomLevel": 1,
  "terminal.integrated.defaultProfile.linux": "bash",
  "workbench.colorTheme": "Default Dark Modern",
  "workbench.colorCustomizations": {
    "terminal.foreground": "#FFFFFF"
  },
  "workbench.startupEditor": "none",
  "workbench.welcomePage.walkthroughs.openOnInstall": false,
  "workbench.tips.enabled": false,
  "update.showReleaseNotes": false,
  "extensions.ignoreRecommendations": true,
  "telemetry.telemetryLevel": "off"
}
EOF
chown "$CODE_EDITOR_USER:$CODE_EDITOR_USER" "$CODE_EDITOR_SETTINGS/settings.json"

# The login shell stays open for the session; background mode prevents Code
# Editor from presenting it as a busy foreground task.
install -d -o "$CODE_EDITOR_USER" -g "$CODE_EDITOR_USER" "$REPO/.vscode"
cat >"$REPO/.vscode/tasks.json" <<'EOF'
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Mosaic terminal",
      "type": "shell",
      "command": "bash",
      "args": ["-l", "deploy/open-workshop-terminal.sh"],
      "presentation": {
        "echo": false,
        "reveal": "always",
        "focus": true,
        "panel": "dedicated",
        "showReuseMessage": false,
        "clear": true,
        "close": false
      },
      "runOptions": { "runOn": "folderOpen" },
      "isBackground": true,
      "problemMatcher": []
    }
  ]
}
EOF
cat >"$REPO/.vscode/settings.json" <<'EOF'
{
  "workbench.editorAssociations": {
    "**/START_HERE.md": "vscode.markdown.preview.editor"
  },
  "markdown.preview.fontSize": 16,
  "files.exclude": {
    "**/__pycache__": true,
    "**/*.egg-info": true,
    "**/.pytest_cache": true,
    "**/.ruff_cache": true,
    "**/.venv": true,
    "**/node_modules": true,
    "**/dist": true,
    "**/build": true,
    "**/.DS_Store": true,
    ".git": true,
    ".vscode": true,
    ".env": true,
    ".local/model-migration-check": true,
    ".local/strands-harness-eval": true,
    ".local/strands-coding-eval": true,
    ".local/rehearsal": true,
    ".local/vocabulary-cache": true,
    "data/full": true,
    "data/raw": true,
    "docs/intentional-gaps.md": true,
    "docs/instructor-guide.md": true,
    "docs/lab-golden-queries.md": true
  }
}
EOF
chown -R "$CODE_EDITOR_USER:$CODE_EDITOR_USER" "$REPO/.vscode"

# Claude Code asks every participant to choose a text style on first run. The
# onboarding flags live in ~/.claude.json, and lastOnboardingVersion has to match
# the pinned CLI or the flow reappears. Merge rather than overwrite: the
# bootstrap's own preflight invoke may already have written that file.
sudo -u "$CODE_EDITOR_USER" -H python3.13 - "$CLAUDE_CODE_VERSION" <<'CLAUDE_ONBOARDING'
import json
import pathlib
import sys

version = sys.argv[1]
path = pathlib.Path.home() / ".claude.json"
try:
    config = json.loads(path.read_text(encoding="utf-8"))
except (OSError, ValueError):
    config = {}
config["hasCompletedOnboarding"] = True
config["lastOnboardingVersion"] = version
path.write_text(json.dumps(config, indent=2), encoding="utf-8")
path.chmod(0o600)
CLAUDE_ONBOARDING

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
# Verify the database hostname as well as encrypting the connection. The CA
# bundle arrives over authenticated HTTPS and is read-only to participants.
install -d -m 755 /etc/pki/mosaic
curl --retry 4 --retry-all-errors --connect-timeout 15 --max-time 180 -fsSL \
  "https://truststore.pki.rds.amazonaws.com/$AWS_REGION/$AWS_REGION-bundle.pem" \
  -o /etc/pki/mosaic/rds-ca-bundle.pem
chmod 644 /etc/pki/mosaic/rds-ca-bundle.pem
DATABASE_URL=$(python3.13 - "$DB_USER" "$DB_PASSWORD" \
  "$DB_CLUSTER_ENDPOINT" "$DB_PORT" "$DB_NAME" <<'PY'
import sys
from urllib.parse import quote

user, password, host, port, database = sys.argv[1:6]
print(
    f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}"
    f"@{host}:{port}/{database}"
    "?sslmode=verify-full&sslrootcert=/etc/pki/mosaic/rds-ca-bundle.pem"
)
PY
)

cat >"$REPO/.env" <<EOF
DATABASE_URL='$DATABASE_URL'
MOSAIC_WORKSHOP_DATABASE=$DB_NAME
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
# The API's caller-trust boundary: the same secret nginx checks above. Carried
# through .env so it reaches /etc/mosaic-api.env below (the file the API unit
# actually loads) via the same filtered copy every other setting here takes.
# Never false in a deployed environment; config/.env.example documents the
# loopback-only development bypass this line deliberately never sets.
MOSAIC_REQUIRE_ORIGIN_VERIFICATION=true
MOSAIC_ORIGIN_VERIFY_SECRET=$ORIGIN_VERIFY_SECRET
EOF
chown "$CODE_EDITOR_USER:$CODE_EDITOR_USER" "$REPO/.env"
chmod 600 "$REPO/.env"

# Twenty-seven lab commands use "$DATABASE_URL", and the guide sourced .env once
# on the introduction page. Any new terminal lost it, every one of those commands
# then ran as psql "" and fell back to a local socket that does not exist, and a
# bare `psql` never worked at all. Load it in every interactive shell instead, and
# give libpq its own variables so `psql` with no arguments reaches Aurora too. The
# password stays out of the environment and out of /etc, in a 0600 ~/.pgpass.
cat >>"/home/$CODE_EDITOR_USER/.bashrc" <<EOF
set -a
[ -r '$REPO/.env' ] && . '$REPO/.env'
set +a
export PGHOST='$DB_CLUSTER_ENDPOINT'
export PGPORT='$DB_PORT'
export PGUSER='$DB_USER'
export PGDATABASE='$DB_NAME'
export PGSSLMODE=verify-full
export PGSSLROOTCERT=/etc/pki/mosaic/rds-ca-bundle.pem
EOF

# Match the familiar green identity and blue path used in the Builder workshop
# terminals without recoloring participant commands or Claude Code output.
cat >>"/home/$CODE_EDITOR_USER/.bashrc" <<'EOF'
export PS1='\[\033[01;32m\]\u:\[\033[01;34m\]\w\[\033[00m\]\$ '
EOF

# .pgpass is colon-delimited and libpq wants a backslash before any literal
# backslash or colon inside a field. RDS generates the mosaic_admin password
# under ManageMasterUserPassword and excludes only /, ", @, and space, so a
# colon is allowed and does occur. Written raw, one such password shifts every
# field right and psql reports "password authentication failed" while reading a
# file that looks correct. Backslashes are escaped first so the escape
# character is not re-escaped.
pgpass_escape() {
  local value=$1
  value=${value//\\/\\\\}
  value=${value//:/\\:}
  printf '%s' "$value"
}

printf '%s:%s:%s:%s:%s\n' \
  "$(pgpass_escape "$DB_CLUSTER_ENDPOINT")" \
  "$(pgpass_escape "$DB_PORT")" \
  "$(pgpass_escape "$DB_NAME")" \
  "$(pgpass_escape "$DB_USER")" \
  "$(pgpass_escape "$DB_PASSWORD")" \
  >"/home/$CODE_EDITOR_USER/.pgpass"
chown "$CODE_EDITOR_USER:$CODE_EDITOR_USER" "/home/$CODE_EDITOR_USER/.pgpass"
chmod 600 "/home/$CODE_EDITOR_USER/.pgpass"
sudo -u "$CODE_EDITOR_USER" -H bash -lc \
  "psql -X -Atc 'SELECT 1' >/dev/null"

network_retry sudo -u "$CODE_EDITOR_USER" -H bash -lc \
  "cd '$REPO' && uv sync --frozen"
sudo -u "$CODE_EDITOR_USER" -H bash -lc "cd '$REPO' && uv pip check"
network_retry sudo -u "$CODE_EDITOR_USER" -H bash -lc \
  "cd '$REPO/ui' && npm ci"
sudo -u "$CODE_EDITOR_USER" -H bash -lc "cd '$REPO/ui' && npm run build"

REAL_CATALOG_CACHE_URI=$(printf 's3://%s/%sreal-catalog/' \
  "$ASSETS_BUCKET" "$ASSETS_PREFIX")
# Verify the immutable catalog input before the first database write. A source pin
# alone cannot make an old catalog restore into the new workshop dataset.
# Workshop Studio caps asset objects at 1 GB, so the archive arrives in parts;
# join checks each part, then the whole archive, against the pinned contract.
network_retry sudo -u "$CODE_EDITOR_USER" -H bash -lc "
  set -Eeuo pipefail
  cd '$REPO'
  mkdir -p build/real-catalog-cache
  aws s3 sync '$REAL_CATALOG_CACHE_URI' build/real-catalog-cache \
    --exclude '*' --include 'real-catalog.tar.gz.part-*' \
    --include 'vocabulary/*.csv.gz' --only-show-errors
"
sudo -u "$CODE_EDITOR_USER" -H bash -lc "
  cd '$REPO' && uv run python scripts/real_catalog_cache.py join \
    --archive build/real-catalog-cache/real-catalog.tar.gz
"
sudo -u "$CODE_EDITOR_USER" -H bash -lc "
  cd '$REPO' && uv run python scripts/corpus_vocabulary.py verify \
    --directory build/real-catalog-cache/vocabulary
"
sudo -u "$CODE_EDITOR_USER" -H bash -lc "
  set -Eeuo pipefail
  cd '$REPO'
  set -a
  source .env
  set +a
  export MOSAIC_VOCABULARY_CACHE_DIR=build/real-catalog-cache/vocabulary
  make db-bootstrap-base
  uv run python scripts/real_catalog_cache.py restore \
    --archive build/real-catalog-cache/real-catalog.tar.gz \
    --selection build/real-catalog
  export MOSAIC_CATALOG_DATASET=\$(uv run python -c \
    'import json; print(json.load(open(\"db/config/real-catalog-cache.json\"))[\"dataset_id\"])')
  printf '\\nMOSAIC_CATALOG_DATASET=%s\\n' \"\$MOSAIC_CATALOG_DATASET\" >> .env
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

# The storefront offers a link back to Code Editor, which needs the editor's
# CloudFront domain. The template cannot pass it in: both distributions have this
# instance as their origin, so neither domain exists when this user data renders.
# Discover it here instead, before /etc/mosaic-api.env is written from $REPO/.env
# below, which is the file the API unit actually loads.
#
# The URL written is deliberately tokenless. The tkn= token in the CodeEditorURL
# stack output is a credential for the participant's editor, and anything Mosaic
# renders reaches every browser that loads the storefront. The editor session
# cookie, set when the participant first opens it from the Event Dashboard,
# authenticates them without it, and service/config.py refuses to start on a
# value carrying tkn= so this cannot regress unnoticed.
#
# Non-fatal by construction. A distribution still deploying, a missing
# cloudfront:ListDistributions permission, or a workshop deployed under another
# name all leave the variable unset, and the storefront then hides the link. The
# lookup runs as an `if` condition so a failed call cannot reach the ERR trap and
# roll back an otherwise working stack over a convenience link.
# CloudFront depends on this instance's success signal on first creation, so
# waiting here cannot discover it. One lookup still finds an existing distribution.
CODE_EDITOR_DOMAIN=''
if [[ -n "${WORKSHOP_NAME:-}" ]]; then
  if ! CODE_EDITOR_DOMAIN=$(aws cloudfront list-distributions \
      --query "DistributionList.Items[?Comment=='${WORKSHOP_NAME} Code Editor'].DomainName | [0]" \
      --output text) || [[ "$CODE_EDITOR_DOMAIN" == 'None' ]]; then
    CODE_EDITOR_DOMAIN=''
  fi
else
  echo "WORKSHOP_NAME is unset; skipping Code Editor URL discovery"
fi
if [[ -n "$CODE_EDITOR_DOMAIN" ]]; then
  printf "MOSAIC_CODE_EDITOR_URL='https://%s/?folder=%s/%s'\n" \
    "$CODE_EDITOR_DOMAIN" "$HOME_FOLDER" \
    'sample-agentic-hybrid-retrieval-aurora-postgresql' \
    >>"$REPO/.env"
  echo "Code Editor URL discovered at https://$CODE_EDITOR_DOMAIN/"
else
  echo "No Code Editor CloudFront domain found; the storefront hides its editor link"
fi

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
GRANT USAGE ON SCHEMA mosaic_catalog_stage, mosaic_catalog_search, mosaic_live_search
    TO :"app_user";
GRANT SELECT ON ALL TABLES IN SCHEMA mosaic_catalog_stage, mosaic_catalog_search, mosaic_live_search
    TO :"app_user";
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA mosaic_live_search
    TO :"app_user";
GRANT INSERT, UPDATE ON mosaic.product_evidence TO :"app_user";
GRANT INSERT, UPDATE ON TABLE
    mosaic.shopper_profile,
    mosaic.memory_event_request,
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
    "?sslmode=verify-full&sslrootcert=/etc/pki/mosaic/rds-ca-bundle.pem"
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
  uv run python scripts/apply_search_functions.py
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

SEARCH_SCHEMA=$(cd "$REPO" && uv run python -c \
  'from service.catalog_runtime import search_schema; print(search_schema())')
FUNCTION_DEFINITION=$(psql "$DATABASE_URL" -X -Atc \
  "SELECT pg_get_functiondef('${SEARCH_SCHEMA}.search_hybrid_rrf(text,vector,jsonb,integer,integer,integer,integer,integer,real)'::regprocedure)")
if grep -q "FROM typo" <<<"$FUNCTION_DEFINITION"; then
  echo "GAP-1 failed: trigram is still wired into unweighted fusion"
  # A bare exit skips the ERR trap, so CloudFormation would roll back with
  # no reason and the log line above would vanish with the instance.
  signal_failure 1
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

# Poll quietly. uvicorn has never bound the port by the first attempt, so -S here
# printed "curl: (7) Failed to connect to 127.0.0.1 port 8000" into the log of
# every successful run, which reads as a failure in an otherwise clean bootstrap
# and is the first thing anyone tailing the log asks about. Errors are still
# shown, once, if the services genuinely never answer.
printf 'waiting for mosaic-api and mosaic-ui to answer\n'
for attempt in $(seq 1 60); do
  if curl -fs http://127.0.0.1:8000/api/health >/tmp/health.json &&
     curl -fs \
       -H "X-Mosaic-Origin-Verify: $ORIGIN_VERIFY_SECRET" \
       http://127.0.0.1:8000/api/readiness >/tmp/readiness.json &&
     curl -fs http://127.0.0.1:5173/ >/dev/null &&
     curl -fs \
       -H "X-Mosaic-Origin-Verify: $ORIGIN_VERIFY_SECRET" \
       http://127.0.0.1:8081/ >/dev/null &&
     curl -fs \
       -H "X-Mosaic-Origin-Verify: $ORIGIN_VERIFY_SECRET" \
       http://127.0.0.1:8081/api/readiness \
       >/tmp/proxy-readiness.json; then
    printf 'services answered on attempt %s\n' "$attempt"
    break
  fi
  if [ "$attempt" -eq 60 ]; then
    printf 'services did not answer after 60 attempts; last error and unit status follow\n'
    curl -fsS http://127.0.0.1:8000/api/health || true
    systemctl status mosaic-api mosaic-ui --no-pager || true
    exit 1
  fi
  sleep 5
done

# The API must enforce the origin secret itself, not merely rely on nginx: a
# direct call to the backend port, with no header at all, must be refused.
# `-o /dev/null -w '%{http_code}'` rather than `-f`, because a failing curl
# here (a 401) is the success case for this specific check.
DIRECT_UNAUTHORIZED_STATUS=$(curl -s -o /dev/null -w '%{http_code}' \
  http://127.0.0.1:8000/api/readiness)
if [ "$DIRECT_UNAUTHORIZED_STATUS" != "401" ]; then
  echo "Mosaic bootstrap acceptance: a direct, unauthenticated call to" \
    "127.0.0.1:8000/api/readiness returned $DIRECT_UNAUTHORIZED_STATUS," \
    "not 401; the API is not enforcing its own origin secret"
  signal_failure 1
fi

jq -e --arg dataset "$(jq -r '.corpus.dataset_id' "$REPO/data/evals/mosaic_labs_missions.json")" \
  --argjson products "$(jq '.products' "$REPO/db/config/real-catalog-cache.json")" '
  .status == "ready" and
  .database.dataset_id == $dataset and
  .database.database_name == "mosaic_catalog" and
  .database.product_count == $products and
  .database.embedded_product_count == $products and
  .database.catalog_ready == true and
  .database.embedding_model_ids == ["us.cohere.embed-v4:0"]
' /tmp/readiness.json

curl -fsS -X POST http://127.0.0.1:8000/api/search \
  -H 'Content-Type: application/json' \
  -H "X-Mosaic-Origin-Verify: $ORIGIN_VERIFY_SECRET" \
  --data '{
    "query": "B07G95TJ3P",
    "filters": {"domain": "consumer_electronics", "category_key": "headphones"},
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
  -H "X-Mosaic-Origin-Verify: $ORIGIN_VERIFY_SECRET" \
  --data '{
    "query": "B07G95T3JP",
    "filters": {
      "domain": "consumer_electronics",
      "category_key": "headphones"
    },
    "limit": 10,
    "include_diagnostics": true,
    "rerank": true
  }' >/tmp/lab1-broken-proof.json
# The identifier transposition is measured on the imported catalog. The intended
# Bose listing must be absent while close spelling is disconnected; other
# products must still be returned so an empty search cannot pass this gate.
# `all` over an empty stream is true, so a deploy that returned no results at
# all (an unbuilt index, an over-filtering predicate) would pass this gate
# while breaking Lab 1 in a way the trigram repair cannot fix. Require the
# plausible-but-wrong page the lesson depends on: a full pool, no target.
jq -e '
  (.results | length) > 0 and
  (.diagnostics.candidate_counts.fused_pool // 0) > 0 and
  .diagnostics.candidate_counts.trigram_in_pool == 0 and
  all(.results[]; .product_id != 1277987)
' /tmp/lab1-broken-proof.json

printf '\n=== MOSAIC BOOTSTRAP GREEN ===\n'
jq -r '"  products            \(.database.product_count)
  embeddings          \(.database.embedded_product_count)
  embedding model     \(.database.embedding_model_ids | join(", "))
  database            \(.database.database_name)
  status              \(.status)"' /tmp/readiness.json
jq -r '"  agent model         \(.models.agent)
  synthesis model     \(.models.synthesis)
  rerank model        \(.models.rerank)"' /tmp/health.json
jq -r '"  rerank             \(.diagnostics.rerank_status), \(.results | length) result(s)"' \
  /tmp/model-access-search.json
jq -r '"  lab 1 broken       trigram_in_pool=\(.diagnostics.candidate_counts.trigram_in_pool), target_absent=\(all(.results[]; .product_id != 1277987))"' \
  /tmp/lab1-broken-proof.json
printf '  timings             see build/bootstrap-timings.tsv\n'
printf '=== every acceptance check passed; signalling CloudFormation ===\n\n'

trap - ERR
# Every acceptance check above already passed, so a failure from here on is
# the PUT itself, not the deploy: this is the one CloudFormation is waiting
# on to mark the stack CREATE_COMPLETE. A single transient failure here used
# to exit non-zero straight into the UserData wrapper's ERR trap, which
# signals FAILURE and rolls back an otherwise green deploy. Retry the PUT
# on its own before letting that happen; only the wrapper's already-retried
# FAILURE path should run, and only if the endpoint stays unreachable.
SUCCESS_SIGNAL_OK=''
for success_attempt in 1 2 3 4 5; do
  if curl --silent --show-error --fail -X PUT -H 'Content-Type:' \
      --data-binary '{"Status":"SUCCESS","Reason":"Mosaic bootstrap complete","UniqueId":"userdata","Data":"ready"}' \
      "$BOOTSTRAP_WAIT_HANDLE"; then
    SUCCESS_SIGNAL_OK=1
    break
  fi
  echo "SUCCESS signal attempt $success_attempt failed; retrying in 10s"
  sleep 10
done
if [ -z "$SUCCESS_SIGNAL_OK" ]; then
  echo "SUCCESS signal failed after 5 attempts; falling through to the UserData wrapper's FAILURE retry path"
  exit 1
fi
printf 'MOSAIC_BOOTSTRAP_COMPLETE\n'
