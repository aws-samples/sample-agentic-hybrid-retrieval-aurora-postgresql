import { describe, expect, it } from "vitest";
import { formatCategoryKey, specFacts } from "./format";

describe("specFacts", () => {
  const monitor = {
    refresh_hz: { value: 60, source: "details.Refresh Rate", quote: "60 Hz" },
    usb_c_power_w: { value: 90, source: "features[1]", quote: "90W charging over one cable" },
    size_in: { value: 27, source: "details.Screen Size", quote: "27" },
    resolution: { value: "3840x2160", source: "details.Display Resolution Maximum", quote: "3840 x 2160" },
  };

  it("orders a listing's specs by the decision they settle, with units", () => {
    expect(specFacts(monitor).map(({ label, value }) => `${label}: ${value}`)).toEqual([
      "Screen size: 27″", "Resolution: 3840 × 2160", "USB-C power: 90 W", "Refresh rate: 60 Hz",
    ]);
  });

  it("keeps the verbatim quote each value was read from", () => {
    expect(specFacts(monitor, 3).at(-1)).toMatchObject({ key: "usb_c_power_w", quote: "90W charging over one cable" });
  });

  it("formats chair and headphone values without inventing absent ones", () => {
    const facts = specFacts({
      lumbar_support: { value: "adjustable", source: "features[2]", quote: "adjustable lumbar" },
      max_weight_lb: { value: 400, source: "details.Maximum Weight Recommendation", quote: "400 Pounds" },
      anc: { value: true, source: "title", quote: "Noise Cancelling" },
    });
    expect(facts.map(({ label, value }) => `${label}: ${value}`)).toEqual([
      "Noise cancellation: Yes", "Lumbar support: Adjustable", "Weight capacity: 400 lb",
    ]);
    expect(specFacts(undefined)).toEqual([]);
  });
});

describe("formatCategoryKey", () => {
  it("reads the real catalog's underscore keys as words", () => {
    expect(formatCategoryKey("headphone_case")).toBe("Headphone Case");
    expect(formatCategoryKey("monitor_accessory")).toBe("Monitor Accessory");
    expect(formatCategoryKey("noise-cancelling")).toBe("Noise Cancelling");
    expect(formatCategoryKey("monitor_stand")).toBe("Monitor stands & arms");
  });
});
