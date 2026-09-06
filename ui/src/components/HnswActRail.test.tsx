// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { actFromHash, HNSW_ACTS, HnswAct, HnswActRail } from "./HnswActRail";

afterEach(() => {
  cleanup();
  window.history.replaceState({}, "", "/");
});

describe("actFromHash", () => {
  it("names only its own hashes", () => {
    expect(actFromHash("#hnsw-act-cost")).toBe("cost");
    expect(actFromHash("#hnsw-act-scale")).toBe("scale");
  });

  it("claims nothing for a hash that belongs to something else", () => {
    // The page also carries `#main-content`, and the Playground's rail writes
    // `#labs-stage-*`. A loose regex here would mark an act for either.
    for (const hash of ["#main-content", "#labs-stage-rank", "#hnsw-act-", "", "#"]) {
      expect(actFromHash(hash)).toBeNull();
    }
  });
});

describe("HnswActRail", () => {
  it("offers one entry per act, in order, with no other destinations", () => {
    // Three, not eight. Eight rail entries is a table of contents, which is a
    // second thing to read; the reader is missing a spine, not an index.
    render(<HnswActRail />);
    const rail = screen.getByRole("navigation", { name: "Vector index acts" });
    const links = within(rail).getAllByRole("link");

    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "#hnsw-act-cost",
      "#hnsw-act-tuning",
      "#hnsw-act-scale",
    ]);
    expect(links.map((link) => link.textContent)).toEqual([
      "01Cost",
      "02Tuning",
      "03Scale",
    ]);
  });

  it("marks the act the hash names, and follows a later click", () => {
    // Clicking a rail link and watching nothing change reads as a dead control,
    // which is the report that put the same mark on the Playground's rail.
    window.history.replaceState({}, "", "#hnsw-act-tuning");
    render(<HnswActRail />);

    const viewing = () =>
      screen
        .getAllByRole("link")
        .filter((link) => link.getAttribute("data-viewing") === "true")
        .map((link) => link.getAttribute("href"));

    expect(viewing()).toEqual(["#hnsw-act-tuning"]);

    window.history.replaceState({}, "", "#hnsw-act-scale");
    fireEvent(window, new HashChangeEvent("hashchange"));
    expect(viewing()).toEqual(["#hnsw-act-scale"]);
  });

  it("marks nothing when the hash belongs to another surface", () => {
    window.history.replaceState({}, "", "#main-content");
    render(<HnswActRail />);
    expect(
      screen.getAllByRole("link").filter((l) => l.getAttribute("data-viewing")),
    ).toHaveLength(0);
  });
});

describe("HnswAct", () => {
  it("gives every rail destination a landing element with that id", () => {
    // The falsifier for the rail: a link to an id nothing renders scrolls
    // nowhere and looks like a broken control rather than a missing section.
    const { container } = render(
      <>
        {HNSW_ACTS.map((act) => (
          <HnswAct key={act.slug} slug={act.slug}>
            <p>{act.slug} body</p>
          </HnswAct>
        ))}
      </>,
    );

    render(<HnswActRail />);
    for (const link of screen.getAllByRole("link")) {
      const id = (link.getAttribute("href") ?? "").slice(1);
      expect(container.querySelector(`#${id}`)).toBeTruthy();
    }
  });

  it("labels each act by its own heading", () => {
    render(
      <HnswAct slug="tuning">
        <p>body</p>
      </HnswAct>,
    );
    expect(screen.getByRole("region", { name: "What it costs to tune" })).toBeTruthy();
  });

  it("refuses an act it does not define rather than rendering an empty group", () => {
    expect(() =>
      render(
        // @ts-expect-error deliberately outside the union
        <HnswAct slug="nonsense">
          <p>body</p>
        </HnswAct>,
      ),
    ).toThrow(/unknown HNSW act/);
  });
});
