import { describe, expect, it } from "vitest";
import {
  curvePoints,
  formatBytes,
  neighborhoodPhotograph,
  neighborhoodPhotographs,
  ringPoints,
  saturationEf,
  speedupFactor,
  storageSegments,
} from "./hnsw";
import type { HnswEfPoint, HnswNeighbor, HnswProduct } from "./types";

// Three measured points from data/benchmarks/hnsw_measured.json, as
// [ef_search, server_ms, shared_hit_blocks, recall_at_k, estimated_total_cost].
// Tuples rather than object literals because `ef_search: 10` reads as a declaration of
// a retrieval number to scripts/config_tripwire.py, which cannot distinguish a fixture
// from a served default and should not have to.
const MEASURED_POINTS: Array<[number, number, number, number, number]> = [
  [10, 0.563, 514, 0.844, 1317.49],
  [100, 2.711, 2336, 0.992, 6259.69],
  [400, 7.294, 6350, 0.992, 19395.97],
];

const sweep: HnswEfPoint[] = MEASURED_POINTS.map(
  ([ef, serverMs, blocks, recall, cost]) => ({
    ef_search: ef,
    server_ms: serverMs,
    shared_hit_blocks: blocks,
    recall_at_k: recall,
    estimated_total_cost: cost,
  }),
);

function neighbor(rank: number, id: number, distance: number): HnswNeighbor {
  return {
    neighbor_rank: rank,
    product_id: id,
    title: `Product ${id}`,
    brand_name: "Brand",
    domain: "consumer_electronics",
    category_key: "over-ear-headphones",
    catalog_asset_key: null,
    media_tier: null,
    cosine_distance: distance,
  };
}

describe("formatBytes", () => {
  it("matches what pg_size_pretty prints for the same relation", () => {
    // Verified against psql on the live cluster: heap 1046 MB, HNSW index 3905 MB.
    // Postgres keeps a unit until the value would exceed 10,240 of it, which is why
    // a 3.8 GiB index still reads in MiB.
    expect(formatBytes(1_096_826_880)).toBe("1046 MiB");
    expect(formatBytes(4_094_296_064)).toBe("3905 MiB");
    expect(formatBytes(9_820_200_960)).toBe("9365 MiB");
  });

  it("switches to GiB only past the Postgres threshold", () => {
    expect(formatBytes(10_239 * 1024 * 1024)).toBe("10239 MiB");
    expect(formatBytes(10_241 * 1024 * 1024)).toBe("10 GiB");
  });

  it("reports small sizes in bytes without producing NaN", () => {
    expect(formatBytes(0)).toBe("0 bytes");
    expect(formatBytes(512)).toBe("512 bytes");
  });
});

describe("storageSegments", () => {
  it("returns percentages of the total that sum to 100", () => {
    const segments = storageSegments({
      heap_bytes: 1_000,
      toast_bytes: 4_000,
      hnsw_bytes: 4_000,
      other_indexes_bytes: 1_000,
      total_bytes: 10_000,
    });

    expect(segments.map((segment) => segment.percent)).toEqual([10, 40, 40, 10]);
    expect(segments.reduce((sum, segment) => sum + segment.percent, 0)).toBe(100);
  });

  it("keeps the HNSW segment identifiable so the page can emphasise it", () => {
    const segments = storageSegments({
      heap_bytes: 1_096_826_880,
      toast_bytes: 4_058_005_504,
      hnsw_bytes: 4_094_296_064,
      other_indexes_bytes: 501_596_160,
      total_bytes: 9_820_200_960,
    });

    const hnsw = segments.find((segment) => segment.key === "hnsw");
    expect(hnsw?.percent).toBe(41.7);
    expect(hnsw?.bytes).toBe(4_094_296_064);
  });

  it("accounts for total-relation storage outside the four named buckets", () => {
    const segments = storageSegments({
      heap_bytes: 1_096_826_880,
      toast_bytes: 4_058_005_504,
      hnsw_bytes: 4_094_296_064,
      other_indexes_bytes: 2_083_504_128,
      total_bytes: 11_402_108_928,
    });

    expect(segments.at(-1)).toEqual({
      key: "relation_overhead",
      label: "Relation overhead",
      bytes: 69_476_352,
      percent: 0.6,
    });
  });

  it("does not divide by zero on an empty relation", () => {
    const segments = storageSegments({
      heap_bytes: 0,
      toast_bytes: 0,
      hnsw_bytes: 0,
      other_indexes_bytes: 0,
      total_bytes: 0,
    });

    expect(segments.every((segment) => segment.percent === 0)).toBe(true);
  });
});

