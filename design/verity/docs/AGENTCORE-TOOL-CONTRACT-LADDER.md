# AgentCore tool-contract ladder

## Decision

Use **Amazon Bedrock AgentCore Gateway** as a short Module 3 capstone.

Do not use AgentCore Runtime, Identity, Policy, Memory, Evaluations, Browser, or Code Interpreter in the participant core.

## Why Gateway fits

The session already has stable HTTP tool endpoints and a local MCP adapter. Gateway demonstrates that existing APIs can be exposed as managed MCP tools without moving retrieval logic out of Aurora PostgreSQL.

## Ladder

```text
canonical Python service
  ├── HTTP/FastAPI
  ├── local stdio MCP
  └── AgentCore Gateway OpenAPI target
```

## Contract requirements

- `contract_version` in every response;
- stable `operationId`;
- JSON only;
- simple schemas;
- no adapter-specific ranking behavior;
- no hidden ACL changes;
- no Gateway-specific candidate selection;
- no direct database call from adapters;
- transport metadata stored in `proof.transport_invocations`.

## AgentCore OpenAPI considerations

- OpenAPI 3.0/3.1 (Swagger 2.0 unsupported);
- every operation exposed as a tool has an `operationId`;
- the deployed schema uses a valid static server URL;
- `application/json`;
- avoid `oneOf`, `anyOf`, and `allOf`;
- configure auth outside the schema;
- the workshop target is pre-provisioned.

## Exposed tool names

Gateway prefixes the target name onto the `operationId`, delimited by three underscores:

```text
${targetName}___${operationId}
```

Target `verity-openapi-tools` therefore exposes `search_evidence` as
`verity-openapi-tools___search_evidence`.

Reference: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-tool-naming.html

The bare `operationId` is the derivation input, not the exposed name. HTTP and local stdio
MCP use the bare `operationId`; only the Gateway transport is prefixed. This is a
transport artifact, not a contract difference.

Two consequences for this session:

- Parity checks must strip the `${targetName}___` prefix before comparing tool names.
- An agent's tool-choice prompt sees the prefixed name over Gateway, so tool-selection
  instructions must not hardcode bare operation IDs.

`operationId` stability is unchanged: renaming one is a contract-version change.

## Inbound authorization

`authorizerType` is required on `CreateGateway`, but `NONE` is valid alongside
`CUSTOM_JWT`, `AWS_IAM`, and `AUTHENTICATE_ONLY`. `authorizerConfiguration` is required
only for `CUSTOM_JWT`.

Reference: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_CreateGateway.html

`NONE` or `AWS_IAM` is the workshop path of least resistance. The release author chooses;
the participant does not.

The participant's Module 3 call is authorized by the workshop utility or approved backend,
which holds the inbound credential. The browser never calls Gateway directly, per
`SECURITY-AND-SCOPE.md`. Participants supply no credential.

## Workshop action

Participants verify portability, not infrastructure.

Recommended call set:

1. `search_evidence`
2. `answer_with_citations`

## Semantic parity

Normalize out:

- invocation ID;
- transport;
- transport trace ID;
- the Gateway `${targetName}___` tool-name prefix;
- timestamps;
- stage latency;
- generated run ID when comparing fresh runs.

Compare:

- contract version;
- evidence IDs and order;
- text/vector/fuzzy positions;
- RRF score within tolerance;
- ACL-visible set;
- relationship verdicts;
- citation evidence IDs;
- citation quote hashes.

## Failure behavior

- If Gateway is unavailable, run Module 3 against the captured responses in
  `fixtures/captures/` (`agentcore.json`, `http.json`, `mcp.json`) or against local MCP.
  The parity claim holds on replay; label the run as replayed.
- Modules 1 and 2 are independent.
- Never imply that a successful Gateway call validates Aurora performance.
