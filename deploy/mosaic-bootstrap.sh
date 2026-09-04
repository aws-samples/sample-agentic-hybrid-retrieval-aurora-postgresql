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
# secrets are passed as arguments rather than interpolated into a sed script,
# because building a delimited expression around an unescaped secret is the exact
# class of bug that `pgpass_escape` below exists to fix.
failure_reason() {
  local prefix='Mosaic bootstrap failed. Tail of /var/log/mosaic-bootstrap.log: '
  local encoded=''
  if command -v python3 >/dev/null 2>&1; then
    encoded=$(tail -c 4000 /var/log/mosaic-bootstrap.log 2>/dev/null \
      | python3 -c '
import json, sys

prefix, secrets = sys.argv[1], [s for s in sys.argv[2:] if s]
flat = " ".join(sys.stdin.read().split())
for secret in secrets:
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
' "$prefix" "${DB_PASSWORD:-}" "${CODE_EDITOR_PASSWORD:-}" \
        "${APP_DB_PASSWORD:-}" "${DATABASE_URL:-}" 2>/dev/null) || encoded=''
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

# Must be *defined*, but may legitimately be empty. ASSETS_PREFIX is empty when
# the assets live at the bucket root: `s3://bucket/embedding-cache/` is a valid
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
dnf install -y git jq nginx nodejs22 nodejs22-npm postgresql15 python3.13 \
  python3.13-pip python3.13-setuptools gcc gcc-c++ make sudo tar gzip unzip
command -v aws >/dev/null 2>&1 || \
  (dnf install -y awscli2 || dnf install -y awscli)
python3.13 -m pip install --no-cache-dir uv==0.11.21
uv --version

# The RHEL 9 PGDG client RPM depends on libldap.so.2, which AL2023 does not
# provide. PostgreSQL 15's packaged psql uses the compatible standard TLS
# negotiation path against the Aurora PostgreSQL 18 server.
psql --version | grep -Eq '^psql \(PostgreSQL\) 15\.'
node --version | grep -Eq '^v22\.'
npm --version >/dev/null

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
ExecStart=$CODE_EDITOR_CMD --accept-server-license-terms --host 127.0.0.1 --port 8080 --default-folder "$REPO" --connection-token "$CODE_EDITOR_PASSWORD"
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

# A secret crossing a format boundary must be escaped for that format, and a
# `sed s///` replacement is the worst of them: `/` ends the expression, `&`
# inserts the whole match, and `\1` interpolates. None of those would fail
# loudly -- nginx would still parse, the origin-verify header would simply never
# match, and every participant request would 403 with nothing naming why.
#
# Safety currently rests on `ExcludePunctuation: true` in the sibling workshop
# repository at assets/hybrid-retrieval-code-editor.yml:113, which makes this
# secret 32 alphanumeric characters. That coupling is invisible from here, so it
# is asserted rather than assumed: if the generator ever changes, this fails by
# name instead of producing a host that looks healthy and rejects everyone.
if [[ ! $CODE_EDITOR_PASSWORD =~ ^[A-Za-z0-9]+$ ]]; then
  echo "Mosaic bootstrap requires an alphanumeric CODE_EDITOR_PASSWORD;" \
    "the nginx origin-verify substitution and the systemd unit below are only" \
    "representation-safe for that character set. If the generator changed," \
    "restore ExcludePunctuation in the workshop template" \
    "(assets/hybrid-retrieval-code-editor.yml) or add explicit escaping here."
  signal_failure 2
fi
# Literal, not pattern-based: python replaces the placeholder as an exact string,
# so no character in the value is interpreted. Kept alongside the assertion above
# rather than instead of it, because the systemd unit and the nginx quoted string
# have their own grammars this substitution cannot fix.
CODE_EDITOR_PASSWORD="$CODE_EDITOR_PASSWORD" python3.13 - \
  /etc/nginx/conf.d/mosaic.conf <<'PYTHON'
import os
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
secret = os.environ["CODE_EDITOR_PASSWORD"]
body = path.read_text(encoding="utf-8")
placeholder = "__CODE_EDITOR_PASSWORD__"
if placeholder not in body:
    raise SystemExit(f"{path} carries no {placeholder} to replace")
path.write_text(body.replace(placeholder, secret), encoding="utf-8")
PYTHON
nginx -t
systemctl enable nginx code-editor
systemctl restart nginx code-editor

CLAUDE_CODE_VERSION=2.1.233
npm install -g "@anthropic-ai/claude-code@$CLAUDE_CODE_VERSION"
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
export ANTHROPIC_MODEL=global.anthropic.claude-sonnet-4-6
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
      ANTHROPIC_MODEL=global.anthropic.claude-sonnet-4-6 \
      CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
      timeout 180 "$CLAUDE_BIN" \
        --bare \
        --tools "" \
        --model global.anthropic.claude-sonnet-4-6 \
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
# 24 minutes after `make db-bootstrap-cached` starts. An account missing
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
sudo -u "$CODE_EDITOR_USER" -H git -C "$REPO" fetch --depth 1 origin "$SOURCE_REVISION"
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
# files.exclude leaves the three places the labs actually edit - db/, scripts/,
# and service/ - and hides the rest of a 700-file repository from the explorer
# and quick-open. It also removes docs/, which is not only clutter: it holds
# intentional-gaps.md, instructor-guide.md, and lab-golden-queries.md, so a
# participant browsing that folder finds the answer to all three labs. This is
# presentation only, so anything hidden is still readable from the terminal.
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
  "telemetry.telemetryLevel": "off",
  "files.exclude": {
    "**/__pycache__": true,
    "**/*.egg-info": true,
    ".github": true,
    ".pytest_cache": true,
    ".ruff_cache": true,
    ".venv": true,
    "ARTIFACTS.md": true,
    "AGENTS.md": true,
    "benchmarks": true,
    "CODE_OF_CONDUCT.md": true,
    "config": true,
    "CONTRIBUTING.md": true,
    "data": true,
    "docs": true,
    "mcp-server": true,
    "READINESS.md": true,
    "tests": true,
    "ui": true,
    "uv.lock": true
  }
}
EOF
chown "$CODE_EDITOR_USER:$CODE_EDITOR_USER" "$CODE_EDITOR_SETTINGS/settings.json"

install -d -o "$CODE_EDITOR_USER" -g "$CODE_EDITOR_USER" "$REPO/.vscode"
cat >"$REPO/.vscode/tasks.json" <<'EOF'
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Mosaic terminal",
      "type": "shell",
      "command": "bash",
      "args": ["-l"],
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
      "isBackground": false,
      "problemMatcher": []
    }
  ]
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
DATABASE_URL=$(python3.13 - "$DB_USER" "$DB_PASSWORD" \
  "$DB_CLUSTER_ENDPOINT" "$DB_PORT" "$DB_NAME" <<'PY'
import sys
from urllib.parse import quote

user, password, host, port, database = sys.argv[1:6]
print(
    f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}"
    f"@{host}:{port}/{database}"
    "?sslmode=require"
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
BEDROCK_CHAT_MODEL_ID=global.anthropic.claude-sonnet-4-6
BEDROCK_AGENT_MODEL_ID=global.anthropic.claude-sonnet-4-6
BEDROCK_SYNTHESIS_MODEL_ID=global.anthropic.claude-sonnet-4-6
ALLOW_DEVELOPMENT_EMBEDDINGS=false
BEDROCK_MAX_ATTEMPTS=5
MOSAIC_SOURCE_REVISION=$SOURCE_REVISION
AURORA_INSTANCE_CLASS=$DB_INSTANCE_CLASS
DB_SECRET_ARN=$DB_SECRET_ARN
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
export PGSSLMODE=require
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
    "?sslmode=require"
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

# Poll quietly. uvicorn has never bound the port by the first attempt, so -S here
# printed "curl: (7) Failed to connect to 127.0.0.1 port 8000" into the log of
# every successful run, which reads as a failure in an otherwise clean bootstrap
# and is the first thing anyone tailing the log asks about. Errors are still
# shown, once, if the services genuinely never answer.
printf 'waiting for mosaic-api and mosaic-ui to answer\n'
for attempt in $(seq 1 60); do
  if curl -fs http://127.0.0.1:8000/api/health >/tmp/health.json &&
     curl -fs http://127.0.0.1:8000/api/readiness >/tmp/readiness.json &&
     curl -fs http://127.0.0.1:5173/ >/dev/null &&
     curl -fs \
       -H "X-Mosaic-Origin-Verify: $CODE_EDITOR_PASSWORD" \
       http://127.0.0.1:8081/ >/dev/null &&
     curl -fs \
       -H "X-Mosaic-Origin-Verify: $CODE_EDITOR_PASSWORD" \
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
    "query": "noice cancelng hedfones",
    "filters": {
      "domain": "consumer_electronics",
      "max_price_cents": 20000,
      "in_stock_only": true
    },
    "limit": 10,
    "include_diagnostics": true,
    "rerank": true
  }' >/tmp/lab1-broken-proof.json
# Lab 1's broken state disconnects the pg_trgm arm from candidate fusion. Measured
# on a live 500,000-row cluster with a real Bedrock query embedding: every token is
# misspelled, so no query lexeme reaches product 2's tsvector, and because the
# query names no identity the semantic arm ranks product 2 far outside its
# 150-candidate budget. With the trigram channel disconnected, product 2 is a
# candidate in no arm and is absent from the results: Recall@10 fails. That
# absence, not just an empty trigram channel, is what this checks.
#
# The previous anchor, "Sonorra WHC720", could not distinguish broken from fixed.
# It named the model number, so the semantic arm ranked product 2 first (exact
# rank 1, cosine 0.492) and returned it even with pg_trgm disconnected. This check
# therefore failed on every deploy. Retiring it also required removing aliases
# from feature_text in db/sql/06_retrieval_projection.sql, because aliases carry
# the target's own misspellings into search_document and let FTS recover any typo
# this query could use.
jq -e '
  .diagnostics.candidate_counts.trigram_in_pool == 0 and
  all(.results[]; .product_id != 2)
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
jq -r '"  lab 1 broken       trigram_in_pool=\(.diagnostics.candidate_counts.trigram_in_pool), target_absent=\(all(.results[]; .product_id != 2))"' \
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
