/**
 * A real HNSW index over a small two-dimensional product map, built in the browser.
 *
 * The map is a teaching stand-in for Aurora's 1,024-dimensional catalog: the points are
 * generated, but insertion, layer assignment, greedy descent and the ef-bounded beam
 * search follow the HNSW algorithm pgvector implements. Every search records a trace so
 * the page can replay exactly what the index did.
 */

export type ToyPoint = { id: number; x: number; y: number; group: string };
export type ToyGroup = { name: string; x: number; y: number };
export type ToyIndex = {
  points: ToyPoint[];
  levels: number[];
  /** links[layer][node] lists the node's neighbours on that layer; empty below its level. */
  links: number[][][];
  entry: number;
  top: number;
  m: number;
};
export type TraceEvent =
  | { kind: "check"; layer: number; node: number; from: number }
  | { kind: "move"; layer: number; node: number; from: number }
  | { kind: "admit"; layer: number; node: number }
  | { kind: "evict"; layer: number; node: number }
  | { kind: "descend"; layer: number; node: number };
export type ToySearch = {
  results: number[];
  exact: number[];
  checks: number;
  trace: TraceEvent[];
  recall: number;
};

/** The map's aspect matches the drawing: x in [0, 1.6], y in [0, 1]. */
export const MAP_WIDTH = 1.6;
export const TOY_GROUPS: ToyGroup[] = [
  { name: "Headphones", x: 1.24, y: 0.28 },
  { name: "Earbuds", x: 1.42, y: 0.62 },
  { name: "Speakers", x: 1.05, y: 0.8 },
  { name: "Monitors", x: 0.66, y: 0.22 },
  { name: "Webcams", x: 0.86, y: 0.52 },
  { name: "Keyboards", x: 0.22, y: 0.3 },
  { name: "Chairs", x: 0.3, y: 0.76 },
  { name: "Desk lamps", x: 0.6, y: 0.78 },
];
export const TOY_REQUESTS = [
  { id: "focus", label: "Headphones for focus", x: 1.31, y: 0.36 },
  { id: "code", label: "A monitor for code", x: 0.58, y: 0.27 },
  { id: "comfort", label: "A chair for long days", x: 0.36, y: 0.7 },
] as const;
export const TOY_RESULTS = 5;
export const LINK_OPTIONS = [3, 4, 8] as const;
export const EFFORT_OPTIONS = [1, 2, 5, 10, 20, 40] as const;
const POINTS_PER_GROUP = 18;
const BUILD_BEAM = 24;
const MAX_LAYER = 2;
const SEED = 20261202;

function mulberry32(seed: number) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function gaussian(random: () => number) {
  const u = Math.max(random(), 1e-9);
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * random());
}

export function toyPoints(): ToyPoint[] {
  const random = mulberry32(SEED);
  const points: ToyPoint[] = [];
  for (const group of TOY_GROUPS) {
    for (let i = 0; i < POINTS_PER_GROUP; i += 1) {
      const x = Math.min(MAP_WIDTH - 0.03, Math.max(0.03, group.x + gaussian(random) * 0.085));
      const y = Math.min(0.97, Math.max(0.03, group.y + gaussian(random) * 0.075));
      points.push({ id: points.length, x, y, group: group.name });
    }
  }
  return points;
}

const distance = (a: { x: number; y: number }, b: { x: number; y: number }) => Math.hypot(a.x - b.x, a.y - b.y);

/** Nearest-first list of `count` candidates; ties break on id so builds are repeatable. */
function nearest(points: ToyPoint[], target: { x: number; y: number }, ids: Iterable<number>, count: number) {
  return [...ids]
    .map((id) => ({ id, d: distance(points[id], target) }))
    .sort((a, b) => a.d - b.d || a.id - b.id)
    .slice(0, count)
    .map((item) => item.id);
}

