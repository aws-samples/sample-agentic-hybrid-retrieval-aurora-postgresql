import { describe, expect, it } from "vitest";
import type { AgentCitation, ProductSummary } from "../../types";
import { comparisonRows, pickName, requirementsFrom, retrievalPath, unknowns } from "./comparison";

// The two Dell listings from a recorded 2026-09-28 answer, reduced to what the
// comparison reads.
const rank = (value: number | null) => ({ rank: value, raw_score: null, rrf_contribution: null });
const dell27 = {
  product_id: 1408222,
  brand: "Dell",
  model: "UltraSharp",
  source_dataset: "reviews-2023-v2",
  title: 'Dell UltraSharp 27" 4K UHD (3840 x 2160) IPS Anti-Glare Monitor - U2720Q-Black',
  specs: {
    size_in: { value: 27, source: "details.Screen Size", quote: "27 Inches" },
    resolution: { value: "3840x2160", source: "details.Display Resolution Maximum", quote: "3840 x 2160 Pixels" },
    usb_c_power_w: { value: 90, source: "description[6]", quote: "get up to 90W of power delivery" },
  },
  signals: { fts: rank(null), trigram: rank(null), semantic: rank(7), pre_rerank_rank: 10, final_rank: 1 },
} as unknown as ProductSummary;
const dellU2720q = {
  ...dell27,
  product_id: 1531801,
  title: 'Dell UltraSharp U2720Q 27" LCD LED Monitor - 3840 x 2160 4K Display',
  specs: {
    size_in: { value: 27, source: "title", quote: 'Dell UltraSharp U2720Q 27" LCD LED Monitor' },
    resolution: { value: "3840x2160", source: "details.Display Resolution Maximum", quote: "3840 x 2160 pixels" },
    usb_c_power_w: { value: 90, source: "features[1]", quote: "Get up to 90W of power delivery" },
  },
  signals: { fts: rank(null), trigram: rank(null), semantic: rank(2), pre_rerank_rank: 5, final_rank: 2 },
} as unknown as ProductSummary;
const listingText = (product: ProductSummary) =>
  `Title: ${product.title}\n\nListing details:\n${Object.values(product.specs ?? {}).map((spec) => spec.quote).join("\n")}`;
const cite = (number: number, product_id: number, evidence_type: string, quote = "") =>
  ({ number, product_id, evidence_type, evidence_id: number, source_uri: "", revision: "", title: "", quote }) as AgentCitation;
const citations = [
  cite(1, 1408222, "product_spec", listingText(dell27)),
  cite(2, 1408222, "customer_review", "Charges my MacBook over the one cable."),
  cite(3, 1531801, "product_spec", listingText(dellU2720q)),
  cite(4, 1531801, "customer_review", "One cable for power and picture."),
];
const FIRST = "I need a 27-inch 4K monitor that charges my laptop over one USB-C cable.";
const FOLLOW_UP = "My laptop actually needs 100W. Does that change your pick?";

describe("pickName", () => {
  it("keeps a listing title short enough for a column header", () => {
    expect(pickName(dell27)).toBe("Dell UltraSharp 27″ 4K UHD");
    expect(pickName(dellU2720q)).toBe("Dell UltraSharp U2720Q 27″ LCD");
    const repeated = { ...dell27, title: 'Dell P2721Q 27" 27 4K USB-C Monitor, Black - 3840 x 2160' } as ProductSummary;
    expect(pickName(repeated)).toBe("Dell P2721Q 27″ 4K USB-C");
    const piped = { ...dell27, title: "BenQ EW2780U 4K | IPS Multimedia with HDMI" } as ProductSummary;
    expect(pickName(piped)).toBe("BenQ EW2780U 4K");
  });
});

