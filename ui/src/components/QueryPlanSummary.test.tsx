// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { QueryPlanSummary } from "./QueryPlanSummary";

afterEach(cleanup);

function fact(label: string) {
  return screen.getByText(label).nextElementSibling?.textContent;
}

describe("QueryPlanSummary", () => {
  it("reports inclusive root buffers once and keeps row estimates separate from measurements", () => {
    render(<QueryPlanSummary plan={[{
      Plan: {
        "Node Type": "Nested Loop", "Plan Rows": 100, "Actual Rows": 4,
        "Actual Loops": 3, "Shared Hit Blocks": 20, "Shared Read Blocks": 0,
        "Temp Read Blocks": 0, "Temp Written Blocks": 2,
        Plans: [{ "Node Type": "Index Scan", "Index Name": "products_pkey", "Shared Hit Blocks": 15,
          Plans: [{ "Node Type": "Index Scan", "Index Name": "products_pkey" }] }],
      },
      "Planning Time": 0, "Execution Time": 1.25,
    }]} />);
    expect(fact("Shared buffer hits")).toBe("20");
    expect(fact("Shared blocks read")).toBe("0");
    expect(fact("Estimated rows per loop")).toBe("100");
    expect(fact("Actual rows per loop")).toBe("4");
    expect(fact("Loops")).toBe("3");
    expect(fact("Planning time")).toBe("0 ms");
    expect(fact("Execution time")).toBe("1.25 ms");
    expect(fact("Temp blocks read / written")).toBe("0 / 2");
    expect(screen.getAllByText("products_pkey")).toHaveLength(1);
  });

  it("does not infer an HNSW index or zero measurements from a Function Scan", () => {
    render(<QueryPlanSummary plan={[{ Plan: { "Node Type": "Function Scan" } }]} />);
    expect(fact("Shared buffer hits")).toBe("Not reported");
    expect(fact("Actual rows per loop")).toBe("Not reported");
    expect(fact("Execution time")).toBe("Not reported");
    expect(screen.getByText("No index name reported.")).toBeTruthy();
    expect(screen.getByText(/cannot establish which indexes/)).toBeTruthy();
  });

  it("keeps incomplete or malformed plan output inspectable without inventing a tree", () => {
    const view = render(<QueryPlanSummary plan={[]} />);
    expect(screen.getByText(/did not report a plan tree/)).toBeTruthy();
    view.rerender(<QueryPlanSummary plan={[{ Plan: [] }]} />);
    expect(screen.getByText(/did not report a plan tree/)).toBeTruthy();
    view.rerender(<QueryPlanSummary plan={[{ Plan: { "Node Type": "Result", Plans: [null, "bad"], "Actual Rows": "10" } }]} />);
    expect(fact("Actual rows per loop")).toBe("Not reported");
  });
});
