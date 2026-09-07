import type { SearchFilters } from "./types";

export type EditorialStory = {
  topic: string;
  title: string;
  caption: string;
  query: string;
  image: string;
  imageFit?: "cover";
  filters: Pick<SearchFilters, "domain" | "category_key">;
};

/**
 * Three editorial entries below the hero, each of which runs a real request.
 *
 * They used to be three same-shaped white cards in a row. Now the first is a
 * full-width image-led band and the other two sit beside it as photographs with
 * their copy on bare canvas, so the section reads as an edit rather than as three
 * containers.
 */
export const editorialStories: EditorialStory[] = [
  {
    topic: "Over-ear headphones",
    title: "For focus, and for the long way home",
    caption:
      "Comfort, isolation, and battery life weighed together, not one at a time.",
    query: "Find the best over-ear headphones for focus and travel.",
    image: "/assets/images/mosaic/ce-over-ear-headphones-02-catalog-3x2.webp",
    // The catalog plates are 3:2 and this frame is wider, so it fills rather
    // than sitting letterboxed inside it.
    imageFit: "cover",
    filters: {
      domain: "consumer_electronics",
      category_key: "over-ear-headphones",
    },
  },
  {
    topic: "Workspace",
    title: "Made to be sat in all day",
    caption: "Fit, budget, and must-haves become real catalog constraints.",
    query:
      "Find an ergonomic mesh chair for long workdays with adjustable lumbar support.",
    image: "/assets/images/mosaic/category/workspace.webp",
    filters: {
      domain: "home_office",
      category_key: "ergonomic-office-chairs",
    },
  },
  {
    topic: "Running & fitness",
    title: "For the miles after the miles",
    caption: "Portable recovery tools for tired legs and limited carry-on space.",
    query: "Recovery tools for sore calves after long runs that fit in a carry-on.",
    image: "/assets/images/mosaic/category/performance.webp",
    imageFit: "cover",
    filters: {
      domain: "running_fitness",
      category_key: "mobility-tools",
    },
  },
];

export const merchandisingDoors: Array<{
  label: string;
  filters: SearchFilters;
  params: Record<string, string>;
}> = [
  {
    label: "Under $200",
    filters: { max_price_cents: 20000 },
    params: { max_price_cents: "20000" },
  },
  {
    label: "In stock now",
    filters: { in_stock_only: true },
    params: { in_stock_only: "true" },
  },
  {
    label: "Rated 4★ and up",
    filters: { min_rating: 4 },
    params: { min_rating: "4" },
  },
];
