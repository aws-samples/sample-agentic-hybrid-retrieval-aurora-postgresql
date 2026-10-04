import { describe, expect, it } from "vitest";
import type { AgentCitation } from "../../types";
import { citedClaim, citedLine, recordSentences } from "./quoteLines";

// Records and answer from the recorded fc97f09b-style run.
const ANSWER = "The Logitech Zone 900 is the strongest starting point here since its listing specifies "
  + "active noise cancellation and a noise-canceling mic meant to isolate your voice on calls [1], "
  + "directly matching your focus and call-clarity needs. A reviewer reports crystal-clear audio with "
  + "no complaints from callers, though this is one person's experience, not a verified benchmark [2]. "
  + "The ViewSonic VG2756-4K provides a 27-inch 4K display with 90W USB-C charging over one cable [3]; "
  + "a reviewer describes successfully charging and connecting a Surface Pro this way [4]. "
  + "The Steelcase Gesture Office Chair lists adjustable lumbar support and fully adjustable arms [5]; "
  + "one reviewer praises the arms but says the lumbar fit fell short of their preference [6].";

const record = (number: number, type: string, quote: string): AgentCitation => ({
  number,
  evidence_id: 100 + number,
  evidence_type: type,
  product_id: 1,
  source_uri: "mosaic://x",
  revision: "r1",
  title: "t",
  quote,
});

const LOGITECH = record(1, "product_spec",
  "Title: Logitech Zone 900 On-Ear Wireless Bluetooth Headset with Advanced Noise-canceling Microphone, "
  + "Connect up to 6 Wireless Devices with one Receiver, Quick Access to ANC and Bluetooth\n\n"
  + "Categories: Electronics > Headphones, Earbuds & Accessories > Headphones & Earbuds > On-Ear Headphones\n\n"
  + "Description:\nTake control of your acoustic experience with Logitech Zone 900, the wireless headset "
  + "specifically designed to enhance focus and productivity at home. Connect to your smartphone and computer "
  + "and seamlessly switch between them to experience great audio—perfect for conference calls and immersive "
  + "music. Active noise cancellation blocks out the noise around you. With comfort, simple controls, and "
  + "a lightweight design, it stays comfortable all day.");

const REVIEW = record(2, "customer_review",
  "This is my second purchase of the headset.my original was purchased in 2020 and the mic stopped last month. "
  + "I tried the lower version of this and returned it. The mic and noise cancelation sucked. This headset rocks. "
  + "The audio is crystal clear and no one ever complains about my audio.<br /><br />Well worth every penny.");

const STEELCASE = record(5, "product_spec",
  "Title: Steelcase Gesture Office Chair, Licorice\n\nCategories: Home & Kitchen > Furniture > Home Office Furniture\n\n"
  + "Description:\nThe Steelcase Gesture chair is a high performing ergonomic office chair designed to support "
  + "our interactions with all of today’s technologies: laptops, desktops, mobile devices and more.A new sitting "
  + "experience, Gesture’s seat and back move as a synchronized system. The seat is flexible on all edges. "
  + "Features: fully adjustable arms, adjustable lumbar support, Maximum Weight Recommendation: 400 Pounds");

const BOILERPLATE = /Title:|Categories:|Description:|<br/i;

describe("recordSentences", () => {
  it("drops the Title, Categories and Description boilerplate of a listing", () => {
    const lines = recordSentences(LOGITECH.quote);
    expect(lines.join(" ")).not.toMatch(BOILERPLATE);
    expect(lines[0]).toBe(
      "Take control of your acoustic experience with Logitech Zone 900, the wireless headset specifically "
      + "designed to enhance focus and productivity at home.",
    );
  });

  it("splits a review at sentence ends and at <br />, never mid-sentence", () => {
    const lines = recordSentences(REVIEW.quote);
    expect(lines).toContain("The audio is crystal clear and no one ever complains about my audio.");
    expect(lines).toContain("Well worth every penny.");
    expect(lines.join(" ")).not.toContain("<br");
  });

  it("splits sentences the seller ran together without a space", () => {
    const lines = recordSentences(STEELCASE.quote);
    expect(lines.some((line) => line.endsWith("mobile devices and more."))).toBe(true);
    expect(lines.some((line) => line.startsWith("A new sitting experience"))).toBe(true);
  });

  it("returns only exact substrings of the record, apart from <br /> breaks", () => {
    for (const source of [LOGITECH, REVIEW, STEELCASE]) {
      for (const line of recordSentences(source.quote)) {
        expect(source.quote).toContain(line);
      }
    }
  });
});

describe("citedClaim", () => {
  it("is the answer's clause that carries the citation", () => {
    expect(citedClaim(ANSWER, 2)).toContain("crystal-clear audio");
    expect(citedClaim(ANSWER, 2)).not.toContain("Zone 900 is the strongest");
    expect(citedClaim(ANSWER, 5)).toContain("adjustable lumbar support");
    expect(citedClaim(ANSWER, 5)).not.toContain("ViewSonic");
  });

  it("is empty for a number the answer never cites", () => {
    expect(citedClaim(ANSWER, 9)).toBe("");
  });
});

describe("citedLine", () => {
  it("shows the listing line that best supports what the answer cited it for", () => {
    expect(citedLine(LOGITECH, ANSWER)).toBe(
      "Active noise cancellation blocks out the noise around you.",
    );
    expect(citedLine(STEELCASE, ANSWER)).toBe(
      "Features: fully adjustable arms, adjustable lumbar support, Maximum Weight Recommendation: 400 Pounds",
    );
  });

  it("shows the review sentence that supports the claim, whole", () => {
    expect(citedLine(REVIEW, ANSWER)).toBe(
      "The audio is crystal clear and no one ever complains about my audio.",
    );
  });

  it("falls back to the first line when nothing overlaps the claim", () => {
    expect(citedLine(LOGITECH, "Nothing relevant here [1].")).toBe(recordSentences(LOGITECH.quote)[0]);
    expect(citedLine(REVIEW, "")).toBe(recordSentences(REVIEW.quote)[0]);
  });

  it("is empty when a record is only boilerplate", () => {
    expect(citedLine(record(1, "product_spec", "Title: Just a name\n\nCategories: A > B"), ANSWER)).toBe("");
  });
});
