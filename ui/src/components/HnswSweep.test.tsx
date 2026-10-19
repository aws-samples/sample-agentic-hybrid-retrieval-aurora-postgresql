// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import type { HnswEfPoint } from "../types";
import { HnswSweep, sweepTakeaway } from "./HnswSweep";

afterEach(cleanup);

const point = (ef: number, recall: number, ms: number): HnswEfPoint => ({
  ef_search: ef, recall_at_k: recall, server_ms: ms, shared_hit_blocks: 1, estimated_total_cost: 1,
});
const sweep = [point(40, 0.967, 0.5), point(100, 0.986, 1), point(400, 1, 2)];

it("reads the takeaway from the first and last measured points", () => {
  expect(sweepTakeaway(sweep)).toBe(
    "From ef_search 40 to 400, recall goes from 96.7% to 100.0% and database time from 0.500 ms to 2.000 ms (4.0x).",
  );
  expect(sweepTakeaway([sweep[0]])).toBe("");
});

it("marks only the served setting and shows every measured value", () => {
  render(<HnswSweep sweep={sweep} served={100} />);
  expect(screen.getAllByText("served")).toHaveLength(1);
  expect(screen.getByText("98.6%")).toBeTruthy();
  expect(screen.getByText("2.000 ms")).toBeTruthy();
});
