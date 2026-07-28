# Hybrid Retrieval Workbench complete implementation specification

## 0. Document status

This document is the consolidated implementation contract for Hybrid Retrieval Workbench, the incident-evidence workbench used in DAT410 at AWS re:Invent 2026.

- **Session:** Build agentic hybrid retrieval with Amazon Aurora PostgreSQL
- **Format:** Builders' session
- **Total session:** 60 minutes
- **Presentation:** 10 minutes
- **Hands-on:** 40 minutes across three modules
- **Arrival, environment check, wrap, and reserve:** 10 minutes
- **Product:** Hybrid Retrieval Workbench — Aurora PostgreSQL incident evidence
- **Corpus:** controlled synthetic operational evidence
- **Primary database:** Amazon Aurora PostgreSQL
- **Core managed extension:** Amazon Bedrock AgentCore Gateway, used only for tool-contract portability in Module 3
- **Release status:** final only after target-Aurora, Bedrock, AgentCore Gateway, artifact, and Workshop Studio gates pass

Source code, SQL, tests, API responses, and measured release receipts are authoritative when they disagree with illustrative mock data.

---

## 1. Final product thesis

Hybrid Retrieval Workbench is not a generic chatbot and not broad enterprise search.

It is an incident-evidence workbench that demonstrates how Aurora PostgreSQL can provide:

- exact identifier retrieval;
- PostgreSQL full-text retrieval;
- filtered semantic retrieval with `pgvector`;
- typo recovery with `pg_trgm`;
- SQL, metadata, time-window, and ACL filters;
- weighted reciprocal rank fusion;
- typed relationship traversal;
- source comparison;
- separate model reranking;
- exact citations;
- replayable database receipts;
- retrieval and traversal evaluation.

The primary sound bite is:

> This is not just a generated answer. It is a retrieved, ranked, cited, and replayable database receipt.

A second sound bite for Module 3 is:

> The tool contract moves; the retrieval authority does not.

---

## 2. Scope decision: AgentCore Gateway belongs, narrowly

Amazon Bedrock AgentCore Gateway is appropriate as the Module 3 capstone because it can convert existing APIs into MCP-compatible tools from an OpenAPI definition. The workshop uses this capability to prove transport portability.

It must not become another architecture branch or provisioning exercise.

### Included

- pre-provisioned AgentCore Gateway;
- one OpenAPI 3.x definition with stable `operationId` values;
- a managed MCP endpoint exposing the same Hybrid Retrieval Workbench tool contracts;
- a parity exercise comparing HTTP, local stdio MCP, and Gateway results;
- Gateway transport/trace metadata recorded separately from Hybrid Retrieval Workbench proof data.

### Excluded from the participant path

- creating a Gateway;
- configuring IAM, inbound auth, outbound auth, OAuth, Identity, or Policy;
- deploying AgentCore Runtime;
- adding live Jira, Slack, Salesforce, or other connectors;
- changing retrieval logic for Gateway;
- using Gateway semantic tool search;
- using AgentCore as a second proof or retrieval store.

### Cut rule

Module 3 is the first optional cut if the room is behind. Modules 1 and 2 remain complete without it.

---

## 3. Standardized identifier system

Use mnemonic thousand-ranges.

| Range | Kind | Canonical fixtures |
|---|---|---|
| `1000` | changes | `CHG-1000`, `CHG-1001`, `CHG-1002` |
| `2000` | incidents | `INC-2000`, `INC-2001` |
| `3000` | lock evidence | `LOCK-3000`, `LOCK-3001` |
| `4000` | support cases | `CASE-4000`, `CASE-4001`, `CASE-4002` |
| `5000` | runbooks | `RB-5000`, `RB-5001` |
| `6000` | commitments | `COMMIT-6000` |
| `7000` | retrieval runs | `RUN-7000` through `RUN-7004` |
| `7100` | agent-loop subquestion retrievals | `RUN-7100` through `RUN-7199` |
| `8000` | agent runs | `ARUN-8000` |

### Canonical evidence

| ID | Kind | Role |
|---|---|---|
| `CHG-1000` | change | confirmed cause; ordinary `CREATE INDEX` on writer |
| `CHG-1001` | change | competing change explicitly ruled out |
| `CHG-1002` | change | follow-up `CREATE INDEX CONCURRENTLY` change |
| `INC-2000` | incident | checkout write incident |
| `INC-2001` | incident | older look-alike incident used as a decoy |
| `LOCK-3000` | lock evidence | first blocked writer and blocking PID snapshot |
| `LOCK-3001` | lock evidence | second snapshot confirming the same blocker |
| `CASE-4000` | support case | Acme Retail, visible and affected |
| `CASE-4001` | support case | affected but restricted to `support-lead` |
| `CASE-4002` | support case | visible and explicitly unaffected |
| `RB-5000` | runbook | approved online index build and cleanup guidance |
| `RB-5001` | runbook | generic write-latency triage decoy |
| `COMMIT-6000` | commitment | RCA and safe-fix plan due to Acme Retail |
| `RUN-7000` | proof run | canonical full investigation |
| `RUN-7001` | proof run | semantic symptom |
| `RUN-7002` | proof run | exact ID |
| `RUN-7003` | proof run | fuzzy ID |
| `RUN-7004` | proof run | customer impact |

### Reserved allocation

- `x000–x009`: canonical thread and direct follow-up.
- `x010–x099`: controlled negatives and evaluation fixtures.
- `x100+`: deterministic background corpus.

### Controlled typo fixture

The trigram mutation is `CGH-1000` — a **letter** transposition of `CHG-1000`. It is not
an allocated identifier and never exists in the corpus.

Do not use a digit transposition such as `CHG-0100`. Digit transpositions collide with
the `x100+` background range: `CHG-0100` is trigram-equidistant from `CHG-1000` and from
background identifier `CHG-1100`, so the recovery result would depend on tie-break
order. See §11.5 for the measured similarities.

### Identifier column contract

`CHG-1000` and its siblings are **`external_key`** values. `evidence_id` is separate
immutable internal identity and is what every edge, candidate, citation, and receipt
references. The workshop fixture seeds the two to the same string for legibility; code
must not depend on that. See §9.0.

---

## 4. Canonical question and query ladder

### Full canonical question

> During `INC-2000` on `checkout-prod-01`, why did checkout writes appear to hang while reads continued? Determine whether `CHG-1000` or `CHG-1001` caused the incident, identify the customer impact visible to the current principal, explain what evidence rules out the alternative change, and cite the lock evidence and approved runbook supporting both immediate recovery and the preventive follow-up.

### Compact UI question

> Why did writes hang during `INC-2000`, which change caused it, who was affected, and what was the safe recovery?

### Query ladder

| Preset | Query | Proof |
|---|---|---|
| exact | `What did CHG-1000 change?` | exact/B-tree and FTS |
| semantic | `Why were checkout writes hanging while reads still worked?` | semantic vocabulary bridge |
| fuzzy | `Did CGH-1000 cause INC-2000?` | trigram typo recovery |
| impact | `Which customer was affected by INC-2000?` | ACL-safe retrieval plus typed relationships |
| canonical | full canonical question | fusion, traversal, comparison, citations, proof |

Do not put an intentional typo into the canonical question. Fuzzy retrieval is a controlled mutation.

In the fuzzy preset, `INC-2000` resolves exactly and `CGH-1000` does not. Only the
unresolved token reaches the trigram arm (§11.5), so the sentence itself is never used
as a similarity probe.

---

## 5. Expected evidence-backed conclusion

### Answer content under the default `workshop` principal

This is what the generated answer may assert. Each line is a factual claim and each
carries a citation.

| Claim | Cited by |
|---|---|
| `CHG-1000` ran ordinary `CREATE INDEX` on the production writer. | `CHG-1000` |
| The build acquired a relation-level lock that allowed reads to continue while checkout writes queued. | `INC-2000` |
| `LOCK-3000` identifies the index-building backend as the blocker, and `LOCK-3001` confirms the same blocker on a second writer. | `LOCK-3000` |
| Acme Retail was affected, and the account carries commitment `COMMIT-6000`. | `CASE-4000` |
| Immediate recovery cancelled the blocking build and released queued writers. | `INC-2000` |
| `RB-5000` recommends `CREATE INDEX CONCURRENTLY` outside a transaction, progress monitoring, and invalid-index cleanup after failure. | `RB-5000` |

The five distinct citation sources are `INC-2000`, `CHG-1000`, `LOCK-3000`, `CASE-4000`,
`RB-5000` — the set `fixtures/canonical-scenario.json` asserts.

### Comparison verdicts

These are `compare_sources` output, rendered as verdict chips beside the answer. They
are not sentences in the answer body, so they do not need answer citations; each
resolves to a canonical FK edge and its rationale.

| Evidence | Verdict | Basis |
|---|---|---|
| `CHG-1000` | `change_confirmed` | lock footprint and timing |
| `CHG-1001` | `change_ruled_out` | timing and absence of a lock footprint |
| `CASE-4000` | `affected` | canonical incident-case edge |
| `CASE-4002` | `not_affected` | canonical incident-case edge |

`CHG-1002` is surfaced as the preventive follow-up through the `RB-5000` relationship,
not as an uncited assertion.

### Facilitator ground truth — not answer content

`CASE-4001` is affected and is restricted to `support-lead`. Under the default principal
it is **absent**: it does not appear in retrieval, traversal, comparison, citations, or
the answer text, and the answer must not mention that withheld evidence exists.
Disclosing it would defeat the ACL demonstration.

The facilitator shows it by switching the principal to `support-lead` and re-running,
which makes it appear through the same code path. That switch is the proof, not a
sentence about hidden evidence.

---

## 6. Why hybrid retrieval is necessary

| Need | Capability | Failure without it |
|---|---|---|
| exact incident/change/lock/runbook IDs | B-tree plus lexical retrieval | embeddings smear identifiers |
| “writes hanging while reads continued” | semantic retrieval | exact keywords differ across evidence |
| `CGH-1000` | indexed trigram | exact and FTS return nothing |
| cluster, incident, severity, time | SQL/metadata filters | semantic results are stale or unrelated |
| restricted customer evidence | ACL inside every arm and hop | post-filtering leaks or distorts ranking |
| cause versus alternative | typed relationships plus source comparison | flat top-k cannot prove causality |
| affected versus unaffected | canonical incident-case edges | similarity does not equal relationship |
| safe procedure | runbook retrieval and citation | generated advice is not auditable |
| final answer | citations and proof receipt | model text cannot be replayed or validated |
| performance | plans, index usage, and stage timing | black-box retrieval cannot be tuned |

---

## 7. System ownership

### Aurora PostgreSQL owns

- normalized synthetic casework;
- deterministic document search index;
- document/chunk versions;
- exact, lexical, vector, and fuzzy retrieval;
- SQL, metadata, time, and ACL filters;
- weighted RRF;
- canonical and governed inferred relationships;
- candidate and stage diagnostics;
- answer and citation receipts;
- replay;
- evaluation judgments and results.

### Amazon Bedrock owns

- embedding model execution;
- optional reranking;
- optional cited synthesis.

Bedrock never becomes a retrieval authority and never overwrites Aurora diagnostics.

### AgentCore Gateway owns

- managed MCP exposure of existing Hybrid Retrieval Workbench tools;
- transport authentication and Gateway observability in Workshop Studio.

Gateway does not own the tool implementation, retrieval logic, proof receipt, ranking, or evidence.

### CloudWatch Database Insights owns

- managed inspection of Aurora database load;
- captured-plan analysis;
- lock-tree visualization.

### Authoritative source systems would own in production

- mutable workflow state;
- current permissions;
- source actions;
- connector cursors;
- transport receipts.

The workshop materializes a synthetic fixture. Federation and live revalidation are architecture context only.

---

## 8. Core database architecture

```text
casework.* typed synthetic facts
    |
    | deterministic render + source revision + search document hash
    v
retrieval.* versioned search index
    documents -> chunks -> embeddings -> indexes
    |
    | filters + ACL inside every arm
    v
exact/B-tree + FTS/GIN + vector/HNSW + fuzzy/pg_trgm
    |
    v
weighted RRF -> optional rerank
    |
    +--> relationship traversal and source comparison
    |
    v
proof.* candidates + stages + answers + citations + evaluation
```

### Schemas

| Schema | Purpose |
|---|---|
| `casework` | authoritative workshop facts and FK relationships |
| `retrieval` | derived, versioned, rebuildable search index |
| `proof` | immutable/historical retrieval, answer, citation, and evaluation receipts |

Base tables, not a materialized view, are required because the search index includes external embeddings, incremental versions, current promotion, tombstones, and historical citation references.

---

## 9. Data model

This section is authoritative DDL. It runs as written on the platform baseline in
§23. Codex implements this schema; it does not invent an alternative one.

### 9.0 Identity rule: `evidence_id` versus `external_key`

These are two different columns with two different contracts. Do not collapse them.

- `evidence_id` is immutable internal identity. Every search index row, edge, candidate,
  citation, and receipt references `evidence_id`. It never changes for the life of an
  evidence item, even if the source system renames the record.
- `external_key` is the source system's domain key (`INC-2000`, `CHG-1000`). It is what
  users type, what `decompose_question` extracts, and what exact/B-tree and trigram
  retrieval match against. It is mutable in principle.

In the workshop fixture the two are **seeded to the same string** so receipts and the
UI stay legible. Application code must never rely on that: always join on
`evidence_id`, always display and match `external_key`.

### 9.1 Extensions, schemas, and platform requirements

```sql
-- pgvector >= 0.8.0 is required for HNSW iterative scan (§11).
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
-- pg_stat_statements additionally requires shared_preload_libraries in the
-- Aurora cluster parameter group; it cannot be enabled by CREATE EXTENSION alone.
-- It is also a hard prerequisite for aurora_stat_plans (§18.1).
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

CREATE SCHEMA IF NOT EXISTS casework;
CREATE SCHEMA IF NOT EXISTS retrieval;
CREATE SCHEMA IF NOT EXISTS proof;
```

`gen_random_uuid()` is built into PostgreSQL 13 and later. On an older engine, add
`CREATE EXTENSION IF NOT EXISTS pgcrypto`.

`btree_gin` is deliberately **not** installed. The only index that would have needed it
was a composite `gin (kind, identity_tsv)`, and no query issues a bare `kind =`
predicate — kind selectivity is served by `documents_kind_time_idx` and by the
denormalized scalars in §11.7. An extension that exists to support one unreachable
index is a dependency with no reader.

### 9.2 `casework` — authoritative synthetic facts

