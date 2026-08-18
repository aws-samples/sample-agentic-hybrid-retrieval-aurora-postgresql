import mediaManifest from "../../data/media/asset_labels_200.json";
import plateManifest from "../../data/media/category_plates.json";
import type { Domain, ProductSummary } from "./types";

const ASSETS = "/assets/images";

const catalogImageByProductId = new Map(
  mediaManifest.products
    .filter((product) => product.catalog_installed)
    .map((product) => [product.product_id, product.catalog_runtime_path]),
);

/** The manifest-bound catalog photograph for an exact product, when installed. */
export function productBoundImage(productId: number): string | null {
  return catalogImageByProductId.get(productId) ?? null;
}

/**
 * Last resort, and unreachable while all three domain-neutral plates exist.
 *
 * Each of these is a photograph of one specific product, so as a fallback it
 * answers "no image exists for this row" with a picture of something else:
 * mesh Wi-Fi systems illustrated with headphones, sound-masking devices with an
 * office chair. `domain_neutral_plates` in the plate manifest replaces each one
 * with a still-life that shows no product at all, which is the honest form of
 * the same fallback, and all three are now installed.
 *
 * This stays as a guard because `installed` is editable data: a plate that fails
 * review gets switched off, and a domain with no neutral plate still has to
 * render something. `media.test.ts` asserts the guard is out of reach, so
 * switching one off turns that test red rather than quietly reinstating a
 * photograph of the Auraluxe H9 across a whole domain.
 */
export const domainMedia: Record<Domain, string> = {
  consumer_electronics: `${ASSETS}/mosaic/auraluxe-h9-studio.webp`,
  running_fitness: `${ASSETS}/mosaic/stride-pro-studio.webp`,
  home_office: `${ASSETS}/mosaic/forma-ergonomic-studio.webp`,
};

type MosaicImageSet = [RegExp, string[]];

/**
 * One image per product, deliberately.
 *
 * These sets previously carried `-scene`/`-alt`/`-studio` companions presented
 * as alternate shots of the same product. They are not: the files were
 * generated in separate passes and the industrial design drifted between them,
 * so the EchoBud S2 rail showed a stem bud in a branded rectangular case
 * alongside stemless maroon-tipped beans in an unbranded oval one. A gallery
 * that pairs a product with photographs of a different product is worse than a
 * gallery with a single image, so only the shot verified to match each product
 * is kept. Real multi-image galleries come from `product.media`, which the API
 * owns; the gallery in ProductPage unions that in.
 */
const mosaicProductImageSets: MosaicImageSet[] = [
  /* auraluxe-h9.webp carries a third-party audio brand's logo on the earcup
     and a different industrial design from the cohort catalog photography;
     the studio shot is the same product as the catalog assets, logo-free. */
  [/\bauraluxe(?:\s+h?9)?\b/i, [`${ASSETS}/mosaic/auraluxe-h9-studio.webp`]],
  [/\becho\s*bud\s*s?2\b/i, [`${ASSETS}/mosaic/echobud-s2.webp`]],
  [/\bpulse\s*one\b/i, [`${ASSETS}/mosaic/pulse-one.webp`]],
  [/\bstride\s*pro\b/i, [`${ASSETS}/mosaic/stride-pro-studio.webp`]],
  [/\bforma\s*ergonomic\b/i, [`${ASSETS}/mosaic/forma-ergonomic-studio.webp`]],
  [/\batelier\s*32\b/i, [`${ASSETS}/mosaic/atelier-32.webp`]],
  [/\bmelody\s*go\b/i, [`${ASSETS}/mosaic/melody-go-scene.webp`]],
  [/\blume\s*desk\s*lamp\b/i, [`${ASSETS}/mosaic/lume-desk-lamp-scene.webp`]],
  [/\bcarryall\s*sleeve\b/i, [`${ASSETS}/mosaic/carryall-sleeve.webp`]],
  [
    /\bflux\s*wireless\s*pad\b/i,
    [`${ASSETS}/mosaic/flux-wireless-pad-scene.webp`],
  ],
];

