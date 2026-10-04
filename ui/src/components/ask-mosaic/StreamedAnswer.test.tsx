// @vitest-environment jsdom

import { act, cleanup, render, renderHook, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { AgentCitation } from "../../types";
import { StreamedAnswer } from "./StreamedAnswer";
import { TRAIL, settle, useSoftReveal } from "./softReveal";

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

function paragraph(container: HTMLElement) {
  return container.querySelector(".ask-prose") as HTMLElement;
}

describe("StreamedAnswer", () => {
  it("renders a settled answer as plain prose with citation chips", () => {
    const { container } = render(
      <StreamedAnswer text={TEXT} reveal={TEXT.length + TRAIL} citations={[citation(1), citation(2)]} answerId="a" />,
    );
    expect(container.querySelectorAll(".ask-fresh")).toHaveLength(0);
    const read = paragraph(container).textContent ?? "";
    expect(read).toContain("The chair is a strong fit for a long desk day 1.");
    expect(read).toContain("A reviewer felt relief on the first day 2.");
    expect(read).not.toContain("[");
    expect(screen.getByRole("link", { name: "Source 1" }).getAttribute("href")).toBe("#a-source-1");
    expect(screen.getByRole("link", { name: "Source 2" })).toBeTruthy();
  });

  it("leaves a bracketed number that names no citation as text", () => {
    const { container } = render(
      <StreamedAnswer text="It has 4 modes [7]." reveal={100} citations={[citation(1)]} answerId="a" />,
    );
    expect(paragraph(container).textContent).toContain("[7]");
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("draws only the newest characters faint, counted across paragraphs", () => {
    const shown = TEXT.length;
    const { container } = render(
      <StreamedAnswer text={TEXT} reveal={shown} citations={[citation(1), citation(2)]} answerId="a" />,
    );
    const fresh = [...container.querySelectorAll<HTMLElement>(".ask-fresh")];
    // The trail spans the paragraph break: it covers the end of the answer, not one paragraph.
    expect(fresh.length).toBeGreaterThan(0);
    expect(fresh.length).toBeLessThanOrEqual(TRAIL);
    const opacity = (node: HTMLElement) => Number.parseFloat(node.style.opacity);
    // Nothing is lighter than what arrived before it.
    for (let index = 1; index < fresh.length; index += 1) {
      expect(opacity(fresh[index])).toBeLessThanOrEqual(opacity(fresh[index - 1]));
    }
    expect(opacity(fresh[0])).toBeGreaterThan(opacity(fresh.at(-1) as HTMLElement));
    expect(paragraph(container).textContent).toContain("felt relief on the first day");
  });

  it("fades a citation chip with the characters around it", () => {
    const text = "Fits well [1]";
    render(<StreamedAnswer text={text} reveal={text.length} citations={[citation(1)]} answerId="a" />);
    expect(Number.parseFloat(screen.getByRole("link", { name: "Source 1" }).style.opacity)).toBeLessThan(1);
  });

  it("never darkens text it has not revealed yet", () => {
    expect(settle(0)).toBeLessThan(settle(TRAIL / 2));
    expect(settle(TRAIL)).toBe(1);
  });
});

describe("useSoftReveal", () => {
  it("shows a turn that mounted already answered whole, with nothing faint", () => {
    const { result } = renderHook(() => useSoftReveal(TEXT, false, true, false));
    expect(result.current).toEqual({ text: TEXT, reveal: TEXT.length + TRAIL, done: true });
  });

  it("shows everything at once under reduced motion, even mid-stream", () => {
    const { result } = renderHook(() => useSoftReveal(TEXT, true, true, true));
    expect(result.current.text).toBe(TEXT);
    expect(result.current.done).toBe(true);
  });

  it("shows nothing until the answer may appear", () => {
    const { result } = renderHook(() => useSoftReveal(TEXT, true, false, false));
    expect(result.current).toEqual({ text: "", reveal: 0, done: false });
  });

  it("holds the clock at the end of the text while the stream is open, then runs past it", async () => {
    const { result, rerender } = renderHook(
      ({ streaming }) => useSoftReveal(TEXT, streaming, true, false),
      { initialProps: { streaming: true } },
    );
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 500));
    });
    expect(result.current.text).toBe(TEXT);
    expect(result.current.reveal).toBe(TEXT.length);
    expect(result.current.done).toBe(false);

    rerender({ streaming: false });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 300));
    });
    expect(result.current.reveal).toBe(TEXT.length + TRAIL);
    expect(result.current.done).toBe(true);
  });

  it("does not cut an emphasized phrase in half", async () => {
    const bold = "Choose **the Steelcase Gesture** today.";
    const { result } = renderHook(() => useSoftReveal(bold, true, true, false));
    for (let step = 0; step < 8; step += 1) {
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 20));
      });
      expect((result.current.text.match(/\*\*/g) ?? []).length % 2).toBe(0);
    }
  });
});
