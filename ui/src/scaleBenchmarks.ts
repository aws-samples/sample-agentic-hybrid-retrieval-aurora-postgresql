import type { HnswFilterLevel, HnswFilterMode } from "./types";

export const scanModes = ["off", "strict_order", "relaxed_order"] as const;

/** Compare scan ordering only when search effort and memory are held constant. */
export function comparableScanModes(level?: HnswFilterLevel): HnswFilterMode[] {
  const groups = new Map<string, HnswFilterMode[]>();
  for (const mode of level?.modes ?? []) {
    const key = `${mode.ef_search}:${mode.scan_mem_multiplier}:${mode.scan_mem_mb}`;
    groups.set(key, [...groups.get(key) ?? [], mode]);
  }
  const complete = [...groups.values()].filter((group) => scanModes.every((key) => group.some((mode) => mode.iterative_scan === key)));
  complete.sort((a, b) => a[0].scan_mem_mb - b[0].scan_mem_mb || (a[0].ef_search != null && b[0].ef_search != null ? a[0].ef_search - b[0].ef_search : 0));
  return complete[0] ? scanModes.map((key) => complete[0].find((mode) => mode.iterative_scan === key)!) : [];
}
