import { showcaseProductDetail } from "./showcase";
import type { ProductSummary } from "./types";

export type StudioZoneFixture = {
  zone: string;
  className: string;
  brief: string;
  productIds: readonly number[];
};

export type StudioBriefFixture = {
  id: string;
  label: string;
  title: string;
  description: string;
  zones: readonly StudioZoneFixture[];
};

function fixtureProduct(productId: number): ProductSummary {
  const product = showcaseProductDetail(productId);
  if (!product) {
    throw new Error(
      `Mosaic Studio fixture references product ${productId}, which is not present in the local premium cohort.`,
    );
  }
  return product;
}

/**
 * Curated catalog compositions for the optional Mosaic Studio visual study.
 *
 * These are intentionally not client-side retrieval results. The phrasing
 * remains visible so people can see the human brief behind each composition,
 * while Shop and the Labs Explore view remain the proof surfaces for live
 * hybrid retrieval.
 */
export const STUDIO_BRIEFS: readonly StudioBriefFixture[] = [
  {
    id: "creative-focus",
    label: "Creative focus",
    title: "A creative studio, composed with intent.",
    description:
      "A quiet, capable starting point for long creative days: ergonomic support, visual room to think, and tactile input.",
    zones: [
      {
        zone: "Focus seating",
        className: "studio-piece-seat",
        brief: "a quiet ergonomic chair for long creative focus sessions",
        productIds: [370001, 370002, 370003],
      },
      {
        zone: "Visual work",
        className: "studio-piece-display",
        brief: "a spacious visual work surface for detailed creative work",
        productIds: [420001, 420002, 474001],
      },
      {
        zone: "Quiet input",
        className: "studio-piece-input",
        brief: "quiet tactile input for a shared creative workspace",
        productIds: [429001, 429002, 434091],
      },
    ],
  },
  {
    id: "shared-studio",
    label: "Shared studio",
    title: "A calm setup for shared creative work.",
    description:
      "Prioritize adjustable support, a collaborative visual surface, and low-distraction input for a room where focus is shared.",
    zones: [
      {
        zone: "Supported seating",
        className: "studio-piece-seat",
        brief: "adjustable seating for long shared studio days",
        productIds: [370002, 370001, 370003],
      },
      {
        zone: "Shared visual work",
        className: "studio-piece-display",
        brief: "an open visual surface for collaborative editing",
        productIds: [420002, 420001, 474001],
      },
      {
        zone: "Shared input",
        className: "studio-piece-input",
        brief: "quiet wireless input for a shared creative workspace",
        productIds: [429002, 429001, 434091],
      },
    ],
  },
  {
    id: "design-desk",
    label: "Design desk",
    title: "A focused desk for detailed visual work.",
    description:
      "Shift toward a compact ergonomic seat, a precise visual surface, and quiet tactile input for long individual sessions.",
    zones: [
      {
        zone: "Compact seating",
        className: "studio-piece-seat",
        brief: "ergonomic seating for a compact creative desk",
        productIds: [370003, 370001, 370002],
      },
      {
        zone: "Detailed visual work",
        className: "studio-piece-display",
        brief: "a precise visual surface for detailed design",
        productIds: [420001, 420002, 474001],
      },
      {
        zone: "Focused input",
        className: "studio-piece-input",
        brief: "quiet mechanical input for focused work",
        productIds: [434091, 429001, 429002],
      },
    ],
  },
] as const;

export const STUDIO_CANDIDATES: ReadonlyMap<number, ProductSummary> = new Map(
  Array.from(
    new Set(STUDIO_BRIEFS.flatMap((brief) => brief.zones.flatMap((zone) => zone.productIds))),
  ).map((productId) => [productId, fixtureProduct(productId)]),
);

export function studioCandidates(zone: StudioZoneFixture): readonly ProductSummary[] {
  return zone.productIds.map((productId) => {
    const product = STUDIO_CANDIDATES.get(productId);
    if (!product) {
      throw new Error(`Mosaic Studio fixture product ${productId} is unavailable.`);
    }
    return product;
  });
}
