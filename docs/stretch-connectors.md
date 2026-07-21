# Optional stretch connectors

## Core lab

Use the workshop source-object bundle, including Slack-like threads, Jira issues, Confluence docs, Salesforce cases, and GitHub PRs.

## Stretch 1: GitHub live ingestion

Run `make github-sync` against the packaged checkout while the repository is
private. Switch to
`GITHUB_TRANSPORT=github GITHUB_REF=main make github-sync` when the public or
token-authorized repository is available. Both paths preserve transport,
revision, blob, and content provenance, reconcile updates/deletions, and
batch-embed only this connector's changed chunks. Then optionally pull GitHub
issues and pull requests through the API connector.

## Stretch 2: Slack federated retrieval

Treat Slack as real-time/federated context. Retrieve relevant Slack messages on behalf of a user and do not persist live message bodies unless approved by your organization.

## Stretch 3: AppFlow / Glue to S3

Use AppFlow or Glue to export SaaS data to S3, normalize into source objects, and ingest through the same API.

## Stretch 4: MCP wrapper

Wrap `/v1/search` and `/v1/agent/answer` as MCP tools. PostgreSQL remains the retrieval engine for the local lab.
