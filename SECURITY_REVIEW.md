# Security Review Notes

## Data Classification

All committed and generated casework is synthetic workshop data. Incident IDs,
change IDs, customer names, SQL statements, lock snapshots, source URIs, and
support commitments are controlled fixtures.

Do not describe the corpus as:

- an actual Aurora service incident;
- a real AWS Support case;
- customer telemetry;
- production guidance for a specific customer environment.

The PostgreSQL lock behavior and SQL syntax are real; the surrounding records
are not.

## Intentional Exclusions

- No customer or employee data
- No committed credentials, database passwords, tokens, or private keys
- No analytics, tracking, or remote frontend assets
- No automatic source-system actions
- No generic live connector in the one-hour core
- No claim that local PostgreSQL validation is Aurora validation

Generated dumps, embedding caches, logs, local databases, `.env`,
`frontend/.env`, and `.claude/settings.local.json` must remain uncommitted unless
a release artifact is intentionally reviewed and approved.

## Credentials

Workshop Studio should provide short-lived role credentials and store the
database secret in AWS Secrets Manager. `make aurora-local-env` writes ignored
local environment files with restrictive permissions.

Relevant configuration:

- `DATABASE_URL`
- `AWS_REGION` and `AWS_DEFAULT_REGION`
- `BEDROCK_EMBEDDING_MODEL`
- `BEDROCK_SYNTHESIS_MODEL`
- `COHERE_RERANK_MODEL`
- `AGENTCORE_GATEWAY_URL`

Model identifiers are configuration, not secrets. Database passwords and AWS
credentials are secrets.

## Database Authorization

The workshop application role requires only the schemas and operations used by
the lab. A production deployment should separate:

- authoritative casework writers;
- search index workers;
- read-only retrieval/API roles;
- schema migration ownership.

Do not grant the API role unrestricted writes to authoritative operational
tables. The local workshop uses one administrative role for setup convenience;
that is not the production privilege model.

All application SQL values are parameterized. Dynamic retrieval mode selection
is constrained by Pydantic literals and maps to fixed SQL statements.

## Evidence ACLs

Each evidence item and indexed document carries an `acl` JSONB whose
`visibility` is either `workshop` or `restricted`. Enforcement is layered:

- **Row-level security** (`sql/11_roles_rls.sql`) is enabled and **forced** on
  `casework.evidence_items`, `retrieval.documents`, and `retrieval.chunks`. All
  three gate on visibility plus the `can_see_restricted` clearance;
  `retrieval.documents` and `retrieval.chunks` read the projected column, and
  `casework.evidence_items` reads the JSONB it is projected from:

```sql
-- retrieval.documents, retrieval.chunks
acl_visibility = 'workshop'
  OR pg_has_role(current_user, 'can_see_restricted', 'USAGE')

-- casework.evidence_items
coalesce(acl ->> 'visibility', 'restricted') = 'workshop'
  OR pg_has_role(current_user, 'can_see_restricted', 'USAGE')
```

  Every detail and junction table beneath `casework.evidence_items` carries no
  visibility clause of its own. Each inherits visibility by reachability, through
  a policy that tests `EXISTS` against its parent evidence row.
- **The explicit predicate** runs inside every retrieval arm and at every
  traversal hop, so the planner filters early and a pasted verify-SQL statement
  returns the same rows without a hidden session prerequisite. Arms reading the
  JSONB call `retrieval.acl_visible(acl)`; arms reading the projected column call
  `retrieval.acl_scalars_visible(acl_visibility)`. Both evaluate the same
  expression as the policy.
- **Column masking** (`sql/12_masking.sql`) redacts the account name, case
  description, customer commitment, and the rendered `chunk_text` blob for
  `persona_auditor` only.

Identity is a **persona**, one of `analyst`, `admin`, or `auditor`. Personas are
`NOLOGIN` database roles; the app pool connects as `workshop_app`, which holds no
table grants, and issues one `SET LOCAL ROLE persona_<persona>` per request
transaction. With no role set, a `SELECT` raises `permission denied`: the pool
identity has no standing privilege path.

Clearance is additive: the `can_see_restricted` role is GRANTed to
`persona_admin` and `persona_auditor`, never to `persona_analyst`. Restricted
evidence, `CASE-7421` and six supporting objects, is invisible to the analyst
at the table, not merely absent from a result set.

This is a teaching policy, not a complete enterprise authorization system. RLS
moves *enforcement* into the database; **which persona a request assumes is still
asserted by the application**, because this workshop ships no authentication. A
production system must authenticate the caller, map current source-system
authorization into the persona decision, and revalidate live when indexed ACL
metadata may be stale.

## Citation Integrity

Citations are created only from retrieved document and chunk versions. The
database stores:

- source URI and revision;
- evidence, document, and chunk IDs;
- quoted text;
- cited claim.

`proof.validate_answer_citations` verifies revision and quote integrity against
the exact persisted chunk. The synthesis prompt cannot create a valid citation
to an unknown row. The API fails rather than inventing evidence when the
database or model is unavailable.

Citation integrity does not replace source review or establish that a source
claim is correct.

## Model Calls

With the workshop defaults:

- query text is sent to Cohere Embed 4 through Bedrock Runtime;
- the fused candidate text is sent to Cohere Rerank v3.5 through Bedrock Agent
  Runtime;
- up to eight numbered evidence excerpts are sent to Claude Sonnet through
  Bedrock Runtime Converse with Global CRIS.

The synthesis request sets an explicit maximum output token count. Bedrock
clients use bounded adaptive retries.

Review Bedrock data handling, cross-Region routing, IAM resources, model
lifecycle, and CloudTrail requirements before deployment. Global CRIS can route
outside the source Region across commercial Regions; use a geographic profile
instead when residency requirements demand it.

The validated synthesis path is Converse plus Global CRIS. The application does
not claim Mantle and CRIS simultaneously.

## Network Surface

The React frontend calls only the configured FastAPI origin. FastAPI allows
configured local development origins and an explicit regex; production
deployment must replace those defaults with the deployed origin.

The local API has no end-user authentication and must not be exposed publicly.
The managed workshop tool boundary uses `AWS_IAM` authorization at AgentCore
Gateway. Gateway authorization does not replace database row authorization.

## Operational Safety

- Corpus load resets workshop tables. Run it only against the intended
  disposable workshop database.
- Release-scale `--embed-missing` makes billable model calls and is never
  enabled implicitly.
- HNSW and GIN index operations can consume CPU, memory, storage, and lock time;
  prebuild them before participants arrive.
- Do not run destructive reset scripts or bulk generation against a production
  database.
- Keep `pg_stat_statements` text and logs free of secrets and unnecessary
  customer content.

## Review Checklist

- [ ] `git status --ignored` shows no committed local secrets or logs.
- [ ] Corpus and restore artifacts contain only synthetic records.
- [ ] Source archive SHA and Git revision match Workshop Studio.
- [ ] Database roles follow the intended workshop or production privilege model.
- [ ] ACL-denial tests pass before fusion and traversal.
- [ ] Citation validation passes for the live answer.
- [ ] CORS and API exposure match the deployment.
- [ ] Bedrock model IDs, lifecycle, CRIS routing, IAM, and quotas are current.
- [ ] The final smoke test ran against the target Aurora PostgreSQL environment.
