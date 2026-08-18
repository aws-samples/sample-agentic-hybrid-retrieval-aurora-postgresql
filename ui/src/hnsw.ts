import mediaManifest from "../../data/media/asset_labels_200.json";
import { categoryProductImageMap } from "./media";
import type {
  HnswBand,
  HnswEfPoint,
  HnswNeighbor,
  HnswProduct,
  HnswStorage,
} from "./types";

const boundPhotographByProductId = new Map<number, string>(
  mediaManifest.products
    .filter((product) => product.catalog_installed)
    .map((product) => [product.product_id, product.catalog_runtime_path]),
);

/** The photograph bound to this specific product, or null. */
export function boundPhotograph(productId: number): string | null {
  return boundPhotographByProductId.get(productId) ?? null;
}

/**
 * The image shown in the neighbourhood instrument, with its provenance intact.
 *
 * Exact product photography wins. The fallback is verified to show the same product
 * category, not the exact SKU, so the component can label that distinction without
 * leaving the graph as anonymous circles.
 */
export function neighborhoodPhotograph(
  product: HnswProduct,
): { kind: "product" | "category"; src: string } {
  const photograph = neighborhoodPhotographs([product]).get(product.product_id);
  if (!photograph) {
    throw new Error(`No neighbourhood photograph resolved for product ${product.product_id}`);
  }
  return photograph;
}

/** Resolve one balanced, provenance-labelled image assignment for a whole ring. */
export function neighborhoodPhotographs(
  products: HnswProduct[],
): Map<number, { kind: "product" | "category"; src: string }> {
  const assigned = new Map<number, { kind: "product" | "category"; src: string }>();
  const unbound: HnswProduct[] = [];
  const reserved: string[] = [];
  for (const product of products) {
    if (assigned.has(product.product_id)) continue;
    const bound = boundPhotograph(product.product_id);
    if (bound) {
      assigned.set(product.product_id, { kind: "product", src: bound });
      reserved.push(bound);
    } else {
      unbound.push(product);
    }
  }
  for (const [productId, src] of categoryProductImageMap(unbound, reserved)) {
    assigned.set(productId, { kind: "category", src });
  }
  return assigned;
}

const KIB = 1024;
// pg_size_pretty stays in a unit until the value would exceed this, which is why it
// prints "3905 MB" for the HNSW index rather than "3.8 GB".
const UNIT_LIMIT = 10 * KIB;
const UNITS = ["bytes", "KiB", "MiB", "GiB", "TiB"] as const;

/**
 * Byte counts in the units, and at the thresholds, that `pg_size_pretty` uses.
 *
 * Deliberately mirrors Postgres rather than picking prettier breakpoints: every size
 * on this page is meant to be checkable against what psql prints for the same
 * relation. Postgres keeps a unit until the value would exceed 10,240 of it, so the
 * 4,094,296,064-byte index reads "3905 MiB" — matching `pg_size_pretty` — instead of
 * "3.8 GiB".
 */
export function formatBytes(bytes: number): string {
  let value = bytes;
  let unit = 0;
  while (Math.abs(value) >= UNIT_LIMIT && unit < UNITS.length - 1) {
    value = value / KIB;
    unit += 1;
  }
  return `${Math.round(value)} ${UNITS[unit]}`;
}

const SEGMENT_LABELS: Array<{ key: keyof HnswStorage; label: string }> = [
  { key: "heap_bytes", label: "Table rows" },
  { key: "toast_bytes", label: "Vector storage" },
  { key: "hnsw_bytes", label: "HNSW index" },
  { key: "other_indexes_bytes", label: "Supporting indexes" },
];

/**
 * The relation's storage split as proportions of its total.
 *
 * Segment keys are stable (`heap`, `toast`, `hnsw`, `other_indexes`) so the page can
 * emphasise the HNSW share. `pg_total_relation_size` also includes auxiliary forks and
 * TOAST indexes; when those bytes are present, they are returned as relation overhead
 * rather than left as an unexplained gap in the bar.
 */
export function storageSegments(
  storage: HnswStorage,
): Array<{ key: string; label: string; bytes: number; percent: number }> {
  const total = storage.total_bytes;
  const segments = SEGMENT_LABELS.map(({ key, label }) => {
    const bytes = storage[key];
    return {
      key: key.replace(/_bytes$/, ""),
      label,
      bytes,
      percent: total > 0 ? Math.round((bytes / total) * 1000) / 10 : 0,
    };
  });
  const namedBytes = SEGMENT_LABELS.reduce((sum, { key }) => sum + storage[key], 0);
  const overheadBytes = Math.max(total - namedBytes, 0);
  if (overheadBytes > 0) {
    segments.push({
      key: "relation_overhead",
      label: "Relation overhead",
      bytes: overheadBytes,
      percent: Math.round((overheadBytes / total) * 1000) / 10,
    });
  }
  return segments;
}

