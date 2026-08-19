// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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

  it("opens on a real captured run rather than an empty instrument", () => {
    const { container } = renderObservatory();

    expect(screen.getByText("Captured run")).toBeTruthy();
    expect(screen.getByText(seedProvenance.captured_at)).toBeTruthy();
    expect(screen.getByText(seedRun.search_event_id.slice(0, 8))).toBeTruthy();
    // One row group per returned product, so nothing waits on a button press.
    expect(container.querySelectorAll(".labs-matrix-table tbody")).toHaveLength(
      seedRun.results.length,
    );
    expect(screen.queryByText(/Run the pipeline to fill the matrix/)).toBeNull();
  });

  it("compares all five retrievers side by side, with the count each found", () => {
    renderObservatory();

    const headings = screen.getAllByRole("columnheader").map((cell) => cell.textContent);
    expect(headings[0]).toBe("Result");
    expect(headings[1]).toContain("Exact words");
    expect(headings[2]).toContain("Close spellings");
    expect(headings[3]).toContain("Meaning");
    expect(headings[4]).toContain("Fused order");
    expect(headings[5]).toContain("Reranker");
    expect(headings[6]).toContain("Before / after");

    const found = (arm: "fts" | "trigram" | "semantic") =>
      seedRun.results.filter((product) => product.signals![arm].rank !== null).length;
    expect(headings[1]).toContain(`${found("fts")} of ${seedRun.results.length}`);
    expect(headings[3]).toContain(`${found("semantic")} of ${seedRun.results.length}`);
  });

  it("marks an arm that returned nothing as not found, not as zero", () => {
    // A rank of 0 or a dash reads as "ranked last". The distinction the labs turn
    // on is that the retriever never produced the row at all.
    const { container } = renderObservatory();
    const misses = container.querySelectorAll(".labs-matrix-cell.is-missing");
    expect(misses.length).toBeGreaterThan(0);
    misses.forEach((cell) => expect(cell.textContent).toBe("not found"));
  });

  it("explains each row from its own signals", () => {
    const { container } = renderObservatory();
    const rows = container.querySelectorAll(".labs-matrix-table tbody");

    // The seed's target matched on exact words and a repaired spelling.
    const target = [...rows].find((row) => row.className.includes("is-target"));
    expect(target).toBeTruthy();
    expect(target!.textContent).toContain("Found by exact words");
    expect(target!.textContent).toMatch(/Repaired spelling: \w+ to \w+/);

    // Every other row in this capture came back on meaning alone.
    const vectorOnly = [...rows].find((row) =>
      row.textContent?.includes("Only the vector arm found it"),
    );
    expect(vectorOnly).toBeTruthy();
    expect(vectorOnly!.textContent).toMatch(/nearest by meaning/);
  });

  it("reveals the query behind a retriever when its heading is selected", () => {
    const { container } = renderObservatory();
    expect(container.querySelector(".labs-matrix-cell.is-focused")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /Close spellings/ }));

    expect(screen.getByText("mosaic_search.search_trigram(", { exact: false })).toBeTruthy();
    expect(container.querySelectorAll(".labs-matrix-cell.is-focused")).toHaveLength(
      seedRun.results.length,
    );

    fireEvent.click(screen.getByRole("button", { name: /Close spellings/ }));
    expect(container.querySelector(".labs-matrix-cell.is-focused")).toBeNull();
  });

  it("replaces the capture with a live run and says which it is showing", () => {
    const { container } = renderObservatory({ response: liveResponse });

    expect(screen.getByText("Live run")).toBeTruthy();
    expect(screen.queryByText("Captured run")).toBeNull();
    expect(screen.getByText("feedface")).toBeTruthy();
    expect(container.querySelectorAll(".labs-matrix-table tbody")).toHaveLength(1);
    expect(screen.getByText("Liveonly Test Headphone")).toBeTruthy();
  });

  it("refuses to show the capture under a scenario it was not captured for", () => {
    // Reusing one scenario's ranks as another's illustration is the exact failure
    // the fixture replay committed. Better to ask for a run.
    const other = mosaicRetrievalExamples.find(
      (candidate) => candidate.id !== seedProvenance.mission_id,
    )!;
    const { container } = renderObservatory({ example: other });

    expect(container.querySelector(".labs-matrix-table")).toBeNull();
    expect(screen.queryByText("Captured run")).toBeNull();
    expect(screen.getByRole("status").textContent).toContain(
      `No run for ${other.discover_label} yet`,
    );
  });

  it("reports work in progress while a run is in flight", () => {
    const other = mosaicRetrievalExamples.find(
      (candidate) => candidate.id !== seedProvenance.mission_id,
    )!;
    renderObservatory({ example: other, loading: true });
    expect(screen.getByRole("status").textContent).toContain("Embedding the query");
  });

  it("states the limits of the numbers it draws", () => {
    renderObservatory();
    const note = document.querySelector(".labs-matrix-note")!;
    expect(note.textContent).toContain("positions within each retriever's own candidate list");
    expect(note.textContent).toContain("order that would have shipped with reranking off");
    expect(note.textContent).toContain("are not");
  });
});