describe("requirementsFrom", () => {
  it("reads only the requirements a spec field can decide", () => {
    expect(requirementsFrom(FIRST).map((item) => item.key)).toEqual(["size_in", "resolution"]);
    expect(requirementsFrom(FOLLOW_UP).map((item) => item.label)).toEqual(["100W charging"]);
    expect(requirementsFrom("Is it comfortable for a long day?")).toEqual([]);
  });
});

describe("comparisonRows", () => {
  it("labels each cell with its source and the citations behind it", () => {
    const rows = comparisonRows([dell27, dellU2720q], citations, [FIRST]);
    const size = rows.find((row) => row.key === "size_in")!;
    expect(size.label).toBe("27-inch screen");
    expect(size.cells.map((cell) => [cell.source, cell.status, cell.citations])).toEqual([
      ["listing", "met", [1]],
      ["title", "met", [3]],
    ]);
    expect(rows.at(-1)!.cells.map((cell) => [cell.text, cell.citations])).toEqual([
      ["1 review cited", [2]],
      ["1 review cited", [4]],
    ]);
  });

  it("marks a follow-up requirement as the change, and decides it against the stated value", () => {
    const rows = comparisonRows([dell27, dellU2720q], citations, [FIRST, FOLLOW_UP]);
    const power = rows.find((row) => row.key === "usb_c_power_w")!;
    expect(power).toMatchObject({ label: "100W charging", changed: true });
    expect(power.cells.map((cell) => [cell.text, cell.status])).toEqual([["90 W", "not_met"], ["90 W", "not_met"]]);
    expect(rows.find((row) => row.key === "size_in")!.changed).toBe(false);
  });

  it("cites a listing record only for the figures its text states", () => {
    const withoutPower = cite(1, 1408222, "product_spec", 'Title: Dell UltraSharp 27" 4K UHD\n27 Inches\n3840 x 2160 Pixels');
    const rows = comparisonRows([dell27], [withoutPower], [FIRST]);
    expect(rows.find((row) => row.key === "size_in")!.cells[0].citations).toEqual([1]);
    expect(rows.find((row) => row.key === "usb_c_power_w")!.cells[0].citations).toEqual([]);
  });

  it("says a missing spec is not stated rather than failing it", () => {
    const { size_in: _size, ...rest } = dellU2720q.specs!;
    const noSize = { ...dellU2720q, specs: rest } as ProductSummary;
    const rows = comparisonRows([dell27, noSize], citations, [FIRST]);
    const size = rows.find((row) => row.key === "size_in")!;
    expect(size.cells[1]).toMatchObject({ text: "Not stated", source: "not_stated", status: null });
    expect(unknowns([dell27, noSize], rows)).toEqual([
      "27-inch screen: not stated for Dell UltraSharp U2720Q 27″ LCD",
      "Current price and stock",
    ]);
  });
});

describe("retrievalPath", () => {
  it("names only the methods that found the pick, then its combined and final positions", () => {
    expect(retrievalPath(dell27)).toEqual(["Meaning match #7", "Combined #10", "Reranked to #1"]);
  });
});

describe("unknowns, grouped", () => {
  const chair = { ...dell27, product_id: 7, category_key: "chair", brand: "Steelcase", model: "Gesture", source_dataset: null, specs: {} } as unknown as ProductSummary;
  const monitor = { ...dell27, category_key: "monitor" } as unknown as ProductSummary;
  const noSize = { ...monitor, product_id: 2, title: "Dell P2722H", specs: {} } as unknown as ProductSummary;

  it("lists only figures the shopper asked about, one line per figure", () => {
    const rows = comparisonRows([monitor, noSize], [], ["a 27-inch monitor"]);
    expect(unknowns([monitor, noSize], rows)).toEqual([
      "27-inch screen: not stated for Dell P2722H",
      "Current price and stock",
    ]);
  });

  it("does not call a monitor's size unknown for a chair in the same room", () => {
    const rows = comparisonRows([monitor, chair], [], ["a 27-inch monitor and a chair"]);
    expect(unknowns([monitor, chair], rows)).toEqual(["Current price and stock"]);
  });
});
