# Mosaic Hybrid Retrieval

A read-only product retrieval capability on Aurora PostgreSQL. It generates
candidates three ways, enforces eligibility in SQL, fuses with reciprocal rank
fusion, reranks the bounded pool, and hands back a receipt that says what it did
and what it granted.

This file describes the capability. It does not implement it. The machine-readable
contract is `db/config/agent_tool_contracts.json`, served live at
`GET /api/tools?surface=skill`, and the generated table below is projected from
it, so this document cannot drift from what the service enforces.

## When to use this

Use it when a caller needs product candidates it can defend: filtered, ranked,
attributable, and inspectable. Use it when the caller must be able to answer "why
this product" with persisted evidence rather than a model's recollection.

Do not use it as a general agent. It decides nothing about what to ask or what to
say. A calling agent chooses which operation to invoke and when.

## What it owns

- lexical candidate retrieval, PostgreSQL full-text search;
- typo-tolerant candidate retrieval, `pg_trgm` similarity;
- semantic candidate retrieval, pgvector HNSW;
- relational and metadata eligibility, applied inside SQL before any limit;
- a bounded candidate pool;
- unweighted reciprocal rank fusion;
- managed reranking, with exact-SKU preservation;
- retrieval provenance, per arm and per stage;
- scoped access to source-addressable evidence;
- a deterministic grant boundary.

## What it does not own

`synthesize_cited_answer` is **not** part of this skill. Composing an answer,
choosing what to claim, and validating citations belong to the calling
application. The skill stops at authorized evidence.

There is no autonomous loop here. The caller orchestrates.

## Operations

<!-- BEGIN GENERATED CONTRACT: scripts/tool_contracts.py -->

| Operation | Capability | Route | Required arguments | Read-only |
|---|---|---|---|---|
| `search_products` | `open_retrieval` | `POST /api/search` | `query` | yes |
| `get_product_evidence` | `get_product_evidence` | `POST /api/products/{product_id}/evidence` | `retrieval_scope_id`, `product_id`, `evidence_query` | yes |
| `compare_products` | `compare_products` | `POST /api/retrieval/events/{search_event_id}/compare` | `retrieval_scope_id`, `product_ids` | yes |
| `explain_retrieval` | `explain_retrieval` | `GET /api/retrieval/events/{search_event_id}` | `retrieval_scope_id` | yes |
<!-- END GENERATED CONTRACT -->

## Inputs

Named as the API accepts them, not as they might read better.

| Field | Meaning |
|---|---|
| `query` | The retrieval intent, or an exact model or SKU string. |
| `filters` | Hard eligibility constraints: domain, category, brand, availability, price bounds, rating floor, attribute equality. |
| `limit` | How many ranked results to return. 1 to 50. |
| `authorized_limit` | How many of those results the caller authorizes for downstream evidence and comparison. Defaults to `limit`. Never greater than `limit`. |
| `include_diagnostics` | Return per-arm counts, stage timings, and warnings. |
| `rerank` | Apply managed reranking to the fused pool. |
| `retrieval_scope_id` | On the scoped operations: the `search_event_id` of the retrieval that granted the products. |

## Outputs

| Field | Meaning |
|---|---|
| `search_event_id` | The retrieval-scope handle. Pass this value as `retrieval_scope_id` to the scoped operations. |
| `results` | Ranked products, each carrying its own rank signals per arm, its fused rank, its rerank score, and its source attribution. |
| `diagnostics` | Strategy, rerank status, candidate counts per arm, stage timings, warnings. |
| `applied_filters` | The eligibility actually enforced, as SQL received it. |
| `normalized_query` | The query text the arms actually matched on. |

## Scope rules

The retrieval receipt records what happened. `authorized_limit` records what the
caller was granted. They are different, and the second one is the boundary.

- Evidence is served only for products the retrieval granted.
- Comparison is a projection over granted products. It cannot widen the set and
  issues no retrieval.
- Explanation covers the retrieval event and its full candidate pool.
- A scope that is unknown, or that predates explicit authorization, grants
  nothing. There is no inference from a receipt's size.
- A refusal is a 404 with a generic body. It does not report which product fell
  outside the window, or whether the product exists.

And the distinction the third lab exists to teach:

> **Retrieving scoped evidence does not by itself authorize that evidence for
> synthesis.** Grant scope and citation authorization are two boundaries. The
> calling application owns the second one.

## Two rank spaces

```text
Inspectable candidate pool          Authorized result window
up to 50 candidates                 1 to `limit`, caller declared
`pre_rerank_rank` lives here        evidence and compare allowed here
```

These are not the same boundary, and their ranks are not comparable. Subtracting
a rank in one from a rank in the other invents movement that did not happen.

> Explain can tell you that candidate 27 existed. That does not authorize you to
> retrieve evidence for candidate 27.

One honest limit on why explanation is left ungated. Explanation also returns
the retrieval's `session_id` and the raw `query_text` that produced it, and
those are not public the way a product record is. Leaving explanation unscoped
is a deliberate choice for a single-attendee, disposable workshop instance where
inspection is the point, not a claim that the data is harmless. A shared
deployment would have to scope event replay to its owner. See
`docs/skill-composition.md` for what else changes outside the workshop trust
model.

## Behavioral guarantees

- Eligibility is applied inside each arm's SQL, before any limit, so a filter can
  never be simulated by discarding rows after the fact.
- The candidate pool is bounded, and the bound is declared in the receipt.
- Fusion is unweighted reciprocal rank fusion. The weighted variant exists only
  as an explicit side-by-side comparison and never serves search.
- Reranking reorders the bounded pool. It cannot introduce a candidate, and it
  cannot displace an exact catalog-identifier match.
- Every operation is read-only.
- Every search persists a receipt, so ranking can be replayed rather than
  recomputed.

## Non-goal: scope is not identity

`search_event_id` is a retrieval-capability handle. It bounds which products a
scoped read may touch: `get_product_evidence` and `compare_products` refuse
anything outside the window the search declared.

It is not a synthesis authority. Citation authorization is a separate,
turn-local decision made by `synthesize_cited_answer`, which is not part of this
skill and never receives a `search_event_id`. Holding a scope handle does not
authorize any product or record for a cited answer.

It is not an identity, a tenant, or a data-access boundary, and holding one is
not authentication. A multi-tenant deployment would have to bind the scope to a
principal as well.

## Composition

For how another agent reaches this capability over MCP or A2A, and for the
AgentCore hosting contract, see `docs/skill-composition.md`. Transport and hosting
details are kept out of this file on purpose, so the contract survives changes in
how a capability happens to be hosted.
