import type { Domain, ProductSummary } from "./types";

const ASSETS = "/assets/images";

export const domainMedia: Record<Domain, string> = {
  consumer_electronics: `${ASSETS}/mosaic/auraluxe-h9.webp`,
  running_fitness: `${ASSETS}/mosaic/stride-pro.webp`,
  home_office: `${ASSETS}/mosaic/forma-ergonomic-thumb.webp`,
};

type MosaicImageSet = [RegExp, string[]];

const mosaicProductImageSets: MosaicImageSet[] = [
  [
    /\bauraluxe(?:\s+h?9)?\b/i,
    [
      `${ASSETS}/mosaic/auraluxe-h9.webp`,
      `${ASSETS}/mosaic/auraluxe-h9-scene.webp`,
      `${ASSETS}/mosaic/auraluxe-h9-alt.webp`,
      `${ASSETS}/mosaic/auraluxe-h9-studio.webp`,
    ],
  ],
  [
    /\becho\s*bud\s*s?2\b/i,
    [
      `${ASSETS}/mosaic/echobud-s2.webp`,
      `${ASSETS}/mosaic/echobud-s2-scene.webp`,
      `${ASSETS}/mosaic/echobud-s2-alt.webp`,
      `${ASSETS}/mosaic/echobud-s2-studio.webp`,
    ],
  ],
  [
    /\bpulse\s*one\b/i,
    [
      `${ASSETS}/mosaic/pulse-one.webp`,
      `${ASSETS}/mosaic/pulse-one-scene.webp`,
      `${ASSETS}/mosaic/pulse-one-alt.webp`,
      `${ASSETS}/mosaic/pulse-one-studio.webp`,
    ],
  ],
  [
    /\bstride\s*pro\b/i,
    [
      `${ASSETS}/mosaic/stride-pro.webp`,
      `${ASSETS}/mosaic/stride-pro-scene.webp`,
      `${ASSETS}/mosaic/stride-pro-alt.webp`,
      `${ASSETS}/mosaic/stride-pro-studio.webp`,
    ],
  ],
  [
    /\bforma\s*ergonomic\b/i,
    [
      `${ASSETS}/mosaic/forma-ergonomic.webp`,
      `${ASSETS}/mosaic/forma-ergonomic-scene.webp`,
      `${ASSETS}/mosaic/forma-ergonomic-alt.webp`,
      `${ASSETS}/mosaic/forma-ergonomic-studio.webp`,
    ],
  ],
  [
    /\batelier\s*32\b/i,
    [
      `${ASSETS}/mosaic/atelier-32.webp`,
      `${ASSETS}/mosaic/atelier-32-scene.webp`,
      `${ASSETS}/mosaic/atelier-32-alt.webp`,
      `${ASSETS}/mosaic/atelier-32-studio.webp`,
    ],
  ],
  [
    /\bmelody\s*go\b/i,
    [`${ASSETS}/mosaic/melody-go-scene.webp`, `${ASSETS}/mosaic/melody-go-alt.webp`],
  ],
  [
    /\blume\s*desk\s*lamp\b/i,
    [
      `${ASSETS}/mosaic/lume-desk-lamp-scene.webp`,
      `${ASSETS}/mosaic/lume-desk-lamp-alt.webp`,
    ],
  ],
  [
    /\bcarryall\s*sleeve\b/i,
    [`${ASSETS}/mosaic/carryall-sleeve.webp`],
  ],
  [
    /\bflux\s*wireless\s*pad\b/i,
    [
      `${ASSETS}/mosaic/flux-wireless-pad-scene.webp`,
      `${ASSETS}/mosaic/flux-wireless-pad-alt.webp`,
    ],
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
  return [product.title, product.category, product.subcategory, product.brand, product.model].join(" ");
}

function matchingMosaicImageSet(product: ProductSummary): string[] | undefined {
  return mosaicProductImageSets.find(([pattern]) => pattern.test(productSearchText(product)))?.[1];
}

/**
 * The API owns product-to-media identity after the media mapping is loaded.
 * These screened local assets cover empty or partially loaded development
 * databases without substituting a remote image service.
 */
const curatedImageByName: Array<[RegExp, string[]]> = [
  [
    /(earbud|true wireless|in-ear)/i,
    [
      `${ASSETS}/mosaic/echobud-s2.webp`,
      `${ASSETS}/mosaic/echobud-s2-scene.webp`,
      `${ASSETS}/mosaic/echobud-s2-alt.webp`,
      `${ASSETS}/mosaic/echobud-s2-studio.webp`,
      `${ASSETS}/curated/novasound-buds.webp`,
    ],
  ],
  [
    /(watch|wearable|tracker|band|ring)/i,
    [
      `${ASSETS}/mosaic/pulse-one.webp`,
      `${ASSETS}/mosaic/pulse-one-scene.webp`,
      `${ASSETS}/mosaic/pulse-one-alt.webp`,
      `${ASSETS}/mosaic/pulse-one-studio.webp`,
      `${ASSETS}/curated/orbit-watch.webp`,
    ],
  ],
  [
    /(keyboard)/i,
    [`${ASSETS}/curated/keysmith-keyboard.webp`, `${ASSETS}/catalog-keyboard.webp`],
  ],
  [
    /(lamp|lighting|light)/i,
    [
      `${ASSETS}/mosaic/lume-desk-lamp-scene.webp`,
      `${ASSETS}/mosaic/lume-desk-lamp-alt.webp`,
    ],
  ],
  [
    /(speaker|soundbar)/i,
    [`${ASSETS}/mosaic/melody-go-scene.webp`, `${ASSETS}/mosaic/melody-go-alt.webp`],
  ],
  [
    /(charger|charging|power bank|usb-c|wireless pad)/i,
    [
      `${ASSETS}/mosaic/flux-wireless-pad-scene.webp`,
      `${ASSETS}/mosaic/flux-wireless-pad-alt.webp`,
    ],
  ],
  [
    /(sleeve|case|bag|pouch)/i,
    [`${ASSETS}/mosaic/carryall-sleeve.webp`],
  ],
  [
    /(stand|riser|dock|mount)/i,
    [`${ASSETS}/curated/riser-laptop-stand.webp`, `${ASSETS}/catalog-stand.webp`],
  ],
  [
    /(monitor|display|ultrawide)/i,
    [
      `${ASSETS}/mosaic/atelier-32.webp`,
      `${ASSETS}/mosaic/atelier-32-scene.webp`,
      `${ASSETS}/mosaic/atelier-32-alt.webp`,
      `${ASSETS}/mosaic/atelier-32-studio.webp`,
      `${ASSETS}/curated/vistaview-monitor.webp`,
      `${ASSETS}/catalog-monitor.webp`,
    ],
  ],
  /* 1,294 Seating rows in the 5,000-product corpus, so this pool carries every
     chair angle available. */
  [
    /(chair|seating|stool)/i,
    [
      `${ASSETS}/mosaic/forma-ergonomic.webp`,
      `${ASSETS}/mosaic/forma-ergonomic-scene.webp`,
      `${ASSETS}/mosaic/forma-ergonomic-alt.webp`,
      `${ASSETS}/mosaic/forma-ergonomic-studio.webp`,
      `${ASSETS}/curated/formamesh-chair.webp`,
      `${ASSETS}/catalog-chair.webp`,
    ],
  ],
  /* 1,596 Road Running Shoes. */
  [
    /(shoe|sneaker|running|trail|walking)/i,
    [
      `${ASSETS}/mosaic/stride-pro.webp`,
      `${ASSETS}/mosaic/stride-pro-scene.webp`,
      `${ASSETS}/mosaic/stride-pro-alt.webp`,
      `${ASSETS}/mosaic/stride-pro-studio.webp`,
      `${ASSETS}/curated/aerostride-road.webp`,
      `${ASSETS}/catalog-shoe.webp`,
    ],
  ],
  /* 2,094 Over-Ear Headphones in the 5,000-product corpus share this pattern,
     so the pool needs breadth or a results grid repeats one photograph across
     adjacent cards. */
  [
    /(headphone|headset|over-ear|on-ear)/i,
    [
      `${ASSETS}/mosaic/auraluxe-h9.webp`,
      `${ASSETS}/mosaic/auraluxe-h9-scene.webp`,
      `${ASSETS}/mosaic/auraluxe-h9-alt.webp`,
      `${ASSETS}/mosaic/auraluxe-h9-studio.webp`,
      `${ASSETS}/curated/auraluxe-h95.webp`,
      `${ASSETS}/curated/halo-comfort-se.webp`,
      `${ASSETS}/curated/sonora-c720.webp`,
      `${ASSETS}/curated/sonora-xm5.webp`,
      `${ASSETS}/curated/luma-770nc.webp`,
      `${ASSETS}/curated/northstar-q45.webp`,
      `${ASSETS}/curated/sennova-momentum.webp`,
    ],
  ],
];

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

export function productImage(product: ProductSummary): string {
  const mosaicImages = matchingMosaicImageSet(product);
  if (mosaicImages) return mosaicImages[0];
  if (product.image_url?.startsWith("/")) return product.image_url;
  const searchable = productSearchText(product);
  const curated = curatedImageByName.find(([pattern]) => pattern.test(searchable));
  if (curated) {
    const images = curated[1];
    return images[spread(product.product_id, images.length)];
  }
  return domainMedia[product.domain];
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