/**
 * The cheapest `ef_search` that reaches the best recall the sweep observed.
 *
 * On the measured corpus this is 100: ef 200 and 400 spend 1.5x and 2.7x the buffers
 * for identical recall. Returns null for an empty sweep rather than inventing a
 * recommendation.
 */
export function saturationEf(sweep: HnswEfPoint[]): number | null {
  if (sweep.length === 0) return null;
  const best = Math.max(...sweep.map((point) => point.recall_at_k));
  const reached = sweep.filter((point) => point.recall_at_k === best);
  return Math.min(...reached.map((point) => point.ef_search));
}

/**
 * Plot geometry for the recall-versus-time curve.
 *
 * y spans the *observed* recall range rather than 0 to 1. Over the measured range
 * (0.844 to 0.992) a 0-to-1 axis compresses the whole curve into the top 15% of the
 * box and the saturation at the served ef_search — the one thing this panel exists to
 * show — becomes invisible.
 *
 * x is logarithmic in server time, because the measured points span 0.563 ms to
 * 7.294 ms and a linear axis crowds the cheap half together.
 */
export function curvePoints(
  sweep: HnswEfPoint[],
  box: { width: number; height: number },
): Array<{ ef: number; x: number; y: number; radius: number }> {
  if (sweep.length === 0) return [];

  const times = sweep.map((point) => Math.log10(Math.max(point.server_ms, 0.001)));
  const recalls = sweep.map((point) => point.recall_at_k);
  const blocks = sweep.map((point) => point.shared_hit_blocks);

  const span = (values: number[]) => {
    const low = Math.min(...values);
    const high = Math.max(...values);
    return { low, range: high - low || 1 };
  };
  const time = span(times);
  const recall = span(recalls);
  const block = span(blocks);

  return sweep.map((point, index) => ({
    ef: point.ef_search,
    x: ((times[index] - time.low) / time.range) * box.width,
    y: box.height - ((recalls[index] - recall.low) / recall.range) * box.height,
    radius: 4 + ((blocks[index] - block.low) / block.range) * 8,
  }));
}

/**
 * Ring geometry for the true neighbours around their anchor.
 *
 * Radius spans the *band* (`nearest` to `kth`), not zero to the largest distance. The
 * measured band is 0.032 wide against absolute distances near 0.34, so an absolute
 * mapping stacks every neighbour on top of every other. Spreading the band is what
 * makes the annulus readable; the panel prints the real distances alongside so the
 * spread is not mistaken for a wider one than it is.
 *
 * The anchor's own zero distance is dropped: it is its own nearest neighbour, and
 * including it would report the band as ten times wider than it is.
 */
export function ringPoints(
  neighbors: HnswNeighbor[],
  band: HnswBand | null,
  radius: number,
): Array<{ product_id: number; angle: number; distance: number; x: number; y: number }> {
  if (band === null) return [];
  const ranked = neighbors.filter((neighbor) => neighbor.cosine_distance > 0);
  if (ranked.length === 0) return [];

  const spread = band.kth - band.nearest;
  const inner = radius * 0.55;

  return ranked.map((neighbor, index) => {
    const fraction = spread > 0 ? (neighbor.cosine_distance - band.nearest) / spread : 0;
    const distanceRadius = inner + fraction * (radius - inner);
    // Golden-angle placement so neighbours do not collide at small counts and the
    // ring reads as a ring rather than a clock face.
    const angle = index * 2.399963;
    return {
      product_id: neighbor.product_id,
      angle,
      distance: neighbor.cosine_distance,
      x: Math.cos(angle) * distanceRadius,
      y: Math.sin(angle) * distanceRadius,
    };
  });
}

/**
 * How many times faster the index is than the exact scan it replaces.
 *
 * Returns 0 rather than Infinity when the ANN time is zero, because an unmeasurable
 * ratio is not an infinite speedup.
 */
export function speedupFactor(exactMs: number, serverMs: number): number {
  if (serverMs <= 0) return 0;
  return Math.round(exactMs / serverMs);
}
