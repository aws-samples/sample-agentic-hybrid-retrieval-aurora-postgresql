import { productImages } from "./media";
import type { CatalogPage, Domain, ProductDetail, ProductSummary, SearchFilters } from "./types";

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
};

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
    product_id: 210001,
    model: "Stride Pro",
    domain: "running_fitness",
    category: "Footwear",
    subcategory: "Performance Running Shoe",
    price_usd: 159,
    image_url: "/assets/images/mosaic/stride-pro.webp",
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
    image_url: "/assets/images/mosaic/forma-ergonomic.webp",
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
];

function toSummary(item: ShowcaseSeed): ProductSummary {
  return {
    product_id: item.product_id,
    sku: `MOS-${item.product_id}`,
    title: `Mosaic ${item.model}`,
    short_description: item.short_description,
    domain: item.domain,
    category: item.category,
    subcategory: item.subcategory,
    brand: "Mosaic",
    model: item.model,
    price_usd: item.price_usd,
    list_price_usd: item.price_usd,
    rating: 4.7,
    review_count: 0,
    availability: "In Stock",
    inventory_count: 1,
    attributes: item.attributes,
    tags: item.tags,
    image_url: item.image_url,
    image_source: "local-showcase-preview",
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

export function showcaseCatalogPage(filters: SearchFilters): CatalogPage {
  const products = showcaseSeed
    .filter((item) => !filters.domain || item.domain === filters.domain)
    .filter((item) => !filters.category || item.category === filters.category)
    .filter((item) => !filters.min_price || item.price_usd >= filters.min_price)
    .filter((item) => !filters.max_price || item.price_usd <= filters.max_price)
    .map(toSummary);
  const categories = ["Audio", "Wearables", "Workspace", "Footwear", "Furniture", "Accessories"];

  return {
    total: products.length,
    offset: 0,
    limit: products.length,
    products,
    facets: {
      category: categories.map((value) => ({
        value,
        count: showcaseSeed.filter((item) => item.category === value).length,
      })),
      brand: [{ value: "Mosaic", count: showcaseSeed.length }],
    },
  };
}

export function showcaseProductDetail(productId: number): ProductDetail | null {
  const item = showcaseSeed.find((candidate) => candidate.product_id === productId);
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
