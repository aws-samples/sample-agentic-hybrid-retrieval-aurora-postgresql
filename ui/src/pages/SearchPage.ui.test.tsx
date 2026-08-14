// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { CommerceProvider } from "../commerce";
import { showcaseCatalogPage } from "../showcase";
import type { SearchResponse } from "../types";
import { SearchPage } from "./SearchPage";

vi.mock("../api", () => ({
  api: {
    agentStream: vi.fn(),
    search: vi.fn(),
  },
}));

describe("SearchPage comparison", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/search?q=workspace");
    vi.mocked(api.search).mockReset();
    vi.mocked(api.agentStream).mockReset();
    const products = showcaseCatalogPage({}, 0, 5).products;
    const response: SearchResponse = {
      search_event_id: "comparison-test",
      query: "workspace",
      normalized_query: "workspace",
      applied_filters: {},
      results: products,
      diagnostics: null,
    };
    vi.mocked(api.search).mockResolvedValue(response);
  });

  afterEach(cleanup);

  it("uses the checked products as the comparison table columns", async () => {
    render(
      <CommerceProvider>
        <SearchPage />
      </CommerceProvider>,
    );

    const checkboxes = await screen.findAllByRole("checkbox", {
      name: /^Compare /,
    });
    expect(checkboxes).toHaveLength(5);
    expect(
      checkboxes.slice(0, 4).every((checkbox) => (checkbox as HTMLInputElement).checked),
    ).toBe(true);
    expect((checkboxes[4] as HTMLInputElement).disabled).toBe(true);

    fireEvent.click(checkboxes[0]);
    await waitFor(() => {
      expect((checkboxes[0] as HTMLInputElement).checked).toBe(false);
      expect((checkboxes[4] as HTMLInputElement).disabled).toBe(false);
    });
    fireEvent.click(checkboxes[4]);

    const table = screen.getByRole("table");
    const selectedModel = showcaseCatalogPage({}, 0, 5).products[4].model;
    expect(within(table).getByText(selectedModel)).toBeTruthy();
    expect(
      within(table).queryByText(showcaseCatalogPage({}, 0, 5).products[0].model),
    ).toBeNull();
  });
});
