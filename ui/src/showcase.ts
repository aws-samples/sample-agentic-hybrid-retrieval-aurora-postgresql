import { productImages } from "./media";
import mediaManifest from "../../data/media/asset_labels_120.json";
import premiumCohort from "../../db/data/premium_cohort_120.json";
import type {
  Availability,
  CatalogPage,
  Domain,
  ProductDetail,
  ProductSummary,
  SearchFilters,
  SearchResponse,
} from "./types";

type ShowcaseSeed = {
  product_id: number;
  model: string;
  domain: Domain;
  category: string;
  subcategory: string;
  price_usd: number;
  image_url: string;
  short_description: string;
  long_description: string;
  attributes: Record<string, string>;
  tags: string[];
  sku?: string;
  media_tier?: string;
  is_flagship?: boolean;
  is_retrieval_anchor?: boolean;
  catalog_asset_key?: string;
  image_source?: string;
};

type PremiumCohortRow = Omit<(typeof premiumCohort)[number], "domain"> & {
  domain: Domain;
};
type MediaManifestRow = (typeof mediaManifest.products)[number];

function categoryKey(value: string) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
}

function showcaseRating(item: ShowcaseSeed) {
  const ratings = [5, 4.9, 4.7, 4.5, 4.3] as const;
  return ratings[Math.abs(item.product_id) % ratings.length];
}

function showcaseReviewCount(item: ShowcaseSeed) {
  return 84 + (Math.abs(item.product_id * 37) % 620);
}

function showcaseAvailability(item: ShowcaseSeed): Availability {
  const availability: Availability[] = ["in_stock", "in_stock", "low_stock", "in_stock", "preorder"];
  return availability[Math.abs(item.product_id) % availability.length];
}

function matchesFilters(item: ShowcaseSeed, filters: SearchFilters) {
  const priceCents = item.price_usd * 100;
  const itemCategoryKey = categoryKey(item.subcategory);

  return (
    (!filters.domain || item.domain === filters.domain) &&
    (!filters.category_key || itemCategoryKey === filters.category_key) &&
    (!filters.min_price_cents || priceCents >= filters.min_price_cents) &&
    (!filters.max_price_cents || priceCents <= filters.max_price_cents) &&
    (!filters.min_rating || showcaseRating(item) >= filters.min_rating) &&
    (!filters.availability || showcaseAvailability(item) === filters.availability)
  );
}

