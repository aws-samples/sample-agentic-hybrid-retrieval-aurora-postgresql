import type { Availability } from "./types";

/**
 * Display formatting for values the API carries in their storage form.
 *
 * The service speaks integer cents and lowercase enum values because those are
 * what PostgreSQL stores. Converting at the edge — here — keeps arithmetic and
 * filtering exact while the interface still reads like a storefront.
 */

const currencyFormatters = new Map<string, Intl.NumberFormat>();

function formatter(currency: string): Intl.NumberFormat {
  let existing = currencyFormatters.get(currency);
  if (!existing) {
    existing = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    currencyFormatters.set(currency, existing);
  }
  return existing;
}

/** `34900` -> `"$349.00"`. Division happens once, at the point of display. */
export function formatPrice(cents: number, currency = "USD"): string {
  return formatter(currency).format(cents / 100);
}

/** `34900` -> `"$349"`. For dense rows where the cents add noise. */
export function formatPriceCompact(cents: number, currency = "USD"): string {
  const whole = cents % 100 === 0;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    minimumFractionDigits: whole ? 0 : 2,
    maximumFractionDigits: whole ? 0 : 2,
  }).format(cents / 100);
}

const AVAILABILITY_LABELS: Record<Availability, string> = {
  in_stock: "In stock",
  low_stock: "Low stock",
  out_of_stock: "Out of stock",
  preorder: "Pre-order",
  discontinued: "Discontinued",
};

export function formatAvailability(value: Availability): string {
  return AVAILABILITY_LABELS[value] ?? value;
}

/** True when the product can actually be bought right now. */
export function isPurchasable(value: Availability): boolean {
  return value === "in_stock" || value === "low_stock";
}

/**
 * `"over-ear-headphones"` -> `"Over-Ear Headphones"`.
 *
 * `category_key` is a slug, and `category_path` is the readable form. Prefer the
 * path where one is available; this is the fallback for the key alone.
 */
export function formatCategoryKey(key: string): string {
  return key
    .split("-")
    .map((part) => (part.length <= 2 ? part.toUpperCase() : part[0].toUpperCase() + part.slice(1)))
    .join("-")
    .replace(/-/g, " ");
}

/** `"Audio > Over-Ear Headphones"` -> `"Over-Ear Headphones"`. */
export function leafCategory(path: string): string {
  const parts = path.split(">").map((part) => part.trim()).filter(Boolean);
  return parts.length ? parts[parts.length - 1] : path;
}

/** Keep catalog values readable without changing the underlying evidence. */
export function formatAttributeValue(value: unknown): string {
  if (value === null || value === undefined) return "Not specified";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.map(formatAttributeValue).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

const ATTRIBUTE_LABELS: Record<string, string> = {
  size_in: "Screen size", resolution: "Resolution", panel: "Panel", refresh_hz: "Refresh rate",
  usb_c_power_w: "USB-C power", vesa: "VESA mount", curved: "Curved screen",
  lumbar_support: "Lumbar support", lumbar: "Lumbar support", armrests: "Armrests",
  recommended_hours: "Recommended use", seat_depth_adjustable: "Seat depth adjustment",
  height_adjustable: "Height adjustment", battery_life_hours: "Battery life",
  battery_hours: "Battery life", anc: "Active noise cancellation", multipoint: "Multipoint",
  mic: "Microphone", microphone: "Microphone", weight_kg: "Weight", weight_g: "Weight",
  best_for: "Suggested uses", color_gamut_pct: "Gamut coverage",
};

export function formatAttributeLabel(key: string): string {
  return ATTRIBUTE_LABELS[key] ?? key.replaceAll("_", " ");
}

export function productFacts(attributes: Record<string, unknown>, count = 4) {
  const order = ["size_in", "resolution", "panel", "usb_c_power_w", "refresh_hz", "recommended_hours", "lumbar_support", "lumbar", "armrests", "seat_depth_adjustable", "anc", "battery_life_hours", "battery_hours", "multipoint"];
  return Object.entries(attributes)
    .filter(([, value]) => value !== null && value !== undefined)
    .sort(([a], [b]) => (order.includes(a) ? order.indexOf(a) : order.length) - (order.includes(b) ? order.indexOf(b) : order.length))
    .slice(0, count)
    .map(([key, value]) => ({
      key,
      label: formatAttributeLabel(key),
      value: typeof value === "number" && /(_in|_hz|_w|_hours|_kg|_g)$/.test(key)
        ? `${value}${key.endsWith("_in") ? '″' : key.endsWith("_hz") ? " Hz" : key.endsWith("_w") ? " W" : key.endsWith("_kg") ? " kg" : key.endsWith("_g") ? " g" : " hours"}`
        : formatAttributeValue(value),
    }));
}
