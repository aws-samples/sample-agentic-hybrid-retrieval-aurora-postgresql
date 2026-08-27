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

## 3. What remains hidden inside Aurora and retrieval

This is the encapsulation claim, and it is the point of packaging a capability
rather than shipping a library. A caller of any of the four operations never
learns:

- that one candidate arm is PostgreSQL full-text search, or anything about
  `tsvector`/`tsquery` matching;
- that a second arm is `pg_trgm` trigram similarity, or the similarity threshold
  it filters on;
- that a third arm is a pgvector HNSW index, its `ef_search` setting, or that it
  runs an `iterative_scan`;
- the reciprocal rank fusion formula, or the value of `rrf_k`;
- the per-arm candidate cap enforced before fusion, or the size of the bounded
  pool;
- whether, or at what point in the request, the managed reranker was invoked;
- how evidence rows are stored, or how they are addressed for later retrieval.

A caller gets a typed contract: ranked products, a scope handle, a receipt.
Everything on the list above can change — index type, fusion weighting, rerank
provider, storage layout — without a single composing agent noticing, because
none of it is part of what was ever handed over. A library would have handed
over the pieces. A capability hands over the contract and keeps the pieces.

## 4. HTTP / MCP / A2A status

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
workshop, and none is provisioned. What follows in sections 5 is a
documentation profile, written so the composition story stays concrete instead
of hand-waved, not a claim that it runs anywhere.

Every adapter that does exist reaches the same `RetrievalService` and the same
`service/retrieval_scope.py`. None of them reimplements filters, arms, fusion,
reranking, or evidence access, and none of them carries its own scope policy.

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

### What a compliant A2A adapter would have to satisfy

Quoted from the AWS Bedrock AgentCore A2A protocol contract, read 2026-08-26:

- **Transport:** JSON-RPC 2.0 over HTTP.
- **Discovery:** an Agent Card served at `/.well-known/agent-card.json`.
- **Host and port:** `0.0.0.0` on port `9000`, which differs from the HTTP and
  MCP protocol ports.
- **Platform:** an ARM64 container.
- **Health:** `GET /ping` returning `{"status": "Healthy"}`, or `HealthyBusy`
  while a session should stay alive.
- **Sessions:** the platform injects
  `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id`.
- **Errors:** JSON-RPC error codes, and note that AgentCore returns the real
  HTTP status rather than the specification's HTTP 200 convention, so a client
  must parse the error body on non-2xx responses.

An Agent Card for this capability would take the documented shape:

```json
{
  "name": "Mosaic Hybrid Retrieval",
  "description": "Read-only product retrieval over Aurora PostgreSQL full-text, pg_trgm, and pgvector HNSW with reciprocal rank fusion and managed reranking.",
  "version": "0.2.0",
  "url": "https://bedrock-agentcore.<region>.amazonaws.com/runtimes/<agent-arn>/invocations/",
  "protocolVersion": "0.3.0",
  "preferredTransport": "JSONRPC",
  "capabilities": {"streaming": false},
  "defaultInputModes": ["text"],
  "defaultOutputModes": ["text"],
  "skills": [
    {
      "id": "open_retrieval",
      "name": "Open a product retrieval",
      "description": "Return ranked, source-attributed products with a retrieval receipt and a declared authorization window.",
      "tags": ["retrieval", "postgresql", "product-search"]
    }
  ]
}
```

Protocol compliance would not be the hard part. What such an adapter must not
do is:

- no arbitrary SQL;
- no bypassing eligibility filters;
- no bypassing the grant boundary, which means calling
  `assert_products_in_retrieval_scope` rather than reimplementing it;
- no second copy of reciprocal rank fusion;
- no widening of the candidate pool;
- **no second autonomous reasoning loop.** This rules out wrapping the
  capability in a Strands `Agent` purely to satisfy protocol machinery, which
  is what `strands.multiagent.a2a.A2AServer` does. A compliant adapter's
  executor is a deterministic mapping from an incoming task to a skill call.

> A2A changes who can call the capability. It does not change what the
> capability is allowed to do.

If an executable adapter is ever built, it goes in its own package with its own
virtual environment, following the `mcp-server/` precedent, and adds zero
dependencies to the participant runtime. The reason is measured: `a2a-sdk` in
Strands 1.48.0's supported range resolves to 0.3.26 and pulls 13 further
packages, including protobuf, cryptography, google-auth, and requests. That is
not a cost a 60-minute workshop should pay for an optional reveal.

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
