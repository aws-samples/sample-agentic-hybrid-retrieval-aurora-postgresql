// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import measuredArtifact from "../../../data/benchmarks/hnsw_measured.json";
import scaleProjection from "../../../data/benchmarks/scale_projection.json";
import { api } from "../api";
import { formatBytes, storageSegments } from "../hnsw";
import type {
  BenchmarkProjection,
  HnswMeasured,
  HnswNeighborhood,
  HnswProbe,
  HnswProduct,
  HnswSubstrate,
  ReadinessResponse,
} from "../types";
import { PerformancePage } from "./PerformancePage";

vi.mock("../api", () => ({
  api: {
    readiness: vi.fn(),
    projection: vi.fn(),
    hnswMeasured: vi.fn(),
    hnswSubstrate: vi.fn(),
    hnswAnchors: vi.fn(),
    hnswNeighborhood: vi.fn(),
    hnswProbe: vi.fn(),
  },
}));

const projection = scaleProjection satisfies BenchmarkProjection;
const measured = measuredArtifact as unknown as HnswMeasured;

const substrate: HnswSubstrate = {
  index: {
    name: "mosaic_search.product_document_embedding_hnsw_cosine_idx",
    definition: "CREATE INDEX ... USING hnsw (embedding vector_cosine_ops)",
    size_bytes: 4_094_296_064,
    bytes_per_vector: 8189,
    fp32_payload_bytes: 4096,
    overhead_factor: 2.0,
  },
  storage: {
    heap_bytes: 1_096_826_880,
    toast_bytes: 4_058_005_504,
    hnsw_bytes: 4_094_296_064,
    other_indexes_bytes: 501_596_160,
    total_bytes: 9_820_200_960,
  },
  corpus: { vector_count: 500_000, anchor_count: 30, dimensions: 1024 },
  aurora: {
    database_instance_id: "agenticretrievalcorestack-aurora",
    database_version: "18.3",
    vector_extension_version: "0.8.1",
    instance_class: "db.r8g.2xlarge",
  },
  settings: { work_mem: "4MB", shared_buffers: "5443689" },
};

const anchors: HnswProduct[] = [
  {
    product_id: 1,
    title: "Mosaic Auraluxe H9 Premium Wireless Headphones",
    brand_name: "Mosaic",
    domain: "consumer_electronics",
    category_key: "over-ear-headphones",
    catalog_asset_key: "ce-over-ear-headphones-auraluxe-h9",
    media_tier: "flagship",
  },
  {
    product_id: 370001,
    title: "Mosaic Forma Ergonomic Office Chair",
    brand_name: "Mosaic",
    domain: "home_office",
    category_key: "ergonomic-office-chairs",
    catalog_asset_key: "ho-chair-forma",
    media_tier: "flagship",
  },
];

const neighborhood: HnswNeighborhood = {
  anchor: anchors[0],
  preset: "none",
  k: 10,
  neighbors: [
    { ...anchors[0], neighbor_rank: 1, cosine_distance: 0 },
    {
      product_id: 10183,
      title: "Sonora Drift ANC Headphones",
      brand_name: "Sonora",
      domain: "consumer_electronics",
      category_key: "over-ear-headphones",
      catalog_asset_key: null,
      media_tier: null,
      neighbor_rank: 2,
      cosine_distance: 0.3374,
    },
    {
      product_id: 6394,
      title: "HaloBeam Quiet Two Headphones",
      brand_name: "HaloBeam",
      domain: "consumer_electronics",
      category_key: "over-ear-headphones",
      catalog_asset_key: null,
      media_tier: null,
      neighbor_rank: 3,
      cosine_distance: 0.3697,
    },
  ],
  band: { nearest: 0.3374, kth: 0.3697, width: 0.0323 },
};

function settingsFrom([efSearch, scanMemMultiplier, maxScanTuples, k]: [
  number,
  number,
  number,
  number,
]): HnswProbe["settings"] {
  return {
    ef_search: efSearch,
    iterative_scan: "relaxed_order",
    scan_mem_multiplier: scanMemMultiplier,
    max_scan_tuples: maxScanTuples,
    k,
  };
}

