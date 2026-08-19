import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

const API_TARGET = process.env.CATALOG_API_PROXY ?? "http://127.0.0.1:8000";

/** What `GET /api/health` reports in service/main.py. Nothing else answers this. */
const MOSAIC_SERVICE = "catalog-hybrid-retrieval";

/**
 * Refuse to proxy quietly to something that is not Mosaic.
 *
 * The proxy target defaults to port 8000, and anything else listening there
 * inherits every `/api` call the storefront makes. That has happened: a
 * different application on 8000 answered `POST /api/search` with HTTP 200 and
 * its own catalog, so the storefront rendered another product set, and the
 * places that read `results` or `signals` off the response failed with an
 * unexplained error instead of saying what was wrong.
 *
 * A wrong-application response is harder to debug than a refused connection
 * precisely because it succeeds. So the target is identified once at startup,
 * and a target that cannot be identified is called out by name along with the
 * variable that redirects it.
 */
function verifyApiTarget(): Plugin {
  return {
    name: "mosaic-verify-api-target",
    apply: "serve",
    configureServer(server) {
      const complain = (detail: string) => {
        server.config.logger.error(
          `\n  Mosaic API check failed at ${API_TARGET}\n`
          + `  ${detail}\n`
          + "  Every /api request from this dev server goes to that address.\n"
          + `  Point it somewhere else with CATALOG_API_PROXY, for example:\n`
          + "    export CATALOG_API_PROXY=http://127.0.0.1:8010\n",
          { timestamp: true },
        );
      };

      server.httpServer?.once("listening", () => {
        void (async () => {
          try {
            const response = await fetch(`${API_TARGET}/api/health`, {
              signal: AbortSignal.timeout(4000),
            });
            if (!response.ok) {
              complain(`GET /api/health answered HTTP ${response.status}.`);
              return;
            }
            const health = (await response.json()) as { service?: unknown };
            if (health.service !== MOSAIC_SERVICE) {
              complain(
                `Something is listening, but it is not Mosaic: /api/health reports `
                + `service ${JSON.stringify(health.service)} rather than `
                + `"${MOSAIC_SERVICE}". Its responses would be served as Mosaic's.`,
              );
              return;
            }
            server.config.logger.info(
              `  Mosaic API verified at ${API_TARGET}`,
              { timestamp: true },
            );
          } catch (cause) {
            complain(
              `Nothing answered: ${cause instanceof Error ? cause.message : String(cause)}`,
            );
          }
        })();
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), verifyApiTarget()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": {
        target: API_TARGET,
        changeOrigin: true,
        // Without this a dead API surfaces as a bare HTTP 500 with no body, so
        // the browser reports "Request failed with HTTP 500" and names nothing.
        configure: (proxy) => {
          proxy.on("error", (error, _request, response) => {
            if (!("writeHead" in response)) return;
            response.writeHead(502, { "Content-Type": "application/json" });
            response.end(JSON.stringify({
              detail:
                `The Mosaic API at ${API_TARGET} did not answer (${error.message}). `
                + "Start it, or set CATALOG_API_PROXY to its address.",
            }));
          });
        },
      },
    },
  },
});
