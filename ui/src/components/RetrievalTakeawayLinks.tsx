export const RETRIEVAL_CONNECTION_GUIDE = "https://github.com/aws-samples/sample-agentic-hybrid-retrieval-aurora-postgresql/blob/main/docs/mcp-interoperability.md";

export function RetrievalTakeawayLinks() {
  return (
    <p className="labs-contract-note">
      Read more: <a href="https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/" target="_blank" rel="noreferrer">MCP tool permissions</a>
      {" · "}<a href="https://blog.modelcontextprotocol.io/posts/2025-11-03-using-server-instructions/" target="_blank" rel="noreferrer">MCP workflow instructions</a>
      {" · "}<a href="https://agentskills.io/home" target="_blank" rel="noreferrer">Agent Skills overview</a>
      {" · "}<a href="https://agentskills.io/specification" target="_blank" rel="noreferrer">Skills specification</a>
    </p>
  );
}