```sql
CREATE TABLE casework.database_clusters (
  cluster_id      text PRIMARY KEY,
  engine          text        NOT NULL,
  engine_version  text        NOT NULL,
  region          text        NOT NULL,
  environment     text        NOT NULL CHECK (environment IN ('prod','staging','dev')),
  service         text        NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE casework.evidence_items (
  evidence_id     text PRIMARY KEY,
  kind            text        NOT NULL
                    CHECK (kind IN ('incident','change','lock','case','runbook','commitment')),
  external_key    text        NOT NULL,
  cluster_id      text        REFERENCES casework.database_clusters(cluster_id),
  title           text        NOT NULL,
  source_uri      text        NOT NULL,   -- workshop://<kind>/<external_key>
  source_revision text        NOT NULL,   -- 'rev-0001'
  source_time     timestamptz NOT NULL,
  acl             jsonb       NOT NULL
                    DEFAULT '{"visibility":"workshop","principals":[]}'::jsonb,
  is_deleted      boolean     NOT NULL DEFAULT false,
  deleted_at      timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT evidence_items_external_key_uniq UNIQUE (kind, external_key),
  CONSTRAINT evidence_items_tombstone_ck CHECK (is_deleted = (deleted_at IS NOT NULL))
);

CREATE INDEX evidence_items_external_key_idx
  ON casework.evidence_items USING btree (external_key);
CREATE INDEX evidence_items_kind_time_idx
  ON casework.evidence_items USING btree (kind, source_time DESC);
CREATE INDEX evidence_items_acl_idx
  ON casework.evidence_items USING gin (acl jsonb_path_ops);

CREATE TABLE casework.incidents (
  evidence_id text PRIMARY KEY REFERENCES casework.evidence_items(evidence_id) ON DELETE CASCADE,
  severity    text        NOT NULL CHECK (severity IN ('SEV1','SEV2','SEV3','SEV4')),
  started_at  timestamptz NOT NULL,
  ended_at    timestamptz,
  impact      text        NOT NULL,
  resolution  text,
  CONSTRAINT incidents_interval_ck CHECK (ended_at IS NULL OR ended_at >= started_at)
);

CREATE TABLE casework.changes (
  evidence_id   text PRIMARY KEY REFERENCES casework.evidence_items(evidence_id) ON DELETE CASCADE,
  change_type   text        NOT NULL,   -- 'schema' | 'config' | 'deploy'
  change_sql    text,
  started_at    timestamptz NOT NULL,
  ended_at      timestamptz,
  owner         text        NOT NULL,
  description   text        NOT NULL,
  rollback_plan text
);

CREATE TABLE casework.support_cases (
  evidence_id text PRIMARY KEY REFERENCES casework.evidence_items(evidence_id) ON DELETE CASCADE,
  account     text        NOT NULL,
  tier        text        NOT NULL,
  severity    text        NOT NULL,
  sla_due_at  timestamptz,
  opened_at   timestamptz NOT NULL,
  description text        NOT NULL
);

CREATE TABLE casework.runbooks (
  evidence_id     text PRIMARY KEY REFERENCES casework.evidence_items(evidence_id) ON DELETE CASCADE,
  runbook_version text NOT NULL,
  procedure       text NOT NULL,
  applicability   text NOT NULL,
  owner           text NOT NULL,
  caveats         text
);

CREATE TABLE casework.lock_evidence (
  evidence_id        text PRIMARY KEY REFERENCES casework.evidence_items(evidence_id) ON DELETE CASCADE,
  incident_id        text        NOT NULL REFERENCES casework.incidents(evidence_id),
  captured_at        timestamptz NOT NULL,
  blocked_pid        integer     NOT NULL,
  blocking_pid       integer     NOT NULL,
  lock_type          text        NOT NULL,   -- 'relation'
  lock_mode          text        NOT NULL,   -- 'ShareLock'
  wait_event         text        NOT NULL,   -- 'Lock:relation'
  blocked_statement  text        NOT NULL,
  blocking_statement text        NOT NULL,
  CONSTRAINT lock_evidence_pids_ck CHECK (blocked_pid <> blocking_pid)
);

CREATE TABLE casework.customer_commitments (
  evidence_id text PRIMARY KEY REFERENCES casework.evidence_items(evidence_id) ON DELETE CASCADE,
  account     text        NOT NULL,
  commitment  text        NOT NULL,
  due_at      timestamptz NOT NULL,
  status      text        NOT NULL CHECK (status IN ('open','met','missed'))
);
```

Canonical relationships are foreign keys, never inferred:

```sql
CREATE TABLE casework.incident_changes (
  incident_id  text NOT NULL REFERENCES casework.incidents(evidence_id) ON DELETE CASCADE,
  change_id    text NOT NULL REFERENCES casework.changes(evidence_id)   ON DELETE CASCADE,
  relationship text NOT NULL
    CHECK (relationship IN ('change_suspected','change_confirmed','change_ruled_out')),
  rationale    text NOT NULL,
  PRIMARY KEY (incident_id, change_id)
);

CREATE TABLE casework.incident_support_cases (
  incident_id  text NOT NULL REFERENCES casework.incidents(evidence_id)     ON DELETE CASCADE,
  case_id      text NOT NULL REFERENCES casework.support_cases(evidence_id) ON DELETE CASCADE,
  relationship text NOT NULL
    CHECK (relationship IN ('affected','potentially_affected','not_affected')),
  rationale    text NOT NULL,
  PRIMARY KEY (incident_id, case_id)
);

CREATE TABLE casework.incident_runbooks (
  incident_id  text NOT NULL REFERENCES casework.incidents(evidence_id) ON DELETE CASCADE,
  runbook_id   text NOT NULL REFERENCES casework.runbooks(evidence_id)  ON DELETE CASCADE,
  relationship text NOT NULL CHECK (relationship IN ('used','recommended','rejected')),
  rationale    text NOT NULL,
  PRIMARY KEY (incident_id, runbook_id)
);

CREATE TABLE casework.support_case_commitments (
  case_id       text NOT NULL REFERENCES casework.support_cases(evidence_id)       ON DELETE CASCADE,
  commitment_id text NOT NULL REFERENCES casework.customer_commitments(evidence_id) ON DELETE CASCADE,
  PRIMARY KEY (case_id, commitment_id)
);
```

The verdict vocabulary in these `CHECK` constraints is the same vocabulary
`compare_sources` returns and `fixtures/canonical-scenario.json` asserts.

### 9.3 `retrieval` — derived, versioned search index

```sql
CREATE TABLE retrieval.search_index_queue (
  outbox_id       bigserial PRIMARY KEY,
  evidence_id     text NOT NULL REFERENCES casework.evidence_items(evidence_id) ON DELETE CASCADE,
  source_revision text        NOT NULL,
  queued_at       timestamptz NOT NULL DEFAULT now(),
  completed_at    timestamptz,
  status          text        NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','in_progress','done','failed')),
  error           text
);

-- At most one open outbox row per evidence item.
CREATE UNIQUE INDEX search_index_queue_open_uidx
  ON retrieval.search_index_queue (evidence_id) WHERE completed_at IS NULL;

CREATE TABLE retrieval.search_index_builds (
  build_id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  evidence_id         text NOT NULL REFERENCES casework.evidence_items(evidence_id) ON DELETE CASCADE,
  renderer_version    text        NOT NULL,
  chunker_version     text        NOT NULL,
  embedding_model_id  text        NOT NULL,
  embedding_dimension integer     NOT NULL,
  search_document_hash     text        NOT NULL,
  document_count      integer     NOT NULL DEFAULT 0,
  chunk_count         integer     NOT NULL DEFAULT 0,
  embedded_count      integer     NOT NULL DEFAULT 0,
  status              text        NOT NULL
                        CHECK (status IN ('running','ready','failed','skipped_unchanged')),
  started_at          timestamptz NOT NULL DEFAULT now(),
  finished_at         timestamptz,
  error               text
);

CREATE TABLE retrieval.documents (
  document_version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  evidence_id         text NOT NULL REFERENCES casework.evidence_items(evidence_id) ON DELETE CASCADE,
  external_key        text        NOT NULL,
  kind                text        NOT NULL,
  title               text        NOT NULL,
  body                text        NOT NULL,
  source_uri          text        NOT NULL,
  source_revision     text        NOT NULL,
  source_time         timestamptz NOT NULL,
  acl                 jsonb       NOT NULL,
  filters             jsonb       NOT NULL,
  metadata            jsonb       NOT NULL DEFAULT '{}'::jsonb,
  -- Denormalized, indexable search columns for acl and filters. The builder writes
  -- them from the same renderer row, and a document version is immutable, so they
  -- cannot drift within a version. The jsonb columns remain for the receipt.
  acl_visibility      text        NOT NULL,
  acl_principals      text[]      NOT NULL DEFAULT '{}',
  f_cluster_id        text,
  f_incident_id       text,
  f_account           text,
  f_severity          text,
  f_environment       text,
  renderer_version    text        NOT NULL,
  chunker_version     text        NOT NULL,
  embedding_model_id  text        NOT NULL,
  search_document_hash     text        NOT NULL,
  identity_tsv        tsvector GENERATED ALWAYS AS (
                        setweight(to_tsvector('simple',  coalesce(external_key,'')), 'A') ||
                        setweight(to_tsvector('english', coalesce(title,'')),        'B')
                      ) STORED,
  state               text        NOT NULL
                        CHECK (state IN ('building','ready','superseded','failed')),
  is_current          boolean     NOT NULL DEFAULT false,
  built_at            timestamptz NOT NULL DEFAULT now(),
  superseded_at       timestamptz,
  build_id            uuid REFERENCES retrieval.search_index_builds(build_id)
);

-- Enforces "one current ready document per live evidence item" in the database,
-- not in application code. A failed build physically cannot promote a second one.
CREATE UNIQUE INDEX documents_one_current_uidx
  ON retrieval.documents (evidence_id) WHERE is_current;

-- Deterministic version identity (§10). Re-rendering unchanged content collides here
-- and is reused rather than duplicated.
CREATE UNIQUE INDEX documents_version_uidx
  ON retrieval.documents
     (evidence_id, renderer_version, chunker_version, embedding_model_id, search_document_hash);

CREATE INDEX documents_external_key_idx
  ON retrieval.documents USING btree (external_key) WHERE is_current;
CREATE INDEX documents_kind_time_idx
  ON retrieval.documents USING btree (kind, source_time DESC) WHERE is_current;
CREATE INDEX documents_identity_tsv_idx
  ON retrieval.documents USING gin (identity_tsv);
CREATE INDEX documents_identity_trgm_idx
  ON retrieval.documents USING gin (external_key gin_trgm_ops, title gin_trgm_ops);
-- Reachable because the arms filter on these scalars directly (§11.7), not through
-- a jsonb function call.
CREATE INDEX documents_acl_visibility_idx
  ON retrieval.documents USING btree (acl_visibility) WHERE is_current;
CREATE INDEX documents_acl_principals_idx
  ON retrieval.documents USING gin (acl_principals);
CREATE INDEX documents_filter_scalars_idx
  ON retrieval.documents USING btree (f_cluster_id, f_incident_id, f_account) WHERE is_current;

CREATE TABLE retrieval.chunks (
  chunk_version_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_version_id uuid NOT NULL REFERENCES retrieval.documents(document_version_id) ON DELETE CASCADE,
  evidence_id         text NOT NULL REFERENCES casework.evidence_items(evidence_id)     ON DELETE CASCADE,
  chunk_ordinal       integer NOT NULL,
  chunk_text          text    NOT NULL,
  chunk_hash          text    NOT NULL,
  body_tsv            tsvector GENERATED ALWAYS AS (
                        to_tsvector('english', coalesce(chunk_text,''))
                      ) STORED,
  embedding           vector(1024),
  embedding_model_id  text    NOT NULL,
  embedding_dimension integer NOT NULL DEFAULT 1024,
  state               text    NOT NULL
                        CHECK (state IN ('pending_embedding','ready','failed')),
  is_current          boolean NOT NULL DEFAULT false,
  created_at          timestamptz NOT NULL DEFAULT now(),
  -- Denormalized from the owning document version so that every selective
  -- predicate in the vector arm is evaluated on THIS relation. See §11.4a.
  kind                text    NOT NULL,
  source_time         timestamptz NOT NULL,
  acl_visibility      text    NOT NULL,
  acl_principals      text[]  NOT NULL DEFAULT '{}',
  f_cluster_id        text,
  f_incident_id       text,
  f_account           text,
  f_severity          text,
  f_environment       text,
  CONSTRAINT chunks_ordinal_uniq UNIQUE (document_version_id, chunk_ordinal),
  CONSTRAINT chunks_ready_requires_embedding_ck
    CHECK (state <> 'ready' OR (embedding IS NOT NULL AND embedding_dimension = 1024))
);

CREATE INDEX chunks_body_tsv_idx ON retrieval.chunks USING gin (body_tsv);
CREATE INDEX chunks_evidence_idx ON retrieval.chunks USING btree (evidence_id) WHERE is_current;
CREATE INDEX chunks_acl_visibility_idx
  ON retrieval.chunks USING btree (acl_visibility) WHERE is_current AND state = 'ready';
CREATE INDEX chunks_acl_principals_idx ON retrieval.chunks USING gin (acl_principals);
CREATE INDEX chunks_filter_scalars_idx
  ON retrieval.chunks USING btree (f_cluster_id, kind, source_time)
  WHERE is_current AND state = 'ready';

-- Partial HNSW index: only current, ready chunks are ever searched, so the
-- currency predicate is index-resident instead of a post-filter.
CREATE INDEX chunks_embedding_hnsw_idx
  ON retrieval.chunks USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64)
  WHERE is_current AND state = 'ready';

-- Embedding reuse across document versions and across evidence items.
-- This is the "embedding cache key = embedding model ID + chunk hash" contract in §10.
CREATE TABLE retrieval.embedding_cache (
  embedding_model_id text NOT NULL,
  chunk_hash         text NOT NULL,
  embedding          vector(1024) NOT NULL,
  created_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (embedding_model_id, chunk_hash)
);

CREATE TABLE retrieval.inferred_edges (
  inferred_edge_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id        text NOT NULL REFERENCES casework.evidence_items(evidence_id) ON DELETE CASCADE,
  target_id        text NOT NULL REFERENCES casework.evidence_items(evidence_id) ON DELETE CASCADE,
  relationship     text NOT NULL,
  method           text NOT NULL,
  -- Strictly less than 1: an inferred edge can never masquerade as an FK fact.
  confidence       numeric(4,3) NOT NULL CHECK (confidence > 0 AND confidence < 1),
  source_revision  text NOT NULL,
  rationale        text,
  created_at       timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT inferred_edges_uniq UNIQUE (source_id, target_id, relationship, method),
  CONSTRAINT inferred_edges_no_self_ck CHECK (source_id <> target_id)
);
```

`retrieval.evidence_edges` is a read-only union of FK-derived canonical edges and
governed inferred edges. Canonical edges always carry `origin = 'canonical'` and
`confidence = 1`.

```sql
CREATE OR REPLACE VIEW retrieval.evidence_edges AS
SELECT ic.incident_id AS source_id, ic.change_id AS target_id, ic.relationship,
       'canonical'::text AS origin, 1.0::numeric AS confidence,
       NULL::text AS method, ic.rationale
FROM casework.incident_changes ic
UNION ALL
SELECT isc.incident_id, isc.case_id, isc.relationship,
       'canonical', 1.0, NULL, isc.rationale
FROM casework.incident_support_cases isc
UNION ALL
SELECT ir.incident_id, ir.runbook_id, ir.relationship,
       'canonical', 1.0, NULL, ir.rationale
FROM casework.incident_runbooks ir
UNION ALL
SELECT scc.case_id, scc.commitment_id, 'has_commitment',
       'canonical', 1.0, NULL, NULL
FROM casework.support_case_commitments scc
UNION ALL
SELECT le.incident_id, le.evidence_id, 'lock_evidence_for',
       'canonical', 1.0, NULL, NULL
FROM casework.lock_evidence le
UNION ALL
SELECT ie.source_id, ie.target_id, ie.relationship,
       'inferred', ie.confidence, ie.method, ie.rationale
FROM retrieval.inferred_edges ie;
```

### 9.4 `proof` — receipts

```sql
CREATE TABLE proof.retrieval_runs (
  run_id             text PRIMARY KEY,          -- 'RUN-7000'
  query              text        NOT NULL,
  mode               text        NOT NULL
                       CHECK (mode IN ('hybrid','lexical','semantic','fuzzy')),
  filters            jsonb       NOT NULL DEFAULT '{}'::jsonb,
  principal          jsonb       NOT NULL,
  controls           jsonb       NOT NULL,      -- full SearchControls object as sent
  embedding_model_id text,
  rerank_model_id    text,
  synthesis_model_id text,
  status             text        NOT NULL CHECK (status IN ('running','succeeded','failed')),
  candidate_count    integer     NOT NULL DEFAULT 0,
  latency_ms         numeric(10,3),
  contract_version   text        NOT NULL,
  created_at         timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE proof.retrieval_candidates (
  run_id              text NOT NULL REFERENCES proof.retrieval_runs(run_id) ON DELETE CASCADE,
  fused_rank          integer NOT NULL,
  final_rank          integer,
  evidence_id         text    NOT NULL,
  external_key        text    NOT NULL,
  kind                text    NOT NULL,
  title               text    NOT NULL,
  source_uri          text    NOT NULL,
  source_revision     text    NOT NULL,
  document_version_id uuid    NOT NULL REFERENCES retrieval.documents(document_version_id),
  chunk_version_id    uuid    NOT NULL REFERENCES retrieval.chunks(chunk_version_id),
  text_position       integer,
  vector_position     integer,
  fuzzy_position      integer,
  text_score          real,
  vector_distance     real,
  fuzzy_score         real,
  rrf_score           double precision NOT NULL,
  rerank_score        real,
  why                 text,
  PRIMARY KEY (run_id, evidence_id),
  CONSTRAINT retrieval_candidates_fused_rank_uniq UNIQUE (run_id, fused_rank)
);
```

`fused_rank` is **dense and gapless**, `1..candidate_count`, over exactly the candidates
persisted for that run. A receipt that returns ranks `2,3,6,7,4` for a five-candidate
run is malformed. `final_rank` is populated only when reranking ran; otherwise it is
`NULL` and consumers fall back to `fused_rank`.

