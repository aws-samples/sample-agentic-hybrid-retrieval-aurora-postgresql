import { execFileSync } from "node:child_process";
import { describe, expect, it } from "vitest";
import { SOURCE_REPOSITORY_URL } from "../navigation";
import { RETRIEVAL_CONNECTION_GUIDE } from "./RetrievalTakeawayLinks";

describe("RETRIEVAL_CONNECTION_GUIDE", () => {
  it("opens the MCP guide at the commit the app was built from, as the lab guide's links do", () => {
    const head = execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim();

    expect(RETRIEVAL_CONNECTION_GUIDE).toBe(
      `${SOURCE_REPOSITORY_URL}/blob/${head}/docs/mcp-interoperability.md`,
    );
  });
});
