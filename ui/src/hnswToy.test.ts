import { describe, expect, it } from "vitest";
import { buildToyIndex, EFFORT_OPTIONS, LINK_OPTIONS, searchToyIndex, TOY_REQUESTS, TOY_RESULTS } from "./hnswToy";

const request = (id: string) => TOY_REQUESTS.find((item) => item.id === id)!;

describe("toy HNSW index", () => {
  it("builds the same graph every time", () => {
    const first = buildToyIndex(LINK_OPTIONS[1]);
    const second = buildToyIndex(LINK_OPTIONS[1]);
    expect(second.levels).toEqual(first.levels);
    expect(second.links).toEqual(first.links);
    expect(first.points).toHaveLength(144);
  });

  it.each(LINK_OPTIONS)("keeps HNSW's layer and link rules with m = %i", (m) => {
    const index = buildToyIndex(m);
    index.links.forEach((layer, depth) => layer.forEach((neighbours, node) => {
      if (index.levels[node] < depth) expect(neighbours).toEqual([]);
      for (const other of neighbours) expect(index.levels[other]).toBeGreaterThanOrEqual(depth);
      expect(neighbours.length).toBeLessThanOrEqual(depth === 0 ? 2 * m : m);
    }));
    expect(index.levels[index.entry]).toBe(index.top);
  });

  it("matches exact search with a wide beam on a well-linked graph", () => {
    const index = buildToyIndex(LINK_OPTIONS[1]);
    for (const item of TOY_REQUESTS) {
      const search = searchToyIndex(index, item, EFFORT_OPTIONS.at(-1)!);
      expect(search.results).toEqual(search.exact);
      expect(search.recall).toBe(1);
    }
  });

  it("returns at most ef_search rows, as one pgvector index scan does", () => {
    const index = buildToyIndex(LINK_OPTIONS[1]);
    for (const effort of EFFORT_OPTIONS.filter((value) => value < TOY_RESULTS)) {
      expect(searchToyIndex(index, request("focus"), effort).results).toHaveLength(effort);
    }
  });

  it("spends more distance checks as the beam widens", () => {
    const index = buildToyIndex(LINK_OPTIONS[1]);
    const checks = EFFORT_OPTIONS.map((effort) => searchToyIndex(index, request("focus"), effort).checks);
    checks.slice(1).forEach((value, i) => expect(value).toBeGreaterThanOrEqual(checks[i]));
    expect(checks.at(-1)!).toBeLessThan(index.points.length);
  });

  it("traps a sparse graph in the wrong group until the beam is wide enough", () => {
    const index = buildToyIndex(LINK_OPTIONS[0]);
    const narrow = searchToyIndex(index, request("comfort"), 20);
    const wide = searchToyIndex(index, request("comfort"), 40);
    expect(narrow.recall).toBeLessThan(1);
    expect(wide.recall).toBe(1);
  });

  it("records a trace that only walks real links, top layer first", () => {
    const index = buildToyIndex(LINK_OPTIONS[1]);
    const { trace } = searchToyIndex(index, request("code"), 10);
    expect(trace[0]).toEqual({ kind: "descend", layer: index.top, node: index.entry });
    let layer = index.top;
    for (const event of trace) {
      expect(event.layer).toBeLessThanOrEqual(layer);
      layer = event.layer;
      if (event.kind === "check" || event.kind === "move") expect(index.links[event.layer][event.from]).toContain(event.node);
    }
    expect(layer).toBe(0);
  });
});
