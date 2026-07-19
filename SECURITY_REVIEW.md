# Security review notes

This repository is designed to be reviewed before creating or publishing an internal GitHub repository.

## Intentional exclusions

- No real Jira, Confluence, Slack, Salesforce, GitHub, or customer data.
- No committed secrets, tokens, OAuth client secrets, private keys, or AWS credentials.
- Checked-in connector logo files are static UI assets only; they do not contain credentials, tracking code, or remote dependencies.
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
- `GITHUB_TOKEN`
- `SLACK_BOT_TOKEN`
- `SALESFORCE_ACCESS_TOKEN`
- `ATLASSIAN_API_TOKEN`

## Slack-specific guidance

The core lab uses synthetic Slack-like threads. Live Slack integration is treated as a stretch exercise and should prefer federated/ephemeral retrieval rather than long-term indexing of live message bodies unless explicitly approved by the organization.

## Permissions and ACLs

The canonical schema includes an `acl` JSONB column on `source_objects`, and all four search functions enforce it: each accepts a `p_principal` JSONB argument and filters rows through `ops.acl_visible(acl, principal)` inside the base scan, so a restricted object never reaches ranking or synthesis for a principal lacking its clearance. The default workshop context passes `p_principal => NULL`, which short-circuits to no ACL filtering so the demo audience sees every object; a real deployment supplies the caller's clearances (e.g. `{"clearances": [...]}`).

## Network calls

The default live search path calls PostgreSQL and, with `EMBED_PROVIDER=bedrock` (the default), Bedrock Runtime (`bedrock:InvokeModel`) for Cohere query embeddings so query vectors match the shipped seed dump. Set `EMBED_PROVIDER=hash` for a local offline run, understanding that vector relevance will not match the Cohere-embedded dump unless the corpus is regenerated with the same provider. With `COHERE_RERANK_ENABLED` on (the default), the hybrid path also calls Cohere Rerank v3.5 through the Bedrock Agent Runtime rerank API (`bedrock:Rerank`); set `COHERE_RERANK_ENABLED=0` to disable it. The canonical Orion answer is served verbatim from `ops.agent_answers` and never invokes a text-generation model; questions outside the seed synthesize a cited answer with a Strands agent over Bedrock (`bedrock:InvokeModelWithResponseStream`). Optional connector scripts perform network calls only when explicitly run.

## Suggested review checklist

- Confirm `.env` is not committed.
- Confirm no real data is present under `data/`.
- Confirm connector scripts require explicit environment variables.
- Confirm frontend does not load external scripts or fonts.
- Confirm backend CORS configuration is scoped before production deployment.
- Confirm IAM roles for deployment are least-privilege.
