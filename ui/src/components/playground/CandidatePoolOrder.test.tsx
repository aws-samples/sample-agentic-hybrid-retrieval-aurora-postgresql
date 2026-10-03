// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { api } from "../../api";
import { fixtureCatalogPage } from "../../testProducts";
import type { RetrievalRunResponse, SearchResponse } from "../../types";
import { CandidatePoolOrder } from "./CandidatePoolOrder";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("shows a combined runner-up outside the displayed results without granting its product content", async () => {
  const product = fixtureCatalogPage({}, 0, 1).products[0];
  const response = { search_event_id: "saved-search", results: [product], diagnostics: { rerank_status: "applied" } } as SearchResponse;
  vi.spyOn(api, "retrievalEvent").mockResolvedValue({ candidates: [
    { product_id: product.product_id, fused_rank: 4, result_rank: 1 },
    { product_id: 9999999, fused_rank: 2, result_rank: 22 },
  ] } as RetrievalRunResponse);
  const search = vi.spyOn(api, "search");
  render(<CandidatePoolOrder response={response} />);
  const row = await screen.findByRole("row", { name: "Product 9999999 #2 #22 No" });
  expect(within(row).queryByRole("link")).toBeNull();
  const rows = () => screen.getAllByRole("row").slice(1).map((r) => r.textContent);
  expect(rows()[0]).toContain("9999999");
  fireEvent.click(screen.getByRole("button", { name: "Final order" }));
  expect(rows()[1]).toContain("9999999");
  expect(search).not.toHaveBeenCalled();
});

it("reports an unreadable pool instead of presenting the displayed slice as complete", async () => {
  vi.spyOn(api, "retrievalEvent").mockRejectedValue(new Error("record unavailable"));
  render(<CandidatePoolOrder response={{ search_event_id: "missing", results: [], diagnostics: null } as unknown as SearchResponse} />);
  expect((await screen.findByRole("alert")).textContent).toContain("Full candidate pool unavailable");
  expect(screen.queryByRole("table")).toBeNull();
});
