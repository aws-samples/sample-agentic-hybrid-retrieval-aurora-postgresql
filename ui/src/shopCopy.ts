import { productBoundImage } from "./media";
import { productFacts } from "./format";
import type { ProductSummary } from "./types";

/** Long-tail search cards use catalog facts instead of repeated filler prose. */
export function shopDescription(product: ProductSummary): string {
  if (productBoundImage(product.product_id)) return product.short_description;
  const a = product.attributes;
  const parts: string[] = [];
  if (product.category_key.includes("chairs")) {
    if (typeof a.material === "string") parts.push(a.material);
    if (typeof a.recommended_hours === "number") parts.push(`${a.recommended_hours}-hour recommended use`);
    if (typeof a.lumbar_support === "string") parts.push(`${a.lumbar_support} lumbar`);
    if (typeof a.armrests === "string") parts.push(`${a.armrests} arms`);
    if (typeof a.recline_deg === "number") parts.push(`${a.recline_deg}° recline`);
    if (typeof a.max_user_weight_lb === "number") parts.push(`${a.max_user_weight_lb} lb capacity`);
    if (typeof a.seat_depth_adjustable === "boolean") parts.push(a.seat_depth_adjustable ? "sliding seat" : "fixed seat depth");
  } else if (product.category_key.includes("monitors")) {
    if (typeof a.size_in === "number") parts.push(`${a.size_in}-inch screen`);
    if (typeof a.resolution === "string") parts.push(a.resolution);
    if (typeof a.panel === "string") parts.push(a.panel);
    if (typeof a.refresh_hz === "number") parts.push(`${a.refresh_hz} Hz`);
    if (typeof a.usb_c_power_w === "number") parts.push(a.usb_c_power_w ? `${a.usb_c_power_w} W USB-C power` : "no USB-C power delivery");
    if (typeof a.height_adjustable === "boolean") parts.push(a.height_adjustable ? "height-adjustable stand" : "fixed stand");
  } else {
    parts.push(...productFacts(a).map((fact) => `${fact.label}: ${fact.value}`));
  }
  return parts.length ? parts.join(" · ") : product.short_description;
}
