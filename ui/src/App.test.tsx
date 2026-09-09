// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { SiteFooter } from "./components/SiteFooter";

vi.mock("./components/Shell", () => ({
  Shell: ({ children }: { children: React.ReactNode }) => (
    <main id="main-content" tabIndex={-1}>{children}</main>
  ),
}));
vi.mock("./pages/DiscoverPage", () => ({ DiscoverPage: () => <p>Discover route</p> }));
vi.mock("./pages/CatalogPage", () => ({
  CatalogPage: () => <><p>Catalog route</p><input aria-label="Draft search" /></>,
}));
vi.mock("./pages/MosaicStudioPage", () => ({ MosaicStudioPage: () => <p>Studio route</p> }));
vi.mock("./pages/ScaleInspectorPage", () => ({ ScaleInspectorPage: () => <p>HNSW route</p> }));
vi.mock("./pages/ProductPage", () => ({ ProductPage: () => <p>Product route</p> }));
vi.mock("./pages/PlaygroundPage", () => ({ PlaygroundPage: () => <p>Retrieval route</p> }));
vi.mock("./pages/SessionMemoryPage", () => ({ SessionMemoryPage: () => <p>Memory route</p> }));

beforeEach(() => {
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  document.title = "Mosaic";
});

describe("App Labs routes", () => {
  it.each([
    ["Hybrid retrieval", "/labs/retrieval", "Retrieval route"],
    ["Scale & HNSW", "/mosaic-labs/hnsw", "HNSW route"],
    ["Session & Memory", "/mosaic-labs/memory", "Memory route"],
  ])("opens the current %s surface from the footer", async (label, path, marker) => {
    window.history.replaceState({}, "", "/catalog");
    render(<><SiteFooter /><App /></>);
    await screen.findByText("Catalog route");
    const footer = within(screen.getByRole("contentinfo"));
    fireEvent.click(footer.getByRole("link", { name: label }));
    expect(await screen.findByText(marker)).toBeTruthy();
    expect(window.location.pathname).toBe(path);
    await waitFor(() => expect(document.title).toBe(`${label} | Mosaic`));
    expect(footer.queryByRole("link", { name: "Catalog studio" })).toBeNull();
  });

  it("takes old Catalog Studio bookmarks to the current Playground", async () => {
    window.history.replaceState({}, "", "/mosaic-labs/studio");
    render(<App />);
    expect(await screen.findByText("Retrieval route")).toBeTruthy();
    expect(window.location.pathname).toBe("/labs/retrieval");
    expect(screen.queryByText("Studio route")).toBeNull();
  });

  it.each([
    ["/shop", "/catalog"],
    ["/playground", "/labs/retrieval"],
    ["/mosaic-labs", "/labs/retrieval"],
    ["/inspiration", "/labs/retrieval"],
    ["/labs/performance", "/mosaic-labs/hnsw"],
  ])("preserves the saved request and section through %s", async (alias, destination) => {
    const query = "?q=clearer+calls&max_price_cents=30000&event=9614ed9b-4ceb-4aad-9276-4e69af2231b9&view=bench";
    window.history.replaceState({}, "", `${alias}${query}#details`);
    render(<App />);
    await waitFor(() => expect(window.location.pathname).toBe(destination));
    expect(window.location.search).toBe(query);
    expect(window.location.hash).toBe("#details");
  });
  it("preserves a draft on query changes and resets scroll and focus for a new page", async () => {
    window.history.replaceState({}, "", "/catalog");
    render(<App />);
    const input = await screen.findByLabelText("Draft search") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "quiet keyboard" } });

    await act(async () => window.history.pushState({}, "", "/catalog?domain=home_office"));
    expect(screen.getByLabelText("Draft search")).toBe(input);
    expect(input.value).toBe("quiet keyboard");
    expect(window.scrollTo).not.toHaveBeenCalled();

    await act(async () => window.history.pushState({}, "", "/"));
    expect(await screen.findByText("Discover route")).toBeTruthy();
    expect(window.scrollTo).toHaveBeenCalledWith({ top: 0, left: 0, behavior: "instant" });
    expect(document.activeElement).toBe(document.getElementById("main-content"));
  });

  it("sets a route-specific document title", async () => {
    window.history.replaceState({}, "", "/catalog");
    render(<App />);

    expect(await screen.findByText("Catalog route")).toBeTruthy();
    await waitFor(() => expect(document.title).toBe("Shop | Mosaic"));
  });

  it("serves HNSW from the canonical Mosaic Labs route", async () => {
    window.history.replaceState({}, "", "/mosaic-labs/hnsw");
    render(<App />);

    expect(await screen.findByText("HNSW route")).toBeTruthy();
  });

  it("redirects the legacy performance route to the canonical Labs route", async () => {
    window.history.replaceState({}, "", "/labs/performance");
    render(<App />);

    await waitFor(() => expect(window.location.pathname).toBe("/mosaic-labs/hnsw"));
    expect(await screen.findByText("HNSW route")).toBeTruthy();
    await waitFor(() => {
      expect(document.title).toBe("Scale & HNSW | Mosaic");
      expect(document.activeElement).toBe(document.getElementById("main-content"));
    });
  });

  it("redirects the retired Explore route to the Playground", async () => {
    window.history.replaceState({}, "", "/mosaic-labs");
    render(<App />);

    await waitFor(() => expect(window.location.pathname).toBe("/labs/retrieval"));
    expect(await screen.findByText("Retrieval route")).toBeTruthy();
  });

  // Every name the navigation prints has to be typeable, or the catch-all sends
  // a participant to Discover with no explanation. /shop used to do exactly that
  // while /discover resolved and /playground redirected.
  it.each([
    ["/shop", "/catalog", "Catalog route"],
    ["/playground", "/labs/retrieval", "Retrieval route"],
  ])("resolves the navigation name %s to %s", async (typed, canonical, marker) => {
    window.history.replaceState({}, "", typed);
    render(<App />);

    await waitFor(() => expect(window.location.pathname).toBe(canonical));
    expect(await screen.findByText(marker)).toBeTruthy();
  });

  it("sends an unroutable path to Discover", async () => {
    window.history.replaceState({}, "", "/not-a-surface");
    render(<App />);

    await waitFor(() => expect(window.location.pathname).toBe("/"));
    expect(await screen.findByText("Discover route")).toBeTruthy();
  });
});