/** Beam search on one layer, as HNSW's SEARCH-LAYER. Records checks and admissions. */
function searchLayer(
  index: Pick<ToyIndex, "points" | "links">,
  target: { x: number; y: number },
  entries: number[],
  beam: number,
  layer: number,
  trace?: TraceEvent[],
) {
  const { points, links } = index;
  const d = (id: number) => distance(points[id], target);
  const visited = new Set(entries);
  const candidates = [...entries];
  const found = [...entries];
  for (const id of entries) trace?.push({ kind: "admit", layer, node: id });
  while (candidates.length) {
    candidates.sort((a, b) => d(a) - d(b) || a - b);
    const current = candidates.shift()!;
    const worst = found.reduce((a, b) => (d(a) >= d(b) ? a : b));
    if (d(current) > d(worst) && found.length >= beam) break;
    for (const next of links[layer][current]) {
      if (visited.has(next)) continue;
      visited.add(next);
      trace?.push({ kind: "check", layer, node: next, from: current });
      const farthest = found.reduce((a, b) => (d(a) >= d(b) ? a : b));
      if (found.length < beam || d(next) < d(farthest)) {
        candidates.push(next);
        found.push(next);
        trace?.push({ kind: "admit", layer, node: next });
        if (found.length > beam) {
          found.splice(found.indexOf(farthest), 1);
          trace?.push({ kind: "evict", layer, node: farthest });
        }
      }
    }
  }
  return { found: found.sort((a, b) => d(a) - d(b) || a - b), visited };
}

/** Greedy walk on an upper layer: move to any closer neighbour until none is closer. */
function greedy(index: Pick<ToyIndex, "points" | "links">, target: { x: number; y: number }, start: number,
  layer: number, trace?: TraceEvent[]) {
  const { points, links } = index;
  let current = start;
  let improved = true;
  while (improved) {
    improved = false;
    const from = current;
    for (const next of links[layer][from]) {
      trace?.push({ kind: "check", layer, node: next, from });
      if (distance(points[next], target) < distance(points[current], target)) current = next;
    }
    if (current !== from) {
      trace?.push({ kind: "move", layer, node: current, from });
      improved = true;
    }
  }
  return current;
}

/** Build an HNSW graph with `m` links per node (2m on the bottom layer), as pgvector does. */
export function buildToyIndex(m: number): ToyIndex {
  const points = toyPoints();
  const random = mulberry32(SEED ^ (m * 7919));
  const levelScale = 1 / Math.log(m);
  const levels = points.map(() => Math.min(MAX_LAYER, Math.floor(-Math.log(Math.max(random(), 1e-9)) * levelScale)));
  const links: number[][][] = Array.from({ length: MAX_LAYER + 1 }, () => points.map(() => []));
  const order = points.map((p) => p.id).sort((a, b) => levels[b] - levels[a] || a - b);
  const index: ToyIndex = { points, levels, links, entry: order[0], top: levels[order[0]], m };
  const inserted: number[] = [order[0]];
  for (const id of order.slice(1)) {
    const target = points[id];
    let entry = index.entry;
    for (let layer = index.top; layer > levels[id]; layer -= 1) entry = greedy(index, target, entry, layer);
    let entries = [entry];
    for (let layer = Math.min(levels[id], index.top); layer >= 0; layer -= 1) {
      const { found } = searchLayer(index, target, entries, BUILD_BEAM, layer);
      const cap = layer === 0 ? 2 * m : m;
      const chosen = found.slice(0, m);
      links[layer][id] = chosen;
      for (const other of chosen) {
        const list = links[layer][other];
        list.push(id);
        if (list.length > cap) links[layer][other] = nearest(points, points[other], list, cap);
      }
      entries = found;
    }
    inserted.push(id);
  }
  return index;
}

/** Search the index the way pgvector does: greedy descent, then a beam of `effort` on layer 0. */
export function searchToyIndex(index: ToyIndex, target: { x: number; y: number }, effort: number, k = TOY_RESULTS): ToySearch {
  const trace: TraceEvent[] = [];
  let entry = index.entry;
  trace.push({ kind: "descend", layer: index.top, node: entry });
  for (let layer = index.top; layer > 0; layer -= 1) {
    entry = greedy(index, target, entry, layer, trace);
    trace.push({ kind: "descend", layer: layer - 1, node: entry });
  }
  const { found } = searchLayer(index, target, [entry], Math.max(effort, 1), 0, trace);
  // The beam never holds more than ef_search candidates, so one index scan returns at most
  // ef_search rows, as pgvector does.
  const results = found.slice(0, k);
  const exact = nearest(index.points, target, index.points.map((p) => p.id), k);
  const checked = new Set<number>([index.entry]);
  for (const event of trace) if (event.kind === "check") checked.add(event.node);
  return {
    results,
    exact,
    checks: checked.size,
    trace,
    recall: results.filter((id) => exact.includes(id)).length / k,
  };
}
