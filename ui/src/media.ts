import plateManifest from "../../data/media/category_plates.json";
import type { Domain, ProductSummary } from "./types";

const UNAVAILABLE_IMAGE = "/assets/images/product-unavailable.svg";

const neutralPlateByDomain = new Map(
  plateManifest.domain_neutral_plates
    .filter((plate) => plate.installed)
    .map((plate) => [plate.domain, `/assets/images/mosaic/${plate.plate_id}-catalog-3x2.webp`]),
);

/**
 * A still-life for the domain that shows no product.
 *
 * For views that know a product's identity but not its listing photograph, so
 * no row is illustrated with a picture of a different product.
 */
export function domainIllustration(domain: Domain): string {
  return neutralPlateByDomain.get(domain) ?? UNAVAILABLE_IMAGE;
}

/** The listing's own photograph, or the unavailable placeholder. */
export function productImage(product: ProductSummary): string {
  return product.image_url || UNAVAILABLE_IMAGE;
}

/**
 * Keep a product's photo stable across Shop, ranking and the agent's shortlist.
 */
export function productImageMap(products: ProductSummary[]): Map<number, string> {
  const assigned = new Map<number, string>();
  for (const product of products) {
    if (assigned.has(product.product_id)) continue;
    assigned.set(product.product_id, productImage(product));
  }
  return assigned;
}

export const domainLabels: Record<Domain, string> = {
  consumer_electronics: "Consumer electronics",
  running_fitness: "Running & fitness",
  home_office: "Home office",
};