```sql
CREATE TABLE proof.run_stages (
  run_id        text    NOT NULL REFERENCES proof.retrieval_runs(run_id) ON DELETE CASCADE,
  stage_ordinal integer NOT NULL,
  stage_name    text    NOT NULL,
  duration_ms   numeric(10,3) NOT NULL,
  details       jsonb   NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (run_id, stage_ordinal)
);
```

An answer is **not** one-to-one with a retrieval. The canonical question decomposes into
five subquestions, each of which gets its own `search_evidence` call, and one of them
gets a second call after escalation. The join table below is where one-to-many lives.

```sql
CREATE TABLE proof.agent_runs (
  agent_run_id      text PRIMARY KEY,             -- 'ARUN-8000'
  question          text        NOT NULL,
  principal         jsonb       NOT NULL,
  filters_initial   jsonb       NOT NULL DEFAULT '{}'::jsonb,
  controls_initial  jsonb       NOT NULL,
  max_tool_calls    integer     NOT NULL DEFAULT 12 CHECK (max_tool_calls  > 0),
  max_escalations   integer     NOT NULL DEFAULT 2  CHECK (max_escalations >= 0),
  tool_calls_spent  integer     NOT NULL DEFAULT 0,
  escalations_spent integer     NOT NULL DEFAULT 0,
  started_at        timestamptz NOT NULL DEFAULT now(),
  ended_at          timestamptz,
  status            text        NOT NULL CHECK (status IN
                      ('running','succeeded','partial','budget_exhausted','no_evidence','failed')),
  contract_version  text        NOT NULL,
  CONSTRAINT agent_runs_budget_ck
    CHECK (tool_calls_spent <= max_tool_calls AND escalations_spent <= max_escalations)
);

CREATE TABLE proof.agent_subquestions (
  agent_run_id          text    NOT NULL REFERENCES proof.agent_runs(agent_run_id) ON DELETE CASCADE,
  subquestion_id        text    NOT NULL,         -- 'SQ-1'
  ordinal               integer NOT NULL,
  subquestion_text      text    NOT NULL,
  required_kinds        text[]  NOT NULL,
  covered               boolean NOT NULL DEFAULT false,
  covering_evidence_ids text[]  NOT NULL DEFAULT '{}',
  missing_kinds         text[]  NOT NULL DEFAULT '{}',
  attempts              integer NOT NULL DEFAULT 0,
  PRIMARY KEY (agent_run_id, subquestion_id),
  CONSTRAINT agent_subquestions_ordinal_uniq UNIQUE (agent_run_id, ordinal),
  CONSTRAINT agent_subquestions_covered_ck
    CHECK (NOT covered OR cardinality(missing_kinds) = 0)
);

-- The one-to-many join. One agent run, five subquestions, six retrievals.
CREATE TABLE proof.agent_retrievals (
  agent_run_id   text    NOT NULL,
  subquestion_id text    NOT NULL,
  attempt        integer NOT NULL CHECK (attempt >= 1),
  run_id         text    NOT NULL REFERENCES proof.retrieval_runs(run_id) ON DELETE CASCADE,
  superseded_by  integer,                          -- attempt that replaced this one
  created_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (agent_run_id, subquestion_id, attempt),
  FOREIGN KEY (agent_run_id, subquestion_id)
    REFERENCES proof.agent_subquestions(agent_run_id, subquestion_id) ON DELETE CASCADE,
  CONSTRAINT agent_retrievals_run_uniq UNIQUE (run_id),
  CONSTRAINT agent_retrievals_supersede_ck
    CHECK (superseded_by IS NULL OR superseded_by > attempt)
);

CREATE TABLE proof.agent_escalations (
  agent_run_id   text    NOT NULL,
  subquestion_id text    NOT NULL,
  attempt        integer NOT NULL,                 -- the attempt this escalation produced
  reason         text    NOT NULL CHECK (reason IN
                   ('missing_required_kind','zero_candidates')),
  missing_kinds  text[]  NOT NULL DEFAULT '{}',
  changed        jsonb   NOT NULL,                 -- {"before":{...},"after":{...}}
  outcome        text    NOT NULL CHECK (outcome IN
                   ('covered','still_uncovered','budget_exhausted')),
  created_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (agent_run_id, subquestion_id, attempt),
  FOREIGN KEY (agent_run_id, subquestion_id)
    REFERENCES proof.agent_subquestions(agent_run_id, subquestion_id) ON DELETE CASCADE
);

CREATE TABLE proof.agent_answers (
  answer_id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_run_id      text NOT NULL UNIQUE
                      REFERENCES proof.agent_runs(agent_run_id) ON DELETE CASCADE,
  question          text NOT NULL,
  answer            text NOT NULL,
  synthesis_mode    text NOT NULL
                      CHECK (synthesis_mode IN ('model','extractive','no_evidence')),
  validation_status text NOT NULL DEFAULT 'pending'
                      CHECK (validation_status IN ('pending','valid','repaired','failed')),
  model_id          text,
  model_transport   text,
  input_tokens      integer,
  output_tokens     integer,
  created_at        timestamptz NOT NULL DEFAULT now()
);
```

A single-retrieval answer is a **degenerate agent run**: one subquestion, one attempt,
zero escalations. There is no second code path. `RUN-7000` stays exactly what it was — a
standalone `search_evidence` retrieval run with its own candidate receipt, unchanged for
the transport parity captures — and the canonical agent run `ARUN-8000` references it as
the retrieval for its first subquestion.

### 9.4a Coverage is a SQL rule, not a model judgement

A subquestion is covered when its retrieval returned at least one candidate of each
`required_kind` inside the top `N`. The agent's decision to escalate is therefore
inspectable and replayable, like every other decision in this system.

```sql
CREATE OR REPLACE FUNCTION proof.evaluate_subquestion_coverage(
  p_run_id         text,
  p_required_kinds text[],
  p_top_n          integer DEFAULT 10
) RETURNS TABLE (
  covered               boolean,
  missing_kinds         text[],
  covering_evidence_ids text[]
) LANGUAGE sql STABLE AS $$
  WITH top_n AS (
    SELECT rc.evidence_id, rc.kind
    FROM proof.retrieval_candidates rc
    WHERE rc.run_id = p_run_id
    ORDER BY COALESCE(rc.final_rank, rc.fused_rank)
    LIMIT p_top_n
  ),
  missing AS (
    SELECT ARRAY(
      SELECT rk FROM unnest(p_required_kinds) AS rk
      WHERE rk NOT IN (SELECT DISTINCT kind FROM top_n)
      ORDER BY rk
    ) AS missing_kinds
  )
  SELECT
    cardinality(m.missing_kinds) = 0,
    m.missing_kinds,
    ARRAY(SELECT DISTINCT t.evidence_id FROM top_n t
          WHERE t.kind = ANY (p_required_kinds) ORDER BY 1)
  FROM missing m;
$$;
```

Zero candidates yields `covered = false` with every required kind missing, which is the
`zero_candidates` escalation reason rather than a special case.

### 9.4b Citations, evaluation, and transport receipts

```sql
CREATE TABLE proof.answer_citations (
  answer_id           uuid    NOT NULL REFERENCES proof.agent_answers(answer_id) ON DELETE CASCADE,
  citation_number     integer NOT NULL,
  evidence_id         text    NOT NULL,
  external_key        text    NOT NULL,
  document_version_id uuid    NOT NULL REFERENCES retrieval.documents(document_version_id),
  chunk_version_id    uuid    NOT NULL REFERENCES retrieval.chunks(chunk_version_id),
  source_uri          text    NOT NULL,
  source_revision     text    NOT NULL,
  quote               text    NOT NULL,
  claim               text    NOT NULL,
  PRIMARY KEY (answer_id, citation_number)
);

CREATE TABLE proof.evaluation_queries (
  eval_query_id text PRIMARY KEY,               -- 'exact-change', 'semantic-symptom', ...
  eval_kind     text  NOT NULL CHECK (eval_kind IN ('retrieval','traversal')),
  query         text  NOT NULL,
  principal     jsonb NOT NULL,
  filters       jsonb NOT NULL DEFAULT '{}'::jsonb,
  notes         text
);

CREATE TABLE proof.relevance_judgments (
  eval_query_id text     NOT NULL REFERENCES proof.evaluation_queries(eval_query_id) ON DELETE CASCADE,
  evidence_id   text     NOT NULL REFERENCES casework.evidence_items(evidence_id)    ON DELETE CASCADE,
  grade         smallint NOT NULL CHECK (grade BETWEEN 0 AND 3),
  rationale     text,
  PRIMARY KEY (eval_query_id, evidence_id)
);

CREATE TABLE proof.traversal_results (
  eval_query_id text    NOT NULL REFERENCES proof.evaluation_queries(eval_query_id) ON DELETE CASCADE,
  seed_id       text    NOT NULL,
  target_id     text    NOT NULL,
  relationship  text    NOT NULL,
  expected      boolean NOT NULL,
  PRIMARY KEY (eval_query_id, seed_id, target_id, relationship)
);

CREATE TABLE proof.transport_invocations (
  invocation_id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  contract_version   text        NOT NULL,
  transport          text        NOT NULL
                       CHECK (transport IN ('http','stdio_mcp','agentcore_gateway')),
  tool_name          text        NOT NULL,
  request_id         text        NOT NULL,
  run_id             text        REFERENCES proof.retrieval_runs(run_id) ON DELETE SET NULL,
  transport_trace_id text,
  response_sha256    text        NOT NULL,
  started_at         timestamptz NOT NULL,
  ended_at           timestamptz NOT NULL,
  succeeded          boolean     NOT NULL,
  error              text
);
```

### 9.5 Transport receipt ownership

`proof.transport_invocations` does not duplicate candidate or answer data.

Adapters stay stateless and never open a database connection. The canonical service
accepts an explicit `invocation_context` argument — `{transport, request_id,
transport_trace_id}` — that each adapter fills in from its own runtime, and the service
writes the receipt row. Transport identity therefore reaches Aurora as a service
parameter, not as adapter-side SQL, and it never enters the canonical result object
that the parity normalizer compares.

### 9.6 Evaluation metric definitions

`POST /v1/evaluation` computes these and nothing else. Retrieval and traversal metrics
are reported in separate blocks and are never averaged together.

Retrieval metrics, over the graded judgments in `proof.relevance_judgments` at cutoff
`k` (default `k = 10`):

| Metric | Definition |
|---|---|
| `recall_at_k` | relevant items retrieved in top `k` / all relevant items for the query (grade `>= 1`) |
| `precision_at_k` | relevant items retrieved in top `k` / `k` |
| `mrr` | mean over queries of `1 / rank of first relevant item`, `0` if none in top `k` |
| `ndcg_at_k` | `DCG@k / IDCG@k`, with `DCG@k = sum over i of (2^grade_i - 1) / log2(i + 1)`, `i` 1-based |

Traversal metrics, over `proof.traversal_results`:

| Metric | Definition |
|---|---|
| `relationship_recall` | expected edges reached / expected edges (`expected = true`) |
| `relationship_precision` | expected edges reached / all edges reached |

A traversal result is never scored as if it were a top-`k` retrieval list.

---

## 10. search index contract

```text
document version =
  evidence_id + renderer version + chunker version
  + embedding model ID + search document hash

chunk version =
  document_version_id + chunk ordinal + chunk hash

embedding cache key =
  embedding model ID + chunk hash
```

Requirements:

- one current ready document per live evidence item;
- historical document and chunk versions remain addressable;
- unchanged model+hash embeddings are reused;
- failed builds never promote two current ready versions;
- tombstones supersede current search state without erasing history;
- `/ready` calls `retrieval.assert_search_index_ready()` and fails closed on drift.

### 10.1 The deterministic renderer

`casework.v_evidence_documents` is the input contract to the search index. It is **not**
the indexed search surface — nothing queries it at request time. It renders typed
casework rows into source identity, title, body, ACL, typed filters, metadata, and a
SHA-256 `search_document_hash`. Given identical casework rows it must emit byte-identical
output, because the hash is what decides whether a rebuild is a no-op.

```sql
CREATE OR REPLACE VIEW casework.v_evidence_documents AS
WITH rendered AS (
  SELECT
    e.evidence_id, e.external_key, e.kind, e.title,
    e.source_uri, e.source_revision, e.source_time, e.acl, e.is_deleted, e.cluster_id,
    CASE e.kind
      WHEN 'incident' THEN format(
        'Incident %s severity %s on cluster %s. Window %s to %s. Impact: %s Resolution: %s',
        e.external_key, i.severity, e.cluster_id,
        to_char(i.started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
        COALESCE(to_char(i.ended_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'), 'open'),
        i.impact, COALESCE(i.resolution, 'unresolved'))
      WHEN 'change' THEN format(
        'Change %s type %s on cluster %s by %s. Window %s to %s. Statement: %s Description: %s Rollback: %s',
        e.external_key, c.change_type, e.cluster_id, c.owner,
        to_char(c.started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
        COALESCE(to_char(c.ended_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'), 'open'),
        COALESCE(c.change_sql, 'n/a'), c.description, COALESCE(c.rollback_plan, 'none'))
      WHEN 'lock' THEN format(
        'Lock snapshot %s for incident %s captured %s. Blocked pid %s waiting on %s (%s %s) behind blocking pid %s. Blocked statement: %s Blocking statement: %s',
        e.external_key, l.incident_id,
        to_char(l.captured_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
        l.blocked_pid, l.wait_event, l.lock_type, l.lock_mode, l.blocking_pid,
        l.blocked_statement, l.blocking_statement)
      WHEN 'case' THEN format(
        'Support case %s for account %s tier %s severity %s opened %s. Description: %s',
        e.external_key, s.account, s.tier, s.severity,
        to_char(s.opened_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'), s.description)
      WHEN 'runbook' THEN format(
        'Runbook %s version %s owned by %s. Applicability: %s Procedure: %s Caveats: %s',
        e.external_key, r.runbook_version, r.owner, r.applicability, r.procedure,
        COALESCE(r.caveats, 'none'))
      WHEN 'commitment' THEN format(
        'Commitment %s to account %s due %s status %s. Commitment: %s',
        e.external_key, m.account,
        to_char(m.due_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
        m.status, m.commitment)
    END AS body,
    jsonb_strip_nulls(jsonb_build_object(
      'kind',        e.kind,
      'cluster_id',  e.cluster_id,
      'incident_id', COALESCE(i.evidence_id, l.incident_id),
      'account',     COALESCE(s.account, m.account),
      'severity',    COALESCE(i.severity, s.severity),
      'environment', d.environment
    )) AS filters,
    jsonb_build_object(
      'renderer_version', 'v1',
      'source_kind',      e.kind,
      'external_key',     e.external_key
    ) AS metadata
  FROM casework.evidence_items e
  LEFT JOIN casework.incidents            i ON i.evidence_id = e.evidence_id
  LEFT JOIN casework.changes              c ON c.evidence_id = e.evidence_id
  LEFT JOIN casework.lock_evidence        l ON l.evidence_id = e.evidence_id
  LEFT JOIN casework.support_cases        s ON s.evidence_id = e.evidence_id
  LEFT JOIN casework.runbooks             r ON r.evidence_id = e.evidence_id
  LEFT JOIN casework.customer_commitments m ON m.evidence_id = e.evidence_id
  LEFT JOIN casework.database_clusters    d ON d.cluster_id  = e.cluster_id
)
SELECT
  rendered.*,
  encode(
    sha256(
      convert_to(
        concat_ws(chr(31),
          rendered.evidence_id, rendered.external_key, rendered.kind, rendered.title,
          COALESCE(rendered.body, ''), rendered.source_uri, rendered.source_revision,
          to_char(rendered.source_time AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
          rendered.acl::text, rendered.filters::text, rendered.is_deleted::text
        ), 'UTF8')
    ), 'hex') AS search_document_hash
FROM rendered;
```

### 10.2 Queueing

The typed casework transaction that changes a fact is the same transaction that
queues the research index. There is no polling of casework tables.

```sql
CREATE OR REPLACE FUNCTION casework.queue_evidence(p_evidence_id text)
RETURNS void LANGUAGE sql AS $$
  INSERT INTO retrieval.search_index_queue (evidence_id, source_revision)
  SELECT e.evidence_id, e.source_revision
  FROM casework.evidence_items e
  WHERE e.evidence_id = p_evidence_id
  ON CONFLICT (evidence_id) WHERE completed_at IS NULL
  DO UPDATE SET source_revision = EXCLUDED.source_revision,
                queued_at       = now(),
                status          = 'pending',
                error           = NULL;
$$;
```

