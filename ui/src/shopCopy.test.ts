import { describe, expect, it } from "vitest";
import { shopDescription } from "./shopCopy";
import { showcaseProductDetail } from "./showcase";
import { productFacts } from "./format";

describe("Shop buying differences", () => {
  it("shows noise cancellation and microphone support before other headphone details", () => {
    const headphones = {
      ...showcaseProductDetail(2)!,
      attributes: { active_noise_cancellation: true, microphone: true, battery_hours: 35 },
    };
    expect(shopDescription(headphones)).toMatch(/^Noise cancellation: Yes · Microphone: Yes/);
    const passive = { ...headphones, attributes: { active_noise_cancellation: false, microphone: false } };
    expect(shopDescription(passive)).toBe("Noise cancellation: No · Microphone: No");
    expect(shopDescription({ ...headphones, attributes: {} })).toBe("Noise cancellation: Not listed · Microphone: Not listed");
  });
  it("prioritizes the catalog's full noise-cancellation key even when values are false", () => {
    expect(productFacts({ codec: "AAC", foldable: true, battery_hours: 22, active_noise_cancellation: false }, 2)).toEqual([
      { key: "active_noise_cancellation", label: "Noise cancellation", value: "No" },
      { key: "battery_hours", label: "Battery life", value: "22 hours" },
    ]);
  });
  it("distinguishes long-tail chairs whose filler descriptions are identical", () => {
    const base = { ...showcaseProductDetail(370001)!, product_id: 370922, short_description: "Body-aligned support for creative work.", attributes: { material: "Mesh", recommended_hours: 4, lumbar_support: "Fixed", armrests: "2D", seat_depth_adjustable: false } };
    const adjusted = { ...base, product_id: 377133, attributes: { ...base.attributes, recommended_hours: 10, lumbar_support: "Adjustable", seat_depth_adjustable: true } };
    expect(shopDescription(base)).toContain("4-hour recommended use");
    expect(shopDescription(base)).toContain("Fixed lumbar");
    expect(shopDescription(base)).toContain("fixed seat depth");
    expect(shopDescription(adjusted)).toContain("10-hour recommended use");
    expect(shopDescription(adjusted)).not.toBe(shopDescription(base));
  });
  it("keeps an explicit zero separate from an unknown charging specification", () => {
    const base = { ...showcaseProductDetail(420001)!, product_id: 420099, attributes: { usb_c_power_w: 0, size_in: 32 } };
    expect(shopDescription(base)).toContain("no USB-C power delivery");
    expect(shopDescription({ ...base, attributes: { size_in: 32 } })).not.toContain("USB-C");
  });
});
