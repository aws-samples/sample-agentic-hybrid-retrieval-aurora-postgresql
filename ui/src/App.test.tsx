// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

vi.mock("./components/Shell", () => ({
  Shell: ({ children }: { children: React.ReactNode }) => (
    <main id="main-content" tabIndex={-1}>{children}</main>
  ),
}));
vi.mock("./pages/DiscoverPage", () => ({ DiscoverPage: () => <p>Discover route</p> }));
vi.mock("./pages/CatalogPage", () => ({ CatalogPage: () => <p>Catalog route</p> }));
vi.mock("./pages/SearchPage", () => ({ SearchPage: () => <p>Search route</p> }));
vi.mock("./pages/MosaicStudioPage", () => ({ MosaicStudioPage: () => <p>Studio route</p> }));
vi.mock("./pages/PerformancePage", () => ({ PerformancePage: () => <p>HNSW route</p> }));
vi.mock("./pages/ProductPage", () => ({ ProductPage: () => <p>Product route</p> }));
vi.mock("./pages/RetrievalLabPage", () => ({ RetrievalLabPage: () => <p>Retrieval route</p> }));

afterEach(() => {
  cleanup();
  document.title = "Mosaic";
});

describe("App Labs routes", () => {
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
      expect(document.title).toBe("Vector index at scale | Mosaic");
      expect(document.activeElement).toBe(document.getElementById("main-content"));
    });
  });

  it("redirects the retired Explore route to Retrieval Observatory", async () => {
    window.history.replaceState({}, "", "/mosaic-labs");
    render(<App />);

    await waitFor(() => expect(window.location.pathname).toBe("/labs/retrieval"));
    expect(await screen.findByText("Retrieval route")).toBeTruthy();
  });
});
