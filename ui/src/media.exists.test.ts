import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { domainIllustration, productImage } from "./media";
import type { Domain, ProductSummary } from "./types";

const publicDir = fileURLToPath(new URL("../public", import.meta.url));

describe("media asset paths", () => {
  it("only returns local images that exist in public/", () => {
    // Vite serves index.html with a 200 for a missing asset, so a deleted file
    // renders as an empty box rather than an error.
    const domains: Domain[] = ["consumer_electronics", "running_fitness", "home_office"];
    const paths = [
      ...domains.map(domainIllustration),
      productImage({ image_url: null } as ProductSummary),
    ];
    const missing = paths.filter((path) => !existsSync(publicDir + path));
    expect(missing).toEqual([]);
  });
});
