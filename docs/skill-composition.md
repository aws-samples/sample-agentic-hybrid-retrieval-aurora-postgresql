# Composing the Mosaic hybrid retrieval skill

## Workshop boundary

This is a reveal, not a lab. It occupies 2 to 3 minutes of the 5-minute scorecard
segment. It adds no required exercise, no provisioning, and no fourth lab. The
required path remains Retrieve, Rank, Reason. The subject of this document is
composability — what a capability lets another agent consume, and what it keeps
hidden — not a tutorial on any particular transport protocol.

## 1. What the skill is

One bounded, read-only retrieval capability over Aurora PostgreSQL. It generates
candidates three ways, enforces eligibility in SQL, fuses the arms, reranks the
bounded pool, and returns a receipt of what it did and what it granted. The full
capability contract is `skills/mosaic-hybrid-retrieval/SKILL.md`; this document
does not restate it. It only answers a question that file deliberately leaves
open: what does it look like for something other than this workshop's own UI to
call the same contract?

## 2. What another agent gets to consume

Exactly four operations, named as the skill exposes them, one scope handle, and
one receipt:

| Operation | What it returns |
|---|---|
| `search_products` | Ranked, source-attributed products, plus `search_event_id` |
| `get_product_evidence` | Source-addressable evidence for a granted product |
| `compare_products` | A projection over already-granted products |
| `explain_retrieval` | The full candidate pool and stage diagnostics for a retrieval |

The `search_event_id` a caller receives from `search_products` is the same value
it must carry forward as `retrieval_scope_id` on the three scoped operations. It
is a retrieval-capability handle, not an identity. The `diagnostics` and
`applied_filters` returned with a search are the receipt: what strategy ran,
what was fused, what was granted, and to what `authorized_limit`. A composing
agent gets exactly this typed contract regardless of which transport carried the
call.

A parent agent composing several capabilities sees only this:

```text
                    Workplace assistant
                            |
        +-------------------+-------------------+
        |                   |                   |
   Facilities          Procurement      Mosaic Hybrid Retrieval
                                                |
                                                v
                                       Aurora PostgreSQL
```

It calls `search_products`, carries `search_event_id` forward as
`retrieval_scope_id`, and reads the receipt. That is the entire surface.

## 3. What stays hidden, and what is merely not the caller's problem

Two different guarantees were collapsing into one claim here, and the previous
version of this section asserted more opacity than the service actually keeps.
Splitting the guarantee into what it should have been from the start:

**Genuinely unobservable.** No field on any of the four operations' response
models, at any depth, serializes these, at any diagnostic setting a caller can
request:

- the `tsvector`/`tsquery` mechanics behind the full-text arm;
- the reciprocal rank fusion formula itself — the equation, not its `rrf_k`
  input, which the receipt does return;
- how evidence rows are stored, or their table and column layout.

**Observable, and not the caller's problem anyway.** Everything else this
section used to list as hidden is returned somewhere in the typed contract,
and most of it without a caller even having to ask: `include_diagnostics`
defaults to `True`, so a plain `search_products` call already gets it. A
caller can read that the full-text arm contributed `fts_in_pool` candidates
and the trigram arm `trigram_in_pool`; that the trigram arm's similarity floor
was `trigram_threshold`; that fusion ran with `rrf_k`; that each arm was
capped before fusion at `fts_limit`, `trigram_limit`, and `semantic_limit`,
and the fused pool at `fused_limit`; and whether, and when, the reranker ran,
as `rerank_status`, `rerank_model_id`, and `stage_timings_ms["rerank"]`. The
semantic arm's identity is in the same bucket, and more plainly than the
service's own `candidate_counts` key admits: `search_products` only ever
names that arm the generic `semantic_in_pool`, and its `ef_search` and
`iterative_scan` settings are HNSW-specific terms a caller would have to
already know to read as such — but `explain_retrieval` persists and returns
the same settings under the literal key `hnsw_settings`, so the index family
is not actually held back on that operation. `evidence_id` and `source_uri`
address evidence rows the same way any API returns an identifier for a
resource it just handed over. That is ordinary resource addressing, not a
leak of the storage layout underneath it.

None of that observability is ownership. A caller can read that `rrf_k` is
`60` and still never have had to choose it, implement fusion, or keep it
consistent with the arm caps: the service resolved every one of those values,
enforced every one of them, and persisted the receipt so the run can be
replayed rather than reasoned about after the fact. Inspectable is not the
same claim as "configure this yourself." The capability keeps working,
unchanged from the caller's point of view, if the index type, the fusion
weighting, the rerank provider, or the storage layout changes tomorrow,
because none of those was ever the interface. A library hands over the
pieces and leaves the caller to assemble them. A capability hands over a
receipt and keeps doing the assembly itself, whether or not the caller ever
reads it.

This is also the claim that actually fits the product. The workshop's own UI
puts this same diagnostics JSON two clicks away — the Playground tab, then its
"View retrieval event" disclosure. A composition document asserting that arm
identities, thresholds, and rerank status were opaque would contradict a
surface the workshop hands every participant. The honest claim was always the
stronger one: everything above is inspectable, and none of it is the
composing agent's job to run.

