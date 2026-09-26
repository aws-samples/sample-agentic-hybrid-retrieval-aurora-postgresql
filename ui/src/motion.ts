/**
 * Shared Motion easing curves.
 *
 * `CatalogPage` and the components it composes (`ShopFilterSheet`) both need
 * the same curve for their transitions; a page-level component and its own
 * child cannot import from each other without a cycle, so a curve one of
 * them needs is defined here instead of being exported from the page.
 */
export const EASE_OUT = [0.16, 1, 0.3, 1] as const;
