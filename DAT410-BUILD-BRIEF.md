# DAT410 Build Brief

**Session:** Build agentic hybrid retrieval with Amazon Aurora PostgreSQL
**Format:** L400 builders session, 60 minutes
**Application:** Hybrid Retrieval Workbench

## Objective

Participants induce a real Aurora PostgreSQL write stall, create a searchable
corpus from their own measured PostgreSQL and AWS telemetry, generate embeddings
in real time, investigate the run with hybrid retrieval and bounded agent
tools, and persist a citation-validated answer for replay.

## Evidence Contract

- Provisioning applies schema, generates 5,000 disposable operational
  customers and 3,000,000 related orders, and starts at `awaiting_incident` with
  zero evidence.
- `make live-workshop` is the only participant ingestion path.
- Every participant-facing record uses `source_system=pg_incident_capture`.
- Every source URI and revision traces to the current capture UUID.
- IDs use `INC-<run-suffix>`, `CHG-<run-suffix>-01/02`,
  `LOCK-<run-suffix>-01`, and `TEL-<run-suffix>-...`.
- Raw repeated samples remain relational proof.
- Distinct measured observations become about 110 documents and 100-250
  chunks.
- Cohere Embed 4 vectors are generated through Bedrock during the run.
- No authored, fictional, demo, offline, fixture, prior-run, or canned record
  is permitted. The Overview main graphic is the sole illustrative exception.

## Participant Path

| Time | Build |
|---:|---|
| 0-5 | access the environment and verify the empty evidence store |
| 5-10 | understand the hung migration and evidence journey |
| 10-25 | cause, fix, admit, embed, and publish the receipt |
| 25-40 | build exact, FTS, semantic, fuzzy, filtered, fused, and reranked retrieval |
| 40-50 | build the incident agent through decomposition, traversal, comparison, and synthesis |
| 50-55 | validate citations and replay |
| 55-58 | inspect the reusable retrieval skill |
| 58-60 | summarize and confirm cleanup |

## Retrieval Contract

Aurora PostgreSQL owns exact and full-text retrieval, pgvector semantic search,
pg_trgm typo recovery, metadata filters, weighted reciprocal rank fusion,
relationship reads, citation validation, evaluation, and replay.

Raw arm scores, PostgreSQL RRF, and model rerank scores stay separate. Exact
identifiers remain deterministic. Filters execute inside each arm before
fusion. Agent tools and adapters consume the API and do not duplicate ranking.

## Acceptance

A fresh target account must prove:

- zero evidence before the run;
- exactly 5,000 customers, 3,000,000 canonical related orders, and no target
  incident index before the run;
- 100-120 current documents, 100-250 chunks, and matching ready embeddings;
- 600-1,000 raw telemetry rows;
- exact and fuzzy rank 1 for the receipt-derived unsafe change;
- mixed kinds before the `change` filter and exactly both measured changes
  afterward;
- recomputable RRF;
- agent coverage of incident, change, lock, and telemetry;
- authoritative `change_confirmed`, `change_remediated`,
  `blocked_by_change`, and `observed_during` relationships;
- valid citation attribution; and
- replay with no model call.

Workshop Studio packages only committed schema and application source. It never
packages participant evidence or database state.