const posterByProductName: Array<[RegExp, { src: string; alt: string }]> = [
  [
    /\becho\s*bud\s*s?2\b/i,
    {
      src: `${ASSETS}/mosaic/posters/02-echobud-s2-poster.png`,
      alt: "Mosaic EchoBud S2 campaign poster",
    },
  ],
  [
    /\bpulse\s*one\b/i,
    {
      src: `${ASSETS}/mosaic/posters/03-pulse-one-poster.png`,
      alt: "Mosaic Pulse One campaign poster",
    },
  ],
  [
    /\bstride\s*pro\b/i,
    {
      src: `${ASSETS}/mosaic/posters/04-stride-pro-poster.png`,
      alt: "Mosaic Stride Pro campaign poster",
    },
  ],
  [
    /\batelier\s*32\b/i,
    {
      src: `${ASSETS}/mosaic/posters/06-atelier-32-poster.png`,
      alt: "Mosaic Atelier 32 campaign poster",
    },
  ],
];

function productSearchText(product: ProductSummary): string {
  return [product.title, product.category_path, product.brand, product.model].join(" ");
}

function matchingMosaicImageSet(product: ProductSummary): string[] | undefined {
  return mosaicProductImageSets.find(([pattern]) => pattern.test(productSearchText(product)))?.[1];
}

/**
 * The corpus holds 500,000 products and a 200-product exact-photography set, so
 * most rows a query returns are filled from a category pool rather than from
 * their own shot.
 *
 * Pools are keyed by the API's `category_key`, not by a regex over the title.
 * The regex version matched on substrings and so illustrated whole categories
 * with the wrong object: `/stand/` claimed every electric standing desk for a
 * laptop riser, and `mesh-wi-fi-systems` matched no pattern at all and fell
 * through to a photograph of headphones. An exact category identity cannot make
 * that mistake; an unmatched category gets a neutral still-life instead.
 */
const categoryPools = buildCategoryPools();

const neutralPlateByDomain = new Map(
  plateManifest.domain_neutral_plates
    .filter((plate) => plate.installed)
    .map((plate) => [plate.domain, platePath(plate.plate_id)]),
);

function platePath(plateId: string): string {
  return `${ASSETS}/mosaic/${plateId}-catalog-3x2.webp`;
}

/**
 * The service's category slug, from `db/scripts/transform_legacy_catalog.py`.
 */
