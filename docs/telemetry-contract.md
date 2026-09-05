# Portable telemetry contract

Mosaic ports the telemetry contract from the PostgreSQL conference demo, not
its coffee-specific panels. Aurora PostgreSQL remains the evidence ledger; an
optional OpenTelemetry adapter projects a smaller operational view to Amazon
Bedrock AgentCore Observability.

## Contract map

| Conference concept | Mosaic canonical source | Portable contract |
|---|---|---|
| plan and stage lifecycle | `mosaic.agent_turn`, `mosaic.agent_tool_event` | ordered `retrieve`, `rank`, `reason` stages with active/completed/failed status and duration |
| retrieval run | `mosaic.search_event` | request profile, model and Aurora identity, candidate counts, stage timings, source revision, dataset hash, retrieval fingerprint |
| ranking panel | `mosaic.search_result_event` | exact per-arm RRF contributions, fused/rerank movement, final rank, and served/authorization disposition |
| model panel | agent-session metadata and persisted `usage` | model IDs, input/output/total tokens, stop reason, synthesis latency, turn latency |
| tool audit | `mosaic.agent_tool_event` | tool, outcome, origin, duration, linked search event |
| grounding and approval | evidence and synthesis tool receipts | evidence coverage, deterministic citation-validation outcome, authorization outcome counts |
| trace linkage | existing JSON receipts | `trace_id`, `span_id`, `agent_turn_id`, and `search_event_id` remain separate correlated identifiers |

`GET /api/telemetry/agent-turns/{agent_turn_id}` returns
`mosaic.telemetry.v1`. It joins the persisted rows; it does not recompute
retrieval, rerank candidates, or ask a model to summarize the run.

Candidate disposition is derived from the receipt that already exists:

- `authorized`: inside `retrieval_profile.authorized_limit`;
- `served_not_authorized`: returned to the caller but withheld from downstream
  evidence tools;
- `outside_served_window`: retained in the inspectable fused pool but not
  returned by that search.

This keeps the existing candidate-count vocabulary and retrieval semantics
unchanged.

## Canonical ledger and export boundary

The API timeline is a workshop inspection surface and therefore includes
candidate-level ranking receipts. The AgentCore projection does not. Its
function accepts only:

- aggregate candidate counts;
- aggregate stage timings and total latency;
- rerank and completion status;
- model/token/stop metadata;
- source revision, dataset hash, and retrieval fingerprint;
- explicit Mosaic and OpenTelemetry correlation IDs.

It cannot receive product IDs, SKUs, titles, evidence text, or the full
candidate rows. Prompt and answer content are also disabled by default.

`search_event_id` is never converted into an OpenTelemetry trace ID. Mosaic
stores the generated W3C `trace_id` and `span_id` inside the existing
`diagnostics.telemetry` and `extracted_intent.telemetry` JSON receipts so both
systems can be queried without corrupting either identity model or changing the
fresh-account schema.

## Optional AgentCore adapter

The base Workshop Studio install remains:

```bash
uv sync --frozen
```

That command does not install the AgentCore exporter. An operator can opt in:

```bash
uv sync --extra agentcore-observability
export MOSAIC_AGENTCORE_OBSERVABILITY=true
export MOSAIC_AGENTCORE_CAPTURE_CONTENT=false
```

Then configure the AWS Distro for OpenTelemetry and start the service through
`opentelemetry-instrument` using the external-agent instructions in the
[AgentCore Observability guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-get-started.html).
The Mosaic instrumentation scope is
`opentelemetry.instrumentation.mosaic`, and `session.id` is propagated as
OpenTelemetry baggage.

Set `MOSAIC_AGENTCORE_CAPTURE_CONTENT=true` only in an environment where prompt
and answer export has been approved. AgentCore managed evaluations need
prompt/completion and tool input/output fields to reconstruct evaluable
sessions; the default aggregate-only mode intentionally withholds them. See
[supported telemetry frameworks](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/supported-frameworks-telemetry.html)
and the
[generic custom-agent mapping](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/supported-frameworks-generic.html).

Mosaic configures no exporter in application code. If the flag is false or no
recording OpenTelemetry provider is installed, the adapter is a no-op and
Aurora telemetry continues unchanged.

## AgentCore remains layered and optional

1. **Observability:** supported first. Mosaic stays in its current deployment;
   the same aggregate spans can appear in CloudWatch GenAI Observability.
2. **Evaluations:** optional after approved content capture. Mosaic keeps
   Recall/MRR/nDCG, citation, and authorization assertions deterministic and
   Aurora-owned.
3. **Gateway:** optional projection of existing OpenAPI/MCP tools. It does not
   own retrieval logic or authorization. The boundary is written out in
   [`mcp-interoperability.md`](mcp-interoperability.md) under "The gate is not
   the guard".
4. **Runtime:** optional later. Moving the agent loop does not move the evidence
   ledger or change the telemetry contract. The container and configuration are
   in `deploy/agentcore/`, described in
   [`agentcore-runtime.md`](agentcore-runtime.md).

No AgentCore resource is required or deployed by the workshop. Treat this as
an “observe anywhere” epilogue, not a fourth lab.

## Workshop Studio release guard

The exporter is an optional dependency and `deploy/mosaic-bootstrap.sh` is
unchanged. A source release still requires the normal chain:

1. publish the source commit;
2. repin Workshop Studio with `scripts/repin.py`;
3. verify the source bootstrap and Studio asset remain byte-identical;
4. run `scripts/validate_workshop.py` and the participant-query validator;
5. perform the clean-account deployment rehearsal before claiming release
   readiness.
