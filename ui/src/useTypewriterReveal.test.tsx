// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { expect, it } from "vitest";
import { useTypewriterReveal } from "./useTypewriterReveal";

it("skips to the full text on request and stays whole as more text streams in", () => {
  const long = "word ".repeat(200).trim();
  const { result, rerender } = renderHook(
    ({ text }: { text: string }) => useTypewriterReveal(text, true, true, false),
    { initialProps: { text: long } },
  );
  expect(result.current.done).toBe(false);
  expect(result.current.text.length).toBeLessThan(long.length);
  act(() => result.current.skip());
  expect(result.current.done).toBe(true);
  expect(result.current.text).toBe(long);
  rerender({ text: `${long} more words` });
  expect(result.current.text).toBe(`${long} more words`);
  expect(result.current.done).toBe(true);
});
