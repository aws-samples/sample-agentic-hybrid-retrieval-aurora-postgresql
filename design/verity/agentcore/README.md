# AgentCore Gateway release-author notes

This directory contains the OpenAPI contract used to create a pre-provisioned Gateway target.

## Workshop rule

Participants do not create or configure Gateway resources.

## Release-author flow

1. Deploy the Verity HTTP API at a static HTTPS endpoint.
2. Copy `contracts/openapi/verity-tools.openapi.yaml`.
3. Replace the placeholder `servers[0].url`.
4. Validate the OpenAPI document.
5. Create or update the AgentCore Gateway.
6. Add the OpenAPI target.
7. Configure inbound and outbound authorization.
8. Invoke `search_evidence`.
9. Capture the Gateway response.
10. Run `scripts/verify_contract_parity.py`.
11. Record the Gateway resource/target IDs in the release receipt, not in source.

## Tool names

Gateway does **not** expose the bare `operationId`. It prefixes the target name, using
three underscores as the delimiter:

```text
${targetName}___${operationId}
```

With the target named `verity-openapi-tools`, `search_evidence` is exposed to an MCP
client as `verity-openapi-tools___search_evidence`.

Reference: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-tool-naming.html

The OpenAPI target page says the `operationId` "is used as the tool name in the MCP
interface". That describes the derivation, not the exposed name. The naming page is
authoritative and warns explicitly to account for the discrepancy between the tool name
visible through MCP and the tool name itself.

Consequences:

- Any parity check comparing tool names across HTTP, local stdio MCP, and Gateway must
  strip the `${targetName}___` prefix before comparing. HTTP and stdio MCP use the bare
  `operationId`; only Gateway is prefixed.
- An agent's tool-choice prompt sees the prefixed name. Tool-selection instructions that
  hardcode bare operation IDs will not match over the Gateway transport.
- The prefix is a transport artifact, not a contract change. Normalize it out; do not
  record it as a contract difference.

`operationId` values remain contract-stable. Do not rename them without a
contract-version change.

## What participants actually see

Resolved MCP tool names for the pre-provisioned target. Use this list to sanity-check the
Gateway target after creation.

| operationId | Exposed MCP tool name |
| --- | --- |
| `decompose_question` | `verity-openapi-tools___decompose_question` |
| `search_evidence` | `verity-openapi-tools___search_evidence` |
| `follow_evidence_links` | `verity-openapi-tools___follow_evidence_links` |
| `compare_sources` | `verity-openapi-tools___compare_sources` |
| `explain_ranking` | `verity-openapi-tools___explain_ranking` |
| `synthesize_cited_answer` | `verity-openapi-tools___synthesize_cited_answer` |
| `answer_with_citations` | `verity-openapi-tools___answer_with_citations` |

If the target is renamed, every exposed name changes. The contract does not.

## Inbound authorization

`authorizerType` is required on `CreateGateway`, but `NONE` is a valid value alongside
`CUSTOM_JWT`, `AWS_IAM`, and `AUTHENTICATE_ONLY`. `authorizerConfiguration` is required
only when `authorizerType` is `CUSTOM_JWT`. Inbound OAuth/JWT is therefore not a
precondition for having a Gateway at all.

Reference: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_CreateGateway.html

For a workshop the path of least resistance is `NONE` or `AWS_IAM`. The release author
makes this call; the participant never sees it and never configures it.

How the participant's Module 3 call is authorized:

- The workshop utility or approved backend holds the inbound credential and invokes the
  Gateway endpoint.
- The browser never calls Gateway directly, consistent with `docs/SECURITY-AND-SCOPE.md`.
- Participants supply no credential and perform no OAuth setup.

Gateway transport auth and evidence ACL remain separate controls. Inbound auth decides
who may call the tool; Aurora still decides which evidence is visible.

## Offline fallback

If the Gateway is unreachable, Module 3 still completes. Run the portability comparison
against the captured Gateway response in `fixtures/captures/agentcore.json` alongside
`http.json` and `mcp.json`. The captured responses carry the same `contract_version` and
evidence set, so the parity claim holds without a live call. Label the run as replayed.