### 10.3 Build lifecycle

Ordered, and each document is processed in **its own transaction**:

1. A typed casework transaction updates `evidence_items.source_revision`.
2. The same transaction calls `casework.queue_evidence(evidence_id)`.
3. The search index builder renders `casework.v_evidence_documents` for the queued item.
4. An unchanged deterministic version — same `(evidence_id, renderer_version,
   chunker_version, embedding_model_id, search_document_hash)` — is reused, and the build is
   recorded as `skipped_unchanged`.
5. A changed render creates new document and chunk versions in `building` state.
6. Embeddings are reused from `retrieval.embedding_cache` where
   `(embedding_model_id, chunk_hash)` already exists; only misses call Bedrock.
7. The new document is marked `ready`, `is_current` is moved to it, and the prior
   current document is set `superseded` with `superseded_at`.
8. The matching outbox row is completed.

Steps 5-8 for one document commit together. A failed build can therefore leave some
older current versions in place, but the `documents_one_current_uidx` partial unique
index makes promoting two current versions for one evidence item impossible.

### 10.4 Tombstones

An authoritative deletion sets `is_deleted` and `deleted_at`, advances
`source_revision`, and queues the item. The rebuild supersedes the current search
version and promotes no replacement. New retrieval excludes the item; historical
candidates and citations that reference the superseded version stay resolvable, so
old receipts keep validating.

### 10.5 Drift and readiness

`retrieval.v_search_index_drift` detects exactly five conditions. Any row is drift.

```sql
CREATE OR REPLACE VIEW retrieval.v_search_index_drift AS
-- 1. live evidence with no current document
SELECT e.evidence_id, 'missing_current_document'::text AS drift_reason,
       NULL::uuid AS document_version_id
FROM casework.evidence_items e
WHERE NOT e.is_deleted
  AND NOT EXISTS (SELECT 1 FROM retrieval.documents d
                  WHERE d.evidence_id = e.evidence_id AND d.is_current)
UNION ALL
-- 2. current document whose revision or search document hash no longer matches the renderer
SELECT d.evidence_id, 'stale_revision_or_hash', d.document_version_id
FROM retrieval.documents d
JOIN casework.v_evidence_documents v ON v.evidence_id = d.evidence_id
WHERE d.is_current
  AND (d.source_revision IS DISTINCT FROM v.source_revision
    OR d.search_document_hash IS DISTINCT FROM v.search_document_hash)
UNION ALL
-- 3. current document that is not ready
SELECT d.evidence_id, 'current_not_ready', d.document_version_id
FROM retrieval.documents d
WHERE d.is_current AND d.state <> 'ready'
UNION ALL
-- 4. current document for tombstoned evidence
SELECT d.evidence_id, 'current_for_deleted_evidence', d.document_version_id
FROM retrieval.documents d
JOIN casework.evidence_items e ON e.evidence_id = d.evidence_id
WHERE d.is_current AND e.is_deleted
UNION ALL
-- 5. current-document chunk with no ready embedding in the active model space
SELECT d.evidence_id, 'missing_ready_embedding', d.document_version_id
FROM retrieval.documents d
JOIN retrieval.chunks c ON c.document_version_id = d.document_version_id
WHERE d.is_current
  AND (c.state <> 'ready'
    OR c.embedding IS NULL
    OR c.embedding_model_id IS DISTINCT FROM d.embedding_model_id);

CREATE OR REPLACE FUNCTION retrieval.assert_search_index_ready()
RETURNS void LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_count  integer;
  v_reason text;
BEGIN
  SELECT count(*), COALESCE(string_agg(DISTINCT drift_reason, ', '), '')
    INTO v_count, v_reason
  FROM retrieval.v_search_index_drift;

  IF v_count > 0 THEN
    RAISE EXCEPTION 'search index not ready: % drift row(s) [%]', v_count, v_reason
      USING ERRCODE = 'data_exception';
  END IF;
END;
$$;
```

Condition 5 is also the enforcement point for the embedding-space invariant in §23:
a chunk embedded in a different model space than its document declares is drift, not
a silently degraded result.

`GET /ready`, the doctor check, the smoke check, and the integration tests all call
`retrieval.assert_search_index_ready()`. They fail closed. None of them reimplements the
check in application code.

---

## 11. Retrieval and indexes

### Index families

| Index | Use |
|---|---|
| B-tree | external IDs and selective filters |
| GIN `tsvector` | identity/title and chunk-body FTS |
| GIN `gin_trgm_ops` | identifier/title typo recovery |
| GIN JSONB | ACL metadata support |
| HNSW `vector_cosine_ops` | semantic candidate generation |

Defaults:

- HNSW `m=16`
- HNSW `ef_construction=64`
- runtime `ef_search=40`
- `hnsw.iterative_scan='strict_order'`
- trigram threshold `0.30`
- pool `24` per arm
- ANN overfetch `ceil(pool * 1.5) = 36`
- one strongest passage per evidence item
- RRF weights `text:vector:fuzzy = 2:1:1`
- RRF `k=60`

Filters and `retrieval.acl_visible()` execute inside every retrieval arm before fusion.

### 11.0 Vector type selection

The choice of vector type is a hard constraint, not a tuning option, because pgvector
caps indexable dimensions per type:

| Type | Max indexable dimensions | Storage |
|---|---:|---|
| `vector` | 2000 | `4 × dims + 8` bytes |
| `halfvec` | 4000 | `2 × dims + 8` bytes |
| `bit` | 64000 | `dims / 8 + 8` bytes |

Two consequences worth stating plainly:

- A 3072-dimension embedding **cannot be HNSW-indexed as `vector` at all**. `halfvec` is
  mandatory at that width, not an optimisation. Discovering this after building a corpus
  is expensive.
- At 1024 dimensions a `vector` chunk embedding is 4104 bytes and a `halfvec` is 2056 —
  2× smaller, and `bit` is 32× smaller. On Aurora that ratio is the lever that decides
  whether the index is RAM-resident, which §18.3 shows is worth 4–9× throughput. Vector
  type selection is a memory-residency decision disguised as a precision decision.

Hybrid Retrieval Workbench uses `vector(1024)`, which is comfortably inside the cap. The table is here so
that a participant scaling this design to a wider embedding knows where the wall is.

### 11.1 Three fusion arms, four UI columns

Fusion has **three** terms: text, vector, fuzzy. The UI shows **four** columns because
the fused result gets its own column. Exact/B-tree is not a fourth fusion term.

Exact identifier matching and GIN full-text search are two SQL sources that merge into
the single `text_position` arm before fusion:

1. Exact hits are the rows whose `external_key` equals an identifier token that
   `decompose_question` extracted. They carry `tier = 0`.
2. FTS hits are the `tsvector` matches. They carry `tier = 1`.
3. The union is deduplicated by `evidence_id`, keeping the lowest tier — so an item
   that matched both is kept as an exact hit.
4. Positions are then assigned `1..n` over the deduplicated list ordered by
   `(tier, raw_score DESC, evidence_id)`. Every exact hit therefore ranks ahead of
   every FTS-only hit.

This is what makes "`CHG-1000` is lexical rank 1 for the exact query" deterministic
rather than a property of `ts_rank` weighting.

### 11.2 Deduplication and position assignment

`DISTINCT ON (evidence_id)` keeps one strongest passage per evidence item.

**Positions are assigned after deduplication**, over the deduplicated per-arm list, so
each arm's positions are dense `1..n` with no gaps. An arm never reports position 7 for
its third distinct evidence item. This ordering is load-bearing: RRF consumes positions,
and gapped positions would silently change every fused score.

### 11.3 ANN runtime is transaction-local

HNSW runtime settings and the trigram threshold are set with `SET LOCAL` semantics
inside the same transaction as the query, through one function:

```sql
CREATE OR REPLACE FUNCTION retrieval.configure_ann_runtime(
  p_ef_search           integer DEFAULT 40,
  p_iterative_scan      text    DEFAULT 'strict_order',
  p_max_scan_tuples     integer DEFAULT 20000,
  p_scan_mem_multiplier numeric DEFAULT 2,
  p_trgm_threshold      real    DEFAULT 0.30
) RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  -- third argument true => is_local => reverted at COMMIT or ROLLBACK
  PERFORM set_config('hnsw.ef_search',              p_ef_search::text,           true);
  PERFORM set_config('hnsw.iterative_scan',         p_iterative_scan,            true);
  PERFORM set_config('hnsw.max_scan_tuples',        p_max_scan_tuples::text,     true);
  PERFORM set_config('hnsw.scan_mem_multiplier',    p_scan_mem_multiplier::text, true);
  PERFORM set_config('pg_trgm.similarity_threshold', p_trgm_threshold::text,     true);
END;
$$;
```

Every retrieval request runs `BEGIN; SELECT retrieval.configure_ann_runtime(...); <arms>; COMMIT;`.

Rationale, and it is not stylistic: the API runs a connection pool. A session-level
`SET hnsw.ef_search` would outlive the request and leak onto whichever request borrows
that connection next, so two identical queries would return different candidate sets
depending on pool scheduling. That breaks replay, breaks the candidate receipt, and
breaks transport parity. Transaction-local is the only setting that keeps a run
reproducible.

`hnsw.max_scan_tuples` (default `20000`) and `hnsw.scan_mem_multiplier` (default `1`,
raised to `2` here) bound how far an iterative scan will go before giving up. They are
the knobs that decide whether a highly selective ACL or time filter still returns a
full pool, and they are what release gate 5 measures at release scale.

**Version trap, verified on a live cluster.** On pgvector earlier than 0.8.0 these three
settings do not exist, and PostgreSQL does not raise. It emits
`WARNING: invalid configuration parameter name "hnsw.iterative_scan", removing it` and
continues. `configure_ann_runtime` returns success, the filtered-HNSW behaviour silently
reverts to plain post-filtering, and recall quietly drops. The pgvector version check is
therefore a hard release gate (§27 gate 2), not something a smoke test will catch.
Codex must also assert the effective setting after configuring:

```sql
SELECT current_setting('hnsw.iterative_scan', true) IS NOT DISTINCT FROM 'strict_order';
```

### 11.4 Why `strict_order`, not `relaxed_order`

`relaxed_order` is faster but pgvector documents that it may return results **slightly
out of distance order**. Hybrid Retrieval Workbench persists `vector_position` into the candidate receipt,
replays runs from it, and compares it byte-for-byte across three transports. An
ordering that is allowed to vary cannot support any of that.

`strict_order` is therefore the default. `relaxed_order` remains selectable through the
`iterative_scan` control for the latency-versus-recall demonstration, but a run
recorded under `relaxed_order` is explicitly labelled as non-reproducible in the receipt
and is never used as a parity fixture.

### 11.4a Scan-level filtering, and why the columns are denormalized

`hnsw.iterative_scan` recovers rows when the index returns candidates that a **filter on
the same scan** then rejects. It cannot help when the filter sits above a join.

The naive schema puts the HNSW index on `retrieval.chunks` and every selective
predicate — ACL, cluster, incident, kind, time — on `retrieval.documents`. The plan is
then an index scan on `chunks` feeding a join, with the selective work happening one
node up. pgvector has no visibility into that node, so iterative scan cannot know it
needs to go back for more, and "filtered HNSW" degrades to fetch-then-discard.

The fix is the denormalized columns in §9.3: `kind`, `source_time`, `acl_visibility`,
`acl_principals`, and the five `f_*` filter scalars are copied onto `chunks` at
search index time. A document version is immutable, so the copy cannot drift within a
version, and a rebuild produces a new version rather than mutating the old one.

Consequences, all of which are the point:

- the vector arm touches exactly one relation and never joins `documents`;
- every selective predicate is a Filter on the index scan node, which is what
  `iterative_scan` is specified to handle;
- the partial HNSW index predicate (`is_current AND state = 'ready'`) is genuinely
  index-resident rather than decorative;
- the §13.6 escalation becomes measurable, because widening `ef_search` now changes
  what the scan returns instead of changing how much the join throws away.

The shape to verify in Plan X-Ray, and the acceptance test for this section — the
selective predicates must appear as `Filter` **on the index scan node itself**, with no
join above it:

```text
Limit
  ->  Index Scan using chunks_embedding_hnsw_idx on chunks c
        Order By: (embedding <=> $1::vector)
        Filter: ((acl_visibility = ANY ('{workshop}'::text[]))
             AND (f_cluster_id = 'checkout-prod-01'::text)
             AND ((acl_principals = '{}'::text[]) OR (acl_principals && '{}'::text[])))
```

If the plan shows a `Nested Loop` or `Hash Join` above the index scan with the filters on
the upper node, the denormalization has not been applied and `iterative_scan` is inert.

Do not describe this workshop's HNSW retrieval as "filtered" without the denormalized
columns in place. With them the claim is true; without them it is marketing.

### 11.5 Trigram retrieval: indexable form and probe rule

Two rules, both required.

**Use the indexable operator.** Filter with `%`, which is driven by the transaction-local
`pg_trgm.similarity_threshold` and can use the `gin_trgm_ops` index. Report
`similarity()` only in the `SELECT` list, as a diagnostic.

```sql
WHERE d.external_key % :probe OR d.title % :probe          -- indexable
SELECT GREATEST(similarity(d.external_key, :probe),
                similarity(d.title, :probe)) AS fuzzy_score  -- diagnostic only
```

`WHERE similarity(d.external_key, :probe) > 0.30` is **wrong**. It cannot use the GIN
index, degrades to a sequential scan over the corpus, and turns the Module 1 "indexed
trigram" teaching point into a false claim in the captured plan.

**Probe only unresolved identifier tokens.** The fuzzy arm does not receive the natural
language query. `decompose_question` extracts identifier-shaped tokens with
`[A-Z]{2,6}-[0-9]{3,6}`, and the fuzzy arm probes only those tokens that produced **no
exact B-tree hit**. A token that resolves exactly is never fuzzed.

- The probe set is normally empty, and an empty fuzzy arm is a legitimate result that
  contributes zero to fusion. It is not an error state.
- Trigram similarity is never computed against the full question string. For the fuzzy
  preset, `similarity('Did CGH-1000 cause INC-2000?', 'CHG-1000') = 0.25`, which is
  below the `0.30` threshold — passing the sentence would return nothing at all.
- `INC-2000` in that same query resolves exactly, so it is excluded from the probe set
  and cannot pollute the fuzzy arm.

**Typo fixture.** The controlled mutation is `CGH-1000` — a letter transposition of
`CHG-1000`. At threshold `0.30` against the canonical thread plus the deterministic
background corpus it returns exactly one row:

| Candidate | `similarity('CGH-1000', ...)` | Returned at 0.30 |
|---|---:|---|
| `CHG-1000` | 0.5000 | yes |
| `CHG-1100` | 0.2857 | no |
| `CHG-1002` | 0.2857 | no |
| `CHG-1001` | 0.2857 | no |

The earlier `CHG-0100` digit transposition is **not usable** and must not be
reintroduced: it ties at 0.5000 with background identifier `CHG-1100` and returns six
rows, so "the typo resolves to `CHG-1000`" would depend on tie-break order.

### 11.6 Canonical arm SQL

Executed inside the configured transaction. `:principal`, `:filters`, `:id_tokens`, and
`:unresolved_id_tokens` come from `decompose_question`; `:query_embedding` is a
`vector(1024)` produced in the same model space as the stored chunks (§23).

The ACL and filter predicates are written inline, against indexable scalar columns, in
every arm. They are shown in full once here; `<<visible_doc>>` and `<<visible_chunk>>`
below stand for the identical predicate blocks.

```text
<<visible_doc>> =
      d.acl_visibility = ANY (:principal_scopes)
  AND (d.acl_principals = '{}'::text[] OR d.acl_principals && :principal_principals)
  AND (cardinality(:kinds) = 0 OR d.kind = ANY (:kinds))
  AND (:cluster_id  IS NULL OR d.f_cluster_id  = :cluster_id)
  AND (:incident_id IS NULL OR d.f_incident_id = :incident_id)
  AND (:account     IS NULL OR d.f_account     = :account)
  AND (:severity    IS NULL OR d.f_severity    = :severity)
  AND (:environment IS NULL OR d.f_environment = :environment)
  AND (:start_time  IS NULL OR d.source_time  >= :start_time)
  AND (:end_time    IS NULL OR d.source_time  <= :end_time)

<<visible_chunk>> = the same block with c. in place of d.
```

