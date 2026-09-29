// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mosaicLabManifest } from "../labMissions";
import { AskMosaicInvite, ShopLanding } from "./ShopLanding";

function renderLanding(onAsk = vi.fn()) {
  return render(<ShopLanding real={false} returning={false} onAsk={onAsk} />);
}

describe("ShopLanding", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/catalog");
  });
  afterEach(cleanup);

  it("introduces Alex’s brief without inventory or a completion tracker", () => {
    const { container } = renderLanding();
    expect(screen.getByRole("heading", { name: "Meet Alex." })).toBeTruthy();
    expect(screen.getByText("Already in place")).toBeTruthy();
    expect(screen.getByText("Desk")).toBeTruthy();
    expect(screen.getByText("Laptop")).toBeTruthy();
    expect(screen.getByText("Still to choose")).toBeTruthy();
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(container.querySelector(".shop-product-card")).toBeNull();
    const briefLink = screen.getByRole("link", { name: "Explore Alex’s brief" });
    const brief = document.querySelector(briefLink.getAttribute("href")!);
    expect(brief?.querySelectorAll(".shop-band")).toHaveLength(3);
  });

  it("keeps the categories in the same order as Alex’s needs, each in its own domain", () => {
    renderLanding();
    const categories = within(screen.getByRole("navigation", { name: "Workspace categories" }));
    expect(categories.getAllByRole("link").map((link) => [link.textContent, link.getAttribute("href")]))
      .toEqual([
        ["Headphones", "/catalog?domain=consumer_electronics&category_key=headphones"],
        ["Chairs", "/catalog?domain=home_office&category_key=chair"],
        ["Monitors", "/catalog?domain=consumer_electronics&category_key=monitor"],
      ]);
  });

  it("routes each band to its category and to the scoped request Shop searches", () => {
    const { container } = renderLanding();
    const bands = [...container.querySelectorAll<HTMLElement>(".shop-band[data-layout]")];
    expect(bands.map((band) => band.querySelector("h2")?.textContent)).toEqual([
      "Find his focus.", "Make room for his work.", "Bring his workspace together.",
    ]);
    const requestIds = {
      headphones: ["headphones", "clear-calls"],
      monitors: ["monitor", "more-screen-space"],
      chairs: ["chair", "comfortable-days"],
    };
    for (const band of bands) {
      expect(band.querySelector("img")).toBeTruthy();
      const [category, search] = within(band).getAllByRole("link");
      const topic = category.textContent!.replace("Shop ", "");
      const [key, requestId] = requestIds[topic as keyof typeof requestIds];
      const request = mosaicLabManifest.playground.requests
        .find((candidate) => candidate.id === requestId)!;

      const categoryUrl = new URL(category.getAttribute("href")!, "http://localhost");
      expect(categoryUrl.pathname).toBe("/catalog");
      expect(categoryUrl.searchParams.get("category_key")).toBe(key);
      expect(categoryUrl.searchParams.has("q")).toBe(false);

      const searchUrl = new URL(search.getAttribute("href")!, "http://localhost");
      expect(search.textContent).toBe(`Find ${topic} for Alex`);
      expect(searchUrl.searchParams.get("q")).toBe(request.query);
      expect(searchUrl.searchParams.get("view")).toBe("results");
      expect(searchUrl.searchParams.get("category_key")).toBe(request.filters.category_key);
      expect(searchUrl.searchParams.get("domain")).toBe(request.filters.domain);
      expect(within(band).getByText("What matters.")).toBeTruthy();
    }
  });

  it("keeps lab instructions, exercise links and implementation vocabulary off the storefront", () => {
    const { container } = renderLanding();
    expect(container.textContent).not.toMatch(/Follow the guide|Retrieve|Reranked shortlist|Grounded recommendation/);
    for (const term of ["FTS", "pg_trgm", "pgvector", "HNSW", "RRF", "tsvector"]) {
      expect(container.textContent).not.toContain(term);
    }
    for (const link of screen.getAllByRole("link")) {
      const url = new URL(link.getAttribute("href")!, "http://localhost");
      expect(url.pathname).not.toMatch(/^\/(?:labs|mosaic-labs)(?:\/|$)/);
      expect(url.searchParams.has("mission")).toBe(false);
    }
  });

  it("closes with one invitation to Ask Mosaic", () => {
    const onAsk = vi.fn();
    renderLanding(onAsk);
    const invite = screen.getByRole("complementary", { name: "What Ask Mosaic does" });
    fireEvent.click(within(invite).getByRole("button", { name: "Ask Mosaic" }));
    expect(onAsk).toHaveBeenCalledTimes(1);
    expect(screen.getAllByRole("complementary", { name: "What Ask Mosaic does" })).toHaveLength(1);
    expect(screen.getByText(/Alex is a fictional shopper/)).toBeTruthy();
  });

  it("takes focus on Alex’s profile when the header’s link lands here", async () => {
    window.history.replaceState({}, "", "/catalog#alex-profile");
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: scrollIntoView });
    renderLanding();
    const profile = document.getElementById("alex-profile");
    await waitFor(() => expect(document.activeElement).toBe(profile));
    expect(scrollIntoView).toHaveBeenCalledWith({ block: "start", behavior: "instant" });
  });
});

describe("AskMosaicInvite", () => {
  afterEach(cleanup);

  it("resumes an answered conversation rather than starting another", () => {
    render(<AskMosaicInvite compact returning onOpen={vi.fn()} />);
    const invite = screen.getByRole("complementary", { name: "What Ask Mosaic does" });
    expect(invite.className).toBe("shop-console-note is-compact");
    expect(within(invite).getByRole("heading").textContent).toBe("Keep comparing your options.");
    expect(within(invite).getByRole("button", { name: "Ask Mosaic" }).textContent).toBe("Return to Ask Mosaic");
  });
});
