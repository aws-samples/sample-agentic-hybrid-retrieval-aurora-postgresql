// @vitest-environment jsdom

import { act, cleanup, render, renderHook, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { AgentCitation } from "../../types";
import { StreamedAnswer } from "./StreamedAnswer";
import { chunkEnd, earned, useSoftReveal } from "./softReveal";

afterEach(cleanup);

const citation = (number: number): AgentCitation => ({
  number,
  evidence_id: 9000 + number,
  evidence_type: "product_spec",
  product_id: 1,
  source_uri: "mosaic://x",
  revision: "r1",
  title: "t",
  quote: "q",
});

const TEXT = "The chair is a strong fit for a long desk day [1].\n\nA reviewer felt relief on the first day [2].";
const SECOND_PARAGRAPH = TEXT.indexOf("A reviewer");

function prose(container: HTMLElement) {
  return container.querySelector(".ask-prose") as HTMLElement;
}

const wait = (ms: number) => act(async () => {
  await new Promise((resolve) => setTimeout(resolve, ms));
});

describe("StreamedAnswer", () => {
  it("renders an answer that was never paced as plain prose with citation chips", () => {
    const { container } = render(
      <StreamedAnswer text={TEXT} chunks={[]} citations={[citation(1), citation(2)]} answerId="a" />,
    );
    expect(container.querySelectorAll(".reveal-chunk")).toHaveLength(0);
    const read = prose(container).textContent ?? "";
    expect(read).toContain("The chair is a strong fit for a long desk day 1.");
    expect(read).toContain("A reviewer felt relief on the first day 2.");
    expect(read).not.toContain("[");
    expect(screen.getByRole("link", { name: "Source 1" }).getAttribute("href")).toBe("#a-source-1");
    expect(screen.getByRole("link", { name: "Source 2" })).toBeTruthy();
  });

  it("leaves a bracketed number that names no citation as text", () => {
    const { container } = render(
      <StreamedAnswer text="It has 4 modes [7]." chunks={[0]} citations={[citation(1)]} answerId="a" />,
    );
    expect(prose(container).textContent).toContain("[7]");
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("splits the prose where each chunk starts, across paragraphs, without changing the words", () => {
    const chunks = [0, 4, 10, SECOND_PARAGRAPH, SECOND_PARAGRAPH + 11];
    const { container } = render(
      <StreamedAnswer text={TEXT} chunks={chunks} citations={[citation(1), citation(2)]} answerId="a" />,
    );
    const pieces = [...container.querySelectorAll<HTMLElement>("span.reveal-chunk")].map((node) => node.textContent);
    expect(pieces.slice(0, 3)).toEqual(["The ", "chair ", "is a strong fit for a long desk day "]);
    expect(pieces).toContain("A reviewer ");
    expect(prose(container).textContent).toContain("A reviewer felt relief on the first day 2.");
    expect(screen.getByRole("link", { name: "Source 1" }).classList.contains("reveal-chunk")).toBe(true);
  });

  it("keeps every earlier chunk's element when the next chunk arrives, so only the new one fades in", () => {
    const first = "Choose the Steelcase ";
    const { container, rerender } = render(
      <StreamedAnswer text={first} chunks={[0, 7]} citations={[]} answerId="a" />,
    );
    const before = [...container.querySelectorAll("span.reveal-chunk")];
    rerender(<StreamedAnswer text={`${first}Gesture today.`} chunks={[0, 7, first.length]} citations={[]} answerId="a" />);
    const after = [...container.querySelectorAll("span.reveal-chunk")];
    expect(after).toHaveLength(3);
    expect(after[0]).toBe(before[0]);
    expect(after[1]).toBe(before[1]);
    expect(after[2].textContent).toBe("Gesture today.");
  });

  it("keeps a citation chip's element as later chunks arrive, so its fade can finish", () => {
    const first = "Fits well [1]. ";
    const { rerender } = render(
      <StreamedAnswer text={first} chunks={[0, 5]} citations={[citation(1)]} answerId="a" />,
    );
    const chip = screen.getByRole("link", { name: "Source 1" });
    rerender(<StreamedAnswer text={`${first}It also folds.`} chunks={[0, 5, first.length]} citations={[citation(1)]} answerId="a" />);
    expect(screen.getByRole("link", { name: "Source 1" })).toBe(chip);
  });
});

describe("chunkEnd", () => {
  it("finishes the word a chunk lands in, with its trailing space", () => {
    expect(chunkEnd("The chair is a strong fit", 0, 1)).toBe(4);
    expect(chunkEnd("The chair is a strong fit", 4, 2)).toBe(10);
  });

  it("cuts a word longer than its reach where it landed", () => {
    const text = `a ${"x".repeat(40)} end`;
    expect(chunkEnd(text, 0, 3)).toBe(3);
  });

  it("never runs past the text", () => {
    expect(chunkEnd("day [1].", 4, 50)).toBe(8);
  });

  it("takes a short tail with no space after it whole, so a closing citation is not split", () => {
    expect(chunkEnd("the first day [2].", 15, 1)).toBe(18);
  });
});

describe("earned", () => {
  it("earns about 50 characters a second once the reveal has caught up", () => {
    expect(earned(20, 0)).toBeCloseTo(1, 5);
    expect(earned(20, 10)).toBeCloseTo(1, 5);
  });

  it("speeds up with the backlog, so a burst is read out rather than dumped", () => {
    expect(earned(16, 1800)).toBeGreaterThan(earned(16, 90) * 10);
  });

  it("counts elapsed time, not frames: two 120 Hz frames earn what one 60 Hz frame does", () => {
    expect(earned(1000 / 120, 600) * 2).toBeCloseTo(earned(1000 / 60, 600), 5);
  });

  it("caps a long frame, so a tab returning from the background does not dump the answer", () => {
    expect(earned(5000, 1800)).toBe(earned(64, 1800));
  });
});

describe("useSoftReveal", () => {
  it("shows a turn that mounted already answered whole, with no chunks", () => {
    const { result } = renderHook(() => useSoftReveal(TEXT, false, true, false));
    expect(result.current).toEqual({ text: TEXT, chunks: [], done: true });
  });

  it("shows everything at once under reduced motion, even mid-stream", () => {
    const { result } = renderHook(() => useSoftReveal(TEXT, true, true, true));
    expect(result.current.text).toBe(TEXT);
    expect(result.current.chunks).toEqual([]);
    expect(result.current.done).toBe(true);
  });

  it("shows nothing until the answer may appear", () => {
    const { result } = renderHook(() => useSoftReveal(TEXT, true, false, false));
    expect(result.current).toEqual({ text: "", chunks: [], done: false });
  });

  it("reads the stream out in whole words, then finishes once the stream closes", async () => {
    const { result, rerender } = renderHook(
      ({ streaming }) => useSoftReveal(TEXT, streaming, true, false),
      { initialProps: { streaming: true } },
    );
    await wait(100);
    expect(result.current.text.length).toBeGreaterThan(0);
    expect(result.current.text.length).toBeLessThan(TEXT.length);
    await wait(1500);
    expect(result.current.text).toBe(TEXT);
    expect(result.current.done).toBe(false);
    const { chunks } = result.current;
    expect(chunks[0]).toBe(0);
    for (const start of chunks.slice(1)) expect(TEXT[start - 1]).toMatch(/\s/);

    rerender({ streaming: false });
    expect(result.current.done).toBe(true);
  });

  it("does not cut an emphasized phrase in half", async () => {
    const bold = "Choose **the Steelcase Gesture** today.";
    const { result } = renderHook(() => useSoftReveal(bold, true, true, false));
    for (let step = 0; step < 8; step += 1) {
      await wait(20);
      expect((result.current.text.match(/\*\*/g) ?? []).length % 2).toBe(0);
    }
  });
});