```sql
-- arm 1a: exact identifier hits (B-tree on external_key)
WITH exact_hits AS (
  SELECT d.evidence_id, c.chunk_version_id, 0::real AS raw_score, 0 AS tier
  FROM retrieval.documents d
  JOIN retrieval.chunks c
    ON c.document_version_id = d.document_version_id AND c.is_current
  WHERE d.is_current AND d.state = 'ready'
    AND d.external_key = ANY (:id_tokens)
    AND <<visible_doc>>
),
exact_identifier_arm AS (
  SELECT
    evidence_id,
    chunk_version_id,
    row_number() OVER (
      ORDER BY evidence_id
    ) AS exact_identifier_position
  FROM exact_hits
),
-- arm 1b: full-text hits (GIN tsvector, identity weighted above body)
fts_hits AS (
  SELECT d.evidence_id, c.chunk_version_id,
         (ts_rank(d.identity_tsv, q.tsq) * 2.0 + ts_rank(c.body_tsv, q.tsq))::real AS raw_score,
         1 AS tier
  FROM retrieval.documents d
  JOIN retrieval.chunks c
    ON c.document_version_id = d.document_version_id AND c.is_current
  CROSS JOIN LATERAL (SELECT websearch_to_tsquery('english', :query) AS tsq) q
  WHERE d.is_current AND d.state = 'ready'
    AND (d.identity_tsv @@ q.tsq OR c.body_tsv @@ q.tsq)
    AND <<visible_doc>>
),
-- text arm: exact prepended ahead of FTS, deduplicated, positions 1..n
text_arm AS (
  SELECT evidence_id, chunk_version_id, raw_score,
         row_number() OVER (ORDER BY tier, raw_score DESC, evidence_id) AS text_position
  FROM (
    SELECT DISTINCT ON (evidence_id) evidence_id, chunk_version_id, raw_score, tier
    FROM (SELECT * FROM exact_hits UNION ALL SELECT * FROM fts_hits) u
    ORDER BY evidence_id, tier, raw_score DESC, chunk_version_id
  ) dedup
  ORDER BY text_position
  LIMIT :pool
),
-- arm 2: ANN candidates. Single relation, no join: every predicate is a Filter on
-- the HNSW index scan node, which is what iterative_scan can act on (§11.4a).
-- Ordered index scan first, dedup second. Overfetch = ceil(pool * 1.5).
vector_candidates AS (
  SELECT c.evidence_id, c.chunk_version_id,
         (c.embedding <=> :query_embedding)::real AS vector_distance
  FROM retrieval.chunks c
  WHERE c.is_current AND c.state = 'ready'
    AND <<visible_chunk>>
  ORDER BY c.embedding <=> :query_embedding
  LIMIT :ann_limit
),
vector_arm AS (
  SELECT evidence_id, chunk_version_id, vector_distance,
         row_number() OVER (ORDER BY vector_distance, evidence_id) AS vector_position
  FROM (
    SELECT DISTINCT ON (evidence_id) evidence_id, chunk_version_id, vector_distance
    FROM vector_candidates
    ORDER BY evidence_id, vector_distance
  ) dedup
  ORDER BY vector_position
  LIMIT :pool
),
-- arm 3: trigram over unresolved identifier tokens only. Empty probe set => empty arm.
fuzzy_arm AS (
  SELECT evidence_id, chunk_version_id, fuzzy_score,
         row_number() OVER (ORDER BY fuzzy_score DESC, evidence_id) AS fuzzy_position
  FROM (
    SELECT DISTINCT ON (d.evidence_id)
           d.evidence_id,
           (SELECT c.chunk_version_id FROM retrieval.chunks c
             WHERE c.document_version_id = d.document_version_id AND c.is_current
             ORDER BY c.chunk_ordinal LIMIT 1) AS chunk_version_id,
           GREATEST(similarity(d.external_key, probe.tok),
                    similarity(d.title,        probe.tok))::real AS fuzzy_score
    FROM retrieval.documents d
    CROSS JOIN LATERAL unnest(:unresolved_id_tokens::text[]) AS probe(tok)
    WHERE d.is_current AND d.state = 'ready'
      AND (d.external_key % probe.tok OR d.title % probe.tok)
      AND <<visible_doc>>
    ORDER BY d.evidence_id,
             GREATEST(similarity(d.external_key, probe.tok),
                      similarity(d.title,        probe.tok)) DESC
  ) dedup
  ORDER BY fuzzy_position
  LIMIT :pool
)
-- fusion follows in §12
```

`:ann_limit` must satisfy `ef_search >= ann_limit`. With `pool = 24` the overfetch is
`36` and the default `ef_search = 40` satisfies it. Raising `pool` without raising
`ef_search` silently degrades recall, so the service computes and validates this
relationship rather than trusting the request.

### 11.7 Filter and ACL helpers

Both run inside every arm, before fusion — never as a post-filter over fused results,
which would leak restricted evidence into ranking positions and distort every score.

```sql
CREATE OR REPLACE FUNCTION retrieval.acl_visible(p_acl jsonb, p_principal jsonb)
RETURNS boolean LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT
    (p_acl ->> 'visibility') IN (
      SELECT jsonb_array_elements_text(COALESCE(p_principal -> 'scopes', '[]'::jsonb)))
    AND (
      jsonb_array_length(COALESCE(p_acl -> 'principals', '[]'::jsonb)) = 0
      OR EXISTS (
        SELECT 1
        FROM jsonb_array_elements_text(COALESCE(p_acl -> 'principals', '[]'::jsonb)) AS required(p)
        WHERE required.p IN (
          SELECT jsonb_array_elements_text(COALESCE(p_principal -> 'principals', '[]'::jsonb)))
      )
    );
$$;

```

There is no `filters_match(jsonb, ...)` function. Filtering happens through the inline
scalar predicates in §11.6, because a function call over jsonb is opaque to the planner:
it cannot use an index and, worse, it cannot be pushed into the HNSW scan node where
`iterative_scan` needs it (§11.4a). The `filters` jsonb column survives on
`retrieval.documents` for the receipt and the UI, and is never a query predicate.

`retrieval.acl_visible(jsonb, jsonb)` is retained as the **single semantic definition**
of visibility. It is used by traversal (§13.2), where the row set is small and already
constrained, and by tests. The arms use the inline two-column form because it is
indexable. These two must agree, and a unit test asserts it across the full corpus and
both principals:

```sql
SELECT count(*) FROM retrieval.documents d
WHERE retrieval.acl_visible(d.acl, :principal)
   <> (d.acl_visibility = ANY (:principal_scopes)
       AND (d.acl_principals = '{}'::text[] OR d.acl_principals && :principal_principals));
-- must be 0
```

The ACL document shape is fixed:

```json
{"visibility": "workshop", "principals": []}                 // default evidence
{"visibility": "workshop", "principals": ["support-lead"]}   // CASE-4001
```

```json
{"scopes": ["workshop"], "principals": []}                   // default principal
{"scopes": ["workshop"], "principals": ["support-lead"]}     // support lead
```

Visible iff `acl.visibility` is in `principal.scopes` **and** `acl.principals` is either
empty or intersects `principal.principals`. Under the default principal this makes
`CASE-4001` absent, not redacted.

Exactly one canonical signature exists for each search and helper function. Overloads
are forbidden: a second signature is how two subtly different ranking paths get shipped
by accident.

---

## 12. Weighted reciprocal rank fusion

### General form

The weights and `k` are request parameters, not constants. They bind from the
`SearchControls` fields `text_weight`, `vector_weight`, `fuzzy_weight`, and `rrf_k`.

```text
RRF(d) =
    text_weight   / (rrf_k + exact_identifier_position(d))
  + text_weight   / (rrf_k + text_position(d))
  + vector_weight / (rrf_k + vector_position(d))
  + fuzzy_weight  / (rrf_k + fuzzy_position(d))
```

The exact-identifier term is present only for boundary-matched identifiers and
shares `text_weight`.

### Default instantiation

`text:vector:fuzzy = 2:1:1`, `rrf_k = 60`:

```text
RRF(d) =
    2.0 / (60 + exact_identifier_position(d))
  + 2.0 / (60 + text_position(d))
  + 1.0 / (60 + vector_position(d))
  + 1.0 / (60 + fuzzy_position(d))
```

### Canonical fusion SQL

Continues the CTE chain from §11.6.

```sql
, fused AS (
  SELECT
    evidence_id,
    COALESCE(t.chunk_version_id, v.chunk_version_id, f.chunk_version_id) AS chunk_version_id,
    e.exact_identifier_position,
    t.text_position, v.vector_position, f.fuzzy_position,
    t.raw_score AS text_score, v.vector_distance, f.fuzzy_score,
      COALESCE(:text_weight   / (:rrf_k + e.exact_identifier_position), 0)
    + COALESCE(:text_weight   / (:rrf_k + t.text_position),   0)
    + COALESCE(:vector_weight / (:rrf_k + v.vector_position), 0)
    + COALESCE(:fuzzy_weight  / (:rrf_k + f.fuzzy_position),  0) AS rrf_score
  FROM exact_identifier_arm e
  FULL JOIN text_arm t USING (evidence_id)
  FULL JOIN vector_arm v USING (evidence_id)
  FULL JOIN fuzzy_arm  f USING (evidence_id)
)
SELECT
  evidence_id, chunk_version_id,
  exact_identifier_position, text_position, vector_position, fuzzy_position,
  text_score, vector_distance, fuzzy_score, rrf_score,
  row_number() OVER (ORDER BY rrf_score DESC, evidence_id) AS fused_rank
FROM fused
ORDER BY fused_rank
LIMIT :pool;
```

### Numeric typing — this is a correctness requirement, not a style preference

`:text_weight`, `:vector_weight`, and `:fuzzy_weight` **must** bind as `numeric` or
`double precision`. They must never bind as `integer`.

In PostgreSQL, `integer / integer` is integer division. If the weights bind as integers,
`2 / (60 + 1)` evaluates to `0`, every fused score becomes `0`, `fused_rank` degenerates
to the tie-break column, and the failure is silent — the query succeeds and returns
plausible-looking rows in the wrong order. Bind `2.0`, not `2`. Codex must assert this
in a unit test that pins `RRF(text_position = 1, vector_position = 1) = 3.0/61`.

### Rules

- absent arm contributes zero, via `COALESCE(..., 0)` on a `NULL` position;
- ranks fuse; raw values never do;
- raw `ts_rank`, vector distance, and trigram similarity remain diagnostics;
- Aurora RRF and model rerank score remain separate;
- no score is shown as a probability;
- optional rerank may reorder the pool but cannot overwrite original positions or RRF;
- `fused_rank` is dense `1..candidate_count` over the persisted candidates.

### Naive score summation — the comparison baseline

Module 2 contrasts RRF against naive score summation. That baseline is defined here so
the comparison is reproducible rather than illustrative.

For each arm, min-max normalize the arm's raw values across the candidate pool, then
take the same weighted sum:

```text
norm_text(d)   = (text_score(d)      - min_text)   / (max_text   - min_text)
norm_vector(d) = (max_distance       - distance(d)) / (max_distance - min_distance)
norm_fuzzy(d)  = (fuzzy_score(d)     - min_fuzzy)  / (max_fuzzy  - min_fuzzy)

naive(d) = 2.0 * norm_text(d) + 1.0 * norm_vector(d) + 1.0 * norm_fuzzy(d)
```

Vector is inverted because cosine distance is better when smaller. An arm with a single
candidate, or a zero-width range, normalizes to `1.0`. An absent arm contributes zero,
as in RRF.

The teaching point is the failure mode: `ts_rank` values in this corpus span roughly
two orders of magnitude while cosine distances cluster in a narrow band. After
normalization the text arm's spread dominates, so the intended `2:1:1` weighting —
nominally a 50/25/25 split of influence — collapses to an effective split of roughly
93/7 between text and everything else. The weights say one thing and the arithmetic
does another. RRF avoids this because rank positions are bounded and comparable across
arms by construction, which is the entire reason ranks fuse and raw values do not.

The UI presents both orderings side by side. It does not present the naive ordering as
broken; it presents it as an ordering whose effective weights cannot be read off its
stated weights.

---

## 13. Agent pipeline

### The loop

The agent is a bounded loop over subquestions, not a fixed five-step script. The
control flow is:

```text
decompose_question
  -> N subquestions, each with required_kinds

for each subquestion:
    search_evidence                        (attempt 1)
    proof.evaluate_subquestion_coverage    (deterministic SQL, §9.4a)
    if not covered and budget remains:
        escalate: restate controls/filters, record the change
        search_evidence                    (attempt 2)
        re-evaluate coverage
    record covered | still_uncovered | budget_exhausted

follow_evidence_links      (over the union of covering evidence)
compare_sources
-> service binds citations, validates them, persists the receipt
```

Two things make this a loop rather than a storyboard: the number of `search_evidence`
calls is a function of the data, not of the script, and the branch condition is a SQL
predicate the participant can run themselves.

### Which tools the agent actually selects

| Tool | Role |
|---|---|
| `decompose_question` | agent step — produces the subquestions and their `required_kinds` |
| `search_evidence` | agent step — called once per subquestion, twice on escalation |
| `follow_evidence_links` | agent step — expands the covering evidence set |
| `compare_sources` | agent step — produces the verdicts |
| `explain_ranking` | **not an agent step.** Human diagnostic surface |
| `synthesize_cited_answer` | **not an agent step.** Server-side citation binding and receipt persistence |
| `answer_with_citations` | orchestration entry point that runs the loop |

`explain_ranking` is deliberately outside the loop. An agent has no action it can take
on "`CHG-1000` was `text_position` 2" — there is no decision that fact changes. It exists
because the *workbench* calls it when a participant expands a candidate row, and
scripting an agent to call a debugger it cannot act on is how a storyboard gets mistaken
for a policy.

`synthesize_cited_answer` is likewise not something an agent selects. It is the
server-side step that binds claims to exact chunk versions, runs
`proof.validate_answer_citations`, and persists the receipt. It is exposed as a tool
because the tool contract must be portable across transports, not because a planner
would choose it.

### Inspectable outputs

| Tool | Required output |
|---|---|
| `decompose_question` | IDs, cluster, time window, evidence kinds, subquestions, planned modes |
| `search_evidence` | run ID, controls, candidate count, arm diagnostics, candidates |
| `follow_evidence_links` | paths, depth, edge origin, confidence, ACL decision |
| `compare_sources` | confirmed/ruled-out/affected/unaffected verdicts and revisions |
| `explain_ranking` | positions, raw diagnostics, RRF contribution, rerank delta |
| `synthesize_cited_answer` | cited answer, claims, citations, synthesis mode |
| `answer_with_citations` | plan, candidates, graph, answer, citations, receipt references |

> Contract status. `contracts/openapi/verity-tools.openapi.yaml` has been widened to
> carry plan, candidates, graph, receipt references, traversal paths, verdict revisions,
> and `Citation.claim`. The remaining gap is the agent-loop surface introduced here:
> `agent_run_id`, per-subquestion coverage, escalation records, budget spend, and the
> `no_evidence` synthesis mode are not yet in the schema. This table is the requirement;
> the OpenAPI must catch up, because Gateway derives its MCP tool schema from that file.
> Codex must not narrow the tool outputs to fit the current OpenAPI. Adding these as
> optional properties is additive and keeps `contract_version` at 1.0.0; making them
> required is a version bump.

### 13.1 Decomposition

The planner is deterministic. It extracts identifier tokens with `[A-Z]{2,6}-[0-9]{3,6}`,
plus a database cluster identifier when present, and emits inspectable filters and steps
rather than an opaque plan.

It classifies every extracted token into exactly one of two sets, and both travel with
the retrieval request:

- `id_tokens` — tokens that match an `external_key` exactly. These drive the exact/B-tree
  half of the text arm.
- `unresolved_id_tokens` — tokens that match nothing exactly. These, and only these, are
  the trigram probe set (§11.5).

Extracting `INC-2000` and `CGH-1000` from the fuzzy preset therefore yields
`id_tokens = {INC-2000}` and `unresolved_id_tokens = {CGH-1000}`.

It also emits subquestions, and each subquestion carries the evidence kinds that must
appear for it to count as answered. `required_kinds` is what makes coverage checkable;
a subquestion without it is a comment.

For the canonical question:

