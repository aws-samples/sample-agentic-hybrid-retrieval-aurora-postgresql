// @vitest-environment jsdom

import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { mosaicRetrievalExamples } from "../labMissions";
import { seedProvenance, seedRun } from "../retrievalSeed";
import type { SearchResponse } from "../types";
import { RetrievalObservatory } from "./RetrievalObservatory";

/**
 * The surface this replaces printed "This replay explains the retrieval flow, not
 * a measured run" above hand-written rank arrays, and showed one retriever at a
 * time. These tests hold the two properties that fixes: everything on screen comes
 * from a run, and all five retrievers are comparable at once.
 */

function exampleFor(id: string) {
  const example = mosaicRetrievalExamples.find((candidate) => candidate.id === id);
  if (!example) throw new Error(`Missing scenario ${id}`);
  return example;
}

const seedExample = exampleFor(seedProvenance.mission_id);

/** A live response distinguishable from the capture at a glance. */
const liveResponse: SearchResponse = {
  ...seedRun,
  search_event_id: "feedfaceb0000000",
  results: [
    {
      ...seedRun.results[0],
      title: "Liveonly Test Headphone",
      signals: { ...seedRun.results[0].signals!, final_rank: 1 },
    },
  ],
};

function renderObservatory(props: Partial<Parameters<typeof RetrievalObservatory>[0]> = {}) {
  return render(
    <RetrievalObservatory
      example={seedExample}
      loading={false}
      response={null}
      {...props}
    />,
  );
}

describe("RetrievalObservatory", () => {
  afterEach(cleanup);

  it("opens empty until a live run completes", () => {
    const { container } = renderObservatory();

    expect(container.querySelector(".labs-matrix-table")).toBeNull();
    expect(screen.queryByText("Live run")).toBeNull();
    expect(screen.getByRole("status").textContent).toContain(
      `No run for ${seedExample.discover_label} yet`,
    );
  });

  it("compares all five stages side by side, with the count each found", () => {
    renderObservatory({ response: seedRun });

    const headings = screen.getAllByRole("columnheader").map((cell) => cell.textContent);
    expect(headings[0]).toBe("Result");
    // One vocabulary, from retrievalLanguage. These headings used to be a fifth
    // naming of the same five stages.
    expect(headings[1]).toContain("Exact terms");
    expect(headings[2]).toContain("Close spelling");
    expect(headings[3]).toContain("Meaning match");
    expect(headings[4]).toContain("Before reranking");
    expect(headings[5]).toContain("Rerank score");
    // The mechanism travels with the label on this surface, and only here.
    expect(headings[1]).toContain("tsvector");
    expect(headings[2]).toContain("pg_trgm");
    expect(headings[3]).toContain("pgvector");
    expect(headings[6]).toContain("Before / after");

    const found = (arm: "fts" | "trigram" | "semantic") =>
      seedRun.results.filter((product) => product.signals![arm].rank !== null).length;
    expect(headings[1]).toContain(`${found("fts")} of ${seedRun.results.length}`);
    expect(headings[3]).toContain(`${found("semantic")} of ${seedRun.results.length}`);
  });

  it("marks an arm that returned nothing as not found, not as zero", () => {
    // A rank of 0 or a dash reads as "ranked last". The distinction the labs turn
    // on is that the retriever never produced the row at all.
    const { container } = renderObservatory({ response: seedRun });
    const misses = container.querySelectorAll(".labs-matrix-cell.is-missing");
    expect(misses.length).toBeGreaterThan(0);
    misses.forEach((cell) => expect(cell.textContent).toBe("not found"));
  });

  it("explains each row from its own signals", () => {
    const { container } = renderObservatory({ response: seedRun });
    const rows = container.querySelectorAll(".labs-matrix-table tbody");

    // The seed's target matched only on a repaired spelling; neither exact
    // words nor meaning found it.
    const target = [...rows].find((row) => row.className.includes("is-target"));
    expect(target).toBeTruthy();
    expect(target!.textContent).toContain("Only the close spelling arm found it.");
    expect(target!.textContent).toMatch(/Repaired spelling: \w+ to \w+/);

    // Every other row in this capture came back on meaning alone.
    const vectorOnly = [...rows].find((row) =>
      row.textContent?.includes("Only the vector arm found it"),
    );
    expect(vectorOnly).toBeTruthy();
    expect(vectorOnly!.textContent).toMatch(/nearest by meaning/);
  });

  it("reveals the query behind a retriever when its heading is selected", () => {
    const { container } = renderObservatory({ response: seedRun });
    expect(container.querySelector(".labs-matrix-cell.is-focused")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Close spelling/ }));

    expect(screen.getByText("mosaic_search.search_trigram(", { exact: false })).toBeTruthy();
    expect(container.querySelectorAll(".labs-matrix-cell.is-focused")).toHaveLength(
      seedRun.results.length,
    );

    fireEvent.click(screen.getByRole("button", { name: /Close spelling/ }));
    expect(container.querySelector(".labs-matrix-cell.is-focused")).toBeNull();
  });

  it("labels a completed response as a live run", () => {
    const { container } = renderObservatory({ response: liveResponse });

    expect(screen.getByText("Live run")).toBeTruthy();
    expect(screen.getByText("feedface")).toBeTruthy();
    expect(container.querySelectorAll(".labs-matrix-table tbody")).toHaveLength(1);
    expect(screen.getByText("Liveonly Test Headphone")).toBeTruthy();
  });

  it("keeps every scenario empty until it has its own live run", () => {
    const other = mosaicRetrievalExamples.find(
      (candidate) => candidate.id !== seedProvenance.mission_id,
    )!;
    const { container } = renderObservatory({ example: other });

    expect(container.querySelector(".labs-matrix-table")).toBeNull();
    expect(screen.getByRole("status").textContent).toContain(
      `No run for ${other.discover_label} yet`,
    );
  });

  it("reports work in progress while a run is in flight", () => {
    const other = mosaicRetrievalExamples.find(
      (candidate) => candidate.id !== seedProvenance.mission_id,
    )!;
    const { container } = renderObservatory({ example: other, loading: true });
    expect(screen.getByRole("status").textContent).toContain("Embedding the query");
    expect(container.querySelector(".labs-matrix")?.getAttribute("aria-busy")).toBe("true");
  });

  it("makes the result matrix a keyboard-focusable scroll region", () => {
    renderObservatory({ response: seedRun });

    const region = screen.getByRole("region", {
      name: "Retrieval result comparison",
    });
    expect(region.getAttribute("tabindex")).toBe("0");
    expect(within(region).getByRole("table")).toBeTruthy();
  });

  it("states the limits of the numbers it draws", () => {
    renderObservatory({ response: seedRun });
    const note = document.querySelector(".labs-matrix-note")!;
    expect(note.textContent).toContain("positions within each retriever's own candidate list");
    expect(note.textContent).toContain("order that would have shipped with reranking off");
    expect(note.textContent).toContain("are not");
  });
});
