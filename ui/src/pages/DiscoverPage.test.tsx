// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { CommerceProvider } from "../commerce";
import { DiscoverPage } from "./DiscoverPage";

describe("DiscoverPage", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/");
  });

  afterEach(cleanup);

  function renderPage() {
    return render(
      <CommerceProvider>
        <DiscoverPage />
      </CommerceProvider>,
    );
  }

  it("routes a typed product need into Shop retrieval", () => {
    renderPage();

    fireEvent.change(screen.getByRole("textbox", { name: "Search products" }), {
      target: { value: "quiet keyboard under $180" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search Mosaic" }));

    expect(window.location.pathname).toBe("/catalog");
    expect(new URLSearchParams(window.location.search).get("q")).toBe(
      "quiet keyboard under $180",
    );
  });

  it("runs a natural-language starter as a real Shop query", () => {
    renderPage();

    const starter = "Find an ergonomic mesh chair for long workdays with adjustable lumbar support.";
    fireEvent.click(screen.getByRole("button", { name: starter }));

    expect(window.location.pathname).toBe("/catalog");
    expect(new URLSearchParams(window.location.search).get("q")).toBe(starter);
  });
});