| ID | Subquestion | `required_kinds` |
|---|---|---|
| `SQ-1` | why did checkout writes hang while reads continued | `{incident, lock}` |
| `SQ-2` | did `CHG-1000` or `CHG-1001` cause the incident | `{change}` |
| `SQ-3` | which customer impact is visible to this principal | `{case}` |
| `SQ-4` | what evidence rules out the alternative change | `{change, lock}` |
| `SQ-5` | what was the safe recovery and the preventive follow-up | `{runbook}` |

Subquestions are persisted to `proof.agent_subquestions` before the first retrieval, so
a run that fails partway still shows what it intended to answer.

### 13.2 Relationship traversal

`retrieval.traverse_evidence` walks canonical and inferred edges, applies ACL checks to
the seeds **and to both endpoints of every hop**, records path provenance, and limits
depth. FK-derived edges carry confidence `1`; inferred edges keep their method and
confidence and never become FK facts.

```sql
CREATE OR REPLACE FUNCTION retrieval.traverse_evidence(
  p_seed_ids         text[],
  p_principal        jsonb,
  p_max_depth        integer DEFAULT 2,
  p_include_inferred boolean DEFAULT true
) RETURNS TABLE (
  depth        integer,
  source_id    text,
  target_id    text,
  relationship text,
  origin       text,
  confidence   numeric,
  method       text,
  path         text[]
) LANGUAGE sql STABLE PARALLEL SAFE AS $$
  WITH RECURSIVE visible AS (
    SELECT e.evidence_id
    FROM casework.evidence_items e
    WHERE NOT e.is_deleted
      AND retrieval.acl_visible(e.acl, p_principal)
  ),
  walk AS (
    SELECT 0 AS depth, NULL::text AS source_id, v.evidence_id AS target_id,
           'seed'::text AS relationship, 'canonical'::text AS origin,
           1.0::numeric AS confidence, NULL::text AS method,
           ARRAY[v.evidence_id] AS provenance
    FROM visible v
    WHERE v.evidence_id = ANY (p_seed_ids)
    UNION ALL
    SELECT w.depth + 1, ee.source_id, ee.target_id, ee.relationship,
           ee.origin, ee.confidence, ee.method, w.provenance || ee.target_id
    FROM walk w
    JOIN retrieval.evidence_edges ee ON ee.source_id = w.target_id
    JOIN visible vs ON vs.evidence_id = ee.source_id
    JOIN visible vt ON vt.evidence_id = ee.target_id
    WHERE w.depth < p_max_depth
      AND (p_include_inferred OR ee.origin = 'canonical')
  ) CYCLE target_id SET is_cycle USING cycle_path
  SELECT depth, source_id, target_id, relationship, origin, confidence, method,
         provenance AS path
  FROM walk
  WHERE depth > 0 AND NOT is_cycle;
$$;
```

Cycle detection uses the native `CYCLE` clause (PostgreSQL 14+), not a hand-rolled
`NOT target_id = ANY(path)` guard. The engine stops recursing and marks the row, which
is both correct and readable; the manual idiom predates the feature and silently does
the wrong thing when the cycle column is not the only join key.

`provenance` is a separate accumulator and is returned as `path`. It is the display and
metrics artifact — the ordered chain of evidence the UI renders — and is deliberately
not the same thing as `cycle_path`, which exists only to terminate the recursion.

An ACL-invisible node is not a pruned branch that gets reported as pruned — it is
absent, exactly as in retrieval.

### 13.3 Source comparison

The compare stage loads source revisions, times, filters, and explicit edges for the
selected evidence. Each relevant edge is attached to synthesis evidence with relation,
direction, counterpart key, canonical-or-inferred origin, confidence, and rationale
when available. Comparison is an input to the answer, not a decorative stage.

### 13.4 Cited synthesis

The model receives at most **eight** numbered evidence blocks. Each block carries source
metadata, relationship context from §13.3, title, and exact evidence text. The system
prompt requires a citation for every factual sentence and forbids presenting retrieval
scores as probabilities.

If model synthesis is unavailable — throttled, disabled, or offline mode — a
deterministic extractive fallback runs. It is not best-effort prose; it is a fixed
selection algorithm, and it is what makes "five citations validate" reproducible across
runs and transports:

1. prefer the named incident and the named change;
2. select diverse evidence — one incident, one change, one lock snapshot, one affected
   case, one runbook;
3. exclude ruled-out changes and explicitly unaffected cases unless the question names
   them;
4. include the visible account and the safe-fix guidance;
5. persist and validate citations exactly as model synthesis does.

Against the canonical scenario, steps 1-4 select `INC-2000`, `CHG-1000`, `LOCK-3000`,
`CASE-4000`, `RB-5000` — the five citations the fixtures assert. `CHG-1001` is excluded
by step 3 as ruled out, `CASE-4002` by step 3 as explicitly unaffected, `CASE-4001` by
ACL before it ever reaches synthesis.

The fallback remains evidence-backed. It is not a substitute for final model-quality
validation, and the answer records `synthesis_mode = 'extractive'` so the receipt never
implies a model wrote it.

### 13.5 Citation integrity

```sql
CREATE OR REPLACE FUNCTION proof.validate_answer_citations(p_agent_run_id text)
RETURNS TABLE (citation_number integer, failure text)
LANGUAGE sql STABLE AS $$
  SELECT t.citation_number, t.failure
  FROM (
    SELECT ac.citation_number,
           CASE
             WHEN d.document_version_id IS NULL THEN 'document_version_not_found'
             WHEN c.chunk_version_id    IS NULL THEN 'chunk_version_not_found'
             WHEN c.document_version_id IS DISTINCT FROM ac.document_version_id
                                              THEN 'chunk_not_in_document'
             WHEN d.source_uri      IS DISTINCT FROM ac.source_uri      THEN 'source_uri_mismatch'
             WHEN d.source_revision IS DISTINCT FROM ac.source_revision THEN 'source_revision_mismatch'
             WHEN position(ac.quote IN c.chunk_text) = 0 THEN 'quote_not_found_in_chunk'
           END AS failure
    FROM proof.agent_answers aa
    JOIN proof.answer_citations ac ON ac.answer_id = aa.answer_id
    LEFT JOIN retrieval.documents d ON d.document_version_id = ac.document_version_id
    LEFT JOIN retrieval.chunks    c ON c.chunk_version_id    = ac.chunk_version_id
    WHERE aa.agent_run_id = p_agent_run_id
  ) t
  WHERE t.failure IS NOT NULL;
$$;
```

Zero rows means every citation validated. The function proves **attribution integrity**:
the evidence, document, and chunk versions resolve; URI and revision match that exact
document version; the quote occurs verbatim in that exact chunk. It does not establish
that a source statement or model claim is universally true, and no UI copy may imply
that it does.

### 13.6 The one bounded escalation

Budget: `max_tool_calls = 12`, `max_escalations = 2`. Both are columns on
`proof.agent_runs`, both are enforced by a CHECK constraint, and both are reported.

On `missing_required_kind`, the agent re-queries that subquestion **once** with a stated
change, persisted to `proof.agent_escalations.changed` as a before/after pair:

| Control | Before | After | Why |
|---|---|---|---|
| `ef_search` | 40 | 200 | widen the ANN search frontier |
| `candidate_pool` | 24 | 48 | more room after `DISTINCT ON` dedup |
| `filters.cluster_id` | `checkout-prod-01` | **dropped** | the interesting one |

Dropping `cluster_id` is the part worth the lab minute. `RB-5000` is a runbook, and a
runbook is not scoped to a cluster — its `f_cluster_id` is `NULL`. The predicate
`(:cluster_id IS NULL OR c.f_cluster_id = :cluster_id)` is therefore false for it, so
the metadata filter that made `SQ-1` through `SQ-4` precise is exactly what starved
`SQ-5`. Raising `ef_search` alone does not fix it and the participant can watch that
fail first: no amount of ANN widening recovers a row the WHERE clause excluded.

The lesson is the one worth teaching about filtered retrieval — a filter that is correct
for the entity you are searching *from* can be wrong for the entity you are searching
*for*, and the only way to see it is a coverage check that names the missing kind.

`budget_exhausted` is a real terminal outcome. When escalations run out with a
subquestion still uncovered, the agent run ends `partial` or `budget_exhausted`, the
answer is synthesized from what was covered, and the uncovered subquestion is reported
in the response and rendered in the UI. It is never swallowed, and a partial answer is
never presented as complete.

Because `required_kinds` for `SQ-5` is `{runbook}` and the corpus contains exactly one
approved runbook, this escalation is deterministic: it fires on every run of the
canonical question, and it fires for a mechanical reason a participant can verify with
one `SELECT`.

### 13.7 Failure and empty-result contracts

Two cases that must not be left to whatever the implementation happens to do.

**Citation validation fails.** `proof.validate_answer_citations` returning rows is a
hard stop, never a warning.

1. The answer is not committed as valid. `validation_status` stays `pending`.
2. Exactly one repair attempt: the offending citations and the claims they supported are
   dropped, and synthesis re-runs over the remaining evidence blocks with the offending
   chunk versions excluded.
3. If the repaired answer validates, `validation_status = 'repaired'` and the receipt
   records which citations were dropped and why.
4. If it still fails, the run ends `failed`, `validation_status = 'failed'`, and
   `POST /v1/agent/answer` returns **422** with the `{citation_number, failure}` rows in
   the body. No answer text is returned.

An answer with an unvalidated citation is never returned under any status code. The
repair attempt is bounded at one for the same reason the escalation is bounded at two.

**Every arm is empty.** `candidate_count = 0` is a legitimate result, not an error.

- Fusion over zero rows produces zero rows. `fused_rank` is simply not assigned; the
  `run_stages` row still records the arm timings, and the receipt shows three empty arms.
- The retrieval run persists with `status = 'succeeded'` and `candidate_count = 0`.
  A query that correctly finds nothing is a successful query.
- Synthesis is **not called**. There are no evidence blocks, so there is no model call,
  no token spend, and no opportunity to answer from parametric memory.
- The answer row is written with `synthesis_mode = 'no_evidence'`, zero citations,
  `validation_status = 'valid'` (vacuously — there is nothing to validate), and a fixed
  answer string that states no evidence matched and names the filters that were applied.
- The extractive fallback's five selection rules select nothing and that is the correct
  output. They are not relaxed to find something.
- The agent run ends `no_evidence`. `POST /v1/agent/answer` returns **200**, because the
  system worked; the corpus simply did not contain an answer under those filters.

The distinction the UI must preserve: `no_evidence` means the filters excluded
everything, `failed` means the system could not stand behind what it produced. They look
different and they are different.

---

## 14. Three participant modules

### Module 1 — Retrieve the evidence

**Target:** 12–14 minutes.

Participants:

1. inspect canonical evidence and filters;
2. complete or inspect the FTS arm;
3. run the exact preset;
4. run the semantic symptom preset with filtered HNSW;
5. run `CGH-1000` and recover `CHG-1000` with `pg_trgm`;
6. observe default-principal ACL behavior;
7. compare independent arm positions.

Required UI:

- exact/FTS column;
- semantic column;
- fuzzy column;
- fused preview;
- query presets;
- principal;
- rerank off by default;
- per-row receipt expansion.

Completion proof:

- `CHG-1000` lexical rank 1 for exact query;
- semantic query finds `INC-2000` and `LOCK-3000`;
- `CGH-1000` resolves to `CHG-1000` as the single trigram hit;
- `CASE-4001` is absent for `workshop`.

### Module 2 — Fuse, traverse, and prove

**Target:** 18–20 minutes.

Participants:

1. implement/inspect weighted RRF;
2. compare RRF with naive score summation;
3. optionally enable rerank and preserve Aurora diagnostics;
4. run typed relationship traversal;
5. confirm `CHG-1000` and rule out `CHG-1001`;
6. identify visible and unaffected cases;
7. run the agent loop and watch `SQ-5` fail its coverage check;
8. read the escalation receipt: confirm that raising `ef_search` alone does not recover
   `RB-5000`, and that dropping the `cluster_id` filter does;
9. produce the cited answer and replay `ARUN-8000` without model calls;
10. inspect Plan X-Ray with Aurora buffer counters, then open the Database Insights
    plan and lock-tree handoff.

Required UI:

- RRF controls and formula;
- candidate table;
- subquestion coverage strip: per subquestion, `required_kinds`, covered/missing, attempts;
- escalation card: reason, before/after controls and filters, outcome;
- cited answer;
- deterministic plan;
- evidence graph;
- plan type label: `estimated` or `actual`, read from `aurora_stat_plans.plan_type`;
- Aurora buffer counters per plan node when present;
- Database Insights actions;
- proof receipt;
- compact evaluation.

Completion proof:

- five exact citations validate;
- run replays without new model calls;
- `CASE-4000` visible and affected;
- `CASE-4002` visible and unaffected;
- `CASE-4001` absent;
- raw arm values, RRF, and rerank are separate;
- `SQ-5` is uncovered on attempt 1 with `missing_kinds = {runbook}`;
- exactly one escalation fires, and attempt 2 covers `SQ-5` with `RB-5000`;
- the agent run reports `tool_calls_spent` against `max_tool_calls`.

### Module 3 — Port the tool contracts

**Target:** 7–9 minutes.

Participants do not deploy infrastructure.

They invoke the same contract through:

1. HTTP/FastAPI;
2. local stdio MCP;
3. pre-provisioned AgentCore Gateway.

Recommended tools for the live exercise:

- `search_evidence`
- `answer_with_citations`

Participant runs a parity command that:

- invokes or consumes captured output from all three transports;
- strips transport-only fields;
- compares contract version;
- compares evidence order and arm positions;
- compares ACL-visible evidence set;
- compares citation source IDs;
- records normalized response hashes.

Completion proof:

- tool names derive from stable OpenAPI `operationId` values, with Gateway namespacing
  them as `${targetName}___${operationId}` and the normalizer stripping that prefix;
- all transports call the same canonical service;
- semantic result parity passes;
- transport trace IDs differ, Hybrid Retrieval Workbench proof semantics do not;
- Gateway adds a managed MCP surface without moving retrieval out of Aurora.

First cut if behind: Module 3.

---

## 15. Workshop timing

### Presentation — 10 minutes

| Time | Topic |
|---:|---|
| 0:00–1:30 | incident question and cited answer |
| 1:30–3:00 | why one retrieval mode fails |
| 3:00–5:30 | Aurora ownership, indexes, filters, and RRF |
| 5:30–7:30 | plans, waits, lock tree, and proof receipt |
| 7:30–9:00 | three-module lab |
| 9:00–10:00 | tool contract portability preview |

### Whole-session budget — 60 minutes

The session is 60 minutes end to end. Presentation plus hands-on is 50 of those; the
remaining 10 are arrival, environment verification, wrap, and reserve. Earlier drafts
budgeted 12 + 45 = 57 minutes of content, which left no room for a room that has to log
in first.

| Time | Segment |
|---:|---|
| 0:00–0:03 | arrival, Code Editor open, `GET /ready` green |
| 0:03–0:13 | presentation |
| 0:13–0:26 | Module 1 — 13 minutes |
| 0:26–0:45 | Module 2 — 19 minutes |
| 0:45–0:53 | Module 3 — 8 minutes |
| 0:53–0:58 | replay receipt and production boundary |
| 0:58–1:00 | reserve |

Hands-on totals `13 + 19 + 8 = 40` minutes. The per-module ranges in §14 (12–14, 18–20,
7–9) are the acceptable envelope; this table is the plan. Overrun is absorbed by the cut
ladder below, not by the reserve.

When behind:

1. skip RRF weight experimentation;
2. use fixed `2:1:1`, `k=60`;
3. skip detailed evaluation;
4. cut Module 3;
5. never cut cited answer, ACL proof, or replay.

---

## 16. Tool contract portability ladder

```text
canonical Python service
  ├── FastAPI adapter          -> HTTP JSON
  ├── stdio MCP adapter        -> local MCP tools
  └── OpenAPI target           -> AgentCore Gateway managed MCP endpoint
```

### Invariants

- one service implementation;
- one contract version;
- one SQL owner;
- one ranking owner;
- one proof owner;
- adapters are stateless;
- adapter-specific metadata stays outside canonical result objects;
- all tools return JSON-serializable structures;
- no adapter directly queries Aurora except through the shared service;
- no adapter calls Bedrock except through the shared service;
- operation names are stable.

### OpenAPI constraints for Gateway

- OpenAPI 3.0 or 3.1;
- `operationId` on every exposed operation;
- static, valid server URL for the deployed artifact;
- `application/json`;
- simple schemas;
- do not use `oneOf`, `anyOf`, or `allOf`;
- auth is configured outside the OpenAPI document.

### Gateway tool naming

