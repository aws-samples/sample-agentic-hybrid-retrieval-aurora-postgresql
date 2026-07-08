import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const API_URL = process.env.RETRIEVAL_API_URL || "http://localhost:8000";

async function post(path: string, payload: unknown) {
  const resp = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!resp.ok) throw new Error(`API ${path} failed: ${resp.status}`);
  return resp.json();
}

const server = new McpServer({ name: "agentic-hybrid-retrieval", version: "0.1.0" });

server.tool(
  "search_evidence",
  {
    query: z.string(),
    sourceSystems: z.array(z.string()).optional(),
    projectKey: z.string().optional(),
    limit: z.number().default(8)
  },
  async ({ query, sourceSystems, projectKey, limit }) => {
    const result = await post("/v1/search", { query, source_systems: sourceSystems, project_key: projectKey, limit });
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  }
);

server.tool(
  "answer_question",
  {
    question: z.string(),
    limit: z.number().default(8)
  },
  async ({ question, limit }) => {
    const result = await post("/v1/agent/answer", { question, limit });
    return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
  }
);

await server.connect(new StdioServerTransport());
