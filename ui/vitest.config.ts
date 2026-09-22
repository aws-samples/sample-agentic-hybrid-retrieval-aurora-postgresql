import { defineConfig, mergeConfig } from "vitest/config";
import { searchForWorkspaceRoot } from "vite";
import { fileURLToPath } from "node:url";

import viteConfig from "./vite.config.ts";

/**
 * Vitest reads this file in preference to vite.config.ts, so the Vite build
 * never sees a `test` key its own types reject.
 */
export default mergeConfig(
  viteConfig,
  defineConfig({
    server: {
      fs: {
        allow: [searchForWorkspaceRoot(process.cwd()), fileURLToPath(new URL("../scripts", import.meta.url))],
      },
    },
    test: {
      // CatalogPage's paced reveals await several 5 s windows inside one test;
      // vitest's default per-test ceiling is also 5 s, so a loaded runner would
      // report a generic timeout instead of the missing element the assertion
      // names. The ceiling sits above the longest legitimate multi-reveal test.
      testTimeout: 15_000,
    },
  }),
);
