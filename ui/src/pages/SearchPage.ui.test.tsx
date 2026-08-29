// @vitest-environment jsdom

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { CommerceProvider } from "../commerce";
import { showcaseCatalogPage } from "../showcase";
import type { AgentResponse, SearchResponse } from "../types";
import { SearchPage } from "./SearchPage";

vi.mock("../api", () => ({
  api: {
    agentStream: vi.fn(),
    search: vi.fn(),
  },
}));

function searchResponse(
  query: string,
  results = showcaseCatalogPage({}, 0, 5).products,
): SearchResponse {
  return {
    search_event_id: `search-${query}`,
    query,
    normalized_query: query,
    applied_filters: {},
    results,
    diagnostics: null,
  };
}

const agentResponse: AgentResponse = {
  agent_run_id: "agent-search",
  question: "What should I buy?",
  answer: "No recommendation was needed.",
  plan: [],
  recommendations: [],
  citations: [],
  trace: [],
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

describe("SearchPage comparison", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/search?q=workspace");
    vi.mocked(api.search).mockReset();
    vi.mocked(api.agentStream).mockReset();
    const products = showcaseCatalogPage({}, 0, 5).products;
    const response = searchResponse("workspace", products);
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

  it("uses the URL mode as truth for starter and history navigation", async () => {
    window.history.replaceState({}, "", "/search");
    vi.mocked(api.agentStream).mockImplementation(
      async (_question, _filters, onEvent) => {
        onEvent({ type: "complete", response: agentResponse });
      },
    );

    render(
      <CommerceProvider>
        <SearchPage />
      </CommerceProvider>,
    );

    fireEvent.click(screen.getByRole("button", {
      name: /What should I buy for a quiet home office under \$600/,
    }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Agent" }).getAttribute("aria-pressed"))
        .toBe("true");
    });
    expect(new URLSearchParams(window.location.search).get("mode")).toBe("agent");
    expect(api.agentStream).toHaveBeenCalledWith(
      expect.any(String),
      {},
      expect.any(Function),
      undefined,
      { signal: expect.any(AbortSignal) },
    );

    act(() => {
      window.history.replaceState(
        {},
        "",
        "/search?q=workspace&mode=retrieval",
      );
      window.dispatchEvent(new PopStateEvent("popstate"));
    });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Retrieval" }).getAttribute("aria-pressed"))
        .toBe("true");
      expect(api.search).toHaveBeenCalled();
    });
  });

  it("aborts and ignores a superseded retrieval response", async () => {
    const first = deferred<SearchResponse>();
    const second = deferred<SearchResponse>();
    const products = showcaseCatalogPage({}, 0, 5).products;
    let firstSignal: AbortSignal | undefined;
    vi.mocked(api.search).mockImplementation((nextQuery, _filters, options) => {
      if (nextQuery === "first") {
        firstSignal = options?.signal;
        return first.promise;
      }
      return second.promise;
    });
    window.history.replaceState({}, "", "/search?q=first&mode=retrieval");

    render(
      <CommerceProvider>
        <SearchPage />
      </CommerceProvider>,
    );
    await waitFor(() => expect(api.search).toHaveBeenCalledTimes(1));

    act(() => {
      window.history.pushState(
        {},
        "",
        "/search?q=second&mode=retrieval",
      );
    });
    await waitFor(() => expect(api.search).toHaveBeenCalledTimes(2));
    expect(firstSignal?.aborted).toBe(true);

    await act(async () => {
      second.resolve(searchResponse("second", [products[1]]));
      await second.promise;
    });
    expect(await screen.findByText(products[1].title)).toBeTruthy();

    await act(async () => {
      first.resolve(searchResponse("first", [products[0]]));
      await first.promise;
    });
    expect(screen.queryByText(products[0].title)).toBeNull();
    expect(screen.getByText(products[1].title)).toBeTruthy();
  });

  it("aborts an active agent stream when history selects another request", async () => {
    let streamSignal: AbortSignal | undefined;
    vi.mocked(api.agentStream).mockImplementation(
      async (_question, _filters, _onEvent, _context, options) => {
        streamSignal = options?.signal;
        await new Promise(() => {});
      },
    );
    window.history.replaceState(
      {},
      "",
      "/search?q=first-agent-request&mode=agent",
    );

    render(
      <CommerceProvider>
        <SearchPage />
      </CommerceProvider>,
    );
    await waitFor(() => expect(streamSignal).toBeInstanceOf(AbortSignal));

    act(() => {
      window.history.pushState(
        {},
        "",
        "/search?q=workspace&mode=retrieval",
      );
    });

    await waitFor(() => expect(streamSignal?.aborted).toBe(true));
    expect(await screen.findByRole("heading", {
      name: "Results for “workspace”",
    })).toBeTruthy();
  });

  it("renders an explicit empty state for a successful zero-result search", async () => {
    vi.mocked(api.search).mockResolvedValue(searchResponse("workspace", []));

    render(
      <CommerceProvider>
        <SearchPage />
      </CommerceProvider>,
    );

    expect(
      await screen.findByRole("heading", { name: "No products matched this request" }),
    ).toBeTruthy();
    expect(screen.queryByRole("article")).toBeNull();
  });
});
