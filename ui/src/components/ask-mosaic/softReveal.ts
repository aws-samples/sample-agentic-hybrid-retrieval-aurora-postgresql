import { useEffect, useState } from "react";

/**
 * Characters over which a newly arrived character darkens to full ink.
 *
 * A character's age is how many characters arrived after it, counted across the
 * whole answer, so the trail crosses sentence, citation and paragraph breaks.
 * Age only grows, which is why nothing ever gets lighter once it is shown.
 */
export const TRAIL = 24;

const FAINTEST = 0.3;

/** 0 for the character that just arrived, 1 once it is fully inked. */
export function settle(age: number): number {
  return Math.min(1, (age + 1) / TRAIL);
}

/** Inline style for a character of the given age, built only from theme tokens. */
export function ageStyle(age: number): string {
  const t = settle(age);
  return `color:color-mix(in srgb, var(--ink) ${Math.round(t * 100)}%, var(--line-strong));`
    + `opacity:${(FAINTEST + (1 - FAINTEST) * t).toFixed(2)};`;
}

/**
 * Cuts the reveal back to the last point that renders cleanly as Markdown.
 *
 * A slice that stops between a bold marker and its close would paint literal
 * asterisks for a few frames. Holding the reveal just before the opener means
 * an emphasized phrase appears whole once its closing marker has streamed in.
 */
function balancedMarkdownSlice(text: string, length: number): string {
  if (length >= text.length) return text;
  const slice = text.slice(0, length);
  const boldMarks = slice.split("**").length - 1;
  if (boldMarks % 2 === 0) return slice;
  return slice.slice(0, slice.lastIndexOf("**"));
}

export interface SoftReveal {
  /** The prose shown so far, cut at a clean Markdown boundary. */
  text: string;
  /**
   * Characters revealed on the answer's clock. It runs `TRAIL` past the text's
   * end once the stream has closed, so the last characters finish darkening.
   */
  reveal: number;
  done: boolean;
}

/**
 * Paces streamed prose onto the page and reports the clock its ages are read
 * from.
 *
 * The service delivers the answer in chunks, and painting each chunk at once
 * makes the paragraph pop. This advances a few characters per animation frame
 * instead, faster with the backlog so it trails the stream by well under a
 * second. A turn that mounts already answered, or any turn under reduced
 * motion, shows everything at once with nothing faint.
 */
export function useSoftReveal(
  text: string,
  streaming: boolean,
  enabled: boolean,
  instant: boolean,
): SoftReveal {
  const [startedStreaming] = useState(streaming);
  const [reveal, setReveal] = useState(0);
  const pace = enabled && startedStreaming && !instant;
  const target = streaming ? text.length : text.length + TRAIL;
  const done = !pace || (!streaming && reveal >= target);

  useEffect(() => {
    if (done) return undefined;
    let frame = window.requestAnimationFrame(function step() {
      setReveal((current) => {
        const backlog = target - current;
        if (backlog <= 0) return current;
        if (backlog > 240) return current + 14;
        if (backlog > 60) return current + 8;
        return current + 3;
      });
      frame = window.requestAnimationFrame(step);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [done, target]);

  if (!enabled) return { text: "", reveal: 0, done: false };
  if (!pace) return { text, reveal: text.length + TRAIL, done: true };
  return {
    text: balancedMarkdownSlice(text, Math.min(reveal, text.length)),
    reveal: Math.min(reveal, target),
    done,
  };
}
