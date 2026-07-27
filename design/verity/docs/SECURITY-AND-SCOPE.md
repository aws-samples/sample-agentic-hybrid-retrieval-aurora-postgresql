# Security and scope

- Synthetic evidence only.
- No real customer, incident, support, or telemetry data.
- No live connectors in the participant path.
- No browser-to-database, browser-to-Bedrock, browser-to-MCP, or browser-to-AgentCore calls.
- Gateway endpoint is invoked from approved backend or workshop utility.
- No OAuth setup by participants.
- ACL checks remain in Aurora retrieval and traversal; Gateway does not replace evidence authorization.
- Gateway transport auth and evidence ACL are separate controls.
- Contract fixtures contain no credentials.
- OpenAPI uses a placeholder server URL in source; release packaging injects the actual static URL.
- No analytics or telemetry in the frontend.
- No remote fonts or vendor-logo assets.
- Transport parity logs must not contain secret headers or tokens.
