import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

import { registerTools } from "./server.generated.js";

const API_URL = (process.env.RETRIEVAL_API_URL || "http://localhost:8000").replace(/\/$/, "");

async function request(path: string, init?: RequestInit): Promise<unknown> {
  const headers = new Headers(init?.headers);
  headers.set("X-Workbench-Transport", "stdio_mcp");
  headers.set("X-Request-ID", `req-mcp-${crypto.randomUUID()}`);
  const response = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (!response.ok) {
    const detail = (await response.text()).slice(0, 1000);
    throw new Error(`API ${path} failed with HTTP ${response.status}: ${detail}`);
  }
  return response.json();
}

async function post(path: string, payload: Record<string, unknown>): Promise<unknown> {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

function wrap(result: unknown) {
  return { content: [{ type: "text" as const, text: JSON.stringify(result, null, 2) }] };
}

const server = new McpServer({
  name: "verity-incident-evidence",
  version: "1.0.0"
});

registerTools(server, post, wrap);

await server.connect(new StdioServerTransport());