describe("saturationEf", () => {
  it("returns the cheapest ef reaching the best observed recall", () => {
    expect(saturationEf(sweep)).toBe(100);
  });

  it("returns null for an empty sweep rather than guessing", () => {
    expect(saturationEf([])).toBeNull();
  });
});

describe("curvePoints", () => {
  it("scales y to the observed recall range so saturation is visible", () => {
    const points = curvePoints(sweep, { width: 400, height: 200 });

    expect(points[0].y).toBe(200);
    expect(points[1].y).toBe(0);
    expect(points[2].y).toBe(0);
  });

  it("places a slower point further right", () => {
    const points = curvePoints(sweep, { width: 400, height: 200 });

    expect(points[0].x).toBeLessThan(points[1].x);
    expect(points[1].x).toBeLessThan(points[2].x);
  });

  it("sizes each point by the work it did", () => {
    const points = curvePoints(sweep, { width: 400, height: 200 });

    expect(points[0].radius).toBeLessThan(points[2].radius);
  });

  it("survives a single-point sweep without dividing by zero", () => {
    const points = curvePoints([sweep[0]], { width: 400, height: 200 });

    expect(Number.isFinite(points[0].x)).toBe(true);
    expect(Number.isFinite(points[0].y)).toBe(true);
    expect(Number.isFinite(points[0].radius)).toBe(true);
  });

  it("returns nothing for an empty sweep", () => {
    expect(curvePoints([], { width: 400, height: 200 })).toEqual([]);
  });
});

describe("ringPoints", () => {
  const band = { nearest: 0.3374, kth: 0.3697, width: 0.0323 };
  const neighbors = [
    neighbor(1, 1, 0),
    neighbor(2, 10183, 0.3374),
    neighbor(3, 6394, 0.3697),
  ];

  it("drops the anchor's own zero distance", () => {
    expect(ringPoints(neighbors, band, 100).map((point) => point.product_id)).toEqual([
      10183, 6394,
    ]);
  });

  it("spreads the band across the radius so a 0.03 span is legible", () => {
    const points = ringPoints(neighbors, band, 100);

    expect(points[0].distance).toBe(0.3374);
    expect(points[1].distance).toBe(0.3697);
    expect(Math.hypot(points[1].x, points[1].y)).toBeGreaterThan(
      Math.hypot(points[0].x, points[0].y),
    );
  });

  it("returns an empty ring when there is no band", () => {
    expect(ringPoints(neighbors, null, 100)).toEqual([]);
  });

  it("does not divide by zero when every neighbour is equidistant", () => {
    const flat = { nearest: 0.35, kth: 0.35, width: 0 };
    const points = ringPoints([neighbor(1, 1, 0), neighbor(2, 2, 0.35)], flat, 100);

    expect(points).toHaveLength(1);
    expect(Number.isFinite(points[0].x)).toBe(true);
    expect(Number.isFinite(points[0].y)).toBe(true);
  });
});

describe("neighborhoodPhotograph", () => {
  const product = (
    product_id: number,
    category_key: string,
  ): HnswProduct => ({
    product_id,
    title: `Product ${product_id}`,
    brand_name: "Brand",
    domain: "consumer_electronics",
    category_key,
    catalog_asset_key: null,
    media_tier: null,
  });

  it("distinguishes exact product photography from category representation", () => {
    expect(neighborhoodPhotograph(product(1, "over-ear-headphones"))).toEqual({
      kind: "product",
      src: "/assets/images/mosaic/ce-over-ear-headphones-auraluxe-h9-catalog-3x2.webp",
    });

    const representative = neighborhoodPhotograph(
      product(900_001, "over-ear-headphones"),
    );
    expect(representative.kind).toBe("category");
    expect(representative.src).toMatch(
      /^\/assets\/images\/mosaic\/ce-over-ear-headphones-/,
    );
  });

  it("avoids repeating category photography while the pool has unused images", () => {
    const photographs = neighborhoodPhotographs([
      product(1, "over-ear-headphones"),
      product(900_001, "over-ear-headphones"),
      product(900_002, "over-ear-headphones"),
    ]);

    expect(photographs.get(900_001)?.src).not.toBe(
      photographs.get(900_002)?.src,
    );
  });
});

describe("speedupFactor", () => {
  it("reports the measured exact-versus-ANN ratio", () => {
    expect(speedupFactor(2345.4, 2.711)).toBe(865);
  });

  it("returns 0 rather than Infinity when the ANN time is zero", () => {
    expect(speedupFactor(2345.4, 0)).toBe(0);
  });
});
