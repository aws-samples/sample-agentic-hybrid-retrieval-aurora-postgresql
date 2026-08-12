import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import mediaManifest from "../../data/media/asset_labels_120.json";

const publicDir = fileURLToPath(new URL("../public", import.meta.url));

describe("media asset paths", () => {
  it("only maps products to images that exist in public/", async () => {
    // Retiring a photograph (a trademark is spotted late, say) leaves the
    // mapping pointing at a deleted file. Vite serves index.html with a 200
    // for a missing asset, so the product grid renders empty boxes and the
    // regex-shaped tests in media.test.ts still pass.
    const source = await readFile(
      fileURLToPath(new URL("./media.ts", import.meta.url)),
      "utf8",
    );
    const paths = [...source.matchAll(/\$\{ASSETS\}(\/[\w/-]+\.webp)/g)].map(
      (match) => "/assets/images" + match[1],
    );
    expect(paths.length).toBeGreaterThan(0);

    const missing = paths.filter((path) => !existsSync(publicDir + path));
    expect(missing).toEqual([]);
  });

  it("ships every premium cohort catalog image referenced by the manifest", () => {
    const installed = mediaManifest.products.filter((product) => product.catalog_installed);
    const missing = installed
      .map((product) => product.catalog_runtime_path)
      .filter((path) => !existsSync(publicDir + path));

    expect(installed).toHaveLength(120);
    expect(missing).toEqual([]);
  });
});