AgentCore Gateway does **not** expose the bare `operationId` as the MCP tool name. It
namespaces each tool by its target:

```text
${targetName}___${operationId}          # three underscores
verity-openapi-tools___search_evidence
verity-openapi-tools___answer_with_citations
```

Consequences Codex must implement:

- `operationId` stability remains a contract rule — it is the stable suffix, and
  renaming one is a contract-version change.
- The parity normalizer strips the `${targetName}___` prefix before comparing tool
  identity across transports. HTTP and stdio MCP use the bare name; Gateway does not.
  Comparing raw tool names across transports will fail for a reason that has nothing to
  do with retrieval.
- The Module 3 UI shows both forms, because the prefix is the visible evidence that the
  transport moved while the contract did not.

### Workshop deployment

Workshop Studio pre-provisions everything below. None of it is participant work.

Database and runtime:

- target Aurora PostgreSQL cluster and network access from the participant environment;
- required extensions and cluster parameter group settings, including
  `shared_preload_libraries` for `pg_stat_statements`;
- preloaded casework, search index, vectors, and built indexes;
- a Code Editor environment with database credentials already configured;
- IAM and Amazon Bedrock model access.

Tool transport:

- the HTTP endpoint at a static HTTPS URL;
- the Gateway;
- the OpenAPI target;
- inbound and outbound auth, including the inbound bearer token the workshop utility
  presents when calling the Gateway MCP endpoint;
- environment variables from §23;
- a test principal.

Participants never generate vectors, create Gateway resources, configure OAuth, or
build the release corpus. If any item above is missing, Module 1 cannot start — this
list is the pre-flight check, not a wish list.

The repository provides:

- OpenAPI file;
- local MCP adapter;
- contract fixtures;
- parity test;
- deployment instructions for authors.

---

## 17. HTTP API

### Health and readiness

- `GET /health`
- `GET /ready`

### Retrieval

- `POST /v1/search`
- `POST /v1/search/fts`
- `POST /v1/search/vector`
- `POST /v1/search/fuzzy`

### Tools

- `POST /v1/tools/decompose`
- `POST /v1/tools/traverse`
- `POST /v1/tools/compare`
- `POST /v1/tools/explain-ranking`
- `POST /v1/tools/synthesize`

### Agent

- `POST /v1/agent/answer`
- `POST /v1/agent/answer/stream`

### Evidence and proof

- `GET /v1/evidence/{evidence_id}`
- `GET /v1/runs/{run_id}`
- `GET /v1/runs/{run_id}/candidates`
- `GET /v1/runs/{run_id}/timeline`
- `GET /v1/runs/{run_id}/graph`
- `GET /v1/agent-runs/{agent_run_id}` — subquestions, coverage, retrievals, escalations,
  budget spend, answer, and citations
- `GET /v1/agent-runs/{agent_run_id}/coverage` — the per-subquestion coverage table
  behind the Module 2 coverage strip

### Diagnostics and evaluation

- `GET /v1/diagnostics/search-index`
- `GET /v1/diagnostics/corpus`
- `GET /v1/diagnostics/fusion-sql`
- `POST /v1/diagnostics/plan`
- `GET /v1/diagnostics/index-usage`
- `GET /v1/diagnostics/slow-queries`
- `POST /v1/evaluation`

---

## 18. Aurora PostgreSQL depth: plans, caches, waits, and locks

This section is what makes the session Aurora-specific rather than
PostgreSQL-with-an-Aurora-logo. Everything here is observable in the Plan X-Ray surface
that already exists, so it costs no additional lab minutes.

### 18.1 `aurora_stat_plans`

Aurora captures execution plans keyed to `pg_stat_statements` entries. The function is:

```sql
SELECT queryid, planid, plan_type, plan_captured_time, calls, mean_exec_time,
       left(query, 80) AS query, explain_plan
FROM aurora_stat_plans(true)          -- showtext = true returns query and plan text
WHERE query ILIKE '%chunks%'
ORDER BY mean_exec_time DESC
LIMIT 10;
```

It returns the `aurora_stat_statements` columns plus `planid`, `explain_plan`,
`plan_type`, and `plan_captured_time`. `plan_type` is exactly one of `no plan`,
`estimate`, or `actual` — which is the source of truth for the Plan X-Ray label in
§18.6. The workbench reads it; it does not infer it.

Prerequisites, both hard:

- `aurora_compute_plan_id = on`;
- `pg_stat_statements` in `shared_preload_libraries`.

Availability is Aurora PostgreSQL 14.10 / 15.5 and later. Plan storage is capped by
`pg_stat_statements.max` — plans are evicted with their statement entries, so a plan is
not a permanent record.

Capture GUCs and their defaults:

| GUC | Default | Effect |
|---|---|---|
| `aurora_stat_plans.minutes_until_recapture` | `0` | never recapture on a timer |
| `aurora_stat_plans.calls_until_recapture` | `0` | never recapture on a call count |
| `aurora_stat_plans.with_costs` | `on` | include cost estimates |
| `aurora_stat_plans.with_analyze` | `off` | actual rows and loops — flips `plan_type` to `actual` |
| `aurora_stat_plans.with_timing` | `on` | per-node timing |
| `aurora_stat_plans.with_buffers` | `off` | buffer counters — see §18.2 |
| `aurora_stat_plans.with_wal` | `off` | WAL counters |
| `aurora_stat_plans.with_triggers` | `off` | trigger timing |

These take effect **only for newly captured plans**. Changing a setting does not
retroactively enrich a plan already in the store, which is why the release gate captures
plans *after* the parameter group is final, not before.

AWS publishes no overhead figure for plan capture. Do not state one, do not estimate one
on a slide, and do not let a participant infer one from lab timings on a corpus this
small.

### 18.2 `with_buffers = on` — the load-bearing setting

This is the strongest Aurora-specific asset in the material.

With `with_buffers` enabled, `EXPLAIN (ANALYZE, BUFFERS)` on Aurora emits two counters
that exist in no other PostgreSQL:

- `aurora_orcache_hit` — pages served from the Optimized Reads tiered cache on local NVMe;
- `aurora_storage_read` — pages that went all the way to the Aurora storage volume.

They appear only when Optimized Reads is enabled and the value is greater than zero, so
their absence is not evidence of anything. Example line from the Aurora documentation:

```text
Buffers: shared hit=3 read=2 aurora_orcache_hit=2
```

Read left to right this is a three-tier memory hierarchy on one line: `shared hit` is
RAM, `aurora_orcache_hit` is the NVMe tier, `aurora_storage_read` is the network storage
volume. Community PostgreSQL has two tiers and one number.

This is what makes the §13.6 escalation *measurable* rather than merely logged. The
first retrieval runs with `ef_search = 40`; the escalated one runs with `ef_search = 200`
over a wider candidate pool, and the per-node buffer counters show the HNSW scan falling
out of RAM onto NVMe, or off NVMe onto storage. The agent's decision to widen its search
has a visible price, expressed in the same units as everything else in the plan.

Enable `with_buffers` for the workshop parameter group. It is `off` by default and it is
the single setting that turns the Plan panel from a generic PostgreSQL plan into an
Aurora one.

### 18.3 Optimized Reads as a plan-visible fact

The interactive scale model was correctly cut. These facts are not that model — they are
properties visible in a plan and in an instance choice, and they are the difference
between a vector workload that fits and one that does not.

- **Tiered cache is Aurora I/O-Optimized only.** On an Aurora Standard cluster you get
  temp-object acceleration and nothing else. There is no error and no warning; the
  performance simply is not there. This is the failure mode most likely to bite someone
  who copies the instance class without the storage configuration.
- **Aurora reduces `shared_buffers` by 4.5%** on `r6gd`, `r6id`, and `r8gd` to hold
  tiered-cache metadata. For a working set that just fits in RAM, moving `r6g` → `r6gd`
  is a **net regression**: you give up buffer pool to gain a tier you were not using.
- **The tier holds clean pages only.** Modifying a page invalidates its NVMe copy. HNSW
  insertion ripples neighbour-list updates across the index, so a continuously
  re-embedded corpus keeps invalidating the tier. Optimized Reads is a **static-corpus
  feature for vector workloads** — which is exactly the shape of this workshop's frozen
  search index, and exactly not the shape of a live ingestion pipeline.
- **Temp objects move to NVMe on both cluster types.** Sorts, hash joins, and
  materialized CTEs spill to local storage regardless of Standard or I/O-Optimized. This
  is directly relevant here: RRF over a large candidate pool is a sort-and-hash workload,
  and the fusion step is where a big pool spills.

Published benchmark, for the appendix and the slide, quoted with its parameters:

| | |
|---|---|
| Dataset | BIGANN-1B, 128 dimensions |
| Index | HNSW, `m=16`, `ef_construction=64`, `ef_search=400`, recall `0.9578` |
| Size | 614 GB table, 781 GB index, against a 250–350 GB buffer pool |
| Result | R6gd vs R6g: **4.1–9.3× throughput** |
| Cost | **$59.02** vs **$329.84** per million queries |

The detail worth putting on the slide is the CPU number. The memory-starved R6g instance
never exceeds **15% CPU** because it is blocked on network storage, while the NVMe
instance runs at **95%**. A starved HNSW workload on Aurora *looks idle*. Anyone
autoscaling on CPU will scale the wrong direction, and anyone eyeballing a dashboard
will conclude the database is fine.

Sources: the Optimized Reads user guide and the AWS Database Blog post on accelerating
generative AI workloads with Optimized Reads and pgvector, both listed in
`docs/REFERENCES.md`. Reconfirm the benchmark numbers before the event; blog figures age.

### 18.4 Aurora-specific wait events

| Wait event | Meaning |
|---|---|
| `IO:AuroraOptimizedReadsCacheRead` | reading a page from the NVMe tiered cache |
| `IO:AuroraOptimizedReadsCacheWrite` | populating the tiered cache |
| `LWLock:AuroraOptimizedReadsCacheMapping` | contention on the tiered-cache mapping table |
| `IO:XactSync` | waiting for the Aurora storage subsystem to acknowledge the commit |
| `IO:AuroraStorageLogAllocate` | allocating log space in the storage tier |

The non-obvious point, and the one to make explicitly during the incident walkthrough:

In the blocked-writer-behind-`CREATE INDEX` scenario, the **lock** wait is plain
community PostgreSQL — `Lock:relation`, identical on any engine. Nothing about lock
semantics is Aurora-specific. What *is* Aurora-specific is the **commit-path** pressure
the index build creates, because Aurora moved durability into the storage tier: the
build generates log volume, and the queued writers behind it accumulate `IO:XactSync`
and `IO:AuroraStorageLogAllocate` that a single-node PostgreSQL would never show.

So the lock tree is portable knowledge and the commit-path waits are the Aurora lesson.
Teaching them as one undifferentiated thing is the mistake.

### 18.5 The lock catalogs the scenario is actually about

This session's incident is a lock incident. The lock evidence must come from the real
catalogs, not only from a seeded `text` column.

Blocking tree via `pg_blocking_pids()`:

```sql
SELECT blocked.pid                        AS blocked_pid,
       blocked.wait_event_type,
       blocked.wait_event,
       left(blocked.query, 60)            AS blocked_statement,
       blocking.pid                       AS blocking_pid,
       left(blocking.query, 60)           AS blocking_statement,
       blocking.state                     AS blocking_state,
       now() - blocked.query_start        AS blocked_for
FROM pg_stat_activity blocked
CROSS JOIN LATERAL unnest(pg_blocking_pids(blocked.pid)) AS b(blocking_pid)
JOIN pg_stat_activity blocking ON blocking.pid = b.blocking_pid
ORDER BY blocked_for DESC;
```

Lock detail for one relation, `pg_locks` joined to `pg_stat_activity`:

```sql
SELECT l.locktype, l.relation::regclass AS relation, l.mode, l.granted,
       a.pid, a.wait_event_type, a.wait_event, left(a.query, 60) AS query
FROM pg_locks l
JOIN pg_stat_activity a ON a.pid = l.pid
WHERE l.relation = 'orders'::regclass
ORDER BY l.granted, a.pid;
```

Build progress, which is how you answer "how much longer" without guessing:

```sql
SELECT p.pid, p.phase,
       p.blocks_done, p.blocks_total,
       round(100.0 * p.blocks_done / NULLIF(p.blocks_total, 0), 1) AS pct_blocks,
       p.tuples_done, p.tuples_total,
       c.relname AS table_name, i.relname AS index_name
FROM pg_stat_progress_create_index p
LEFT JOIN pg_class c ON c.oid = p.relid
LEFT JOIN pg_class i ON i.oid = p.index_relid;
```

Cleanup after a failed concurrent build — `RB-5000` describes this in prose and must
also name the statements:

```sql
-- an interrupted CREATE INDEX CONCURRENTLY leaves an INVALID index behind
SELECT i.indexrelid::regclass AS invalid_index,
       i.indrelid::regclass   AS on_table
FROM pg_index i
WHERE NOT i.indisvalid;

-- documented recovery for a failed concurrent build: drop, then rebuild
DROP INDEX CONCURRENTLY idx_orders_customer;

-- for a valid but bloated index, rebuild without a long exclusive lock (PG12+)
REINDEX INDEX CONCURRENTLY idx_orders_customer;
```

`DROP INDEX CONCURRENTLY` and `REINDEX INDEX CONCURRENTLY` solve different problems and
the runbook must say which is which: drop-and-recreate is the recovery path for an
INVALID index left by a failed build; `REINDEX ... CONCURRENTLY` is the maintenance path
for an index that is valid and needs rebuilding.

Both carry the same restriction as `CREATE INDEX CONCURRENTLY` and it is the one that
bites during an incident: **none of them can run inside a transaction block.** Pasting
the cleanup into a `BEGIN ... COMMIT`, or into a tool that opens one implicitly, fails
with `DROP INDEX CONCURRENTLY cannot run inside a transaction block` at exactly the
moment someone is trying to recover. `RB-5000` states this for all three statements, not
just for the build.

### 18.6 CloudWatch Database Insights handoff

Plan X-Ray must distinguish `estimated` from `actual`, and the label comes from
`aurora_stat_plans.plan_type` (§18.1), never from inference.

Default label:

```text
Plan type: estimated
```

Show `actual` only when the backend has read `plan_type = 'actual'` for that `planid`,
which requires `aurora_stat_plans.with_analyze = on` at capture time.

The UI offers author-configured links:

- `Open captured plans in Database Insights`
- `Open incident lock tree`

The workbench does not claim Database Insights data is available in local mode, and it
does not present any Aurora-specific counter it did not actually read.

---

## 19. Final UI information architecture

Use three top-level modules:

1. **Retrieve**
2. **Prove**
3. **Port tools**

Do not ship seven equal-weight top-nav screens.

### Retrieve

Consolidates the strongest parts of Retrieval Lab and Fusion:

- four-column layout — three fusion arms (text, vector, fuzzy) plus the fused result
  column, per §11.1. Exact/B-tree is part of the text column, not a fourth arm;
- presets;
- principal;
- rerank;
- RRF formula;
- `k` and weights;
- per-row receipt drawer;
- empty-arm state.

### Prove

Consolidates Ask, Evidence Graph, Plan X-Ray, and Evaluation:

- canonical question;
- deterministic plan;
- cited answer;
- candidate receipt;
- graph;
- plan/SQL panel;
- stage timing;
- proof receipt;
- compact leaderboard;
- Database Insights handoff.

Use internal tabs or anchored panels:

- `Answer`
- `Graph`
- `Plan`
- `Receipt`

### Port tools

A clear portability ladder:

- shared contract;
- HTTP adapter;
- stdio MCP adapter;
- AgentCore Gateway adapter;
- tool list;
- sample input;
- normalized output hash;
- parity matrix;
- Gateway status;
- explicit note: “same retrieval and proof owner.”

### Removed from core UI

- marketing landing page;
- Scale page;
- live connector page;
- OAuth configuration;
- infrastructure provisioning;
- Managed Knowledge Base lane;
- generic chat panel.

---

## 20. Final visual design

Use the warm technical workbench design system:

- paper `#FAF4EC`;
- ink `#211C16`;
- soft ink `#584F45`;
- muted `#94897C`;
- hairline `#E9DFD2`;
- evidence red `#C13A26`;
- deep red `#9E2F1E`;
- wash `#FBEDE8`;
- confirmed green `#2E7D54`;
- derived/vector clay `#DE9C7C`.

Rules:

