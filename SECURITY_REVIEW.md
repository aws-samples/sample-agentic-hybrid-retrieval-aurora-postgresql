# Security review notes

This repository is designed to be reviewed before creating or publishing an internal GitHub repository.

## Intentional exclusions

- No real Jira, Confluence, Slack, Salesforce, GitHub, or customer data.
- No committed secrets, tokens, OAuth client secrets, private keys, or AWS credentials.
- No vendored vendor logo image files. The React UI uses package-provided brand SVG components for source badges.
- No analytics or telemetry.
- No automatic outbound calls from the frontend.
- No live connector runs unless a user explicitly invokes connector scripts and provides credentials through environment variables.

## Data classification

Default generated data is synthetic and should be treated as workshop/demo data. Generated records include fictional projects, customers, source IDs, comments, and incidents.

## Credential handling

The repo uses `.env.example` only. Real deployments should store secrets in AWS Secrets Manager or Parameter Store.

Recommended secret keys:

- `DATABASE_URL`
- `BEDROCK_OPUS_MODEL`
- `BEDROCK_SONNET_MODEL`
- `BEDROCK_ROUTER_MODEL`
- `BEDROCK_REPORTING_MODEL`
- `BEDROCK_CHAT_MODEL`
- `BEDROCK_EMBEDDING_MODEL`
- `BEDROCK_RERANK_MODEL`
- `GITHUB_TOKEN`
- `SLACK_BOT_TOKEN`
- `SALESFORCE_ACCESS_TOKEN`
- `ATLASSIAN_API_TOKEN`

## Slack-specific guidance

The core lab uses synthetic Slack-like threads. Live Slack integration is treated as a stretch exercise and should prefer federated/ephemeral retrieval rather than long-term indexing of live message bodies unless explicitly approved by the organization.

## Permissions and ACLs

The canonical schema includes an `acl` JSONB column on `source_objects`. Production systems should filter results by user/team/source-system permissions before ranking or synthesis.

## Network calls

The default API only calls Aurora PostgreSQL. Optional Bedrock embeddings/reranking are disabled unless configured. Optional connector scripts perform network calls only when explicitly run.

## Suggested review checklist

- Confirm `.env` is not committed.
- Confirm no real data is present under `data/`.
- Confirm connector scripts require explicit environment variables.
- Confirm frontend does not load external scripts or fonts.
- Confirm backend CORS configuration is scoped before production deployment.
- Confirm IAM roles for deployment are least-privilege.
