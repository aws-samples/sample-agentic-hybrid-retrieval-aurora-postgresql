// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HnswSearchGraph } from "./HnswSearchGraph";

const motion = vi.hoisted(() => ({ reduced: true }));
vi.mock("motion/react", async (original) => ({
  ...(await original<typeof import("motion/react")>()),
  useReducedMotion: () => motion.reduced,
}));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); motion.reduced = true; });

const receipt = (term: string) => {
  const row = screen.getByText(term).closest("div")!;
  return within(row).getByRole("definition").textContent;
};

describe("HnswSearchGraph", () => {
  it("finds the true nearest products with the default settings", () => {
    render(<HnswSearchGraph />);
    expect(screen.getByRole("button", { name: "Headphones for focus" }).getAttribute("aria-pressed")).toBe("true");
    expect(receipt("Recall@5")).toBe("100%");
    expect(receipt("Rows returned")).toBe("5 of 5");
    expect(screen.getByRole("status").textContent).toContain("returned the same 5 as an exact scan");
  });

  it("shows that a beam smaller than the result list returns fewer rows", () => {
    render(<HnswSearchGraph />);
    fireEvent.click(screen.getByRole("button", { name: /^ef_search 1,/ }));
    expect(receipt("Rows returned")).toBe("1 of 5");
    expect(receipt("Recall@5")).toBe("20%");
    expect(screen.getByRole("status").textContent).toContain("keeps only 1 candidate");
  });

  it("explains a sparse graph that traps the search, and the setting that escapes it", () => {
    render(<HnswSearchGraph />);
    fireEvent.click(screen.getByRole("button", { name: "A chair for long days" }));
    fireEvent.click(screen.getByRole("button", { name: "m 3" }));
    fireEvent.click(screen.getByRole("button", { name: /^ef_search 20,/ }));
    expect(receipt("Recall@5")).toBe("20%");
    expect(screen.getByRole("status").textContent).toContain("try ef_search 40");
    fireEvent.click(screen.getByRole("button", { name: /^ef_search 40,/ }));
    expect(receipt("Recall@5")).toBe("100%");
  });

  it("names Aurora's served index settings without restating them", () => {
    const served = { efSearch: 100, vectors: 553911, dimensions: 1024,
      definition: "CREATE INDEX product_embedding_hnsw ON product_document USING hnsw (embedding vector_cosine_ops) WITH (m='16', ef_construction='64')" };
    const { container } = render(<HnswSearchGraph served={served} />);
    const caption = container.querySelector("figcaption")!.textContent!;
    expect(caption).toContain("553,911 products in 1,024 dimensions with m = 16");
    expect(caption).toContain(`ef_search = ${served.efSearch}`);
  });

  it("replays the search layer by layer when motion is allowed", () => {
    motion.reduced = false;
    let frame!: FrameRequestCallback;
    vi.stubGlobal("requestAnimationFrame", vi.fn((callback: FrameRequestCallback) => { frame = callback; return 1; }));
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    vi.spyOn(performance, "now").mockReturnValue(0);
    render(<HnswSearchGraph />);
    act(() => frame(0));
    expect(screen.getByRole("button", { name: "Restart search" })).toBeTruthy();
    expect(receipt("Recall@5")).toBe("–");
    expect(screen.getByRole("status").textContent).toContain("top layer");
    act(() => frame(60_000));
    expect(screen.getByRole("button", { name: "Search again" })).toBeTruthy();
    expect(receipt("Recall@5")).toBe("100%");
  });
});