- red means evidence thread, not danger;
- green means a confirmed finding, including a ruled-out alternative;
- clay is fill/stroke only, not body text;
- muted+dashed means absent, not failed;
- identifiers, scores, SQL, and timings are monospace;
- assertions and final answer headings use serif;
- UI copy uses sans-serif;
- remote fonts are forbidden in the shipped app;
- color is never the only semantic channel;
- reduced-motion is honored;
- scores are diagnostics, not probabilities;
- RRF and rerank remain separate;
- ACL-filtered evidence is absent.

---

## 21. Frontend routes and component map

Recommended routes:

- `/retrieve`
- `/prove`
- `/tools`

Recommended subroutes or state:

- `/prove?tab=answer`
- `/prove?tab=graph`
- `/prove?tab=plan`
- `/prove?tab=receipt`

Core components:

- `AppShell`
- `ModuleNav`
- `QueryBar`
- `PrincipalToggle`
- `PresetSelector`
- `RetrievalArm`
- `FusedCandidateList`
- `CandidateReceiptDrawer`
- `RrfControls`
- `CitedAnswer`
- `DeterministicPlan`
- `EvidenceGraph`
- `PlanXray`
- `DatabaseInsightsLinks`
- `ProofReceipt`
- `EvaluationSummary`
- `ToolContractLadder`
- `TransportParityMatrix`

---

## 22. Backend package boundaries

```text
sql/                         # schema, indexes, search, diagnostics, receipts, evaluation, traversal
  001_extensions.sql
  002_schemas.sql
  010_casework.sql
  020_retrieval.sql
  030_proof.sql
  040_functions.sql
seed/                        # deterministic synthetic casework corpus and release inputs
  casework/
  background/
backend/
  domain/
    models.py
    ids.py
  services/
    planner.py
    retrieval.py
    traversal.py
    comparison.py
    ranking.py
    synthesis.py
    receipts.py
  repositories/
    casework.py
    retrieval.py
    proof.py
  api/                       # the single HTTP home: FastAPI app and routers
    app.py
    routes_*.py
  adapters/
    lambda_target/           # AWS Lambda entry point over the same services
      handler.py
mcp-server/                  # local stdio MCP adapter (TypeScript)
contracts/
```

Rules:

- No SQL or domain logic in `adapters/` or `mcp-server/`. Adapters marshal and delegate.
- `backend/api/` is the only HTTP home. There is no parallel `adapters/http/`; the
  FastAPI app *is* the HTTP adapter, and a second one would be a second place for a
  route to drift.
- `backend/adapters/lambda_target/` — **not** `adapters/lambda/`. `lambda` is a Python
  keyword, so `import backend.adapters.lambda.handler` is a `SyntaxError` and the
  package cannot be imported at all.
- There is no top-level `lambda_mcp/`. The Lambda entry point lives in
  `backend/adapters/lambda_target/` so it shares the service layer by import rather
  than by copy.
- `sql/` is applied in filename order and is the only source of schema. The DDL in §9,
  §10, and §11 is what these files contain.

---

## 23. Model configuration

Model IDs are configuration, not application constants. The values below are the
validated defaults, and Codex wires them through environment variables rather than
literals.

### Platform baseline

| Component | Requirement |
|---|---|
| PostgreSQL | 13 or later for `gen_random_uuid()`; validated on 18.4 |
| `pgvector` | **>= 0.8.0** — required for HNSW iterative scan (§11.3) |
| `pg_trgm` | any supported version |
| `pg_stat_statements` | enabled via cluster parameter group `shared_preload_libraries` |
| `aurora_compute_plan_id` | `on` — prerequisite for `aurora_stat_plans` (§18.1) |
| `aurora_stat_plans.with_buffers` | `on` — required for the Aurora buffer counters (§18.2) |
| `aurora_stat_plans` availability | Aurora PostgreSQL 14.10 / 15.5 and later |

Aurora PostgreSQL ships `pgvector 0.8.0` on 16.8, 15.12, 14.17, and 13.20 and later, and
`0.8.1` on 17.9 and 16.13 and later. Pin the workshop cluster at or above one of those
minor versions. AWS engine-version-to-extension-version mapping moves; reconfirm it
against current documentation at release gate 2 rather than trusting this table.

### Model roles

| Role | Model ID | API and routing |
|---|---|---|
| Embedding | `us.cohere.embed-v4:0` | Bedrock Runtime `InvokeModel`, US CRIS |
| Reranking | `cohere.rerank-v3-5:0` | Bedrock Agent Runtime `rerank` |
| Synthesis | `global.anthropic.claude-sonnet-5` | Bedrock Runtime `Converse`, Global CRIS |

### Embedding space invariant

Non-negotiable, and the most common way this system fails silently:

- vectors are **1024-dimensional**;
- `output_dimension` is pinned **explicitly on both ingest and query** — not defaulted on
  either side, because a provider default change would silently re-space the corpus;
- stored evidence embeds with Cohere input type `search_document`;
- live queries embed with input type `search_query`;
- **query and stored embedding spaces must match exactly** — same model ID, same
  dimension. A query vector from a different model space produces confidently ranked
  nonsense rather than an error.

The invariant is enforced in three places: the `chunks_ready_requires_embedding_ck`
constraint (§9.3), drift condition 5 (§10.5), and a unit test that asserts a
mismatched-space query is rejected rather than executed.

Cosine distance produces the semantic ordering, via `<=>` against a
`vector_cosine_ops` HNSW index.

### Environment variables

```bash
AWS_REGION=us-east-1
AWS_DEFAULT_REGION=us-east-1
BEDROCK_EMBEDDING_MODEL=us.cohere.embed-v4:0
COHERE_RERANK_MODEL=cohere.rerank-v3-5:0
BEDROCK_SYNTHESIS_MODEL=global.anthropic.claude-sonnet-5
BEDROCK_MODEL_TRANSPORT=converse_global_cris
BEDROCK_SYNTHESIS_MAX_TOKENS=1200
EMBED_PROVIDER=bedrock            # 'hash' in offline local mode
VITE_RETRIEVAL_API_URL=           # the only URL the frontend calls
VITE_USE_MOCKS=false              # 'true' selects local mock mode
```

Workshop Studio injects these. The names are part of the contract: renaming one breaks
a pre-provisioned environment that Codex cannot see.

### Modes

**Offline local mode.** `EMBED_PROVIDER=hash`. Stored and query embeddings both use
model space `local-hash-embedding-v1` at 1024 dimensions. Reranking is disabled and
synthesis falls back to the deterministic extractive path (§13.4). The hash provider is
a mechanical substitute that proves embedding-space enforcement and search plumbing —
it proves nothing about semantic quality, and no result from it may be described as
Cohere-validated.

**Mock mode.** `VITE_USE_MOCKS=true`. Frontend-only. The UI renders from
`src/lib/fixtures.ts` and makes no network calls at all. It exists for component work
and visual regression, never for demonstrating retrieval.

**Workshop mode.** `EMBED_PROVIDER=bedrock`, vectors preloaded, Bedrock access
preconfigured, bounded adaptive retries on every model client, explicit `maxTokens` on
synthesis, and `RUN-7000` replayable by the facilitator with no model call on the path.

The validated synthesis design uses Converse plus Global CRIS. It does not claim that
Mantle and CRIS are used simultaneously. Revalidate model lifecycle, Region support,
CRIS routing, quotas, and IAM before the event.

---

## 24. Tests

### Unit

- ID extraction for standardized IDs, including the `id_tokens` versus
  `unresolved_id_tokens` split;
- ACL visibility, both directions, against the fixed ACL document shape;
- RRF formula, pinning `RRF(text=1, vector=1) = 3.0/61` so integer division cannot
  regress silently;
- weights bind as numeric, never integer;
- absent arm zero;
- arm positions are dense `1..n` after `DISTINCT ON`;
- one strongest passage per evidence item;
- exact hits sort ahead of FTS-only hits in the merged text arm;
- embedding-space mismatch is rejected, not executed;
- naive score summation baseline reproduces its documented effective weighting;
- citation quote containment;
- response normalization for parity, including stripping the Gateway
  `${targetName}___` tool-name prefix;
- transport metadata stripping;
- `evaluate_subquestion_coverage` returns the exact missing kinds, including the
  zero-candidate case where every required kind is missing;
- the escalation fires at most `max_escalations` times and the budget CHECK rejects
  an over-spend;
- `budget_exhausted` and `partial` are surfaced in the response, not swallowed;
- citation repair runs at most once, and a still-failing answer produces 422 with no
  answer text;
- `no_evidence` makes no model call;
- traversal terminates on a cyclic edge set via the `CYCLE` clause.

### Integration

- exact query ranks `CHG-1000` first;
- semantic query finds incident and lock evidence;
- fuzzy query maps `CGH-1000` to `CHG-1000`, and to nothing else at threshold `0.30`;
- default principal excludes `CASE-4001`;
- support lead includes it;
- `CHG-1000` confirmed and `CHG-1001` ruled out;
- answer cites incident, change, lock, visible case, and runbook;
- `RUN-7000` replays;
- `SQ-5` coverage fails on attempt 1 with `missing_kinds = {runbook}` under the
  `cluster_id` filter, and succeeds on attempt 2 after the filter is dropped;
- raising `ef_search` without dropping `cluster_id` does **not** cover `SQ-5`;
- budget exhaustion produces a `partial` run that reports the uncovered subquestion
  rather than a complete-looking answer;
- an all-arms-empty query returns `synthesis_mode = 'no_evidence'`, HTTP 200, zero
  citations, and makes no model call;
- a tampered citation quote yields HTTP 422 and no answer text;
- the inline ACL predicate and `retrieval.acl_visible` agree for every document and
  both principals;
- HTTP and stdio MCP normalize to the same semantic response;
- AgentCore capture normalizes to the same semantic response.

### UI

- all three modules render;
- internal tables scroll;
- no document-level horizontal overflow;
- keyboard focus visible;
- reduced motion honored;
- no remote network calls in mock mode;
- no remote fonts;
- no vendor logos;
- `CASE-4001` absent in default fixture state;
- plan type clearly labeled;
- tool parity status is not implied until checked.

---

## 25. Acceptance criteria

### search index and retrieval

- rebuild is idempotent — a second build over unchanged casework promotes nothing and
  records `skipped_unchanged`;
- unchanged content reuses model-and-hash embeddings from `retrieval.embedding_cache`;
- tombstones supersede current documents without erasing history, and historical
  citations still validate;
- `retrieval.v_search_index_drift` returns zero rows before `/ready` reports ready;
- exactly one canonical signature exists for each search and helper function;
- query and stored embedding spaces match exactly;
- default fusion controls persist as `2:1:1`, `k=60`, fuzzy threshold `0.30`,
  `ef_search=40`, `iterative_scan=strict_order`;
- result sets contain at most one strongest passage per evidence item;
- HNSW runtime settings are transaction-local and do not survive the transaction.

### Module 1

- exact/FTS, semantic, and fuzzy arms are visible independently;
- filters and ACL placement are explicit;
- empty arm is not an error;
- `CGH-1000` resolves through trigram, using the `%` operator against the GIN index;
- the fuzzy arm probes only unresolved identifier tokens, never the full question;
- RRF receives rank positions, not raw scores, and weights bind as numeric.

### Module 2

- `CHG-1000` confirmed;
- `CHG-1001` ruled out;
- `CASE-4000` affected;
- `CASE-4002` unaffected;
- `CASE-4001` absent for workshop;
- five citations validate;
- candidate receipt persists before synthesis;
- replay works without model calls;
- plan label is honest;
- Database Insights handoff is available only when configured.

### Module 3

- OpenAPI has stable `operationId` for every tool;
- HTTP, stdio MCP, and Gateway adapters use the same service;
- normalized candidate ordering matches;
- normalized citations match;
- ACL-visible evidence set matches;
- contract version matches;
- transport traces are stored separately;
- no Gateway provisioning is required by participants.

---

## 26. Non-goals

Do not implement in the participant core:

- live SaaS connectors;
- source mutations;
- participant OAuth;
- Gateway provisioning;
- AgentCore Runtime, Identity, Policy, Memory, Evaluations, Browser, or Code Interpreter;
- Managed Knowledge Bases;
- OpenSearch;
- Neptune;
- a second evidence database;
- vector generation at session time;
- marketing landing page;
- the Scale page and the interactive Optimized Reads / scale-multiplier model;
- unmeasured performance claims.

Optimized Reads itself is **not** a non-goal. The interactive capacity model was cut;
the plan-visible facts in §18.2 and §18.3 are in scope, because they are read from
`EXPLAIN (ANALYZE, BUFFERS)` output and from published benchmarks with their parameters
attached. The rule is unchanged: state what was measured and by whom, or say nothing.

---

## 27. Release gates

1. Schema and migrations pass on target Aurora PostgreSQL.
2. Required extensions and minimum versions verified against §23, specifically
   `pgvector >= 0.8.0`, `pg_trgm`, `btree_gin`, and `pg_stat_statements` in
   `shared_preload_libraries`.
3. search index readiness and drift zero.
4. Exact/FTS/trigram/HNSW plans captured.
5. Filtered HNSW behavior measured at release scale.
6. `aurora_compute_plan_id = on`, `aurora_stat_plans` returns rows, and the
   `estimate` / `actual` label the UI shows matches `aurora_stat_plans.plan_type`.
7. Lock-tree handoff validated, and the §18.5 catalog queries run against the
   workshop cluster.
8. Bedrock embedding/rerank/synthesis models and quotas validated.
9. AgentCore Gateway OpenAPI target created from the packaged contract.
10. HTTP/MCP/Gateway parity test passes.
11. Workshop Studio image contains immutable source revision, the frozen embedding
    cache, and the PostgreSQL restore artifact.
12. Frontend build and responsive tests pass.
13. Facilitator replay works without Bedrock.
14. All illustrative numbers clearly labeled until replaced.
15. Room-scale concurrency and throttling tests pass for API, Aurora, rerank, and
    synthesis, at the expected participant count. Module 2 has every participant
    issuing a synthesis call inside the same five-minute window.
16. Fresh-account Workshop Studio provisioning verified end to end, including every
    item in the §16 provisioning list and the exact participant commands.
17. Final source revision, archive hash, expected run IDs, and facilitator fallback
    checkpoints recorded.
18. `aurora_stat_plans.with_buffers = on` in the workshop parameter group, and a captured
    plan actually shows `aurora_orcache_hit` or `aurora_storage_read`. If the cluster is
    Aurora Standard rather than I/O-Optimized, these counters will never appear — verify
    the storage configuration, not just the instance class (§18.3).
19. Agent-loop determinism: the canonical question produces exactly one escalation on
    `SQ-5`, and `RUN-7100`-series retrieval IDs are stable across reruns.
20. Optimized Reads benchmark figures in §18.3 reconfirmed against current AWS sources,
    or removed. Blog numbers age; a stale figure on a slide is a claim.
21. **Tracked risk, not a stage claim:** Aurora currently ships pgvector `0.8.1` at
    newest, so it does not yet include the `0.8.3` fix for possible index corruption
    during HNSW vacuuming. Confirm the shipped version at release, confirm whether the
    workshop's static, never-vacuumed search index is exposed, and record the finding. Do
    not raise this on stage as an Aurora defect; it is a version-tracking item.

No local result may be described as Aurora validation, and no hash-vector result may be
described as Cohere semantic-quality validation.

---

## 28. Codex implementation order

1. Apply the `sql/` schema from §9, §10, and §11 to a disposable database and confirm
   it runs clean, before writing any application code.
2. Apply ID migration, including the `CHG-0100` to `CGH-1000` typo-fixture change.
3. Update seed data, expected results, tests, UI fixtures, docs.
4. Widen `contracts/openapi/verity-tools.openapi.yaml` to the §13 tool outputs, then
   stabilize tool schemas and `contract_version`.
5. Implement/verify canonical service boundaries.
6. Build `Retrieve`.
7. Build `Prove`.
8. Build `Port tools`.
9. Implement local MCP adapter.
10. Package AgentCore OpenAPI target.
11. Add parity normalizer/test, including Gateway tool-name prefix stripping.
12. Add Database Insights links and honest plan labels.
13. Remove/deprecate Scale from core navigation.
14. Run QA and release gates.

---

## 29. Final implementation warning

The design-source HTML files contain old identifiers, remote font references, illustrative timings, and a deprecated Scale concept. They are references only.

The shipped React implementation must use:

- standardized identifiers;
- system/local fonts;
- API-driven data;
- three modules;
- no Scale page;
- no old Threadline product copy.
