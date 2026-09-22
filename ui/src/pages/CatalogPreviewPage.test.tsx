// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CatalogPreviewPage, readPreviewData } from "./CatalogPreviewPage";

function preview() {
  const product = {
    id: "test-known",
    brand: "Test",
    model: "Known",
    title: "Original listing — unchanged",
    originalDescription: "Exact wording.\nNo rewritten claims.",
    originalBulletPoints: "Feature A\nFeature B",
    image: "https://example.com/original.jpg",
    description: "Display summary",
    sourceUrl: "https://example.com/specifications",
    sourceLabel: "Product specifications",
    facts: [
      { label: "Microphone", value: "Yes", meetsNeed: true as boolean | undefined },
      { label: "Noise cancellation", value: "Yes", meetsNeed: true as boolean | undefined },
    ],
  };
  return {
    imageSource: "Test image source",
    groups: [{
      id: "headphones",
      label: "Headphones",
      heading: "Clear calls",
      request: "A microphone and noise cancellation",
      requirements: ["Microphone", "Noise cancellation"],
      products: [
        product,
        { ...structuredClone(product), id: "test-false", model: "No",
          facts: [{ label: "Microphone", value: "Yes", meetsNeed: true }, { label: "Noise cancellation", value: "No", meetsNeed: false }] },
        { ...structuredClone(product), id: "test-unknown", model: "Unknown",
          facts: [{ label: "Microphone", value: "Yes", meetsNeed: true }, { label: "Noise cancellation", value: "Not listed", meetsNeed: undefined }] },
      ],
    }],
  };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function sampledPreview() {
  const data = preview();
  return { ...data, groups: data.groups.map((group) => ({ ...group, catalogSamples: [
    { ...structuredClone(group.products[0]), id: "new-sample", title: "Additional original product", selectedInBulk: true,
      facts: [{ label: "Connection", value: "Wired" }] },
    { ...structuredClone(group.products[0]), id: "other-sample", title: "Another original product", selectedInBulk: true,
      facts: [{ label: "Style", value: "Over Ear" }] },
  ] })) };
}

describe("local catalog preview", () => {
  it("keeps exact retailer links visible outside the source disclosure in both views", async () => {
    const data = preview();
    const listingUrl = "https://www.amazon.com/dp/SOURCE123?variant=original%20colour";
    Object.assign(data.groups[0].products[0], { listingUrl });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(data))));
    render(<CatalogPreviewPage />);
    const name = "View original listing for Original listing — unchanged (opens in a new tab)";
    const link = await screen.findByRole("link", { name });
    expect(link.getAttribute("href")).toBe(listingUrl);
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(link.closest("details")).toBeNull();
    expect(screen.getByText("amazon.com")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Compare features" }));
    expect(screen.getByRole("link", { name }).getAttribute("href")).toBe(listingUrl);
    expect(screen.getByRole("link", { name }).closest("details")).toBeNull();
  });

  it("preserves the source website when no retailer listing is supplied", async () => {
    const data = preview();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(data))));
    render(<CatalogPreviewPage />);
    const links = await screen.findAllByRole("link", { name: /View source website for/ });
    expect(links).toHaveLength(3);
    expect(links.map((link) => link.getAttribute("href"))).toEqual(data.groups[0].products.map((product) => product.sourceUrl));
    expect(screen.queryByRole("link", { name: /View original listing/ })).toBeNull();
  });

  it("shows additional products first without implying they meet Alex's requirements", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(sampledPreview()))));
    render(<CatalogPreviewPage />);
    await screen.findByRole("heading", { name: "Additional original product" });
    expect(screen.getByText(/Showing 2 of 2/)).toBeTruthy();
    expect(screen.queryByText("Documented fit")).toBeNull();
    expect(screen.queryByRole("checkbox", { name: "Documented fits only" })).toBeNull();
    expect(screen.getAllByText("In selected catalog")).toHaveLength(2);
    fireEvent.change(screen.getByRole("combobox", { name: "Sample set" }), { target: { value: "all" } });
    expect(screen.getByRole("heading", { name: "Test Known" })).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: "Documented fits only" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Additional original product" })).toBeNull();
  });

  it("compares unreviewed samples using supplied fields and leaves missing values unknown", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(sampledPreview()))));
    render(<CatalogPreviewPage />);
    await screen.findByRole("heading", { name: "Additional original product" });
    fireEvent.click(screen.getByRole("button", { name: "Compare features" }));
    expect(screen.getByRole("rowheader", { name: "Connection" })).toBeTruthy();
    expect(screen.getByRole("rowheader", { name: "Style" })).toBeTruthy();
    expect(screen.queryByRole("rowheader", { name: "Fit to the brief" })).toBeNull();
    expect(screen.getAllByRole("cell", { name: "Not supplied" })).toHaveLength(4);
  });

  it("rejects unconfirmed membership and repeated identities in additional samples", () => {
    const data = sampledPreview();
    data.groups[0].catalogSamples[0].selectedInBulk = false;
    expect(() => readPreviewData(data)).toThrow(/source link/);
    data.groups[0].catalogSamples[0].selectedInBulk = true;
    data.groups[0].catalogSamples[0].id = data.groups[0].products[0].id;
    expect(() => readPreviewData(data)).toThrow(/repeated product/);
  });

  it("preserves original source strings without replacing them with the display summary", async () => {
    const data = preview();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(data))));
    const { container } = render(<CatalogPreviewPage />);
    await screen.findByRole("heading", { name: "Test Known" });
    const original = container.querySelectorAll(".catalog-preview-original");
    expect([...original].slice(0, 3).map((node) => node.textContent)).toEqual([
      data.groups[0].products[0].title,
      data.groups[0].products[0].originalDescription,
      data.groups[0].products[0].originalBulletPoints,
    ]);
  });

  it("requires a confirmed yes for every requested feature, excluding both false and unknown", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(preview()))));
    render(<CatalogPreviewPage />);
    await screen.findByRole("heading", { name: "Test Unknown" });
    fireEvent.click(screen.getByRole("checkbox", { name: "Documented fits only" }));
    expect(screen.getByRole("heading", { name: "Test Known" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Test No" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Test Unknown" })).toBeNull();
    expect(screen.getByText(/Showing 1 of 3/)).toBeTruthy();
  });

  it("compares the same source facts without promoting an unknown feature to a match", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(preview()))));
    render(<CatalogPreviewPage />);
    await screen.findByRole("heading", { name: "Test Unknown" });
    fireEvent.click(screen.getByRole("button", { name: "Compare features" }));
    expect(screen.getByRole("table")).toBeTruthy();
    expect(screen.getByRole("rowheader", { name: "Noise cancellation" })).toBeTruthy();
    expect(screen.getByText("Documented fit")).toBeTruthy();
    expect(screen.getByText("Requirement mismatch")).toBeTruthy();
    expect(screen.getByText("Needs verification")).toBeTruthy();
    expect(screen.getByText("Not listed", { selector: "span" })).toBeTruthy();
    fireEvent.click(screen.getByRole("checkbox", { name: "Documented fits only" }));
    expect(screen.getByRole("heading", { name: "Test Known" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Test Unknown" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Gallery" }));
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Test Unknown" })).toBeNull();
  });

  it("uses reviewed catalog membership and keeps external reference samples separate", async () => {
    const data = preview();
    data.groups[0].products[0].id = "B07G95TJ3P";
    data.groups[0].products[1].id = "B085RNVJ3P";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(data))));
    render(<CatalogPreviewPage />);
    await screen.findByRole("heading", { name: "Test Unknown" });
    fireEvent.change(screen.getByRole("combobox", { name: "Sample set" }), { target: { value: "selected" } });
    expect(screen.getByRole("heading", { name: "Test Known" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Test No" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Test Unknown" })).toBeNull();
    expect(screen.getByText("In selected catalog")).toBeTruthy();
  });

  it("offers a working recovery when the selected sample set is empty", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(preview()))));
    render(<CatalogPreviewPage />);
    await screen.findByRole("heading", { name: "Test Known" });
    fireEvent.change(screen.getByRole("combobox", { name: "Sample set" }), { target: { value: "selected" } });
    expect(screen.getByRole("heading", { name: "No documented fit in this sample set" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Show all samples" }));
    expect(screen.getByRole("heading", { name: "Test Known" })).toBeTruthy();
    expect((screen.getByRole("combobox", { name: "Sample set" }) as HTMLSelectElement).value).toBe("all");
  });

  it("refuses an incomplete requirement list instead of silently passing it", () => {
    const data = preview();
    data.groups[0].requirements.push("Unreported feature");
    expect(() => readPreviewData(data)).toThrow(/specifications/);
    data.groups[0].requirements = [];
    expect(() => readPreviewData(data)).toThrow(/product group/);
  });

  it("rejects unsafe URLs and duplicate product identities", () => {
    const data = preview();
    data.groups[0].products[0].sourceUrl = "javascript:alert(1)";
    expect(() => readPreviewData(data)).toThrow(/source link/);
    const duplicate = preview();
    duplicate.groups[0].products[1].id = duplicate.groups[0].products[0].id;
    expect(() => readPreviewData(duplicate)).toThrow(/repeated product/);
  });

  it("reports an unavailable image without substituting another product", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(preview()))));
    render(<CatalogPreviewPage />);
    await screen.findByRole("heading", { name: "Test Known" });
    fireEvent.error(screen.getAllByRole("img", { name: "Original listing — unchanged" })[0]);
    expect(screen.getByText("Photo unavailable from the source")).toBeTruthy();
    expect(screen.getAllByRole("img", { name: "Original listing — unchanged" })).toHaveLength(2);
  });

  it("can recover when a missing local preview file becomes available", async () => {
    vi.stubGlobal("fetch", vi.fn()
      .mockResolvedValueOnce(new Response("{}", { status: 404 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(preview()))));
    render(<CatalogPreviewPage />);
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByRole("heading", { name: "Test Known" });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("displays supplied rating aggregates without inventing missing ratings", async () => {
    const data = preview();
    Object.assign(data.groups[0].products[0], { rating: { average: 4.7, count: 5341 } });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(data))));
    render(<CatalogPreviewPage />);
    expect(await screen.findByText("4.7 out of 5 · 5,341 ratings")).toBeTruthy();
    expect(screen.getAllByText("Dataset rating")).toHaveLength(1);
  });

  it.each([{ average: 6, count: 4 }, { average: 4, count: 0 }, { average: 4, count: 1.5 }])(
    "rejects an invalid rating aggregate %s", (rating) => {
      const data = preview();
      Object.assign(data.groups[0].products[0], { rating });
      expect(() => readPreviewData(data)).toThrow(/rating/);
    },
  );
});