const showcaseSeed: ShowcaseSeed[] = [
  {
    product_id: 1,
    model: "Auraluxe H9",
    domain: "consumer_electronics",
    category: "Audio",
    subcategory: "Over-Ear Headphones",
    price_usd: 349,
    image_url: "/assets/images/mosaic/auraluxe-h9.webp",
    short_description: "Adaptive over-ear listening for focused work and travel.",
    long_description: "Mosaic Auraluxe H9 pairs adaptive noise cancellation, comfortable all-day materials, and high-resolution wireless listening for deep-focus sessions.",
    attributes: { battery: "60 hours", connectivity: "Bluetooth multipoint", cancellation: "Adaptive ANC" },
    tags: ["Focus", "Travel"],
  },
  {
    product_id: 17001,
    model: "EchoBud S2",
    domain: "consumer_electronics",
    category: "Audio",
    subcategory: "Wireless Earbuds",
    price_usd: 129,
    image_url: "/assets/images/mosaic/echobud-s2.webp",
    short_description: "Compact wireless earbuds with quiet, clear everyday listening.",
    long_description: "Mosaic EchoBud S2 combines active noise cancellation, a three-microphone call system, and a compact charging case made for commutes and everyday carry.",
    attributes: { battery: "28 hours with case", cancellation: "Active noise cancellation", fit: "Pocket-friendly" },
    tags: ["Audio", "Everyday carry"],
  },
  {
    product_id: 116001,
    model: "Pulse One",
    domain: "consumer_electronics",
    category: "Wearables",
    subcategory: "Smart Watch",
    price_usd: 229,
    image_url: "/assets/images/mosaic/pulse-one.webp",
    short_description: "A refined training and health companion with room to breathe.",
    long_description: "Mosaic Pulse One brings together GPS, daily health signals, sleep tracking, and a seven-day battery in a durable, understated watch.",
    attributes: { battery: "7 days", tracking: "GPS and health", water_resistance: "5 ATM" },
    tags: ["Training", "Health"],
  },
  {
    product_id: 234001,
    model: "Stride Pro",
    domain: "running_fitness",
    category: "Footwear",
    subcategory: "Carbon Racing Shoes",
    price_usd: 159,
    image_url: "/assets/images/mosaic/rf-carbon-racing-shoes-stride-pro-catalog-3x2.webp",
    short_description: "Responsive road-running cushioning for everyday miles.",
    long_description: "Mosaic Stride Pro balances an energetic foam midsole, breathable engineered upper, and stable geometry for daily training and long-distance comfort.",
    attributes: { terrain: "Road", cushioning: "Responsive foam", upper: "Engineered mesh" },
    tags: ["Running", "Daily trainer"],
  },
  {
    product_id: 370001,
    model: "Forma Ergonomic",
    domain: "home_office",
    category: "Furniture",
    subcategory: "Task Chair",
    price_usd: 699,
    image_url: "/assets/images/mosaic/forma-ergonomic-studio.webp",
    short_description: "Adaptive, breathable seating designed for long working days.",
    long_description: "Mosaic Forma Ergonomic combines synchronized recline, adaptive lumbar support, adjustable seat depth, and a breathable suspension back.",
    attributes: { lumbar: "Adaptive support", armrests: "4D adjustable", recline: "Synchronized" },
    tags: ["Workspace", "Ergonomic"],
  },
  {
    product_id: 420001,
    model: "Atelier 32",
    domain: "home_office",
    category: "Workspace",
    subcategory: "4K Monitor Display",
    price_usd: 499,
    image_url: "/assets/images/mosaic/atelier-32.webp",
    short_description: "A calibrated 4K display for clear, spacious desk work.",
    long_description: "Mosaic Atelier 32 combines a color-accurate 4K IPS panel, single-cable USB-C power, and a minimal height-adjustable stand for focused creative work.",
    attributes: { resolution: "4K UHD", panel: "IPS", connectivity: "USB-C" },
    tags: ["Creative work", "Workspace"],
  },
  {
    product_id: 700001,
    model: "Melody Go",
    domain: "consumer_electronics",
    category: "Audio",
    subcategory: "Portable Speaker",
    price_usd: 99,
    image_url: "/assets/images/mosaic/melody-go-scene.webp",
    short_description: "A warm, portable speaker for the spaces between work and life.",
    long_description: "Mosaic Melody Go delivers room-filling sound, simple controls, and a compact profile designed to move easily from desk to weekend.",
    attributes: { battery: "16 hours", portability: "Grab-and-go", pairing: "Stereo pair ready" },
    tags: ["Audio", "Portable"],
  },
  {
    product_id: 700002,
    model: "Lume Desk Lamp",
    domain: "home_office",
    category: "Workspace",
    subcategory: "Adjustable LED Lamp",
    price_usd: 129,
    image_url: "/assets/images/mosaic/lume-desk-lamp-scene.webp",
    short_description: "A precise, warm desk light for late focus sessions.",
    long_description: "Mosaic Lume Desk Lamp provides smoothly adjustable task lighting, a warm evening setting, and a compact architectural base.",
    attributes: { color_temperature: "2700-5000K", controls: "Touch dimmer", power: "USB-C" },
    tags: ["Lighting", "Workspace"],
  },
  {
    product_id: 700003,
    model: "CarryAll Sleeve 16",
    domain: "home_office",
    category: "Accessories",
    subcategory: "Laptop Sleeve",
    price_usd: 69,
    image_url: "/assets/images/mosaic/carryall-sleeve.webp",
    short_description: "A structured 16-inch laptop sleeve with everyday protection.",
    long_description: "Mosaic CarryAll Sleeve 16 wraps a laptop in a refined, protective shell with a low-profile silhouette and dedicated accessory pocket.",
    attributes: { fit: "Up to 16-inch laptops", protection: "Padded lining", material: "Water-resistant weave" },
    tags: ["Travel", "Workspace"],
  },
  {
    product_id: 700004,
    model: "Flux Wireless Pad",
    domain: "consumer_electronics",
    category: "Accessories",
    subcategory: "Fast Charging Pad",
    price_usd: 59,
    image_url: "/assets/images/mosaic/flux-wireless-pad-scene.webp",
    short_description: "A quiet wireless charging surface for an uncluttered desk.",
    long_description: "Mosaic Flux Wireless Pad keeps compatible phones charged with a stable, low-profile surface and a clean visual footprint.",
    attributes: { charging: "Fast wireless", surface: "Soft-touch", power: "USB-C" },
    tags: ["Charging", "Desk setup"],
  },
  {
    product_id: 2,
    model: "Sonora WH-C720",
    domain: "consumer_electronics",
    category: "Audio",
    subcategory: "Over-Ear Headphones",
    price_usd: 279,
    image_url: "/assets/images/mosaic/ce-over-ear-headphones-02-catalog-3x2.webp",
    short_description: "Multi-mode noise cancellation for commutes and open offices.",
    long_description: "Sonora WH-C720 pairs multi-mode active noise cancellation with 50 hours of playtime and soft protein leather earcups for all-day wear.",
    attributes: { battery: "50 hours", cancellation: "Multi-mode ANC", earcups: "Protein leather" },
    tags: ["Commute", "Focus"],
  },
  {
    product_id: 3,
    model: "Northstar Space Q45",
    domain: "consumer_electronics",
    category: "Audio",
    subcategory: "Over-Ear Headphones",
    price_usd: 329,
    image_url: "/assets/images/mosaic/ce-over-ear-headphones-03-catalog-3x2.webp",
    short_description: "Adaptive cancellation that reads the room and adjusts.",
    long_description: "Northstar Space Q45 measures ambient noise continuously and adapts its cancellation profile, with a low-latency mode for calls.",
    attributes: { battery: "44 hours", cancellation: "Adaptive ANC", calls: "Low-latency mode" },
    tags: ["Travel", "Calls"],
  },
  {
    product_id: 4,
    model: "Halo Comfort SE",
    domain: "consumer_electronics",
    category: "Audio",
    subcategory: "Over-Ear Headphones",
    price_usd: 199,
    image_url: "/assets/images/mosaic/ce-over-ear-headphones-04-catalog-3x2.webp",
    short_description: "Lightweight over-ear listening built around long-session comfort.",
    long_description: "Halo Comfort SE keeps clamping force low and padding deep, so a full working day stays comfortable without sacrificing cancellation.",
    attributes: { battery: "38 hours", weight: "228 g", cancellation: "Hybrid ANC" },
    tags: ["Comfort", "Everyday"],
  },
  {
    product_id: 5,
    model: "LumaTone Live 770NC",
    domain: "consumer_electronics",
    category: "Audio",
    subcategory: "Over-Ear Headphones",
    price_usd: 249,
    image_url: "/assets/images/mosaic/ce-over-ear-headphones-05-catalog-3x2.webp",
    short_description: "Studio-leaning tuning with cancellation you can dial back.",
    long_description: "LumaTone Live 770NC offers a flatter reference tuning for critical listening and a stepped cancellation control for shared spaces.",
    attributes: { battery: "40 hours", tuning: "Reference", cancellation: "Stepped ANC" },
    tags: ["Listening", "Studio"],
  },
  {
    product_id: 17002,
    model: "EchoArc Air Pro 3",
    domain: "consumer_electronics",
    category: "Audio",
    subcategory: "True Wireless Earbuds",
    price_usd: 179,
    image_url: "/assets/images/mosaic/ce-true-wireless-earbuds-02-catalog-3x2.webp",
    short_description: "Compact earbuds with a secure fit for movement.",
    long_description: "EchoArc Air Pro 3 holds position through training and commuting, with a three-microphone call system and a pocketable charging case.",
    attributes: { battery: "30 hours with case", fit: "Secure wing", calls: "Three microphones" },
    tags: ["Training", "Everyday carry"],
  },
  {
    product_id: 17003,
    model: "Auraluxe EX",
    domain: "consumer_electronics",
    category: "Audio",
    subcategory: "True Wireless Earbuds",
    price_usd: 219,
    image_url: "/assets/images/mosaic/ce-true-wireless-earbuds-03-catalog-3x2.webp",
    short_description: "Premium earbuds tuned to match the Auraluxe over-ear family.",
    long_description: "Auraluxe EX carries the same tuning target as the over-ear range, so switching between them does not change the sound signature.",
    attributes: { battery: "26 hours with case", tuning: "Auraluxe target", cancellation: "Adaptive ANC" },
    tags: ["Audio", "Premium"],
  },
  {
    product_id: 30001,
    model: "Sonora Roam 2",
    domain: "consumer_electronics",
    category: "Audio",
    subcategory: "Portable Speakers",
    price_usd: 149,
    image_url: "/assets/images/mosaic/ce-portable-speakers-catalog-3x2.webp",
    short_description: "A room-filling portable speaker with a carry strap.",
    long_description: "Sonora Roam 2 delivers balanced sound at low volume as well as high, pairs in stereo, and runs 20 hours between charges.",
    attributes: { battery: "20 hours", pairing: "Stereo pair ready", water_resistance: "IP67" },
    tags: ["Portable", "Weekend"],
  },
  {
    product_id: 116002,
    model: "StrideWatch Apex 965",
    domain: "consumer_electronics",
    category: "Wearables",
    subcategory: "Smartwatches",
    price_usd: 349,
    image_url: "/assets/images/mosaic/ce-smartwatches-02-catalog-3x2.webp",
    short_description: "A performance smartwatch with multi-band positioning.",
    long_description: "StrideWatch Apex 965 tracks pace and route with multi-band GNSS, reads daily recovery signals, and runs 14 days in smartwatch mode.",
    attributes: { battery: "14 days", positioning: "Multi-band GNSS", water_resistance: "10 ATM" },
    tags: ["Training", "Health"],
  },
  {
    product_id: 210001,
    model: "AeroStride Cloud Road",
    domain: "running_fitness",
    category: "Footwear",
    subcategory: "Road Running Shoes",
    price_usd: 139,
    image_url: "/assets/images/mosaic/rf-road-running-shoes-01-catalog-3x2.webp",
    short_description: "A cushioned daily trainer for easy and long runs.",
    long_description: "AeroStride Cloud Road uses a soft, high-stack midsole and a stable heel for the miles that make up most of a training week.",
    attributes: { terrain: "Road", cushioning: "High stack", use: "Daily trainer" },
    tags: ["Running", "Daily trainer"],
  },
  {
    product_id: 210002,
    model: "PulseMotion Daily Flow",
    domain: "running_fitness",
    category: "Footwear",
    subcategory: "Road Running Shoes",
    price_usd: 129,
    image_url: "/assets/images/mosaic/rf-road-running-shoes-02-catalog-3x2.webp",
    short_description: "A responsive road shoe for mixed-pace weeks.",
    long_description: "PulseMotion Daily Flow balances a lighter midsole with a breathable upper, so the same shoe handles easy days and tempo efforts.",
    attributes: { terrain: "Road", cushioning: "Responsive", upper: "Engineered mesh" },
    tags: ["Running", "Tempo"],
  },
  {
    product_id: 234002,
    model: "Velocity Carbon 3",
    domain: "running_fitness",
    category: "Footwear",
    subcategory: "Carbon Racing Shoes",
    price_usd: 259,
    image_url: "/assets/images/mosaic/rf-carbon-racing-shoes-02-catalog-3x2.webp",
    short_description: "A carbon-plated racer built for long-distance efficiency.",
    long_description: "Velocity Carbon 3 pairs a full-length carbon plate with a resilient supercritical foam for marathon-distance economy.",
    attributes: { plate: "Full-length carbon", distance: "Marathon", drop: "8 mm" },
    tags: ["Racing", "Marathon"],
  },
  {
    product_id: 370002,
    model: "PostureWorks Pro Mesh",
    domain: "home_office",
    category: "Seating",
    subcategory: "Ergonomic Office Chairs",
    price_usd: 599,
    image_url: "/assets/images/mosaic/ho-ergonomic-office-chairs-02-catalog-3x2.webp",
    short_description: "A breathable mesh chair with adjustable lumbar support.",
    long_description: "PostureWorks Pro Mesh combines a tensioned mesh back, height-and-depth lumbar adjustment, and a synchronised recline.",
    attributes: { back: "Tensioned mesh", lumbar: "Height and depth", recline: "Synchronised" },
    tags: ["Workspace", "Ergonomic"],
  },
  {
    product_id: 370003,
    model: "LumaSeat Executive Air",
    domain: "home_office",
    category: "Seating",
    subcategory: "Ergonomic Office Chairs",
    price_usd: 749,
    image_url: "/assets/images/mosaic/ho-ergonomic-office-chairs-03-catalog-3x2.webp",
    short_description: "An executive chair with a headrest and 4D armrests.",
    long_description: "LumaSeat Executive Air adds a height-adjustable headrest and four-way armrests to a breathable suspension back.",
    attributes: { headrest: "Height adjustable", armrests: "4D", back: "Suspension" },
    tags: ["Workspace", "Executive"],
  },
  {
    product_id: 420002,
    model: "HorizonView 38",
    domain: "home_office",
    category: "Displays",
    subcategory: "Ultrawide Monitors",
    price_usd: 899,
    image_url: "/assets/images/mosaic/ho-ultrawide-monitors-02-catalog-3x2.webp",
    short_description: "A 38-inch ultrawide for side-by-side work.",
    long_description: "HorizonView 38 gives two full documents room to sit side by side, with single-cable USB-C power and a factory colour report.",
    attributes: { size: "38 inch", resolution: "WQHD+", connectivity: "USB-C" },
    tags: ["Workspace", "Productivity"],
  },
];

