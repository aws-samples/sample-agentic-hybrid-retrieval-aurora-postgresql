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