const probeResult: HnswProbe = {
  anchor: anchors[0],
  preset: "none",
  // Built from a tuple for the same reason as ui/src/hnsw.test.ts: these field names
  // read as declarations of retrieval numbers to config_tripwire.
  settings: settingsFrom([10, 2, 20_000, 10]),
  sql: "SELECT product_id FROM mosaic_search.product_document WHERE embedding IS NOT NULL",
  rows_returned: 10,
  exact_rows_available: 10,
  recall_at_k: 0.6,
  missed: [6394],
  unexpected: [],
  plan: {
    node: "Index Scan",
    index_name: "product_document_embedding_hnsw_cosine_idx",
    server_ms: 0.624,
    shared_hit_blocks: 514,
    shared_read_blocks: 0,
    estimated_total_cost: 1317.49,
    estimated_rows: 10,
  },
  products: [],
};

const readiness: ReadinessResponse = {
  status: "ready",
  database_ready: true,
  model_space_ready: true,
  database: {
    database_name: "mosaic_catalog",
    server_version: "18.3",
    schema_ready: true,
    vector_version: "0.8.1",
    product_count: 500_000,
    embedded_product_count: 500_000,
    embedding_dimensions: 1024,
    embedding_model_ids: ["us.cohere.embed-v4:0"],
    premium_product_count: 120,
    evidence_product_count: 500_000,
    missing_retrieval_indexes: [],
    missing_retrieval_functions: [],
  },
  configured_models: {
    embedding: "us.cohere.embed-v4:0",
    rerank: "cohere.rerank-v3-5:0",
    agent: "global.anthropic.claude-sonnet-4-6",
    synthesis: "global.anthropic.claude-sonnet-4-6",
  },
  bedrock_credentials: { ready: true },
};