const authoredSeedById = new Map(
  showcaseSeed.map((item) => [item.product_id, item]),
);
const mediaByProductId = new Map<number, MediaManifestRow>(
  mediaManifest.products.map((item) => [item.product_id, item]),
);
const fallbackImageByDomain: Record<Domain, string> = {
  consumer_electronics:
    "/assets/images/mosaic/ce-over-ear-headphones-auraluxe-h9-catalog-3x2.webp",
  running_fitness:
    "/assets/images/mosaic/rf-carbon-racing-shoes-stride-pro-catalog-3x2.webp",
  home_office:
    "/assets/images/mosaic/ho-ergonomic-office-chairs-forma-ergonomic-catalog-3x2.webp",
};

function fallbackPrice(row: PremiumCohortRow) {
  const floor = row.domain === "home_office" ? 79 : 49;
  return floor + (Math.abs(row.product_id * 37) % 720);
}

function canonicalSeedRow(row: PremiumCohortRow): ShowcaseSeed {
  const authored = authoredSeedById.get(row.product_id);
  const media = mediaByProductId.get(row.product_id);
  const imageInstalled = media?.catalog_installed ?? false;
  const model =
    authored?.model ?? row.merchandising_title.replace(/^Mosaic\s+/i, "");

  return {
    product_id: row.product_id,
    model,
    domain: row.domain,
    category: row.category,
    subcategory: row.subcategory,
    price_usd: authored?.price_usd ?? fallbackPrice(row),
    image_url:
      imageInstalled && media
        ? media.catalog_runtime_path
        : fallbackImageByDomain[row.domain],
    short_description:
      authored?.short_description ??
      `A premium ${row.subcategory.toLowerCase()} selection from the Mosaic ${row.category.toLowerCase()} collection.`,
    long_description:
      authored?.long_description ??
      `${row.merchandising_title} is part of the fixed 120-product Mosaic workshop cohort, selected for catalog browsing and retrieval evaluation.`,
    attributes: authored?.attributes ?? {},
    tags: authored?.tags ?? [row.category, row.subcategory],
    sku: row.sku,
    media_tier: row.media_tier,
    is_flagship: row.is_flagship,
    is_retrieval_anchor: row.is_retrieval_anchor,
    catalog_asset_key: media?.catalog_asset_key ?? row.catalog_asset_key,
    image_source: imageInstalled ? "cohort-runtime" : "domain-fallback",
  };
}

