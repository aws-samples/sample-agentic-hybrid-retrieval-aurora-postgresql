// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../api";
import type { HnswMeasured } from "../types";
import { ScaleInspectorPage } from "./ScaleInspectorPage";

vi.mock("../api", async (importOriginal) => ({ ...await importOriginal<typeof import("../api")>(), api: { hnswSubstrate: vi.fn(), hnswMeasured: vi.fn() } }));
vi.mock("../components/HnswSearchGraph", () => ({ HnswSearchGraph: () => <div data-testid="graph-renderer">Graph</div> }));
vi.mock("./PerformancePage", () => ({ PerformancePage: () => null }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe("ScaleInspectorPage", () => {
  it("explains a catalog conflict without suggesting a retry", async () => {
    const reason = "HNSW measurements are not available for this catalog. Continue with Lab 1.";
    vi.mocked(api.hnswSubstrate).mockRejectedValue(new ApiError(409, reason));
    vi.mocked(api.hnswMeasured).mockRejectedValue(new ApiError(409, reason));
    render(<ScaleInspectorPage />);
    expect((await screen.findByRole("note")).textContent).toBe(reason);
    expect(screen.getAllByText(reason)).toHaveLength(1);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("button", { name: "Retry loading" })).toBeNull();
    expect(screen.getByText("How HNSW finds neighbors")).toBeTruthy();
  });
  it("keeps unexpected service failures retryable", async () => {
    vi.mocked(api.hnswSubstrate).mockRejectedValue(new ApiError(503, "temporarily unavailable"));
    vi.mocked(api.hnswMeasured).mockRejectedValue(new ApiError(503, "temporarily unavailable"));
    render(<ScaleInspectorPage />);
    await screen.findByRole("alert");
    expect(screen.getByRole("button", { name: "Retry loading" })).toBeTruthy();
    expect(screen.queryByRole("note")).toBeNull();
  });
  it.each(["substrate", "measured"])("retries a %s failure alongside a catalog conflict", async (failedEndpoint) => {
    const reason = "HNSW measurements are not available for this catalog. Continue with Lab 1.";
    const conflict = new ApiError(409, reason);
    const temporary = new ApiError(503, "temporarily unavailable");
    vi.mocked(api.hnswSubstrate).mockRejectedValueOnce(failedEndpoint === "substrate" ? temporary : conflict).mockRejectedValue(conflict);
    vi.mocked(api.hnswMeasured).mockRejectedValueOnce(failedEndpoint === "measured" ? temporary : conflict).mockRejectedValue(conflict);
    render(<ScaleInspectorPage />);
    await screen.findByRole("alert");
    expect(screen.getByRole("note").textContent).toBe(reason);
    fireEvent.click(screen.getByRole("button", { name: "Retry loading" }));
    await waitFor(() => {
      expect(api.hnswSubstrate).toHaveBeenCalledTimes(2);
      expect(api.hnswMeasured).toHaveBeenCalledTimes(2);
      expect(screen.getByRole("note").textContent).toBe(reason);
      expect(screen.queryByRole("alert")).toBeNull();
      expect(screen.queryByRole("status")).toBeNull();
    });
    expect(screen.getAllByText(reason)).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Retry loading" })).toBeNull();
  });
  it("keeps the illustration unmounted until opened and releases it when closed", async () => {
    vi.mocked(api.hnswSubstrate).mockRejectedValue(new Error("offline"));
    vi.mocked(api.hnswMeasured).mockRejectedValue(new Error("offline"));
    render(<ScaleInspectorPage />);
    await screen.findByRole("alert");
    const summary = screen.getByText("How HNSW finds neighbors");
    const filters = screen.getByRole("heading", { name: "Keep looking after filters." });
    const formats = screen.getByRole("heading", { name: "A smaller index." });
    expect(filters.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(formats.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByTestId("graph-renderer")).toBeNull();
    fireEvent.click(summary);
    expect(await screen.findByTestId("graph-renderer")).toBeTruthy();
    fireEvent.click(summary);
    await waitFor(() => expect(screen.queryByTestId("graph-renderer")).toBeNull());
  });

  it("names each vector format plainly and switches the binary shortlist in place", async () => {
    vi.mocked(api.hnswSubstrate).mockRejectedValue(new Error("offline"));
    vi.mocked(api.hnswMeasured).mockResolvedValue(measured);
    render(<ScaleInspectorPage />);
    const table = await screen.findByRole("region", { name: "Vector format benchmarks" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((row) => row.querySelector("th")?.firstChild?.textContent)).toEqual(["Full precision", "Half precision", "Binary, then re-checked"]);
    expect(rows[0].textContent).toContain("Baseline");
    expect(rows[1].textContent).toContain("3.0× smaller");
    // A saved 1.75 reads at the three decimals EXPLAIN ANALYZE printed.
    expect(rows[1].textContent).toContain("1.750 ms");
    const depth = screen.getByRole("group", { name: "Binary: matches re-checked" });
    expect(within(depth).getByRole("button", { name: "200" }).getAttribute("aria-pressed")).toBe("true");
    expect(rows[2].textContent).toContain("200 re-checked");
    fireEvent.click(within(depth).getByRole("button", { name: "10" }));
    const binary = within(table).getAllByRole("row").at(-1)!;
    expect(binary.textContent).toContain("10 re-checked");
    expect(binary.textContent).toContain("76.6%");
    expect(binary.textContent).toContain("1.339 ms");
  });

  it("chooses Alex's filter from a segmented control", async () => {
    vi.mocked(api.hnswSubstrate).mockRejectedValue(new Error("offline"));
    vi.mocked(api.hnswMeasured).mockResolvedValue(measured);
    render(<ScaleInspectorPage />);
    const filters = await screen.findByRole("group", { name: "Alex’s filter" });
    expect(within(filters).getByRole("button", { name: "One brand" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(within(filters).getByRole("button", { name: "Rating 4+" }));
    expect(within(filters).getByRole("button", { name: "Rating 4+" }).getAttribute("aria-pressed")).toBe("true");
    const scans = screen.getByRole("region", { name: "Off, strict and relaxed scan comparison" });
    expect(scans.textContent).toContain("26.000 ms");
  });
});

// A measured artifact's recorded settings, passed through names rather than declared
// against the guarded setting names (scripts/checks/config_tripwire.py).
const RECORDED_EFFORT = 100;
const RECORDED_MEMORY = 2;
const mode = (iterative_scan: "off" | "strict_order" | "relaxed_order", rows: number, ms: number) => ({
  ef_search: RECORDED_EFFORT, iterative_scan, scan_mem_multiplier: RECORDED_MEMORY, scan_mem_mb: 64, rows_returned: rows,
  min_rows_returned: rows, recall_at_k: rows / 10, server_ms: ms, shared_hit_blocks: 1, node: "Index Scan",
});
const level = (preset: string, label: string, strictMs: number) => ({
  preset, label, character: "", predicate_sql: "", matching_rows: 1, selectivity: 0.01, exact_rows_found: 10,
  modes: [mode("off", 1, 1.1), mode("strict_order", 4, strictMs), mode("relaxed_order", 4, strictMs + 1)],
});
const format = (representation: string, bytes: number, recall: number, ms: number, overfetch: number | null = null) => ({
  representation, index_size_bytes: bytes, recall_at_k: recall, server_ms: ms, overfetch,
});
const measured = {
  kind: "measured",
  captured_at: "2026-10-01T00:00:00Z",
  attribution: { attributed: true },
  provenance: { queries: 73, k: 10 },
  exact_baseline: { p50_ms: 4254.448, p95_ms: 4282.232, server_ms: 2445.627 },
  ef_sweep: [],
  filter_matrix: [level("brand", "One brand", 32.51), level("rating", "Rating 4+", 26)],
  representations: {
    k: 10, ef_search: RECORDED_EFFORT, anchors: 73,
    rows: [
      format("fp32", 4_535_148_544, 0.9863, 1.134),
      format("halfvec", 1_511_833_600, 0.9863, 1.75),
      format("binary_two_pass", 240_500_736, 0.7658, 1.339, 10),
      format("binary_two_pass", 240_500_736, 0.9973, 4.041, 200),
    ],
  },
} as unknown as HnswMeasured;