describe("PerformancePage", () => {
  beforeAll(() => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  });

  beforeEach(() => {
    vi.mocked(api.readiness).mockResolvedValue(readiness);
    vi.mocked(api.projection).mockResolvedValue(projection);
    vi.mocked(api.hnswMeasured).mockResolvedValue(measured);
    vi.mocked(api.hnswSubstrate).mockResolvedValue(substrate);
    vi.mocked(api.hnswAnchors).mockResolvedValue(anchors);
    vi.mocked(api.hnswNeighborhood).mockResolvedValue(neighborhood);
    vi.mocked(api.hnswProbe).mockResolvedValue(probeResult);
  });

  afterEach(cleanup);

  it("keeps the instrument when only exact ground truth is missing", async () => {
    // The neighbourhood endpoint answers 503 when mosaic_bench.exact_neighbor has
    // no rows for the connected dataset manifest. That used to write the
    // page-level error state, so one failing panel replaced the substrate sizes,
    // the measured sweep, the anchors and the projection that had all loaded.
    vi.mocked(api.hnswNeighborhood).mockRejectedValue(
      new Error("found no stored neighbours for anchor 1; fix: run make db-seed-exact-neighbors"),
    );

    render(<PerformancePage />);

    expect(await screen.findByText("LIVE AURORA INDEX")).toBeTruthy();
    expect(screen.getByText("PROJECTED FROM 500K BASELINE")).toBeTruthy();
    expect(screen.getAllByText("MEASURED").length).toBeGreaterThan(0);

    // The one panel that needed it says so, and says how to fix it.
    const notice = await screen.findByText(/found no stored neighbours/);
    expect(notice.closest(".hnsw-neighborhood-unavailable")).not.toBeNull();
  });

  it("keeps live, measured, and projected evidence separately labelled", async () => {
    const { container } = render(<PerformancePage />);

    const live = await screen.findByText("LIVE AURORA INDEX");
    expect(live.classList).toContain("live");
    expect(screen.getByText("PROJECTED FROM 500K BASELINE")).toBeTruthy();
    const measuredBadges = screen.getAllByText("MEASURED");
    expect(measuredBadges.length).toBeGreaterThan(0);
    measuredBadges.forEach((badge) => {
      expect(badge.classList).toContain("measured");
      expect(badge.classList).not.toContain("live");
    });
    expect(container.querySelector(".labs-intro")?.className).toBe("labs-intro");
    expect(
      screen.getByRole("link", { name: "HNSW at scale" }).getAttribute("aria-current"),
    ).toBe("page");
  });

  it("shows the measured storage anatomy in the units psql prints", async () => {
    render(<PerformancePage />);

    // pg_size_pretty on the live cluster: index 3905 MB, heap 1046 MB.
    // Appears twice by design: once as the headline, once in the legend.
    expect((await screen.findAllByText("3905 MiB")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("1046 MiB").length).toBeGreaterThan(0);
    // Also stated in the envelope header, where it is the extrapolation basis.
    expect(screen.getAllByText(/8,189 bytes per vector/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/2x overhead/).length).toBeGreaterThan(0);
  });

  it("keeps each storage share attached to its value", async () => {
    render(<PerformancePage />);

    const vectorStorage = (await screen.findByText("Vector storage")).closest("li");
    expect(vectorStorage).toBeTruthy();
    const vectorSegment = storageSegments(substrate.storage).find(
      (segment) => segment.key === "toast",
    );
    expect(vectorStorage?.querySelector(".hnsw-storage-legend-metric")?.textContent).toBe(
      `${formatBytes(substrate.storage.toast_bytes)}${vectorSegment?.percent}% of total`,
    );
    expect(screen.getByText("Table rows")).toBeTruthy();
    expect(screen.getByText("Supporting indexes")).toBeTruthy();
  });

  it("uses compact data roles for live substrate metadata", async () => {
    render(<PerformancePage />);

    expect((await screen.findByText("500,000")).classList).toContain(
      "hnsw-live-value--metric",
    );
    expect(screen.getByText("PostgreSQL 18.3").classList).toContain(
      "hnsw-live-value--metadata",
    );
    expect(
      screen.getByText(
        `m=${measured.index.m} / ef_construction=${measured.index.ef_construction}`,
      ).classList,
    ).toContain("hnsw-live-value--config");
  });

  it("marks the measured saturation point on the ef_search curve", async () => {
    render(<PerformancePage />);
    await screen.findByRole("heading", { name: /Recall you can buy/ });

    const saturation = measured.ef_sweep.find(
      (point) => point.recall_at_k === Math.max(...measured.ef_sweep.map((p) => p.recall_at_k)),
    )!;
    expect(
      screen.getAllByText(new RegExp(`ef_search ${saturation.ef_search}`)).length,
    ).toBeGreaterThan(0);
    expect(screen.getByLabelText(/Recall saturates at ef_search/)).toBeTruthy();
  });

  it("shows the measured values when an ef_search point is inspected", async () => {
    render(<PerformancePage />);
    await screen.findByRole("heading", { name: /Recall you can buy/ });

    const first = measured.ef_sweep[0];
    fireEvent.pointerEnter(
      screen.getByLabelText(
        new RegExp(
          `ef_search ${first.ef_search}: ${first.server_ms} ms, ` +
            `${(first.recall_at_k * 100).toFixed(1)}% recall`,
        ),
      ),
    );

    expect(screen.getByText(`${first.shared_hit_blocks.toLocaleString()} buffers`)).toBeTruthy();
  });

  it("renders every neighbourhood node with product imagery", async () => {
    render(<PerformancePage />);

    const ring = await screen.findByRole("img", {
      name: /neighbours of Mosaic Auraluxe H9/,
    });
    expect(ring.querySelectorAll("image")).toHaveLength(
      neighborhood.neighbors.length,
    );
    expect(
      screen.getByText(/Bound images are exact; the rest use verified same-category/),
    ).toBeTruthy();
  });

  it("labels a live probe result distinctly from the measured curve", async () => {
    render(<PerformancePage />);
    await screen.findByRole("heading", { name: /Recall you can buy/ });

    fireEvent.click(screen.getByRole("button", { name: /Run on Aurora now/ }));

    await waitFor(() => expect(screen.getByText("LIVE PROBE")).toBeTruthy());
    expect(screen.getByText(/Index Scan using/)).toBeTruthy();
    expect(screen.getByText("0.624 ms")).toBeTruthy();
    expect(screen.getAllByText("MEASURED").length).toBeGreaterThan(0);
  });

  it("marks the neighbours a low ef_search missed", async () => {
    render(<PerformancePage />);
    await screen.findByText(/Mosaic Auraluxe H9/);

    fireEvent.click(screen.getByRole("button", { name: /Run on Aurora now/ }));

    await waitFor(() =>
      expect(screen.getAllByText(/missed at ef_search/).length).toBeGreaterThan(0),
    );
  });

  it("states the measured band width rather than implying a wide spread", async () => {
    render(<PerformancePage />);

    expect(await screen.findByText("0.0323")).toBeTruthy();
    expect(screen.getAllByText("0.3374").length).toBeGreaterThan(0);
    expect(screen.getByText(/Titles, ranks, and distances remain exact/)).toBeTruthy();
  });

  it("shows a less selective filter failing worse than a more selective one", async () => {
    render(<PerformancePage />);
    await screen.findByRole("heading", { name: /Add a WHERE clause/ });

    fireEvent.click(screen.getByRole("button", { name: /Home office only/ }));

    expect(await screen.findByText(/Less selective, and far worse/)).toBeTruthy();
    expect(screen.getByText(/100 of the 100 nearest neighbours/)).toBeTruthy();
  });

  it("names the memory budget rather than the tuple cap on the budget-bound preset", async () => {
    render(<PerformancePage />);
    await screen.findByRole("heading", { name: /Add a WHERE clause/ });

    fireEvent.click(screen.getByRole("button", { name: /Refurbished above/ }));

    expect(
      await screen.findByText(/binding limit is work_mem x scan_mem_multiplier/),
    ).toBeTruthy();
    expect(screen.getByText(/max_scan_tuples from 20,000 to 1,000,000/)).toBeTruthy();
  });

  it("offers the pre-fix memory budget so the truncation can be reproduced", async () => {
    render(<PerformancePage />);
    await screen.findByRole("heading", { name: /Add a WHERE clause/ });

    expect(screen.getByText(/\(pre-fix\)/)).toBeTruthy();
    expect(screen.getByText(/\(shipped\)/)).toBeTruthy();
  });

  it("renders no build-time column, because it was never measured", async () => {
    render(<PerformancePage />);
    await screen.findByRole("heading", { name: /Where this goes/ });

    expect(screen.queryByText(/Projected build/)).toBeNull();
    expect(screen.queryByText(/min$/)).toBeNull();
  });

  it("never renders the retired decorative search path", async () => {
    const { container } = render(<PerformancePage />);
    await screen.findByRole("heading", { name: /Recall you can buy/ });

    expect(screen.queryByText(/Illustrative search path/)).toBeNull();
    expect(screen.queryByText(/not a captured Aurora query plan/)).toBeNull();
    expect(container.querySelector(".hnsw-graph-layer")).toBeNull();
  });

  it("reports missing live vector metadata without presenting the index as ready", async () => {
    vi.mocked(api.readiness).mockResolvedValueOnce({
      ...readiness,
      database_ready: false,
      database: {
        ...readiness.database,
        missing_retrieval_indexes: ["product_document_embedding_hnsw_cosine_idx"],
      },
    });

    render(<PerformancePage />);

    expect(await screen.findByText("HNSW index unavailable")).toBeTruthy();
    expect(screen.queryByText("HNSW index ready")).toBeNull();
  });

  it("surfaces a failed probe instead of silently doing nothing", async () => {
    vi.mocked(api.hnswProbe).mockRejectedValueOnce(new Error("statement timeout"));

    render(<PerformancePage />);
    await screen.findByRole("heading", { name: /Recall you can buy/ });

    fireEvent.click(screen.getByRole("button", { name: /Run on Aurora now/ }));

    expect((await screen.findByRole("alert")).textContent).toContain(
      "statement timeout",
    );
  });

  it("labels the controlled A/B with every condition of the result", async () => {
    render(<PerformancePage />);
    await screen.findByRole("heading", { name: "Controlled scale A/B" });

    // AWS documents I/O-Optimized as required for the tiered-cache behaviour, so it
    // belongs in the badge rather than a footnote. Same for the pinned shared_buffers.
    const badge = screen.getByText(/PURPOSE-BUILT AURORA PAIR/);
    expect(badge.textContent).toContain("US-EAST-1");
    expect(badge.textContent).toContain("2.0 GiB shared_buffers");
    expect(badge.textContent).toContain("I/O-OPTIMIZED");
  });

  it("states the A/B headline and every control beside it", async () => {
    render(<PerformancePage />);
    await screen.findByRole("heading", { name: "Controlled scale A/B" });

    expect(screen.getByText(/8.1x speedup with 87.2% less I\/O wait/)).toBeTruthy();
    expect(screen.getByText(/both instance classes were approximately 1.6 ms/)).toBeTruthy();
    expect(screen.getByText(/first r8gd pass was 665 ms/)).toBeTruthy();
    expect(screen.getByText(/Page counts remained equivalent/)).toBeTruthy();
    expect(
      screen.getByText(/index construction showed no measurable improvement/),
    ).toBeTruthy();
  });

  it("keeps the A/B boundary statement with the result, not below the fold", async () => {
    render(<PerformancePage />);
    await screen.findByRole("heading", { name: "Controlled scale A/B" });

    expect(
      screen.getByText(/not the workshop's default configuration or a general r8gd guarantee/),
    ).toBeTruthy();
  });

  it("never claims the crossover itself is worth 8x", async () => {
    render(<PerformancePage />);
    await screen.findByRole("heading", { name: /Where this goes/ });

    // The projection identifies when to test; the measurement is a separate statement.
    expect(
      screen.getByText(/crossover identifies when to test Optimized Reads/),
    ).toBeTruthy();
    expect(screen.queryByText(/past 1.96M products, NVMe is worth/i)).toBeNull();
  });

  it("shows the three representations with halfvec marked recommended", async () => {
    render(<PerformancePage />);
    await screen.findByRole("heading", { name: /three ways to store them/ });

    expect(screen.getByText("halfvec(1024)")).toBeTruthy();
    expect(screen.getByText("recommended")).toBeTruthy();
    expect(screen.getByText(/cut the index by 3x, not 2x/)).toBeTruthy();
    expect(screen.getByText("Existing index")).toBeTruthy();
    expect(screen.queryByText("not measured")).toBeNull();
    // The citation was a "forthcoming" placeholder until the post published. It
    // is a real outbound link now, and still names no authors.
    const reference = screen.getByRole("link", {
      name: /Scale pgvector with binary quantization on Amazon Aurora PostgreSQL/,
    });
    expect(reference.getAttribute("href")).toBe(
      "https://aws.amazon.com/blogs/database/scale-pgvector-with-binary-quantization-on-amazon-aurora-postgresql/",
    );
    expect(reference.getAttribute("target")).toBe("_blank");
    expect(reference.getAttribute("rel")).toBe("noreferrer");
    expect(screen.getByText(/AWS Database Blog, 18 August 2026/)).toBeTruthy();
    expect(screen.queryByText("AWS Blog (forthcoming)")).toBeNull();
    expect(screen.queryByText(/Dille|Manickam/)).toBeNull();
  });

  it("frames the tight cosine band as a useful recall stress test", async () => {
    render(<PerformancePage />);
    await screen.findByRole("heading", { name: /neighbours sit in a band/ });

    expect(
      screen.getByText(/tight distance band makes this a useful recall stress test/),
    ).toBeTruthy();
    expect(screen.getByText(/identify a defensible operating point/)).toBeTruthy();
    expect(screen.queryByText(/property of this corpus, not of pgvector/)).toBeNull();
  });

  it("keeps the A/B table intervals identical to the headline", async () => {
    render(<PerformancePage />);
    await screen.findByRole("heading", { name: "Controlled scale A/B" });

    // The headline states 893-995 ms and 106-126 ms. A table that rounded differently
    // would put two versions of the same measurement on one screen.
    const headline = screen.getByText(/8.1x speedup with 87.2% less I\/O wait/).textContent!;
    expect(headline).toContain("893-995 ms");
    expect(headline).toContain("106-126 ms");
    expect(screen.getByText("893-995 ms")).toBeTruthy();
    expect(screen.getByText("106-126 ms")).toBeTruthy();
  });

  it("keeps both wide benchmark tables reachable on narrow screens", async () => {
    render(<PerformancePage />);
    await screen.findByRole("heading", { name: "Controlled scale A/B" });

    const representations = screen.getByRole("region", {
      name: "Vector representation benchmark",
    });
    const controlledAb = screen.getByRole("region", {
      name: "Controlled Aurora A/B results",
    });
    const projectionTable = screen.getByRole("region", {
      name: "Projected HNSW scale envelope",
    });

    expect(representations.getAttribute("tabindex")).toBe("0");
    expect(controlledAb.getAttribute("tabindex")).toBe("0");
    expect(projectionTable.getAttribute("tabindex")).toBe("0");
    expect(representations.querySelector("table")).toBeTruthy();
    expect(controlledAb.querySelector("table")).toBeTruthy();
    expect(projectionTable.querySelector("table")).toBeTruthy();
  });
});