const canonicalSeed = [...(premiumCohort as PremiumCohortRow[])]
  .sort(
    (left, right) =>
      left.shop_page - right.shop_page ||
      left.shop_position - right.shop_position,
  )
  .map(canonicalSeedRow);

function toSummary(item: ShowcaseSeed): ProductSummary {
  return {
    product_id: item.product_id,
    sku: item.sku ?? `MOS-${item.product_id}`,
    title: `Mosaic ${item.model}`,
    short_description: item.short_description,
    domain: item.domain,
    category_key: categoryKey(item.subcategory),
    category_path: `${item.category} > ${item.subcategory}`,
    brand: "Mosaic",
    model: item.model,
    price_cents: item.price_usd * 100,
    list_price_cents: item.price_usd * 100,
    currency: "USD",
    rating: showcaseRating(item),
    review_count: showcaseReviewCount(item),
    availability: showcaseAvailability(item),
    inventory_count: 1,
    attributes: item.attributes,
    tags: item.tags,
    catalog_asset_key:
      item.catalog_asset_key ??
      item.image_url.split("/").at(-1)?.replace(/\.webp$/, "") ??
      null,
    canonical_group_id: null,
    media_tier: item.media_tier ?? "showcase",
    is_flagship: item.is_flagship ?? false,
    is_retrieval_anchor: item.is_retrieval_anchor ?? false,
    image_url: item.image_url,
    image_source: item.image_source ?? "local-showcase-preview",
    signals: null,
    sources: [
      {
        source_uri: `mosaic://showcase/${item.model.toLowerCase().replaceAll(" ", "-")}`,
        revision: "local-showcase-2026-08-08",
        title: `Mosaic ${item.model}`,
        quote: item.short_description,
      },
    ],
  };
}