## 4. HTTP / MCP / A2A status, and what composing over A2A would and would not change

```text
              Mosaic Hybrid Retrieval Skill
                 (SKILL.md + registry)
                          |
                canonical typed contract
                          |
      +-------------------+-------------------+
      |                   |                   |
   HTTP / API            MCP                 A2A
      |                   |                   |
  implemented         implemented      documentation profile
                                          not deployed
```

HTTP and MCP are real, running surfaces: `GET /api/tools?surface=skill` serves
the same four capabilities live, and `make mcp-test` exercises the MCP adapter
against them. **A2A is neither.** No A2A endpoint is deployed for this
workshop, and none is provisioned. Section 5 is a documentation profile,
written so the composition story stays concrete instead of hand-waved, not a
claim that it runs anywhere.

Every existing adapter reaches the same `RetrievalService` and
`service/retrieval_scope.py`, reimplements none of filters, arms, fusion,
reranking, or evidence access, and carries no scope policy of its own. An A2A
adapter, if one were ever built, would be bound by the same rule — a
composability boundary, not a transport detail, so it belongs here rather than
in the hosting profile in Section 5. It would have to refuse to: run arbitrary
SQL; bypass eligibility filters; bypass the grant boundary by calling anything
other than `assert_products_in_retrieval_scope`; keep a second copy of
reciprocal rank fusion; widen the candidate pool; or run a second autonomous
reasoning loop, which rules out wrapping the capability in a Strands `Agent`
purely to satisfy protocol machinery, as `strands.multiagent.a2a.A2AServer`
does. Its executor would be a deterministic mapping from an incoming task to a
skill call, nothing more.

> A2A changes who can call the capability. It does not change what the
> capability is allowed to do.

## 5. AgentCore as production boundary only

```text
Aurora PostgreSQL        owns retrieval truth
Bedrock models           provide embeddings, reranking, synthesis
This application         owns tool exposure and grant scope
AgentCore                may host the capability in production
```

Only the bottom row is optional, and it is a hosting decision, not a curriculum
topic. Moving the interface does not move retrieval authority, and it does not
move the grant boundary. This workshop does not deploy an AgentCore Runtime,
does not configure a Gateway, Identity, Memory, or Policy, does not write Cedar,
and does not exercise OTEL or Observability. Those are production concerns for
whoever hosts this capability later, not something a participant does today.

If an A2A adapter were ever built, here is the protocol contract quoted from
the AWS Bedrock AgentCore A2A protocol contract (read 2026-08-26), condensed to
one reference block, plus the protocol-relevant fields of this capability's
Agent Card in that contract's documented shape:

| Fact | Value |
|---|---|
| Transport | JSON-RPC 2.0 over HTTP |
| Discovery | Agent Card served at `/.well-known/agent-card.json` |
| Host / port | `0.0.0.0:9000` — differs from the HTTP and MCP protocol ports |
| Platform | ARM64 container |
| Health | `GET /ping` returns `{"status": "Healthy"}`, or `HealthyBusy` while a session should stay alive |
| Sessions | platform injects `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` |
| Errors | JSON-RPC error codes; AgentCore returns the real HTTP status rather than the specification's HTTP 200 convention, so a client must parse the error body on non-2xx responses |
| Agent Card `protocolVersion` | `0.3.0` |
| Agent Card `preferredTransport` | `JSONRPC` |
| Agent Card `skills[0].id` | `open_retrieval` |

The rest of the Agent Card is ordinary metadata this capability would set, not
an added protocol constraint: `name: "Mosaic Hybrid Retrieval"`,
`description: "Read-only product retrieval over Aurora PostgreSQL full-text,
pg_trgm, and pgvector HNSW with reciprocal rank fusion and managed
reranking"`, `version: "0.2.0"`,
`url: "https://bedrock-agentcore.<region>.amazonaws.com/runtimes/<agent-arn>/invocations/"`,
`capabilities: {"streaming": false}`, `defaultInputModes` and
`defaultOutputModes: ["text"]`, and
`skills[0]: {name: "Open a product retrieval", description: "Return ranked,
source-attributed products with a retrieval receipt and a declared
authorization window", tags: ["retrieval", "postgresql", "product-search"]}`.

Protocol compliance would not be the hard part; what such an adapter must
never do regardless of transport is Section 4's list, not a hosting concern.

If an executable adapter is ever built, it goes in its own package with its
own virtual environment, following the `mcp-server/` precedent, and adds zero
dependencies to the participant runtime — measured: `a2a-sdk` in Strands
1.48.0's supported range resolves to 0.3.26 and pulls 13 further packages,
including protobuf, cryptography, google-auth, and requests, which is not a
cost a 60-minute workshop should pay for an optional reveal.

## No runtime or deployment claims

Nothing above is running. No A2A endpoint exists, none is provisioned, no
AgentCore Runtime, Gateway, Identity, Memory, or Policy has been created for
this workshop, and no dependency for any of it has entered the participant
environment or `mcp-server/`'s isolated one. This document is a deployment
profile, written to make the composition story concrete; it is not evidence
that the story has been built.

## Sources

- [A2A protocol contract, Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-a2a-protocol-contract.html)
- [Deploy A2A servers in AgentCore Runtime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-a2a.html)
