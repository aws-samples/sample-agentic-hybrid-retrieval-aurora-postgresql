// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import shared from "../../../../data/cited_line_cases.json";
import type { AgentCitation, ProductSummary } from "../../types";
import { pickFacts } from "./pickFacts";
import { SourceList } from "./SourceList";

afterEach(cleanup);

const records = shared.records as Record<string, { evidence_type: string; quote: string }>;
const ANSWER = shared.cases[0].answer;

const cite = (number: number, record: string): AgentCitation => ({
  number,
  evidence_id: 1000 + number,
  evidence_type: records[record].evidence_type,
  product_id: 1551237,
  source_uri: "u",
  revision: "fdb89c37",
  title: "t",
  quote: records[record].quote,
  rating: records[record].evidence_type === "customer_review" ? 5 : null,
});

const viewsonic = { product_id: 1551237, title: "ViewSonic VG2756-4K 27 Inch IPS", brand: "ViewSonic" } as ProductSummary;

function sources(answer: string, citations: AgentCitation[]) {
  render(<SourceList answer={answer} answerId="a" builder={false} products={[viewsonic]} citations={citations} />);
  return screen.getByRole("region", { name: "Sources" });
}

describe("the recorded 100W answer's sources", () => {
  it("quote the listing's 90W line with the figure marked, not the USB hub sentence", () => {
    const list = sources(ANSWER, [cite(1, "viewsonic_listing"), cite(2, "viewsonic_review")]);
    const [listing, review] = within(list).getAllByRole("listitem");

    expect(within(listing).getByText("90W", { selector: "mark" })).toBeTruthy();
    expect(listing.querySelector(".ask-source-quote")?.textContent).toContain("90W charging over one cable");
    expect(listing.querySelector(".ask-source-quote")?.textContent).not.toContain("USB hub");
    expect(review.querySelector("mark")).toBeNull();
    expect(review.querySelector(".ask-source-quote")?.textContent).toContain("pass battery charging to my laptop");
  });

  it("show the whole line that carries the figure; the one-line clamp would cut it off", () => {
    const list = sources(ANSWER, [cite(1, "viewsonic_listing")]);

    expect(list.querySelector(".ask-source-quote")?.hasAttribute("data-figure")).toBe(true);
  });

  it("say which figure a record never states, and imply nothing about it", () => {
    const list = sources("Its listing states 90W, short of the 100W this laptop needs [1].", [cite(1, "viewsonic_listing")]);

    expect(within(list).getByText("No line in this record states 100W.")).toBeTruthy();
    expect(within(list).getByText("90W", { selector: "mark" })).toBeTruthy();
    expect(within(list).queryByText("100W", { selector: "mark" })).toBeNull();
  });

  it("open to the whole record without its ingest labels or category path", () => {
    const list = sources(ANSWER, [cite(1, "viewsonic_listing")]);
    const whole = within(list).getByText("Read the whole listing");
    const record = whole.closest("details")!;
    expect(record.textContent).toBe("Read the whole listing");
    record.open = true;
    fireEvent(record, new Event("toggle"));

    expect(record.textContent).toContain("ViewSonic VG2756-4K 27 Inch IPS 4K Docking Monitor");
    expect(record.textContent).toContain("That’s not all, the integrated USB hub");
    expect(record.textContent).not.toMatch(/Title:|Categories:|Description:/);
  });
});

describe("the pick card's line", () => {
  it("marks the figure inside a review's quotation marks at the right place", () => {
    const answer = "One reviewer charges a laptop at 90W over USB-C [1].";
    const review = { ...cite(1, "spaced_unit"), evidence_type: "customer_review", rating: 5 };
    const [fact] = pickFacts(viewsonic, [review], answer).filter((item) => item.number === 1);

    expect(fact.text.startsWith("“")).toBe(true);
    expect(fact.marks?.map(([start, end]) => fact.text.slice(start, end))).toEqual(["90 W"]);
  });
});