export function showcaseCatalogPage(
  filters: SearchFilters,
  offset = 0,
  limit = 12,
  sort = "featured",
): CatalogPage {
  const matching = canonicalSeed
    .filter((item) => matchesFilters(item, filters))
    .map(toSummary);
  const products = [...matching];
  if (sort === "rating") {
    products.sort((left, right) => (right.rating ?? 0) - (left.rating ?? 0));
  } else if (sort === "price_asc") {
    products.sort((left, right) => left.price_cents - right.price_cents);
  } else if (sort === "price_desc") {
    products.sort((left, right) => right.price_cents - left.price_cents);
  } else if (sort === "newest") {
    products.sort((left, right) => right.product_id - left.product_id);
  }
  const categories = Array.from(
    new Set(canonicalSeed.map((item) => categoryKey(item.subcategory))),
  );

  return {
    total: matching.length,
    offset,
    limit,
    products: products.slice(offset, offset + limit),
    facets: {
      category_key: categories.map((value) => ({
        value,
        count: canonicalSeed.filter(
          (item) => categoryKey(item.subcategory) === value,
        ).length,
      })),
      brand: [{ value: "Mosaic", count: canonicalSeed.length }],
    },
  };
}

export function showcaseProductDetail(productId: number): ProductDetail | null {
  const item = canonicalSeed.find((candidate) => candidate.product_id === productId);
  if (!item) return null;

  const product = toSummary(item);
  return {
    ...product,
    long_description: item.long_description,
    canonical_group_id: `mosaic-showcase-${item.product_id}`,
    source_system: "Mosaic local showcase",
    updated_at: "2026-08-08T00:00:00.000Z",
    media: productImages(product).map((image_url, index) => ({
      role: index === 0 ? "detail" : "gallery",
      sort_order: index,
      image_url,
      image_source: "local-showcase-preview",
      image_key: image_url.split("/").at(-1) ?? null,
      alt_text: `${product.title} product image ${index + 1}`,
    })),
    reviews: [],
  };
}