function slugify(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

/**
 * Exact images are product-bound, and they are also the only photograph many
 * categories have, so each one joins the pool for its own category. The product
 * it was shot for still gets it first, from `catalogImageByProductId`.
 *
 * A manifest row is registered under both forms the service can emit for its
 * category: the bare subcategory slug, and the fully qualified
 * domain-family-subcategory slug it falls back to when two domains share a
 * subcategory name. Registering both is exact rather than a guess. The
 * qualified form is reachable only by that one triple, and the bare form only
 * when no other domain claims the name, because a collision is precisely what
 * makes the service emit the qualified key instead. "Portable Monitors" is the
 * live collision, under Computing in consumer electronics and Displays in home
 * office.
 */
function buildCategoryPools(): Map<string, string[]> {
  const pools = new Map<string, string[]>();
  const add = (key: string, path: string) => {
    const pool = pools.get(key);
    if (!pool) {
      pools.set(key, [path]);
    } else if (!pool.includes(path)) {
      pool.push(path);
    }
  };
  for (const product of mediaManifest.products) {
    if (!product.catalog_installed) continue;
    add(slugify(product.subcategory), product.catalog_runtime_path);
    add(
      slugify(`${product.domain} ${product.category} ${product.subcategory}`),
      product.catalog_runtime_path,
    );
  }
  for (const plate of plateManifest.plates) {
    if (plate.installed) add(plate.category_key, platePath(plate.plate_id));
  }
  return pools;
}

/**
 * Categories whose photography is interchangeable on sight, used only after a
 * category's own pool is exhausted.
 *
 * This is a short list on purpose. A carbon racer standing in for a road shoe
 * is a running shoe either way, so a participant reads a varied catalog rather
 * than a mistake. Anything looser is how a treadmill ends up illustrated with
 * an exercise bike, and the workshop is a demonstration of retrieval accuracy.
 */
const relatedCategories: Record<string, string[]> = {
  "trail-running-shoes": ["road-running-shoes", "carbon-racing-shoes", "cross-training-shoes"],
  "road-running-shoes": ["carbon-racing-shoes", "cross-training-shoes"],
  "carbon-racing-shoes": ["road-running-shoes", "cross-training-shoes"],
  "cross-training-shoes": ["road-running-shoes", "carbon-racing-shoes"],
  "quiet-keyboards": ["mechanical-keyboards", "ergonomic-keyboards"],
  "mechanical-keyboards": ["quiet-keyboards", "ergonomic-keyboards"],
  "ergonomic-keyboards": ["quiet-keyboards", "mechanical-keyboards"],
};

/**
 * Mixes a product id so neighbouring ids land on unrelated assets.
 *
 * Catalog ids arrive sorted and evenly spaced, so `id % assetCount` cycles
 * through a subset and repeats one photograph across adjacent cards.
 */
function spread(productId: number, assetCount: number): number {
  // Math.imul keeps the multiply in 32 bits; a plain `*` produces a float and
  // loses the high bits the mix depends on.
  let hash = (Math.abs(productId) + 0x9e3779b9) | 0;
  hash = Math.imul(hash ^ (hash >>> 16), 0x21f0aaad);
  hash = Math.imul(hash ^ (hash >>> 15), 0x735a2d97);
  hash ^= hash >>> 15;
  return (hash >>> 0) % assetCount;
}

/**
 * Generated photography. Anything outside it is the scraped substrate that the
 * category pools replaced, and a database column may still point into it.
 *
 * `data/full/product_image_urls.csv.gz` maps installed exact products into this
 * namespace and sends the remaining corpus to category fallbacks. A path is
 * still trusted only if it names the generated namespace, so stale catalog data
 * cannot bypass the governed pools.
 */
const GENERATED_PREFIX = `${ASSETS}/mosaic/`;

type CategoryImageProduct = Pick<
  ProductSummary,
  "product_id" | "domain" | "category_key"
>;

/**
 * The photograph that belongs to this exact product, or null if none does.
 *
 * The 200-product manifest is the product-to-media contract. Some older
 * database rows still carry square detail photography in image_url; using those
 * in a 3:2 catalog card creates letterboxing and obscures the catalog shot
 * selected for this exact product.
 */
function boundImage(product: ProductSummary): string | null {
  const catalogImage = productBoundImage(product.product_id);
  if (catalogImage) return catalogImage;
  if (product.image_url?.startsWith(GENERATED_PREFIX)) return product.image_url;
  return matchingMosaicImageSet(product)?.[0] ?? null;
}

/** Every photograph eligible for a row in this category, best match first. */
function categoryPool(product: CategoryImageProduct): string[] {
  const primary = categoryPools.get(product.category_key) ?? [];
  const related = (relatedCategories[product.category_key] ?? [])
    .flatMap((key) => categoryPools.get(key) ?? [])
    .filter((path) => !primary.includes(path));
  const pool = [...primary, ...related];
  if (pool.length) return pool;
  return [neutralPlateByDomain.get(product.domain) ?? domainMedia[product.domain]];
}

/**
 * A category-verified product photograph for a row that has no bound image.
 *
 * This does not claim that the pictured product is the exact SKU. Callers must keep
 * that provenance visible anywhere the image could be read as product-bound.
 */
export function categoryProductImage(product: CategoryImageProduct): string {
  const pool = categoryPool(product);
  return pool[spread(product.product_id, pool.length)];
}

/**
 * Assign representative category photography across a set without avoidable repeats.
 *
 * `reserved` contains exact product images already visible in the same composition, so
 * a representative node does not immediately reuse the anchor's photograph while an
 * unused image remains in the category pool.
 */
export function categoryProductImageMap(
  products: CategoryImageProduct[],
  reserved: Iterable<string> = [],
): Map<number, string> {
  const assigned = new Map<number, string>();
  const uses = new Map<string, number>();
  for (const path of reserved) {
    uses.set(path, (uses.get(path) ?? 0) + 1);
  }
  for (const product of products) {
    if (assigned.has(product.product_id)) continue;
    const pool = categoryPool(product);
    const chosen = leastUsed(pool, spread(product.product_id, pool.length), uses);
    uses.set(chosen, (uses.get(chosen) ?? 0) + 1);
    assigned.set(product.product_id, chosen);
  }
  return assigned;
}

export function productImage(product: ProductSummary): string {
  const bound = boundImage(product);
  if (bound) return bound;
  return categoryProductImage(product);
}

/**
 * The pool entry used fewest times so far, scanned from this row's preference.
 *
 * An unused photograph always wins, so a grid whose pool is large enough repeats
 * nothing. Past that point this spreads the surplus evenly instead of letting
 * one photograph absorb it, which bounds any grid at ceil(rows / pool) copies of
 * a single file and puts the duplicates as far apart as the pool allows.
 */
function leastUsed(pool: string[], start: number, uses: Map<string, number>): string {
  let chosen = pool[start];
  let fewest = Infinity;
  for (let step = 0; step < pool.length; step += 1) {
    const candidate = pool[(start + step) % pool.length];
    const count = uses.get(candidate) ?? 0;
    if (count < fewest) {
      chosen = candidate;
      fewest = count;
      if (count === 0) break;
    }
  }
  return chosen;
}

/**
 * Assign one photograph per product across a whole result set, avoiding repeats.
 *
 * Hashing a product id into a pool cannot do this. Twelve independent draws from
 * a pool of twelve yield about 7.7 distinct values, so a full grid always
 * repeated something even where the pool was large enough. This walks the result
 * list instead: product-bound photography is placed first and reserves its file,
 * then each remaining row takes the least-used photograph in its category pool.
 *
 * The cost is that a filler row's photograph depends on the result set it appears
 * in, so the same product can show a different plate under a different query.
 * That is the price of the guarantee, and it only ever applies to rows that have
 * no photograph of their own. A pool smaller than the number of rows drawing from
 * it still repeats, evenly, which is the honest signal that the category needs
 * plates rather than a photograph of something else.
 */
export function productImageMap(products: ProductSummary[]): Map<number, string> {
  const assigned = new Map<number, string>();
  const uses = new Map<string, number>();
  const filler: ProductSummary[] = [];

  for (const product of products) {
    if (assigned.has(product.product_id)) continue;
    const bound = boundImage(product);
    if (bound) {
      assigned.set(product.product_id, bound);
      uses.set(bound, (uses.get(bound) ?? 0) + 1);
    } else {
      filler.push(product);
    }
  }

  for (const product of filler) {
    if (assigned.has(product.product_id)) continue;
    const pool = categoryPool(product);
    const chosen = leastUsed(pool, spread(product.product_id, pool.length), uses);
    uses.set(chosen, (uses.get(chosen) ?? 0) + 1);
    assigned.set(product.product_id, chosen);
  }

  return assigned;
}

export function productImages(product: ProductSummary): string[] {
  return matchingMosaicImageSet(product) ?? [productImage(product)];
}

export function productEditorialPoster(product: ProductSummary) {
  return posterByProductName.find(([pattern]) => pattern.test(productSearchText(product)))?.[1] ?? null;
}

export const domainLabels: Record<Domain, string> = {
  consumer_electronics: "Consumer electronics",
  running_fitness: "Running & fitness",
  home_office: "Home office",
};
