# Develop and validate Mosaic

This guide is for running or contributing to Mosaic outside a Workshop Studio
event. Workshop participants should follow [Start Here](../START_HERE.md) and the
workshop guide; their environment is already prepared.

Read [AGENTS.md](../AGENTS.md) and [house standards](house-standards.md) before
editing. Review [security boundaries](security-boundaries.md) before adapting
this single-participant sample to a shared application.

## Set up the application

You need Python 3.13, [uv](https://docs.astral.sh/uv/), Node.js 22 (22.12 or later)
with npm, PostgreSQL client tools, AWS credentials for Amazon Bedrock in
`us-east-1`, and access to an Aurora cluster with the Mosaic catalog loaded.
See [Aurora deployment](aurora-deployment.md) for provisioning.

**Aurora only:** there is no local database path. Set `DATABASE_URL` to the
intended Aurora PostgreSQL cluster. [ARTIFACTS.md](../ARTIFACTS.md) records the
catalog restore contract and connection troubleshooting.

Install the locked dependencies and configure the environment:

```bash
make setup
make ui-install
cp config/.env.example .env
```

Edit `.env` with your Aurora connection, selected catalog, and AWS configuration,
then start the API:

```bash
set -a
source .env
set +a
make api-serve
```

In a second terminal:

```bash
make ui-dev
```

Open **http://127.0.0.1:5173**. The API runs at `http://127.0.0.1:8000`;
`/api/health` and `/api/readiness` report its status. Override `UI_PORT` and
`API_PORT` when needed; the UI proxy follows `API_PORT`.

## Validate a change

Run the offline checks without Aurora or Bedrock:

```bash
make lint
make validate
make validate-db
make validate-config
uv run python scripts/mission_contract.py --shape-only
PYTHONPATH=. uv run pytest -q
make ui-test
make ui-build
```

With `DATABASE_URL` set to the intended Aurora cluster:

```bash
MISSION_GATE_REQUIRE_DB=1 make validate-missions
make validate-evals
make db-verify-bootstrap
make test
```

The full Python gate includes 15 integration tests against Aurora. See
[READINESS.md](../READINESS.md) for the complete release gates and
[the evaluation plan](evaluation-plan.md) before running model-backed scoring.
Source CI does not certify a fresh deployment or a new relevance scorecard.
Saved [scale benchmarks](current-scale-benchmarks.md) describe a historical
catalog; they do not certify the current real catalog.

The [Mosaic skill](../skills/mosaic-hybrid-retrieval/SKILL.md) declares a
four-operation HTTP skill surface. It is not a standalone retrieval runtime;
callers need a compatible backend. The [MCP adapter](mcp-interoperability.md)
exposes three typed, catalog-read-only tools over the same API. Search still
writes retrieval receipts. Validate the shared tool contracts with:

```bash
uv run python scripts/tool_contracts.py --check
```

## Publish a workshop update

Follow the [publishing runbook](workshop-studio-publishing.md): publish source,
repin, verify and upload assets, sync static URLs, then push the workshop
repository and verify its build.

For other deployments, see [AgentCore Runtime](agentcore-runtime.md) and
[telemetry export](telemetry-contract.md). Contribution and security-reporting
instructions are in [CONTRIBUTING.md](../CONTRIBUTING.md).