/**
 * Offline retrieval preview.
 *
 * Scores the local seed by term overlap against title, subcategory, category,
 * brand, and attribute values. This is a lexical stand-in so the surface is
 * navigable without a backend; it is NOT the hybrid pipeline, and the caller is
 * responsible for labelling it as a preview. `signals` stays null because no
 * ranking arms ran.
 */
export function showcaseSearchResponse(query: string, filters: SearchFilters): SearchResponse {
  const terms = query.toLowerCase().split(/[^a-z0-9$]+/).filter((term) => term.length > 2);
  const scored = canonicalSeed
    .filter((item) => matchesFilters(item, filters))
    .map((item) => {
      const haystack = [
        item.model,
        item.subcategory,
        item.category,
        item.short_description,
        item.long_description,
        ...Object.values(item.attributes),
        ...item.tags,
      ]
        .join(" ")
        .toLowerCase();
      const score = terms.reduce((total, term) => (haystack.includes(term) ? total + 1 : total), 0);
      return { item, score };
    })
    .filter((row) => row.score > 0)
    .sort((a, b) => b.score - a.score);

  // With no term overlap the whole seed is shown rather than an empty page: the
  // preview cannot rank, so hiding everything would misrepresent the catalog.
  const rows = (scored.length ? scored.map((row) => row.item) : canonicalSeed).slice(0, 8);

  return {
    search_event_id: "local-showcase-preview",
    query,
    normalized_query: query.trim().toLowerCase(),
    applied_filters: { ...filters },
    results: rows.map(toSummary),
    diagnostics: null,
  };
}
