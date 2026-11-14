// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { coreMosaicLabs } from "../labMissions";
import { LabFaultCard, idDifference, trigrams } from "./LabFaultCard";

vi.mock("../api", () => ({ api: { product: vi.fn() } }));
afterEach(cleanup);

const mission = coreMosaicLabs.find((item) => item.stage === "retrieve")!;
const LISTING = "B0C2WWCFQB";

beforeEach(() => {
  vi.mocked(api.product).mockReset().mockResolvedValue({ title: "Logitech Zone 900", sku: LISTING } as never);
});

function card(state: "broken" | "fixed") {
  return render(<LabFaultCard
    mission={mission} labNumber={1} state={state} targetPresent={state === "fixed"}
    detail="Every product shown still fits Alex's request and filters." finalRank={state === "fixed" ? 1 : null}
    playgroundHref="/labs/retrieval" onSearchAgain={() => {}}
  />);
}

describe("trigrams", () => {
  it("pads each word as pg_trgm's show_trgm does", () => {
    expect([...trigrams("cat")]).toEqual(["  c", " ca", "cat", "at "]);
    expect(trigrams("WH-C720").has("  c")).toBe(true);
  });
});

describe("idDifference", () => {
  it("names Alex's swap and the pieces fuzzy matching still shares", () => {
    expect(mission.query).toBe("B0C2WWFCQB");
    expect(idDifference(mission.query, LISTING)).toBe(
      "Two adjacent letters are swapped. Full-text search matches whole words, so it cannot find this ID. "
      + "Fuzzy matching compares three-letter pieces, and 7 of 11 still match.",
    );
  });

  it("counts characters when the IDs differ by more than a swap", () => {
    expect(idDifference("B0C2WWXXQB", LISTING)).toMatch(/^2 characters differ\./);
  });
});

describe("LabFaultCard", () => {
  it("opens the two IDs on the card once the repair is verified", async () => {
    card("fixed");
    const open = await screen.findByText(/Two adjacent letters are swapped/);
    const panel = open.closest(".shop-fault-ids-open")!;
    expect(panel.closest("details")).toBeNull();
    expect(panel.querySelectorAll("mark")).toHaveLength(4);
  });

  it("keeps the IDs inside the evidence panel, without the explanation, while the lab is broken", async () => {
    card("broken");
    await screen.findByText("Alex typed");
    expect(screen.getByText("Alex typed").closest("details")).not.toBeNull();
    expect(screen.queryByText(/Two adjacent letters are swapped/)).toBeNull();
  });
});
