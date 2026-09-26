// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../api";
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
});
