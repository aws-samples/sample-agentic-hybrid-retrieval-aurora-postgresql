import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const pageUrl = new URL("./DiscoverPage.tsx", import.meta.url);
const publicDir = fileURLToPath(new URL("../../public", import.meta.url));

async function imagePathsInDiscoverPage(): Promise<string[]> {
  const source = await readFile(fileURLToPath(pageUrl), "utf8");
  return [...source.matchAll(/"(\/assets\/images\/[^"]+)"/g)].map((match) => match[1]);
}

describe("DiscoverPage media", () => {
  it("references only images that exist in public/", async () => {
    // Three landing images were renamed during the photography swap. Vite
    // answers a missing asset with the SPA index.html and a 200, so a broken
    // hero renders as an empty box instead of failing the build.
    const paths = await imagePathsInDiscoverPage();
    expect(paths.length).toBeGreaterThan(0);

    const missing = paths.filter((path) => !existsSync(publicDir + path));
    expect(missing).toEqual([]);
  });
});
